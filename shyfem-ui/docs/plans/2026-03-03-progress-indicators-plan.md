# Progress Indicators Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show a Bootstrap progress bar during mesh generation (indeterminate) and bathymetry interpolation (phase-based with real % on node assignment).

**Architecture:** Two new reactive values (`progress_value`, `progress_label`) drive a new `operation_progress` output_ui. The service is refactored to expose `_compute_depths_only()` (runs in thread) and `_build_grd_from_depths()` (pure, called from async page handler in chunks for smooth progress). Mesh gen uses an animated striped bar; interpolation walks through 3 labeled phases.

**Tech Stack:** Shiny for Python, Bootstrap 5 progress bar HTML, asyncio.

---

## Task 1: Service refactor — extract `_compute_depths_only` and `_build_grd_from_depths`

**Files:**
- Modify: `shyfem_ui/services/mesh_builder.py:786-850`

No new tests needed — the public function `interpolate_bathymetry_scipy` keeps its exact signature and behavior. After the refactor the existing test suite must still pass (all 85 tests).

---

### Step 1: Add `_compute_depths_only` before `_idw_interpolate` (around line 852)

In `shyfem_ui/services/mesh_builder.py`, find the block starting at line 786 (`interpolate_bathymetry_scipy`). You will split it into three functions. First, insert `_compute_depths_only` and `_build_grd_from_depths` **before** `_idw_interpolate` (which currently starts at line 853).

Insert this block between line 851 (blank after `interpolate_bathymetry_scipy`) and line 853 (`def _idw_interpolate`):

```python
def _compute_depths_only(
    grd: GrdFile,
    bathy_points: np.ndarray,
    method: str,
    use_boundary_zero: bool = False,
) -> tuple[list[int], np.ndarray]:
    """Compute interpolated depth values for all mesh nodes.

    Runs entirely as a pure computation — no Shiny state. Intended to be
    called via ``asyncio.to_thread`` from the page handler.

    Returns:
        Tuple of (node_ids, depths) where depths[i] is the depth for node_ids[i].
    """
    if len(bathy_points) == 0:
        raise ValueError("No bathymetry points provided")

    if use_boundary_zero:
        zero_pts = extract_boundary_zero_points(grd)
        if len(zero_pts) > 0:
            bathy_points = np.vstack([zero_pts, bathy_points])
            logger.info(
                "Injected %d boundary-zero points (total: %d)",
                len(zero_pts), len(bathy_points),
            )

    bathy_xy = bathy_points[:, :2]
    bathy_z = bathy_points[:, 2]

    node_ids = sorted(grd.nodes.keys())
    mesh_xy = np.array([[grd.nodes[nid].x, grd.nodes[nid].y] for nid in node_ids])

    if method == "idw":
        depths = _idw_interpolate(bathy_xy, bathy_z, mesh_xy, k=8, power=2.0)
    elif method in ("nearest", "linear", "cubic"):
        depths = griddata(bathy_xy, bathy_z, mesh_xy, method=method)
        if np.any(np.isnan(depths)):
            nearest = griddata(bathy_xy, bathy_z, mesh_xy, method="nearest")
            depths = np.where(np.isnan(depths), nearest, depths)
    elif method == "rbf":
        depths = _rbf_interpolate(bathy_xy, bathy_z, mesh_xy)
    elif method == "cloughtocher":
        depths = _cloughtocher_interpolate(bathy_xy, bathy_z, mesh_xy)
    else:
        raise ValueError(f"Unknown interpolation method: {method}")

    return node_ids, depths


def _build_grd_from_depths(
    grd: GrdFile, node_ids: list[int], depths: np.ndarray
) -> GrdFile:
    """Build a new GrdFile from precomputed depth values.

    Args:
        grd: Original mesh (elements and lines are shallow-copied).
        node_ids: Ordered list of node IDs matching the depths array.
        depths: 1-D array of float depth values, one per node_id.

    Returns:
        New GrdFile with depth set on all nodes.
    """
    new_grd = GrdFile()
    for i, nid in enumerate(node_ids):
        node = grd.nodes[nid]
        new_grd.nodes[nid] = Node(
            id=nid, node_type=node.node_type, x=node.x, y=node.y,
            depth=float(depths[i]),
        )
    new_grd.elements = dict(grd.elements)
    new_grd.lines = dict(grd.lines)
    return new_grd

```

### Step 2: Simplify `interpolate_bathymetry_scipy` to call the new helpers

Replace the body of `interpolate_bathymetry_scipy` (lines 806-850) so it delegates to the two new helpers:

**Old body (lines 806-850):**
```python
    if len(bathy_points) == 0:
        raise ValueError("No bathymetry points provided")

    # Optionally prepend boundary=0 points
    if use_boundary_zero:
        zero_pts = extract_boundary_zero_points(grd)
        if len(zero_pts) > 0:
            bathy_points = np.vstack([zero_pts, bathy_points])
            logger.info(
                "Injected %d boundary-zero points (total: %d)",
                len(zero_pts), len(bathy_points),
            )

    bathy_xy = bathy_points[:, :2]
    bathy_z = bathy_points[:, 2]

    node_ids = sorted(grd.nodes.keys())
    mesh_xy = np.array([[grd.nodes[nid].x, grd.nodes[nid].y] for nid in node_ids])

    if method == "idw":
        depths = _idw_interpolate(bathy_xy, bathy_z, mesh_xy, k=8, power=2.0)
    elif method in ("nearest", "linear", "cubic"):
        depths = griddata(bathy_xy, bathy_z, mesh_xy, method=method)
        # Fill NaN with nearest for edge nodes
        if np.any(np.isnan(depths)):
            nearest = griddata(bathy_xy, bathy_z, mesh_xy, method="nearest")
            depths = np.where(np.isnan(depths), nearest, depths)
    elif method == "rbf":
        depths = _rbf_interpolate(bathy_xy, bathy_z, mesh_xy)
    elif method == "cloughtocher":
        depths = _cloughtocher_interpolate(bathy_xy, bathy_z, mesh_xy)
    else:
        raise ValueError(f"Unknown interpolation method: {method}")

    # Build new GrdFile with depths
    new_grd = GrdFile()
    for i, nid in enumerate(node_ids):
        node = grd.nodes[nid]
        new_grd.nodes[nid] = Node(
            id=nid, node_type=node.node_type, x=node.x, y=node.y,
            depth=float(depths[i]),
        )
    new_grd.elements = dict(grd.elements)
    new_grd.lines = dict(grd.lines)
    return new_grd
```

**New body:**
```python
    node_ids, depths = _compute_depths_only(grd, bathy_points, method, use_boundary_zero)
    return _build_grd_from_depths(grd, node_ids, depths)
```

### Step 3: Run the full test suite to confirm no regressions

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q --tb=short
```

Expected: 85 passed, 0 failed.

### Step 4: Verify import check

```bash
/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.services.mesh_builder import _compute_depths_only, _build_grd_from_depths, interpolate_bathymetry_scipy; print('OK')"
```

Expected: `OK`

### Step 5: Commit

```bash
git add shyfem_ui/services/mesh_builder.py
git commit -m "refactor(ui): extract _compute_depths_only and _build_grd_from_depths helpers"
```

---

## Task 2: Add progress state, output_ui placeholder, and render function

**Files:**
- Modify: `shyfem_ui/pages/mesh_builder.py`

No tests — UI render functions require Shiny runtime.

---

### Step 1: Update page-level imports

In `shyfem_ui/pages/mesh_builder.py`, line 13, the import from `mesh_builder` service currently starts with:
```python
from shyfem_ui.services.mesh_builder import (
    adjust_depths,
    compute_mesh_stats,
```

Add `_compute_depths_only,` as a new first entry:
```python
from shyfem_ui.services.mesh_builder import (
    _compute_depths_only,
    adjust_depths,
    compute_mesh_stats,
```

Also, line 27 currently reads:
```python
from shyfem_ui.services.parser_grd import GrdParser
```

Extend it to import `GrdFile` and `Node` as well:
```python
from shyfem_ui.services.parser_grd import GrdFile, GrdParser, Node
```

### Step 2: Add `operation_progress` to the static UI

In `mesh_builder_ui()` (around line 295), the current layout is:
```python
        # Status bar
        ui.output_ui("status_summary"),
        # Main content area — tabs for wizard / preview / log
        ui.navset_card_tab(
```

Add `ui.output_ui("operation_progress")` between them:
```python
        # Status bar
        ui.output_ui("status_summary"),
        ui.output_ui("operation_progress"),
        # Main content area — tabs for wizard / preview / log
        ui.navset_card_tab(
```

### Step 3: Add two reactive state values

In `mesh_builder_server`, the state block ends around line 353 with:
```python
    comparison_runs = reactive.value({})  # {label: GrdFile}, max 3 entries
```

Add immediately after:
```python
    progress_value = reactive.value(0)   # 0-100 = percent; -1 = indeterminate
    progress_label = reactive.value("")  # empty = bar hidden
```

### Step 4: Add `operation_progress` render function

Find the `status_summary` `@render.ui` function (around line 411). Insert the following new render function **immediately before** it:

```python
    @render.ui
    def operation_progress():
        """Bootstrap progress bar shown during mesh gen and interpolation."""
        label = progress_label.get()
        if not label:
            return ui.div()
        pct = progress_value.get()
        if pct == -1:
            return ui.div(
                ui.tags.div(
                    ui.tags.div(
                        label,
                        class_="progress-bar progress-bar-striped progress-bar-animated",
                        role="progressbar",
                        style="width: 100%",
                    ),
                    class_="progress mb-2",
                ),
            )
        return ui.div(
            ui.tags.div(
                ui.tags.div(
                    f"{label} ({pct}%)",
                    class_="progress-bar",
                    role="progressbar",
                    style=f"width: {pct}%",
                    aria_valuenow=str(pct),
                    aria_valuemin="0",
                    aria_valuemax="100",
                ),
                class_="progress mb-2",
            ),
        )

```

### Step 5: Verify import check

```bash
/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.mesh_builder import mesh_builder_ui, mesh_builder_server; print('OK')"
```

Expected: `OK`

### Step 6: Commit

```bash
git add shyfem_ui/pages/mesh_builder.py
git commit -m "feat(ui): add operation_progress output_ui and progress reactive state"
```

---

## Task 3: Update `_on_generate_mesh` with indeterminate progress bar

**Files:**
- Modify: `shyfem_ui/pages/mesh_builder.py:706-745`

---

### Step 1: Update the pre-thread setup block (around line 726-728)

**Old:**
```python
        _log(f"Generating mesh: method={method}, max_area={eff_area}, min_angle={eff_angle} deg...")
        busy_message.set("Generating mesh — this may take a moment for large boundaries...")
        await asyncio.sleep(0)  # yield so Shiny flushes the spinner to the browser
```

**New:**
```python
        _log(f"Generating mesh: method={method}, max_area={eff_area}, min_angle={eff_angle} deg...")
        busy_message.set("Generating mesh…")
        estimate = estimate_element_count(grd, eff_area) if eff_area else 0
        est_label = f" (~{estimate:,} elements estimated)" if estimate else ""
        progress_label.set(f"Generating mesh{est_label}…")
        progress_value.set(-1)
        await asyncio.sleep(0)  # yield so Shiny flushes the bar to the browser
```

### Step 2: Clear progress in the `finally` block (around line 744-745)

**Old:**
```python
        finally:
            busy_message.set("")
```

**New:**
```python
        finally:
            busy_message.set("")
            progress_label.set("")
            progress_value.set(0)
```

### Step 3: Verify import check

```bash
/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.mesh_builder import mesh_builder_ui, mesh_builder_server; print('OK')"
```

Expected: `OK`

### Step 4: Commit

```bash
git add shyfem_ui/pages/mesh_builder.py
git commit -m "feat(ui): indeterminate progress bar for mesh generation (Step 3)"
```

---

## Task 4: Update `_on_interpolate` with phase-based progress

**Files:**
- Modify: `shyfem_ui/pages/mesh_builder.py:920-965`

---

### Step 1: Replace the scipy branch in `_on_interpolate`

The `else` branch in `_on_interpolate` currently reads (around line 939-943):
```python
            else:
                result_grd = await asyncio.to_thread(
                    interpolate_bathymetry_scipy,
                    grd, data, method=method, use_boundary_zero=boundary_zero,
                )
```

Replace it with the three-phase orchestration:
```python
            else:
                n_bathy = len(data)
                n_nodes = len(grd.nodes)
                # Phase 1: setup
                progress_value.set(5)
                progress_label.set(f"Preparing {n_bathy:,} bathymetry points…")
                await asyncio.sleep(0)
                # Phase 2: scipy model + evaluation in thread
                progress_value.set(10)
                progress_label.set(f"Running {method} on {n_nodes:,} nodes…")
                await asyncio.sleep(0)
                node_ids, depths = await asyncio.to_thread(
                    _compute_depths_only, grd, data, method, boundary_zero,
                )
                # Phase 3: assign depths in async chunks for smooth progress
                new_grd = GrdFile()
                chunk = 500
                for start in range(0, n_nodes, chunk):
                    end = min(start + chunk, n_nodes)
                    for i in range(start, end):
                        nid = node_ids[i]
                        node = grd.nodes[nid]
                        new_grd.nodes[nid] = Node(
                            id=nid, node_type=node.node_type,
                            x=node.x, y=node.y,
                            depth=float(depths[i]),
                        )
                    pct = min(99, 10 + int(end / n_nodes * 90))
                    progress_value.set(pct)
                    progress_label.set(
                        f"Assigning depths… {end:,} / {n_nodes:,} nodes"
                    )
                    await asyncio.sleep(0)
                new_grd.elements = dict(grd.elements)
                new_grd.lines = dict(grd.lines)
                result_grd = new_grd
```

### Step 2: Clear progress in the `finally` block

The `finally` block currently reads (around line 961-962):
```python
        finally:
            busy_message.set("")
```

**New:**
```python
        finally:
            busy_message.set("")
            progress_label.set("")
            progress_value.set(0)
```

### Step 3: Verify import check

```bash
/opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.mesh_builder import mesh_builder_ui, mesh_builder_server; print('OK')"
```

Expected: `OK`

### Step 4: Run full test suite

```bash
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q --tb=short
```

Expected: 85 passed, 0 failed.

### Step 5: Commit

```bash
git add shyfem_ui/pages/mesh_builder.py
git commit -m "feat(ui): phase-based progress bar for bathymetry interpolation (Step 4)"
```

---

## Manual Smoke Test (after all tasks)

1. Open Mesh Builder, complete Steps 1–2 (import and refine boundary)
2. **Step 3 mesh gen:** Click "Generate Mesh"
   - Expect: animated striped bar appears with label like "Generating mesh (~3,200 elements estimated)…"
   - Expect: bar disappears when done, stats show
3. **Step 4 interpolation — small mesh:** Upload bathymetry, click "Interpolate Bathymetry" with method = "linear"
   - Expect: bar goes through "Preparing…" → "Running linear…" → "Assigning depths… N / N nodes" → disappears
4. **Step 4 interpolation — shybas method:** Click "Interpolate Bathymetry" with method = "shybas"
   - Expect: existing `busy_message` spinner only (shybas path is unchanged — no progress bar, just the text spinner)
5. Verify map updates after each operation
