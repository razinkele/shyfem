"""Build the Parquet cache of one box-model run (spec §6). Runs as a CHILD
PROCESS: ``python -m shyfem_ui.boxmodel_cache_cli --run DIR --out DIR
--trusted-base DIR ...``. Imports only the parser module, stdlib, numpy,
pandas, pyarrow -- never ``shyfem_ui.services`` (its package init loads the
ORM) -- and re-validates its paths structurally because it has no project
row: ``--out`` must be ``<base>/.../<project>/.boxmodel_cache/<run-id>.tmp-
<token>`` (checked against ``_OUT_NAME_RE``), must not itself be a symlink,
and its ``.boxmodel_cache`` parent must sit below one of ``--trusted-base``.

``meta.json`` keys: ``schema`` (1), ``built_at`` (ISO UTC), ``hourly`` (bool),
``records`` (int), ``period`` (``{"start", "end"}``), ``step_seconds``,
``boxes`` (list of ``{box, area, volume, depth}``), ``sections`` (list of
``{section, from_box, to_box}``), ``section_nodes`` (``{section: [[lon,
lat], ...]}``), ``element_box`` (list of ``[element, box]`` pairs, or
``null`` when ``boxes_geom.txt`` is absent -- consumed by Task 10 for the
polygon dissolve), ``run_log`` (``RunLogFacts`` as a dict, or ``null``),
``sources`` (``{filename: {"size", "mtime_ns"}}`` for every input file read).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
import tempfile
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from shyfem_ui import boxmodel_output as bo

STATE_FILE, METEO_FILE, STATS_FILE, GEOM_FILE, LOG_FILE = (
    "boxes_2d.txt",
    "boxes_meteo.txt",
    "boxes_stats.txt",
    "boxes_geom.txt",
    "run.log",
)
MINMAX_VARS = ("temp", "salt", "act_eta")
BYTES_PER_STATE_RECORD_GUESS = 6200  # 29 boxes + 56 sections; only for the progress estimate
_OUT_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}\.tmp-[A-Za-z0-9_-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


class _Progress:
    def __init__(self, out: Path, expected: int):
        self.path = out / "progress.json"
        self.expected = expected
        self.records = 0

    def write(self, phase: str, *, error: str | None = None, exit_code: int | None = None) -> None:
        _atomic_json(
            self.path,
            {
                "phase": phase,
                "records": self.records,
                "expected": self.expected,
                "error": error,
                "exit": exit_code,
                "updated": _now(),
            },
        )


def _no_symlink_components(p: Path) -> bool:
    cur = Path(p.anchor)
    for part in p.relative_to(p.anchor).parts:
        cur = cur / part
        if cur.is_symlink():
            return False
    return True


def _validate(run_dir: Path, out_dir: Path, bases: list[Path]) -> str | None:
    """Return an error message or None."""
    if not run_dir.is_absolute() or not out_dir.is_absolute():
        return "run and out must be absolute"
    if not run_dir.is_dir() or not _no_symlink_components(run_dir):
        return "run dir must be a real directory without symlink components"
    if not (run_dir / STATE_FILE).is_file() or (run_dir / STATE_FILE).is_symlink():
        return f"run dir has no regular {STATE_FILE}"
    if out_dir.is_symlink():
        return "out dir must not itself be a symlink"
    if not _OUT_NAME_RE.fullmatch(out_dir.name):
        return "out dir name must look like <run-id>.tmp-<token>"
    if out_dir.parent.name != ".boxmodel_cache" or not _no_symlink_components(out_dir.parent):
        return "out dir must sit directly under a .boxmodel_cache directory"
    project = out_dir.parent.parent.resolve()
    if not any(str(project).startswith(str(b.resolve()) + "/") for b in bases):
        return "out dir's project is not below a trusted base"
    return None


def _day_accumulate(acc_sum, acc_cnt, acc_min, acc_max, day, ids, values):
    s = acc_sum[day]
    if s is None:
        acc_sum[day] = values.copy()
        acc_cnt[day] = 1
        acc_min[day] = values[:, [bo.STATE_VARS.index(v) for v in MINMAX_VARS]].copy()
        acc_max[day] = acc_min[day].copy()
        return
    s += values
    acc_cnt[day] += 1
    sub = values[:, [bo.STATE_VARS.index(v) for v in MINMAX_VARS]]
    np.minimum(acc_min[day], sub, out=acc_min[day])
    np.maximum(acc_max[day], sub, out=acc_max[day])


def build(run_dir: Path, out_dir: Path, *, hourly: bool, progress_cb=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = max(1, os.path.getsize(run_dir / STATE_FILE) // BYTES_PER_STATE_RECORD_GUESS)
    prog = _Progress(out_dir, expected)
    prog.write("state")
    stats = bo.read_stats(run_dir / STATS_FILE)
    geom = bo.read_geom(run_dir / GEOM_FILE) if (run_dir / GEOM_FILE).is_file() else None
    # ---- state (and fluxes) -------------------------------------------------
    box_ids = None
    ssum: dict = defaultdict(lambda: None)
    scnt: dict = {}
    smin: dict = {}
    smax: dict = {}
    fsum: dict = defaultdict(lambda: None)
    fcnt: dict = {}
    sec_meta = None
    hourly_rows = []
    n = 0
    for rec in bo.iter_state_records(run_dir / STATE_FILE):
        if box_ids is None:
            box_ids = rec.box_ids.copy()
        elif not np.array_equal(box_ids, rec.box_ids):
            raise bo.BoxOutputError(f"{STATE_FILE}: box ids change at record {n + 1}")
        day = rec.stamp.date()
        _day_accumulate(ssum, scnt, smin, smax, day, rec.box_ids, rec.values)
        if rec.sections.size:
            if sec_meta is None:
                sec_meta = rec.sections[:, :3].astype(int)
            f = fsum[day]
            if f is None:
                fsum[day] = rec.sections[:, 3:].copy()
                fcnt[day] = 1
            else:
                f += rec.sections[:, 3:]
                fcnt[day] += 1
        if hourly:
            hourly_rows.append((rec.stamp, rec.values.astype(np.float32)))
        n += 1
        if n % 500 == 0:
            prog.records = n
            prog.write("state")
            if progress_cb:
                progress_cb(n, expected)
    if n == 0:
        raise bo.BoxOutputError(f"{STATE_FILE}: no records")
    prog.records = n
    # ---- meteo ----------------------------------------------------------------
    prog.write("meteo")
    msum: dict = defaultdict(lambda: None)
    mcnt: dict = {}
    if (run_dir / METEO_FILE).is_file():
        for rec in bo.iter_meteo_records(run_dir / METEO_FILE):
            day = rec.stamp.date()
            m = msum[day]
            if m is None:
                msum[day] = rec.values.copy()
                mcnt[day] = 1
            else:
                m += rec.values
                mcnt[day] += 1
    # ---- write ---------------------------------------------------------------
    prog.write("write")
    days = sorted(scnt)
    frames = []
    for day in days:
        df = pd.DataFrame(ssum[day] / scnt[day], columns=list(bo.STATE_VARS))
        for j, v in enumerate(MINMAX_VARS):
            df[f"{v}_min"] = smin[day][:, j]
            df[f"{v}_max"] = smax[day][:, j]
        df.insert(0, "box", box_ids.astype(np.int32))
        df.insert(0, "date", day)
        frames.append(df)
    state_daily = pd.concat(frames, ignore_index=True)
    state_daily.to_parquet(out_dir / "state_daily.parquet", index=False)
    if sec_meta is not None:
        fframes = []
        for day in sorted(fcnt):
            df = pd.DataFrame(fsum[day] / fcnt[day], columns=["total", "positive", "negative"])
            df.insert(0, "to_box", sec_meta[:, 2])
            df.insert(0, "from_box", sec_meta[:, 1])
            df.insert(0, "section", sec_meta[:, 0])
            df.insert(0, "date", day)
            fframes.append(df)
        pd.concat(fframes, ignore_index=True).to_parquet(
            out_dir / "flux_daily.parquet", index=False
        )
    else:
        pd.DataFrame(
            columns=["date", "section", "from_box", "to_box", "total", "positive", "negative"]
        ).to_parquet(out_dir / "flux_daily.parquet", index=False)
    mframes = []
    for day in sorted(mcnt):
        df = pd.DataFrame(msum[day] / mcnt[day], columns=list(bo.METEO_VARS))
        df.insert(0, "box", box_ids.astype(np.int32))
        df.insert(0, "date", day)
        mframes.append(df)
    (
        pd.concat(mframes, ignore_index=True)
        if mframes
        else pd.DataFrame(columns=["date", "box", *bo.METEO_VARS])
    ).to_parquet(out_dir / "meteo_daily.parquet", index=False)
    if hourly:
        stamps = np.repeat(
            np.array([s for s, _ in hourly_rows], dtype="datetime64[s]"), len(box_ids)
        )
        vals = np.vstack([v for _, v in hourly_rows])
        hdf = pd.DataFrame(vals, columns=list(bo.STATE_VARS))
        hdf.insert(0, "box", np.tile(box_ids.astype(np.int32), len(hourly_rows)))
        hdf.insert(0, "stamp", stamps)
        hdf.to_parquet(out_dir / "state_hourly.parquet", index=False, compression="zstd")
    run_log = None
    if (run_dir / LOG_FILE).is_file():
        run_log = dataclasses.asdict(bo.read_run_log(run_dir / LOG_FILE))
    sources = {}
    for name in (STATE_FILE, METEO_FILE, STATS_FILE, GEOM_FILE, LOG_FILE):
        p = run_dir / name
        if p.is_file():
            st = p.stat()
            sources[name] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    meta = {
        "schema": 1,
        "built_at": _now(),
        "hourly": hourly,
        "records": n,
        "period": {"start": stats.start.isoformat(), "end": stats.end.isoformat()},
        "step_seconds": stats.idtbox_seconds,
        "boxes": stats.boxes[["box", "area", "volume", "depth"]].to_dict(orient="records"),
        "sections": stats.sections[["section", "from_box", "to_box"]].to_dict(orient="records"),
        "section_nodes": {str(k): [[x, y] for x, y in v] for k, v in stats.section_nodes.items()},
        "element_box": (geom[["element", "box"]].values.tolist() if geom is not None else None),
        "run_log": run_log,
        "sources": sources,
    }
    _atomic_json(out_dir / "meta.json", meta)
    prog.write("done", exit_code=0)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shyfem_ui.boxmodel_cache_cli")
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trusted-base", action="append", required=True)
    ap.add_argument("--hourly", action="store_true")
    a = ap.parse_args(argv)
    run_dir, out_dir = Path(a.run), Path(a.out)
    err = _validate(run_dir, out_dir, [Path(b) for b in a.trusted_base])
    if err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    prog = _Progress(out_dir, 1)
    try:
        build(run_dir, out_dir, hourly=a.hourly)
        return 0
    except (bo.BoxOutputError, OSError, ValueError) as e:
        prog.write("error", error=str(e), exit_code=1)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Catch-all: progress.json must never be left stuck mid-phase, even for a
        # parser failure mode not in the tuple above (e.g. IndexError on a
        # truncated boxes_stats.txt). The traceback goes to stderr for the
        # parent's build.log; the short message goes to progress.json.
        prog.write("error", error=f"{type(e).__name__}: {e}", exit_code=1)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
