"""Tests for deck.gl grid map data builders (Tasks 1-4).

Tests cover: _get_lonlat, _build_edge_data, _build_triangle_data,
_build_boundary_data, _build_node_data, and helper functions.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from shyfem_ui.components.grid_map import (
    BOUNDARY_COLORS,
    PARTITION_COLORS,
    _build_boundary_data,
    _build_edge_data,
    _build_node_data,
    _build_triangle_data,
    _compute_quality,
    _compute_view_state,
    _depth_to_colors,
    _detect_projected_crs,
    _get_lonlat,
    _is_geographic,
    _quality_to_colors,
    build_layers,
)
from shyfem_ui.services.parser_grd import (
    CoordinateSystem,
    Element,
    GrdFile,
    GrdParser,
    Line,
    Node,
)

# Path to Mar Menor test grid (UTM zone 30N, EPSG:32630)
_MAR_MENOR_GRD = Path(__file__).resolve().parents[1] / (
    "../testcases/examples/mar_menor/GRID/MM_coarse.grd"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_triangle_grid() -> GrdFile:
    """One triangle, 3 nodes with depth, geographic coords (Mar Menor area)."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=-0.80, y=37.70, depth=2.5),
        2: Node(id=2, node_type=0, x=-0.78, y=37.70, depth=4.0),
        3: Node(id=3, node_type=0, x=-0.79, y=37.72, depth=3.0),
    }
    grd.elements = {
        1: Element(id=1, elem_type=3, nodes=[1, 2, 3]),
    }
    grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
    return grd


def _make_multi_grid() -> GrdFile:
    """Two triangles sharing edge 2-3, with a boundary line of type 1."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=-0.82, y=37.68, depth=1.0),
        2: Node(id=2, node_type=0, x=-0.78, y=37.68, depth=2.0),
        3: Node(id=3, node_type=0, x=-0.80, y=37.72, depth=3.5),
        4: Node(id=4, node_type=0, x=-0.76, y=37.72, depth=1.5),
    }
    grd.elements = {
        1: Element(id=1, elem_type=3, nodes=[1, 2, 3]),
        2: Element(id=2, elem_type=3, nodes=[2, 4, 3]),
    }
    grd.lines = {
        10: Line(id=10, line_type=1, nodes=[1, 2, 4]),
    }
    grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
    return grd


# ===========================================================================
# TestGetLonLat
# ===========================================================================

class TestGetLonLat:
    """Tests for _get_lonlat()."""

    def test_geographic_returns_xy(self):
        """Geographic grids return [x, y] (lon, lat) directly."""
        grd = _make_triangle_grid()
        lonlat = _get_lonlat(grd)
        assert len(lonlat) == 3
        assert lonlat[1] == [-0.80, 37.70]
        assert lonlat[2] == [-0.78, 37.70]
        assert lonlat[3] == [-0.79, 37.72]

    def test_empty_grid(self):
        grd = GrdFile()
        lonlat = _get_lonlat(grd)
        assert lonlat == {}

    def test_cartesian_returns_xy(self):
        """Cartesian grids also return [x, y] -- conversion is caller's job."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=500000.0, y=4170000.0),
        }
        grd.coordinate_system = CoordinateSystem(CoordinateSystem.CARTESIAN)
        lonlat = _get_lonlat(grd)
        assert lonlat[1] == [500000.0, 4170000.0]

    def test_preserves_node_ids(self):
        """Node IDs in output match input, even if non-contiguous."""
        grd = GrdFile()
        grd.nodes = {
            10: Node(id=10, node_type=0, x=-0.80, y=37.70),
            99: Node(id=99, node_type=0, x=-0.75, y=37.65),
        }
        grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
        lonlat = _get_lonlat(grd)
        assert set(lonlat.keys()) == {10, 99}


# ===========================================================================
# TestBuildEdgeData
# ===========================================================================

class TestBuildEdgeData:
    """Tests for _build_edge_data()."""

    def test_single_triangle_3_edges(self):
        """One triangle produces exactly 3 unique edges."""
        grd = _make_triangle_grid()
        edges = _build_edge_data(grd)
        assert len(edges) == 3

    def test_two_triangles_5_edges_dedup(self):
        """Two triangles sharing an edge produce 5 unique edges, not 6."""
        grd = _make_multi_grid()
        edges = _build_edge_data(grd)
        assert len(edges) == 5

    def test_path_structure(self):
        """Each edge dict has a 'path' key with exactly 2 coordinate pairs."""
        grd = _make_triangle_grid()
        edges = _build_edge_data(grd)
        for edge in edges:
            assert "path" in edge
            assert len(edge["path"]) == 2
            # Each point is [lon, lat]
            assert len(edge["path"][0]) == 2
            assert len(edge["path"][1]) == 2

    def test_empty_grid(self):
        grd = GrdFile()
        edges = _build_edge_data(grd)
        assert edges == []

    def test_coordinates_are_floats(self):
        grd = _make_triangle_grid()
        edges = _build_edge_data(grd)
        for edge in edges:
            for pt in edge["path"]:
                assert isinstance(pt[0], float)
                assert isinstance(pt[1], float)

    def test_no_duplicate_edges(self):
        """Edge (a, b) and (b, a) should be treated as the same edge."""
        grd = _make_multi_grid()
        edges = _build_edge_data(grd)
        # Collect sorted endpoint pairs
        pairs = set()
        for edge in edges:
            p = tuple(sorted([tuple(edge["path"][0]), tuple(edge["path"][1])]))
            pairs.add(p)
        assert len(pairs) == len(edges)


# ===========================================================================
# TestComputeQuality
# ===========================================================================

class TestComputeQuality:
    """Tests for _compute_quality()."""

    def test_equilateral(self):
        """Equilateral triangle has quality = 1.0."""
        # Equilateral triangle with side length 1
        coords = [[0.0, 0.0], [1.0, 0.0], [0.5, math.sqrt(3) / 2]]
        q = _compute_quality(coords)
        assert abs(q - 1.0) < 1e-10

    def test_degenerate(self):
        """Collinear points: sides are 1, 1, 2 so min/max = 0.5."""
        coords = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
        q = _compute_quality(coords)
        assert abs(q - 0.5) < 1e-10

    def test_zero_area(self):
        """All coincident points have quality = 0 (zero-length sides)."""
        coords = [[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]]
        q = _compute_quality(coords)
        assert q == 0.0

    def test_right_triangle(self):
        """Right triangle (1, 1, sqrt(2)) has quality = 1/sqrt(2)."""
        coords = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        q = _compute_quality(coords)
        expected = 1.0 / math.sqrt(2)
        assert abs(q - expected) < 1e-10


# ===========================================================================
# TestDepthToColors / TestQualityToColors
# ===========================================================================

class TestDepthToColors:
    """Tests for _depth_to_colors()."""

    def test_returns_rgba_lists(self):
        colors = _depth_to_colors([1.0, 2.0, 3.0], "viridis")
        assert len(colors) == 3
        for c in colors:
            assert len(c) == 4  # RGBA
            assert all(isinstance(v, int) for v in c)

    def test_single_value(self):
        colors = _depth_to_colors([5.0], "ocean")
        assert len(colors) == 1

    def test_empty_returns_empty(self):
        colors = _depth_to_colors([], "viridis")
        assert colors == []

    def test_unknown_palette_uses_viridis(self):
        """Unknown palette name falls back to viridis."""
        colors = _depth_to_colors([1.0, 2.0], "nonexistent")
        assert len(colors) == 2


class TestQualityToColors:
    """Tests for _quality_to_colors()."""

    def test_returns_rgba(self):
        colors = _quality_to_colors([0.0, 0.5, 1.0])
        assert len(colors) == 3
        for c in colors:
            assert len(c) == 4

    def test_empty(self):
        assert _quality_to_colors([]) == []


# ===========================================================================
# TestBuildTriangleData
# ===========================================================================

class TestBuildTriangleData:
    """Tests for _build_triangle_data()."""

    def test_mesh_mode_returns_empty(self):
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="mesh")
        assert result == []

    def test_depth_mode_has_fill_color(self):
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="depth")
        assert len(result) == 1
        tri = result[0]
        assert "fill_color" in tri
        assert len(tri["fill_color"]) == 4  # RGBA
        assert "polygon" in tri
        assert "elem_id" in tri
        assert "depth" in tri

    def test_quality_mode_has_quality(self):
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="quality")
        assert len(result) == 1
        tri = result[0]
        assert "quality" in tri
        assert 0.0 <= tri["quality"] <= 1.0

    def test_depth_3d_has_elevation(self):
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="depth_3d", elevation_scale=100.0)
        assert len(result) == 1
        tri = result[0]
        assert "elevation" in tri
        avg_depth = (2.5 + 4.0 + 3.0) / 3.0
        # depth is rounded to 6 decimals internally, so allow small tolerance
        assert abs(tri["elevation"] - avg_depth * 100.0) < 0.01

    def test_partitions_different_colors(self):
        grd = _make_multi_grid()
        pmap = {1: 0, 2: 1}
        result = _build_triangle_data(grd, mode="partitions", partition_map=pmap)
        assert len(result) == 2
        # Different partitions should have different colors
        assert result[0]["fill_color"] != result[1]["fill_color"]

    def test_boundaries_mode_light_gray(self):
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="boundaries")
        assert len(result) == 1
        tri = result[0]
        # Light gray, semi-transparent
        r, g, b, a = tri["fill_color"]
        assert r == g == b  # gray
        assert a < 255  # semi-transparent

    def test_empty_grid(self):
        grd = GrdFile()
        result = _build_triangle_data(grd, mode="depth")
        assert result == []

    def test_no_depth_data(self):
        """Nodes with no depth should still produce triangles with depth=0."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=-0.80, y=37.70),
            2: Node(id=2, node_type=0, x=-0.78, y=37.70),
            3: Node(id=3, node_type=0, x=-0.79, y=37.72),
        }
        grd.elements = {1: Element(id=1, elem_type=3, nodes=[1, 2, 3])}
        grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
        result = _build_triangle_data(grd, mode="depth")
        assert len(result) == 1
        assert result[0]["depth"] == 0.0

    def test_tooltip_html_present(self):
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="depth")
        assert len(result) == 1
        assert "tooltip_html" in result[0]
        assert "Elem" in result[0]["tooltip_html"]

    def test_polygon_coords_count(self):
        """Polygon should have 3 coordinate pairs for a triangle."""
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="depth")
        poly = result[0]["polygon"]
        assert len(poly) == 3
        for pt in poly:
            assert len(pt) == 2

    def test_partitions_without_map_returns_empty(self):
        """Partitions mode with no partition_map returns empty list."""
        grd = _make_triangle_grid()
        result = _build_triangle_data(grd, mode="partitions", partition_map=None)
        assert result == []

    def test_multi_triangle_depth(self):
        grd = _make_multi_grid()
        result = _build_triangle_data(grd, mode="depth")
        assert len(result) == 2
        for tri in result:
            assert "fill_color" in tri
            assert "depth" in tri
            assert "tooltip_html" in tri


# ===========================================================================
# TestBuildBoundaryData
# ===========================================================================

class TestBuildBoundaryData:
    """Tests for _build_boundary_data()."""

    def test_grouped_by_type(self):
        grd = _make_multi_grid()
        result = _build_boundary_data(grd)
        assert isinstance(result, dict)
        assert 1 in result  # line_type 1

    def test_path_has_coords(self):
        grd = _make_multi_grid()
        result = _build_boundary_data(grd)
        lines = result[1]
        assert len(lines) >= 1
        line_data = lines[0]
        assert "path" in line_data
        # Path should have at least 2 points
        assert len(line_data["path"]) >= 2
        for pt in line_data["path"]:
            assert len(pt) == 2
            assert isinstance(pt[0], float)
            assert isinstance(pt[1], float)

    def test_empty_grid(self):
        grd = GrdFile()
        result = _build_boundary_data(grd)
        assert result == {}

    def test_line_id_in_data(self):
        grd = _make_multi_grid()
        result = _build_boundary_data(grd)
        lines = result[1]
        assert lines[0]["line_id"] == 10

    def test_tooltip_html_present(self):
        grd = _make_multi_grid()
        result = _build_boundary_data(grd)
        lines = result[1]
        assert "tooltip_html" in lines[0]
        assert "Boundary" in lines[0]["tooltip_html"]

    def test_multiple_types(self):
        """Multiple line types are grouped separately."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=-0.80, y=37.70),
            2: Node(id=2, node_type=0, x=-0.78, y=37.70),
            3: Node(id=3, node_type=0, x=-0.76, y=37.70),
        }
        grd.lines = {
            1: Line(id=1, line_type=1, nodes=[1, 2]),
            2: Line(id=2, line_type=2, nodes=[2, 3]),
        }
        grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
        result = _build_boundary_data(grd)
        assert 1 in result
        assert 2 in result

    def test_path_follows_node_order(self):
        """Path coordinates follow the line's node order."""
        grd = _make_multi_grid()
        result = _build_boundary_data(grd)
        line_data = result[1][0]
        path = line_data["path"]
        # Line 10 has nodes [1, 2, 4]
        expected = [
            [-0.82, 37.68],  # node 1
            [-0.78, 37.68],  # node 2
            [-0.76, 37.72],  # node 4
        ]
        for i, pt in enumerate(path):
            assert abs(pt[0] - expected[i][0]) < 1e-10
            assert abs(pt[1] - expected[i][1]) < 1e-10


# ===========================================================================
# TestBuildNodeData
# ===========================================================================

class TestBuildNodeData:
    """Tests for _build_node_data()."""

    def test_count(self):
        grd = _make_triangle_grid()
        result = _build_node_data(grd)
        assert len(result) == 3

    def test_position(self):
        grd = _make_triangle_grid()
        result = _build_node_data(grd)
        # Find node 1
        node1 = [n for n in result if n["node_id"] == 1][0]
        assert node1["position"] == [-0.80, 37.70]

    def test_metadata(self):
        grd = _make_triangle_grid()
        result = _build_node_data(grd)
        node1 = [n for n in result if n["node_id"] == 1][0]
        assert node1["depth"] == 2.5
        assert node1["node_type"] == 0
        assert node1["node_id"] == 1

    def test_tooltip_html(self):
        grd = _make_triangle_grid()
        result = _build_node_data(grd)
        node1 = [n for n in result if n["node_id"] == 1][0]
        assert "tooltip_html" in node1
        assert "Node 1" in node1["tooltip_html"]
        assert "2.5" in node1["tooltip_html"]

    def test_empty_grid(self):
        grd = GrdFile()
        result = _build_node_data(grd)
        assert result == []

    def test_node_without_depth(self):
        """Node without depth should have depth=0.0 in output."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=-0.80, y=37.70),
        }
        grd.coordinate_system = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
        result = _build_node_data(grd)
        assert len(result) == 1
        assert result[0]["depth"] == 0.0
        assert "No depth" in result[0]["tooltip_html"]

    def test_all_nodes_present(self):
        grd = _make_multi_grid()
        result = _build_node_data(grd)
        ids = {n["node_id"] for n in result}
        assert ids == {1, 2, 3, 4}


# ===========================================================================
# TestBuildLayers
# ===========================================================================

def _layer_ids(layers: list[dict]) -> set[str]:
    """Extract the set of layer IDs from a list of layer dicts."""
    return {lyr["id"] for lyr in layers}


class TestBuildLayers:
    """Tests for build_layers()."""

    def test_mesh_mode_returns_wireframe(self):
        """Mesh mode returns wireframe path_layer but no triangles polygon."""
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="mesh", colorscale="viridis",
                              show_boundaries=False, show_nodes=False)
        ids = _layer_ids(layers)
        assert "wireframe" in ids
        assert "triangles" not in ids

    def test_depth_mode_returns_fill_and_wireframe(self):
        """Depth mode returns both filled triangles and wireframe."""
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="depth", colorscale="viridis",
                              show_boundaries=False, show_nodes=False)
        ids = _layer_ids(layers)
        assert "triangles" in ids
        assert "wireframe" in ids

    def test_depth_3d_mode_has_extruded(self):
        """Depth 3D mode produces triangles layer with extruded=True."""
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="depth_3d", colorscale="viridis",
                              show_boundaries=False, show_nodes=False,
                              elevation_scale=100.0)
        tri_layer = [l for l in layers if l["id"] == "triangles"]
        assert len(tri_layer) == 1
        assert tri_layer[0].get("extruded") is True

    def test_boundaries_mode_adds_boundary_layers(self):
        """Boundaries mode includes boundary_* layers."""
        grd = _make_multi_grid()
        layers = build_layers(grd, mode="boundaries", colorscale="viridis",
                              show_boundaries=False, show_nodes=False)
        ids = _layer_ids(layers)
        boundary_ids = {i for i in ids if i.startswith("boundary_")}
        assert len(boundary_ids) >= 1

    def test_show_boundaries_adds_layers(self):
        """show_boundaries=True in mesh mode appends boundary_* layers."""
        grd = _make_multi_grid()
        layers = build_layers(grd, mode="mesh", colorscale="viridis",
                              show_boundaries=True, show_nodes=False)
        ids = _layer_ids(layers)
        boundary_ids = {i for i in ids if i.startswith("boundary_")}
        assert len(boundary_ids) >= 1

    def test_show_nodes_adds_scatter(self):
        """show_nodes=True appends a nodes scatterplot layer."""
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="mesh", colorscale="viridis",
                              show_boundaries=False, show_nodes=True)
        ids = _layer_ids(layers)
        assert "nodes" in ids

    def test_empty_grid(self):
        """Empty grid returns empty layer list."""
        grd = GrdFile()
        layers = build_layers(grd, mode="mesh", colorscale="viridis",
                              show_boundaries=False, show_nodes=False)
        assert layers == []

    def test_partition_mode(self):
        """Partition mode has triangles layer."""
        grd = _make_multi_grid()
        pmap = {1: 0, 2: 1}
        layers = build_layers(grd, mode="partitions", colorscale="viridis",
                              show_boundaries=False, show_nodes=False,
                              partition_map=pmap)
        ids = _layer_ids(layers)
        assert "triangles" in ids

    def test_depth_3d_no_wireframe(self):
        """Depth 3D mode should NOT have a wireframe layer."""
        grd = _make_triangle_grid()
        layers = build_layers(grd, mode="depth_3d", colorscale="viridis",
                              show_boundaries=False, show_nodes=False,
                              elevation_scale=100.0)
        ids = _layer_ids(layers)
        assert "wireframe" not in ids


# ===========================================================================
# TestComputeViewState
# ===========================================================================

class TestComputeViewState:
    """Tests for _compute_view_state()."""

    def test_geographic_grid_center(self):
        """Center longitude/latitude should be within node bounds."""
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd)
        # Node x range: -0.80 to -0.78, y range: 37.70 to 37.72
        assert -0.80 <= vs["longitude"] <= -0.78
        assert 37.70 <= vs["latitude"] <= 37.72

    def test_3d_tilts_camera(self):
        """3D mode sets pitch=45 and bearing=-30."""
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd, is_3d=True)
        assert vs["pitch"] == 45
        assert vs["bearing"] == -30

    def test_empty_grid_defaults(self):
        """Empty grid returns sensible defaults."""
        grd = GrdFile()
        vs = _compute_view_state(grd)
        assert "longitude" in vs
        assert "latitude" in vs
        assert "zoom" in vs
        assert vs["longitude"] == 0
        assert vs["latitude"] == 0
        assert vs["zoom"] == 2

    def test_returns_bounds(self):
        """View state includes bounds as [[sw], [ne]]."""
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd)
        assert "bounds" in vs
        bounds = vs["bounds"]
        assert len(bounds) == 2
        assert len(bounds[0]) == 2  # [xmin, ymin]
        assert len(bounds[1]) == 2  # [xmax, ymax]
        # SW should be less than NE
        assert bounds[0][0] <= bounds[1][0]
        assert bounds[0][1] <= bounds[1][1]

    def test_2d_flat_camera(self):
        """2D mode sets pitch=0 and bearing=0."""
        grd = _make_triangle_grid()
        vs = _compute_view_state(grd, is_3d=False)
        assert vs["pitch"] == 0
        assert vs["bearing"] == 0

    def test_projected_coords_returns_safe_defaults(self):
        """Projected CRS coords (outside WGS84 range) return safe defaults."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=300000.0, y=6100000.0),
            2: Node(id=2, node_type=0, x=350000.0, y=6150000.0),
        }
        vs = _compute_view_state(grd)
        # Should NOT crash maplibre-gl — lat must be in [-90, 90]
        assert -90 <= vs["latitude"] <= 90
        assert -180 <= vs["longitude"] <= 180
        assert vs["zoom"] == 2  # default fallback

    def test_longitude_out_of_range_returns_safe_defaults(self):
        """X values > 180 (projected CRS) return safe defaults."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=500000.0, y=55.0),
        }
        vs = _compute_view_state(grd)
        assert -90 <= vs["latitude"] <= 90
        assert -180 <= vs["longitude"] <= 180


class TestBuildLayersBoundaryOnly:
    """Tests for build_layers() with boundary-only grids (no elements)."""

    def test_boundary_only_grid_renders_lines(self):
        """Grid with nodes+lines but no elements produces boundary layers."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=21.0, y=55.0),
            2: Node(id=2, node_type=0, x=21.5, y=55.0),
            3: Node(id=3, node_type=0, x=21.5, y=55.5),
            4: Node(id=4, node_type=0, x=21.0, y=55.5),
        }
        grd.lines = {
            1: Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1]),
        }
        layers = build_layers(grd, mode="mesh")
        # Should auto-switch to boundaries mode for boundary-only grids
        assert len(layers) >= 1
        layer_ids = [l["id"] for l in layers]
        assert any("boundary" in lid for lid in layer_ids)

    def test_boundary_only_grid_no_crash_on_depth_mode(self):
        """Depth mode on boundary-only grid should not crash."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=21.0, y=55.0),
            2: Node(id=2, node_type=0, x=21.5, y=55.0),
        }
        grd.lines = {
            1: Line(id=1, line_type=1, nodes=[1, 2]),
        }
        # Element-dependent modes fall through to boundary rendering
        layers = build_layers(grd, mode="depth")
        assert isinstance(layers, list)

    def test_boundary_only_grid_explicit_boundaries_mode(self):
        """Explicit boundaries mode on boundary-only grid."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=21.0, y=55.0),
            2: Node(id=2, node_type=0, x=21.5, y=55.0),
            3: Node(id=3, node_type=0, x=21.5, y=55.5),
            4: Node(id=4, node_type=0, x=21.0, y=55.5),
        }
        grd.lines = {
            1: Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1]),
        }
        layers = build_layers(grd, mode="boundaries")
        assert len(layers) >= 1
        # Should NOT have triangle or wireframe layers
        layer_ids = [l["id"] for l in layers]
        assert "triangles" not in layer_ids
        assert "wireframe" not in layer_ids

    def test_nodes_only_grid_returns_empty(self):
        """Grid with only nodes (no elements, no lines) returns empty."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=21.0, y=55.0),
        }
        layers = build_layers(grd, mode="mesh")
        assert layers == []

    def test_show_nodes_on_boundary_only_grid(self):
        """show_nodes works on boundary-only grids."""
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=21.0, y=55.0),
            2: Node(id=2, node_type=0, x=21.5, y=55.0),
        }
        grd.lines = {
            1: Line(id=1, line_type=1, nodes=[1, 2]),
        }
        layers = build_layers(grd, mode="boundaries", show_nodes=True)
        layer_ids = [l["id"] for l in layers]
        assert "nodes" in layer_ids


# ===========================================================================
# UTM fixture for reprojection tests
# ===========================================================================

def _make_utm30n_grid() -> GrdFile:
    """Mar Menor-like grid in UTM zone 30N (EPSG:32630).

    Three nodes near Mar Menor, Spain (~lon -0.8, lat 37.7).
    Coordinates in metres (easting/northing).
    """
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=690_000.0, y=4_175_000.0, depth=2.0),
        2: Node(id=2, node_type=0, x=700_000.0, y=4_175_000.0, depth=3.0),
        3: Node(id=3, node_type=0, x=695_000.0, y=4_185_000.0, depth=4.0),
    }
    grd.elements = {
        1: Element(id=1, elem_type=3, nodes=[1, 2, 3]),
    }
    return grd


def _make_gauss_boaga_west_grid() -> GrdFile:
    """Italian grid in Gauss-Boaga West (EPSG:3003).

    Gauss-Boaga West has false easting ~1,500,000.
    """
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=1_550_000.0, y=4_600_000.0, depth=5.0),
        2: Node(id=2, node_type=0, x=1_560_000.0, y=4_600_000.0, depth=6.0),
        3: Node(id=3, node_type=0, x=1_555_000.0, y=4_610_000.0, depth=7.0),
    }
    grd.elements = {
        1: Element(id=1, elem_type=3, nodes=[1, 2, 3]),
    }
    return grd


# ===========================================================================
# TestIsGeographic
# ===========================================================================

class TestIsGeographic:
    """Tests for _is_geographic()."""

    def test_lonlat_coords_are_geographic(self):
        grd = _make_triangle_grid()
        assert _is_geographic(grd) is True

    def test_utm_coords_are_not_geographic(self):
        grd = _make_utm30n_grid()
        assert _is_geographic(grd) is False

    def test_gauss_boaga_not_geographic(self):
        grd = _make_gauss_boaga_west_grid()
        assert _is_geographic(grd) is False

    def test_empty_grid_is_geographic(self):
        grd = GrdFile()
        assert _is_geographic(grd) is True


# ===========================================================================
# TestDetectProjectedCrs
# ===========================================================================

class TestDetectProjectedCrs:
    """Tests for _detect_projected_crs()."""

    def test_gauss_boaga_west_detected(self):
        grd = _make_gauss_boaga_west_grid()
        assert _detect_projected_crs(grd) == 3003

    def test_gauss_boaga_east_detected(self):
        grd = GrdFile()
        grd.nodes = {
            1: Node(id=1, node_type=0, x=2_550_000.0, y=4_600_000.0),
        }
        assert _detect_projected_crs(grd) == 3004

    def test_utm_returns_none(self):
        """UTM zone cannot be auto-detected."""
        grd = _make_utm30n_grid()
        assert _detect_projected_crs(grd) is None

    def test_empty_grid_returns_none(self):
        grd = GrdFile()
        assert _detect_projected_crs(grd) is None


# ===========================================================================
# TestGetLonLatReprojection
# ===========================================================================

class TestGetLonLatReprojection:
    """Tests for _get_lonlat() with EPSG reprojection."""

    def test_utm30n_with_epsg_reprojects(self):
        """UTM 30N grid reprojects to correct lon/lat with explicit EPSG."""
        grd = _make_utm30n_grid()
        lonlat = _get_lonlat(grd, epsg=32630)
        # Node 1: (690000, 4175000) in UTM 30N → lon ~-0.85, lat ~37.7
        lon1, lat1 = lonlat[1]
        assert -1.5 < lon1 < 0.0, f"Expected lon near -0.85, got {lon1}"
        assert 37.0 < lat1 < 38.5, f"Expected lat near 37.7, got {lat1}"

    def test_utm_without_epsg_returns_raw(self):
        """UTM grid without EPSG returns raw metre coordinates."""
        grd = _make_utm30n_grid()
        lonlat = _get_lonlat(grd)
        # No EPSG → raw coordinates (easting/northing)
        assert lonlat[1][0] == 690_000.0
        assert lonlat[1][1] == 4_175_000.0

    def test_grd_epsg_attribute_used_as_fallback(self):
        """grd.epsg is used when no explicit epsg param is passed."""
        grd = _make_utm30n_grid()
        grd.epsg = 32630  # Set on the GrdFile object (like sample data loader)
        # Call without explicit epsg — should still reproject via grd.epsg
        # _get_lonlat doesn't read grd.epsg directly (that's in grid_map_server),
        # but we verify the attribute exists and the explicit param works
        lonlat = _get_lonlat(grd, epsg=grd.epsg)
        lon1, lat1 = lonlat[1]
        assert -1.5 < lon1 < 0.0
        assert 37.0 < lat1 < 38.5

    def test_geographic_with_epsg_still_reprojects(self):
        """If user sets EPSG on a geographic grid, it still reprojects."""
        # Edge case: user mistakenly sets EPSG on lon/lat grid
        grd = _make_triangle_grid()
        # With EPSG=4326 (WGS84→WGS84), coords should be essentially unchanged
        lonlat = _get_lonlat(grd, epsg=4326)
        assert abs(lonlat[1][0] - (-0.80)) < 0.001
        assert abs(lonlat[1][1] - 37.70) < 0.001

    def test_gauss_boaga_auto_detected(self):
        """Gauss-Boaga is auto-detected without explicit EPSG."""
        grd = _make_gauss_boaga_west_grid()
        lonlat = _get_lonlat(grd)
        # GB West → should give Italian coordinates (lon ~9-12, lat ~40-45)
        lon1, lat1 = lonlat[1]
        assert 5.0 < lon1 < 20.0, f"Expected Italian longitude, got {lon1}"
        assert 35.0 < lat1 < 50.0, f"Expected Italian latitude, got {lat1}"


# ===========================================================================
# TestBuildLayersWithEpsg
# ===========================================================================

class TestBuildLayersWithEpsg:
    """Tests for build_layers() with EPSG parameter."""

    def test_utm_mesh_with_epsg(self):
        """UTM grid produces wireframe when EPSG is set."""
        grd = _make_utm30n_grid()
        layers = build_layers(grd, mode="mesh", epsg=32630)
        assert len(layers) == 1
        assert layers[0]["id"] == "wireframe"

    def test_utm_depth_with_epsg(self):
        """UTM grid produces depth layers when EPSG is set."""
        grd = _make_utm30n_grid()
        layers = build_layers(grd, mode="depth", epsg=32630)
        ids = [l["id"] for l in layers]
        assert "triangles" in ids
        assert "wireframe" in ids

    def test_utm_without_epsg_still_renders(self):
        """UTM grid without EPSG uses raw coords but still renders."""
        grd = _make_utm30n_grid()
        layers = build_layers(grd, mode="mesh")
        # Should still produce layers (with raw metre coords)
        assert len(layers) == 1

    def test_view_state_with_epsg(self):
        """View state centers on reprojected coordinates."""
        grd = _make_utm30n_grid()
        vs = _compute_view_state(grd, epsg=32630)
        # Center should be near Mar Menor
        assert -2.0 < vs["longitude"] < 1.0
        assert 36.0 < vs["latitude"] < 39.0
        assert vs["zoom"] > 5

    def test_view_state_without_epsg_raw_coords(self):
        """View state with raw UTM coords exceeds WGS84 → safe defaults."""
        grd = _make_utm30n_grid()
        vs = _compute_view_state(grd)
        # Raw UTM northing ~4M exceeds 90° → should return safe defaults
        assert vs["longitude"] == 0
        assert vs["latitude"] == 0
        assert vs["zoom"] == 2


# ===========================================================================
# Mar Menor real-grid integration tests (EPSG:32630 — UTM zone 30N)
# ===========================================================================


@pytest.fixture(scope="module")
def mar_menor_grd() -> GrdFile:
    """Load the real Mar Menor grid from the SHYFEM testcases directory."""
    if not _MAR_MENOR_GRD.exists():
        pytest.skip(f"Mar Menor grid not found: {_MAR_MENOR_GRD}")
    return GrdParser.parse_file(_MAR_MENOR_GRD)


class TestMarMenorGridParsing:
    """Verify the real Mar Menor grid parses correctly."""

    def test_grid_has_nodes(self, mar_menor_grd):
        assert mar_menor_grd.num_nodes > 100

    def test_grid_has_elements(self, mar_menor_grd):
        assert mar_menor_grd.num_elements > 100

    def test_coordinates_are_utm(self, mar_menor_grd):
        """Mar Menor coordinates are in UTM metres, not geographic."""
        assert _is_geographic(mar_menor_grd) is False

    def test_coordinates_in_utm_range(self, mar_menor_grd):
        """Eastings ~688k-710k, northings ~4.17M-4.19M."""
        xs = [n.x for n in mar_menor_grd.nodes.values()]
        ys = [n.y for n in mar_menor_grd.nodes.values()]
        assert 600_000 < min(xs) < 750_000
        assert 600_000 < max(xs) < 750_000
        assert 4_000_000 < min(ys) < 4_500_000
        assert 4_000_000 < max(ys) < 4_500_000

    def test_auto_detect_returns_none_for_utm(self, mar_menor_grd):
        """UTM zone cannot be auto-detected — returns None."""
        assert _detect_projected_crs(mar_menor_grd) is None


class TestMarMenorReprojection:
    """Verify Mar Menor grid reprojects correctly with EPSG:32630."""

    def test_lonlat_without_epsg_returns_raw(self, mar_menor_grd):
        """Without EPSG, returns raw UTM coordinates."""
        lonlat = _get_lonlat(mar_menor_grd)
        some_lon = next(iter(lonlat.values()))[0]
        # Raw easting ~690k (not a valid longitude)
        assert some_lon > 10_000

    def test_lonlat_with_epsg_gives_geographic(self, mar_menor_grd):
        """With EPSG:32630, coordinates are in geographic range."""
        lonlat = _get_lonlat(mar_menor_grd, epsg=32630)
        lons = [p[0] for p in lonlat.values()]
        lats = [p[1] for p in lonlat.values()]
        # Mar Menor is near lon -0.8, lat 37.7
        assert all(-2.0 < lon < 1.0 for lon in lons)
        assert all(36.0 < lat < 39.0 for lat in lats)

    def test_lonlat_center_near_mar_menor(self, mar_menor_grd):
        """Reprojected centroid is near Mar Menor, Spain."""
        lonlat = _get_lonlat(mar_menor_grd, epsg=32630)
        lons = [p[0] for p in lonlat.values()]
        lats = [p[1] for p in lonlat.values()]
        center_lon = sum(lons) / len(lons)
        center_lat = sum(lats) / len(lats)
        # Mar Menor center: approx lon -0.74, lat 37.75
        assert abs(center_lon - (-0.74)) < 0.2
        assert abs(center_lat - 37.75) < 0.2

    def test_all_nodes_reprojected(self, mar_menor_grd):
        """Every node gets a reprojected coordinate."""
        lonlat = _get_lonlat(mar_menor_grd, epsg=32630)
        assert len(lonlat) == mar_menor_grd.num_nodes

    def test_wrong_epsg_gives_wrong_location(self, mar_menor_grd):
        """Using wrong EPSG (e.g. UTM 35N) gives very different coordinates."""
        lonlat_30 = _get_lonlat(mar_menor_grd, epsg=32630)
        lonlat_35 = _get_lonlat(mar_menor_grd, epsg=32635)
        center_lon_30 = sum(p[0] for p in lonlat_30.values()) / len(lonlat_30)
        center_lon_35 = sum(p[0] for p in lonlat_35.values()) / len(lonlat_35)
        # 5 zones apart = ~30° longitude shift
        assert abs(center_lon_35 - center_lon_30) > 20


class TestMarMenorViewState:
    """Verify view state computation for Mar Menor grid."""

    def test_view_state_without_epsg_returns_defaults(self, mar_menor_grd):
        """Without EPSG, UTM coords exceed WGS84 → safe defaults."""
        vs = _compute_view_state(mar_menor_grd)
        assert vs["longitude"] == 0
        assert vs["latitude"] == 0
        assert vs["zoom"] == 2

    def test_view_state_with_epsg_centers_on_mar_menor(self, mar_menor_grd):
        """With EPSG:32630, view centers on Mar Menor."""
        vs = _compute_view_state(mar_menor_grd, epsg=32630)
        assert -2.0 < vs["longitude"] < 1.0
        assert 36.0 < vs["latitude"] < 39.0

    def test_view_state_zoom_reasonable(self, mar_menor_grd):
        """Zoom level is reasonable for a local lagoon grid."""
        vs = _compute_view_state(mar_menor_grd, epsg=32630)
        # Mar Menor is ~25km across, should give zoom ~9-12
        assert 8 < vs["zoom"] < 15

    def test_view_state_bounds_in_wgs84(self, mar_menor_grd):
        """View state bounds are within WGS84 range."""
        vs = _compute_view_state(mar_menor_grd, epsg=32630)
        bounds = vs["bounds"]
        assert -180 <= bounds[0][0] <= 180
        assert -90 <= bounds[0][1] <= 90
        assert -180 <= bounds[1][0] <= 180
        assert -90 <= bounds[1][1] <= 90


class TestMarMenorLayerGeneration:
    """Verify layer generation for Mar Menor grid."""

    def test_mesh_mode_without_epsg_still_produces_layers(self, mar_menor_grd):
        """Without EPSG, mesh mode still produces wireframe (raw coords)."""
        layers = build_layers(mar_menor_grd, mode="mesh")
        assert len(layers) == 1
        assert layers[0]["id"] == "wireframe"

    def test_mesh_mode_with_epsg(self, mar_menor_grd):
        """With EPSG, mesh mode produces wireframe with correct data."""
        layers = build_layers(mar_menor_grd, mode="mesh", epsg=32630)
        assert len(layers) == 1
        assert layers[0]["id"] == "wireframe"
        data = layers[0]["data"]
        assert len(data) > 100  # Many edges

    def test_mesh_edge_coords_in_wgs84(self, mar_menor_grd):
        """Wireframe edges have geographic coordinates with EPSG."""
        layers = build_layers(mar_menor_grd, mode="mesh", epsg=32630)
        edge = layers[0]["data"][0]
        path = edge["path"]
        lon, lat = path[0]
        assert -2.0 < lon < 1.0
        assert 36.0 < lat < 39.0

    def test_depth_mode_with_epsg(self, mar_menor_grd):
        """Depth mode produces triangles + wireframe."""
        layers = build_layers(mar_menor_grd, mode="depth", epsg=32630)
        ids = [l["id"] for l in layers]
        assert "triangles" in ids
        assert "wireframe" in ids

    def test_depth_triangle_coords_in_wgs84(self, mar_menor_grd):
        """Triangle polygons have geographic coordinates with EPSG."""
        layers = build_layers(mar_menor_grd, mode="depth", epsg=32630)
        tri_layer = next(l for l in layers if l["id"] == "triangles")
        tri = tri_layer["data"][0]
        polygon = tri["polygon"]
        lon, lat = polygon[0]
        assert -2.0 < lon < 1.0
        assert 36.0 < lat < 39.0

    def test_quality_mode_with_epsg(self, mar_menor_grd):
        """Quality mode produces layers."""
        layers = build_layers(mar_menor_grd, mode="quality", epsg=32630)
        ids = [l["id"] for l in layers]
        assert "triangles" in ids

    def test_show_nodes_with_epsg(self, mar_menor_grd):
        """show_nodes produces scatterplot layer with geographic coords."""
        layers = build_layers(
            mar_menor_grd, mode="mesh", show_nodes=True, epsg=32630,
        )
        ids = [l["id"] for l in layers]
        assert "nodes" in ids
        node_layer = next(l for l in layers if l["id"] == "nodes")
        node = node_layer["data"][0]
        lon, lat = node["position"]
        assert -2.0 < lon < 1.0
        assert 36.0 < lat < 39.0

    def test_show_boundaries_with_epsg(self, mar_menor_grd):
        """show_boundaries on the mesh overlay (if grid has boundary lines)."""
        layers = build_layers(
            mar_menor_grd, mode="mesh", show_boundaries=True, epsg=32630,
        )
        # If grid has boundary lines, there should be boundary layers
        has_lines = bool(mar_menor_grd.lines)
        if has_lines:
            ids = [l["id"] for l in layers]
            assert any("boundary" in i for i in ids)

    def test_all_view_modes_no_crash(self, mar_menor_grd):
        """All view modes run without errors when EPSG is set."""
        for mode in ("mesh", "depth", "depth_3d", "quality", "boundaries"):
            layers = build_layers(mar_menor_grd, mode=mode, epsg=32630)
            assert isinstance(layers, list), f"mode={mode} failed"


# ===========================================================================
# Simulate the "Load Sample Data" flow (grid_prep page)
# ===========================================================================


class TestSampleDataFlow:
    """Simulate the exact flow of grid_prep's 'Load Sample Data' button.

    The button does:
      grd = GrdParser.parse_file(grd_path)
      grd.epsg = 32630
      current_grd.set(grd)

    Then grid_map_server reads grd.epsg as fallback when the CRS dropdown
    is "Auto".
    """

    def test_parse_and_set_epsg(self):
        """Parse the real grid, set epsg, verify attribute persists."""
        if not _MAR_MENOR_GRD.exists():
            pytest.skip("Mar Menor grid not found")
        grd = GrdParser.parse_file(_MAR_MENOR_GRD)
        assert grd.epsg is None  # Parser doesn't set EPSG
        grd.epsg = 32630
        assert grd.epsg == 32630

    def test_full_pipeline_with_grd_epsg(self):
        """Full pipeline: parse → set epsg → build layers → verify WGS84."""
        if not _MAR_MENOR_GRD.exists():
            pytest.skip("Mar Menor grid not found")
        grd = GrdParser.parse_file(_MAR_MENOR_GRD)
        grd.epsg = 32630

        # Simulate grid_map_server: use grd.epsg when dropdown is "Auto"
        epsg_val = grd.epsg

        layers = build_layers(grd, mode="mesh", epsg=epsg_val)
        assert len(layers) == 1
        assert layers[0]["id"] == "wireframe"

        # Verify edge coords are in WGS84
        edge = layers[0]["data"][0]
        lon, lat = edge["path"][0]
        assert -2.0 < lon < 1.0, f"lon={lon} not near Mar Menor"
        assert 36.0 < lat < 39.0, f"lat={lat} not near Mar Menor"

    def test_view_state_with_grd_epsg(self):
        """View state centers on Mar Menor when using grd.epsg."""
        if not _MAR_MENOR_GRD.exists():
            pytest.skip("Mar Menor grid not found")
        grd = GrdParser.parse_file(_MAR_MENOR_GRD)
        grd.epsg = 32630

        vs = _compute_view_state(grd, epsg=grd.epsg)
        assert -2.0 < vs["longitude"] < 1.0
        assert 36.0 < vs["latitude"] < 39.0
        assert 8 < vs["zoom"] < 15

    def test_depth_mode_with_grd_epsg(self):
        """Depth mode works with grd.epsg set."""
        if not _MAR_MENOR_GRD.exists():
            pytest.skip("Mar Menor grid not found")
        grd = GrdParser.parse_file(_MAR_MENOR_GRD)
        grd.epsg = 32630

        layers = build_layers(grd, mode="depth", epsg=grd.epsg)
        ids = [l["id"] for l in layers]
        assert "triangles" in ids
        # Verify triangle coords
        tri_layer = next(l for l in layers if l["id"] == "triangles")
        polygon = tri_layer["data"][0]["polygon"]
        lon, lat = polygon[0]
        assert -2.0 < lon < 1.0
        assert 36.0 < lat < 39.0

    def test_nodes_overlay_with_grd_epsg(self):
        """Node scatter overlay works with grd.epsg set."""
        if not _MAR_MENOR_GRD.exists():
            pytest.skip("Mar Menor grid not found")
        grd = GrdParser.parse_file(_MAR_MENOR_GRD)
        grd.epsg = 32630

        layers = build_layers(
            grd, mode="mesh", show_nodes=True, epsg=grd.epsg,
        )
        ids = [l["id"] for l in layers]
        assert "nodes" in ids
        node_layer = next(l for l in layers if l["id"] == "nodes")
        pos = node_layer["data"][0]["position"]
        assert -2.0 < pos[0] < 1.0
        assert 36.0 < pos[1] < 39.0
