"""Pure helpers behind the "Compare" tab of the Box model page (spec §8).

Everything here reads only ``CachedRun.state_daily`` frames and returns plain
pandas objects; no reactive state, no I/O. The one shared day set
(:func:`common_days`) is computed once by the page and handed to the
difference map, the overlay plot and the skill tables, so the three can never
silently disagree on which days they describe. Metric maths stays in
``boxmodel_skill`` -- this module only rearranges its output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shyfem_ui.services.boxmodel_skill import VARIABLE_COLUMNS, model_series

if TYPE_CHECKING:
    from shyfem_ui.services.boxmodel_cache import CachedRun

#: Skill metrics shown side by side, in row order, as ``skill_table`` names them.
METRIC_COLUMNS = ("n", "bias", "rmse", "r", "r2", "sd_ratio")

_INDEX_NAMES = ["site", "variable", "metric"]


def _empty_days() -> pd.DatetimeIndex:
    return pd.DatetimeIndex([], dtype="datetime64[ns]")


def common_days(runs: dict[str, CachedRun | None], start, end) -> pd.DatetimeIndex:
    """Intersection of every run's ``state_daily["date"]`` clamped to
    ``[start, end]`` (both ends inclusive), unique and sorted.

    Empty when ``runs`` is empty, when any run is missing (``None``) or when
    the intersection is empty. Same day set as ``skill_table`` builds
    internally, so the tables and the map/overlay agree.
    """
    if not runs or any(r is None for r in runs.values()):
        return _empty_days()
    common: pd.DatetimeIndex | None = None
    for run in runs.values():
        days = pd.DatetimeIndex(run.state_daily["date"].unique())
        common = days if common is None else common.intersection(days)
    if common is None:
        return _empty_days()
    common = common[(common >= pd.Timestamp(start)) & (common <= pd.Timestamp(end))]
    if len(common) == 0:
        return _empty_days()
    return pd.DatetimeIndex(common.unique().sort_values()).astype("datetime64[ns]")


def _box_means(run: CachedRun, column: str, days: pd.DatetimeIndex) -> pd.Series:
    """Per-box mean of ``column`` over exactly ``days``; non-finite values are
    treated as missing (like ``skill_table`` does), so a box with no finite
    value comes out NaN rather than inf.
    """
    sd = run.state_daily
    sel = sd.loc[sd["date"].isin(days), ["box", column]]
    values = sel[column].astype(float).replace([np.inf, -np.inf], np.nan)
    return values.groupby(sel["box"]).mean()


def period_mean_diff(
    a: CachedRun, b: CachedRun, column: str, days: pd.DatetimeIndex
) -> dict[int, float]:
    """``mean_b - mean_a`` of ``column`` per box over exactly ``days``.

    Only boxes present in both runs are considered, and a box with no finite
    value in either run is omitted. Keys are plain ``int`` box ids, the shape
    ``build_box_layers`` consumes.
    """
    if len(days) == 0:
        return {}
    mean_a = _box_means(a, column, days)
    mean_b = _box_means(b, column, days)
    diff = (mean_b - mean_a).dropna()
    return {int(box): float(value) for box, value in diff.items()}


def overlay_series(
    runs: dict[str, CachedRun], box: int, column: str, days: pd.DatetimeIndex
) -> dict[str, pd.Series]:
    """One daily series of ``column`` for ``box`` per run, restricted to and
    indexed by ``days`` (NaN where a run has no value), in ``runs`` order.
    """
    if len(days) == 0:
        return {run_id: pd.Series(dtype=float, index=_empty_days()) for run_id in runs}
    start, end = days.min(), days.max()
    return {
        run_id: model_series(run, box, column, start, end).astype(float).reindex(days)
        for run_id, run in runs.items()
    }


def _column_labels(run_ids: list[str], labels: dict[str, str]) -> list[str]:
    """Labels in ``run_ids`` order; a label shared by several runs is
    disambiguated with the run id so the headers never collide.
    """
    names = [labels.get(run_id, run_id) for run_id in run_ids]
    counts = pd.Series(names).value_counts()
    return [
        f"{name} ({run_id})" if counts[name] > 1 else name
        for name, run_id in zip(names, run_ids, strict=True)
    ]


def side_by_side(skill: pd.DataFrame, run_ids: list[str], labels: dict[str, str]) -> pd.DataFrame:
    """Pivot long ``skill_table`` rows into one column per run.

    Rows are indexed by ``(site, variable, metric)`` -- sites sorted, variables
    in ``VARIABLE_COLUMNS`` order, metrics in :data:`METRIC_COLUMNS` order --
    and only the ``(site, variable)`` pairs that some run in ``run_ids`` has a
    row for appear. Columns are the run labels in ``run_ids`` order (a run
    without rows gives an all-NaN column); missing cells are NaN, which also
    makes ``n`` a float column here.
    """
    sub = skill[skill["run"].isin(run_ids)]
    var_rank = {v: i for i, v in enumerate(VARIABLE_COLUMNS)}
    pairs = sorted(
        set(zip(sub["site"], sub["variable"], strict=True)),
        key=lambda p: (p[0], var_rank.get(p[1], len(var_rank)), p[1]),
    )
    index = pd.MultiIndex.from_tuples(
        [(site, variable, metric) for site, variable in pairs for metric in METRIC_COLUMNS],
        names=_INDEX_NAMES,
    )
    long = sub.melt(
        id_vars=["run", "site", "variable"],
        value_vars=list(METRIC_COLUMNS),
        var_name="metric",
        value_name="value",
    )
    long["value"] = long["value"].astype(float)
    wide = long.pivot(index=_INDEX_NAMES, columns="run", values="value")
    wide = wide.reindex(index=index, columns=list(run_ids))
    wide.columns = pd.Index(_column_labels(list(run_ids), labels))
    return wide
