# Design: deck.gl Grid Map Component

**Date:** 2026-03-02
**Status:** Approved
**Replaces:** `shyfem_ui/components/grid_map.py` (Plotly-based)

## Problem

The current interactive map in Mesh Builder and Grid Preparation uses Plotly `Scattergl`
with line-segment wireframes. This produces a "fan-like" appearance where edges radiate
from shared nodes, depth is shown as scattered dots rather than filled triangles, and
there is no geographic basemap context.

## Solution

Replace the Plotly grid map component with `shiny_deckgl` (v1.0.1), leveraging GPU-accelerated
WebGL rendering via deck.gl for proper filled-polygon mesh visualization on a geographic basemap.

## Architecture

### Data Transformation Pipeline

```
GrdFile → _build_triangle_data(grd) → list[dict] → polygon_layer()
GrdFile → _build_edge_data(grd)     → list[dict] → path_layer()   (wireframe)
GrdFile → _build_boundary_data(grd) → list[dict] → path_layer()   (boundaries)
GrdFile → _build_node_data(grd)     → list[dict] → scatterplot_layer() (nodes)
```

### Coordinate Handling

Mesh coordinates (lat/lon or UTM) are converted to [longitude, latitude] for deck.gl.
UTM coordinates use the existing `to_geographic()` in `parser_grd.py`.

### Layer Composition Per Mode

| Mode         | Layers                                     | Camera         |
|--------------|-------------------------------------------|----------------|
| `mesh`       | wireframe `path_layer` (blue edges)       | 2D (pitch=0)   |
| `depth`      | filled `polygon_layer` + thin wireframe   | 2D (pitch=0)   |
| `depth_3d`   | extruded `polygon_layer` (3D bathymetry)  | 3D (pitch=45)  |
| `boundaries` | light wireframe + bold boundary paths     | 2D (pitch=0)   |
| `quality`    | filled `polygon_layer` (RdYlGn) + wireframe | 2D (pitch=0) |
| `partitions` | filled `polygon_layer` (partition colors) | 2D (pitch=0)   |

### Basemap

CARTO Positron (default), with selector for CARTO Dark and OSM Liberty.

## Component API

Same Shiny module interface as the current component (drop-in replacement):

```python
# UI
grid_map_ui("mesh_preview", height="600px")

# Server
grid_map_server("mesh_preview", grd_file=preview_grd)
```

### UI Controls

- **View mode** dropdown: Mesh, Depth, Depth 3D, Boundaries, Quality
- **Colorscale** selector: Viridis, Plasma, Ocean, Thermal, Chlorophyll
- **Elevation scale** slider: 1x–50x (visible only in depth_3d mode)
- **Basemap** selector: Positron / Dark / OSM
- **Show boundaries** checkbox
- **Show nodes** checkbox
- **Node inspect panel** below the map

## Data Transformation Functions

### `_build_triangle_data(grd, mode, colorscale, partition_map)`

Converts GrdFile triangles to polygon_layer data:

```python
{
    "polygon": [[lon1,lat1], [lon2,lat2], [lon3,lat3]],
    "fill_color": [R, G, B, A],
    "elevation": float,       # for 3D mode
    "depth": float,           # average of 3 vertex depths
    "quality": float,         # min(sides)/max(sides)
    "elem_id": int,
}
```

Color computation per mode:
- **depth/depth_3d**: `color_bins()` or `color_quantiles()` mapping depth → palette
- **quality**: RdYlGn scale, quality ratio 0→1
- **partitions**: 20-color partition palette
- **mesh**: not used (wireframe only)

### `_build_edge_data(grd)`

Converts mesh edges to wireframe path_layer data. **Deduplicates shared edges** — each
edge appears once (collected via sorted node-id pair set). Halves wireframe data vs current.

```python
{"path": [[lon1,lat1], [lon2,lat2]]}
```

### `_build_boundary_data(grd)`

Converts boundary lines grouped by `line_type`:

```python
{line_type: [{"path": [[lon1,lat1], [lon2,lat2], ...], "line_id": int}, ...]}
```

Each boundary type rendered as a separate `path_layer` with distinct color:
- Type 1 (exterior): red
- Type 2 (holes): green
- Additional types: orange, purple, teal, etc.

### `_build_node_data(grd)`

Converts nodes to scatterplot_layer data:

```python
{"position": [lon, lat], "node_id": int, "depth": float, "type": int}
```

## View State Management

- On data load: compute bounding box from all node coordinates
- Call `fit_bounds([[min_lon, min_lat], [max_lon, max_lat]])` to auto-center
- 3D mode sets `pitch=45, bearing=-30` for perspective view
- 2D modes reset to `pitch=0, bearing=0`

## Tooltip & Interaction

- **Hover on triangle**: Element ID, average depth, quality ratio
- **Hover on boundary**: Boundary type, line ID
- **Click on node** (when nodes visible): Populates inspect panel below map
- **Map click**: Feeds `selected_node` reactive for downstream use

## Performance

- deck.gl GPU rendering: 100k+ polygons at 60fps
- Edge deduplication: ~50% less wireframe data
- Layers sent via `map_widget.update()` — mode changes only resend layer config
- Binary attribute transport available as future optimization for very large meshes

## Files Changed

- **Replace**: `shyfem_ui/components/grid_map.py` (full rewrite)
- **Update**: `shyfem_ui/pages/mesh_builder.py` (import change, add head_includes)
- **Update**: `shyfem_ui/pages/grid_prep.py` (import change, add head_includes)
- **Update**: `shyfem_ui/app.py` (add `head_includes()` to page layout)
- **New tests**: `tests/test_grid_map_deckgl.py`
- **Update tests**: `tests/test_grid_map.py` (adapt to new API)

## Dependencies

- `shiny_deckgl` v1.0.1 (already installed)
- No new dependencies required
