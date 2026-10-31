"""B-01: section interfaces are drawn in the map's frame, not the grid's.

SHYFEM's box output lists each section's nodes with the grid's own x/y, and the
cache keeps them as written. On a projected grid those are metres, which the
Setup map read as lon/lat, so the interfaces landed far off the box outlines
(which ARE reprojected).
"""

from __future__ import annotations

import pytest
from pyproj import Transformer

from shyfem_ui.pages import boxmodel as page
from shyfem_ui.services import boxmodel_polygons as bp
from shyfem_ui.services.parser_grd import GrdParser
from tests.test_boxmodel_polygons import _write_projected_grd

LONLAT = [[21.0, 55.5], [21.01, 55.51]]


def _interfaces(path):
    return [{"section": 1, "from_box": 1, "to_box": 2, "open_boundary": None, "path": path}]


def test_interfaces_on_a_projected_grid_are_reprojected(tmp_path):
    grd_path = tmp_path / "utm.grd"
    _write_projected_grd(grd_path, 32634)
    grd = GrdParser.parse_file(grd_path)
    grd.epsg = 32634  # the same source CRS the box outlines are dissolved with
    to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32634", always_xy=True)
    native = [list(to_utm.transform(x, y)) for x, y in LONLAT]

    got = page._interfaces_on_map(_interfaces(native), grd)

    assert got[0]["section"] == 1 and got[0]["from_box"] == 1
    for (lon, lat), (want_lon, want_lat) in zip(got[0]["path"], LONLAT, strict=True):
        assert lon == pytest.approx(want_lon, abs=1e-6)
        assert lat == pytest.approx(want_lat, abs=1e-6)


def test_interfaces_on_a_geographic_grid_pass_through_unchanged(tmp_path):
    from tests._boxmodel_fixture import make_box_project, make_box_run

    make_box_run(tmp_path / "run", days=1)
    proj = make_box_project(tmp_path / "proj", tmp_path / "run")
    grd = GrdParser.parse_file(proj / "fixture.grd")
    interfaces = _interfaces([list(p) for p in LONLAT])
    assert page._interfaces_on_map(interfaces, grd) == interfaces


def test_interfaces_without_a_grid_are_left_as_they_are():
    interfaces = _interfaces([list(p) for p in LONLAT])
    assert page._interfaces_on_map(interfaces, None) == interfaces


def test_interfaces_on_a_projected_grid_with_no_known_crs_are_dropped(tmp_path):
    """Metres drawn as degrees are worse than no lines: the page drops them."""
    grd_path = tmp_path / "utm.grd"
    _write_projected_grd(grd_path, 32634)
    grd = GrdParser.parse_file(grd_path)
    assert bp.grid_to_wgs84(grd) is None
    assert page._interfaces_on_map(_interfaces([[500000.0, 6150000.0]]), grd) == []


def test_the_setup_map_draws_the_reprojected_interfaces():
    import inspect

    src = inspect.getsource(page)
    assert "_interfaces_on_map(" in src.split("def interfaces_calc", 1)[1].split("@reactive", 1)[0]
