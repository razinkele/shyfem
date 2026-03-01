"""Tests for grid inspection helper functions in pages/grid_prep.py."""

import math

import pytest

from shyfem_ui.pages.grid_prep import (
    _get_triangle_vertices,
    compute_boundary_summary,
    compute_element_areas,
    compute_element_quality,
    compute_min_angles,
)
from shyfem_ui.services.parser_grd import Element, GrdFile, Line, Node


# ---------------------------------------------------------------------------
# Helpers to build test grids
# ---------------------------------------------------------------------------

def _make_grid(nodes_dict, elements_dict, lines_dict=None):
    """Create a GrdFile from dicts."""
    grd = GrdFile()
    grd.nodes = nodes_dict
    grd.elements = elements_dict
    grd.lines = lines_dict or {}
    return grd


def _equilateral_nodes():
    """Equilateral triangle with side length 2."""
    return {
        1: Node(id=1, node_type=0, x=0.0, y=0.0),
        2: Node(id=2, node_type=0, x=2.0, y=0.0),
        3: Node(id=3, node_type=0, x=1.0, y=math.sqrt(3.0)),
    }


def _right_triangle_nodes():
    """Right triangle: (0,0), (1,0), (0,1)."""
    return {
        1: Node(id=1, node_type=0, x=0.0, y=0.0),
        2: Node(id=2, node_type=0, x=1.0, y=0.0),
        3: Node(id=3, node_type=0, x=0.0, y=1.0),
    }


def _skinny_triangle_nodes():
    """Very thin triangle with a small minimum angle (~5.7 degrees)."""
    return {
        1: Node(id=1, node_type=0, x=0.0, y=0.0),
        2: Node(id=2, node_type=0, x=10.0, y=0.0),
        3: Node(id=3, node_type=0, x=5.0, y=0.5),
    }


# ---------------------------------------------------------------------------
# _get_triangle_vertices
# ---------------------------------------------------------------------------

class TestGetTriangleVertices:

    def test_true_triangle(self):
        """3 nodes → return as-is."""
        elem = Element(id=1, elem_type=0, nodes=[10, 20, 30])
        result = _get_triangle_vertices(elem, {})
        assert result == [10, 20, 30]

    def test_parser_quirk(self):
        """4 nodes with first=3 → parser quirk, return last 3."""
        elem = Element(id=1, elem_type=0, nodes=[3, 10, 20, 30])
        result = _get_triangle_vertices(elem, {})
        assert result == [10, 20, 30]

    def test_genuine_quad(self):
        """4 nodes with first≠3 → genuine quad, return None."""
        elem = Element(id=1, elem_type=0, nodes=[4, 10, 20, 30])
        result = _get_triangle_vertices(elem, {})
        assert result is None

    def test_five_nodes(self):
        """5 nodes → polygon, return None."""
        elem = Element(id=1, elem_type=0, nodes=[5, 10, 20, 30, 40])
        result = _get_triangle_vertices(elem, {})
        assert result is None

    def test_two_nodes(self):
        """2 nodes → not a triangle, return None."""
        elem = Element(id=1, elem_type=0, nodes=[10, 20])
        result = _get_triangle_vertices(elem, {})
        assert result is None


# ---------------------------------------------------------------------------
# compute_element_quality
# ---------------------------------------------------------------------------

class TestComputeElementQuality:

    def test_equilateral(self):
        """Equilateral triangle → quality = 1.0."""
        nodes = _equilateral_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_element_quality(grd)
        assert result["stats"]["count"] == 1
        assert result["qualities"][0] == pytest.approx(1.0, abs=1e-6)

    def test_right_triangle(self):
        """Right triangle (1,1,√2 sides) → quality = 1/√2 ≈ 0.707."""
        nodes = _right_triangle_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_element_quality(grd)
        assert result["qualities"][0] == pytest.approx(1.0 / math.sqrt(2), abs=1e-4)

    def test_parser_quirk_elements(self):
        """Elements with parser quirk (nodes=[3,n1,n2,n3]) are handled."""
        nodes = _equilateral_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[3, 1, 2, 3])})
        result = compute_element_quality(grd)
        assert result["stats"]["count"] == 1
        assert result["qualities"][0] == pytest.approx(1.0, abs=1e-6)

    def test_empty_grid(self):
        """Empty grid → stats is None."""
        grd = _make_grid({}, {})
        result = compute_element_quality(grd)
        assert result["stats"] is None
        assert result["qualities"] == []

    def test_thresholds(self):
        """below_03 and below_05 counts are correct."""
        nodes = {
            1: Node(id=1, node_type=0, x=0.0, y=0.0),
            2: Node(id=2, node_type=0, x=1.0, y=0.0),
            3: Node(id=3, node_type=0, x=0.5, y=math.sqrt(3) / 2),
            4: Node(id=4, node_type=0, x=10.0, y=0.0),
            5: Node(id=5, node_type=0, x=10.01, y=1.0),
        }
        # Element 1: equilateral (q=1.0), Element 2: very skinny (q~0.01)
        elems = {
            1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),
            2: Element(id=2, elem_type=0, nodes=[1, 4, 5]),
        }
        grd = _make_grid(nodes, elems)
        result = compute_element_quality(grd)
        assert result["stats"]["count"] == 2
        assert result["stats"]["below_03"] == 1
        assert result["stats"]["below_05"] == 1

    def test_missing_node_skipped(self):
        """Element referencing missing node is skipped."""
        nodes = _equilateral_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 999])})
        result = compute_element_quality(grd)
        assert result["stats"] is None


# ---------------------------------------------------------------------------
# compute_element_areas
# ---------------------------------------------------------------------------

class TestComputeElementAreas:

    def test_right_triangle_area(self):
        """Right triangle (0,0)-(1,0)-(0,1) → area = 0.5."""
        nodes = _right_triangle_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_element_areas(grd)
        assert result["areas"][0] == pytest.approx(0.5, abs=1e-10)

    def test_equilateral_area(self):
        """Equilateral triangle side=2 → area = √3."""
        nodes = _equilateral_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_element_areas(grd)
        assert result["areas"][0] == pytest.approx(math.sqrt(3), abs=1e-6)

    def test_area_ratio(self):
        """Area ratio = max/min when two triangles of different size."""
        nodes = {
            1: Node(id=1, node_type=0, x=0.0, y=0.0),
            2: Node(id=2, node_type=0, x=1.0, y=0.0),
            3: Node(id=3, node_type=0, x=0.0, y=1.0),
            4: Node(id=4, node_type=0, x=0.0, y=0.0),
            5: Node(id=5, node_type=0, x=2.0, y=0.0),
            6: Node(id=6, node_type=0, x=0.0, y=2.0),
        }
        elems = {
            1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),  # area=0.5
            2: Element(id=2, elem_type=0, nodes=[4, 5, 6]),  # area=2.0
        }
        grd = _make_grid(nodes, elems)
        result = compute_element_areas(grd)
        assert result["stats"]["area_ratio"] == pytest.approx(4.0, abs=1e-6)

    def test_empty_grid(self):
        """Empty grid → stats is None."""
        grd = _make_grid({}, {})
        result = compute_element_areas(grd)
        assert result["stats"] is None

    def test_parser_quirk_areas(self):
        """Parser quirk elements are handled for area."""
        nodes = _right_triangle_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[3, 1, 2, 3])})
        result = compute_element_areas(grd)
        assert result["areas"][0] == pytest.approx(0.5, abs=1e-10)


# ---------------------------------------------------------------------------
# compute_min_angles
# ---------------------------------------------------------------------------

class TestComputeMinAngles:

    def test_equilateral(self):
        """Equilateral → all angles = 60°, min = 60°."""
        nodes = _equilateral_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_min_angles(grd)
        assert result["min_angles"][0] == pytest.approx(60.0, abs=0.1)

    def test_right_triangle(self):
        """Right triangle (1,1,√2) → angles = 45°, 45°, 90°, min = 45°."""
        nodes = _right_triangle_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_min_angles(grd)
        assert result["min_angles"][0] == pytest.approx(45.0, abs=0.1)

    def test_below_20_count(self):
        """Skinny triangle has min angle < 20°."""
        nodes = _skinny_triangle_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])})
        result = compute_min_angles(grd)
        assert result["stats"]["below_20"] == 1
        assert result["min_angles"][0] < 20.0

    def test_empty_grid(self):
        """Empty grid → stats is None."""
        grd = _make_grid({}, {})
        result = compute_min_angles(grd)
        assert result["stats"] is None

    def test_parser_quirk_angles(self):
        """Parser quirk elements are handled for angles."""
        nodes = _equilateral_nodes()
        grd = _make_grid(nodes, {1: Element(id=1, elem_type=0, nodes=[3, 1, 2, 3])})
        result = compute_min_angles(grd)
        assert result["min_angles"][0] == pytest.approx(60.0, abs=0.1)


# ---------------------------------------------------------------------------
# compute_boundary_summary
# ---------------------------------------------------------------------------

class TestComputeBoundarySummary:

    def test_with_boundaries(self):
        """Lines are returned sorted by line_id."""
        grd = GrdFile()
        grd.lines = {
            3: Line(id=3, line_type=2, nodes=[10, 11, 12]),
            1: Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 5]),
        }
        result = compute_boundary_summary(grd)
        assert len(result) == 2
        assert result[0]["line_id"] == 1
        assert result[0]["line_type"] == 1
        assert result[0]["node_count"] == 5
        assert result[0]["node_range_str"] == "1-5"
        assert result[1]["line_id"] == 3
        assert result[1]["node_count"] == 3

    def test_no_boundaries(self):
        """Grid with no lines → empty list."""
        grd = GrdFile()
        result = compute_boundary_summary(grd)
        assert result == []

    def test_single_boundary(self):
        """Single boundary line."""
        grd = GrdFile()
        grd.lines = {1: Line(id=1, line_type=0, nodes=[50, 100])}
        result = compute_boundary_summary(grd)
        assert len(result) == 1
        assert result[0]["node_range_str"] == "50-100"
