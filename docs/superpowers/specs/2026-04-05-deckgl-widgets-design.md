# shiny_deckgl v1.9.1 Widget Integration Design

**Date:** 2026-04-05
**Scope:** Add 5 new deck.gl widgets to existing SHYFEM UI pages
**Approach:** Widgets only — no simplification of existing manual geometry code

---

## Goal

Integrate `layer_legend_widget`, `opacity_control`, `screenshot_widget`, `timeline_control`, and `trips_layer` from shiny_deckgl v1.9.1 into the SHYFEM UI. This adds layer toggles, per-layer opacity sliders, map export, and animated particle playback without modifying the battle-tested manual mesh rendering code.

---

## Component 1: grid_map — layer_legend_widget, opacity_control, screenshot_widget

**File:** `shyfem_ui/components/grid_map.py`

### Import changes

Add to the second `try/except` import block (the one with `MapWidget`):

```python
from shiny_deckgl import (
    MapWidget,
    fullscreen_widget,
    layer_legend_widget,
    legend_control,
    opacity_control,
    screenshot_widget,
    zoom_widget,
)
```

Keep `legend_control` imported for backward compatibility in case any external code references it.

### grid_map_ui() changes

- Add `screenshot_widget(placement="top-right")` to the map widget list
- Remove the 3 manual toggle checkboxes: EMODnet (`input.show_emodnet`), Boundaries (`input.show_boundaries`), Nodes (`input.show_nodes`). These are replaced by `layer_legend_widget` checkboxes + `opacity_control` sliders.

### build_layers() / _update_map() changes

Replace the manual `legend_control(entries=[...])` construction (~30 lines that build entries per layer) with:

```python
layer_legend_widget(
    auto_introspect=True,
    show_checkbox=True,
    label_map=_build_label_map(layers),  # dynamically built from active layers
    # Static entries: "emodnet-bathy" → "EMODnet Bathymetry",
    #   "mesh-wireframe" → "Wireframe", "node-scatter" → "Nodes", etc.
    # Boundary entries built dynamically: "boundary-coastline" → "Coastline",
    #   "boundary-island" → "Island", etc. (one per boundary type in the grid)
    title="Layers",
)
```

Add `opacity_control()` with:

```python
opacity_control(
    base_layers={"emodnet-bathy": "EMODnet Bathymetry"},
    over_layers={
        "mesh-wireframe": "Wireframe",
        "depth-triangles": "Depth",
        "node-scatter": "Nodes",
    },
)
```

### Reactive handler removal

Remove the reactive handlers for `input.show_emodnet`, `input.show_boundaries`, `input.show_nodes` — the layer_legend_widget handles visibility toggling via its built-in checkboxes.

### What stays unchanged

- All view modes: mesh, depth, depth_3d, quality, partitions, boundaries
- All layer-building functions: `_build_edge_data`, `_build_mesh_geometry`, `_build_boundary_data`, `_build_node_data`
- Palette selection, CRS dropdown, elevation slider
- Click/tooltip handling
- None guard fallback when shiny_deckgl is not installed

---

## Component 2: IBM page — trips_layer, timeline_control, screenshot_widget

**File:** `shyfem_ui/pages/ibm.py`

### Import changes

```python
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
```

Remove `path_layer` import (no longer used for track rendering).

### ibm_ui() changes

- Remove the From/To time-range select dropdowns from sidebar
- Add `trips_animation_ui("ibm_trips")` in their place (speed slider, trail length, play/pause)
- Add `screenshot_widget(placement="top-right")` to map widgets

### ibm_server() changes

- Remove manual time filtering: the `_filtered_tracks` reactive, `filter_by_time()` calls
- Remove manual `path_layer()` construction for particle tracks
- Add track-to-trips adapter: convert `list[ParticleTrack]` to trips format using `format_trips()`. If `format_trips` expects a different structure than our `ParticleTrack`, write a small adapter (~5-10 lines) converting ISO time strings to numeric timestamps and restructuring fields.
- Replace `path_layer` with `trips_layer(id="particle-trips", data=trips_data, ...)`
- Call `trips_animation_server("ibm_trips", widget=_map, session=session)` to wire controls to map
- Keep `scatterplot_layer` for start/end points (static, not animated)
- Keep track statistics panel unchanged

### What stays unchanged

- Start/end point scatterplots
- Track statistics panel and computation
- Basemap selector, EMODnet toggle
- LgrService loading
- Legend control (tracks + start/end entries)
- None guard fallback

---

## Testing Strategy (TDD)

### New test file: `tests/test_grid_map_widgets.py` (~8 tests)

| Test | Asserts |
|------|---------|
| `test_grid_map_ui_contains_screenshot_widget` | UI HTML includes screenshot widget |
| `test_grid_map_ui_contains_opacity_control` | UI HTML includes opacity control |
| `test_grid_map_ui_no_manual_toggle_checkboxes` | No `show_emodnet`, `show_boundaries`, `show_nodes` checkbox IDs |
| `test_layer_legend_widget_replaces_legend_control` | `layer_legend_widget` called with `auto_introspect=True` |
| `test_label_map_covers_all_layer_ids` | label_map has entries for all layer IDs from `build_layers()` |
| `test_opacity_control_has_base_and_over` | Both `base_layers` and `over_layers` dicts populated |
| `test_build_layers_no_manual_legend_entries` | No manual legend entry list construction |
| `test_grid_map_ui_fallback_without_deckgl` | None guard returns alert div |

### New test file: `tests/test_ibm_trips.py` (~8 tests)

| Test | Asserts |
|------|---------|
| `test_ibm_ui_no_time_range_dropdowns` | No `time_from`/`time_to` select IDs in UI |
| `test_ibm_ui_contains_trips_animation_ui` | Trips animation controls present |
| `test_ibm_ui_contains_screenshot_widget` | Screenshot widget present |
| `test_format_tracks_to_trips` | Adapter converts ParticleTrack list correctly |
| `test_format_tracks_empty_list` | Empty input → empty output |
| `test_format_tracks_preserves_type_colors` | Per-type RGBA colors maintained |
| `test_format_tracks_timestamps_numeric` | ISO strings → float timestamps |
| `test_trips_layer_replaces_path_layer` | `trips_layer` used, `path_layer` not imported |

### Existing tests to update

- `test_ibm.py::test_ibm_ui_renders` — may need update if UI structure changes
- Any tests asserting on toggle checkbox presence in grid_map UI

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| `layer_legend_widget` auto-introspect misses dynamic layers | Verify with all 6 view modes; fall back to manual entries if needed |
| `format_trips` incompatible with `ParticleTrack` | Write adapter; test with real .lgr file if available |
| `opacity_control` conflicts with existing layer visibility logic | Remove old toggle handlers first, test toggle-free rendering |
| `trips_animation_server` timing issues | xfail timing-sensitive tests if needed |
| Widgets not rendering in Shiny Server proxy | Test with existing deployment if accessible |

---

## Out of Scope

- Manual geometry code simplification (deferred to Part B)
- `splitter_widget`, `theme_widget`, `compass_widget`, `scale_widget`
- Visualize page migration from Plotly to deck.gl
- New layer types (contour_layer, heatmap_layer)
