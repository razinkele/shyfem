"""Observation import rules and skill metrics, transcribed from the Curonian
scripts ``compare_runs.py`` / ``grid_summary.py`` (spec §7). Keep them in
sync by hand; the tests here pin every formula we can exercise directly,
but a same-input-and-output numerical cross-check against the standalone
scripts is what actually caught a wrong ``band_amplitude_ratios`` formula
that a degenerate (scalar-multiple) test had let through -- treat "the
tests pass" as necessary, not sufficient, evidence of a correct
transcription.
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
    try:
        size = path.stat().st_size
    except FileNotFoundError as e:
        raise ObservationError(f"observations: file not found: {path}") from e
    if size > MAX_OBS_BYTES:
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

    if df["site"].isna().any() or df["variable"].isna().any():
        raise ObservationError("observations: site and variable must be non-empty")

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

    # Checked LAST, after the non-finite and level<=0 drops: the fixture's
    # own `2009-01-05,A,level,0` sentinel row shares a (date, site,
    # variable) key with that day's real level reading, and is only
    # resolved to a single row once the le0 drop above has removed the
    # sentinel -- checking duplicates any earlier would raise on that
    # fixture. Don't reorder this without re-checking that fixture row.
    if df.duplicated(["date", "site", "variable"]).any():
        raise ObservationError("observations: duplicate (date, site, variable) rows")

    return df.reset_index(drop=True), report


def load_sites(path: Path) -> pd.DataFrame:
    """Load ``sites.csv`` (columns ``site, lat, lon, box``); ``box`` is a
    nullable ``Int64`` (a blank/whitespace-only cell means "not mapped to a
    box"). Anything else that isn't an integer (``"abc"``, ``"1.7"``)
    raises :class:`ObservationError` naming the offending value, rather
    than silently coercing a typo to a plausible-looking box id.
    """
    try:
        s = pd.read_csv(path, usecols=["site", "lat", "lon", "box"], dtype={"site": "string"})
    except FileNotFoundError as e:
        raise ObservationError(f"sites: file not found: {path}") from e
    except (ValueError, KeyError) as e:
        raise ObservationError(f"sites: {e}") from e

    raw = s["box"].astype("string")  # normalize whatever read_csv inferred
    stripped = raw.str.strip()
    blank = raw.isna() | (stripped == "")
    numeric = pd.to_numeric(stripped, errors="coerce")
    bad = ~blank & (numeric.isna() | (numeric != numeric.round()))
    if bad.any():
        bad_value = raw[bad].iloc[0]
        raise ObservationError(f"sites: box must be an integer, got {bad_value!r}")
    s["box"] = pd.array(numeric.round().where(~blank), dtype="Int64")
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
    skipped entirely, mirroring ``compare_runs.py``. Within those matched
    days, only the ones where *both* the observation and the model value
    are finite are counted or passed to :func:`compute_metrics` -- a
    non-finite model value (``inf``/``nan``, e.g. from a diverged run) is
    excluded exactly like a missing one, so this function stays
    self-sufficient even when ``obs`` didn't come from
    :func:`load_observations` (which already guarantees finite values).
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
        obs_values = o.reindex(days).to_numpy(dtype=float)
        for run_id, r in runs.items():
            mod_values = model_series(r, box, col, start, end).reindex(days).to_numpy(dtype=float)
            k = np.isfinite(obs_values) & np.isfinite(mod_values)
            if k.sum() < min_n:
                continue
            mt = compute_metrics(obs_values[k], mod_values[k], is_level=(var == "level"))
            rows.append({"run": run_id, "site": site, "variable": var, "box": box, **asdict(mt)})
    columns = ["run", "site", "variable", "box", "n", "bias", "rmse", "r", "r2", "sd_ratio"]
    dtypes = {
        "run": "str",
        "site": "str",
        "variable": "str",
        "box": "int64",
        "n": "int64",
        "bias": "float64",
        "rmse": "float64",
        "r": "float64",
        "r2": "float64",
        "sd_ratio": "float64",
    }
    # .astype unconditionally (not just on the rows=[] branch): guarantees
    # the empty and populated cases always agree on dtypes, rather than
    # relying on pandas' string-dtype-inference default (a global option)
    # to happen to match what an explicit empty-frame cast would produce.
    return pd.DataFrame(rows, columns=columns).astype(dtypes)


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
        columns = [
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
        dtypes = {
            "year": "int64",
            "run": "str",
            "site": "str",
            "variable": "str",
            "box": "int64",
            "n": "int64",
            "bias": "float64",
            "rmse": "float64",
            "r": "float64",
            "r2": "float64",
            "sd_ratio": "float64",
        }
        return pd.DataFrame(columns=columns).astype(dtypes)
    return pd.concat(frames, ignore_index=True)


def band_amplitude_ratios(obs_daily: pd.Series, mod_daily: pd.Series) -> dict[str, float] | None:
    """Hann-windowed FFT amplitude ratio (model / observed) per period band.

    Per band, the amplitude of a series is
    ``sqrt(sum(|rfft((x - xbar) * hanning(n))|**2))`` over that band's
    frequency bins, and the ratio is the model's amplitude divided by the
    observed one -- this is ``bandamp`` in ``compare_runs.py``, and must
    stay numerically equivalent to it (an earlier version of this function
    summed the magnitudes instead of taking the root-sum-of-squares, and
    used a closed upper band edge; both were wrong, caught only by a
    numerical cross-check against ``compare_runs.py`` itself). Band
    membership is the half-open ``1/hi <= f < 1/lo`` (the shared edge
    between adjacent bands belongs to
    the *lower-frequency* -- i.e. longer-period -- band only). Requires at
    least 120 gap-free (one-per-calendar-day) common days; returns ``None``
    when that cannot be satisfied, or when a band's observed power is zero
    (nothing to compare against).
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
        sel = (freqs >= 1.0 / hi) & (freqs < 1.0 / lo)
        obs_power = float((fo[sel] ** 2).sum())
        if sel.any() and obs_power > 0:
            mod_power = float((fm[sel] ** 2).sum())
            out[f"{lo}-{hi} d"] = math.sqrt(mod_power) / math.sqrt(obs_power)
    return out or None
