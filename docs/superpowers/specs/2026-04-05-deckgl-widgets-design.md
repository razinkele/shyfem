# shiny_deckgl v1.9.1 Widget Integration Design

**Date:** 2026-04-05
**Scope:** Add 4 new deck.gl widgets to existing SHYFEM UI pages
**Approach:** Widgets only — no simplification of existing manual geometry code

---

## Goal

Integrate `layer_legend_widget`, `screenshot_widget`, `trips_layer`, and `trips_animation_ui/server` from shiny_deckgl v1.9.1 into the SHYFEM UI. This adds layer toggles with checkboxes, map export, and animated particle playback without modifying the battle-tested manual mesh rendering code.

**Note:** `opacity_control` is excluded — it operates on MapLibre style layers, not deck.gl layers. Our mesh/wireframe/node layers are deck.gl layers and would be invisible to the MapLibre opacity plugin. `timeline_control` is excluded — the IBM animation uses the dedicated `trips_animation_ui/server` API from `shiny_deckgl.ibm` which is purpose-built for `trips_layer` playback.

---

## Component 1: grid_map — layer_legend_widget, screenshot_widget

**File:** `shyfem_ui/components/grid_map.py`

### Import changes

Add to the second `try/except` import block (the one with `MapWidget`):

```python
from shiny_deckgl import (
    MapWidget,
    fullscreen_widget,
    layer_legend_widget,
    legend_control,
    screenshot_widget,
    zoom_widget,
)
```

Keep `legend_control` imported for backward compatibility.

### grid_map_ui() changes

- Add `screenshot_widget(placement="top-right")` to the map widget list
- Remove the 3 manual toggle checkboxes at lines 1313-1315: `show_boundaries`, `show_nodes`, `show_emodnet`. Their visibility role is replaced by `layer_legend_widget` checkboxes.

### _update_map() changes

Replace the existing `legend_control(legend_entries, position="bottom-right", title="Layers")` call (which passes a list of dicts as the first positional arg) with:

```python
layer_legend_widget(
    auto_introspect=True,
    show_checkbox=True,
    label_map=_build_label_map(layers),
    placement="bottom-right",
    title="Layers",
)
```

Add a helper function `_build_label_map(layers: list[dict]) -> dict[str, str]` that builds the label map from active layer IDs:
- Static entries: `"emodnet-bathy"` → `"EMODnet Bathymetry"`, `"mesh-wireframe"` → `"Wireframe"`, `"node-scatter"` → `"Nodes"`, `"depth-triangles"` → `"Depth"`, `"quality-triangles"` → `"Quality"`, `"partition-triangles"` → `"Partitions"`
- Dynamic boundary entries: iterate layers, for any ID starting with `"boundary-"`, map to a friendly name (e.g., `"boundary-coastline"` → `"Coastline"`)

### Toggle checkbox removal

The 3 toggle checkboxes (`show_emodnet`, `show_boundaries`, `show_nodes`) are consumed inline inside `_update_map()` — they're passed to `build_layers()` as boolean args. To remove them:
1. Delete the 3 `ui.input_checkbox(...)` calls from `grid_map_ui()`
2. In `_update_map()`, remove the `input.show_emodnet()`, `input.show_boundaries()`, `input.show_nodes()` reads
3. In `build_layers()`, remove the `show_emodnet`, `show_boundaries`, `show_nodes` parameters — always include all layers. The `layer_legend_widget` checkboxes handle visibility client-side via deck.gl's built-in layer visibility system.

### What stays unchanged

- All view modes: mesh, depth, depth_3d, quality, partitions, boundaries
- All layer-building functions: `_build_edge_data`, `_build_mesh_geometry`, `_build_boundary_data`, `_build_node_data`
- Palette selection, CRS dropdown, elevation slider
- Click/tooltip handling
- None guard fallback when shiny_deckgl is not installed

---

## Component 2: IBM page — trips_layer, trips_animation_ui/server, screenshot_widget

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

- Remove the `ui.output_ui("time_range_controls")` call and its `ui.h6("Time Filter")` label from the sidebar (lines 149-151). The From/To dropdowns are rendered dynamically by `@render.ui def time_range_controls()` — remove that render function too.
- Add `trips_animation_ui("ibm_trips")` in the sidebar where the time controls were (provides speed slider, trail length slider, play/pause/reset buttons)
- Add `screenshot_widget(placement="top-right")` to the map widgets
- Keep the `show_tracks`, `show_starts`, `show_ends` checkboxes — `show_tracks` toggles whether the `trips_layer` is included in the update, `show_starts`/`show_ends` control the scatterplot layers as before.

### ibm_server() changes

- Remove the `time_range_controls` render function (the @render.ui that generates From/To selects)
- Remove the inline time filtering at lines 276-282 of `_update_ibm_map()`: the `try/except` block that reads `input.tmin()`/`input.tmax()` and calls `filter_by_time(tracks, tmin, tmax)`. Use `tracks` directly instead of `filtered`. Also remove `filter_by_time` from the import on line 31.
- Remove manual `path_layer()` construction for particle tracks
- Add track-to-trips adapter function `_tracks_to_trips(tracks: list[ParticleTrack]) -> list[dict]`:
  ```python
  def _tracks_to_trips(tracks):
      from datetime import datetime
      paths = []
      timestamps = []
      properties = []
      for t in tracks:
          # Guard: format_trips ignores timestamps arg if path has 3+ coords
          assert all(len(p) == 2 for p in t.path), (
              f"ParticleTrack paths must be 2-D [lon,lat], got {len(t.path[0])}-D"
          )
          paths.append(t.path)
          timestamps.append(
              [datetime.fromisoformat(ts).timestamp() for ts in t.times]
          )
          properties.append(
              {"color": _TRACK_COLORS[(t.type_id - 1) % len(_TRACK_COLORS)]}
          )
      return format_trips(paths, timestamps=timestamps, properties=properties)
  ```
  This converts ISO time strings (from `ParticleTrack.times`) to Unix epoch floats via `datetime.fromisoformat().timestamp()`, and passes per-track colors via `properties`. The 2-D assertion guards against `format_trips` silently ignoring the `timestamps` arg when paths have a third coordinate.
- Replace `path_layer` track rendering with `trips_layer(id="particle-trips", data=trips_data, ...)`
- Call `anim = trips_animation_server("ibm_trips", widget=_map, session=session)` at the **top level of `ibm_server()`** (not inside a reactive — it registers its own internal reactives via `@module.server`). The return value is a `SimpleNamespace` with `.speed()` and `.trail()` reactive callables — pass these to `trips_layer(currentTime=anim.speed(), trailLength=anim.trail())` so the animation panel sliders control playback.
- Keep `scatterplot_layer` for start/end points (static, not animated)
- Keep track statistics panel unchanged

### What stays unchanged

- Start/end point scatterplots and their `show_starts`/`show_ends` toggles
- Track statistics panel and computation
- Basemap selector, EMODnet toggle (kept as server-side toggle because IBM doesn't use `layer_legend_widget` — the IBM page has a simple fixed layer set unlike grid_map's dynamic view modes)
- LgrService loading
- None guard fallback

---

## Testing Strategy (TDD)

### New test file: `tests/test_grid_map_widgets.py` (~7 tests)

Tests use `unittest.mock.patch` to intercept widget function calls, since widgets are JS dicts pushed via async `_map.update()`, not embedded in static UI HTML.

| Test | Asserts |
|------|---------|
| `test_grid_map_ui_no_manual_toggle_checkboxes` | UI HTML string does not contain `show_emodnet`, `show_boundaries`, `show_nodes` checkbox IDs |
| `test_grid_map_ui_still_renders_without_deckgl` | When MapWidget is None, returns alert div (existing guard) |
| `test_build_label_map_static_entries` | `_build_label_map` returns correct friendly names for known layer IDs |
| `test_build_label_map_dynamic_boundaries` | `_build_label_map` generates entries for boundary layer IDs |
| `test_build_layers_always_includes_all` | `build_layers` no longer takes show_emodnet/show_boundaries/show_nodes params |
| `test_screenshot_widget_in_imports` | `screenshot_widget` is not None (shiny_deckgl installed) |
| `test_layer_legend_widget_in_imports` | `layer_legend_widget` is not None (shiny_deckgl installed) |

### New test file: `tests/test_ibm_trips.py` (~8 tests)

| Test | Asserts |
|------|---------|
| `test_ibm_ui_no_time_range_output` | UI HTML string does not contain `time_range_controls` output ID |
| `test_ibm_ui_contains_trips_animation_ui` | UI HTML string contains trips animation module ID |
| `test_tracks_to_trips_basic` | `_tracks_to_trips` converts a list of ParticleTracks to list of dicts with `path` and `timestamps` keys |
| `test_tracks_to_trips_empty` | Empty input → empty output |
| `test_tracks_to_trips_preserves_colors` | Per-type RGBA colors from `_TRACK_COLORS` are in output `properties` |
| `test_tracks_to_trips_timestamps_are_floats` | Output timestamps are Unix epoch floats (not ISO strings) |
| `test_tracks_to_trips_timestamps_monotonic` | Output timestamps are monotonically increasing per track |
| `test_path_layer_not_imported` | `path_layer` is not in `ibm.py` imports (verify via source inspection or mock) |

### Existing tests to update

- `test_ibm.py::test_ibm_ui_renders` — UI structure changed (trips_animation_ui replaces time_range_controls)
- `test_grid_map.py` or similar — remove any assertions on toggle checkbox presence

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| `layer_legend_widget` auto-introspect misses dynamic layers | Verify with all 6 view modes; fall back to manual entries if needed |
| `format_trips` timestamp format incompatible | Adapter converts via `datetime.fromisoformat().timestamp()`; tested explicitly |
| `trips_animation_server` placement matters | Must be called at top level of `ibm_server()`, not inside a reactive |
| `layer_legend_widget` checkbox toggles don't affect deck.gl layer visibility | Test with real MapWidget; if broken, fall back to manual entries with `show_checkbox=False` |
| Widgets not rendering in Shiny Server proxy | Test with existing deployment if accessible |

---

## Out of Scope

- `opacity_control` — operates on MapLibre style layers, incompatible with deck.gl layers
- `timeline_control` — IBM uses `trips_animation_ui/server` instead (purpose-built for trips)
- Manual geometry code simplification (deferred to Part B)
- `splitter_widget`, `theme_widget`, `compass_widget`, `scale_widget`
- Visualize page migration from Plotly to deck.gl
- New layer types (contour_layer, heatmap_layer)
