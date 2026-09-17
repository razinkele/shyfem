import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from shyfem_ui.services import boxmodel_skill as sk
from shyfem_ui.services.boxmodel_cache import CachedRun
from tests._boxmodel_fixture import make_box_project, make_box_run


def test_compute_metrics_by_hand():
    o = np.array([1.0, 2.0, 3.0, 4.0])
    m = np.array([1.5, 2.0, 2.5, 5.0])
    mt = sk.compute_metrics(o, m, is_level=False)
    assert mt.n == 4 and mt.bias == pytest.approx(0.25)
    assert mt.rmse == pytest.approx(math.sqrt((0.25 + 0 + 0.25 + 1.0) / 4))
    so, sm = o.std(), m.std()  # ddof = 0
    assert mt.sd_ratio == pytest.approx(sm / so)
    assert mt.r == pytest.approx(np.corrcoef(o, m)[0, 1])
    assert mt.r2 == pytest.approx(1 - ((m - o) ** 2).sum() / ((o - o.mean()) ** 2).sum())


def test_level_is_compared_as_anomaly():
    o = np.array([5.10, 5.20, 5.30])
    m = np.array([0.10, 0.20, 0.30])  # same shape, huge offset
    mt = sk.compute_metrics(o, m, is_level=True)
    assert (
        mt.bias == pytest.approx(0.0)
        and mt.rmse == pytest.approx(0.0)
        and mt.r == pytest.approx(1.0)
    )


def test_sd_ratio_blank_when_obs_constant():
    mt = sk.compute_metrics(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0]), is_level=False)
    assert mt.sd_ratio is None and math.isnan(mt.r)


def test_load_observations_rules(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    proj = make_box_project(tmp_path / "proj", tmp_path / "run")
    obs, report = sk.load_observations(proj / "observations.csv")
    assert report["dropped_level_le0"] == 1
    lvl = obs[(obs["site"] == "A") & (obs["variable"] == "level")]
    assert len(lvl) == 10 and lvl["value"].max() == pytest.approx(5.10)  # cm -> m
    assert str(obs["date"].dtype).startswith("datetime64")


def test_load_observations_rejects_duplicates_and_bad_variable(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("date,site,variable,value\n2009-01-01,A,salinity,1\n2009-01-01,A,salinity,2\n")
    with pytest.raises(sk.ObservationError, match="duplicate"):
        sk.load_observations(p)
    p.write_text("date,site,variable,value\n2009-01-01,A,oxygen,1\n")
    with pytest.raises(sk.ObservationError, match="variable"):
        sk.load_observations(p)
    p.write_text("date,site,variable,value\n01/02/2009,A,salinity,1\n")
    with pytest.raises(sk.ObservationError, match="date"):
        sk.load_observations(p)


def test_load_sites_nullable_box(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    proj = make_box_project(tmp_path / "proj", tmp_path / "run")
    s = sk.load_sites(proj / "sites.csv")
    assert s.loc[s["site"] == "A", "box"].iloc[0] == 1 and pd.isna(
        s.loc[s["site"] == "B", "box"].iloc[0]
    )


def _fake_run(run_id, days=40, offset=0.0):
    dates = pd.date_range("2009-01-01", periods=days, freq="D")
    rows = []
    for d in dates:
        for b in (1, 2):
            rows.append(
                {
                    "date": d,
                    "box": b,
                    "salt": 1.0 + 0.1 * d.day + offset,
                    "temp": 5.0,
                    "act_eta": 0.01 * d.day,
                    "cur_speed": 0,
                    "aver_eta": 0,
                    "bstress": 0,
                    "volume": 1,
                }
            )
    sd = pd.DataFrame(rows)
    return CachedRun(
        run_id,
        {"period": {"start": str(dates[0]), "end": str(dates[-1])}},
        sd,
        pd.DataFrame(),
        pd.DataFrame(),
        None,
    )


def test_skill_table_uses_common_days_and_min_n():
    a, b = _fake_run("a"), _fake_run("b", days=35, offset=0.5)
    dates = pd.date_range("2009-01-01", periods=40, freq="D")
    obs = pd.DataFrame(
        {
            "date": dates,
            "site": "A",
            "variable": "salinity",
            "value": [1.0 + 0.1 * d.day for d in dates],
        }
    )
    sites = pd.DataFrame(
        {"site": ["A"], "lat": [0.0], "lon": [0.0], "box": pd.array([1], dtype="Int64")}
    )
    t = sk.skill_table({"a": a, "b": b}, obs, sites, date(2009, 1, 1), date(2009, 2, 9))
    assert set(t["run"]) == {"a", "b"} and (t["n"] == 35).all()  # intersection of days
    assert t.loc[t["run"] == "a", "bias"].iloc[0] == pytest.approx(0.0)
    assert t.loc[t["run"] == "b", "bias"].iloc[0] == pytest.approx(0.5)
    short = sk.skill_table({"a": a}, obs.head(20), sites, date(2009, 1, 1), date(2009, 2, 9))
    assert short.empty  # n < 30 -> no row


def test_band_amplitude_ratios_on_sine():
    t = np.arange(400)
    obs = pd.Series(
        np.sin(2 * np.pi * t / 7.0), index=pd.date_range("2009-01-01", periods=400, freq="D")
    )
    mod = 2.0 * obs
    r = sk.band_amplitude_ratios(obs, mod)
    assert r is not None and r["4-10 d"] == pytest.approx(2.0, rel=0.05)
    assert sk.band_amplitude_ratios(obs.head(100), mod.head(100)) is None  # < 120 days
