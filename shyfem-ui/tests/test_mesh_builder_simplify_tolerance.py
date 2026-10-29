"""The Step 2 Simplify Tolerance is metres, not degrees (M-09).

Imported boundaries are lon/lat degrees; the slider's smallest non-zero
value (1.0) was 1 degree (~111 km), which collapsed any lagoon boundary to
a handful of nodes.
"""

import ast
import math
import pathlib

import pytest

from shyfem_ui.services.mesh_builder import reduce_boundary, tolerance_in_grid_units
from shyfem_ui.services.parser_grd import GrdFile, Line, Node

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


def _ring(cx, cy, radius, n=400, wiggle=0.0) -> GrdFile:
    """A closed ring of ``n`` nodes; ``wiggle`` adds a small zig-zag."""
    grd = GrdFile(epsg=4326)
    for i in range(n):
        a = 2 * math.pi * i / n
        r = radius + (wiggle if i % 2 else 0.0)
        grd.nodes[i + 1] = Node(
            id=i + 1, node_type=0, x=cx + r * math.cos(a), y=cy + r * math.sin(a)
        )
    grd.lines[1] = Line(id=1, line_type=1, nodes=list(range(1, n + 1)) + [1])
    return grd


def _kept(grd: GrdFile, metres: float) -> int:
    tol = tolerance_in_grid_units(grd, metres)
    return len(reduce_boundary(grd, 1, tolerance=tol).lines[1].nodes)


def test_one_metre_on_a_degree_boundary_simplifies_a_little():
    # A ~5.5 km-radius lagoon at 55N with a 1 m zig-zag on its shore.
    grd = _ring(21.1, 55.3, 0.05, wiggle=1e-5)
    original = len(grd.lines[1].nodes)
    kept = _kept(grd, 1.0)
    assert 4 < kept < original  # the 1 m wiggle goes, the shape stays
    assert _kept(grd, 100.0) > 10  # a 100 m tolerance still keeps a lagoon
    assert _kept(grd, 0.0) == original


def test_degree_conversion():
    grd = _ring(21.1, 55.3, 0.05, n=10)
    assert tolerance_in_grid_units(grd, 111_320.0) == pytest.approx(1.0)
    assert tolerance_in_grid_units(grd, 0.0) == 0.0


def test_projected_grid_tolerance_is_already_metres():
    grd = _ring(715000.0, 4195000.0, 5000.0, n=10)  # untagged UTM (Mar Menor style)
    assert tolerance_in_grid_units(grd, 25.0) == 25.0


def test_page_converts_the_slider_and_labels_it_in_metres():
    src = (SRC / "pages/mesh_builder.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_on_reduce"
    )
    calls = {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "tolerance_in_grid_units" in calls
    assert '"Simplify Tolerance (m)"' in src
