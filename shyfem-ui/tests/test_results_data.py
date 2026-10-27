"""UGRID results data layer (shyfem_ui.services.results_data)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
import xarray as xr

from shyfem_ui.services import results_data as rd
from tests._ugrid_fixture import write_ugrid


@pytest.fixture
def opened(tmp_path):
    """Open files and close them at teardown."""
    files = []

    def _open(**kw):
        rf = rd.open_results(write_ugrid(tmp_path / f"f{len(files)}.nc", **kw))
        files.append(rf)
        return rf

    yield _open
    for rf in files:
        rf.close()


def test_opens_hydro_and_discovers_variables(opened):
    rf = opened()
    assert set(rf.variables) == {
        "water_level",
        "u_velocity",
        "v_velocity",
        "current_speed",
    }
    assert rf.has_currents
    assert rf.faces.min() == 0 and rf.faces.shape == (3, 3)
    assert len(rf.times) == 4 and all(isinstance(t, datetime) for t in rf.times)
    assert rf.variables["water_level"].label == "Water level"
    assert rf.variables["u_velocity"].label == "U velocity"
    assert rf.variables["current_speed"].label == "Current speed"
    assert rf.variables["current_speed"].units == "m s-1"
    assert not rf.variables["water_level"].has_level
    assert rf.variables["u_velocity"].has_level


def test_opens_ts_without_currents(opened):
    rf = opened(kind="ts")
    assert set(rf.variables) == {"salinity", "temperature"}
    assert not rf.has_currents
    assert rf.variables["salinity"].units == "psu"
    assert rf.variables["temperature"].units == "degC"


def test_refuses_a_regular_grid(tmp_path):
    p = tmp_path / "era5.nc"
    xr.Dataset(
        {"t2m": (("time", "lat", "lon"), np.zeros((2, 3, 4)))},
        coords={"lat": [1.0, 2.0, 3.0], "lon": [1.0, 2.0, 3.0, 4.0], "time": [0, 1]},
    ).to_netcdf(p)
    with pytest.raises(rd.NotUgridError) as e:
        rd.open_results(p)
    assert str(e.value).startswith("Not a SHYFEM mesh file")
    assert "era5.nc" in str(e.value)


def test_fill_values_are_nan(opened):
    rf = opened(fill_at=2)
    f = rd.frame(rf, "water_level", 1)
    assert f.dtype == np.float64 and np.isnan(f[2]) and not np.isnan(f[0])
    lo, hi = rd.value_range(rf, "water_level")
    assert np.isfinite(lo) and np.isfinite(hi)
    assert lo == pytest.approx(0.0) and hi == pytest.approx(0.1 * 3 + 0.04)


def test_constant_variable_range(opened):
    rf = opened(kind="ts", const=35.0)
    assert rd.value_range(rf, "salinity") == (35.0, 35.0)


def test_current_speed_is_the_vector_norm(opened):
    rf = opened(const={"u_velocity": 3.0, "v_velocity": 4.0})
    u, v = rd.velocity(rf, 0)
    assert np.allclose(u, 3.0) and np.allclose(v, 4.0)
    assert np.allclose(rd.frame(rf, rd.CURRENT_SPEED, 0), 5.0)
    assert rd.value_range(rf, rd.CURRENT_SPEED) == pytest.approx((5.0, 5.0))


def test_frame_index_out_of_range_is_clamped(opened):
    rf = opened()
    assert np.array_equal(rd.frame(rf, "water_level", 99), rd.frame(rf, "water_level", 3))
    assert np.array_equal(rd.frame(rf, "water_level", -5), rd.frame(rf, "water_level", 0))
    assert np.array_equal(rd.velocity(rf, 99)[0], rd.velocity(rf, 3)[0])


def test_levels_differ(opened):
    rf = opened(kind="ts", n_levels=2)
    assert rf.n_levels == 2
    assert rf.variables["salinity"].has_level
    assert not np.array_equal(
        rd.frame(rf, "salinity", 0, level=1), rd.frame(rf, "salinity", 0, level=0)
    )


def test_level_is_clamped_everywhere(opened):
    rf = opened(kind="ts")
    assert np.array_equal(
        rd.frame(rf, "salinity", 0, level=5), rd.frame(rf, "salinity", 0, level=0)
    )
    assert rd.value_range(rf, "salinity", level=5) == rd.value_range(rf, "salinity")


def test_value_range_chunks_and_memoises(opened, monkeypatch):
    monkeypatch.setattr(rd, "_CHUNK", 2)
    rf = opened(kind="ts")
    r = rd.value_range(rf, "salinity")
    assert r == pytest.approx((30.0, 33.4))
    assert rf._ranges[("salinity", 0)] is r
    assert rd.value_range(rf, "salinity") is r


def test_close_releases_the_file(tmp_path):
    p = write_ugrid(tmp_path / "a.nc", kind="ts", const=1.0)
    rf = rd.open_results(p)
    assert rd.frame(rf, "salinity", 0)[0] == 1.0
    rf.close()
    for call in (
        lambda: rd.frame(rf, "salinity", 0),
        lambda: rd.value_range(rf, "salinity"),
    ):
        with pytest.raises(ValueError, match="results file is closed"):
            call()
    p.unlink()
    write_ugrid(p, kind="ts", const=2.0)
    rf2 = rd.open_results(p)
    try:
        assert rd.frame(rf2, "salinity", 0)[0] == 2.0
    finally:
        rf2.close()
