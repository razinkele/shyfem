# Depth Preview Before Accept — Design

**Date:** 2026-03-03
**Feature:** Staged interpolation with method comparison, depth adjustments, and explicit Accept step in Mesh Builder Step 4.

---

## Goal

Allow users to explore interpolated bathymetry depth values — compare methods, adjust clamping/fill — before committing them into the GRD file.

## Problem with Current Flow

Clicking "Interpolate Bathymetry" immediately sets `final_grd`, which flows into the Export step. There is no way to review, adjust, or compare without already having committed the result. The user cannot try RBF, inspect it, try Linear, and pick the better one before accepting.

## Architecture

### New reactive state

| Value | Type | Purpose |
|---|---|---|
| `staged_grd` | `reactive.value(None)` | Holds the most recent interpolation result (not yet accepted) |
| `comparison_runs` | `reactive.value({})` | Dict of `{method_label: GrdFile}`, max 3 entries |

`final_grd` is **only** set when the user clicks **"Accept depths"**.
`preview_grd` is driven by `staged_grd` (or whichever comparison run is selected via radio).

### Data flow

```
Interpolate → staged_grd + comparison_runs → preview_grd (map)
                                                    ↓
                           [optional] Apply adjustments → staged_grd (updated)
                                                    ↓
                              Accept depths → final_grd → Export step
```

---

## Step 4 UI Changes

The existing upload, source type, method select, and stats panels are unchanged.

### New sections shown after first successful interpolation

**1. Comparison selector** (only when ≥2 runs exist)
- Radio buttons, one per stored run, label = `"{method} (min: X.X, max: Y.Y m)"`
- Switching selection updates `staged_grd` and `preview_grd` (map re-renders)
- Max 3 entries; oldest replaced when a 4th run is added

**2. Depth adjustments** (always shown after first interpolation)
- *Clamp min depth* — numeric input, optional — nodes shallower than this are clamped
- *Clamp max depth* — numeric input, optional — nodes deeper than this are clamped
- *Fill unmapped nodes* — checkbox + numeric fill value — nodes with no depth receive a constant
- **"Apply adjustments"** button — calls `adjust_depths()`, updates `staged_grd` and map

**3. Accept depths** button
- Replaces the old "Next: Interpolate Bathymetry → Export" flow
- Disabled when `staged_grd` is None
- On click: `final_grd.set(staged_grd.get())`, navigates to Step 5 Export

---

## New Service Function

```python
def adjust_depths(
    grd: GrdFile,
    min_clamp: float | None = None,
    max_clamp: float | None = None,
    fill_value: float | None = None,
) -> GrdFile:
    """Return a new GrdFile with depth values adjusted.

    - min_clamp: nodes with depth < min_clamp are set to min_clamp
    - max_clamp: nodes with depth > max_clamp are set to max_clamp
    - fill_value: nodes where depth is None receive this value
    Each parameter is independent; all are optional.
    """
```

Pure function, returns a new GrdFile (does not mutate input).

---

## Files to Change

| File | Change |
|---|---|
| `shyfem_ui/services/mesh_builder.py` | Add `adjust_depths()` pure function |
| `shyfem_ui/pages/mesh_builder.py` | Add `staged_grd`, `comparison_runs` state; update `_on_interpolate`; add comparison selector, adjustment controls, Accept button; update `_step_bathy_panel()` |
| `tests/test_mesh_builder.py` | 5 unit tests for `adjust_depths()` |

---

## Tests

```python
# test_adjust_depths.py (in test_mesh_builder.py)
test_min_clamp          # nodes shallower than min are raised to min
test_max_clamp          # nodes deeper than max are clamped to max
test_fill_unmapped      # None-depth nodes receive fill_value
test_combined           # min_clamp + max_clamp + fill together
test_no_op              # no params → returns identical depths
```

---

## Constraints

- Max 3 comparison runs stored (YAGNI — more than 3 adds confusion)
- Adjustments operate on `staged_grd`, not on the raw interpolation cache — re-running the same method resets adjustments
- No histogram (not requested)
- No per-node manual editing (not requested)
