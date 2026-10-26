"""M-04: bathymetry de-duplication must not thin real data.

_deduplicate_points rounded to 2 decimals. Step-4 isobaths are in degrees
(EPSG:4326), so that is a ~1 km lattice: a 200-point isobath kept 31 points
and a 400-point one 4. It only exists to drop near-identical points that
make RBF / Clough-Tocher singular.
"""

import numpy as np
import pytest

from shyfem_ui.services.mesh_builder import _deduplicate_points, _rbf_interpolate


def _isobath(n, step):
    x = 21.0 + np.arange(n) * step
    y = 55.3 + 0.2 * np.sin(np.arange(n) / 10)
    return np.column_stack([x, y]), np.full(n, -5.0)


@pytest.mark.parametrize("n", [200, 400])
def test_a_dense_isobath_in_degrees_keeps_every_point(n):
    xy, z = _isobath(n, 0.0005)  # ~35 m apart
    out_xy, out_z = _deduplicate_points(xy, z)
    assert len(out_xy) == n


def test_near_identical_points_are_still_dropped():
    xy, z = _isobath(50, 0.001)
    dup = xy[:10] + 1e-10  # sub-millimetre copies
    out_xy, _ = _deduplicate_points(np.vstack([xy, dup]), np.concatenate([z, z[:10]]))
    assert len(out_xy) == 50


def test_metre_coordinates_work_the_same_way():
    xy = np.column_stack([np.arange(300) * 5.0, np.zeros(300)])  # 5 m apart, UTM-like
    out_xy, _ = _deduplicate_points(np.vstack([xy, xy[:5] + 1e-6]), np.zeros(305))
    assert len(out_xy) == 300


def test_rbf_on_duplicated_dense_data_still_solves():
    xy, z = _isobath(200, 0.0005)
    z = z + np.linspace(0, 1, 200)
    xy2 = np.vstack([xy, xy[:20]])
    z2 = np.concatenate([z, z[:20]])
    got = _rbf_interpolate(xy2, z2, xy[:5])
    assert np.allclose(got, z[:5], atol=1e-3)


def test_two_points_straddling_a_rounding_boundary_are_still_merged():
    xy = np.array([[21.0, 55.0], [21.5, 55.5], [21.25 - 1e-12, 55.25], [21.25 + 1e-12, 55.25]])
    out_xy, _ = _deduplicate_points(xy, np.zeros(4))
    assert len(out_xy) == 3
