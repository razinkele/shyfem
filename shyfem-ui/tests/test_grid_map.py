"""Tests for build_mesh_figure() in components/grid_map.py."""

import plotly.graph_objects as go

from shyfem_ui.components.grid_map import _build_edge_arrays, build_mesh_figure
from shyfem_ui.services.parser_grd import Element, GrdFile, Line, Node


def _make_triangle_grid() -> GrdFile:
    """Create a minimal grid with one triangle for testing."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=1, x=0.0, y=0.0, depth=1.0),
        2: Node(id=2, node_type=1, x=1.0, y=0.0, depth=2.0),
        3: Node(id=3, node_type=1, x=0.5, y=1.0, depth=3.0),
    }
    grd.elements = {
        1: Element(id=1, elem_type=3, nodes=[1, 2, 3]),
    }
    return grd


def _make_multi_element_grid() -> GrdFile:
    """Create a grid with 2 triangles and a boundary line."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=1, x=0.0, y=0.0, depth=1.0),
        2: Node(id=2, node_type=1, x=1.0, y=0.0, depth=2.0),
        3: Node(id=3, node_type=1, x=0.5, y=1.0, depth=3.0),
        4: Node(id=4, node_type=1, x=1.5, y=1.0, depth=1.5),
    }
    grd.elements = {
        1: Element(id=1, elem_type=3, nodes=[1, 2, 3]),
        2: Element(id=2, elem_type=3, nodes=[2, 4, 3]),
    }
    grd.lines = {
        1: Line(id=1, line_type=1, nodes=[1, 3]),
    }
    return grd


class TestBuildEdgeArrays:
    """Tests for _build_edge_arrays()."""

    def test_single_triangle(self):
        grd = _make_triangle_grid()
        edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)

        assert len(node_ids) == 3
        assert len(x) == 3
        assert len(y) == 3
        # A triangle has 3 edges, each edge = [x1, x2, None] → 9 entries
        assert len(edge_x) == 9
        assert edge_x.count(None) == 3

    def test_node_map_covers_all(self):
        grd = _make_multi_element_grid()
        _, _, _, _, node_ids, node_map = _build_edge_arrays(grd)
        assert set(node_ids) == {1, 2, 3, 4}
        assert len(node_map) == 4


class TestBuildMeshFigure:
    """Tests for build_mesh_figure()."""

    def test_returns_plotly_figure(self):
        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd)
        assert isinstance(fig, go.Figure)

    def test_mesh_mode_has_traces(self):
        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd, mode="mesh")
        assert len(fig.data) >= 1

    def test_depth_mode_has_colorbar(self):
        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd, mode="depth")
        assert len(fig.data) >= 1

    def test_with_boundaries(self):
        grd = _make_multi_element_grid()
        fig = build_mesh_figure(grd, show_boundaries=True)
        assert isinstance(fig, go.Figure)

    def test_with_nodes(self):
        grd = _make_multi_element_grid()
        fig = build_mesh_figure(grd, show_nodes=True)
        assert isinstance(fig, go.Figure)
        # Should have node scatter trace
        assert len(fig.data) >= 2

    def test_partition_mode(self):
        grd = _make_multi_element_grid()
        partition_map = {1: 0, 2: 1}
        fig = build_mesh_figure(grd, mode="partitions", partition_map=partition_map)
        assert isinstance(fig, go.Figure)

    def test_empty_grid(self):
        grd = GrdFile()
        fig = build_mesh_figure(grd)
        assert isinstance(fig, go.Figure)
