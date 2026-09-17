"""Observation import rules and skill metrics, transcribed from the Curonian
scripts ``compare_runs.py`` / ``grid_summary.py`` (spec §7). Keep them in
sync by hand; the plan's tests pin every definition.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from shyfem_ui.services.boxmodel_cache import CachedRun

VARIABLE_COLUMNS = {"salinity": "salt", "temperature": "temp", "level": "act_eta"}
MIN_N_SKILL = 30
MIN_N_YEAR = 60
MIN_OBS_DAYS = 3
MAX_OBS_ROWS = 2_000_000
MAX_OBS_BYTES = 50 * 1024 * 1024
BANDS = ((2, 4), (4, 10), (10, 30), (30, 400))


class ObservationError(ValueError):
    """User-facing observation-file problem."""


@dataclass(frozen=True)
class Metrics:
    n: int
    bias: float
    rmse: float
    r: float
    r2: float
    sd_ratio: float | None


def compute_metrics(obs: np.ndarray, mod: np.ndarray, *, is_level: bool) -> Metrics:
    """bias = mean(m) - mean(o); rmse = sqrt(mean((m-o)^2)); r, sd with
    ddof=0 (population statistics); r2 = 1 - sum((m-o)^2) / sum((o-obar)^2)
    (Nash-Sutcliffe form, can be negative). For a level series, both sides
    are first replaced by their own anomaly (value - own mean) so a
    reference-datum offset between the model and the gauge never enters the
    comparison.
    """
    o = np.asarray(obs, dtype=float)
    m = np.asarray(mod, dtype=float)
    if is_level:  # anomaly about each series' own mean
        o = o - o.mean()
        m = m - m.mean()
    n = len(o)
    bias = float(m.mean() - o.mean())
    rmse = float(math.sqrt(((m - o) ** 2).sum() / n))
    so, sm = float(o.std()), float(m.std())  # ddof = 0 (population std)
    r = (
        float(((o - o.mean()) * (m - m.mean())).sum() / n / (so * sm))
        if so > 0 and sm > 0
        else float("nan")
    )
    denom = ((o - o.mean()) ** 2).sum()
    r2 = float(1 - ((m - o) ** 2).sum() / denom) if denom > 0 else float("nan")
    sd_ratio = (sm / so) if so > 0 else None
    return Metrics(n, bias, rmse, r, r2, sd_ratio)


def load_observations(path: Path) -> tuple[pd.DataFrame, dict]:
    """Load ``observations.csv`` (columns ``date, site, variable, value``).

    Validates strictly and raises :class:`ObservationError` on any problem;
    returns the cleaned frame (``date`` datetime64, ``value`` in metres for
    ``level``) plus a report of what was dropped and why.
    """
    path = Path(path)
    if path.stat().st_size > MAX_OBS_BYTES:
        raise ObservationError("observations file exceeds 50 MB")
    try:
        df = pd.read_csv(
            path,
            usecols=["date", "site", "variable", "value"],
            dtype={"site": "string", "variable": "string", "value": "float64"},
            nrows=MAX_OBS_ROWS + 1,
        )
    except (ValueError, KeyError) as e:
        raise ObservationError(f"observations: {e}") from e
    if len(df) > MAX_OBS_ROWS:
        raise ObservationError("observations exceed 2 000 000 rows")

    bad_var = set(df["variable"].dropna()) - set(VARIABLE_COLUMNS)
    if bad_var:
        raise ObservationError(f"observations: unknown variable(s) {sorted(bad_var)}")

    dates = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ObservationError("observations: date must be ISO YYYY-MM-DD")
    df["date"] = dates

    report = {"rows": int(len(df)), "dropped_nonfinite": 0, "dropped_level_le0": 0}

    finite = np.isfinite(df["value"].to_numpy(dtype=float))
    report["dropped_nonfinite"] = int((~finite).sum())
    df = df[finite]

    is_level = df["variable"] == "level"
    le0 = is_level & (df["value"] <= 0)
    report["dropped_level_le0"] = int(le0.sum())
    df = df[~le0].copy()

    level_mask = df["variable"] == "level"
    df.loc[level_mask, "value"] = df.loc[level_mask, "value"] / 100.0  # cm -> m

    if df.duplicated(["date", "site", "variable"]).any():
        raise ObservationError("observations: duplicate (date, site, variable) rows")

    return df.reset_index(drop=True), report


def load_sites(path: Path) -> pd.DataFrame:
    """Load ``sites.csv`` (columns ``site, lat, lon, box``); ``box`` is a
    nullable ``Int64`` (a blank cell means "not mapped to a box").
    """
    try:
        s = pd.read_csv(path, usecols=["site", "lat", "lon", "box"], dtype={"site": "string"})
    except (ValueError, KeyError) as e:
        raise ObservationError(f"sites: {e}") from e
    s["box"] = pd.array(pd.to_numeric(s["box"], errors="coerce").round(), dtype="Int64")
    return s


def model_series(run: CachedRun, box: int, column: str, start, end) -> pd.Series:
    """Daily ``column`` for ``box`` in ``[start, end]`` from ``run.state_daily``."""
    sd = run.state_daily
    sel = sd[
        (sd["box"] == box) & (sd["date"] >= pd.Timestamp(start)) & (sd["date"] <= pd.Timestamp(end))
    ]
    return pd.Series(sel[column].to_numpy(), index=pd.Index(sel["date"])).sort_index()


def _targets(obs: pd.DataFrame, sites: pd.DataFrame):
    """Yield ``(site, variable, box, column, obs_series)`` for every
    site/variable pair that has both a box mapping and at least one
    observation row.
    """
    mapped = sites.dropna(subset=["box"])
    for _, srow in mapped.iterrows():
        for var, col in VARIABLE_COLUMNS.items():
            o = obs[(obs["site"] == srow["site"]) & (obs["variable"] == var)]
            if len(o):
                yield (
                    srow["site"],
                    var,
                    int(srow["box"]),
                    col,
                    pd.Series(o["value"].to_numpy(), index=pd.Index(o["date"])),
                )


def skill_table(
    runs: dict[str, CachedRun],
    obs: pd.DataFrame,
    sites: pd.DataFrame,
    start,
    end,
    *,
    min_n: int = MIN_N_SKILL,
) -> pd.DataFrame:
    """One row per (run, site, variable) with at least ``min_n`` matched days
    in ``[start, end]``. A target with fewer than ``MIN_OBS_DAYS`` matched
    observation days (before the per-run model-availability filter) is
    skipped entirely, mirroring ``compare_runs.py``.
    """
    rows: list[dict] = []
    common: set | None = None
    for r in runs.values():
        d = set(r.state_daily["date"].unique())
        common = d if common is None else common & d
    common = {c for c in (common or set()) if pd.Timestamp(start) <= c <= pd.Timestamp(end)}

    for site, var, box, col, o in _targets(obs, sites):
        days = sorted(set(o.index) & common)
        if len(days) < MIN_OBS_DAYS:
            continue  # target skipped, like compare_runs.py
        obs_on_days = o.reindex(days)
        for run_id, r in runs.items():
            m = model_series(r, box, col, start, end).reindex(days)
            k = m.notna().to_numpy()
            if k.sum() < min_n:
                continue
            mt = compute_metrics(
                obs_on_days.to_numpy()[k], m.to_numpy()[k], is_level=(var == "level")
            )
            rows.append({"run": run_id, "site": site, "variable": var, "box": box, **asdict(mt)})
    return pd.DataFrame(
        rows, columns=["run", "site", "variable", "box", "n", "bias", "rmse", "r", "r2", "sd_ratio"]
    )


def per_year_table(
    runs: dict[str, CachedRun],
    obs: pd.DataFrame,
    sites: pd.DataFrame,
    start,
    end,
    *,
    min_n: int = MIN_N_YEAR,
) -> pd.DataFrame:
    """Same columns as :func:`skill_table` plus a leading ``year`` column,
    one :func:`skill_table` call per calendar year overlapping ``[start,
    end]`` (so a target's per-year rows use only that year's matched days).
    """
    frames = []
    for y in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        ys = max(pd.Timestamp(start), pd.Timestamp(y, 1, 1))
        ye = min(pd.Timestamp(end), pd.Timestamp(y, 12, 31))
        t = skill_table(runs, obs, sites, ys, ye, min_n=min_n)
        if len(t):
            t.insert(0, "year", y)
            frames.append(t)
    if not frames:
        return pd.DataFrame(
            columns=[
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
        )
    return pd.concat(frames, ignore_index=True)


def band_amplitude_ratios(obs_daily: pd.Series, mod_daily: pd.Series) -> dict[str, float] | None:
    """Hann-windowed FFT amplitude ratio (model / observed) per period band.

    Requires at least 120 gap-free (one-per-calendar-day) common days;
    returns ``None`` when that cannot be satisfied, or when a band's
    observed amplitude is zero (nothing to compare against).
    """
    idx = obs_daily.index.intersection(mod_daily.index).sort_values()
    if len(idx) < 120:
        return None
    gaps = np.diff(idx.values).astype("timedelta64[D]").astype(int)
    if (gaps != 1).any():
        return None
    o = obs_daily.reindex(idx).to_numpy(dtype=float)
    m = mod_daily.reindex(idx).to_numpy(dtype=float)
    if np.isnan(o).any() or np.isnan(m).any():
        return None

    w = np.hanning(len(idx))
    fo = np.abs(np.fft.rfft((o - o.mean()) * w))
    fm = np.abs(np.fft.rfft((m - m.mean()) * w))
    freqs = np.fft.rfftfreq(len(idx), d=1.0)

    out: dict[str, float] = {}
    for lo, hi in BANDS:
        sel = (freqs > 0) & (freqs >= 1.0 / hi) & (freqs <= 1.0 / lo)
        if sel.any() and fo[sel].sum() > 0:
            out[f"{lo}-{hi} d"] = float(fm[sel].sum() / fo[sel].sum())
    return out or None
