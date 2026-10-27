"""Pure layer-building helpers of the results map: no Shiny, no browser."""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from shyfem_ui.components import results_map_layers as rml
from shyfem_ui.components.grid_map import PALETTES


def _rf(x, y):
    return SimpleNamespace(node_x=np.asarray(x, float), node_y=np.asarray(y, float))


def _metres(lon0, lat0, lon, lat):
    return (
        (lon - lon0) * 111320 * math.cos(math.radians(lat0)),
        (lat - lat0) * 110540,
    )


def test_lonlat_mesh_is_used_as_is():
    out = rml.mesh_lonlat(_rf([20.0, 21.0], [55.0, 55.5]), None)
    assert out.shape == (2, 2)
    assert out[1].tolist() == [21.0, 55.5]


def test_utm_without_epsg_needs_projection():
    rf = _rf([688589.0, 710073.0], [4100000.0, 4120000.0])
    with pytest.raises(rml.NeedsProjection, match="Choose the mesh projection"):
        rml.mesh_lonlat(rf, None)


def test_utm_with_epsg_is_transformed():
    rf = _rf([688589.0, 710073.0], [4150000.0, 4160000.0])
    out = rml.mesh_lonlat(rf, 32630)
    assert np.all((out[:, 0] > -1) & (out[:, 0] < 0))
    assert np.all((out[:, 1] > 37) & (out[:, 1] < 38.5))


def test_utm_mesh_with_wgs84_is_not_on_earth():
    rf = _rf([688589.0, 710073.0], [4150000.0, 4160000.0])
    with pytest.raises(rml.NeedsProjection, match="does not place the mesh on Earth"):
        rml.mesh_lonlat(rf, 4326)


def test_a_projection_that_cannot_hold_the_mesh_is_rejected():
    rf = _rf([5e9, 6e9], [4150000.0, 4160000.0])  # pyproj returns inf for UTM 30N
    with pytest.raises(rml.NeedsProjection, match="does not place the mesh on Earth"):
        rml.mesh_lonlat(rf, 32630)


def test_geometry_is_indexed_one_vertex_per_node():
    lonlat = np.array([[20.0, 55.0], [20.1, 55.0], [20.0, 55.1], [20.1, 55.1]])
    faces = np.array([[0, 1, 2], [1, 3, 2]])
    g = rml.mesh_geometry(lonlat, faces)
    assert g["positions"].shape == (4, 3) and g["positions"].dtype == np.float32
    assert g["normals"].shape == (4, 3) and np.all(g["normals"] == [0, 0, 1])
    assert g["indices"].dtype == np.uint32
    assert g["indices"].tolist() == [0, 1, 2, 1, 3, 2]
    assert g["center"] == pytest.approx([20.05, 55.05])
    assert g["positions"][0, 0] < 0 < g["positions"][1, 0]


def test_nan_nodes_are_grey():
    c = rml.node_colors(np.array([0.0, np.nan, 1.0]), 0.0, 1.0, "viridis")
    assert c.dtype == np.float32 and c.shape == (3, 3)
    assert c[1].tolist() == pytest.approx([0.78, 0.78, 0.78])
    assert c.min() >= 0 and c.max() <= 1
    first = np.array(PALETTES["viridis"][0][:3]) / 255
    assert c[0] == pytest.approx(first, abs=1e-6)


def test_flat_range_does_not_divide_by_zero():
    with np.errstate(all="raise"):
        c = rml.node_colors(np.array([2.0, 2.0]), 2.0, 2.0, "viridis")
    assert np.isfinite(c).all()
    assert np.allclose(c[0], c[1])
    pal = np.array(PALETTES["viridis"], float)[:, :3] / 255
    assert not np.allclose(c[0], pal[0]) and not np.allclose(c[0], pal[-1])


def test_color_patch_is_only_colours():
    p = rml.color_patch(np.ones((3, 3)))
    assert set(p) == {"_meshColors"}
    assert p["_meshColors"]["@@binary"] is True
    assert p["_meshColors"]["dtype"] == "float32"


def test_mesh_layer_has_the_full_geometry():
    lonlat = np.array([[20.0, 55.0], [20.1, 55.0], [20.0, 55.1]])
    g = rml.mesh_geometry(lonlat, np.array([[0, 1, 2]]))
    lyr = rml.mesh_layer(g, np.ones((3, 3), np.float32))
    assert lyr["id"] == rml.RESULTS_LAYER_ID
    for key in ("_meshPositions", "_meshIndices", "_meshColors"):
        assert key in lyr
    assert lyr["pickable"] is False


def _scatter(n=1000, seed=0):
    rng = np.random.default_rng(seed)
    return np.column_stack([rng.uniform(20, 21, n), rng.uniform(55, 55.5, n)])


def test_arrows_are_thinned():
    ll = _scatter()
    paths = rml.arrow_paths(ll, np.ones(1000), np.ones(1000), speed_max=2.0)
    assert 0 < len(paths) <= 400


def _length_m(path, lat0):
    (lo0, _), (lo1, la1) = path[0], path[1]
    dx, dy = _metres(lo0, lat0, lo1, la1)
    return math.hypot(dx, dy)


def test_arrow_length_scales_with_speed_under_a_fixed_max():
    ll = np.array([[20.0, 55.0], [21.0, 55.5]])
    one = rml.arrow_paths(ll[:1], np.array([0.5]), np.array([0.0]), speed_max=2.0, length_m=1000)
    two = rml.arrow_paths(ll[:1], np.array([1.0]), np.array([0.0]), speed_max=2.0, length_m=1000)
    l1 = _length_m(one[0]["path"], 55.0)
    l2 = _length_m(two[0]["path"], 55.0)
    assert l1 == pytest.approx(250.0, rel=1e-3)
    assert l2 == pytest.approx(2 * l1, rel=1e-6)


def test_arrow_direction_is_true_at_55N():
    ll = np.array([[20.0, 55.0]])
    p = rml.arrow_paths(ll, np.array([1.0]), np.array([1.0]), speed_max=1.5, length_m=5000)
    tail, tip = p[0]["path"][0], p[0]["path"][1]
    dx, dy = _metres(tail[0], tail[1], tip[0], tip[1])
    bearing = math.degrees(math.atan2(dx, dy))
    assert bearing == pytest.approx(45.0, abs=1.0)


def test_arrows_have_a_head():
    ll = _scatter(50)
    paths = rml.arrow_paths(ll, np.full(50, 0.3), np.full(50, 0.1), speed_max=1.0)
    assert paths and all(len(p["path"]) == 5 for p in paths)
    assert all(p["path"][1] == p["path"][3] for p in paths)


def test_arrows_skip_nan_and_zero_speed():
    ll = _scatter(3)
    u = np.array([np.nan, 0.0, 1.0])
    v = np.array([0.0, 0.0, 0.0])
    assert len(rml.arrow_paths(ll, u, v, speed_max=1.0)) == 1


def test_arrows_layer_is_a_path_layer():
    lyr = rml.arrows_layer([{"path": [[0, 0], [1, 1]]}])
    assert lyr["id"] == rml.ARROWS_LAYER_ID
    assert lyr["getPath"] == "@@d.path"


def test_legend_escapes_units():
    html = rml.legend_html("viridis", 0.0, 1.5, "<b>m/s</b>", "Speed & more")
    assert "<b>m/s</b>" not in html
    assert "&lt;b&gt;m/s&lt;/b&gt;" in html
    assert "Speed &amp; more" in html
    assert "gradient" in html
