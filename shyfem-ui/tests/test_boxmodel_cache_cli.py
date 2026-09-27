import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from shyfem_ui import boxmodel_cache_cli as cli
from shyfem_ui import boxmodel_output as bo
from tests._boxmodel_fixture import flux_at, make_box_run, value_at


@pytest.fixture
def run(tmp_path):
    make_box_run(tmp_path / "run", days=3)
    return tmp_path / "run"


def _out(tmp_path):
    base = tmp_path / "users"
    proj = base / "alice" / "proj"
    out = proj / ".boxmodel_cache" / "fix.tmp-abc"
    out.mkdir(parents=True)
    return base, out


def test_build_daily_means_match_hand_computation(run, tmp_path):
    base, out = _out(tmp_path)
    meta = cli.build(run, out, hourly=False)
    daily = pd.read_parquet(out / "state_daily.parquet")
    # day 1 has records 01:00..23:00 (23 records); day 2 has 00:00 of day 2 + 01:00..23:00 (24)
    d1 = daily[(daily["date"] == date(2009, 1, 1)) & (daily["box"] == 2)].iloc[0]
    hours = range(1, 24)
    assert d1["temp"] == pytest.approx(
        sum(value_at("temp", 2, datetime(2009, 1, 1, h)) for h in hours) / 23
    )
    assert d1["salt_max"] == pytest.approx(value_at("salt", 2, datetime(2009, 1, 1, 23)))
    d2 = daily[(daily["date"] == date(2009, 1, 2)) & (daily["box"] == 2)].iloc[0]
    assert d2["temp"] == pytest.approx(
        sum(value_at("temp", 2, datetime(2009, 1, 2, h)) for h in range(24)) / 24
    )
    assert set(daily["date"].unique()) == {
        date(2009, 1, 1),
        date(2009, 1, 2),
        date(2009, 1, 3),
        date(2009, 1, 4),
    }
    assert meta["records"] == 72 and meta["period"] == {
        "start": "2009-01-01T00:00:00",
        "end": "2009-01-04T00:00:00",
    }


def test_flux_daily_keeps_split_sections_and_boundary(run, tmp_path):
    base, out = _out(tmp_path)
    cli.build(run, out, hourly=False)
    flux = pd.read_parquet(out / "flux_daily.parquet")
    row = flux[(flux["date"] == date(2009, 1, 2)) & (flux["section"] == 3)].iloc[0]
    exp = [flux_at(3, datetime(2009, 1, 2, h)) for h in range(24)]
    assert row["positive"] == pytest.approx(sum(p for _, p, _ in exp) / 24)
    assert row["total"] == pytest.approx(row["positive"] - row["negative"])
    assert (row["from_box"], row["to_box"]) == (2, 3)
    assert sorted(flux[flux["date"] == date(2009, 1, 2)]["section"].tolist()) == [1, 2, 3, 4]
    assert flux[flux["section"] == 4]["from_box"].iloc[0] == -1


def test_meteo_daily_and_meta_sources_are_relative(run, tmp_path):
    base, out = _out(tmp_path)
    meta = cli.build(run, out, hourly=True)
    meteo = pd.read_parquet(out / "meteo_daily.parquet")
    assert meteo[(meteo["date"] == date(2009, 1, 2)) & (meteo["box"] == 1)]["srad"].iloc[
        0
    ] == pytest.approx(100 + 11.5)
    assert set(meta["sources"]) == {
        "boxes_2d.txt",
        "boxes_meteo.txt",
        "boxes_stats.txt",
        "boxes_geom.txt",
        "run.log",
    }
    assert all("/" not in k for k in meta["sources"]) and meta["hourly"] is True
    hourly = pd.read_parquet(out / "state_hourly.parquet")
    assert len(hourly) == 72 * 3 and str(hourly["temp"].dtype) == "float32"
    hourly_table = pq.read_table(out / "state_hourly.parquet")
    assert hourly_table.schema.field("stamp").type == pa.timestamp("ms")
    assert hourly_table.schema.field("box").type == pa.int32()
    for v in bo.STATE_VARS:
        assert hourly_table.schema.field(v).type == pa.float32()
    assert hourly_table.num_rows == meta["records"] * len(meta["boxes"])
    assert meta["run_log"]["program_stop_time"] == "2009-01-04::00:00:00"
    assert meta["section_nodes"]["1"] == [[21.01, 55.5], [21.01, 55.51]]
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "done" and prog["exit"] == 0 and prog["records"] == 72


def test_cli_rejects_out_dir_outside_trusted_base(run, tmp_path):
    base, out = _out(tmp_path)
    rc = cli.main(
        ["--run", str(run), "--out", str(out), "--trusted-base", str(tmp_path / "elsewhere")]
    )
    assert rc == 2
    bad = tmp_path / "not_cache" / "x"
    bad.mkdir(parents=True)
    assert cli.main(["--run", str(run), "--out", str(bad), "--trusted-base", str(base)]) == 2


def test_cli_rejects_out_dir_bad_name_or_symlink(run, tmp_path):
    base, out = _out(tmp_path)
    # out dir name lacks the required "<run-id>.tmp-<token>" shape
    no_suffix = out.parent / "fix"
    no_suffix.mkdir()
    assert cli.main(["--run", str(run), "--out", str(no_suffix), "--trusted-base", str(base)]) == 2
    # out itself is a symlink into the same .boxmodel_cache directory
    real = out.parent / "fix.tmp-real"
    real.mkdir()
    link = out.parent / "fix.tmp-link"
    link.symlink_to(real)
    assert cli.main(["--run", str(run), "--out", str(link), "--trusted-base", str(base)]) == 2


def test_cli_rejects_symlinked_run_dir(run, tmp_path):
    base, out = _out(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(run)
    assert cli.main(["--run", str(link), "--out", str(out), "--trusted-base", str(base)]) == 2


def test_cli_end_to_end_as_subprocess_and_light_imports(run, tmp_path):
    base, out = _out(tmp_path)
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "shyfem_ui.boxmodel_cache_cli",
            "--run",
            str(run),
            "--out",
            str(out),
            "--trusted-base",
            str(base),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert (out / "meta.json").exists()
    # The real child path, not a monkeypatched one: the reaper's two inputs
    # must be in the file a genuine build leaves behind.
    final = json.loads((out / "progress.json").read_text())
    assert final["phase"] == "done" and final["exit"] == 0
    assert final["pid"] and final["pid"] != os.getpid(), "pid must be the CHILD's"
    assert datetime.fromisoformat(final["started"]) <= datetime.fromisoformat(final["updated"])
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, shyfem_ui.boxmodel_cache_cli; "
            "bad=[m for m in sys.modules if m.startswith(('shyfem_ui.db','shyfem_ui.services'))]; "
            "print(bad)",
        ],
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "[]", probe.stdout


def test_error_is_recorded_in_progress(run, tmp_path):
    base, out = _out(tmp_path)
    (run / "boxes_2d.txt").write_text("garbage\n")
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error" and "preamble" in prog["error"]


def test_truncated_stats_file_is_reported_by_name_not_as_an_indexerror(run, tmp_path):
    # Truncate boxes_stats.txt mid-table. This used to raise a bare IndexError
    # (lines[i - 1] past the end) that named neither the file nor the place;
    # review Important 2 made it a BoxOutputError naming the file, which is
    # what reaches progress.json and the page badge.
    base, out = _out(tmp_path)
    lines = (run / "boxes_stats.txt").read_text().splitlines()[:4]
    (run / "boxes_stats.txt").write_text("\n".join(lines) + "\n")
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error"
    assert prog["error"].startswith("boxes_stats.txt:"), prog["error"]
    assert "IndexError" not in prog["error"]
    assert prog["exit"] == 1


def test_error_is_recorded_in_progress_for_uncaught_exception_type(run, tmp_path, monkeypatch):
    # An exception type outside the (OSError, ValueError) tuple main()'s
    # specific except clause names must still leave progress.json in an
    # "error" phase (never stuck mid-phase) and return exit code 1.
    base, out = _out(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("something no parser models")

    monkeypatch.setattr(cli, "build", _boom)
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error"
    assert prog["error"] == "RuntimeError: something no parser models"
    assert prog["exit"] == 1


def test_meteo_daily_empty_has_contract_schema_when_meteo_file_absent(run, tmp_path):
    (run / "boxes_meteo.txt").unlink()
    base, out = _out(tmp_path)
    cli.build(run, out, hourly=False)
    table = pq.read_table(out / "meteo_daily.parquet")
    assert table.num_rows == 0
    assert table.schema.field("date").type == pa.date32()
    assert table.schema.field("box").type == pa.int32()
    for v in bo.METEO_VARS:
        assert table.schema.field(v).type == pa.float64()


def test_flux_daily_empty_has_contract_schema_when_no_sections(tmp_path, monkeypatch):
    # Patch the shared fixture module's SECTIONS list to empty before generating
    # a run, so every "# sections" block in boxes_2d.txt/boxes_stats.txt reports
    # count 0 (the fixture always emits the header + count line, just with zero
    # data rows when SECTIONS is empty -- both files stay parseable).
    monkeypatch.setattr("tests._boxmodel_fixture.SECTIONS", [])
    run_dir = tmp_path / "run_nosec"
    make_box_run(run_dir, days=1)
    base, out = _out(tmp_path)
    cli.build(run_dir, out, hourly=False)
    table = pq.read_table(out / "flux_daily.parquet")
    assert table.num_rows == 0
    assert table.schema.field("date").type == pa.date32()
    for c in ("section", "from_box", "to_box"):
        assert table.schema.field(c).type == pa.int32()
    for c in ("total", "positive", "negative"):
        assert table.schema.field(c).type == pa.float64()


def test_section_table_change_mid_run_is_rejected(run, tmp_path):
    base, out = _out(tmp_path)
    lines = (run / "boxes_2d.txt").read_text().splitlines()
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "# time record"]
    assert len(marks) >= 2
    start = marks[1]  # second "# time record" block == record 2
    hdr = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("# section"))
    sec_line = hdr + 1  # first section data row in record 2
    parts = lines[sec_line].split()
    parts[1] = "99"  # corrupt the "from" box of section 1
    lines[sec_line] = " ".join(parts)
    (run / "boxes_2d.txt").write_text("\n".join(lines) + "\n")
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error" and "section table changed" in prog["error"]
    # record 1 completed before record 2 raised: the shared _Progress object
    # (build() now takes main()'s prog instead of creating its own) must
    # report the real count reached, not the 0 a fresh throwaway object would
    # show since n=1 never hit the every-500 periodic update.
    assert prog["records"] == 1


def test_meteo_loop_and_write_phase_keep_the_heartbeat_alive(run, tmp_path, monkeypatch):
    """Review Important 1 (CLI half): the meteo loop and the Parquet writes
    used to write no progress.json at all, so a build could stay silent for
    longer than LIVE_TMP_SECONDS and have its own tmp dir reconciled away.
    Every long-running phase must tick.
    """
    base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "RECORDS_PER_HEARTBEAT", 10)
    seen: list[tuple[str, int]] = []
    original = cli._Progress.write

    def spy(self, phase, **kw):
        original(self, phase, **kw)
        seen.append((phase, self.records))

    monkeypatch.setattr(cli._Progress, "write", spy)
    cli.build(run, out, hourly=False)

    phases = [p for p, _ in seen]
    # 72 state records / 10 per heartbeat
    assert phases.count("state") >= 7
    # 72 meteo records / 10 per heartbeat (plus the one entering the phase)
    assert phases.count("meteo") >= 7, phases
    # the write phase brackets each of the three Parquet tables
    assert phases.count("write") >= 4, phases
    assert phases[-1] == "done"
    # the meteo heartbeats must not move the badge's record count backwards
    records = [n for p, n in seen if p in ("meteo", "write")]
    assert records and all(n == 72 for n in records), seen


def test_progress_records_never_exceed_expected(run, tmp_path, monkeypatch):
    """Minor 4: ``expected`` is a size-based estimate, so a run of smaller
    records overshoots it and the page badge would read above 100%."""
    base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "BYTES_PER_STATE_RECORD_GUESS", 10**9)  # -> expected == 1
    cli.build(run, out, hourly=False)
    prog = json.loads((out / "progress.json").read_text())
    assert prog["records"] == 72
    assert prog["expected"] >= prog["records"], prog


def test_heartbeat_cadence_stays_well_inside_the_live_tmp_window():
    """The heartbeat is a liveness signal for the cache service's reaper, so
    the cadence must hold even with a pessimistic per-record cost.

    Bound: 50 ms per record. Real cost on the fixture is well under 1 ms
    (72 records parse in a few milliseconds), so this is ~100x headroom; the
    resulting interval must still stay far below LIVE_TMP_SECONDS. This test
    (not the CLI) imports the service -- the CLI itself must stay free of
    ``shyfem_ui.services``; see the light-imports probe above.
    """
    from shyfem_ui.services import boxmodel_cache as bc

    generous_seconds_per_record = 0.050
    interval = cli.RECORDS_PER_HEARTBEAT * generous_seconds_per_record
    assert interval < bc.LIVE_TMP_SECONDS / 3, (
        f"{cli.RECORDS_PER_HEARTBEAT} records x {generous_seconds_per_record}s = {interval}s "
        f"is not comfortably below LIVE_TMP_SECONDS={bc.LIVE_TMP_SECONDS}"
    )


def test_truncated_state_file_reaches_progress_as_a_named_parser_error(run, tmp_path):
    """Review Important 2, end to end: a state file that stops between two
    lines used to surface as ``RuntimeError: generator raised StopIteration``
    (PEP 479) in progress.json -- and therefore in the page's status badge.
    It must name the file and the record instead."""
    base, out = _out(tmp_path)
    path = run / "boxes_2d.txt"
    lines = path.read_text().splitlines()
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "# time record"]
    path.write_text("\n".join(lines[: marks[1] + 2]) + "\n")  # ends after record 2's time line

    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error" and prog["exit"] == 1
    assert prog["error"].startswith("boxes_2d.txt: record 2:"), prog["error"]
    assert "RuntimeError" not in prog["error"]


def test_hourly_writer_close_failure_fails_the_build_when_nothing_else_is_wrong(
    run, tmp_path, monkeypatch
):
    """A ParquetWriter.close() error on the success path must not be swallowed:
    the build must end in the error phase, never publish a truncated hourly file."""
    import pyarrow.parquet as pq

    calls = {"n": 0}

    def _boom(self, *a, **k):
        # Raise once: pyarrow's ParquetWriter.__del__ calls close() again, and a
        # second raise would only surface as an unraisable-exception warning.
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full while writing the footer")

    monkeypatch.setattr(pq.ParquetWriter, "close", _boom)
    base, out = _out(tmp_path)
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base), "--hourly"])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error"
    assert "footer" in (prog["error"] or "")
    assert not (out / "meta.json").exists()


def test_cli_source_imports_nothing_from_services():
    """Static complement of the runtime light-imports probe above: every
    import statement in the CLI (and in the shared root module it depends
    on) is checked, so a lazily executed ``from shyfem_ui.services import``
    hidden inside a function cannot slip past the probe."""
    import ast
    from pathlib import Path

    from shyfem_ui import boxmodel_common as bcm

    for mod in (cli, bcm):
        tree = ast.parse(Path(mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{mod.__name__}: relative import"
                module = node.module or ""
                assert not module.startswith("shyfem_ui.services"), module
                if module == "shyfem_ui":
                    for alias in node.names:
                        assert alias.name != "services", f"{mod.__name__}: services"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("shyfem_ui.services"), alias.name


def test_cli_uses_the_shared_helpers():
    from shyfem_ui import boxmodel_common as bcm

    assert cli.atomic_json is bcm.atomic_json
    assert cli.no_symlink_components is bcm.no_symlink_components
    for private in ("_atomic_json", "_no_symlink_components"):
        assert not hasattr(cli, private), private


# --- the liveness heartbeat thread ------------------------------------------
#
# Before the thread existed, ``progress.json`` was refreshed only every
# RECORDS_PER_HEARTBEAT records, so a single long step (a big Parquet write,
# the run.log tail) could stay quiet past LIVE_TMP_SECONDS and another
# worker's page-load reconcile would delete a HEALTHY build's own out dir.


def _wait_for_refresh(path, before, timeout=3.0):
    """True once ``path``'s mtime moves past ``before`` (a heartbeat landed)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.stat().st_mtime_ns > before:
            return True
        time.sleep(0.01)
    return False


def test_progress_json_carries_pid_and_a_fixed_start_stamp(tmp_path, monkeypatch):
    """``pid`` lets an operator tell "not beating because it died" from
    "beating"; ``started`` is the birth stamp the reaper's absolute age cap
    measures from, so NOTHING may move it -- neither a later write nor a
    heartbeat. If it moved, a hung child that still beats would be immortal
    and the cap would be decoration.

    The clock is monkeypatched because ``_now`` has one-second resolution: two
    real writes land in the same second, so a stamp that IS being rewritten
    still compares equal (this test was vacuous before the clock was pinned).
    """
    _base, out = _out(tmp_path)
    stamps = iter(f"2026-09-27T00:00:{n:02d}+00:00" for n in range(1, 40))
    monkeypatch.setattr(cli, "_now", lambda: next(stamps))

    prog = cli._Progress(out, 10)
    prog.write("state")
    first = json.loads((out / "progress.json").read_text())
    born = first["started"]
    assert born == "2026-09-27T00:00:01+00:00", "started is stamped at construction"

    prog.records = 5
    prog.write("write")
    second = json.loads((out / "progress.json").read_text())
    assert second["started"] == born, "a later write must not re-stamp started"
    assert second["updated"] != first["updated"], "updated must move"

    assert prog.touch() is True
    third = json.loads((out / "progress.json").read_text())
    assert third["started"] == born, "a heartbeat must not re-stamp started"
    assert third["updated"] != second["updated"], "a heartbeat must move updated"
    assert third["records"] == 5, "a heartbeat must not move the record count"
    assert first["pid"] == second["pid"] == third["pid"] == os.getpid()


def test_heartbeat_thread_refreshes_progress_while_one_step_runs_long(tmp_path, monkeypatch):
    _base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    pj = out / "progress.json"
    prog = cli._Progress(out, 100)
    prog.records = 7
    prog.write("state")
    before = pj.stat().st_mtime_ns
    prog.start_heartbeat()
    try:
        assert _wait_for_refresh(pj, before), "the heartbeat thread never refreshed progress.json"
    finally:
        prog.stop()
    payload = json.loads(pj.read_text())
    # A touch re-publishes the LAST payload: it must not reset the badge.
    assert payload["records"] == 7
    assert payload["phase"] == "state"
    assert payload["expected"] == 100


def test_stop_ends_the_heartbeat_thread(tmp_path, monkeypatch):
    _base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    pj = out / "progress.json"
    prog = cli._Progress(out, 1)
    prog.write("state")
    prog.start_heartbeat()
    try:
        assert _wait_for_refresh(pj, pj.stat().st_mtime_ns)
    finally:
        prog.stop()
    thread = prog._thread
    assert thread is not None and not thread.is_alive()
    quiet = pj.stat().st_mtime_ns
    time.sleep(0.1)
    assert pj.stat().st_mtime_ns == quiet, "progress.json moved after stop()"


def test_start_heartbeat_twice_starts_one_thread(tmp_path, monkeypatch):
    _base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    prog = cli._Progress(out, 1)
    prog.write("state")
    prog.start_heartbeat()
    first = prog._thread
    prog.start_heartbeat()
    try:
        assert prog._thread is first
    finally:
        prog.stop()


def test_touch_before_any_write_creates_nothing(tmp_path):
    """The thread can be started before the first real write; a touch with no
    payload to re-publish must not invent one (phase-less progress.json)."""
    _base, out = _out(tmp_path)
    prog = cli._Progress(out, 1)
    assert prog.touch() is False
    assert not (out / "progress.json").exists()


def test_touch_is_best_effort_when_the_out_dir_is_gone(tmp_path):
    """Between the child's last write and its exit the parent (or another
    worker's reconcile) can publish the directory away. A heartbeat must not
    turn that race into a crash."""
    _base, out = _out(tmp_path)
    prog = cli._Progress(out, 1)
    prog.write("state")
    shutil.rmtree(out)
    assert prog.touch() is False


def test_main_beats_through_a_long_build_and_stops_the_thread(run, tmp_path, monkeypatch):
    base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    seen = {}

    def slow_build(run_dir, out_dir, *, hourly=False, progress=None):
        pj = out_dir / "progress.json"
        progress.write("state")
        seen["refreshed"] = _wait_for_refresh(pj, pj.stat().st_mtime_ns)
        seen["thread"] = progress._thread
        progress.write("done", exit_code=0)
        return {}

    monkeypatch.setattr(cli, "build", slow_build)
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 0
    assert seen["refreshed"], "main() did not start the heartbeat around build()"
    assert not seen["thread"].is_alive(), "main() left the heartbeat thread running"


def test_main_stops_the_heartbeat_before_recording_an_error(run, tmp_path, monkeypatch):
    """The error write is the child's last word. If the thread were still
    beating it could re-publish the pre-error payload on top of it and the
    page would show a build stuck mid-phase instead of the failure."""
    base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    seen = {}

    def boom(run_dir, out_dir, *, hourly=False, progress=None):
        progress.write("state")
        seen["thread"] = progress._thread
        raise ValueError("no state file")

    monkeypatch.setattr(cli, "build", boom)
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    assert not seen["thread"].is_alive()
    payload = json.loads((out / "progress.json").read_text())
    assert payload["phase"] == "error" and payload["error"] == "no state file"
    time.sleep(0.1)
    assert json.loads((out / "progress.json").read_text())["phase"] == "error"


def test_one_failed_beat_does_not_end_liveness_for_the_rest_of_the_build(tmp_path, monkeypatch):
    """A single transient write error (ENOSPC, EIO, an NFS hiccup) must not
    retire the heartbeat thread. If it did, the build would fall back to the
    500-record cadence alone -- silently, since nothing reports a failed beat
    -- and the next long quiet step would be reaped by another worker: exactly
    the bug the thread exists to prevent.
    """
    _base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    pj = out / "progress.json"
    prog = cli._Progress(out, 1)
    prog.write("state")

    real_atomic_json = cli.atomic_json
    beats = {"n": 0}

    def flaky(path, payload):
        beats["n"] += 1
        if beats["n"] == 1:
            raise OSError("transient")
        return real_atomic_json(path, payload)

    monkeypatch.setattr(cli, "atomic_json", flaky)
    before = pj.stat().st_mtime_ns
    prog.start_heartbeat()
    try:
        assert _wait_for_refresh(pj, before), "the thread never recovered from one failed beat"
        assert prog._thread.is_alive()
    finally:
        prog.stop()


def test_a_beat_before_the_first_write_does_not_end_the_heartbeat(tmp_path, monkeypatch):
    """The thread starts before build()'s first write. A beat that finds no
    payload to re-publish has nothing to do -- and must keep the thread, or a
    future edit that does slow work before the first write would silently lose
    liveness for the whole build."""
    _base, out = _out(tmp_path)
    monkeypatch.setattr(cli, "HEARTBEAT_SECONDS", 0.02)
    pj = out / "progress.json"
    prog = cli._Progress(out, 1)
    prog.start_heartbeat()
    try:
        time.sleep(0.1)  # several payload-less beats
        assert prog._thread.is_alive()
        assert not pj.exists(), "a payload-less beat must not invent progress"
        prog.write("state")
        assert _wait_for_refresh(pj, pj.stat().st_mtime_ns), "liveness did not resume"
    finally:
        prog.stop()
