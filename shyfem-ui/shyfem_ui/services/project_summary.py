"""Cached per-project summary written to ``.project_summary.json``.

Describes a project's setup files, grids (with mesh statistics), box-model
runs, and time-series statistics for both forcing series and measurements, so
pages (e.g. the Projects *Details* popup) read one small JSON instead of
re-scanning the directory and re-parsing grids/series every time.

The summary is rebuilt only when a source file's mtime changes (tracked in
``_sources``); otherwise the cached JSON is returned as-is. All builders are
defensive — a single unreadable file never aborts the summary.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SUMMARY_NAME = ".project_summary.json"
SCHEMA = 1
_SLUG = re.compile(r"^[a-z0-9_-]{1,64}$")
_MAX_FILES = 500


def _walk(root: Path):
    """Yield ``(rel, path, size, mtime_ns)`` for non-hidden files; hidden
    directories (e.g. ``.boxmodel_cache``) are pruned, never descended.

    The second yielded value per directory is its own mtime via
    :func:`dir_mtimes`; callers track those so adding/removing a file (which
    bumps its parent directory's mtime) invalidates the cached summary."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.startswith("."):
                continue
            p = Path(dirpath) / fn
            try:
                st = p.stat()
            except OSError:
                continue
            yield str(p.relative_to(root)), p, st.st_size, st.st_mtime_ns


def _dir_mtimes(root: Path) -> dict[str, int]:
    """``{"dir:<rel>": mtime_ns}`` for the root and every non-hidden subdir, so
    a file added or removed (which changes its parent dir's mtime) is detected."""
    out: dict[str, int] = {}
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        try:
            out[f"dir:{Path(dirpath).relative_to(root)}"] = Path(dirpath).stat().st_mtime_ns
        except OSError:
            continue
    return out


def _grid_stats(path: Path) -> dict | None:
    """Mesh statistics for a ``.grd`` file, or None if it can't be parsed."""
    from shyfem_ui.services.parser_grd import GrdParser

    try:
        g = GrdParser.parse_file(path)
    except Exception:
        return None
    if g.num_nodes == 0:
        return None
    try:
        s = GrdParser.get_statistics(g)
    except Exception:
        return None
    depth = s.get("depth") or {}
    return {
        "nodes": s.get("num_nodes"),
        "elements": s.get("num_elements"),
        "triangles": s.get("num_triangles"),
        "quads": s.get("num_quads"),
        "depth_min": depth.get("min"),
        "depth_max": depth.get("max"),
        "bounds": s.get("bounds"),
    }


def _series_stats(path: Path) -> list[dict]:
    """Per-column statistics for a time-series file (n, date range, min/max/mean)."""
    from shyfem_ui.services.timeseries_loader import load_timeseries

    try:
        df = load_timeseries(path).get("df")
    except Exception:
        return []
    if df is None or df.shape[1] < 2:
        return []
    start = end = None
    x = df.iloc[:, 0]
    if str(x.dtype).startswith("datetime"):
        try:
            start, end = str(x.min())[:10], str(x.max())[:10]
        except (ValueError, TypeError):
            pass
    out = []
    for col in df.columns[1:]:
        v = df[col].to_numpy(dtype=float, na_value=np.nan)
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        out.append(
            {
                "series": str(col),
                "n": int(v.size),
                "start": start,
                "end": end,
                "min": round(float(v.min()), 4),
                "max": round(float(v.max()), 4),
                "mean": round(float(v.mean()), 4),
            }
        )
    return out


def _observation_stats(path: Path) -> list[dict]:
    """Per site+variable statistics for a long-format observations file."""
    from shyfem_ui.services.boxmodel_skill import load_observations

    try:
        obs, _report = load_observations(path)
    except Exception:
        return []
    out = []
    for (site, var), grp in obs.groupby(["site", "variable"], sort=True):
        v = grp["value"].to_numpy(dtype=float, na_value=np.nan)
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        out.append(
            {
                "site": str(site),
                "variable": str(var),
                "n": int(v.size),
                "start": str(grp["date"].min())[:10],
                "end": str(grp["date"].max())[:10],
                "min": round(float(v.min()), 4),
                "max": round(float(v.max()), 4),
                "mean": round(float(v.mean()), 4),
            }
        )
    return out


def _manifest(root: Path) -> dict | None:
    mf = root / "boxmodel.json"
    if not mf.is_file():
        return None
    try:
        d = json.loads(mf.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _runs(root: Path, manifest: dict | None) -> list[dict]:
    if not manifest:
        return []
    runs = manifest.get("runs")
    if not isinstance(runs, list):
        return []
    out = []
    for r in runs:
        if not isinstance(r, dict):
            continue
        rid = r.get("id") or ""
        entry = {"id": rid, "label": r.get("label") or rid, "period": None, "cache": "not built"}
        if isinstance(rid, str) and _SLUG.fullmatch(rid):
            meta = root / ".boxmodel_cache" / rid / "meta.json"
            if meta.is_file():
                entry["cache"] = "ready"
                try:
                    p = (json.loads(meta.read_text(encoding="utf-8")).get("period")) or {}
                    if p.get("start") and p.get("end"):
                        entry["period"] = f"{p['start'][:10]} → {p['end'][:10]}"
                except (OSError, ValueError):
                    pass
        out.append(entry)
    return out


def build_summary(work_dir: str | Path) -> dict:
    """Scan ``work_dir`` and compute the full summary dict (does not write it)."""
    root = Path(work_dir)
    manifest = _manifest(root)
    forcing_dir = None
    if manifest and isinstance(manifest.get("forcing"), dict):
        fd = manifest["forcing"].get("dir")
        if isinstance(fd, str):
            forcing_dir = fd.strip("/")
    obs_rel = None
    if manifest and isinstance(manifest.get("observations"), dict):
        of = manifest["observations"].get("file")
        if isinstance(of, str):
            obs_rel = of

    files: list[dict] = []
    grids: list[dict] = []
    forcing: list[dict] = []
    sources: dict[str, int] = {}
    truncated = False

    for rel, p, size, mtime in _walk(root):
        if len(files) >= _MAX_FILES:
            truncated = True
            break
        files.append({"path": rel, "size": size})
        suf = p.suffix.lower()
        if suf == ".grd":
            gs = _grid_stats(p)
            if gs is not None:
                grids.append({"file": rel, **gs})
                sources[rel] = mtime
        elif suf in (".txt", ".ts") and (forcing_dir is None or rel.startswith(forcing_dir + "/")):
            series = _series_stats(p)
            if series:
                forcing.append({"file": rel, "series": series})
                sources[rel] = mtime

    observations: list[dict] = []
    if obs_rel:
        obs_path = root / obs_rel
        if obs_path.is_file():
            observations = _observation_stats(obs_path)
            try:
                sources[obs_rel] = obs_path.stat().st_mtime_ns
            except OSError:
                pass
    if manifest:
        try:
            sources["boxmodel.json"] = (root / "boxmodel.json").stat().st_mtime_ns
        except OSError:
            pass
    # Directory mtimes catch files added/removed after the summary was built.
    sources.update(_dir_mtimes(root))

    return {
        "schema": SCHEMA,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
        "files_truncated": truncated,
        "grids": grids,
        "runs": _runs(root, manifest),
        "forcing": forcing,
        "observations": observations,
        "_sources": sources,
    }


def _is_stale(root: Path, sources: dict) -> bool:
    """True if any tracked source file/directory's mtime changed (or vanished).

    Keys prefixed ``dir:`` are directory mtimes (added/removed files); the rest
    are file mtimes."""
    for key, mtime in sources.items():
        rel = key[4:] if key.startswith("dir:") else key
        try:
            if (root / rel).stat().st_mtime_ns != mtime:
                return True
        except OSError:
            return True
    return False


def load_summary(work_dir: str | Path, *, allow_build: bool = True) -> dict | None:
    """Return the cached summary, rebuilding it only if missing/stale.

    Writes ``.project_summary.json`` back on a rebuild. Returns None only when
    the summary is absent and ``allow_build`` is False.
    """
    root = Path(work_dir)
    sf = root / SUMMARY_NAME
    if sf.is_file():
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            if (
                isinstance(data, dict)
                and data.get("schema") == SCHEMA
                and not _is_stale(root, data.get("_sources", {}))
            ):
                return data
        except (OSError, ValueError):
            pass
    if not allow_build:
        return None
    data = build_summary(root)
    try:
        sf.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    except OSError:
        logger.warning("could not write %s in %s", SUMMARY_NAME, work_dir)
    return data
