"""Tests for pure helpers extracted from pages/grid_prep.py."""
import json
from types import SimpleNamespace

import pytest

from shyfem_ui.services.grid_prep_logic import (
    compute_boundary_summary,
    format_element_shape,
    grid_stats_to_json,
)


class TestGridStatsToJson:

    def test_basic_dict_round_trip(self):
        stats = {"num_nodes": 100, "num_elements": 200}
        result = grid_stats_to_json(stats, "mygrid")
        parsed = json.loads(result)
        assert parsed["grid_name"] == "mygrid"
        assert parsed["statistics"]["num_nodes"] == 100
        assert parsed["statistics"]["num_elements"] == 200

    def test_set_values_sorted_to_list(self):
        # The default= handler converts sets to sorted lists for stable output
        stats = {"node_types": {3, 1, 2}}
        result = grid_stats_to_json(stats, "g")
        parsed = json.loads(result)
        # Must round-trip cleanly AND the list is sorted
        assert parsed["statistics"]["node_types"] == [1, 2, 3]

    def test_indented_output(self):
        stats = {"x": 1}
        result = grid_stats_to_json(stats, "g")
        # indent=4 produces newlines + leading spaces
        assert "\n" in result
        assert "    " in result

    def test_unsupported_type_raises(self):
        # The default= raises TypeError for unknown types
        class Weird:
            pass

        with pytest.raises(TypeError, match="not JSON serializable"):
            grid_stats_to_json({"x": Weird()}, "g")


class TestComputeBoundarySummary:

    def _make_grd(self, lines_data):
        """Build a fake grd object with .lines mapping."""
        lines = {}
        for lid, ltype, nodes in lines_data:
            lines[lid] = SimpleNamespace(line_type=ltype, nodes=nodes)
        return SimpleNamespace(lines=lines)

    def test_empty_grd(self):
        grd = self._make_grd([])
        assert compute_boundary_summary(grd) == []

    def test_single_line(self):
        grd = self._make_grd([(1, 0, [10, 20, 30])])
        result = compute_boundary_summary(grd)
        assert len(result) == 1
        assert result[0] == {
            "line_id": 1,
            "line_type": 0,
            "node_count": 3,
            "node_range_str": "10-30",
        }

    def test_sorted_by_line_id(self):
        grd = self._make_grd([
            (3, 0, [1, 2]),
            (1, 1, [3, 4]),
            (2, 0, [5, 6]),
        ])
        result = compute_boundary_summary(grd)
        ids = [r["line_id"] for r in result]
        assert ids == [1, 2, 3]

    def test_empty_node_list(self):
        grd = self._make_grd([(1, 0, [])])
        result = compute_boundary_summary(grd)
        assert result[0]["node_count"] == 0
        assert result[0]["node_range_str"] == ""


class TestFormatElementShape:

    def _elem(self, *, is_triangle=False, is_quad=False, nodes=None):
        return SimpleNamespace(
            is_triangle=is_triangle, is_quad=is_quad, nodes=nodes or [],
        )

    def test_triangle(self):
        e = self._elem(is_triangle=True, nodes=[1, 2, 3])
        assert format_element_shape(e) == "Tri"

    def test_quad(self):
        e = self._elem(is_quad=True, nodes=[1, 2, 3, 4])
        assert format_element_shape(e) == "Quad"

    def test_pentagon(self):
        e = self._elem(nodes=[1, 2, 3, 4, 5])
        assert format_element_shape(e) == "5-gon"

    def test_triangle_takes_precedence_over_quad(self):
        # Defensive: if both flags are somehow set, triangle wins (matches
        # the original ternary order in node_inspector).
        e = self._elem(is_triangle=True, is_quad=True, nodes=[1, 2, 3])
        assert format_element_shape(e) == "Tri"
