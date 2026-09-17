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
