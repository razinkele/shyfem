# deck.gl Widget Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `layer_legend_widget`, `screenshot_widget`, `trips_layer`, and `trips_animation_ui/server` from shiny_deckgl v1.9.1 to the SHYFEM UI grid_map component and IBM page.

**Architecture:** Two independent components modified: (1) grid_map gets `layer_legend_widget` (replaces manual legend + toggle checkboxes) and `screenshot_widget`; (2) IBM page gets `trips_layer` with `trips_animation_ui/server` (replaces static time-filtered path_layer) and `screenshot_widget`. TDD approach — tests first, then implementation, then verification.

**Tech Stack:** Python 3.13, Shiny for Python, shiny_deckgl v1.9.1, pytest

**Spec:** `docs/superpowers/specs/2026-04-05-deckgl-widgets-design.md`

**Test commands:**
```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/<file> -v --tb=short
```

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `shyfem_ui/components/grid_map.py` | Modify | Add imports, remove checkboxes, replace legend_control with layer_legend_widget, add screenshot_widget |
| `shyfem_ui/pages/ibm.py` | Modify | Add imports, replace time dropdowns with trips_animation_ui, replace path_layer with trips_layer, add screenshot_widget |
| `tests/test_grid_map_widgets.py` | Create | Tests for grid_map widget changes |
| `tests/test_ibm_trips.py` | Create | Tests for IBM trips animation changes |

---

## Task 1: grid_map — Write Tests

**Files:**
- Create: `shyfem-ui/tests/test_grid_map_widgets.py`

- [ ] **Step 1: Create test file with all grid_map widget tests**

```python
"""Tests for grid_map deck.gl widget integration (layer_legend_widget, screenshot_widget)."""

import re
from unittest.mock import MagicMock

import pytest


def test_screenshot_widget_importable():
    """screenshot_widget is available from shiny_deckgl."""
    from shiny_deckgl import screenshot_widget
    assert screenshot_widget is not None


def test_layer_legend_widget_importable():
    """layer_legend_widget is available from shiny_deckgl."""
    from shiny_deckgl import layer_legend_widget
    assert layer_legend_widget is not None


def test_grid_map_ui_no_manual_toggle_checkboxes():
    """grid_map_ui output must not contain show_emodnet/show_boundaries/show_nodes checkboxes."""
    from shyfem_ui.components.grid_map import grid_map_ui
    html = str(grid_map_ui("test_map"))
    assert "show_emodnet" not in html, "show_emodnet checkbox should be removed"
    assert "show_boundaries" not in html, "show_boundaries checkbox should be removed"
    assert "show_nodes" not in html, "show_nodes checkbox should be removed"


def test_grid_map_ui_fallback_without_deckgl():
    """When MapWidget is None, grid_map_ui returns an alert div."""
    from unittest.mock import patch
    import shyfem_ui.components.grid_map as gm

    with patch.object(gm, "MapWidget", None):
        html = str(gm.grid_map_ui("test_fallback"))
    assert "shiny_deckgl" in html


def test_build_label_map_static_entries():
    """_build_label_map returns friendly names for known layer IDs."""
    from shyfem_ui.components.grid_map import _build_label_map

    layers = [
        {"id": "emodnet"},
        {"id": "wireframe"},
        {"id": "triangles"},
        {"id": "nodes"},
    ]
    label_map = _build_label_map(layers)
    assert label_map["emodnet"] == "EMODnet Bathy"
    assert label_map["wireframe"] == "Wireframe"
    assert label_map["triangles"] is not None  # mode-dependent label
    assert label_map["nodes"] == "Nodes"


def test_build_label_map_dynamic_boundaries():
    """_build_label_map generates entries for boundary layer IDs."""
    from shyfem_ui.components.grid_map import _build_label_map

    layers = [
        {"id": "boundary_coastline"},
        {"id": "boundary_island"},
    ]
    label_map = _build_label_map(layers)
    assert "boundary_coastline" in label_map
    assert "boundary_island" in label_map
    assert "coastline" in label_map["boundary_coastline"].lower()


def test_build_layers_no_toggle_params():
    """build_layers no longer accepts show_emodnet/show_boundaries/show_nodes params."""
    import inspect
    from shyfem_ui.components.grid_map import build_layers

    sig = inspect.signature(build_layers)
    params = set(sig.parameters.keys())
    assert "show_emodnet" not in params, "show_emodnet param should be removed"
    assert "show_boundaries" not in params, "show_boundaries param should be removed"
    assert "show_nodes" not in params, "show_nodes param should be removed"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map_widgets.py -v --tb=short 2>&1 | tail -20
```

Expected: `test_screenshot_widget_importable` and `test_layer_legend_widget_importable` PASS (already installed). `test_grid_map_ui_no_manual_toggle_checkboxes` FAILS (checkboxes still present). `test_build_label_map_*` FAILS (function doesn't exist yet). `test_build_layers_no_toggle_params` FAILS (params still present).

- [ ] **Step 3: Commit tests**

```bash
git add shyfem-ui/tests/test_grid_map_widgets.py
git commit -m "test: add grid_map widget integration tests (red)"
```

---

## Task 2: grid_map — Add Imports and _build_label_map Helper

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py:1194-1202` (import block)
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py` (add helper after imports)

- [ ] **Step 1: Update the import block**

In `grid_map.py`, replace lines 1194-1202:

```python
try:
    from shiny_deckgl import (  # noqa: E402
        MapWidget,
        fullscreen_widget,
        legend_control,
        zoom_widget,
    )
except ImportError:
    MapWidget = fullscreen_widget = legend_control = zoom_widget = None
```

with:

```python
try:
    from shiny_deckgl import (  # noqa: E402
        MapWidget,
        fullscreen_widget,
        layer_legend_widget,
        legend_control,
        screenshot_widget,
        zoom_widget,
    )
except ImportError:
    MapWidget = fullscreen_widget = layer_legend_widget = None
    legend_control = screenshot_widget = zoom_widget = None
```

- [ ] **Step 2: Add _build_label_map helper function**

After the `_VIEW_MODES` dict (around line 1213), add:

```python
def _build_label_map(layers: list[dict]) -> dict[str, str]:
    """Build a layer-ID → friendly-name map for layer_legend_widget."""
    _STATIC_LABELS = {
        "emodnet": "EMODnet Bathy",
        "wireframe": "Wireframe",
        "triangles": "Triangles",
        "nodes": "Nodes",
    }
    label_map: dict[str, str] = {}
    for layer in layers:
        lid = layer.get("id", "")
        if lid in _STATIC_LABELS:
            label_map[lid] = _STATIC_LABELS[lid]
        elif lid.startswith("boundary_"):
            btype = lid.split("_", 1)[1]
            label_map[lid] = btype.replace("_", " ").title()
    return label_map
```

- [ ] **Step 3: Run label_map tests**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map_widgets.py::test_build_label_map_static_entries tests/test_grid_map_widgets.py::test_build_label_map_dynamic_boundaries -v --tb=short
```

Expected: Both PASS.

- [ ] **Step 4: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/grid_map.py
git commit -m "feat(grid_map): add layer_legend_widget/screenshot imports and _build_label_map helper"
```

---

## Task 3: grid_map — Remove Toggle Checkboxes and Update build_layers

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py:1313-1315` (remove checkboxes from UI)
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py:731-741` (remove params from build_layers)
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py:1380-1424` (remove input reads in _update_map)

- [ ] **Step 1: Remove toggle checkboxes from grid_map_ui**

In `grid_map_ui()`, delete these 3 lines (around lines 1313-1315):

```python
                ui.input_checkbox("show_boundaries", "Boundaries", value=True),
                ui.input_checkbox("show_nodes", "Nodes", value=False),
                ui.input_checkbox("show_emodnet", "EMODnet", value=False),
```

- [ ] **Step 2: Remove show_* params from build_layers signature**

In `build_layers()` at line 731, change the signature from:

```python
def build_layers(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "viridis",
    show_boundaries: bool = False,
    show_nodes: bool = False,
    show_emodnet: bool = False,
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
    epsg: int | None = None,
) -> list[dict]:
```

to:

```python
def build_layers(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
    epsg: int | None = None,
) -> list[dict]:
```

Inside the function body, replace any `if show_emodnet:` / `if show_boundaries:` / `if show_nodes:` guards with unconditional inclusion (always add the layers). The `layer_legend_widget` handles visibility client-side.

- [ ] **Step 3: Update _update_map to remove input reads and adjust build_layers call**

In `_update_map()`, remove these 3 lines (around 1382-1384):

```python
        show_bdry = input.show_boundaries()
        show_nd = input.show_nodes()
        show_emod = input.show_emodnet()
```

And update the `build_layers()` call (around line 1414) to remove the 3 arguments:

```python
        layers = build_layers(
            grd,
            mode=actual_mode,
            colorscale=colorscale,
            elevation_scale=elev_scale,
            partition_map=pmap,
            epsg=epsg_val,
        )
```

- [ ] **Step 4: Run tests**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map_widgets.py -v --tb=short
```

Expected: `test_grid_map_ui_no_manual_toggle_checkboxes` and `test_build_layers_no_toggle_params` now PASS. All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/grid_map.py
git commit -m "feat(grid_map): remove toggle checkboxes, always include all layers"
```

---

## Task 4: grid_map — Replace legend_control with layer_legend_widget and Add screenshot_widget

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py:1428-1489` (_update_map legend + widget code)

- [ ] **Step 1: Add screenshot_widget and layer_legend_widget to _update_map**

In `_update_map()`, update the `_map.update()` call's `widgets` list (around line 1433) to include `screenshot_widget`:

```python
        await _map.update(
            session,
            layers=layers,
            view_state=vs,
            transition_duration=500,
            widgets=[
                zoom_widget(),
                fullscreen_widget(placement="top-right"),
                screenshot_widget(placement="top-right"),
            ],
        )
```

- [ ] **Step 2: Replace manual legend_entries with layer_legend_widget**

Replace the entire legend construction block (from `legend_entries: list[dict] = []` through `await _map.set_controls(session, [...])`) — approximately lines 1439-1489 — with:

```python
        label_map = _build_label_map(layers)
        await _map.set_controls(session, [
            layer_legend_widget(
                auto_introspect=True,
                show_checkbox=True,
                label_map=label_map,
                placement="bottom-right",
                title="Layers",
            ),
        ])
```

Also update the empty-grid branch (around line 1377) to clear controls:

```python
            await _map.set_controls(session, [])
```

(This line should already exist; verify it's still there.)

- [ ] **Step 3: Run full test suite**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map_widgets.py tests/test_grid_map.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add shyfem-ui/shyfem_ui/components/grid_map.py
git commit -m "feat(grid_map): replace legend_control with layer_legend_widget, add screenshot_widget"
```

---

## Task 5: IBM — Write Tests

**Files:**
- Create: `shyfem-ui/tests/test_ibm_trips.py`

- [ ] **Step 1: Create test file with all IBM trips tests**

```python
"""Tests for IBM page trips_layer animation integration."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from shyfem_ui.services.lgr_service import ParticleTrack


def _make_track(type_id=1, n=5):
    """Create a simple ParticleTrack for testing."""
    base = datetime(2026, 1, 1, 0, 0, 0)
    return ParticleTrack(
        type_id=type_id,
        path=[[12.0 + i * 0.01, 45.0 + i * 0.01] for i in range(n)],
        times=[(base.replace(hour=i)).isoformat(sep=" ") for i in range(n)],
        depths=[float(i) for i in range(n)],
        ages=[float(i * 3600) for i in range(n)],
    )


def test_ibm_ui_no_time_range_output():
    """IBM UI must not contain time_range_controls output."""
    from shyfem_ui.pages.ibm import ibm_ui
    html = str(ibm_ui("test_ibm"))
    assert "time_range_controls" not in html, "time_range_controls output should be removed"


def test_ibm_ui_contains_trips_animation():
    """IBM UI should contain trips animation controls."""
    from shyfem_ui.pages.ibm import ibm_ui
    html = str(ibm_ui("test_ibm2"))
    # trips_animation_ui generates a module with the given id
    assert "ibm_trips" in html, "trips_animation_ui module ID should be in the UI"


def test_tracks_to_trips_basic():
    """_tracks_to_trips converts ParticleTrack list to format_trips output."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    tracks = [_make_track(type_id=1, n=3)]
    result = _tracks_to_trips(tracks)
    assert isinstance(result, list)
    assert len(result) == 1
    assert "path" in result[0]
    assert "timestamps" in result[0]


def test_tracks_to_trips_empty():
    """Empty input produces empty output."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    result = _tracks_to_trips([])
    assert result == []


def test_tracks_to_trips_preserves_colors():
    """Per-type colors from _TRACK_COLORS are passed through."""
    from shyfem_ui.pages.ibm import _tracks_to_trips, _TRACK_COLORS
    tracks = [_make_track(type_id=1, n=3), _make_track(type_id=2, n=3)]
    result = _tracks_to_trips(tracks)
    assert result[0].get("color") == _TRACK_COLORS[0]
    assert result[1].get("color") == _TRACK_COLORS[1]


def test_tracks_to_trips_timestamps_are_floats():
    """Output timestamps are Unix epoch floats, not ISO strings."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    tracks = [_make_track(type_id=1, n=3)]
    result = _tracks_to_trips(tracks)
    ts = result[0]["timestamps"]
    assert all(isinstance(t, float) for t in ts)
    # First timestamp should be 2026-01-01 00:00:00
    assert ts[0] == pytest.approx(datetime(2026, 1, 1, 0, 0, 0).timestamp(), abs=1)


def test_tracks_to_trips_timestamps_monotonic():
    """Output timestamps are monotonically increasing per track."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    tracks = [_make_track(type_id=1, n=5)]
    result = _tracks_to_trips(tracks)
    ts = result[0]["timestamps"]
    for i in range(1, len(ts)):
        assert ts[i] > ts[i - 1], f"Timestamps not monotonic at index {i}"


def test_path_layer_not_imported():
    """ibm.py should not import path_layer (replaced by trips_layer)."""
    import inspect
    import shyfem_ui.pages.ibm as ibm_mod
    source = inspect.getsource(ibm_mod)
    # path_layer should not appear in import statements
    import_lines = [ln for ln in source.split("\n") if "import" in ln and "path_layer" in ln]
    assert len(import_lines) == 0, f"path_layer still imported: {import_lines}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_ibm_trips.py -v --tb=short 2>&1 | tail -20
```

Expected: Import tests may PASS. `test_ibm_ui_no_time_range_output` FAILS (still present). `test_tracks_to_trips_*` FAILS (`_tracks_to_trips` doesn't exist). `test_path_layer_not_imported` FAILS (still imported).

- [ ] **Step 3: Commit tests**

```bash
git add shyfem-ui/tests/test_ibm_trips.py
git commit -m "test: add IBM trips animation tests (red)"
```

---

## Task 6: IBM — Add Imports, _tracks_to_trips Adapter, and Update UI

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/ibm.py:13-27` (imports)
- Modify: `shyfem-ui/shyfem_ui/pages/ibm.py` (add adapter function)
- Modify: `shyfem-ui/shyfem_ui/pages/ibm.py:148-151` (UI changes)

- [ ] **Step 1: Update imports**

Replace the existing shiny_deckgl import block (lines 13-27) with:

```python
try:
    from shiny_deckgl import (
        MapWidget,
        context_menu_widget,
        fullscreen_widget,
        info_widget,
        legend_control,
        screenshot_widget,
        scatterplot_layer,
        tile_layer,
        trips_layer,
        zoom_widget,
    )
    from shiny_deckgl.ibm import (
        format_trips,
        trips_animation_ui,
        trips_animation_server,
    )
except ImportError:
    MapWidget = context_menu_widget = fullscreen_widget = None
    info_widget = legend_control = screenshot_widget = None
    scatterplot_layer = tile_layer = trips_layer = zoom_widget = None
    format_trips = trips_animation_ui = trips_animation_server = None
```

Remove `path_layer` from the import. Remove `filter_by_time` from the lgr_service import on line 31:

Change:
```python
from shyfem_ui.services.lgr_service import LgrService, ParticleTrack, filter_by_time
```
to:
```python
from shyfem_ui.services.lgr_service import LgrService, ParticleTrack
```

- [ ] **Step 2: Add _tracks_to_trips adapter function**

After the `_TRACK_COLORS` list (around line 48), add:

```python
def _tracks_to_trips(tracks: list[ParticleTrack]) -> list[dict]:
    """Convert ParticleTrack list to format_trips input and call it.

    Returns a list of trip dicts ready for trips_layer.
    """
    if not tracks or format_trips is None:
        return []
    from datetime import datetime as _dt

    paths: list[list[list[float]]] = []
    timestamps: list[list[float]] = []
    properties: list[dict] = []
    for t in tracks:
        if not t.path:
            continue
        assert all(len(p) == 2 for p in t.path), (
            f"ParticleTrack paths must be 2-D [lon,lat], got {len(t.path[0])}-D"
        )
        paths.append(t.path)
        timestamps.append(
            [_dt.fromisoformat(ts).timestamp() for ts in t.times]
        )
        properties.append(
            {"color": _TRACK_COLORS[(t.type_id - 1) % len(_TRACK_COLORS)]}
        )
    return format_trips(paths, timestamps=timestamps, properties=properties)
```

- [ ] **Step 3: Update ibm_ui — replace time controls with trips_animation_ui**

In `ibm_ui()`, replace lines 148-151:

```python
                ui.hr(),
                ui.h6("Time Filter"),
                ui.output_ui("time_range_controls"),
```

with:

```python
                ui.hr(),
                ui.h6("Animation"),
                trips_animation_ui("ibm_trips") if trips_animation_ui else ui.p("Animation requires shiny_deckgl", class_="text-muted small"),
```

- [ ] **Step 4: Add screenshot_widget to map widgets in ibm_ui**

This will be done in Task 7 when we update `_update_ibm_map`.

- [ ] **Step 5: Run adapter tests**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_ibm_trips.py::test_tracks_to_trips_basic tests/test_ibm_trips.py::test_tracks_to_trips_empty tests/test_ibm_trips.py::test_tracks_to_trips_preserves_colors tests/test_ibm_trips.py::test_tracks_to_trips_timestamps_are_floats tests/test_ibm_trips.py::test_tracks_to_trips_timestamps_monotonic -v --tb=short
```

Expected: All 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/ibm.py
git commit -m "feat(ibm): add trips imports, _tracks_to_trips adapter, replace time UI with trips_animation_ui"
```

---

## Task 7: IBM — Replace path_layer with trips_layer in Server

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/ibm.py:193-374` (ibm_server function)

- [ ] **Step 1: Add trips_animation_server call at top of ibm_server**

In `ibm_server()`, right after `_map = MapWidget(...)` and before any reactive definitions, add:

```python
    if trips_animation_server is not None:
        anim = trips_animation_server("ibm_trips", widget=_map, session=session)
    else:
        anim = None
```

- [ ] **Step 2: Remove time_range_controls render function**

Delete the entire `@render.ui def time_range_controls():` block (lines 253-264).

- [ ] **Step 3: Replace path_layer track rendering with trips_layer in _update_ibm_map**

In `_update_ibm_map()`, replace the time filtering and per-track path_layer construction block (lines 276-316) with trips_layer construction:

Remove:
```python
        try:
            tmin = input.tmin()
            tmax = input.tmax()
        except Exception:
            tmin, tmax = None, None

        filtered = filter_by_time(tracks, tmin, tmax)
```

Replace with:
```python
        filtered = tracks  # trips_layer handles time via animation controls
```

Replace the per-track `path_layer()` construction (inside the `for track in filtered:` loop, the `if show_trk:` block with `layers.append(path_layer(...))`) with a single `trips_layer` call after the loop:

After the `for track in filtered:` loop, and after the start/end point collection, add:

```python
        if show_trk and filtered:
            trips_data = _tracks_to_trips(filtered)
            if trips_data:
                trail_len = anim.trail() if anim else 180
                layers.append(trips_layer(
                    "particle-trips",
                    trips_data,
                    getColor="@@d.color",
                    trailLength=trail_len,
                    widthMinPixels=2,
                    pickable=True,
                ))
```

Remove the old per-track `if show_trk: layers.append(path_layer(...))` block from inside the loop.

- [ ] **Step 4: Add screenshot_widget to the widgets list**

In the `_map.update()` call (around line 358), add `screenshot_widget`:

```python
        await _map.update(
            session,
            layers=layers,
            view_state={"longitude": lon, "latitude": lat, "zoom": zoom, "pitch": 0, "bearing": 0},
            transition_duration=300,
            widgets=[
                zoom_widget(),
                fullscreen_widget(placement="top-right"),
                screenshot_widget(placement="top-right"),
                info_widget(placement="top-left"),
                context_menu_widget(),
            ],
        )
```

- [ ] **Step 5: Run all IBM tests**

```bash
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_ibm_trips.py tests/test_ibm.py -v --tb=short
```

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add shyfem-ui/shyfem_ui/pages/ibm.py
git commit -m "feat(ibm): replace path_layer with trips_layer, add trips_animation_server and screenshot_widget"
```

---

## Task 8: Full Test Suite Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full Python test suite**

```bash
cd /home/razinka/shyfem/shyfem-ui
CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: 1533+ passed, 0 failed (may have a few more tests now).

- [ ] **Step 2: Fix any broken existing tests**

If `test_ibm.py::test_ibm_ui_renders` fails due to UI structure changes, update it to match the new structure (trips_animation_ui instead of time_range_controls).

- [ ] **Step 3: Final commit if any test fixes needed**

```bash
git add -u
git commit -m "fix(tests): update existing tests for new widget structure"
```

---

## Task 9: Push and Summary

- [ ] **Step 1: Push to remote**

```bash
git push
```

- [ ] **Step 2: Verify commit log**

```bash
git log --oneline -8
```

Expected: 6-7 commits for this feature (2 test files, imports, checkboxes, legend, IBM adapter, IBM server).
