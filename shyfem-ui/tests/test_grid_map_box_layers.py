"""Tests for box-layer support in the grid map component (Task 9).

Covers the pure helpers ``value_colors`` and ``build_box_layers``, plus a
source-level check that ``grid_map_server`` gained the box-click branch and
the ``extra_layers``/``on_box_click`` parameters without disturbing the
existing node-click behaviour.
"""

from __future__ import annotations

import inspect
import math

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


def test_value_colors_handles_nan_and_none():
    colors, bins = gm.value_colors([1.0, float("nan"), None, 2.0])
    assert len(colors) == 4
    assert colors[1] == [200, 200, 200] and colors[2] == [200, 200, 200]
    assert colors[0] != [200, 200, 200] and colors[3] != [200, 200, 200]
    assert len(bins) == 6
    assert bins[0][0] == pytest.approx(1.0) and bins[-1][1] == pytest.approx(2.0)


def test_value_colors_all_non_finite_returns_all_grey_and_empty_bins():
    colors, bins = gm.value_colors([float("nan"), None, float("inf")])
    assert colors == [[200, 200, 200], [200, 200, 200], [200, 200, 200]]
    assert bins == []


def test_helpers_degrade_without_shiny_deckgl(monkeypatch):
    monkeypatch.setattr(gm, "polygon_layer", None)
    monkeypatch.setattr(gm, "scatterplot_layer", None)
    monkeypatch.setattr(gm, "color_bins", None)

    polys = {1: [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]}
    assert gm.build_box_layers(polys, {1: 1.0}) == ([], [])

    colors, bins = gm.value_colors([1.0, 2.0])
    # Minor 3: the degrade path used its own grey; there is one
    # "no colour to give" colour and every path uses it.
    assert colors == [list(gm._NON_FINITE_COLOR)] * 2
    assert bins == []


def test_bounds_from_layers_polygon_and_point():
    layers = [
        {"data": [{"polygon": [[0.0, 1.0], [2.0, 1.0], [2.0, 3.0], [0.0, 1.0]]}]},
        {"data": [{"position": [5.0, -1.0]}]},
    ]
    bounds = gm._bounds_from_layers(layers)
    assert bounds == [[0.0, -1.0], [5.0, 3.0]]


def test_bounds_from_layers_empty_returns_none():
    assert gm._bounds_from_layers([]) is None
    assert gm._bounds_from_layers([{"data": []}]) is None


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


def test_build_box_layers_escapes_tooltip_text():
    """Every ``tooltip_html`` built here is rendered by deck.gl as innerHTML
    (``tooltip={"html": "{tooltip_html}"}``), so a site name or a value label
    is an XSS sink. On a shared project one user's sites.csv is rendered in
    every collaborator's browser, so the escaping must happen at the sink."""
    evil_site = "<img src=x onerror=alert(1)>"
    evil_label = "<script>alert(2)</script>"
    layers, _bins = gm.build_box_layers(
        {1: [[21.0, 55.5], [21.01, 55.5], [21.01, 55.51], [21.0, 55.5]]},
        {1: 0.2},
        label=evil_label,
        posts=[{"site": evil_site, "lon": 21.005, "lat": 55.505, "value": 0.25}],
    )
    box_tip = layers[0]["data"][0]["tooltip_html"]
    post_tip = layers[1]["data"][0]["tooltip_html"]
    for tip in (box_tip, post_tip):
        assert "<img" not in tip
        assert "<script" not in tip
        # The payload text may still appear -- escaped, it is inert. What must
        # not survive is an unescaped tag delimiter: strip the component's own
        # markup and nothing with "<" or ">" may be left.
        bare = tip.replace("<b>", "").replace("</b>", "").replace("<br>", "")
        assert "<" not in bare and ">" not in bare
    # escaped, not merely dropped -- the text still reaches the user
    assert "&lt;img src=x onerror=alert(1)&gt;" in post_tip
    assert "&lt;script&gt;" in box_tip


def test_build_box_layers_escapes_outline_only_tooltip():
    """The no-values branch builds its own tooltip; it must be safe too."""
    layers, _bins = gm.build_box_layers({1: [[0, 0], [1, 0], [1, 1], [0, 0]]}, None)
    assert "<" not in layers[0]["data"][0]["tooltip_html"].replace("<b>", "").replace("</b>", "")


def test_build_box_layers_escapes_an_ampersand_exactly_once():
    """Escaping must happen here and ONLY here. A site legitimately named
    "Smith & Co" has to reach the tooltip as ``Smith &amp; Co`` -- if the caller
    escaped it too, it would arrive as ``Smith &amp;amp; Co`` and render with a
    visible "&amp;"."""
    layers, _bins = gm.build_box_layers(
        {1: [[21.0, 55.5], [21.01, 55.5], [21.01, 55.51], [21.0, 55.5]]},
        {1: 0.2},
        label="Salinity & more",
        posts=[{"site": "Smith & Co", "lon": 21.005, "lat": 55.505, "value": 0.25}],
    )
    post_tip = layers[1]["data"][0]["tooltip_html"]
    box_tip = layers[0]["data"][0]["tooltip_html"]
    assert "Smith &amp; Co" in post_tip
    assert "&amp;amp;" not in post_tip
    assert "Salinity &amp; more" in box_tip
    assert "&amp;amp;" not in box_tip


# --- PR 2 Task 4: diverging palette + symmetric scale -----------------------


def test_diverging_palette_is_registered_blue_white_red():
    pal = gm.PALETTES["diverging"]
    assert pal is gm.PALETTE_DIVERGING and len(pal) == 7
    first, mid, last = pal[0], pal[3], pal[-1]
    assert first[2] > first[0]  # blue end
    assert all(c >= 240 for c in mid[:3])  # white centre
    assert last[0] > last[2]  # red end


def test_value_colors_symmetric_bins_are_mirrored_around_zero():
    colors, bins = gm.value_colors([-3.0, 1.0, 2.0], palette="diverging", symmetric=True)
    assert len(colors) == 3 and all(len(c) == 3 for c in colors)
    assert bins[0][0] == pytest.approx(-3.0) and bins[-1][1] == pytest.approx(3.0)
    # every bin has a mirror image: (lo, hi) <-> (-hi, -lo)
    edges = [(lo, hi) for lo, hi, _ in bins]
    for lo, hi in edges:
        assert any(mlo == pytest.approx(-hi) and mhi == pytest.approx(-lo) for mlo, mhi in edges), (
            lo,
            hi,
        )
    # one bin straddles zero and it is the white centre of the palette
    centre = [b for b in bins if b[0] < 0 < b[1]]
    assert len(centre) == 1 and centre[0][2] == list(gm.PALETTE_DIVERGING[3][:3])
    # -3 is the extreme blue, +2 sits on the red side, neither is white
    assert colors[0] == list(gm.PALETTE_DIVERGING[0][:3])
    assert colors[2][0] > colors[2][2] and colors[2] != centre[0][2]


def test_value_colors_symmetric_all_zero_does_not_divide_by_zero():
    colors, bins = gm.value_colors([0.0, 0.0], palette="diverging", symmetric=True)
    assert bins[0][0] == pytest.approx(-1.0) and bins[-1][1] == pytest.approx(1.0)
    assert all(math.isfinite(lo) and math.isfinite(hi) for lo, hi, _ in bins)
    # both zeros land in the central (white) bin
    assert colors == [list(gm.PALETTE_DIVERGING[3][:3])] * 2


def test_value_colors_symmetric_keeps_positions_and_grey_for_gaps():
    colors, bins = gm.value_colors(
        [float("nan"), -0.5, None, 0.25], palette="diverging", symmetric=True
    )
    assert len(colors) == 4
    assert colors[0] == gm._NON_FINITE_COLOR and colors[2] == gm._NON_FINITE_COLOR
    assert colors[1] != gm._NON_FINITE_COLOR and colors[3] != gm._NON_FINITE_COLOR
    # legend spans [-m, m] with m = max(|finite|), not the sentinel-free range
    assert bins[0][0] == pytest.approx(-0.5) and bins[-1][1] == pytest.approx(0.5)


def test_value_colors_non_symmetric_path_unchanged_by_the_new_keyword():
    before = gm.value_colors([-3.0, 1.0, 2.0], palette="viridis")
    after = gm.value_colors([-3.0, 1.0, 2.0], palette="viridis", symmetric=False)
    assert before == after
    assert before[1][0][0] == pytest.approx(-3.0) and before[1][-1][1] == pytest.approx(2.0)


def test_build_box_layers_symmetric_legend_straddles_zero():
    polys = {
        1: [[21.0, 55.5], [21.01, 55.5], [21.01, 55.51], [21.0, 55.5]],
        2: [[21.01, 55.5], [21.02, 55.5], [21.02, 55.51], [21.01, 55.5]],
        3: [[21.02, 55.5], [21.03, 55.5], [21.03, 55.51], [21.02, 55.5]],
    }
    layers, bins = gm.build_box_layers(
        polys, {1: -1.5, 2: 0.2, 3: float("nan")}, palette="diverging", symmetric=True
    )
    assert bins[0][0] == pytest.approx(-1.5) and bins[-1][1] == pytest.approx(1.5)
    assert any(lo < 0 < hi for lo, hi, _ in bins)
    data = layers[0]["data"]
    assert data[0]["color"][:3] == list(gm.PALETTE_DIVERGING[0][:3])  # extreme blue
    assert data[2]["color"][:3] == [200, 200, 200]  # gap stays grey
    # default is still the plain (min..max) scale
    _layers, plain = gm.build_box_layers(polys, {1: -1.5, 2: 0.2}, palette="diverging")
    assert plain[0][0] == pytest.approx(-1.5) and plain[-1][1] == pytest.approx(0.2)
