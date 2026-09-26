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


# --- PR 3 Task 3: node positions + setup layers ------------------------------


def _iface(section, a, b, *, open_boundary=None, path=None):
    return {
        "section": section,
        "from_box": a,
        "to_box": b,
        "open_boundary": open_boundary,
        "path": path or [[21.0, 55.5], [21.01, 55.51]],
    }


def _bnode(node, boundary, kind, *, title="Fixture river", boundn="fem_forcing/river.txt"):
    return {
        "node": node,
        "lon": 21.0 + node / 100,
        "lat": 55.5,
        "boundary": boundary,
        "title": title,
        "kind": kind,
        "boundn": boundn,
    }


def _bare(tip: str) -> str:
    return tip.replace("<b>", "").replace("</b>", "").replace("<br>", "")


def test_node_positions_is_the_public_get_lonlat():
    from shyfem_ui.services.parser_grd import GrdFile, Node

    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=-0.80, y=37.70, depth=2.5),
        2: Node(id=2, node_type=0, x=-0.78, y=37.70, depth=4.0),
    }
    assert gm.node_positions(grd) == gm._get_lonlat(grd) == {1: [-0.80, 37.70], 2: [-0.78, 37.70]}
    assert gm.node_positions(GrdFile()) == {}
    assert gm.node_positions(grd, epsg=None) == gm.node_positions(grd)


def test_build_setup_layers_ids_and_open_vs_interior_split():
    interfaces = [
        _iface(1, 1, 2),
        _iface(2, -1, 1, open_boundary=1),
        _iface(3, 2, 3),
    ]
    points = [_bnode(1, 1, "level", title="Baltic sea", boundn="fem_forcing/sea.fem")]
    layers = gm.build_setup_layers(interfaces, points)
    assert [lyr["id"] for lyr in layers] == [
        "setup_interfaces",
        "setup_open_interfaces",
        "setup_boundary_nodes",
    ]
    interior, opened, nodes = layers
    assert [d["section"] for d in interior["data"]] == [1, 3]
    assert [d["section"] for d in opened["data"]] == [2]
    assert interior["data"][0]["path"] == [[21.0, 55.5], [21.01, 55.51]]
    assert interior["getPath"] == "@@d.path" and opened["getPath"] == "@@d.path"
    assert interior["pickable"] is True and opened["pickable"] is True
    # open-boundary interfaces are blue and wider than the grey interior ones
    assert opened["getColor"] == list(gm.SETUP_OPEN_INTERFACE_COLOR)
    assert interior["getColor"] == list(gm.SETUP_INTERFACE_COLOR)
    assert opened["widthMinPixels"] > interior["widthMinPixels"]
    # tooltips
    assert interior["data"][0]["tooltip_html"] == "section 1: box 1 → box 2"
    assert opened["data"][0]["tooltip_html"] == "section 2: open boundary 1 → box 1"
    # records carry the ids the page needs, but never the keys the click
    # handler of grid_map_server branches on ("box", "node_id")
    for d in interior["data"] + opened["data"] + nodes["data"]:
        assert "box" not in d and "node_id" not in d
    assert nodes["data"][0]["position"] == [21.01, 55.5]
    assert nodes["data"][0]["node"] == 1 and nodes["data"][0]["boundary"] == 1


def test_build_setup_layers_only_emits_layers_that_have_data():
    only_nodes = gm.build_setup_layers([], [_bnode(3, 2, "discharge")])
    assert [lyr["id"] for lyr in only_nodes] == ["setup_boundary_nodes"]
    only_interior = gm.build_setup_layers([_iface(1, 1, 2)], [])
    assert [lyr["id"] for lyr in only_interior] == ["setup_interfaces"]
    only_open = gm.build_setup_layers([_iface(1, -2, 4, open_boundary=2)], [])
    assert [lyr["id"] for lyr in only_open] == ["setup_open_interfaces"]
    # a degenerate path (fewer than two points) is dropped, like mesh boundaries
    assert gm.build_setup_layers([_iface(1, 1, 2, path=[[21.0, 55.5]])], []) == []


def test_build_setup_layers_colours_nodes_by_kind():
    points = [
        _bnode(1, 1, "level"),
        _bnode(2, 2, "discharge"),
        _bnode(3, 3, "unknown"),
        _bnode(4, 4, "something-else"),
    ]
    (nodes,) = gm.build_setup_layers([], points)
    colors = [d["color"] for d in nodes["data"]]
    assert colors[0] == list(gm.SETUP_KIND_COLORS["level"])
    assert colors[1] == list(gm.SETUP_KIND_COLORS["discharge"])
    assert colors[2] == list(gm.SETUP_KIND_COLORS["unknown"])
    assert colors[3] == list(gm.SETUP_KIND_COLORS["unknown"])  # unknown kind -> grey
    blue, green, grey = colors[0], colors[1], colors[2]
    assert blue[2] > blue[0] and green[1] > green[0] and grey[0] == grey[1] == grey[2]
    assert nodes["getFillColor"] == "@@d.color" and nodes["getPosition"] == "@@d.position"
    assert nodes["pickable"] is True
    # an unrecognised kind is rendered as "unknown", never echoed into the HTML
    assert "something-else" not in nodes["data"][3]["tooltip_html"]
    assert "unknown" in nodes["data"][3]["tooltip_html"]
    assert "level" in nodes["data"][0]["tooltip_html"]


def test_build_setup_layers_selected_boundary_nodes_are_larger():
    points = [_bnode(1, 1, "level"), _bnode(2, 2, "discharge"), _bnode(3, 2, "discharge")]
    (nodes,) = gm.build_setup_layers([], points, selected_boundary=2)
    radii = {d["node"]: d["radius"] for d in nodes["data"]}
    assert radii[2] == radii[3] > radii[1]
    assert nodes["getRadius"] == "@@d.radius" and nodes["radiusUnits"] == "pixels"
    assert nodes["radiusMinPixels"] <= radii[1]
    # no selection -> everyone gets the small radius
    (plain,) = gm.build_setup_layers([], points)
    assert {d["radius"] for d in plain["data"]} == {radii[1]}


def test_build_setup_layers_tooltip_names_boundary_node_and_file():
    (nodes,) = gm.build_setup_layers(
        [], [_bnode(7, 2, "discharge", title="Nemunas", boundn="fem_forcing/nemunas.txt")]
    )
    tip = nodes["data"][0]["tooltip_html"]
    assert tip.startswith("<b>Nemunas</b>")
    assert "boundary 2" in tip and "node 7" in tip and "discharge" in tip
    assert "fem_forcing/nemunas.txt" in tip
    # no title / no file: falls back to the boundary number, no "None" leaks
    (bare,) = gm.build_setup_layers([], [_bnode(7, 2, "level", title="", boundn=None)])
    tip2 = bare["data"][0]["tooltip_html"]
    assert tip2.startswith("<b>boundary 2</b>") and "None" not in tip2


def test_build_setup_layers_escapes_title_and_boundn():
    """The STR's ``$boundN`` title and ``boundn`` are user text rendered as
    innerHTML by deck.gl; this builder is the sink and must escape them."""
    evil_title = "<b>Baltic</b><img src=x onerror=alert(1)>"
    evil_file = "<script>alert(2)</script>.txt"
    (nodes,) = gm.build_setup_layers(
        [], [_bnode(1, 1, "level", title=evil_title, boundn=evil_file)]
    )
    tip = nodes["data"][0]["tooltip_html"]
    assert "<img" not in tip and "<script" not in tip
    assert "<" not in _bare(tip) and ">" not in _bare(tip)
    # escaped, not dropped
    assert "&lt;b&gt;Baltic&lt;/b&gt;" in tip and "&lt;script&gt;" in tip


def test_build_setup_layers_escapes_an_ampersand_exactly_once():
    (nodes,) = gm.build_setup_layers(
        [], [_bnode(1, 1, "level", title="Smith & Co", boundn="a&b.txt")]
    )
    tip = nodes["data"][0]["tooltip_html"]
    assert "Smith &amp; Co" in tip and "a&amp;b.txt" in tip and "&amp;amp;" not in tip


def test_build_setup_layers_empty_inputs_return_empty_list():
    assert gm.build_setup_layers([], []) == []
    assert gm.build_setup_layers([], [], selected_boundary=1) == []


def test_build_setup_layers_degrades_without_shiny_deckgl(monkeypatch):
    monkeypatch.setattr(gm, "path_layer", None)
    monkeypatch.setattr(gm, "scatterplot_layer", None)
    assert gm.build_setup_layers([_iface(1, 1, 2)], [_bnode(1, 1, "level")]) == []
    # either half missing is enough to degrade (the builder needs both)
    monkeypatch.setattr(gm, "scatterplot_layer", object())
    assert gm.build_setup_layers([_iface(1, 1, 2)], [_bnode(1, 1, "level")]) == []


def test_setup_layer_ids_have_legend_labels():
    layers = gm.build_setup_layers(
        [_iface(1, 1, 2), _iface(2, -1, 1, open_boundary=1)], [_bnode(1, 1, "level")]
    )
    labels = gm._build_label_map(layers)
    assert set(labels) == {"setup_interfaces", "setup_open_interfaces", "setup_boundary_nodes"}
    assert all(labels[k] for k in labels)
