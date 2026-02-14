"""Tests for grid statistics JSON export."""

import json


def _make_stats():
    """Create a realistic stats dict matching GrdParser.get_statistics() output."""
    return {
        "num_nodes": 1234,
        "num_elements": 2345,
        "num_triangles": 2000,
        "num_quads": 345,
        "num_lines": 50,
        "bounds": {
            "xmin": 0.0,
            "xmax": 100.5,
            "ymin": 10.0,
            "ymax": 55.3,
            "width": 100.5,
            "height": 45.3,
        },
        "depth": {"min": -2.5, "max": 30.0, "mean": 12.4},
        "node_types": [1, 2, 3],
        "element_types": [3, 4],
        "line_types": [1],
    }


class TestGridStatsToJson:
    """Tests for grid_stats_to_json()."""

    def test_valid_stats(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        stats = _make_stats()
        result = grid_stats_to_json(stats, "test_grid")
        parsed = json.loads(result)
        assert parsed["grid_name"] == "test_grid"
        assert parsed["statistics"]["num_nodes"] == 1234
        assert parsed["statistics"]["bounds"]["xmax"] == 100.5

    def test_empty_stats(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        result = grid_stats_to_json({}, "empty")
        parsed = json.loads(result)
        assert parsed["grid_name"] == "empty"
        assert parsed["statistics"] == {}

    def test_none_depth_values(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        stats = _make_stats()
        stats["depth"] = {"min": None, "max": None, "mean": None}
        result = grid_stats_to_json(stats, "no_depth")
        parsed = json.loads(result)
        assert parsed["statistics"]["depth"]["min"] is None

    def test_output_is_indented(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        result = grid_stats_to_json(_make_stats(), "test")
        assert "\n    " in result  # 4-space indent

    def test_sets_converted_to_lists(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        stats = _make_stats()
        stats["node_types"] = {1, 2, 3}  # set instead of list
        result = grid_stats_to_json(stats, "set_test")
        parsed = json.loads(result)
        assert sorted(parsed["statistics"]["node_types"]) == [1, 2, 3]
