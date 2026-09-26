"""Pure compare service (spec §8 "Compare", §7 metrics).

The run frames here are built directly, not through ``tests/_boxmodel_fixture``:
run A has ``temp = 10 + box + 0.05 * day_index``, run B is A + 1.5 in ``temp``
and identical in ``cur_speed``, so every expectation is computable by hand.
"""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from shyfem_ui.services import boxmodel_compare as cmp
from shyfem_ui.services import boxmodel_skill as sk
from shyfem_ui.services.boxmodel_cache import CachedRun

BOXES = (1, 2, 3)


def _temp(box: int, day_index: int, offset: float = 0.0) -> float:
    return 10.0 + box + 0.05 * day_index + offset


def _run(run_id: str, days: int = 40, offset: float = 0.0, start="2009-01-01") -> CachedRun:
    dates = pd.date_range(start, periods=days, freq="D")
    rows = [
        {
            "date": d,
            "box": b,
            "temp": _temp(b, i, offset),
            "salt": 2.0 + 0.1 * b,
            "cur_speed": 0.3 * b,
        }
        for i, d in enumerate(dates)
        for b in BOXES
    ]
    sd = pd.DataFrame(rows)
    sd["date"] = sd["date"].astype("datetime64[ns]")
    return CachedRun(run_id, {}, sd, pd.DataFrame(), pd.DataFrame(), None)


# --- common_days -------------------------------------------------------------


def test_common_days_is_the_shorter_run_clamped_to_the_window():
    a, b = _run("a", days=10), _run("b", days=40, offset=1.5)
    days = cmp.common_days({"a": a, "b": b}, date(2009, 1, 1), date(2009, 12, 31))
    assert isinstance(days, pd.DatetimeIndex)
    assert list(days) == list(pd.date_range("2009-01-01", periods=10, freq="D"))

    clamped = cmp.common_days({"a": a, "b": b}, date(2009, 1, 3), date(2009, 1, 6))
    assert list(clamped) == list(pd.date_range("2009-01-03", periods=4, freq="D"))  # inclusive

    outside = cmp.common_days({"a": a, "b": b}, date(2010, 1, 1), date(2010, 2, 1))
    assert len(outside) == 0


def test_common_days_is_unique_sorted_and_datetime_even_when_empty():
    a = _run("a", days=5)
    shuffled = a.state_daily.sample(frac=1.0, random_state=7).reset_index(drop=True)
    a = CachedRun("a", {}, shuffled, pd.DataFrame(), pd.DataFrame(), None)
    days = cmp.common_days({"a": a}, date(2009, 1, 1), date(2009, 1, 5))
    assert days.is_monotonic_increasing and days.is_unique and len(days) == 5

    for runs in ({}, {"a": a, "b": None}):
        empty = cmp.common_days(runs, date(2009, 1, 1), date(2009, 1, 5))
        assert isinstance(empty, pd.DatetimeIndex) and len(empty) == 0
        assert empty.dtype == "datetime64[ns]"


def test_common_days_matches_skill_table_day_set():
    """The Global Constraint: one day set shared by map, overlay and tables."""
    a, b = _run("a", days=35), _run("b", days=40, offset=1.5)
    dates = pd.date_range("2009-01-01", periods=40, freq="D")
    obs = pd.DataFrame(
        {"date": dates, "site": "S", "variable": "temperature", "value": 12.0 + 0.1 * np.arange(40)}
    )
    sites = pd.DataFrame(
        {"site": ["S"], "lat": [0.0], "lon": [0.0], "box": pd.array([1], dtype="Int64")}
    )
    start, end = date(2009, 1, 1), date(2009, 2, 9)
    days = cmp.common_days({"a": a, "b": b}, start, end)
    table = sk.skill_table({"a": a, "b": b}, obs, sites, start, end)
    assert len(days) == 35 and (table["n"] == len(days)).all()


# --- period_mean_diff -------------------------------------------------------


def test_period_mean_diff_is_b_minus_a_per_box():
    a, b = _run("a", days=10), _run("b", days=40, offset=1.5)
    days = cmp.common_days({"a": a, "b": b}, date(2009, 1, 1), date(2009, 12, 31))
    diff = cmp.period_mean_diff(a, b, "temp", days)
    assert set(diff) == set(BOXES)
    assert all(type(k) is int for k in diff)
    assert all(v == pytest.approx(1.5) for v in diff.values())
    assert cmp.period_mean_diff(b, a, "temp", days)[2] == pytest.approx(-1.5)
    assert all(
        v == pytest.approx(0.0) for v in cmp.period_mean_diff(a, b, "cur_speed", days).values()
    )


def test_period_mean_diff_uses_exactly_the_given_days():
    a, b = _run("a", days=10), _run("b", days=10, offset=1.5)
    spike_day = pd.Timestamp("2009-01-05")
    b.state_daily.loc[b.state_daily["date"] == spike_day, "temp"] = 1e6  # excluded below
    days = pd.DatetimeIndex(
        [d for d in pd.date_range("2009-01-01", periods=10, freq="D") if d != spike_day]
    )
    diff = cmp.period_mean_diff(a, b, "temp", days)
    assert all(v == pytest.approx(1.5) for v in diff.values())
    assert cmp.period_mean_diff(a, b, "temp", pd.DatetimeIndex([])) == {}


def test_period_mean_diff_omits_boxes_without_finite_values_in_either_run():
    a, b = _run("a", days=10), _run("b", days=10, offset=1.5)
    # box 3 exists only in A; box 2 of B is all inf (a diverged run)
    a.state_daily.loc[a.state_daily["box"] == 3, "temp"] = np.nan
    b.state_daily = b.state_daily[b.state_daily["box"] != 3].reset_index(drop=True)
    b.state_daily.loc[b.state_daily["box"] == 2, "temp"] = np.inf
    days = cmp.common_days({"a": a, "b": b}, date(2009, 1, 1), date(2009, 1, 10))
    diff = cmp.period_mean_diff(a, b, "temp", days)
    assert set(diff) == {1} and diff[1] == pytest.approx(1.5)
    # a single non-finite day is skipped like a missing one, not propagated
    b.state_daily.loc[(b.state_daily["box"] == 1) & (b.state_daily["date"] == days[0]), "temp"] = (
        np.inf
    )
    partial = cmp.period_mean_diff(a, b, "temp", days)
    assert math.isfinite(partial[1])


# --- overlay_series ---------------------------------------------------------


def test_overlay_series_one_series_per_run_on_the_shared_days():
    a, b, c = _run("a", days=10), _run("b", days=40, offset=1.5), _run("c", days=20, offset=-1)
    runs = {"a": a, "b": b, "c": c}
    days = cmp.common_days(runs, date(2009, 1, 1), date(2009, 12, 31))
    series = cmp.overlay_series(runs, 2, "temp", days)
    assert list(series) == ["a", "b", "c"]  # run_ids order preserved
    for s in series.values():
        assert isinstance(s, pd.Series) and len(s) == 10
        assert s.index.equals(days)
        assert not s.isna().any()  # datetime64 alignment must line up
    assert (series["b"] - series["a"]).round(9).eq(1.5).all()
    assert series["a"].iloc[3] == pytest.approx(_temp(2, 3))


def test_overlay_series_handles_empty_days_and_missing_box():
    runs = {"a": _run("a", days=10), "b": _run("b", days=10)}
    empty = cmp.overlay_series(runs, 2, "temp", pd.DatetimeIndex([]))
    assert list(empty) == ["a", "b"] and all(len(s) == 0 for s in empty.values())
    days = cmp.common_days(runs, date(2009, 1, 1), date(2009, 1, 10))
    absent = cmp.overlay_series(runs, 99, "temp", days)
    assert all(len(s) == 10 and s.isna().all() for s in absent.values())


# --- side_by_side -----------------------------------------------------------


def _skill_rows() -> pd.DataFrame:
    rows = [
        # (run, site, variable, box, n, bias, rmse, r, r2, sd_ratio)
        ("b", "S2", "salinity", 2, 35, 0.5, 0.6, 0.9, 0.7, 1.1),
        ("a", "S1", "temperature", 1, 35, 0.0, 0.1, 0.99, 0.98, 1.0),
        ("b", "S1", "temperature", 1, 35, 1.5, 1.6, 0.99, -2.0, 1.0),
        ("a", "S1", "level", 1, 35, 0.0, 0.02, 0.8, 0.6, np.nan),
        ("a", "S2", "salinity", 2, 35, 0.4, 0.5, 0.9, 0.7, 1.05),
        ("z", "S3", "salinity", 3, 35, 9.0, 9.0, 0.1, 0.0, 2.0),  # not selected
    ]
    columns = ["run", "site", "variable", "box", "n", "bias", "rmse", "r", "r2", "sd_ratio"]
    return pd.DataFrame(rows, columns=columns)


def test_side_by_side_pivots_in_run_order_with_labels_and_nan_gaps():
    labels = {"a": "Baseline", "b": "Minija fix", "c": "Third"}
    wide = cmp.side_by_side(_skill_rows(), ["b", "a", "c"], labels)
    assert list(wide.columns) == ["Minija fix", "Baseline", "Third"]
    assert wide.index.names == ["site", "variable", "metric"]
    expected_rows = [
        (s, v, m)
        for s, v in (("S1", "temperature"), ("S1", "level"), ("S2", "salinity"))
        for m in cmp.METRIC_COLUMNS
    ]
    assert list(wide.index) == expected_rows  # site sorted, variable order, metric order
    assert cmp.METRIC_COLUMNS == ("n", "bias", "rmse", "r", "r2", "sd_ratio")
    assert wide.loc[("S1", "temperature", "bias"), "Minija fix"] == pytest.approx(1.5)
    assert wide.loc[("S1", "temperature", "r2"), "Minija fix"] == pytest.approx(-2.0)
    assert wide.loc[("S1", "temperature", "n"), "Baseline"] == 35
    assert np.isnan(wide.loc[("S1", "level", "bias"), "Minija fix"])  # b has no level row
    assert wide["Third"].isna().all()  # selected but absent from the table
    assert "S3" not in wide.index.get_level_values("site")  # run z not selected


def test_side_by_side_labels_fall_back_to_run_id_and_never_collide():
    wide = cmp.side_by_side(_skill_rows(), ["a", "b"], {"a": "Same", "b": "Same"})
    assert list(wide.columns) == ["Same (a)", "Same (b)"]
    bare = cmp.side_by_side(_skill_rows(), ["a", "b"], {})
    assert list(wide.columns) != list(bare.columns) and list(bare.columns) == ["a", "b"]


def test_side_by_side_empty_skill_keeps_shape():
    empty = sk.skill_table(
        {},
        pd.DataFrame(columns=["date", "site", "variable", "value"]),
        pd.DataFrame(columns=["site", "lat", "lon", "box"]),
        date(2009, 1, 1),
        date(2009, 1, 2),
    )
    wide = cmp.side_by_side(empty, ["a", "b"], {"a": "A"})
    assert wide.empty and list(wide.columns) == ["A", "b"]
    assert wide.index.names == ["site", "variable", "metric"]


def test_side_by_side_lines_up_with_skill_table_and_compute_metrics():
    a, b = _run("a", days=40), _run("b", days=40, offset=1.5)
    dates = pd.date_range("2009-01-01", periods=40, freq="D")
    obs_values = np.array([_temp(1, i) + 0.2 * ((-1) ** i) for i in range(40)])
    obs = pd.DataFrame({"date": dates, "site": "S", "variable": "temperature", "value": obs_values})
    sites = pd.DataFrame(
        {"site": ["S"], "lat": [0.0], "lon": [0.0], "box": pd.array([1], dtype="Int64")}
    )
    skill = sk.skill_table({"a": a, "b": b}, obs, sites, date(2009, 1, 1), date(2009, 2, 9))
    wide = cmp.side_by_side(skill, ["a", "b"], {"a": "A", "b": "B"})
    assert wide.shape == (len(cmp.METRIC_COLUMNS), 2)
    mod_b = np.array([_temp(1, i, 1.5) for i in range(40)])
    mt = sk.compute_metrics(obs_values, mod_b, is_level=False)
    assert wide.loc[("S", "temperature", "bias"), "B"] == pytest.approx(mt.bias)
    assert wide.loc[("S", "temperature", "rmse"), "B"] == pytest.approx(mt.rmse)
    assert wide.loc[("S", "temperature", "n"), "A"] == 40
    assert wide.loc[("S", "temperature", "sd_ratio"), "A"] == pytest.approx(mt.sd_ratio)
