"""Smoothing or simplifying one line keeps the lines it shares nodes with (M-08).

import_boundaries gives two touching polygons one node where they touch.
Rebuilding the edited line deleted those nodes and dropped them from the
sibling, which came back shortened and unclosed.
"""

import json

import pytest

from shyfem_ui.services.mesh_builder import (
    import_boundaries,
    reduce_boundary,
    smooth_boundary,
    validate_boundary,
)


def _edge(x0, y0, x1, y1, n=5):
    return [[x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n] for i in range(n)]


@pytest.fixture
def two_touching_polygons(tmp_path):
    """A 10x10 square and its right-hand neighbour, sharing the x=10 edge.

    The left square's outer edges are wavy so smoothing/simplifying moves
    or removes their nodes.
    """
    left = (
        [[x, 0.3 * (i % 2)] for i, (x, _) in enumerate(_edge(0, 0, 10, 0))]
        + _edge(10, 0, 10, 10)
        + [[x, 10 - 0.3 * (i % 2)] for i, (x, _) in enumerate(_edge(10, 10, 0, 10))]
        + [[0.3 * (i % 2), y] for i, (_, y) in enumerate(_edge(0, 10, 0, 0))]
    )
    right = _edge(10, 0, 20, 0) + _edge(20, 0, 20, 10) + _edge(20, 10, 10, 10)
    right += _edge(10, 10, 10, 0)
    feats = [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [r]}}
        for r in (left + left[:1], right + right[:1])
    ]
    path = tmp_path / "two.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    grd = import_boundaries(path)
    assert len(grd.lines) == 2
    shared = set(grd.lines[1].nodes) & set(grd.lines[2].nodes)
    assert len(shared) == 6  # the x=10 edge: 5 + 1 corner
    return grd


EDITS = {
    "chaikin": lambda g: smooth_boundary(g, 1, method="chaikin", iterations=2),
    "gaussian": lambda g: smooth_boundary(g, 1, method="gaussian", iterations=2),
    "simplify": lambda g: reduce_boundary(g, 1, tolerance=0.5),
}


@pytest.mark.parametrize("edit", EDITS, ids=list(EDITS))
def test_sibling_line_is_untouched(two_touching_polygons, edit):
    grd = two_touching_polygons
    before = list(grd.lines[2].nodes)
    xy_before = {n: (grd.nodes[n].x, grd.nodes[n].y) for n in before}
    shared = set(grd.lines[1].nodes) & set(before)

    out = EDITS[edit](grd)

    assert out.lines[2].nodes == before
    assert {n: (out.nodes[n].x, out.nodes[n].y) for n in before} == xy_before
    # The edited line still runs through the shared nodes, in place.
    assert shared <= set(out.lines[1].nodes)
    line1 = out.lines[1].nodes
    assert line1[0] == line1[-1], "edited ring must stay closed"
    assert all(n in out.nodes for n in line1)
    assert not [i for i in validate_boundary(out) if i.startswith("ERROR")]
    # And the edit did something to the line's own part.
    assert line1 != grd.lines[1].nodes


def test_lone_line_is_still_reworked_as_a_ring(two_touching_polygons):
    """No shared nodes: the old whole-ring behaviour (a closed result)."""
    grd = two_touching_polygons
    del grd.lines[2]
    out = smooth_boundary(grd, 1, method="chaikin", iterations=1)
    nodes = out.lines[1].nodes
    assert nodes[0] == nodes[-1]
    assert len(nodes) > len(grd.lines[1].nodes)
