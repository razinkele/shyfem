"""The vectorised grid-map builders match the old loop builders (V-06).

``tests/_grid_map_reference.py`` is a frozen copy of the builders as they
were before V-06; the numpy versions must produce the same geometry.
Coordinates are compared to the rounding they are sent with (numpy and
Python can round a tie to different sides).
"""

from pathlib import Path

import numpy as np
import pytest

from shyfem_ui.components import grid_map as gm
from shyfem_ui.services.parser_grd import Element, GrdFile, GrdParser, Node
from tests import _grid_map_reference as ref

_VENLAG = Path(__file__).resolve().parents[2] / "testcases/examples/venice_lagoon/GRID/venlag62.grd"


def _synthetic(n: int = 30, projected: bool = True) -> GrdFile:
    """A grid of triangles and quads, with an element on a missing node,
    nodes without depth, and an element with a duplicated node."""
    g = GrdFile()
    k = 1
    for j in range(n):
        for i in range(n):
            x, y = (
                (500_000 + i * 75.0, 4_100_000 + j * 60.0)
                if projected
                else (
                    12 + i * 1e-3,
                    45 + j * 8e-4,
                )
            )
            depth = None if (i * j) % 11 == 0 else 0.5 + ((i + 2 * j) % 9)
            g.nodes[k] = Node(k, 0, x, y, depth=depth)
            k += 1
    e = 1
    for j in range(n - 1):
        for i in range(n - 1):
            a = j * n + i + 1
            b, c, d = a + 1, a + n, a + n + 1
            if (i + j) % 5 == 0:
                g.elements[e] = Element(e, 0, [a, b, d, c])
                e += 1
            else:
                g.elements[e] = Element(e, 0, [a, b, d])
                g.elements[e + 1] = Element(e + 1, 0, [a, d, c])
                e += 2
    g.elements[e] = Element(e, 0, [1, 2, 999_999])  # a node with no position
    g.elements[e + 1] = Element(e + 1, 0, [1, 1, 2])  # degenerate
    return g


def _grids():
    yield "synthetic-utm", _synthetic(), 32633
    yield "synthetic-geo", _synthetic(projected=False), None
    if _VENLAG.is_file():
        yield "venlag62", GrdParser.parse_file(_VENLAG), 3004


GRIDS = list(_grids())
MODES = [
    ("depth", {}),
    ("depth_3d", {"elevation_scale": 7.5}),
    ("quality", {}),
    ("boundaries", {}),
    ("partitions", {"partition_map": "by-id"}),
]


def _kwargs(grd, extra):
    kw = dict(extra)
    if kw.get("partition_map") == "by-id":
        kw["partition_map"] = {eid: eid % 5 for eid in grd.elements}
    return kw


@pytest.mark.parametrize("name, grd, epsg", GRIDS, ids=[g[0] for g in GRIDS])
def test_lonlat_matches(name, grd, epsg):
    new, old = gm._get_lonlat(grd, epsg=epsg), ref.reference_lonlat(grd, epsg=epsg)
    assert list(new) == list(old)
    np.testing.assert_allclose(list(new.values()), list(old.values()), rtol=0, atol=1e-12)


@pytest.mark.parametrize("name, grd, epsg", GRIDS, ids=[g[0] for g in GRIDS])
@pytest.mark.parametrize("mode, extra", MODES, ids=[m[0] for m in MODES])
def test_mesh_geometry_matches(name, grd, epsg, mode, extra):
    kw = _kwargs(grd, extra)
    new = gm._build_mesh_geometry(grd, mode=mode, epsg=epsg, **kw)
    old = ref.reference_mesh_geometry(grd, mode=mode, epsg=epsg, **kw)

    assert new["indices"] == old["indices"]
    assert (new["n_vertices"], new["n_triangles"]) == (old["n_vertices"], old["n_triangles"])
    assert new["center"] == old["center"]
    np.testing.assert_allclose(new["positions"], old["positions"], rtol=0, atol=0.011)
    np.testing.assert_allclose(new["colors"], old["colors"], rtol=0, atol=0.0011)
    np.testing.assert_allclose(new["normals"], old["normals"], rtol=0, atol=0.00011)
    # JSON-safe: plain Python numbers, not numpy scalars.
    for key in ("positions", "normals", "colors", "indices"):
        assert all(type(v) in (int, float) for v in new[key][:50]), key


def test_build_layers_reprojects_once(monkeypatch):
    grd = _synthetic(10)
    calls = []
    real = gm._get_lonlat
    monkeypatch.setattr(gm, "_get_lonlat", lambda *a, **k: calls.append(1) or real(*a, **k))
    gm._build_map(grd, "depth", "viridis", 1.0, None, 32633, False)
    assert len(calls) == 1


@pytest.mark.parametrize("name, grd, epsg", GRIDS, ids=[g[0] for g in GRIDS])
def test_edge_data_matches(name, grd, epsg):
    """Same edges, same order, same endpoints (the first side that shows
    an edge decides its direction)."""
    assert gm._build_edge_data(grd, epsg=epsg) == ref.reference_edge_data(grd, epsg=epsg)
