"""Tests for deck.gl grid map data builders (Tasks 1-4).

Tests cover: _get_lonlat, _build_edge_data, _build_triangle_data,
_build_boundary_data, _build_node_data, and helper functions.
"""

from __future__ import annotations

import math

import pytest

from shyfem_ui.components.grid_map import (
    BOUNDARY_COLORS,
    PARTITION_COLORS,
    _build_boundary_data,
    _build_edge_data,
    _build_node_data,
    _build_triangle_data,
    _compute_quality,
    _depth_to_colors,
    _get_lonlat,
    _quality_to_colors,
)
from shyfem_ui.services.parser_grd import (
    CoordinateSystem,
    Element,
    GrdFile,
    Line,
    Node,
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
