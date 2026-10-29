"""Mesh Builder, Partitioning and Grid Prep loaders run in a thread (M-11).

Boundary import, bathymetry point and contour loads, the Partitioning grid
parse and the Grid Prep Inspect statistics ran on the event loop, freezing
every session in the worker for as long as they took.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return getattr(node, "id", "")


def _function(path: str, name: str) -> ast.AST:
    for node in ast.walk(ast.parse((SRC / path).read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not in {path}")


@pytest.mark.parametrize(
    "path, handler, threaded, never_direct",
    [
        (
            "pages/mesh_builder.py",
            "_on_boundary_upload",
            "_import_boundary_upload",
            ("import_boundaries", "stage_boundary_upload", "validate_boundary"),
        ),
        (
            "pages/mesh_builder.py",
            "_on_bathy_upload",
            "_load_bathy_upload",
            ("load_bathymetry_file", "drop_nonfinite_points"),
        ),
        (
            "pages/mesh_builder.py",
            "_on_contour_upload",
            "_load_contour_upload",
            ("load_bathymetry_contours", "stage_boundary_upload"),
        ),
        ("pages/partitioning.py", "_load_grid", "GrdParser.parse_file", ()),
        (
            "pages/grid_prep.py",
            "grid_inspect",
            "_inspect_stats",
            ("compute_element_quality", "compute_element_areas", "compute_min_angles"),
        ),
    ],
)
def test_loader_runs_in_a_thread(path, handler, threaded, never_direct):
    fn = _function(path, handler)
    assert isinstance(fn, ast.AsyncFunctionDef), f"{handler} must be async"
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    in_thread = [
        c
        for c in calls
        if _dotted(c.func) == "asyncio.to_thread" and c.args and _dotted(c.args[0]) == threaded
    ]
    assert len(in_thread) == 1
    direct = {_dotted(c.func) for c in calls} & {threaded, *never_direct}
    assert not direct, direct
