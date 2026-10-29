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
