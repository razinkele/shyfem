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

``progress.json`` is rewritten every ``RECORDS_PER_HEARTBEAT`` records in
BOTH streaming loops and around every Parquet table write, because the
parent treats that file's mtime as this build's liveness signal (a page
load's ``reconcile_tmp_dirs`` removes a ``.tmp-*`` whose progress is older
than ``LIVE_TMP_SECONDS``). Only the state loop advances ``records``; the
meteo loop and the write phase merely refresh the timestamp, so the page
badge's ``records/expected`` stays monotone.

``--hourly`` streams ``state_hourly.parquet`` with a ``pyarrow.parquet.
ParquetWriter`` opened lazily on the first hourly record and flushed one
completed calendar day at a time, so peak memory is bounded by one day's
rows (not the whole run) -- see ``_write_hourly_batch``. ``flux_daily.
parquet`` and ``meteo_daily.parquet`` are always written through explicit
``pyarrow.Schema`` objects (``FLUX_DAILY_SCHEMA``, ``METEO_DAILY_SCHEMA``),
including the section-less / meteo-less empty case, so a downstream reader
never sees Arrow ``null``-typed columns.
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
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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
#: How often ``build()`` refreshes ``progress.json`` while streaming records.
#:
#: This is a LIVENESS signal, not just a progress one:
#: ``services/boxmodel_cache.reconcile_tmp_dirs`` (which any page load runs)
#: deletes a ``.tmp-*`` directory whose ``progress.json`` is older than
#: ``LIVE_TMP_SECONDS`` (90 s), so every loop in this module that can run for
#: a long time has to tick at least that often or risk having its own output
#: directory removed out from under it. At even a pessimistic 50 ms per
#: record this cadence writes every ~25 s -- see
#: ``test_heartbeat_cadence_stays_well_inside_the_live_tmp_window``.
RECORDS_PER_HEARTBEAT = 500
_OUT_NAME_RE = re.compile(r"^[a-z0-9_-]{1,64}\.tmp-[A-Za-z0-9_-]+$")

HOURLY_STATE_SCHEMA = pa.schema(
    [("stamp", pa.timestamp("ms")), ("box", pa.int32())]
    + [(v, pa.float32()) for v in bo.STATE_VARS]
)
FLUX_DAILY_SCHEMA = pa.schema(
    [
        ("date", pa.date32()),
        ("section", pa.int32()),
        ("from_box", pa.int32()),
        ("to_box", pa.int32()),
        ("total", pa.float64()),
        ("positive", pa.float64()),
        ("negative", pa.float64()),
    ]
)
METEO_DAILY_SCHEMA = pa.schema(
    [("date", pa.date32()), ("box", pa.int32())] + [(v, pa.float64()) for v in bo.METEO_VARS]
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _Progress:
    def __init__(self, out: Path, expected: int):
        self.path = out / "progress.json"
        self.expected = expected
        self.records = 0

    def write(self, phase: str, *, error: str | None = None, exit_code: int | None = None) -> None:
        # ``expected`` is only an estimate (state file size / a per-record
        # byte guess), so a run with smaller-than-guessed records overshoots
        # it. Clamp here, the one place every progress write goes through, so
        # the page badge's "records/expected" never reads above 100%.
        self.expected = max(self.expected, self.records)
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


def _day_accumulate(acc_sum, acc_cnt, acc_min, acc_max, day, values):
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


def _write_hourly_batch(
    writer: pq.ParquetWriter, stamps: list[datetime], values: list[np.ndarray], box_ids: np.ndarray
) -> None:
    """Write one calendar day's hourly rows as a single Table (bounds peak memory)."""
    ts = np.repeat(np.array(stamps, dtype="datetime64[ms]"), len(box_ids))
    vals = np.vstack(values)
    boxes = np.tile(box_ids.astype(np.int32), len(stamps))
    arrays = [pa.array(ts, type=pa.timestamp("ms")), pa.array(boxes, type=pa.int32())]
    for j in range(len(bo.STATE_VARS)):
        arrays.append(pa.array(vals[:, j], type=pa.float32()))
    writer.write_table(pa.Table.from_arrays(arrays, schema=HOURLY_STATE_SCHEMA))


def build(
    run_dir: Path,
    out_dir: Path,
    *,
    hourly: bool,
    progress_cb=None,
    progress: _Progress | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = max(1, os.path.getsize(run_dir / STATE_FILE) // BYTES_PER_STATE_RECORD_GUESS)
    prog = progress if progress is not None else _Progress(out_dir, expected)
    prog.expected = expected
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
    n = 0
    hourly_writer: pq.ParquetWriter | None = None
    hourly_day: date | None = None
    hourly_stamps: list[datetime] = []
    hourly_values: list[np.ndarray] = []
    try:
        for rec in bo.iter_state_records(run_dir / STATE_FILE):
            if box_ids is None:
                box_ids = rec.box_ids.copy()
            elif not np.array_equal(box_ids, rec.box_ids):
                raise bo.BoxOutputError(f"{STATE_FILE}: box ids change at record {n + 1}")
            day = rec.stamp.date()
            _day_accumulate(ssum, scnt, smin, smax, day, rec.values)
            if rec.sections.size:
                cur_sec_meta = rec.sections[:, :3].astype(int)
                if sec_meta is None:
                    sec_meta = cur_sec_meta
                elif not np.array_equal(sec_meta, cur_sec_meta):
                    raise bo.BoxOutputError(f"{STATE_FILE}: record {n + 1}: section table changed")
                f = fsum[day]
                if f is None:
                    fsum[day] = rec.sections[:, 3:].copy()
                    fcnt[day] = 1
                else:
                    f += rec.sections[:, 3:]
                    fcnt[day] += 1
            if hourly:
                if hourly_writer is None:
                    hourly_writer = pq.ParquetWriter(
                        str(out_dir / "state_hourly.parquet"),
                        HOURLY_STATE_SCHEMA,
                        compression="zstd",
                    )
                if hourly_day is None:
                    hourly_day = day
                elif day != hourly_day:
                    _write_hourly_batch(hourly_writer, hourly_stamps, hourly_values, box_ids)
                    hourly_stamps = []
                    hourly_values = []
                    hourly_day = day
                hourly_stamps.append(rec.stamp)
                hourly_values.append(rec.values.astype(np.float32))
            n += 1
            if n % RECORDS_PER_HEARTBEAT == 0:
                prog.records = n
                prog.write("state")
                if progress_cb:
                    progress_cb(n, expected)
        if n == 0:
            raise bo.BoxOutputError(f"{STATE_FILE}: no records")
        if hourly and hourly_stamps:
            _write_hourly_batch(hourly_writer, hourly_stamps, hourly_values, box_ids)
    finally:
        # Runs on both the success path and every exception path (box-id
        # mismatch, section-table mismatch, no-records) so a caught error
        # always reports the real record count reached so far, not whatever
        # prog.records last held from the periodic heartbeat update.
        prog.records = n
        # Capture this BEFORE close(): inside the except below, sys.exc_info()
        # would describe the close error, not the error being propagated.
        propagating = sys.exc_info()[0] is not None
        if hourly_writer is not None:
            try:
                hourly_writer.close()
            except Exception:  # noqa: BLE001 - must not mask an in-flight exception
                if not propagating:
                    # Nothing else is failing: a half-written hourly file must
                    # fail the build loudly, not publish as "ready".
                    raise
                # This ``finally`` also runs while a parser error is
                # propagating; letting a close() failure out here would
                # replace that error (the one that says what is actually
                # wrong with the run) with an Arrow/OS error about the
                # half-written hourly file.
                # stderr is this child's log: the parent tees it to build.log.
                hourly_path = out_dir / "state_hourly.parquet"
                print(f"warning: could not close {hourly_path}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
    # ---- meteo ----------------------------------------------------------------
    prog.write("meteo")
    msum: dict = defaultdict(lambda: None)
    mcnt: dict = {}
    if (run_dir / METEO_FILE).is_file():
        nm = 0
        for rec in bo.iter_meteo_records(run_dir / METEO_FILE):
            day = rec.stamp.date()
            m = msum[day]
            if m is None:
                msum[day] = rec.values.copy()
                mcnt[day] = 1
            else:
                m += rec.values
                mcnt[day] += 1
            nm += 1
            if nm % RECORDS_PER_HEARTBEAT == 0:
                # Heartbeat only: deliberately does NOT touch prog.records,
                # which stays on the state count so the page badge's
                # records/expected never jumps backwards when the meteo file
                # (a second, independently long stream) starts from zero.
                prog.write("meteo")
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
    prog.write("write")
    state_daily.to_parquet(out_dir / "state_daily.parquet", index=False)
    prog.write("write")
    if sec_meta is not None:
        fframes = []
        for day in sorted(fcnt):
            df = pd.DataFrame(fsum[day] / fcnt[day], columns=["total", "positive", "negative"])
            df.insert(0, "to_box", sec_meta[:, 2])
            df.insert(0, "from_box", sec_meta[:, 1])
            df.insert(0, "section", sec_meta[:, 0])
            df.insert(0, "date", day)
            fframes.append(df)
        flux_table = pa.Table.from_pandas(
            pd.concat(fframes, ignore_index=True), schema=FLUX_DAILY_SCHEMA, preserve_index=False
        )
    else:
        flux_table = pa.Table.from_pylist([], schema=FLUX_DAILY_SCHEMA)
    pq.write_table(flux_table, out_dir / "flux_daily.parquet")
    prog.write("write")
    mframes = []
    for day in sorted(mcnt):
        df = pd.DataFrame(msum[day] / mcnt[day], columns=list(bo.METEO_VARS))
        df.insert(0, "box", box_ids.astype(np.int32))
        df.insert(0, "date", day)
        mframes.append(df)
    if mframes:
        meteo_table = pa.Table.from_pandas(
            pd.concat(mframes, ignore_index=True), schema=METEO_DAILY_SCHEMA, preserve_index=False
        )
    else:
        meteo_table = pa.Table.from_pylist([], schema=METEO_DAILY_SCHEMA)
    pq.write_table(meteo_table, out_dir / "meteo_daily.parquet")
    prog.write("write")
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
        # bo.BoxOutputError is a ValueError subclass, so it's covered below.
        build(run_dir, out_dir, hourly=a.hourly, progress=prog)
        return 0
    except (OSError, ValueError) as e:
        prog.write("error", error=str(e), exit_code=1)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Catch-all: progress.json must never be left stuck mid-phase, even for
        # a failure not in the tuple above -- a bug in the parser itself, a
        # MemoryError on a huge run, an Arrow error from pyarrow. (Every
        # *parser* failure is a BoxOutputError, hence a ValueError, and so is
        # already covered by the clause above.) The traceback goes to stderr
        # for the parent's build.log; the short message goes to progress.json.
        prog.write("error", error=f"{type(e).__name__}: {e}", exit_code=1)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
