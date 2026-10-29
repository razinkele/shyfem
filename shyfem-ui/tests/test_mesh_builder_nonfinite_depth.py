"""A NaN in the bathymetry never reaches an exported GRD (M-05).

One ``nan`` row in an XYZ survey went through IDW into every node near it and
was written to the GRD as the literal text ``nan``.
"""

import numpy as np
import pytest

from shyfem_ui.services.mesh_builder import (
    drop_nonfinite_points,
    interpolate_bathymetry_scipy,
    load_bathymetry_file,
)
from shyfem_ui.services.parser_grd import Element, GrdFile, GrdParser, Node


def _square_mesh() -> GrdFile:
    grd = GrdFile()
    for nid, (x, y) in enumerate([(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)], start=1):
        grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))
    for eid, tri in enumerate([[1, 2, 5], [2, 3, 5], [3, 4, 5], [4, 1, 5]], start=1):
        grd.elements[eid] = Element(id=eid, elem_type=0, nodes=tri)
    return grd


def _xyz_with_a_nan(tmp_path):
    path = tmp_path / "survey.xyz"
    rows = ["0 0 1", "10 0 2", "10 10 3", "0 10 4", "5 5 nan", "2 8 inf"]
    path.write_text("\n".join(rows) + "\n")
    return path


@pytest.mark.parametrize("method", ["idw", "linear", "nearest", "cloughtocher"])
def test_a_nan_survey_point_does_not_reach_the_grd(tmp_path, method):
    points = load_bathymetry_file(_xyz_with_a_nan(tmp_path))
    out = GrdParser.generate(interpolate_bathymetry_scipy(_square_mesh(), points, method))
    assert "nan" not in out.lower() and "inf" not in out.lower()
    depths = [float(line.split()[5]) for line in out.splitlines() if line.startswith("1 ")]
    assert len(depths) == 5 and all(np.isfinite(depths))


def test_drop_nonfinite_points_reports_the_count():
    pts = np.array([[0, 0, 1], [1, 1, np.nan], [np.inf, 2, 3], [4, 4, 4]], dtype=float)
    kept, dropped = drop_nonfinite_points(pts)
    assert dropped == 2
    assert kept.tolist() == [[0, 0, 1], [4, 4, 4]]


def test_drop_nonfinite_points_refuses_an_all_nan_survey():
    with pytest.raises(ValueError, match="finite"):
        drop_nonfinite_points(np.array([[0, 0, np.nan]]))


def test_upload_helper_drops_and_counts(tmp_path):
    from shyfem_ui.pages.mesh_builder import _dropped_points_note, _load_bathy_upload

    data, dropped = _load_bathy_upload(_xyz_with_a_nan(tmp_path))
    assert dropped == 2 and len(data) == 4 and np.isfinite(data).all()
    assert "2 point(s)" in _dropped_points_note(dropped)
    assert _dropped_points_note(0) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_writer_leaves_a_non_finite_depth_out(bad):
    """Written like SHYFEM's own -999 flag: no depth field, which the core
    reader takes as "depth not set"."""
    grd = GrdFile()
    grd.nodes[1] = Node(id=1, node_type=0, x=1.0, y=2.0, depth=bad)
    grd.nodes[2] = Node(id=2, node_type=0, x=3.0, y=4.0, depth=5.0)
    grd.elements[1] = Element(id=1, elem_type=0, nodes=[1, 2, 1], depth=bad)
    out = GrdParser.generate(grd)
    assert "nan" not in out.lower() and "inf" not in out.lower()
    lines = out.splitlines()
    assert lines[0].split() == ["1", "1", "0", "1.000000", "2.000000"]
    assert lines[1].split()[-1] == "5.000000"
    assert GrdParser.parse(out).nodes[1].depth is None
