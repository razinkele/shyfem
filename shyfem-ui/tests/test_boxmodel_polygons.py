"""Tests for the box-polygon service (spec sec4, sec9): loading polygons from a
user-supplied GeoPackage/GeoJSON (with driver/size/feature/vertex caps, id-field
validation and WGS84 reprojection) or dissolving them from the SHYFEM grid's
element->box mapping.
"""

import json
import os

import pytest

from shyfem_ui.services import boxmodel_polygons as bp
from tests._boxmodel_fixture import ELEMENT_BOX, make_box_project, make_box_run


@pytest.fixture
def proj(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    return make_box_project(tmp_path / "proj", tmp_path / "run")


def test_geojson_polygons_keyed_by_box(proj):
    polys = bp.load_box_polygons(proj / "box_polygons.geojson", None, "box")
    assert set(polys) == {1, 2, 3}
    ring = polys[2]
    assert ring[0] == ring[-1] and ring[0] == [21.01, 55.5]


def test_id_field_must_be_int_and_unique(proj):
    d = json.loads((proj / "box_polygons.geojson").read_text())
    d["features"][1]["properties"]["box"] = 1
    (proj / "dup.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="unique"):
        bp.load_box_polygons(proj / "dup.geojson", None, "box")
    d["features"][1]["properties"]["box"] = "two"
    (proj / "str.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="integer"):
        bp.load_box_polygons(proj / "str.geojson", None, "box")


def test_expected_boxes_must_match(proj):
    with pytest.raises(bp.PolygonError, match="expected"):
        bp.load_box_polygons(
            proj / "box_polygons.geojson", None, "box", expected_boxes={1, 2, 3, 4}
        )


def test_caps_and_driver(proj, monkeypatch):
    monkeypatch.setattr(bp, "MAX_FEATURES", 2)
    with pytest.raises(bp.PolygonError, match="features"):
        bp.load_box_polygons(proj / "box_polygons.geojson", None, "box")
    (proj / "x.csv").write_text("a,b\n1,2\n")
    with pytest.raises(bp.PolygonError):
        bp.load_box_polygons(proj / "x.csv", None, "box")


def test_dissolve_from_grid(proj):
    polys = bp.dissolve_boxes_from_grid(
        proj / "fixture.grd", [[e, b] for e, b in ELEMENT_BOX.items()]
    )
    assert set(polys) == {1, 2, 3}
    xs = [p[0] for p in polys[1]]
    ys = [p[1] for p in polys[1]]
    assert min(xs) == pytest.approx(21.00) and max(xs) == pytest.approx(21.01)
    assert min(ys) == pytest.approx(55.50) and max(ys) == pytest.approx(55.51)


def test_load_box_polygons_reprojects_to_wgs84(proj, tmp_path):
    """A GeoPackage in a projected CRS (UTM 34N) must round-trip back to the
    original WGS84 fixture coordinates through load_box_polygons's pyproj
    reprojection, and the layer= parameter must select the named layer."""
    import fiona
    from fiona.crs import CRS as FionaCRS
    from pyproj import Transformer

    original = json.loads((proj / "box_polygons.geojson").read_text())
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32634", always_xy=True)

    gpkg = tmp_path / "utm_boxes.gpkg"
    schema = {"geometry": "Polygon", "properties": {"box": "int"}}
    with fiona.open(
        str(gpkg),
        "w",
        driver="GPKG",
        schema=schema,
        crs=FionaCRS.from_epsg(32634),
        layer="boxes",
    ) as dst:
        for feature in original["features"]:
            ring = feature["geometry"]["coordinates"][0]
            utm_ring = [list(to_utm.transform(x, y)) for x, y in ring]
            dst.write(
                {
                    "geometry": {"type": "Polygon", "coordinates": [utm_ring]},
                    "properties": {"box": feature["properties"]["box"]},
                }
            )

    polys = bp.load_box_polygons(gpkg, "boxes", "box")
    assert set(polys) == {1, 2, 3}
    for feature in original["features"]:
        box = feature["properties"]["box"]
        orig_ring = feature["geometry"]["coordinates"][0]
        got_ring = polys[box]
        assert got_ring[0] == got_ring[-1]  # closed
        assert len(got_ring) == len(orig_ring)
        for (ox, oy), (gx, gy) in zip(orig_ring, got_ring, strict=True):
            assert gx == pytest.approx(ox, abs=1e-6)
            assert gy == pytest.approx(oy, abs=1e-6)


def test_load_box_polygons_rejects_symlink(proj, tmp_path):
    real = proj / "box_polygons.geojson"
    link = tmp_path / "link.geojson"
    os.symlink(real, link)
    with pytest.raises(bp.PolygonError, match="symlink"):
        bp.load_box_polygons(link, None, "box")
    # the real (non-symlink) file still loads fine
    polys = bp.load_box_polygons(real, None, "box")
    assert set(polys) == {1, 2, 3}


def test_mixed_type_id_field_raises(proj):
    """OGR's GeoJSON driver resolves an id field holding both an int and a
    string across features to an ambiguous "json" schema type; this must be
    rejected as a PolygonError naming the id field, not leak the raw fiona/
    json exception (or, worse, silently coerce a numeric string to int)."""
    d = json.loads((proj / "box_polygons.geojson").read_text())
    d["features"][0]["properties"]["box"] = 1
    d["features"][1]["properties"]["box"] = "2"
    (proj / "mixed_id_type.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="field 'box'"):
        bp.load_box_polygons(proj / "mixed_id_type.geojson", None, "box")


def test_load_box_polygons_rejects_out_of_bounds_coordinates(proj):
    """pyproj returns inf/nan for out-of-domain input instead of raising, so a
    post-transform sanity check must catch a vertex outside valid WGS84
    bounds even when the source is already tagged WGS84 (identity transform).

    Mutates a middle vertex (index 1), not the first/last, so the ring stays
    closed and this doesn't also trip GDAL's "non closed ring" warning."""
    d = json.loads((proj / "box_polygons.geojson").read_text())
    d["features"][0]["geometry"]["coordinates"][0][1] = [1e6, 1e6]
    (proj / "bad_coord.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="box 1"):
        bp.load_box_polygons(proj / "bad_coord.geojson", None, "box")


def test_vertex_cap_counts_all_rings_and_parts(proj, monkeypatch):
    """MAX_VERTICES must bound the cost of parsing a feature's whole raw
    geometry (outer ring + holes), not just the outer ring _outer_ring keeps."""
    d = json.loads((proj / "box_polygons.geojson").read_text())
    outer = d["features"][0]["geometry"]["coordinates"][0]
    hole = [
        [21.002, 55.502],
        [21.004, 55.502],
        [21.004, 55.504],
        [21.002, 55.504],
        [21.002, 55.502],
    ]
    d["features"][0]["geometry"]["coordinates"].append(hole)
    (proj / "with_hole.geojson").write_text(json.dumps(d))

    # The outer ring alone fits exactly at this cap; outer + hole must overflow.
    monkeypatch.setattr(bp, "MAX_VERTICES", len(outer))
    with pytest.raises(bp.PolygonError, match="vertices"):
        bp.load_box_polygons(proj / "with_hole.geojson", None, "box")


def test_dissolve_missing_grid_raises(tmp_path):
    with pytest.raises(bp.PolygonError, match="fixture.grd"):
        bp.dissolve_boxes_from_grid(
            tmp_path / "fixture.grd", [[e, b] for e, b in ELEMENT_BOX.items()]
        )


def test_dissolve_dangling_node_raises(proj):
    grd_text = (proj / "fixture.grd").read_text()
    # Element 1 originally references nodes 1, 2, 6; point one of them at a
    # node id that does not exist in the grid.
    modified = grd_text.replace("2 1 0 3 1 2 6", "2 1 0 3 1 2 99")
    assert modified != grd_text
    (proj / "dangling.grd").write_text(modified)
    with pytest.raises(bp.PolygonError, match="99"):
        bp.dissolve_boxes_from_grid(proj / "dangling.grd", [[e, b] for e, b in ELEMENT_BOX.items()])


def test_dissolve_missing_element_raises_with_examples(proj):
    element_box = [[e, b] for e, b in ELEMENT_BOX.items()] + [[99, 1], [98, 1]]
    with pytest.raises(bp.PolygonError, match=r"2 element\(s\)"):
        bp.dissolve_boxes_from_grid(proj / "fixture.grd", element_box)


def _write_projected_grd(path, epsg: int) -> None:
    from pyproj import Transformer

    from tests._boxmodel_fixture import ELEMENTS, NODES

    to_projected = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    lines = ["0 projected fixture grid"]
    for node_id, (lon, lat) in NODES.items():
        x, y = to_projected.transform(lon, lat)
        lines.append(f"1 {node_id} 0 {x:.6f} {y:.6f} 6.00")
    for elem_id, (a, b, c) in ELEMENTS.items():
        lines.append(f"2 {elem_id} 0 3 {a} {b} {c}")
    path.write_text("\n".join(lines) + "\n")


def test_dissolve_from_grid_reprojects_with_explicit_epsg(tmp_path):
    grd_path = tmp_path / "utm.grd"
    _write_projected_grd(grd_path, 32634)
    element_box = [[e, b] for e, b in ELEMENT_BOX.items()]

    polys = bp.dissolve_boxes_from_grid(grd_path, element_box, epsg=32634)
    assert set(polys) == {1, 2, 3}
    xs = [p[0] for p in polys[1]]
    ys = [p[1] for p in polys[1]]
    assert min(xs) == pytest.approx(21.00, abs=1e-6) and max(xs) == pytest.approx(21.01, abs=1e-6)
    assert min(ys) == pytest.approx(55.50, abs=1e-6) and max(ys) == pytest.approx(55.51, abs=1e-6)


def test_dissolve_from_grid_without_epsg_and_undetectable_crs_raises(tmp_path):
    grd_path = tmp_path / "utm_no_epsg.grd"
    _write_projected_grd(grd_path, 32634)
    element_box = [[e, b] for e, b in ELEMENT_BOX.items()]

    with pytest.raises(bp.PolygonError, match="EPSG"):
        bp.dissolve_boxes_from_grid(grd_path, element_box)


def test_feature_cap_is_inclusive_and_reads_module_global(proj, monkeypatch):
    """The cap must be read from the module global at call time (not copied
    into a default argument), and must be inclusive: a file with exactly
    MAX_FEATURES features loads fine; one more raises, naming the cap."""
    monkeypatch.setattr(bp, "MAX_FEATURES", 3)
    polys = bp.load_box_polygons(proj / "box_polygons.geojson", None, "box")
    assert set(polys) == {1, 2, 3}

    d = json.loads((proj / "box_polygons.geojson").read_text())
    extra = json.loads(json.dumps(d["features"][0]))
    extra["properties"]["box"] = 4
    d["features"].append(extra)
    (proj / "four.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="more than 3 features"):
        bp.load_box_polygons(proj / "four.geojson", None, "box")


def test_dissolve_unknown_epsg_raises_polygon_error(proj):
    """An epsg= that pyproj cannot resolve must become a PolygonError, not a
    raw pyproj.exceptions.CRSError -- same contract as load_box_polygons."""
    element_box = [[e, b] for e, b in ELEMENT_BOX.items()]
    with pytest.raises(bp.PolygonError, match="EPSG:99999"):
        bp.dissolve_boxes_from_grid(proj / "fixture.grd", element_box, epsg=99999)


def test_dissolve_accepts_an_already_parsed_grid(proj, monkeypatch):
    """The page already holds the parsed ``GrdFile`` (it uses it for the EPSG
    decision), so handing the object over must dissolve without re-parsing the
    whole .grd -- ``parse_file`` is monkeypatched to fail, and the dissolve
    must still work."""
    from shyfem_ui.services.parser_grd import GrdParser

    grd = GrdParser.parse_file(proj / "fixture.grd")
    from_path = bp.dissolve_boxes_from_grid(
        proj / "fixture.grd", [[e, b] for e, b in ELEMENT_BOX.items()]
    )

    def _explode(_path):
        raise AssertionError("the grid must not be re-parsed")

    monkeypatch.setattr(bp.GrdParser, "parse_file", classmethod(lambda cls, p: _explode(p)))
    polys = bp.dissolve_boxes_from_grid(grd, [[e, b] for e, b in ELEMENT_BOX.items()])
    assert polys == from_path


def test_dissolve_from_a_parsed_grid_still_names_the_file(proj):
    """A parsed grid carries ``file_path``, so every PolygonError keeps naming
    the .grd the way the path form does."""
    from shyfem_ui.services.parser_grd import GrdParser

    grd_text = (proj / "fixture.grd").read_text()
    (proj / "dangling.grd").write_text(grd_text.replace("2 1 0 3 1 2 6", "2 1 0 3 1 2 99"))
    grd = GrdParser.parse_file(proj / "dangling.grd")
    with pytest.raises(bp.PolygonError, match=r"dangling\.grd: element 1 .* node 99"):
        bp.dissolve_boxes_from_grid(grd, [[e, b] for e, b in ELEMENT_BOX.items()])


def test_dissolve_from_a_parsed_grid_without_a_path_still_reports(proj):
    """A ``GrdFile`` built in memory has ``file_path is None``; the messages
    fall back to a neutral name instead of raising an AttributeError."""
    from shyfem_ui.services.parser_grd import GrdParser

    grd = GrdParser.parse((proj / "fixture.grd").read_text())
    assert grd.file_path is None
    with pytest.raises(bp.PolygonError, match=r"grid: 1 element\(s\)"):
        bp.dissolve_boxes_from_grid(grd, [[99, 1]])
