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
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


def _looks_numeric(token: str) -> bool:
    """Return *True* if *token* looks like a number (int or float)."""
    return token.replace(".", "").replace("-", "").replace("+", "").replace("e", "").isdigit()


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

    If the file cannot be read at all an empty result is returned.
    """
    path = Path(path)
    if not path.exists():
        logger.debug("Time-series file does not exist: %s", path)
        return {"columns": [], "data": [], "df": None}

    # ---- attempt 1: pandas CSV (auto-detect delimiter) ----
    try:
        import pandas as _pd

        df: pd.DataFrame = _pd.read_csv(path, sep=None, engine="python")
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


def _load_whitespace(path: Path) -> dict:
    """Parse a whitespace-delimited file with optional header row."""
    data: list[list[float]] = []
    columns: list[str] = []

    try:
        with open(path) as fh:
            for i, line in enumerate(fh):
                parts = line.strip().split()
                if not parts:
                    continue
                # First row: treat as header if the first token is not numeric
                if i == 0 and not _looks_numeric(parts[0]):
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
