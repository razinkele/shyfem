"""Tests for box-layer support in the grid map component (Task 9).

Covers the pure helpers ``value_colors`` and ``build_box_layers``, plus a
source-level check that ``grid_map_server`` gained the box-click branch and
the ``extra_layers``/``on_box_click`` parameters without disturbing the
existing node-click behaviour.
"""

from __future__ import annotations

import inspect

import pytest

from shyfem_ui.components import grid_map as gm

pytest.importorskip("shiny_deckgl")


def test_value_colors_bins_and_legend():
    colors, bins = gm.value_colors([0.0, 0.5, 1.0], palette="viridis", n_bins=2)
    assert len(colors) == 3 and all(len(c) == 3 for c in colors)
    assert len(bins) == 2 and bins[0][0] == pytest.approx(0.0) and bins[-1][1] == pytest.approx(1.0)
    assert colors[0] != colors[2]


def test_build_box_layers_polygon_and_posts():
    polys = {
        1: [[21.0, 55.5], [21.01, 55.5], [21.01, 55.51], [21.0, 55.5]],
        2: [[21.01, 55.5], [21.02, 55.5], [21.02, 55.51], [21.01, 55.5]],
    }
    layers, bins = gm.build_box_layers(
        polys,
        {1: 0.2, 2: 0.8},
        label="salt",
        posts=[{"site": "A", "lon": 21.005, "lat": 55.505, "value": 0.25}],
        selected=2,
    )
    ids = [lyr["id"] for lyr in layers]
    assert ids == ["boxes", "posts"]
    boxes = layers[0]
    data = boxes["data"]
    assert [d["box"] for d in data] == [1, 2] and data[1]["value"] == 0.8
    assert (
        boxes["getFillColor"] == "@@d.color"
        and boxes["getPolygon"] == "@@d.polygon"
        and boxes["pickable"] is True
    )
    assert (
        "salt" in data[0]["tooltip_html"]
        and data[1]["color"][3] == 255
        and data[0]["color"][3] < 255
    )  # selection highlighted
    assert layers[1]["data"][0]["position"] == [21.005, 55.505]
    assert len(bins) == 6


def test_build_box_layers_without_values_is_outline_only():
    layers, bins = gm.build_box_layers({1: [[0, 0], [1, 0], [1, 1], [0, 0]]}, None)
    assert layers[0]["filled"] is False and bins == []


def test_grid_map_server_has_box_click_branch_and_extra_layers():
    src = (
        inspect.getsource(gm.grid_map_server.__closure__[0].cell_contents)
        if gm.grid_map_server.__closure__
        else inspect.getsource(gm.grid_map_server)
    )
    assert (
        '"box" in obj' in src
        and "selected_box" in src
        and "extra_layers" in src
        and "on_box_click" in src
    )
