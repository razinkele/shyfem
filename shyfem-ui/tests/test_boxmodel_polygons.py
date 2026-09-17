"""Tests for the box-polygon service (spec sec4, sec9): loading polygons from a
user-supplied GeoPackage/GeoJSON (with driver/size/feature/vertex caps, id-field
validation and WGS84 reprojection) or dissolving them from the SHYFEM grid's
element->box mapping.
"""

import json

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
