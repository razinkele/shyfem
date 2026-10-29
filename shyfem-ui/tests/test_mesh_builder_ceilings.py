"""Server ceilings on Mesh Builder triangulation and contour sampling (M-12).

A tiny Max Triangle Area or contour resample distance let one request
allocate until the shared worker was OOM-killed.
"""

import ast
import json
import pathlib
import time

import pytest

from shyfem_ui.config import Config
from shyfem_ui.services.mesh_builder import (
    check_element_ceiling,
    load_bathymetry_contours,
    triangulate,
)
from shyfem_ui.services.parser_grd import GrdFile, Line, Node

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


def _square(size: float = 1000.0) -> GrdFile:
    grd = GrdFile()
    for nid, (x, y) in enumerate([(0, 0), (size, 0), (size, size), (0, size)], start=1):
        grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))
    grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1])
    return grd


def _long_contour(tmp_path) -> pathlib.Path:
    path = tmp_path / "isobath.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]},
                        "properties": {"depth": 5.0},
                    }
                ],
            }
        )
    )
    return path


def test_config_has_the_two_ceilings():
    cfg = Config()
    assert cfg.mesh_max_elements > 0
    assert cfg.mesh_max_bathy_points > 0


def test_a_tiny_resample_distance_is_refused_before_allocating(tmp_path):
    started = time.monotonic()
    with pytest.raises(ValueError, match="more than 1,000 bathymetry points"):
        # 10 units at 1e-9 would be 10 billion points without the ceiling.
        load_bathymetry_contours(_long_contour(tmp_path), sample_distance=1e-9, max_points=1000)
    assert time.monotonic() - started < 5


def test_resampling_under_the_ceiling_still_works(tmp_path):
    data = load_bathymetry_contours(_long_contour(tmp_path), sample_distance=1.0, max_points=1000)
    assert 11 <= len(data) <= 12


def test_contour_upload_helper_passes_the_ceiling(tmp_path):
    from shyfem_ui.pages.mesh_builder import _load_contour_upload

    path = _long_contour(tmp_path)
    files = [{"name": path.name, "datapath": str(path)}]
    with pytest.raises(ValueError, match="bathymetry points"):
        _load_contour_upload(files, "depth", 1e-9, 1000)


def test_element_ceiling_message():
    grd = _square()  # area 1e6
    assert check_element_ceiling(grd, 1000.0, 2000) is None  # ~1000 elements
    msg = check_element_ceiling(grd, 1.0, 2000)  # ~1,000,000 elements
    assert "1,000,000" in msg and "2,000" in msg and "Max Triangle Area" in msg
    assert check_element_ceiling(grd, None, 2000) is None
    assert check_element_ceiling(grd, 1.0, None) is None


def test_triangulate_refuses_over_the_ceiling():
    with pytest.raises(ValueError, match="limit of 2,000 elements"):
        triangulate(_square(), max_area=1e-3, max_elements=2000)
    assert triangulate(_square(), max_area=1e5, max_elements=2000).num_elements > 0


def _handler(name: str) -> ast.AST:
    tree = ast.parse((SRC / "pages/mesh_builder.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(name)


def _src(node) -> str:
    return ast.unparse(node)


def test_generate_handler_checks_the_config_ceiling_before_the_thread():
    fn = _handler("_on_generate_mesh")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    check = [c for c in calls if _src(c.func) == "check_element_ceiling"]
    thread = [c for c in calls if _src(c.func) == "asyncio.to_thread"]
    assert check and thread
    assert "config.mesh_max_elements" in _src(check[0])
    assert check[0].lineno < thread[0].lineno
    assert "max_elements=config.mesh_max_elements" in _src(thread[0])


def test_contour_handler_passes_the_config_ceiling():
    fn = _handler("_on_contour_upload")
    thread = [
        c for c in ast.walk(fn) if isinstance(c, ast.Call) and _src(c.func) == "asyncio.to_thread"
    ]
    assert "config.mesh_max_bathy_points" in _src(thread[0])


def _two_squares(small: float, big: float) -> GrdFile:
    """Two outer rings: a tiny first one, a big second one."""
    grd = GrdFile()
    nid = 1
    for lid, (x0, size) in enumerate([(0.0, small), (10 * big, big)], start=1):
        ids = []
        for x, y in [(x0, 0), (x0 + size, 0), (x0 + size, size), (x0, size)]:
            grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))
            ids.append(nid)
            nid += 1
        grd.lines[lid] = Line(id=lid, line_type=1, nodes=ids + ids[:1])
    return grd


def test_ceiling_counts_every_outer_polygon_not_just_the_first():
    grd = _two_squares(small=1.0, big=1000.0)  # areas 1 and 1e6
    # Only the first ring would estimate 1 element at max_area=1.
    msg = check_element_ceiling(grd, 1.0, 2000)
    # Bounded by the hull of both rings (>= 1,000,001, the two areas).
    assert msg is not None and "limit of 2,000" in msg
    with pytest.raises(ValueError, match="limit of 2,000 elements"):
        triangulate(grd, max_area=1.0, max_elements=2000)


def test_only_open_lines_fall_back_to_the_convex_hull():
    from shyfem_ui.services.mesh_builder import estimate_element_count

    grd = _square()
    grd.lines[1] = Line(id=1, line_type=0, nodes=[1, 2])  # open, not a ring
    grd.lines[2] = Line(id=2, line_type=0, nodes=[3, 4])
    assert estimate_element_count(grd, 1.0) == 1_000_000


@pytest.mark.parametrize("area, text", [(1e-5, "a0.00001"), (1e16, "a10000000000000000")])
def test_triangle_reads_the_area_that_was_checked(area, text):
    """'a1e-05' / 'a1e+16' reach Triangle as area 1 ('e' is a switch)."""
    from shyfem_ui.services.mesh_builder import _triangle_opts

    opts = _triangle_opts(area, 20.0)
    assert opts == f"pq20{text}"
    assert "e" not in opts


def test_huge_area_typed_in_exponent_form_is_meshed_at_that_area():
    # Area 1e16 boundary, max_area 1e16 -> 1 element; Triangle reading
    # "a1e+16" as a1 would have tried to build ~1e16 triangles.
    out = triangulate(_square(1e8), max_area=1e16, min_angle=0, max_elements=2000)
    assert out.num_elements <= 4


def test_a_bowtie_ring_cannot_hide_its_extent():
    """A self-intersecting outer line: its signed lobes nearly cancel (area
    500), but Triangle meshes the whole ~1000 x 1000 extent."""
    from shapely.geometry import Polygon

    corners = [(0, 0), (1000, 1000), (1000, 0), (0, 1001)]
    grd = GrdFile()
    for nid, (x, y) in enumerate(corners, start=1):
        grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))
    grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1])
    assert Polygon(corners).area == pytest.approx(500.0)
    msg = check_element_ceiling(grd, 1.0, 2000)  # ~1,000,000 elements
    assert msg is not None and "1,000,500" in msg
    with pytest.raises(ValueError, match="limit of 2,000 elements"):
        triangulate(grd, max_area=1.0, max_elements=2000)
