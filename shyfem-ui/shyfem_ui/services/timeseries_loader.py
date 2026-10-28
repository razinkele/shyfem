"""Unified time series file loading utilities.

Consolidates duplicate CSV / whitespace-delimited loading logic that was
previously scattered across ``components/timeseries.py``,
``pages/visualize.py``, ``pages/compare.py`` and ``pages/ensemble.py``.

Two entry-points:

*  ``load_timeseries(path)`` — rich loader that returns column names,
   raw data rows, and (when pandas succeeds) a ``DataFrame``.
*  ``load_timeseries_raw(path)`` — lightweight loader that returns only
   ``list[list[float]]`` with no pandas dependency.
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

# SHYFEM time-series stamp, e.g. ``1990-01-03::06:00:00`` (date ``::`` time).
_SHYFEM_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}::\d{2}:\d{2}:\d{2}$")
# Long-format observation columns (case-insensitive) -> pivoted to wide.
_OBS_COLUMNS = {"date", "site", "variable", "value"}


def _looks_numeric(token: str) -> bool:
    """Return *True* if *token* looks like a number (int or float)."""
    return token.replace(".", "").replace("-", "").replace("+", "").replace("e", "").isdigit()


def _first_token(path: Path) -> str | None:
    """First whitespace token of the first non-blank, non-comment line."""
    try:
        with open(path) as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    return s.split()[0]
    except OSError:
        return None
    return None


def _load_shyfem_ts(path: Path) -> dict:
    """Parse a SHYFEM ``YYYY-MM-DD::HH:MM:SS  v1 [v2 ...]`` series.

    Used for the river/forcing ``.txt`` files, which have no header and a
    ``date::time`` stamp the generic CSV sniffer mis-reads. Returns the usual
    ``columns``/``data``/``df`` dict with a parsed datetime first column so
    the plot gets a real time axis.
    """
    import pandas as _pd

    times: list[str] = []
    rows: list[list[float]] = []
    header: str | None = None
    try:
        with open(path) as fh:
            for line in fh:
                if not rows and line.lstrip().startswith("#"):
                    header = line  # shyelab's "# date <names>" line
                    continue
                parts = line.split()
                if not parts or not _SHYFEM_TS_RE.match(parts[0]):
                    continue
                try:
                    vals = [float(p) for p in parts[1:]]
                except ValueError:
                    continue
                times.append(parts[0].replace("::", " "))
                # shyelab writes "Infinity" for an undefined Basin Average
                rows.append([v if math.isfinite(v) else float("nan") for v in vals])
    except OSError:
        logger.warning("Could not open SHYFEM time-series %s", path, exc_info=True)
        return {"columns": [], "data": [], "df": None}

    if not rows:
        return {"columns": [], "data": [], "df": None}

    ncol = max(len(r) for r in rows)
    rows = [r + [float("nan")] * (ncol - len(r)) for r in rows]
    value_cols = _header_names(header, ncol) or (
        ["value"] if ncol == 1 else [f"value{i + 1}" for i in range(ncol)]
    )
    df: pd.DataFrame = _pd.DataFrame(rows, columns=value_cols)
    df.insert(0, "time", _pd.to_datetime(times, format="%Y-%m-%d %H:%M:%S", errors="coerce"))
    return {"columns": list(df.columns), "data": df.values.tolist(), "df": df}


def _header_names(header: str | None, ncol: int) -> list[str] | None:
    """Column names from a ``# date name ...`` header, when they fit ``ncol``.

    One value column takes the whole text (``salinity (vertically
    averaged)``); several take one word each (``minimum average maximum``).
    """
    words = header.lstrip().lstrip("#").split() if header else []
    if len(words) < 2 or not words[0].lower().startswith("date"):
        return None
    if ncol == 1:
        return [" ".join(words[1:])]
    names = words[1:]
    if len(names) == ncol and len(set(names)) == ncol and "time" not in names:
        return names
    return None


def _pivot_observations(df: pd.DataFrame) -> dict:
    """Pivot a long ``date,site,variable,value`` frame to one column per
    ``site variable`` series, indexed by date, so it plots as time series."""
    import pandas as _pd

    d = df.copy()
    d["date"] = _pd.to_datetime(d["date"], errors="coerce")
    d["series"] = d["site"].astype(str) + " " + d["variable"].astype(str)
    wide = d.pivot_table(
        index="date", columns="series", values="value", aggfunc="mean"
    ).reset_index()
    wide.columns.name = None
    return {"columns": list(wide.columns), "data": wide.values.tolist(), "df": wide}


# ---------------------------------------------------------------------------
# Rich loader (returns columns + optional DataFrame)
# ---------------------------------------------------------------------------


def load_timeseries(path: Path | str) -> dict:
    """Load a time-series file, trying pandas first then whitespace fallback.

    Returns a dict with keys:
        ``columns`` — list of column name strings
        ``data``    — list of rows (each row a list of floats)
        ``df``      — ``pandas.DataFrame`` if pandas parsing succeeded,
                      else ``None``

    Two SHYFEM-specific shapes are handled before the generic path: forcing
    ``.txt`` files (``date::time value``) and long-format ``observations.csv``
    (``date,site,variable,value`` pivoted to one column per site+variable).

    If the file cannot be read at all an empty result is returned.
    """
    path = Path(path)
    if not path.exists():
        logger.debug("Time-series file does not exist: %s", path)
        return {"columns": [], "data": [], "df": None}

    # ---- SHYFEM forcing (date::time value), before the CSV sniffer ----
    tok = _first_token(path)
    if tok is not None and _SHYFEM_TS_RE.match(tok):
        shyfem = _load_shyfem_ts(path)
        if shyfem["df"] is not None:
            return shyfem

    # ---- attempt 1: pandas CSV (auto-detect delimiter) ----
    try:
        import pandas as _pd

        if _first_row_is_numeric(path):
            # A numeric first line is data, not a header (V-04): pandas would
            # drop the first record and name the columns after its values.
            df = _pd.read_csv(path, sep=None, engine="python", header=None)
            df.columns = [f"col{j}" for j in range(df.shape[1])]
        else:
            df = _pd.read_csv(path, sep=None, engine="python")
        if {str(c).lower() for c in df.columns} == _OBS_COLUMNS:
            return _pivot_observations(df)
        return {
            "columns": list(df.columns),
            "data": df.values.tolist(),
            "df": df,
        }
    except Exception:
        logger.debug(
            "pandas CSV parsing failed for %s, falling back to whitespace-delimited",
            path,
        )

    # ---- attempt 2: manual whitespace-delimited ----
    return _load_whitespace(path)


def _first_row_is_numeric(path: Path) -> bool:
    """True when the first non-blank line is all numbers (so no header)."""
    try:
        with open(path) as fh:
            for line in fh:
                parts = [t for t in re.split(r"[,;\s]+", line.strip()) if t]
                if parts:
                    return all(_looks_numeric(t) for t in parts)
    except OSError:
        return False
    return False


def _load_whitespace(path: Path) -> dict:
    """Parse a whitespace-delimited file with optional header row."""
    data: list[list[float]] = []
    columns: list[str] = []
    header_checked = False

    try:
        with open(path) as fh:
            for i, line in enumerate(fh):
                parts = line.strip().split()
                if not parts:
                    continue
                # First non-blank row: treat as header if the first token is
                # not numeric. Detection is index-independent so leading
                # blank lines don't shift the header past this check.
                if not header_checked:
                    header_checked = True
                    if not _looks_numeric(parts[0]):
                        columns = parts
                        continue
                try:
                    data.append([float(p) for p in parts])
                except ValueError:
                    logger.debug("Skipping non-numeric line %d in %s", i, path)
    except OSError:
        logger.warning("Could not open time-series file %s", path, exc_info=True)
        return {"columns": [], "data": [], "df": None}

    if not columns and data:
        columns = [f"col{j}" for j in range(len(data[0]))]

    return {"columns": columns, "data": data, "df": None}


# ---------------------------------------------------------------------------
# Lightweight loader (float rows only, no pandas)
# ---------------------------------------------------------------------------


def load_timeseries_raw(path: Path | str) -> list[list[float]]:
    """Load time-series data as a flat list of float rows.

    Skips blank lines and lines that cannot be fully converted to float.
    Returns an empty list if the file is missing or unreadable.
    """
    path = Path(path)
    if not path.exists():
        return []

    data: list[list[float]] = []
    try:
        with open(path) as fh:
            for line in fh:
                parts = line.strip().split()
                if not parts:
                    continue
                try:
                    data.append([float(p) for p in parts])
                except ValueError:
                    logger.debug("Skipping non-numeric line in %s", path)
    except OSError:
        logger.warning("Failed to load time series from %s", path, exc_info=True)

    return data
