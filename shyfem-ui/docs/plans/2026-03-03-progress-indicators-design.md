# Progress Indicators — Design

**Date:** 2026-03-03
**Feature:** Bootstrap progress bars for mesh generation (Step 3) and bathymetry interpolation (Step 4).

---

## Goal

Give users live feedback during long-running operations so they can see that work is happening and roughly how far along it is.

## Constraints

- `triangulate()` is a single atomic C call (Triangle library) — no internal hooks possible → indeterminate bar
- `interpolate_bathymetry_scipy` scipy calls are vectorized/atomic → can only show phase labels, not sample-by-sample progress
- Node-assignment loop (`_build_grd_from_depths`) is pure Python → can yield every N nodes for smooth 10→100% progress
- All reactive-value updates must happen from the async Shiny event loop, not from worker threads

---

## New Reactive State

| Value | Type | Purpose |
|---|---|---|
| `progress_value` | `reactive.value(0)` | 0–100 = percent; -1 = indeterminate (animated stripe) |
| `progress_label` | `reactive.value("")` | Non-empty = bar shown; empty = bar hidden |

---

## UI

Add `ui.output_ui("operation_progress")` in the static `mesh_builder_ui()` between `status_summary` and the wizard navset.

`@render.ui operation_progress` renders:
- `ui.div()` (empty) when `progress_label` is `""`
- Bootstrap indeterminate bar when `progress_value == -1`:
  ```html
  <div class="progress mb-2">
    <div class="progress-bar progress-bar-striped progress-bar-animated"
         role="progressbar" style="width:100%">
      {progress_label}
    </div>
  </div>
  ```
- Bootstrap determinate bar otherwise:
  ```html
  <div class="progress mb-2">
    <div class="progress-bar" role="progressbar"
         style="width:{pct}%" aria-valuenow="{pct}" aria-valuemin="0" aria-valuemax="100">
      {progress_label} ({pct}%)
    </div>
  </div>
  ```

---

## Mesh Generation (Step 3)

`_on_generate_mesh` sets an indeterminate bar before entering the thread:

```
progress_value = -1
progress_label = "Generating mesh  (~5,000 elements estimated)…"
```

Cleared in `finally` block alongside `busy_message`.

---

## Interpolation (Step 4)

### Service refactor

Extract the pure-computation part of `interpolate_bathymetry_scipy` into a new internal function `_compute_depths_only(grd, bathy_points, method) -> tuple[list[int], np.ndarray]` returning `(node_ids, depths_array)`. This runs in a worker thread.

The existing `interpolate_bathymetry_scipy` keeps its signature unchanged — it calls `_compute_depths_only` internally and then calls `_build_grd_from_depths`. No callers break.

Add a module-level helper `_build_grd_from_depths(grd, node_ids, depths) -> GrdFile` that does the node-assignment loop. This is a pure function (no Shiny coupling) and can be called from both the service (unchanged) and the page (for chunked progress).

### Page orchestration

`_on_interpolate` uses phase-based progress between async yields:

| Phase | progress_value | progress_label |
|---|---|---|
| Setup | 5 | `"Preparing {N} bathymetry points…"` |
| Computing | 10 | `"Running {method} on {N} nodes…"` |
| (thread runs) | 10 | (unchanged — thread can't update reactives) |
| Assigning | 10→100 | `"Assigning depths… {done:,} / {total:,} nodes ({pct}%)"` |

Node assignment is done in the async handler in chunks of 500, with `await asyncio.sleep(0)` between chunks.

---

## Files to Change

| File | Change |
|---|---|
| `shyfem_ui/pages/mesh_builder.py` | Add `operation_progress` output_ui to static UI; add `progress_value`/`progress_label` state; add `operation_progress` render; update `_on_generate_mesh`; update `_on_interpolate` |
| `shyfem_ui/services/mesh_builder.py` | Extract `_compute_depths_only()` and `_build_grd_from_depths()` internal helpers |

---

## No New Tests

The service public API (`interpolate_bathymetry_scipy`) is unchanged. Progress logic lives entirely in the page server and is not unit-testable without Shiny runtime. The existing `TestAdjustDepths` and interpolation tests continue to pass.
