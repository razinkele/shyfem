# Mesh Creation — Input Validation Hardening Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the validation gaps surfaced by the 2026-04-28 audit of the mesh-creation pipeline so users cannot proceed past obviously broken input, and so a non-UI caller of the service layer cannot trigger Triangle hangs or OOM.

**Architecture:** Each task is a small, isolated validator added either as a pure function in `services/mesh_builder.py` (unit-testable) or as an inline check in `pages/mesh_builder.py` reactive effects. We follow the existing convention: validators that block return `(ok, reason)` tuples or raise `ValueError`; advisory validators return `str | None`. No new modules, no API breaks. The eight tasks are largely independent and can be merged in any order, with two intra-phase placement dependencies: Task 4 inserts its helper "after `warn_if_min_geq_max_area`" (added in Task 3), and Task 6 inserts its helpers "after `check_bathy_extent`" (added in Task 5) — if the referenced helper isn't present yet, the agent should pick a sensible nearby insertion point and proceed (no functional blocker). Tasks 1–4 land the highest-leverage bug-prevention and should go first.

**Tech Stack:** Python 3.13, Shiny for Python, NumPy, Shapely. Test runner: `/opt/micromamba/envs/shiny/bin/python -m pytest` from `shyfem-ui/`.

---

## Findings Being Fixed

| # | Severity | Finding | Task |
|---|----------|---------|------|
| 1 | HIGH | `validate_boundary` ERROR-prefixed issues are surfaced as styled alerts but do not block "Generate Mesh" — degenerate boundaries reach Triangle | 1 |
| 2 | HIGH | Self-intersecting boundary is reported as WARNING-only; Triangle on self-intersecting PSLG can hang or segfault | 1 |
| 3 | MED  | `triangulate()` accepts `min_angle > 34` (Triangle hangs) and `max_area <= 0` (no-op); only the UI slider enforces bounds | 2 |
| 4 | MED  | `min_area >= max_area` is not flagged in the UI; post-flight will report the entire mesh as slivers | 3 |
| 5 | MED  | `delaunay_minimal` + `Max Elements` cap: pre-flight estimate is 0 (no `max_area`), so the cap is silently inert. Existing warning only fires for the quality method. | 4 |
| 6 | MED  | XYZ bathymetry has no CRS metadata; mesh is reprojected to WGS84 on import — silent misalignment if user supplies UTM-coord XYZ | 5 |
| 7 | LOW  | Bathymetry upload silently accepts all-zero / all-NaN / single-value depth files; user only finds out after interpolation | 6 |
| 8 | LOW  | `_prepare_upload_files` falls back to `files[0]["name"]` for unrecognized extensions — fiona then raises a cryptic error | 7 |

**Out of scope (deferred to follow-up):**
- Slider unit-ambiguity for `reduce_tolerance` (0–1000 in coordinate units, meaningless after WGS84 reprojection) and `contour_sample_dist` (no cap on resulting point count). Both require UX rework (dynamic labels or percent-of-extent semantics) beyond pure validation. Tracked in `docs/followups/2026-04-28-mesh-slider-units.md` (created by Task 8).
- Chaikin smoothing output-size cap (5 iterations on a 10k-point boundary → 320k points). Same UX-redesign character.
- Server-level upload size limits — environmental, not application.

---

## Phase A — Fail-Closed Gate (highest leverage)

### Task 1: Block mesh generation on broken boundaries

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py` — add `_check_boundary_gates`
- Modify: `shyfem-ui/shyfem_ui/pages/mesh_builder.py` — call the gate at the top of `_on_generate_mesh`
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — add `TestCheckBoundaryGates`

**Context:** `validate_boundary()` already classifies issues as ERROR/WARNING strings, but the page-level handler only displays them as alerts. `_on_generate_mesh` should fail-closed when any of the following are present:
- ERROR: any of the three (`No boundary lines`, `fewer than 3 nodes`, `references missing nodes`)
- WARNING: `has self-intersections` (Triangle hangs/segfaults)
- WARNING: `No exterior boundary found (line_type=1)` (Triangle output is geometrically wrong — `_boundary_to_polygon` returns None and the cap pre-flight evaluates to 0)

The unclosed-ring WARNING is left non-blocking — Triangle handles it cleanly.

- [ ] **Step 1: Add the gate function in the service**

In `shyfem-ui/shyfem_ui/services/mesh_builder.py`, immediately after `validate_boundary` (around line 1223), append:

```python
def _check_boundary_gates(grd: GrdFile) -> tuple[bool, str | None]:
    """Decide whether ``grd`` is safe to hand to Triangle.

    Returns ``(True, None)`` if the boundary is mesh-ready. Otherwise returns
    ``(False, reason)`` where ``reason`` is a human-readable explanation.

    Blocks on:
    - any ERROR-prefixed issue from :func:`validate_boundary`
    - self-intersecting lines (Triangle can hang or segfault)
    - missing exterior boundary (line_type=1)

    Allows:
    - unclosed rings (Triangle closes them automatically)
    """
    issues = validate_boundary(grd)
    blocking: list[str] = []
    for issue in issues:
        if issue.startswith("ERROR"):
            blocking.append(issue)
        elif "self-intersect" in issue.lower():
            blocking.append(issue)
        elif "no exterior boundary" in issue.lower():
            blocking.append(issue)
    if blocking:
        return False, "; ".join(blocking)
    return True, None
```

- [ ] **Step 2: Write failing tests**

Append to `shyfem-ui/tests/test_mesh_builder.py` (next to `TestValidateBoundary`, around line 798):

Reuse the module-level `_make_square_boundary()` helper (10×10 square at origin, line_type=1, closed ring) and mutate the returned grid for the variant cases:

```python
class TestCheckBoundaryGates:
    """The fail-closed gate around triangulate()."""

    def test_clean_square_passes(self):
        ok, reason = _check_boundary_gates(_make_square_boundary())
        assert ok
        assert reason is None

    def test_no_lines_blocks(self):
        ok, reason = _check_boundary_gates(GrdFile())
        assert not ok
        assert "no boundary lines" in reason.lower()

    def test_only_holes_blocks(self):
        # No line_type=1 — turn the square's exterior into a hole.
        grd = _make_square_boundary()
        grd.lines[1].line_type = 2
        ok, reason = _check_boundary_gates(grd)
        assert not ok
        assert "exterior" in reason.lower()

    def test_fewer_than_three_nodes_blocks(self):
        grd = GrdFile()
        grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0)
        grd.nodes[2] = Node(id=2, node_type=0, x=1.0, y=0.0)
        grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2])
        ok, reason = _check_boundary_gates(grd)
        assert not ok
        assert "fewer than 3 nodes" in reason.lower()

    def test_self_intersecting_blocks(self):
        # Bowtie / figure-8: diagonals (0,0)-(1,1) and (1,0)-(0,1) cross.
        grd = GrdFile()
        for i, (x, y) in enumerate(
            [(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)], start=1
        ):
            grd.nodes[i] = Node(id=i, node_type=0, x=float(x), y=float(y))
        grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1])
        ok, reason = _check_boundary_gates(grd)
        assert not ok
        assert "self-intersect" in reason.lower()

    def test_unclosed_ring_passes(self):
        # WARNING: not a closed ring — left non-blocking; Triangle closes it.
        grd = _make_square_boundary()
        # Drop the closing repeat node
        grd.lines[1].nodes = [1, 2, 3, 4]
        ok, reason = _check_boundary_gates(grd)
        assert ok
```

Add `_check_boundary_gates` as a new line in the existing `from shyfem_ui.services.mesh_builder import (...)` block at the top of `tests/test_mesh_builder.py`. Insert it as the first entry inside the parens (alphabetical position — comes before `_remove_ring_loops`). The block currently begins:

```python
from shyfem_ui.services.mesh_builder import (
    _remove_ring_loops,
    adjust_depths,
    ...
```

After the edit it should begin:

```python
from shyfem_ui.services.mesh_builder import (
    _check_boundary_gates,
    _remove_ring_loops,
    adjust_depths,
    ...
```

(do **not** write a literal `...` token into the source — leave the rest of the existing list untouched.)

- [ ] **Step 3: Run the new tests — expect PASS for the function, but make sure imports resolve**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestCheckBoundaryGates -v
```
Expected: 6 tests pass.

- [ ] **Step 4: Wire the gate into `_on_generate_mesh`**

In `shyfem-ui/shyfem_ui/pages/mesh_builder.py`, around line 806, locate:

```python
    @reactive.effect
    @reactive.event(input.generate_mesh)
    async def _on_generate_mesh():
        grd = refined_grd.get()
        if grd is None:
            ui.notification_show("No boundary data to mesh.", type="warning")
            return
        method = input.mesh_method()
```

Replace the body up to `method = input.mesh_method()` with:

```python
    @reactive.effect
    @reactive.event(input.generate_mesh)
    async def _on_generate_mesh():
        grd = refined_grd.get()
        if grd is None:
            ui.notification_show("No boundary data to mesh.", type="warning")
            return
        ok, reason = _check_boundary_gates(grd)
        if not ok:
            msg = f"Cannot generate mesh: {reason}. Fix Step 1/2 issues first."
            _log(msg)
            ui.notification_show(msg, type="error", duration=8)
            return
        method = input.mesh_method()
```

Add `_check_boundary_gates` as a new line in the existing `from shyfem_ui.services.mesh_builder import (...)` block in `shyfem-ui/shyfem_ui/pages/mesh_builder.py`. Insert it as the first entry inside the parens (alphabetical position — comes before `_compute_depths_only`). After the edit the block should begin:

```python
from shyfem_ui.services.mesh_builder import (
    _check_boundary_gates,
    _compute_depths_only,
    adjust_depths,
    ...
```

(do **not** write a literal `...` token into the source — leave the rest of the existing list untouched.)

- [ ] **Step 5: Manual smoke test (optional but recommended)**

Run the app in local mode, upload an empty geojson:
```bash
cd shyfem-ui && SHYFEM_UI_DEPLOYMENT_MODE=local /opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app &
APP_PID=$!
sleep 3
# Upload tests/data/empty.geojson at http://localhost:8000/mesh, click Generate Mesh.
kill $APP_PID
```
Expected: error toast "Cannot generate mesh: ERROR: No boundary lines found. Fix Step 1/2 issues first." No Triangle invocation in logs.

If the harness is unavailable, skip this step and rely on the unit tests.

- [ ] **Step 6: Run the full mesh test suite — no regressions**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q
```
Expected: all previously-passing tests still pass; 6 new tests pass.

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/shyfem_ui/pages/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "fix(mesh): fail-closed gate when boundary has ERRORs or self-intersection"
```

---

## Phase B — Service-Level Invariants

### Task 2: Service-level guards on `triangulate()`

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py:479` — add ValueError raises in `triangulate`
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — extend `TestTriangulate`

**Context:** Current UI slider caps `min_angle` at 33° (a documented practical limit for Triangle's quality refinement — values ≥ 34° can fail to converge and hang). UI numeric input has `min=0.001` for `max_area`. But `triangulate()` itself accepts any float, so a non-UI caller (test, script, future API) can hand it pathological values. Add service-side guards that match the UI's intent.

- [ ] **Step 1: Write failing tests**

`TestTriangulate` already uses a module-level helper `_make_square_boundary()` (defined elsewhere in `test_mesh_builder.py`); reuse it. Append to the body of `TestTriangulate` (around line 401, just before `class TestInterpolateScipy`):

```python
    def test_min_angle_above_34_raises(self):
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="min_angle"):
            triangulate(grd, max_area=10.0, min_angle=40.0)

    def test_zero_max_area_raises(self):
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="max_area"):
            triangulate(grd, max_area=0.0, min_angle=20.0)

    def test_negative_max_area_raises(self):
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="max_area"):
            triangulate(grd, max_area=-1.0, min_angle=20.0)

    def test_min_angle_exactly_34_passes(self):
        # 34 is the upper bound the guard allows; 33 is the documented
        # practical max. Triangle accepts up to 34 but can fail to converge
        # above it.
        grd = _make_square_boundary()
        triangulate(grd, max_area=10.0, min_angle=34.0)  # must not raise

    def test_max_area_none_still_allowed(self):
        # None means "no global area constraint" — the existing minimal-mesh
        # path. Must continue to work.
        grd = _make_square_boundary()
        triangulate(grd, max_area=None, min_angle=20.0)
```

The `max_area=10.0` value matches the scale used by `test_max_area_produces_more_elements` (which calls `triangulate(grd, max_area=50.0)` and `max_area=5.0`), so the guard tests run fast on the same boundary.

- [ ] **Step 2: Run the new tests — expect FAIL on the three raise-tests**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestTriangulate -v
```
Expected: `test_min_angle_above_34_raises`, `test_zero_max_area_raises`, `test_negative_max_area_raises` all fail with "DID NOT RAISE"; the other two pass.

- [ ] **Step 3: Add the guards in `triangulate()`**

In `shyfem-ui/shyfem_ui/services/mesh_builder.py`, locate `triangulate` at line 479. Find this line near the top of the function body:

```python
    pslg = _build_pslg(grd)
```

Insert these 9 lines **immediately above it** (do not modify the signature or docstring; do not touch any code below `pslg = ...`):

```python
    if max_area is not None and max_area <= 0:
        raise ValueError(
            f"max_area must be positive (got {max_area!r}); pass None for no constraint"
        )
    if min_angle > 34.0:
        raise ValueError(
            f"min_angle must be <= 34 degrees (got {min_angle!r}); "
            "Triangle's quality refinement may not converge above 34"
        )
```

- [ ] **Step 4: Run the tests — expect PASS**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestTriangulate -v
```
Expected: all tests pass.

- [ ] **Step 5: Run the full mesh test suite — no regressions**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q
```
Expected: same pass count as before plus the new tests.

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "fix(mesh): service-level guards on triangulate() min_angle/max_area"
```

---

### Task 3: UI inline warning when `min_area >= max_area`

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py` — add pure helper `warn_if_min_geq_max_area`
- Modify: `shyfem-ui/shyfem_ui/pages/mesh_builder.py` — render the warning under the area inputs
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — add `TestWarnIfMinGeqMaxArea`

**Context:** When a user sets `min_area >= max_area`, the post-flight sliver counter (`count_below_area`) will report every triangle as a sliver — alarming and useless. Surface a clear warning at input time.

- [ ] **Step 1: Add the pure helper to the service**

In `shyfem-ui/shyfem_ui/services/mesh_builder.py`, after `count_below_area` (around line 471), insert:

```python
def warn_if_min_geq_max_area(
    min_area: float | None, max_area: float | None
) -> str | None:
    """Return a warning string if both bounds are set and min >= max."""
    if min_area is None or max_area is None:
        return None
    if min_area <= 0 or max_area <= 0:
        return None
    if min_area >= max_area:
        return (
            f"Min Triangle Area ({min_area:g}) is ≥ Max Triangle Area "
            f"({max_area:g}); every triangle will be flagged as a sliver."
        )
    return None
```

- [ ] **Step 2: Write failing tests**

Append to `shyfem-ui/tests/test_mesh_builder.py` (near the bottom, in a new class):

```python
class TestWarnIfMinGeqMaxArea:

    def test_returns_none_when_both_unset(self):
        assert warn_if_min_geq_max_area(None, None) is None

    def test_returns_none_when_one_unset(self):
        assert warn_if_min_geq_max_area(0.1, None) is None
        assert warn_if_min_geq_max_area(None, 0.5) is None

    def test_returns_none_when_min_lt_max(self):
        assert warn_if_min_geq_max_area(0.01, 0.1) is None

    def test_returns_none_when_min_zero(self):
        # min=0 is the "no constraint" sentinel; never warn.
        assert warn_if_min_geq_max_area(0.0, 0.1) is None

    def test_warns_when_min_eq_max(self):
        msg = warn_if_min_geq_max_area(0.1, 0.1)
        assert msg is not None
        assert "sliver" in msg

    def test_warns_when_min_gt_max(self):
        msg = warn_if_min_geq_max_area(0.5, 0.1)
        assert msg is not None
        assert "sliver" in msg
```

Add `warn_if_min_geq_max_area` to the import list in the test file.

- [ ] **Step 3: Run the tests — expect PASS**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestWarnIfMinGeqMaxArea -v
```
Expected: 6 tests pass.

- [ ] **Step 4: Render the warning in the page**

In `shyfem-ui/shyfem_ui/pages/mesh_builder.py`, locate the existing `element_estimate` render around line 787:

```python
    @render.ui
    def element_estimate():
        grd = refined_grd.get()
        area = input.max_area()
        if grd is None or area is None or area <= 0:
            return ui.p("Enter max area to see estimate.", class_="text-muted small")
        count = estimate_element_count(grd, area)
        return ui.p(f"Estimated elements: ~{count:,}", class_="small text-info")
```

Add a new `render.ui` immediately after it:

```python
    @render.ui
    def area_bounds_warning():
        # Only the quality method renders both inputs.
        if input.mesh_method() != "delaunay_quality":
            return ui.span()
        try:
            min_a = input.min_area()
            max_a = input.max_area()
        except Exception:
            return ui.span()
        msg = warn_if_min_geq_max_area(min_a, max_a)
        if msg is None:
            return ui.span()
        return ui.p(msg, class_="alert alert-warning py-2 px-3 small mb-2")
```

Then mount it under the area inputs by editing `mesh_method_controls` around line 736 — find the `ui.output_ui("element_estimate")` line inside the `delaunay_quality` branch and add immediately after:

```python
                            ui.output_ui("element_estimate"),
                            ui.output_ui("area_bounds_warning"),
```

Add `warn_if_min_geq_max_area` to the page-level service imports.

- [ ] **Step 5: Manual smoke test (optional)**

Start the app, upload Mar Menor sample boundary, set Min=0.5, Max=0.1; warning should appear under the area inputs.

- [ ] **Step 6: Run the full mesh test suite — no regressions**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q
```

- [ ] **Step 7: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/shyfem_ui/pages/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "feat(mesh): warn when Min Triangle Area >= Max Triangle Area"
```

---

### Task 4: Inert-cap warning for `delaunay_minimal` + Max Elements

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py` — add helper `warn_if_minimal_with_cap`
- Modify: `shyfem-ui/shyfem_ui/pages/mesh_builder.py` — add reactive notification at button click
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — add `TestWarnIfMinimalWithCap`

**Context:** When `mesh_method == "delaunay_minimal"`, no `max_area` is collected, so `estimate_element_count` returns 0 and the pre-flight cap check trivially passes. The user thinks they have a cap; in practice the element count is purely a function of the boundary geometry. The current warning at line 845 only fires for `delaunay_quality` and `delaunay_conforming`. Extend the warning to cover `delaunay_minimal`.

- [ ] **Step 1: Add the pure helper**

In `shyfem-ui/shyfem_ui/services/mesh_builder.py`, after `warn_if_min_geq_max_area` (added in Task 3), insert:

```python
def warn_if_minimal_with_cap(method: str, max_elements: int | None) -> str | None:
    """Warn the user that Max Elements has no effect in minimal mode."""
    if method == "delaunay_minimal" and max_elements:
        return (
            "Max Elements is ignored for Delaunay (minimal) — the element "
            "count depends only on the boundary geometry. Switch to a quality "
            "method if you want the cap to be enforced."
        )
    return None
```

- [ ] **Step 2: Write failing tests**

Append to `shyfem-ui/tests/test_mesh_builder.py`:

```python
class TestWarnIfMinimalWithCap:

    def test_minimal_with_cap_warns(self):
        msg = warn_if_minimal_with_cap("delaunay_minimal", 5000)
        assert msg is not None
        assert "ignored" in msg.lower()

    def test_minimal_without_cap_silent(self):
        assert warn_if_minimal_with_cap("delaunay_minimal", None) is None
        assert warn_if_minimal_with_cap("delaunay_minimal", 0) is None

    def test_quality_with_cap_silent(self):
        assert warn_if_minimal_with_cap("delaunay_quality", 5000) is None

    def test_conforming_with_cap_silent(self):
        assert warn_if_minimal_with_cap("delaunay_conforming", 5000) is None
```

Add `warn_if_minimal_with_cap` to the test file imports.

- [ ] **Step 3: Run the tests — expect PASS**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestWarnIfMinimalWithCap -v
```

- [ ] **Step 4: Wire the warning into `_on_generate_mesh`**

In `shyfem-ui/shyfem_ui/pages/mesh_builder.py`, locate the existing `if not eff_area and method != "delaunay_minimal":` branch (around line 845). Find this exact block:

```python
            if not eff_area and method != "delaunay_minimal":
                ui.notification_show(
                    "Set a Max Triangle Area so the element-count cap can be checked.",
                    type="warning",
                    duration=6,
                )
                return
```

Insert immediately after the closing `return` (still inside the `if max_elements and max_elements > 0:` outer block — same 12-space indent as `if not eff_area`):

```python
            # Minimal mode does not honor max_area, so the cap can't be enforced.
            minimal_msg = warn_if_minimal_with_cap(method, max_elements)
            if minimal_msg:
                _log(minimal_msg)
                ui.notification_show(minimal_msg, type="warning", duration=8)
```

(this is an insertion, not a replacement — the existing branch is unchanged.)

Add `warn_if_minimal_with_cap` to the page's service imports.

- [ ] **Step 5: Run the full mesh test suite — no regressions**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q
```

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/shyfem_ui/pages/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "feat(mesh): warn that Max Elements is inert under Delaunay minimal"
```

---

## Phase C — CRS / Coordinate Sanity

### Task 5: Bathymetry-vs-mesh extent overlap check

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py` — add `check_bathy_extent`
- Modify: `shyfem-ui/shyfem_ui/pages/mesh_builder.py` — call inside `_on_bathy_upload`, `_on_contour_upload`, and `_on_interpolate`
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — add `TestCheckBathyExtent`

**Context:** Mesh boundaries get reprojected to WGS84 by `import_boundaries`, but XYZ bathymetry is loaded raw — text files have no CRS. If the user uploads UTM-coord XYZ for a WGS84 mesh, points fall outside the mesh bbox and interpolation produces garbage (often via extrapolation). A bbox-disjoint test is cheap and catches this case before interpolation runs.

- [ ] **Step 1: Add the helper to the service**

In `shyfem-ui/shyfem_ui/services/mesh_builder.py`, after `_boundary_to_polygon` (around line 1283), insert:

```python
def check_bathy_extent(
    grd: GrdFile, bathy: np.ndarray
) -> str | None:
    """Return a warning if bathymetry points fall outside the mesh bbox.

    The check is bbox-vs-bbox (cheap). Disjoint bboxes almost certainly
    indicate a CRS mismatch (e.g. UTM-meter XYZ for a WGS84-degree mesh).

    Returns ``None`` if extents overlap or the boundary has no exterior.
    """
    if bathy.size == 0:
        return None
    poly = _boundary_to_polygon(grd)
    if poly is None or poly.is_empty:
        return None
    min_x, min_y, max_x, max_y = poly.bounds
    bx_min, by_min = float(bathy[:, 0].min()), float(bathy[:, 1].min())
    bx_max, by_max = float(bathy[:, 0].max()), float(bathy[:, 1].max())
    disjoint = (
        bx_max < min_x or bx_min > max_x or by_max < min_y or by_min > max_y
    )
    if disjoint:
        return (
            f"Bathymetry extent [{bx_min:.3g}, {by_min:.3g}] – "
            f"[{bx_max:.3g}, {by_max:.3g}] does not overlap mesh boundary "
            f"[{min_x:.3g}, {min_y:.3g}] – [{max_x:.3g}, {max_y:.3g}]. "
            "Likely cause: CRS mismatch — re-export bathymetry in the mesh's "
            "coordinate system (mesh is in WGS84 lon/lat after import)."
        )
    return None
```

- [ ] **Step 2: Write failing tests**

Append to `shyfem-ui/tests/test_mesh_builder.py`:

Reuse the module-level `_make_square_boundary()` helper (defined near the top of `test_mesh_builder.py`, default size = 10×10 starting at origin):

```python
class TestCheckBathyExtent:

    def test_overlapping_returns_none(self):
        grd = _make_square_boundary()  # 10x10 at origin
        bathy = np.array([[5.0, 5.0, -1.0], [3.0, 7.0, -2.0]])
        assert check_bathy_extent(grd, bathy) is None

    def test_disjoint_east_returns_warning(self):
        grd = _make_square_boundary()
        bathy = np.array([[100.0, 5.0, -1.0], [200.0, 5.0, -1.0]])
        msg = check_bathy_extent(grd, bathy)
        assert msg is not None
        assert "does not overlap" in msg

    def test_disjoint_north_returns_warning(self):
        grd = _make_square_boundary()
        bathy = np.array([[5.0, 100.0, -1.0]])
        msg = check_bathy_extent(grd, bathy)
        assert msg is not None

    def test_partial_overlap_returns_none(self):
        # Bathy bbox extends beyond mesh on the east, but they intersect.
        grd = _make_square_boundary()
        bathy = np.array([[5.0, 5.0, -1.0], [50.0, 5.0, -1.0]])
        assert check_bathy_extent(grd, bathy) is None

    def test_empty_bathy_returns_none(self):
        grd = _make_square_boundary()
        assert check_bathy_extent(grd, np.empty((0, 3))) is None

    def test_no_exterior_returns_none(self):
        # No line_type=1 — _boundary_to_polygon returns None.
        grd = GrdFile()
        bathy = np.array([[1.0, 1.0, -1.0]])
        assert check_bathy_extent(grd, bathy) is None
```

Add `check_bathy_extent` to the test file imports.

- [ ] **Step 3: Run the tests — expect PASS**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestCheckBathyExtent -v
```

- [ ] **Step 4: Wire into the bathymetry upload + interpolate flows**

In `shyfem-ui/shyfem_ui/pages/mesh_builder.py`, locate `_on_bathy_upload` around line 1040. Before `bathy_data.set(data)`, add:

```python
            mesh = mesh_grd.get()
            if mesh is not None:
                msg = check_bathy_extent(mesh, data)
                if msg is not None:
                    _log(f"Bathymetry warning: {msg}")
                    ui.notification_show(msg, type="warning", duration=10)
```

Apply the same block in `_on_contour_upload` (around line 1058–1083) before `bathy_data.set(data)`.

Also in `_on_interpolate` around line 1086, after fetching `data = bathy_data.get()` and the early-return guard, add a final extent check (in case the user uploaded bathy first and mesh later):

```python
        msg = check_bathy_extent(grd, data)
        if msg is not None:
            _log(f"Bathymetry warning: {msg}")
            ui.notification_show(msg, type="warning", duration=10)
            # Non-blocking — let the user proceed if they understand the warning.
```

Add `check_bathy_extent` to the page's service imports.

- [ ] **Step 5: Run the full mesh test suite**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q
```

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/shyfem_ui/pages/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "feat(mesh): warn when bathymetry extent disjoint from mesh boundary"
```

---

## Phase D — Upload Sanity

### Task 6: Bathymetry depth-stats summary + degenerate-input warning

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/mesh_builder.py` — add `summarize_depth_stats` and `warn_if_degenerate_bathy`
- Modify: `shyfem-ui/shyfem_ui/pages/mesh_builder.py` — extend `_on_bathy_upload` and `_on_contour_upload`
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — add `TestBathyUploadStats`

**Context:** SHYFEM convention: depth > 0 below surface. Users coming from elevation datasets often supply `z = 0` or `z < 0`. Today they only find out after interpolation produces a flat or sign-flipped bathymetry. Surface a depth summary at upload time, plus an explicit warning when input is obviously degenerate.

- [ ] **Step 1: Add the two helpers**

In `shyfem-ui/shyfem_ui/services/mesh_builder.py`, after `check_bathy_extent` (added in Task 5), insert:

```python
def summarize_depth_stats(bathy: np.ndarray) -> str:
    """Return a one-line min/max/mean summary of bathymetry depths.

    NaN-aware: NaN values are excluded from min/max/mean (so partial-NaN
    arrays still report meaningful stats); the count of NaN-stripped
    points is appended when non-zero.
    """
    if bathy.size == 0:
        return "Bathymetry: empty"
    z = bathy[:, 2]
    valid = z[~np.isnan(z)]
    if valid.size == 0:
        return "Bathymetry: all depths are NaN"
    nan_count = z.size - valid.size
    nan_note = f" ({nan_count} NaN excluded)" if nan_count else ""
    return (
        f"Depth: min={float(valid.min()):.2f}, max={float(valid.max()):.2f}, "
        f"mean={float(valid.mean()):.2f}{nan_note} "
        f"(SHYFEM convention: depth>0 below surface)"
    )


def warn_if_degenerate_bathy(bathy: np.ndarray) -> str | None:
    """Return a warning if depths are obviously broken; otherwise None."""
    if bathy.size == 0:
        return None
    z = bathy[:, 2]
    if np.all(np.isnan(z)):
        return "All bathymetry values are NaN — interpolation will fail."
    valid = z[~np.isnan(z)]
    if valid.size == 0:
        return None
    if np.all(valid == 0):
        return "All bathymetry depths are 0 — likely missing depth data."
    if np.all(valid == valid[0]):
        return (
            f"All bathymetry depths are identical ({float(valid[0]):.2f}); "
            "interpolation will produce a flat bottom."
        )
    return None
```

- [ ] **Step 2: Write failing tests**

Append to `shyfem-ui/tests/test_mesh_builder.py`:

```python
class TestBathyUploadStats:

    def test_summary_min_max_mean(self):
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, 3.0], [2.0, 2.0, 5.0]])
        s = summarize_depth_stats(bathy)
        assert "1.00" in s and "5.00" in s and "3.00" in s

    def test_summary_empty(self):
        assert "empty" in summarize_depth_stats(np.empty((0, 3)))

    def test_summary_excludes_nan(self):
        # Regression: numpy.min/max/mean propagate NaN by default; the
        # summary must use NaN-aware reductions.
        bathy = np.array(
            [[0.0, 0.0, 1.0], [1.0, 1.0, np.nan], [2.0, 2.0, 5.0]]
        )
        s = summarize_depth_stats(bathy)
        assert "min=1.00" in s
        assert "max=5.00" in s
        assert "1 NaN excluded" in s

    def test_summary_all_nan(self):
        bathy = np.array([[0.0, 0.0, np.nan], [1.0, 1.0, np.nan]])
        s = summarize_depth_stats(bathy)
        assert "all depths are nan" in s.lower()

    def test_warn_all_nan(self):
        bathy = np.array([[0.0, 0.0, np.nan], [1.0, 1.0, np.nan]])
        msg = warn_if_degenerate_bathy(bathy)
        assert msg is not None
        assert "nan" in msg.lower()

    def test_warn_all_zero(self):
        bathy = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
        msg = warn_if_degenerate_bathy(bathy)
        assert msg is not None
        assert "0" in msg

    def test_warn_all_identical(self):
        bathy = np.array([[0.0, 0.0, 5.0], [1.0, 1.0, 5.0]])
        msg = warn_if_degenerate_bathy(bathy)
        assert msg is not None
        assert "identical" in msg

    def test_no_warn_normal(self):
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, 5.0]])
        assert warn_if_degenerate_bathy(bathy) is None

    def test_no_warn_some_nan(self):
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, np.nan], [2.0, 2.0, 3.0]])
        assert warn_if_degenerate_bathy(bathy) is None

    def test_empty_returns_none(self):
        assert warn_if_degenerate_bathy(np.empty((0, 3))) is None
```

Add `summarize_depth_stats` and `warn_if_degenerate_bathy` to the test imports.

- [ ] **Step 3: Run the tests — expect PASS**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestBathyUploadStats -v
```

- [ ] **Step 4: Wire into upload handlers**

Two small edits per handler — done as anchor-specific replacements so this task is order-independent with respect to Task 5 (which inserts unrelated code into the same `try` blocks).

**Edit 4a — replace the existing depth-range log line in `_on_bathy_upload`:**

In `shyfem-ui/shyfem_ui/pages/mesh_builder.py`, find:

```python
            _log(f"  Depth range: {data[:,2].min():.2f} to {data[:,2].max():.2f}")
```

(this exact line appears twice — once in `_on_bathy_upload`, once in `_on_contour_upload`). Replace **both** occurrences with:

```python
            _log(f"  {summarize_depth_stats(data)}")
```

(use `replace_all=True` on the Edit tool, or do two passes — both call sites want the same change).

**Edit 4b — add the degenerate-bathy warning after the "Loaded N points" notification.**

In `_on_bathy_upload`, find:

```python
            ui.notification_show(
                f"Loaded {len(data)} bathymetry points", type="message", duration=3
            )
```

Replace with:

```python
            ui.notification_show(
                f"Loaded {len(data)} bathymetry points", type="message", duration=3
            )
            warn = warn_if_degenerate_bathy(data)
            if warn:
                _log(f"Bathymetry warning: {warn}")
                ui.notification_show(warn, type="warning", duration=8)
```

In `_on_contour_upload`, find:

```python
            ui.notification_show(
                f"Extracted {len(data)} points from contour isobaths",
                type="message",
                duration=3,
            )
```

Replace with:

```python
            ui.notification_show(
                f"Extracted {len(data)} points from contour isobaths",
                type="message",
                duration=3,
            )
            warn = warn_if_degenerate_bathy(data)
            if warn:
                _log(f"Bathymetry warning: {warn}")
                ui.notification_show(warn, type="warning", duration=8)
```

Add `summarize_depth_stats, warn_if_degenerate_bathy` to the page's service imports.

- [ ] **Step 5: Run the full suite — no regressions**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py -q
```

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/services/mesh_builder.py shyfem-ui/shyfem_ui/pages/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "feat(mesh): warn on degenerate bathymetry input at upload"
```

---

### Task 7: Reject unknown boundary upload extensions explicitly

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/mesh_builder.py` — `_prepare_upload_files`
- Modify: `shyfem-ui/tests/test_mesh_builder.py` — add `TestPrepareUploadFiles` (or extend existing)

**Context:** `_prepare_upload_files` falls back to `return work / files[0]["name"]` when no recognized extension is found. fiona then raises a cryptic driver error. Replace with an explicit `ValueError` listing accepted formats.

- [ ] **Step 1: Inspect current fallback**

Run:
```bash
sed -n '402,425p' shyfem-ui/shyfem_ui/pages/mesh_builder.py
```
Confirm the fallback line `return work / files[0]["name"]` is at the bottom of the function.

- [ ] **Step 2: Replace the fallback with an explicit error**

Edit `_prepare_upload_files` — find the final fallback block:

```python
        for ext in (".geojson", ".json", ".gpkg"):
            found = list(work.glob(f"*{ext}"))
            if found:
                return found[0]

        # Fallback: return the first file
        return work / files[0]["name"]
```

Replace with:

```python
        for ext in (".geojson", ".json", ".gpkg"):
            found = list(work.glob(f"*{ext}"))
            if found:
                return found[0]

        names = ", ".join(f["name"] for f in files)
        raise ValueError(
            f"Unrecognized boundary file format. Got: {names}. "
            "Accepted: .geojson, .json, .gpkg, .shp (with companions), or "
            ".zip containing one of the above."
        )
```

- [ ] **Step 3: Add a test that exercises the new error path**

Because `_prepare_upload_files` is a closure inside `mesh_builder_server`, it's not directly importable. The simplest cover is an integration-shaped unit test that imports the helper via the `pages` module after exposing it. To avoid restructuring the page, add the test against the message string instead:

Append to `shyfem-ui/tests/test_mesh_builder.py`:

```python
class TestUploadRejectsUnknownExt:
    """Smoke test: the page-level upload helper must explicitly reject
    unknown extensions instead of letting fiona raise a cryptic error."""

    def test_error_message_lists_accepted_formats(self):
        """Static check that the user-facing error message mentions all
        accepted formats. If someone removes one, this catches it."""
        # `Path` is already imported at the top of test_mesh_builder.py.
        page_src = (
            Path(__file__).resolve().parent.parent / "shyfem_ui" / "pages"
            / "mesh_builder.py"
        ).read_text()
        # The branch that raises must be present and mention the formats.
        assert "Unrecognized boundary file format" in page_src
        for fmt in (".geojson", ".json", ".gpkg", ".shp", ".zip"):
            assert fmt in page_src
```

This is intentionally a static-source assertion — exercising the closure properly would require building a fake Shiny session, which is much more invasive than the bug warrants.

- [ ] **Step 4: Run the test**

Run:
```bash
cd shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_mesh_builder.py::TestUploadRejectsUnknownExt -v
```
Expected: PASS.

- [ ] **Step 5: Manual smoke test (optional)**

Upload a `.txt` file at the boundary upload — expected: error toast "Unrecognized boundary file format. Got: foo.txt. Accepted: .geojson, .json, .gpkg, .shp (with companions), or .zip containing one of the above." instead of fiona's driver error.

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/mesh_builder.py shyfem-ui/tests/test_mesh_builder.py
git commit -m "fix(mesh): reject unknown boundary upload extensions explicitly"
```

---

## Phase E — Documentation

### Task 8: Open follow-up doc for slider unit-ambiguity work

**Files:**
- Create: `docs/followups/2026-04-28-mesh-slider-units.md`

**Context:** The audit surfaced two parameters whose meaning is implicit in the source CRS: `reduce_tolerance` (Step 2) and `contour_sample_dist` (Step 4). Fixing them properly is UX redesign — dynamic labels keyed off the imported CRS, or percent-of-extent sliders. Out of scope for this validation pass; track explicitly so it doesn't get lost.

- [ ] **Step 1: Create the followup**

Create `docs/followups/2026-04-28-mesh-slider-units.md`:

```markdown
# Follow-up: Unit-Aware Mesh Sliders

**Origin:** 2026-04-28 mesh-input validation audit — the two issues called out under "Out of scope" in `docs/superpowers/plans/2026-04-28-mesh-validation-hardening.md`.

**Problem.** Two sliders in the mesh-builder wizard accept values in the
source CRS's coordinate units, with no in-UI cue:

- `reduce_tolerance` (Step 2 — Refine boundary): range 0–1000. After
  `import_boundaries()` reprojects to WGS84, units are degrees; 1000° is
  meaningless. For a non-reprojected projected source, 1 unit ≈ 1 m.
- `contour_sample_dist` (Step 4 — Bathymetry contours): no upper bound;
  small values on long lines explode the point cloud (e.g. 0.001 sample
  on a 100 km line → 100M points).

**Why we deferred.** A clean fix is UX redesign, not pure validation:
- Option A — Dynamic labels keyed off `grd.epsg` after import
  ("Tolerance (degrees)" vs "Tolerance (meters)"), plus auto-scaling the
  slider max to a sensible fraction of boundary extent.
- Option B — Replace coordinate-unit sliders with percent-of-extent
  sliders (0–10 % of boundary diagonal) that translate to the right
  underlying units internally.

**Suggested next step.** Pick Option B for both sliders — it is unit-free
from the user's perspective, can't accept absurd values, and is one
arithmetic step (`tolerance = pct * boundary.diagonal_length`) inside
the existing handlers.

**Related code:**
- `shyfem-ui/shyfem_ui/pages/mesh_builder.py:622–625` (`reduce_tolerance` slider)
- `shyfem-ui/shyfem_ui/pages/mesh_builder.py` (`contour_sample_dist` numeric input — search `contour_sample_dist`)
- `shyfem-ui/shyfem_ui/services/mesh_builder.py:333` (`reduce_boundary`)
- `shyfem-ui/shyfem_ui/services/mesh_builder.py:805` (sample-dist branch in `load_bathymetry_contours`)
```

- [ ] **Step 2: Commit**

```bash
git add docs/followups/2026-04-28-mesh-slider-units.md
git commit -m "docs(followup): track mesh slider unit-ambiguity work"
```

---

## Verification Checklist

After all 8 tasks:

1. **Fail-closed gate active**: `pytest tests/test_mesh_builder.py::TestCheckBoundaryGates -v` → 6 pass.
2. **Service guards active**: `pytest tests/test_mesh_builder.py::TestTriangulate -v` → 10 pass (5 existing + 5 new), the 3 raise-tests included.
3. **All advisory helpers present**: `grep -c '^def warn_if_\|^def check_bathy\|^def summarize_depth\|^def _check_boundary_gates' shyfem-ui/shyfem_ui/services/mesh_builder.py` returns exactly **6** (`_check_boundary_gates`, `warn_if_min_geq_max_area`, `warn_if_minimal_with_cap`, `check_bathy_extent`, `summarize_depth_stats`, `warn_if_degenerate_bathy`).
4. **Page wiring complete**: each of the 6 helper names must appear in `shyfem-ui/shyfem_ui/pages/mesh_builder.py` on at least 2 lines (import + at least one call site). Run:
   ```bash
   for name in _check_boundary_gates warn_if_min_geq_max_area warn_if_minimal_with_cap check_bathy_extent summarize_depth_stats warn_if_degenerate_bathy; do
     n=$(grep -c "$name" shyfem-ui/shyfem_ui/pages/mesh_builder.py)
     [ "$n" -ge 2 ] || echo "FAIL $name ($n)"
   done
   ```
   Expected: no FAIL lines printed.
5. **No regressions**: `pytest tests/test_mesh_builder.py -q` is all green and the pass count is exactly old-count + 6+5+6+4+6+10+1 = old + 38.
6. **Mar Menor reproducibility**: existing `TestMarMenorIntegration::test_smooth_and_triangulate` still passes (the gate must not block valid Mar Menor data).
7. **Unrecognized-extension rejection**: `grep "Unrecognized boundary file format" shyfem-ui/shyfem_ui/pages/mesh_builder.py` returns a hit.
8. **Followup doc filed**: `ls docs/followups/2026-04-28-mesh-slider-units.md` exists.

---

## Validation Coverage After Plan

| Gap | Severity | Status |
|-----|----------|--------|
| `validate_boundary` ERRORs not blocking | HIGH | Closed (Task 1) |
| Self-intersection warning not blocking | HIGH | Closed (Task 1) |
| `triangulate` accepts pathological min_angle/max_area | MED | Closed (Task 2) |
| `min_area >= max_area` not flagged | MED | Closed (Task 3) |
| `delaunay_minimal` + cap silently inert | MED | Closed (Task 4) |
| XYZ bathy CRS mismatch silent | MED | Closed (Task 5) |
| Degenerate bathy depths silent | LOW | Closed (Task 6) |
| Unknown boundary extensions silent | LOW | Closed (Task 7) |
| Slider unit-ambiguity (reduce/sample) | MED | Tracked (Task 8 follow-up) |
| Chaikin output-size cap | MED | Tracked (Task 8 follow-up) |
| Server upload size limits | LOW | Out of scope (environmental) |
