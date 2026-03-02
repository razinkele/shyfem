# deck.gl Grid Map Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Plotly-based grid map component with a shiny_deckgl MapWidget that renders filled triangles on a geographic basemap, with 3D bathymetry view.

**Architecture:** GrdFile data is converted through 4 builder functions into deck.gl layer dicts (polygon_layer for filled triangles, path_layer for wireframe/boundaries, scatterplot_layer for nodes). A MapWidget provides GPU-accelerated WebGL rendering with auto-fit bounds, mode switching, and tooltip interaction. The component keeps the same Shiny module interface so both mesh_builder.py and grid_prep.py can use it as a drop-in replacement.

**Tech Stack:** shiny_deckgl 1.0.1, Shiny for Python 1.5.1, deck.gl polygon/path/scatterplot layers, CARTO/OSM basemaps.

---

### Task 1: Data Builder — `_get_lonlat` Coordinate Helper

**Files:**
- Create: `shyfem_ui/components/grid_map.py` (full rewrite, start fresh)
- Test: `tests/test_grid_map.py` (rewrite for new API)

**Step 1: Write the failing test**

In `tests/test_grid_map.py`, replace all contents with:

```python
"""Tests for deck.gl grid map component."""

import numpy as np

from shyfem_ui.services.parser_grd import (
    CoordinateSystem,
    Element,
    GrdFile,
    Line,
    Node,
)


# -- Test fixtures --

def _make_triangle_grid() -> GrdFile:
    """Minimal grid: one triangle, geographic coords (lon/lat)."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=-0.8, y=37.7, depth=1.0),
        2: Node(id=2, node_type=0, x=-0.7, y=37.7, depth=2.0),
        3: Node(id=3, node_type=0, x=-0.75, y=37.8, depth=3.0),
    }
    grd.elements = {
        1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),
    }
    grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
    return grd


def _make_multi_grid() -> GrdFile:
    """Two triangles sharing edge 2-3, with boundary line."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=-0.8, y=37.7, depth=1.0),
        2: Node(id=2, node_type=0, x=-0.7, y=37.7, depth=2.0),
        3: Node(id=3, node_type=0, x=-0.75, y=37.8, depth=3.0),
        4: Node(id=4, node_type=0, x=-0.65, y=37.8, depth=1.5),
    }
    grd.elements = {
        1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),
        2: Element(id=2, elem_type=0, nodes=[2, 4, 3]),
    }
    grd.lines = {
        1: Line(id=1, line_type=1, nodes=[1, 3, 2]),
    }
    grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
    return grd


# -- Tests for _get_lonlat --

class TestGetLonLat:
    """Test coordinate extraction and conversion."""

    def test_geographic_returns_xy(self):
        from shyfem_ui.components.grid_map import _get_lonlat
        grd = _make_triangle_grid()
        coords = _get_lonlat(grd)
        # Geographic: x=lon, y=lat → returns {node_id: [lon, lat]}
        assert coords[1] == [-0.8, 37.7]
        assert coords[3] == [-0.75, 37.8]

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import _get_lonlat
        grd = GrdFile()
        coords = _get_lonlat(grd)
        assert coords == {}

    def test_cartesian_returns_xy_as_is(self):
        from shyfem_ui.components.grid_map import _get_lonlat
        grd = GrdFile()
        grd.nodes = {1: Node(id=1, node_type=0, x=100.0, y=200.0)}
        grd.coordinate_system = CoordinateSystem(CoordinateSystem.CARTESIAN)
        coords = _get_lonlat(grd)
        assert coords[1] == [100.0, 200.0]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestGetLonLat -v`
Expected: FAIL — `ImportError: cannot import name '_get_lonlat'`

**Step 3: Write minimal implementation**

Create `shyfem_ui/components/grid_map.py` with:

```python
"""Interactive grid map component using deck.gl via shiny_deckgl.

Provides GPU-accelerated mesh visualization with:
- Filled triangle polygons with depth/quality coloring
- Mesh wireframe overlay
- Boundary line highlighting
- 3D extruded bathymetry view
- Geographic basemap (CARTO/OSM)
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from shiny import module, reactive, render, ui
from shiny_deckgl import (
    CARTO_DARK,
    CARTO_POSITRON,
    MapWidget,
    OSM_LIBERTY,
    PALETTE_CHLOROPHYLL,
    PALETTE_OCEAN,
    PALETTE_PLASMA,
    PALETTE_THERMAL,
    PALETTE_VIRIDIS,
    color_bins,
    head_includes,
    path_layer,
    polygon_layer,
    scatterplot_layer,
    zoom_widget,
)

from shyfem_ui.services.parser_grd import CoordinateSystem, GrdFile

# Boundary type colors (up to 8 types)
BOUNDARY_COLORS: list[list[int]] = [
    [231, 76, 60, 255],   # red
    [46, 204, 113, 255],  # green
    [243, 156, 18, 255],  # orange
    [155, 89, 182, 255],  # purple
    [26, 188, 156, 255],  # teal
    [230, 126, 34, 255],  # dark orange
    [52, 152, 219, 255],  # blue
    [233, 30, 99, 255],   # pink
]

# Partition colors (20 distinct, RGBA)
PARTITION_COLORS: list[list[int]] = [
    [31, 119, 180, 200], [255, 127, 14, 200], [44, 160, 44, 200],
    [214, 39, 40, 200], [148, 103, 189, 200], [140, 86, 75, 200],
    [227, 119, 194, 200], [127, 127, 127, 200], [188, 189, 34, 200],
    [23, 190, 207, 200], [174, 199, 232, 200], [255, 187, 120, 200],
    [152, 223, 138, 200], [255, 152, 150, 200], [197, 176, 213, 200],
    [196, 156, 148, 200], [247, 182, 210, 200], [199, 199, 199, 200],
    [219, 219, 141, 200], [158, 218, 229, 200],
]

# Palette lookup
PALETTES = {
    "Viridis": PALETTE_VIRIDIS,
    "Plasma": PALETTE_PLASMA,
    "Ocean": PALETTE_OCEAN,
    "Thermal": PALETTE_THERMAL,
    "Chlorophyll": PALETTE_CHLOROPHYLL,
}

# Basemap lookup
BASEMAPS = {
    "Positron": CARTO_POSITRON,
    "Dark": CARTO_DARK,
    "OSM": OSM_LIBERTY,
}


def _get_lonlat(grd: GrdFile) -> dict[int, list[float]]:
    """Extract [longitude, latitude] for each node.

    For geographic coordinates, x=longitude, y=latitude.
    For Cartesian/UTM, returns [x, y] as-is (deck.gl will render
    in a flat coordinate space).
    """
    if not grd.nodes:
        return {}
    return {nid: [n.x, n.y] for nid, n in grd.nodes.items()}
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestGetLonLat -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): start deck.gl grid map — coordinate helper"
```

---

### Task 2: Data Builder — `_build_edge_data` (Deduplicated Wireframe)

**Files:**
- Modify: `shyfem_ui/components/grid_map.py`
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestBuildEdgeData:
    """Test wireframe edge extraction with deduplication."""

    def test_single_triangle_has_3_edges(self):
        from shyfem_ui.components.grid_map import _build_edge_data
        grd = _make_triangle_grid()
        edges = _build_edge_data(grd)
        assert len(edges) == 3

    def test_shared_edge_deduplicated(self):
        from shyfem_ui.components.grid_map import _build_edge_data
        grd = _make_multi_grid()
        edges = _build_edge_data(grd)
        # 2 triangles, 5 unique edges (shared edge 2-3 counted once)
        assert len(edges) == 5

    def test_edge_has_path_key(self):
        from shyfem_ui.components.grid_map import _build_edge_data
        grd = _make_triangle_grid()
        edges = _build_edge_data(grd)
        assert "path" in edges[0]
        assert len(edges[0]["path"]) == 2  # two endpoints

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import _build_edge_data
        grd = GrdFile()
        edges = _build_edge_data(grd)
        assert edges == []
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildEdgeData -v`
Expected: FAIL — `ImportError: cannot import name '_build_edge_data'`

**Step 3: Write minimal implementation**

Add to `grid_map.py` after `_get_lonlat`:

```python
def _build_edge_data(grd: GrdFile) -> list[dict]:
    """Build deduplicated wireframe edges for path_layer.

    Each edge appears once (not twice for shared triangle edges).
    Returns list of {"path": [[lon1,lat1], [lon2,lat2]]}.
    """
    if not grd.nodes or not grd.elements:
        return []
    coords = _get_lonlat(grd)
    seen: set[tuple[int, int]] = set()
    edges: list[dict] = []
    for elem in grd.elements.values():
        nids = elem.nodes
        n = len(nids)
        if n < 3:
            continue
        for i in range(n):
            j = (i + 1) % n
            key = (min(nids[i], nids[j]), max(nids[i], nids[j]))
            if key in seen:
                continue
            seen.add(key)
            c0 = coords.get(nids[i])
            c1 = coords.get(nids[j])
            if c0 and c1:
                edges.append({"path": [c0, c1]})
    return edges
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildEdgeData -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add deduplicated wireframe edge builder"
```

---

### Task 3: Data Builder — `_build_triangle_data` (Filled Polygons + Color)

**Files:**
- Modify: `shyfem_ui/components/grid_map.py`
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestBuildTriangleData:
    """Test filled triangle polygon data generation."""

    def test_single_triangle_mesh_mode(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = _make_triangle_grid()
        data = _build_triangle_data(grd, mode="mesh")
        # mesh mode returns empty (wireframe only, no filled polygons)
        assert data == []

    def test_depth_mode_has_fill_color(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = _make_triangle_grid()
        data = _build_triangle_data(grd, mode="depth")
        assert len(data) == 1
        tri = data[0]
        assert "polygon" in tri
        assert len(tri["polygon"]) == 3  # 3 vertices
        assert "fill_color" in tri
        assert len(tri["fill_color"]) == 4  # RGBA
        assert "depth" in tri
        assert tri["depth"] == 2.0  # avg of 1, 2, 3

    def test_quality_mode_has_quality(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = _make_triangle_grid()
        data = _build_triangle_data(grd, mode="quality")
        assert len(data) == 1
        assert "quality" in data[0]
        assert 0.0 <= data[0]["quality"] <= 1.0

    def test_depth_3d_has_elevation(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = _make_triangle_grid()
        data = _build_triangle_data(grd, mode="depth_3d", elevation_scale=10)
        assert len(data) == 1
        assert "elevation" in data[0]
        assert data[0]["elevation"] == 20.0  # avg_depth=2.0 * scale=10

    def test_partition_mode(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = _make_multi_grid()
        pmap = {1: 0, 2: 1}
        data = _build_triangle_data(grd, mode="partitions", partition_map=pmap)
        assert len(data) == 2
        # Different partitions get different colors
        assert data[0]["fill_color"] != data[1]["fill_color"]

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = GrdFile()
        data = _build_triangle_data(grd, mode="depth")
        assert data == []

    def test_no_depth_data(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=0.0, y=0.0),
            2: Node(id=2, node_type=0, x=1.0, y=0.0),
            3: Node(id=3, node_type=0, x=0.5, y=1.0),
        }
        grd.elements = {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])}
        data = _build_triangle_data(grd, mode="depth")
        assert len(data) == 1
        assert data[0]["depth"] == 0.0
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildTriangleData -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

Add to `grid_map.py`:

```python
def _compute_quality(coords: list[list[float]]) -> float:
    """Compute element quality as min(sides)/max(sides)."""
    n = len(coords)
    sides = []
    for i in range(n):
        j = (i + 1) % n
        dx = coords[j][0] - coords[i][0]
        dy = coords[j][1] - coords[i][1]
        sides.append((dx * dx + dy * dy) ** 0.5)
    return min(sides) / max(sides) if max(sides) > 0 else 0.0


def _depth_to_colors(
    depths: list[float], palette_name: str = "Viridis"
) -> list[list[int]]:
    """Map depth values to RGBA colors using color_bins."""
    if not depths:
        return []
    palette = PALETTES.get(palette_name, PALETTE_VIRIDIS)
    return color_bins(depths, n_bins=min(len(palette), 6), palette=palette)


def _quality_to_colors(qualities: list[float]) -> list[list[int]]:
    """Map quality values (0-1) to RdYlGn RGBA colors."""
    # Simple RdYlGn: red(0) → yellow(0.5) → green(1)
    colors = []
    for q in qualities:
        q = max(0.0, min(1.0, q))
        if q < 0.5:
            # Red to yellow
            t = q * 2
            r, g, b = int(215 + 40 * t), int(48 + 180 * t), int(39 + 10 * t)
        else:
            # Yellow to green
            t = (q - 0.5) * 2
            r, g, b = int(255 - 211 * t), int(228 + 16 * t), int(49 - 5 * t)
        colors.append([r, g, b, 200])
    return colors


def _build_triangle_data(
    grd: GrdFile,
    mode: str = "depth",
    colorscale: str = "Viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
) -> list[dict]:
    """Build polygon data for filled triangle rendering.

    Returns list of dicts for polygon_layer. Empty list for mesh mode
    (wireframe only, no filled polygons needed).
    """
    if mode == "mesh":
        return []
    if not grd.nodes or not grd.elements:
        return []

    coords = _get_lonlat(grd)
    triangles: list[dict] = []
    depths_list: list[float] = []
    qualities_list: list[float] = []

    for elem in grd.elements.values():
        nids = elem.nodes
        if len(nids) < 3:
            continue
        verts = [coords.get(nid) for nid in nids]
        if any(v is None for v in verts):
            continue

        node_depths = [
            grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0
            for nid in nids
        ]
        avg_depth = sum(node_depths) / len(node_depths)
        quality = _compute_quality(verts)

        tri = {
            "polygon": verts,
            "elem_id": elem.id,
            "depth": avg_depth,
            "quality": quality,
        }
        if mode in ("depth_3d",):
            tri["elevation"] = avg_depth * elevation_scale

        depths_list.append(avg_depth)
        qualities_list.append(quality)
        triangles.append(tri)

    if not triangles:
        return []

    # Assign colors based on mode
    if mode in ("depth", "depth_3d"):
        colors = _depth_to_colors(depths_list, colorscale)
        for tri, c in zip(triangles, colors):
            tri["fill_color"] = c
    elif mode == "quality":
        colors = _quality_to_colors(qualities_list)
        for tri, c in zip(triangles, colors):
            tri["fill_color"] = c
    elif mode == "partitions" and partition_map:
        for tri in triangles:
            part = partition_map.get(tri["elem_id"], 0)
            tri["fill_color"] = PARTITION_COLORS[part % len(PARTITION_COLORS)]
    elif mode == "boundaries":
        # Light fill for boundary mode background
        for tri in triangles:
            tri["fill_color"] = [200, 200, 200, 40]

    return triangles
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildTriangleData -v`
Expected: 7 passed

**Step 5: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add filled triangle polygon builder with color mapping"
```

---

### Task 4: Data Builder — `_build_boundary_data` and `_build_node_data`

**Files:**
- Modify: `shyfem_ui/components/grid_map.py`
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestBuildBoundaryData:
    """Test boundary line data extraction."""

    def test_boundary_grouped_by_type(self):
        from shyfem_ui.components.grid_map import _build_boundary_data
        grd = _make_multi_grid()
        data = _build_boundary_data(grd)
        assert 1 in data  # line_type 1
        assert len(data[1]) == 1  # one boundary line of type 1

    def test_boundary_path_has_coords(self):
        from shyfem_ui.components.grid_map import _build_boundary_data
        grd = _make_multi_grid()
        data = _build_boundary_data(grd)
        line_data = data[1][0]
        assert "path" in line_data
        assert len(line_data["path"]) == 3  # 3 nodes in boundary

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import _build_boundary_data
        grd = GrdFile()
        assert _build_boundary_data(grd) == {}


class TestBuildNodeData:
    """Test node scatter data extraction."""

    def test_node_count(self):
        from shyfem_ui.components.grid_map import _build_node_data
        grd = _make_triangle_grid()
        data = _build_node_data(grd)
        assert len(data) == 3

    def test_node_has_position(self):
        from shyfem_ui.components.grid_map import _build_node_data
        grd = _make_triangle_grid()
        data = _build_node_data(grd)
        assert "position" in data[0]
        assert len(data[0]["position"]) == 2

    def test_node_has_metadata(self):
        from shyfem_ui.components.grid_map import _build_node_data
        grd = _make_triangle_grid()
        data = _build_node_data(grd)
        assert "node_id" in data[0]
        assert "depth" in data[0]

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import _build_node_data
        grd = GrdFile()
        assert _build_node_data(grd) == []
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildBoundaryData tests/test_grid_map.py::TestBuildNodeData -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

Add to `grid_map.py`:

```python
def _build_boundary_data(grd: GrdFile) -> dict[int, list[dict]]:
    """Build boundary line data grouped by line_type.

    Returns {line_type: [{"path": [[lon,lat], ...], "line_id": int}, ...]}.
    """
    if not grd.nodes or not grd.lines:
        return {}
    coords = _get_lonlat(grd)
    result: dict[int, list[dict]] = {}
    for line in grd.lines.values():
        path = [coords[nid] for nid in line.nodes if nid in coords]
        if len(path) < 2:
            continue
        result.setdefault(line.line_type, []).append({
            "path": path,
            "line_id": line.id,
        })
    return result


def _build_node_data(grd: GrdFile) -> list[dict]:
    """Build node scatter data for scatterplot_layer.

    Returns list of {"position": [lon,lat], "node_id": int, "depth": float, ...}.
    """
    if not grd.nodes:
        return []
    coords = _get_lonlat(grd)
    return [
        {
            "position": coords[nid],
            "node_id": nid,
            "depth": n.depth if n.depth is not None else 0.0,
            "node_type": n.node_type,
        }
        for nid, n in grd.nodes.items()
        if nid in coords
    ]
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildBoundaryData tests/test_grid_map.py::TestBuildNodeData -v`
Expected: 7 passed

**Step 5: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add boundary and node data builders"
```

---

### Task 5: Layer Assembly — `build_layers`

**Files:**
- Modify: `shyfem_ui/components/grid_map.py`
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestBuildLayers:
    """Test deck.gl layer assembly."""

    def test_mesh_mode_returns_wireframe(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="mesh")
        ids = [l["id"] for l in layers]
        assert "wireframe" in ids
        assert "triangles" not in ids

    def test_depth_mode_returns_fill_and_wireframe(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="depth")
        ids = [l["id"] for l in layers]
        assert "triangles" in ids
        assert "wireframe" in ids

    def test_depth_3d_mode_has_extruded(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="depth_3d")
        tri_layer = [l for l in layers if l["id"] == "triangles"][0]
        assert tri_layer.get("extruded") is True

    def test_boundaries_mode_adds_boundary_layers(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_multi_grid()
        layers = build_layers(grd, mode="boundaries")
        boundary_ids = [l["id"] for l in layers if l["id"].startswith("boundary_")]
        assert len(boundary_ids) >= 1

    def test_show_boundaries_adds_layers(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_multi_grid()
        layers = build_layers(grd, mode="mesh", show_boundaries=True)
        boundary_ids = [l["id"] for l in layers if l["id"].startswith("boundary_")]
        assert len(boundary_ids) >= 1

    def test_show_nodes_adds_scatter(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="mesh", show_nodes=True)
        ids = [l["id"] for l in layers]
        assert "nodes" in ids

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = GrdFile()
        layers = build_layers(grd, mode="mesh")
        assert layers == []

    def test_partition_mode(self):
        from shyfem_ui.components.grid_map import build_layers
        grd = _make_multi_grid()
        pmap = {1: 0, 2: 1}
        layers = build_layers(grd, mode="partitions", partition_map=pmap)
        ids = [l["id"] for l in layers]
        assert "triangles" in ids
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildLayers -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

Add to `grid_map.py`:

```python
def build_layers(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "Viridis",
    show_boundaries: bool = False,
    show_nodes: bool = False,
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
) -> list[dict]:
    """Assemble deck.gl layers for the given visualization mode.

    Returns a list of layer dicts ready for MapWidget.update().
    """
    if not grd.nodes:
        return []

    layers: list[dict] = []

    # Filled triangle polygons (all modes except mesh)
    tri_data = _build_triangle_data(
        grd, mode=mode, colorscale=colorscale,
        elevation_scale=elevation_scale, partition_map=partition_map,
    )
    if tri_data:
        is_3d = mode == "depth_3d"
        layers.append(
            polygon_layer(
                "triangles",
                data=tri_data,
                getPolygon="@@d.polygon",
                getFillColor="@@d.fill_color",
                getLineColor=[0, 0, 0, 0],
                lineWidthMinPixels=0,
                extruded=is_3d,
                getElevation="@@d.elevation" if is_3d else None,
                pickable=True,
                opacity=0.85,
                autoHighlight=True,
                highlightColor=[255, 255, 255, 80],
            )
        )

    # Wireframe edges (all 2D modes)
    if mode != "depth_3d":
        edge_data = _build_edge_data(grd)
        if edge_data:
            # Thinner and lighter for depth/quality/boundaries/partitions
            is_bg = mode in ("depth", "quality", "boundaries", "partitions")
            layers.append(
                path_layer(
                    "wireframe",
                    data=edge_data,
                    getPath="@@d.path",
                    getColor=[45, 156, 186, 255] if not is_bg else [150, 150, 150, 80],
                    widthMinPixels=1 if not is_bg else 0.5,
                    pickable=False,
                )
            )

    # Boundary lines
    if show_boundaries or mode == "boundaries":
        bnd_data = _build_boundary_data(grd)
        for lt_idx, (lt, lines) in enumerate(sorted(bnd_data.items())):
            color = BOUNDARY_COLORS[lt_idx % len(BOUNDARY_COLORS)]
            layers.append(
                path_layer(
                    f"boundary_{lt}",
                    data=lines,
                    getPath="@@d.path",
                    getColor=color,
                    widthMinPixels=3,
                    pickable=True,
                )
            )

    # Node scatter
    if show_nodes:
        node_data = _build_node_data(grd)
        if node_data:
            layers.append(
                scatterplot_layer(
                    "nodes",
                    data=node_data,
                    getPosition="@@d.position",
                    getFillColor=[255, 60, 60, 220],
                    radiusMinPixels=3,
                    radiusMaxPixels=6,
                    pickable=True,
                )
            )

    return layers
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestBuildLayers -v`
Expected: 8 passed

**Step 5: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add deck.gl layer assembly function"
```

---

### Task 6: View State Helper — `_compute_view_state`

**Files:**
- Modify: `shyfem_ui/components/grid_map.py`
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestComputeViewState:
    """Test auto-fit view state calculation."""

    def test_geographic_grid_center(self):
        from shyfem_ui.components.grid_map import _compute_view_state
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd, is_3d=False)
        # Center should be average of node coords
        assert -0.8 <= vs["longitude"] <= -0.65
        assert 37.7 <= vs["latitude"] <= 37.8
        assert vs["pitch"] == 0
        assert vs["bearing"] == 0

    def test_3d_mode_tilts_camera(self):
        from shyfem_ui.components.grid_map import _compute_view_state
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd, is_3d=True)
        assert vs["pitch"] == 45
        assert vs["bearing"] == -30

    def test_empty_grid_defaults(self):
        from shyfem_ui.components.grid_map import _compute_view_state
        grd = GrdFile()
        vs = _compute_view_state(grd, is_3d=False)
        assert "longitude" in vs
        assert "latitude" in vs

    def test_returns_bounds(self):
        from shyfem_ui.components.grid_map import _compute_view_state
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd, is_3d=False)
        assert "bounds" in vs
        assert len(vs["bounds"]) == 2  # [[sw], [ne]]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestComputeViewState -v`
Expected: FAIL

**Step 3: Write minimal implementation**

Add to `grid_map.py`:

```python
def _compute_view_state(grd: GrdFile, is_3d: bool = False) -> dict:
    """Compute initial view state to fit the grid bounds.

    Returns a dict with longitude, latitude, zoom, pitch, bearing, bounds.
    """
    if not grd.nodes:
        return {
            "longitude": 0.0,
            "latitude": 0.0,
            "zoom": 2,
            "pitch": 45 if is_3d else 0,
            "bearing": -30 if is_3d else 0,
            "bounds": [[-180, -90], [180, 90]],
        }

    xmin, ymin, xmax, ymax = grd.get_bounds()
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2

    # Estimate zoom from extent (rough heuristic for geographic coords)
    dx = max(xmax - xmin, 0.001)
    dy = max(ymax - ymin, 0.001)
    extent = max(dx, dy)
    # deck.gl zoom: ~0 for 360°, ~10 for ~0.35°, ~15 for ~0.01°
    import math
    zoom = max(0, min(20, round(math.log2(360 / extent) + 0.5)))

    return {
        "longitude": cx,
        "latitude": cy,
        "zoom": zoom,
        "pitch": 45 if is_3d else 0,
        "bearing": -30 if is_3d else 0,
        "bounds": [[xmin, ymin], [xmax, ymax]],
    }
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestComputeViewState -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add auto-fit view state computation"
```

---

### Task 7: Shiny Module — `grid_map_ui` and `grid_map_server`

**Files:**
- Modify: `shyfem_ui/components/grid_map.py` (add module UI/server)
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestGridMapUI:
    """Test the Shiny module UI function."""

    def test_returns_tag(self):
        from shyfem_ui.components.grid_map import grid_map_ui
        tag = grid_map_ui("test_map")
        assert tag is not None

    def test_has_map_mode_select(self):
        from shyfem_ui.components.grid_map import grid_map_ui
        tag = grid_map_ui("test_map")
        html = str(tag)
        assert "map_mode" in html

    def test_has_basemap_select(self):
        from shyfem_ui.components.grid_map import grid_map_ui
        tag = grid_map_ui("test_map")
        html = str(tag)
        assert "basemap" in html
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestGridMapUI -v`
Expected: FAIL — the old grid_map_ui doesn't have basemap

**Step 3: Write the UI and server functions**

Add to `grid_map.py`:

```python
@module.ui
def grid_map_ui(height: str = "600px"):
    """Interactive deck.gl grid map component UI."""
    map_id = module.resolve_id("deckgl_map")
    _map_widget = MapWidget(
        id=map_id,
        view_state={"longitude": 0, "latitude": 0, "zoom": 2, "pitch": 0, "bearing": 0},
        style=CARTO_POSITRON,
        tooltip={"html": "{tooltip_html}", "style": {"fontSize": "12px"}},
        controls=[{"type": "navigation", "position": "top-right"}],
    )
    # Store on module for server access
    return ui.div(
        head_includes(),
        # Controls row
        ui.div(
            ui.div(
                ui.tags.label("View", class_="form-label small mb-0"),
                ui.input_select(
                    "map_mode",
                    "",
                    choices={
                        "mesh": "Mesh",
                        "depth": "Depth",
                        "depth_3d": "Depth 3D",
                        "boundaries": "Boundaries",
                        "quality": "Quality",
                    },
                    width="120px",
                ),
                class_="me-2",
            ),
            ui.div(
                ui.tags.label("Colors", class_="form-label small mb-0"),
                ui.input_select(
                    "colorscale",
                    "",
                    choices=list(PALETTES.keys()),
                    width="100px",
                ),
                class_="me-2",
            ),
            ui.div(
                ui.tags.label("Basemap", class_="form-label small mb-0"),
                ui.input_select(
                    "basemap",
                    "",
                    choices=list(BASEMAPS.keys()),
                    width="100px",
                ),
                class_="me-2",
            ),
            ui.panel_conditional(
                "input.map_mode === 'depth_3d'",
                ui.div(
                    ui.tags.label("Elevation", class_="form-label small mb-0"),
                    ui.input_slider("elevation_scale", "", min=1, max=50, value=10, width="120px"),
                    class_="me-2",
                ),
            ),
            ui.input_checkbox("show_boundaries", "Boundaries", value=True),
            ui.input_checkbox("show_nodes", "Nodes", value=False),
            class_="d-flex align-items-end gap-2 mb-2 flex-wrap",
        ),
        # Map widget
        _map_widget.ui(width="100%", height=height),
        # Node inspection panel
        ui.output_ui("inspect_info"),
        class_="grid-map-component",
        # Stash the widget instance as a data attribute for server retrieval
        **{"data-map-id": map_id},
    )


@module.server
def grid_map_server(
    input,
    output,
    session,
    grd_file: reactive.Value[GrdFile | None],
    partition_map: reactive.Value[dict[int, int] | None] | None = None,
    on_node_click: Callable[[int], None] | None = None,
):
    """Interactive deck.gl grid map server logic."""
    selected_node = reactive.value(None)

    map_id = module.resolve_id("deckgl_map")
    _map = MapWidget(
        id=map_id,
        view_state={"longitude": 0, "latitude": 0, "zoom": 2, "pitch": 0, "bearing": 0},
        style=CARTO_POSITRON,
        tooltip={"html": "{tooltip_html}", "style": {"fontSize": "12px"}},
        controls=[{"type": "navigation", "position": "top-right"}],
    )

    @reactive.effect
    async def _update_map():
        grd = grd_file.get()
        if grd is None:
            await _map.update(session, layers=[])
            return

        mode = input.map_mode()
        colorscale = input.colorscale()
        show_bounds = input.show_boundaries()
        show_nd = input.show_nodes()
        elev_scale = input.elevation_scale() if mode == "depth_3d" else 1.0

        pmap = None
        if partition_map is not None:
            pmap = partition_map.get()
            if pmap and mode == "mesh":
                mode = "partitions"

        layers = build_layers(
            grd,
            mode=mode,
            colorscale=colorscale,
            show_boundaries=show_bounds,
            show_nodes=show_nd,
            elevation_scale=elev_scale,
            partition_map=pmap,
        )

        vs = _compute_view_state(grd, is_3d=(mode == "depth_3d"))
        basemap = BASEMAPS.get(input.basemap(), CARTO_POSITRON)

        await _map.set_style(session, basemap)
        await _map.update(
            session,
            layers=layers,
            view_state={
                "longitude": vs["longitude"],
                "latitude": vs["latitude"],
                "zoom": vs["zoom"],
                "pitch": vs["pitch"],
                "bearing": vs["bearing"],
            },
            transition_duration=500,
            widgets=[zoom_widget(placement="top-right")],
        )

        # Fit bounds for better framing
        if vs["bounds"]:
            await _map.fit_bounds(
                session,
                bounds=vs["bounds"],
                max_zoom=18,
                duration=800,
            )

    @reactive.effect
    def _handle_click():
        click_id = f"{map_id}_click"
        click_info = input[click_id]()
        if click_info is None:
            return
        obj = click_info.get("object")
        if obj and "node_id" in obj:
            nid = obj["node_id"]
            selected_node.set(nid)
            if on_node_click:
                on_node_click(nid)

    @render.ui
    def inspect_info():
        nid = selected_node.get()
        if nid is None:
            return None
        grd = grd_file.get()
        if grd is None or nid not in grd.nodes:
            return None
        n = grd.nodes[nid]
        items = [f"Node: {nid}", f"X: {n.x:.6f}", f"Y: {n.y:.6f}"]
        if n.depth is not None:
            items.append(f"Depth: {n.depth:.4f}")
        items.append(f"Type: {n.node_type}")
        return ui.div(
            *[ui.span(s, class_="badge bg-info me-1") for s in items],
            class_="mt-2 p-2 bg-light border rounded small",
        )

    return {"selected_node": selected_node}
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestGridMapUI -v`
Expected: 3 passed

**Step 5: Run all tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py -v`
Expected: All passed

**Step 6: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add deck.gl Shiny module UI and server"
```

---

### Task 8: Integration — Wire Up `head_includes` in `app.py`

**Files:**
- Modify: `shyfem_ui/app.py:919-920` (add head_includes to page layout)

**Step 1: Add head_includes import and call**

In `shyfem_ui/app.py`, add the import at the top with other imports:

```python
from shiny_deckgl import head_includes as deckgl_head_includes
```

Then in `_build_ui()`, add `deckgl_head_includes()` to the `ui.page_fillable()` call at line 919, right after `ui.head_content(_HEAD_EXTRAS)`:

```python
    return ui.page_fillable(
        ui.head_content(_HEAD_EXTRAS),
        deckgl_head_includes(),    # <-- ADD THIS LINE
        ui.busy_indicators.use(spinners=True, pulse=True),
        ...
    )
```

**Step 2: Verify the app still imports cleanly**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add shyfem_ui/app.py
git commit -m "feat(ui): add deck.gl head includes to app layout"
```

---

### Task 9: Integration — Update Page Imports

**Files:**
- Modify: `shyfem_ui/pages/mesh_builder.py:10`
- Modify: `shyfem_ui/pages/grid_prep.py:11`

The import line in both files already reads:
```python
from shyfem_ui.components.grid_map import grid_map_server, grid_map_ui
```

Since we're doing a full replacement with the same function names, **no import changes are needed**. However, we need to verify that the pages work with the new async server:

**Step 1: Verify mesh_builder imports cleanly**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.mesh_builder import mesh_builder_ui; print('OK')"`
Expected: `OK`

**Step 2: Verify grid_prep imports cleanly**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages.grid_prep import grid_prep_ui; print('OK')"`
Expected: `OK`

**Step 3: Remove the old `_get_triangle_vertices` helper from grid_prep.py**

The helper at `grid_prep.py:44-59` (`_get_triangle_vertices`) was used for the old Plotly approach. Check if it's still used elsewhere in grid_prep.py. If it is, leave it; if only the old map used it, remove it.

Run: `grep -n '_get_triangle_vertices' shyfem_ui/pages/grid_prep.py`

If still used within the file, leave it. Otherwise remove lines 44-59.

**Step 4: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --timeout=30`
Expected: All tests pass

**Step 5: Commit**

```bash
git add shyfem_ui/pages/mesh_builder.py shyfem_ui/pages/grid_prep.py
git commit -m "fix(ui): verify page integration with new deck.gl grid map"
```

---

### Task 10: Add Tooltip HTML to Triangle/Node Data

**Files:**
- Modify: `shyfem_ui/components/grid_map.py` (add tooltip_html field to data dicts)
- Test: `tests/test_grid_map.py`

**Step 1: Write the failing test**

Append to `tests/test_grid_map.py`:

```python
class TestTooltips:
    """Test tooltip HTML generation in data builders."""

    def test_triangle_has_tooltip(self):
        from shyfem_ui.components.grid_map import _build_triangle_data
        grd = _make_triangle_grid()
        data = _build_triangle_data(grd, mode="depth")
        assert "tooltip_html" in data[0]
        assert "Elem" in data[0]["tooltip_html"]
        assert "Depth" in data[0]["tooltip_html"]

    def test_node_has_tooltip(self):
        from shyfem_ui.components.grid_map import _build_node_data
        grd = _make_triangle_grid()
        data = _build_node_data(grd)
        assert "tooltip_html" in data[0]
        assert "Node" in data[0]["tooltip_html"]
```

**Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestTooltips -v`
Expected: FAIL — tooltip_html not present

**Step 3: Add tooltip_html to data builders**

In `_build_triangle_data`, add inside the loop after the `tri` dict is created:

```python
        tri["tooltip_html"] = (
            f"<b>Element {elem.id}</b><br>"
            f"Depth: {avg_depth:.2f}<br>"
            f"Quality: {quality:.3f}"
        )
```

In `_build_node_data`, add to each dict:

```python
        {
            ...
            "tooltip_html": (
                f"<b>Node {nid}</b><br>"
                f"X: {n.x:.4f}, Y: {n.y:.4f}<br>"
                f"Depth: {n.depth:.2f}" if n.depth is not None else f"<b>Node {nid}</b><br>X: {n.x:.4f}, Y: {n.y:.4f}"
            ),
        }
```

**Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py::TestTooltips -v`
Expected: 2 passed

**Step 5: Run all grid_map tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map.py -v`
Expected: All passed

**Step 6: Commit**

```bash
git add shyfem_ui/components/grid_map.py tests/test_grid_map.py
git commit -m "feat(ui): add hover tooltip HTML to mesh triangles and nodes"
```

---

### Task 11: Full Integration Test — Run the App

**Files:** None (manual verification)

**Step 1: Run the full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: All tests pass, no regressions

**Step 2: Verify app starts**

Run: `cd /home/razinka/shyfem/shyfem-ui && timeout 10 /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.app import create_app; app = create_app(); print('App created OK')" 2>&1`
Expected: `App created OK`

**Step 3: Commit the final state**

```bash
git add -A
git commit -m "feat(ui): complete deck.gl grid map replacement

Replace Plotly Scattergl wireframe map with shiny_deckgl MapWidget:
- Filled triangle polygons with depth/quality/partition coloring
- Deduplicated wireframe edge overlay
- Bold boundary lines by type with distinct colors
- 3D extruded bathymetry view (depth_3d mode)
- Geographic basemap (CARTO Positron/Dark, OSM Liberty)
- Auto-fit bounds on data load
- Hover tooltips on triangles and nodes
- Node click inspection panel
- Same Shiny module API (drop-in replacement)"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | `_get_lonlat` coord helper | grid_map.py, test_grid_map.py |
| 2 | `_build_edge_data` dedup wireframe | grid_map.py, test_grid_map.py |
| 3 | `_build_triangle_data` filled polygons | grid_map.py, test_grid_map.py |
| 4 | `_build_boundary_data` + `_build_node_data` | grid_map.py, test_grid_map.py |
| 5 | `build_layers` assembly | grid_map.py, test_grid_map.py |
| 6 | `_compute_view_state` auto-fit | grid_map.py, test_grid_map.py |
| 7 | `grid_map_ui` + `grid_map_server` module | grid_map.py, test_grid_map.py |
| 8 | `head_includes` in app.py | app.py |
| 9 | Verify page integration | mesh_builder.py, grid_prep.py |
| 10 | Tooltip HTML | grid_map.py, test_grid_map.py |
| 11 | Full integration test | — |
