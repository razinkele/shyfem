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


def test_load_observations_rejects_blank_site_or_variable(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("date,site,variable,value\n2009-01-01,,salinity,1\n")
    with pytest.raises(sk.ObservationError, match="non-empty"):
        sk.load_observations(p)
    p.write_text("date,site,variable,value\n2009-01-01,A,,1\n")
    with pytest.raises(sk.ObservationError, match="non-empty"):
        sk.load_observations(p)


def test_load_observations_and_load_sites_wrap_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.csv"
    with pytest.raises(sk.ObservationError, match="file not found"):
        sk.load_observations(missing)
    with pytest.raises(sk.ObservationError, match="file not found"):
        sk.load_sites(missing)


def test_load_sites_nullable_box(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    proj = make_box_project(tmp_path / "proj", tmp_path / "run")
    s = sk.load_sites(proj / "sites.csv")
    assert s.loc[s["site"] == "A", "box"].iloc[0] == 1 and pd.isna(
        s.loc[s["site"] == "B", "box"].iloc[0]
    )


def test_load_sites_rejects_malformed_box(tmp_path):
    p = tmp_path / "sites.csv"
    p.write_text("site,lat,lon,box\nA,55.0,21.0,abc\n")
    with pytest.raises(sk.ObservationError, match="box must be an integer"):
        sk.load_sites(p)
    p.write_text("site,lat,lon,box\nA,55.0,21.0,1.7\n")
    with pytest.raises(sk.ObservationError, match="box must be an integer"):
        sk.load_sites(p)


def test_load_sites_rejects_a_comma_decimal(tmp_path):
    """B-03: '55,7' loaded as text and blanked the Map tab with no message."""
    p = tmp_path / "sites.csv"
    p.write_text('site,lat,lon,box\nA,"55,7",21.1,1\n')
    with pytest.raises(
        sk.ObservationError, match=r"lat must be a number, got '55,7' \(use a decimal point\)"
    ):
        sk.load_sites(p)
    p.write_text("site,lat,lon,box\nA,55.7,east,1\n")
    with pytest.raises(sk.ObservationError, match="lon must be a number, got 'east'"):
        sk.load_sites(p)


def test_load_sites_coordinates_are_floats_and_may_be_blank(tmp_path):
    p = tmp_path / "sites.csv"
    p.write_text("site,lat,lon,box\nA,55.7,21.1,1\nB,,,2\nC, 55.5 , 21.0 ,\n")
    s = sk.load_sites(p)
    assert s["lat"].dtype == float and s["lon"].dtype == float
    assert s["lat"].tolist()[0] == 55.7 and s["lat"].isna().tolist() == [False, True, False]
    assert s["lon"].tolist()[2] == 21.0


def test_load_sites_rejects_a_repeated_site(tmp_path):
    """B-03: a duplicate site broke Compare with a pandas reshape error."""
    p = tmp_path / "sites.csv"
    p.write_text("site,lat,lon,box\nA,55.7,21.1,1\nB,55.6,21.0,2\nA,55.5,21.2,3\n")
    with pytest.raises(sk.ObservationError, match="site 'A' is listed more than once"):
        sk.load_sites(p)


def test_load_sites_blank_or_whitespace_box_stays_na(tmp_path):
    p = tmp_path / "sites.csv"
    p.write_text("site,lat,lon,box\nA,55.0,21.0,\nB,55.0,21.0, \nC,55.0,21.0,3\n")
    s = sk.load_sites(p)
    assert pd.isna(s.loc[s["site"] == "A", "box"].iloc[0])
    assert pd.isna(s.loc[s["site"] == "B", "box"].iloc[0])
    assert s.loc[s["site"] == "C", "box"].iloc[0] == 3


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
    assert pd.api.types.is_integer_dtype(short["n"])  # empty frame keeps real dtypes, not object


def test_skill_table_drops_nonfinite_model_values():
    a = _fake_run("a", days=40)
    inf_date = pd.Timestamp("2009-01-10")
    mask = (a.state_daily["box"] == 1) & (a.state_daily["date"] == inf_date)
    a.state_daily.loc[mask, "salt"] = np.inf

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
    t = sk.skill_table({"a": a}, obs, sites, date(2009, 1, 1), date(2009, 2, 9))
    row = t.loc[t["run"] == "a"].iloc[0]
    assert row["n"] == 39  # the one inf day is excluded, like a missing one
    assert np.isfinite(row["bias"])
    assert np.isfinite(row["rmse"])
    assert np.isfinite(row["r"])
    assert np.isfinite(row["r2"])


def test_skill_table_level_anomaly_hides_constant_offset(tmp_path):
    """End-to-end through load_observations/load_sites/skill_table: a
    constant offset between model and gauge vanishes from the level metrics
    (anomaly comparison) but not from an ordinary variable's bias.
    """
    dates = pd.date_range("2009-01-01", periods=40, freq="D")
    rows = []
    for d in dates:
        rows.append(
            {
                "date": d,
                "box": 1,
                "salt": (1.0 + 0.1 * d.day) + 0.5,  # model = obs + 0.5
                "temp": 5.0,
                "act_eta": (0.01 * d.day) + 0.5,  # model = obs/100 + 0.5
                "cur_speed": 0,
                "aver_eta": 0,
                "bstress": 0,
                "volume": 1,
            }
        )
    run = CachedRun("a", {}, pd.DataFrame(rows), pd.DataFrame(), pd.DataFrame(), None)

    obs_lines = ["date,site,variable,value"]
    for d in dates:
        level_cm = (0.01 * d.day) * 100.0  # obs in cm; load_observations -> m
        obs_lines.append(f"{d:%Y-%m-%d},A,level,{level_cm}")
        obs_lines.append(f"{d:%Y-%m-%d},A,salinity,{1.0 + 0.1 * d.day}")
    (tmp_path / "observations.csv").write_text("\n".join(obs_lines) + "\n")
    (tmp_path / "sites.csv").write_text("site,lat,lon,box\nA,55.0,21.0,1\n")

    obs, _ = sk.load_observations(tmp_path / "observations.csv")
    sites = sk.load_sites(tmp_path / "sites.csv")

    t = sk.skill_table({"a": run}, obs, sites, date(2009, 1, 1), date(2009, 2, 9))

    level_row = t.loc[t["variable"] == "level"].iloc[0]
    assert level_row["bias"] == pytest.approx(0.0, abs=1e-9)
    assert level_row["r"] == pytest.approx(1.0, abs=1e-9)
    assert level_row["rmse"] == pytest.approx(0.0, abs=1e-9)

    salt_row = t.loc[t["variable"] == "salinity"].iloc[0]
    assert salt_row["bias"] == pytest.approx(0.5, abs=1e-9)


def test_band_amplitude_ratios_on_sine():
    # A degenerate sanity check only: mod = 2*obs gives a ratio of exactly
    # 2.0 whether the formula sums magnitudes or takes sqrt(sum(power)), so
    # this alone cannot pin the formula -- see
    # test_band_amplitude_ratios_matches_reference_formula for that.
    t = np.arange(400)
    obs = pd.Series(
        np.sin(2 * np.pi * t / 7.0), index=pd.date_range("2009-01-01", periods=400, freq="D")
    )
    mod = 2.0 * obs
    r = sk.band_amplitude_ratios(obs, mod)
    assert r is not None and r["4-10 d"] == pytest.approx(2.0, rel=0.05)
    assert sk.band_amplitude_ratios(obs.head(100), mod.head(100)) is None  # < 120 days


def test_band_amplitude_ratios_matches_reference_formula():
    """Non-scalar-multiple case (peaked obs, broadband mod): every band
    ratio is checked against the reference formula
    (``sqrt(sum(|rfft((x - xbar) * hanning(n))|**2))`` per band, band
    membership ``1/hi <= f < 1/lo``) spelled out independently here, not by
    calling into ``band_amplitude_ratios`` or any other module helper.
    """
    n = 365
    rng = np.random.default_rng(20260917)
    t = np.arange(n)
    obs = np.sin(2 * np.pi * t / 3.0) + np.sin(2 * np.pi * t / 7.0) + np.sin(2 * np.pi * t / 60.0)
    noise = rng.normal(scale=0.05, size=n)  # deterministic (seeded) broadband noise
    mod = (
        0.3 * np.sin(2 * np.pi * t / 3.0)
        + np.sin(2 * np.pi * t / 7.0)
        + np.sin(2 * np.pi * t / 60.0)
        + noise
    )
    idx = pd.date_range("2009-01-01", periods=n, freq="D")
    got = sk.band_amplitude_ratios(pd.Series(obs, index=idx), pd.Series(mod, index=idx))
    assert got is not None

    # Independent oracle: the same reference formula, written out again
    # here rather than re-using any part of the implementation.
    w = np.hanning(n)
    fo = np.abs(np.fft.rfft((obs - obs.mean()) * w))
    fm = np.abs(np.fft.rfft((mod - mod.mean()) * w))
    freqs = np.fft.rfftfreq(n, d=1.0)
    checked_any = False
    for lo, hi in sk.BANDS:
        sel = (freqs >= 1.0 / hi) & (freqs < 1.0 / lo)
        obs_power = (fo[sel] ** 2).sum()
        label = f"{lo}-{hi} d"
        if obs_power <= 0:
            assert label not in got
            continue
        expected = math.sqrt((fm[sel] ** 2).sum()) / math.sqrt(obs_power)
        assert got[label] == pytest.approx(expected, abs=1e-9)
        checked_any = True
    assert checked_any


def test_per_year_table_splits_by_calendar_year_and_gates_on_min_n(tmp_path):
    start, end = date(2009, 11, 1), date(2010, 3, 31)
    dates = pd.date_range(start, end, freq="D")

    # salinity obs = model salt(box=1) + a constant +0.3 offset (so the
    # per-day difference, and hence bias, is exactly -0.3 regardless of
    # which days end up matched); temperature obs is a constant offset from
    # the model's constant 5.0.
    obs_lines = ["date,site,variable,value"]
    for d in dates:
        obs_lines.append(f"{d:%Y-%m-%d},A,salinity,{1.0 + 0.1 * d.day + 0.3}")
        obs_lines.append(f"{d:%Y-%m-%d},A,temperature,5.2")
    (tmp_path / "observations.csv").write_text("\n".join(obs_lines) + "\n")
    (tmp_path / "sites.csv").write_text("site,lat,lon,box\nA,55.0,21.0,1\n")

    obs, _ = sk.load_observations(tmp_path / "observations.csv")
    sites = sk.load_sites(tmp_path / "sites.csv")
    assert str(obs["site"].dtype) == "string" and str(sites["box"].dtype) == "Int64"

    # The model run covers all of 2009 but only a truncated slice of 2010,
    # deliberately short of MIN_N_YEAR (60) -- exercises the per-year gate.
    # (A fully-covered 2010 would give 90 matched days, i.e. >= MIN_N_YEAR
    # for *both* years, and would never exercise the "absent" branch.)
    model_last = pd.Timestamp("2010-02-14")
    model_days = (model_last - pd.Timestamp("2009-01-01")).days + 1
    run_a = _fake_run("a", days=model_days, offset=0.0)

    days_2009 = len(pd.date_range("2009-11-01", "2009-12-31", freq="D"))
    days_2010 = len(pd.date_range("2010-01-01", model_last, freq="D"))
    assert days_2009 >= sk.MIN_N_YEAR and days_2010 < sk.MIN_N_YEAR  # sanity on the fixture

    result = sk.per_year_table({"a": run_a}, obs, sites, start, end, min_n=sk.MIN_N_YEAR)

    # (a) contract columns (year first, as skill_table's own columns plus a
    # leading year -- matching the non-empty-case behaviour asserted below,
    # not the "run, site, variable, box, year, ..." order suggested in the
    # ruling, which would be inconsistent with it; see the fix report),
    # year is an int column, one row per (run, site, variable, year).
    contract_columns = [
        "year",
        "run",
        "site",
        "variable",
        "box",
        "n",
        "bias",
        "rmse",
        "r",
        "r2",
        "sd_ratio",
    ]
    assert list(result.columns) == contract_columns
    assert pd.api.types.is_integer_dtype(result["year"])
    key = list(zip(result["run"], result["site"], result["variable"], result["year"], strict=True))
    assert len(key) == len(set(key))
    assert set(key) == {("a", "A", "salinity", 2009), ("a", "A", "temperature", 2009)}

    # (b) 2010 (45 matched days, < 60) is absent; 2009 (61 matched days,
    # >= 60) is present.
    assert set(result["year"]) == {2009}
    assert (result["n"] == days_2009).all()

    # (c) hand-computed bias for the salinity row, on the matched pairs only
    matched = pd.date_range("2009-11-01", "2009-12-31", freq="D")
    obs_salt = np.array([1.0 + 0.1 * d.day + 0.3 for d in matched])
    mod_salt = np.array([1.0 + 0.1 * d.day for d in matched])
    expected_bias = float(mod_salt.mean() - obs_salt.mean())
    got_bias = result.loc[result["variable"] == "salinity", "bias"].iloc[0]
    assert got_bias == pytest.approx(expected_bias, abs=1e-9)
    assert got_bias == pytest.approx(-0.3, abs=1e-9)

    # (d) no matching site -> empty frame, contract columns preserved
    sites_no_match = sites.copy()
    sites_no_match["site"] = pd.array(["Z"], dtype="string")
    empty = sk.per_year_table({"a": run_a}, obs, sites_no_match, start, end, min_n=sk.MIN_N_YEAR)
    assert empty.empty
    assert list(empty.columns) == contract_columns
    assert pd.api.types.is_integer_dtype(empty["n"])
