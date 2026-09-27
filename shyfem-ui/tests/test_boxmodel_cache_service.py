"""Tests for the box-model cache service (spec sec6): status detection, the
per-worker build registry, child-process builds, cancel, two-step publish,
reconciliation, and loading a published cache into DataFrames.

Ruling 4: ``Config.analysis_roots`` rejects anything under ``/tmp``, and
pytest's ``tmp_path`` lives there, so the ``env`` fixture (the only fixture
that constructs a server-mode ``Config`` with ``analysis_roots``) builds its
whole tree under the conftest ``outside_tmp_dir`` fixture instead. Tests that
never touch ``analysis_roots`` (paths/publish/reconcile) keep plain
``tmp_path`` unchanged, exactly as the brief wrote them.

Async pattern: pytest-asyncio is not used here (the project's convention,
see test_lgr_service.py). ``asyncio.run()`` always creates a fresh event loop
and cancels every still-pending task on that loop before returning (verified
empirically -- a bare ``asyncio.run(start_build(...))`` followed by a second,
separate ``asyncio.run(_wait(h))`` silently cancels the background build
task at the *first* call's shutdown, orphaning the child process). Every test
that starts a build therefore performs the start + wait (+ any further
awaited calls) inside a single ``async def go(): ...`` coroutine run through
one ``asyncio.run(go())`` call, matching the pattern the brief itself already
used in ``test_registry_dedupes_and_limits`` and ``test_cancel_removes_tmp``.
"""

import asyncio
import json
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from shyfem_ui.config import Config
from shyfem_ui.services import boxmodel_cache as bc
from tests._boxmodel_fixture import make_box_project, make_box_run


@pytest.fixture
def env(outside_tmp_dir):
    tmp_path = outside_tmp_dir
    udr = tmp_path / "users"
    wd = tmp_path / "projects"
    udr.mkdir()
    wd.mkdir()
    root = tmp_path / "data"
    run = root / "runs" / "fix"
    make_box_run(run, days=2)
    proj = make_box_project(udr / "alice" / "proj", run)
    cfg = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=tmp_path / "shyfem",
        database_url=f"sqlite:///{tmp_path / 'db' / 'ui.db'}",
        analysis_roots=[str(root)],
    )
    user = {"id": 1, "username": "alice", "role": "user"}
    project = {"id": 7, "name": "proj", "work_dir": str(proj)}
    return cfg, user, project, run


def test_cache_paths(tmp_path):
    assert bc.cache_dir_for(tmp_path, "fix") == tmp_path / ".boxmodel_cache" / "fix"


def test_status_missing_then_ready_then_stale(env, monkeypatch):
    cfg, user, project, run = env
    wd = Path(project["work_dir"])
    assert bc.cache_status(wd, "fix", run, None).state == "missing"
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)

    asyncio.run(go())
    st = bc.cache_status(wd, "fix", run, reg)
    assert st.state == "ready" and st.meta["records"] == 48
    (run / "boxes_2d.txt").write_text((run / "boxes_2d.txt").read_text() + "\n")
    assert bc.cache_status(wd, "fix", run, reg).state == "stale"


async def _wait(h, timeout=60):
    if h.task is not None:
        await asyncio.wait_for(h.task, timeout)


def test_editor_gate_blocks_build(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: "nope"
    )
    with pytest.raises(PermissionError, match="nope"):
        asyncio.run(
            bc.start_build(
                bc.BuildRegistry(),
                project=project,
                run_id="fix",
                run_dir=run,
                user=user,
                config=cfg,
            )
        )


def test_run_dir_must_be_confined(env, monkeypatch, tmp_path):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    # confine_path's N44 branch (reached because `outside` is not under any
    # allowed root) would otherwise query the shared-project-permission table
    # via the global session factory; the suite's global test DB is
    # deliberately left uninitialised, so keep the rejection coming from the
    # roots check alone (same fix as test_boxmodel_manifest.py commit 167a8fc1).
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.accessible_shared_work_dirs",
        lambda user, session_factory=None: [],
    )
    outside = tmp_path / "outside"
    make_box_run(outside, days=1)
    with pytest.raises(ValueError):
        asyncio.run(
            bc.start_build(
                bc.BuildRegistry(),
                project=project,
                run_id="fix",
                run_dir=outside,
                user=user,
                config=cfg,
            )
        )


def test_publish_over_existing_cache_and_old_cleanup(tmp_path):
    root = tmp_path / ".boxmodel_cache"
    root.mkdir()
    old = root / "fix"
    old.mkdir()
    (old / "meta.json").write_text("{}")
    (old / "x.parquet").write_text("old")
    tmp = root / "fix.tmp-abc"
    tmp.mkdir()
    (tmp / "meta.json").write_text('{"schema":1}')
    (tmp / "progress.json").write_text(json.dumps({"phase": "done", "exit": 0}))
    out = bc.publish(tmp, "fix")
    assert (
        out == old
        and (old / "meta.json").read_text() == '{"schema":1}'
        and not (old / "x.parquet").exists()
    )
    assert not list(root.glob("fix.old-*")) and not tmp.exists()


def test_publish_called_twice_on_same_tmp_dir_does_not_destroy_the_cache(tmp_path):
    """Critical 1: reachable in production -- this worker's own _run_build
    publishes at the end of a build at the same moment another session's
    page-load reconcile_tmp_dirs has already listed that same finished tmp
    dir (from an earlier directory scan) and calls publish on it too. The
    second call must be a safe no-op, not destroy the published cache.
    """
    root = tmp_path / ".boxmodel_cache"
    root.mkdir()
    tmp = root / "fix.tmp-abc"
    tmp.mkdir()
    (tmp / "meta.json").write_text('{"schema":1}')
    (tmp / "state_daily.parquet").write_text("data")

    out1 = bc.publish(tmp, "fix")
    assert out1 == root / "fix"
    assert (root / "fix" / "meta.json").read_text() == '{"schema":1}'
    assert (root / "fix" / "state_daily.parquet").read_text() == "data"

    out2 = bc.publish(tmp, "fix")
    assert out2 == root / "fix"
    assert (root / "fix").is_dir()
    assert (root / "fix" / "meta.json").read_text() == '{"schema":1}'
    assert (root / "fix" / "state_daily.parquet").read_text() == "data"
    assert not list(root.glob("fix.old-*"))


def test_reconcile_publishes_finished_and_removes_dead_tmp(tmp_path):
    wd = tmp_path
    root = wd / ".boxmodel_cache"
    root.mkdir()
    fin = root / "a.tmp-1"
    fin.mkdir()
    (fin / "meta.json").write_text("{}")
    (fin / "progress.json").write_text(json.dumps({"phase": "done", "exit": 0}))
    dead = root / "b.tmp-2"
    dead.mkdir()
    (dead / "progress.json").write_text(json.dumps({"phase": "state", "exit": None}))
    old_t = time.time() - 10 * bc.LIVE_TMP_SECONDS
    os.utime(dead / "progress.json", (old_t, old_t))
    stray = root / "c.old-3"
    stray.mkdir()
    msgs = bc.reconcile_tmp_dirs(wd)
    assert (root / "a").exists() and not dead.exists() and not stray.exists() and len(msgs) == 3


def test_clear_stale_keeps_fresh_empty_tmp_removes_old_empty_tmp(tmp_path):
    """Important 3: a tmp dir freshly created by start_build (queued behind
    the per-worker cap) has no progress.json yet -- its own mtime, not the
    1e9 "infinitely old" sentinel, must decide whether it looks dead.
    """
    root = tmp_path / ".boxmodel_cache"
    root.mkdir()
    fresh = root / "fix.tmp-fresh"
    fresh.mkdir()  # empty: no progress.json yet, mtime is "now"
    old = root / "fix.tmp-old"
    old.mkdir()
    old_t = time.time() - 2 * bc.LIVE_TMP_SECONDS
    os.utime(old, (old_t, old_t))

    bc._clear_stale_tmp_dirs(root, "fix")
    assert fresh.exists() and not old.exists()


def test_reconcile_keeps_fresh_empty_tmp_removes_old_empty_tmp(tmp_path):
    root = tmp_path / ".boxmodel_cache"
    root.mkdir()
    fresh = root / "fix.tmp-fresh"
    fresh.mkdir()
    old = root / "fix.tmp-old"
    old.mkdir()
    old_t = time.time() - 2 * bc.LIVE_TMP_SECONDS
    os.utime(old, (old_t, old_t))

    bc.reconcile_tmp_dirs(tmp_path)
    assert fresh.exists() and not old.exists()


def test_registry_dedupes_and_limits(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    monkeypatch.setattr(bc, "MAX_BUILDS_PER_USER", 1)
    reg = bc.BuildRegistry()

    async def go():
        h1 = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        h2 = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        assert h1 is h2
        with pytest.raises(RuntimeError, match="one build"):
            await bc.start_build(
                reg, project=project, run_id="other", run_dir=run, user=user, config=cfg
            )
        await _wait(h1)
        assert h1.state == "done"

    asyncio.run(go())


def test_cancel_removes_tmp(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        ok = await bc.cancel_build(reg, h.key, project=project, user=user)
        assert ok and h.state in ("cancelled", "done")
        await asyncio.sleep(0.5)
        assert not h.tmp_dir.exists() or h.state == "done"

    asyncio.run(go())


def test_load_cache(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)

    asyncio.run(go())
    cr = bc.load_cache(bc.cache_dir_for(Path(project["work_dir"]), "fix"), "fix")
    assert cr.run_id == "fix" and str(cr.state_daily["date"].dtype).startswith("datetime64")
    assert set(cr.state_daily["box"]) == {1, 2, 3} and cr.state_hourly is None
    assert cr.meta["period"]["start"] == "2009-01-01T00:00:00"


def test_load_cache_state_reads_only_state_daily(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)

    asyncio.run(go())
    cr = bc.load_cache_state(bc.cache_dir_for(Path(project["work_dir"]), "fix"), "fix")
    # state_daily present (used by the multi-run skill comparison) ...
    assert cr.run_id == "fix" and set(cr.state_daily["box"]) == {1, 2, 3}
    assert str(cr.state_daily["date"].dtype).startswith("datetime64")
    # ... while the large frames are left empty to keep loading every run cheap.
    assert cr.flux_daily.empty and cr.meteo_daily.empty and cr.state_hourly is None
    assert cr.meta["period"]["start"] == "2009-01-01T00:00:00"


# --- Controller ruling on concern 1 (stale-error-shadows-success) ----------


def test_status_failed_build_does_not_shadow_later_success(env, monkeypatch):
    """cache_status precedence: a published, up-to-date cache always wins over
    an old error tmp dir left by a previous failed build for the same run_id.
    """
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    wd = Path(project["work_dir"])
    reg = bc.BuildRegistry()
    stats_path = run / "boxes_stats.txt"
    good_stats = stats_path.read_text()
    # Corrupt an input the CLI parses early -- confirmed empirically to make
    # the real CLI exit 1 with progress.json phase="error" (error: "boxes_
    # stats.txt: truncated preamble"), and no meta.json, so the tmp dir is
    # kept around (see _run_build's failed branch).
    stats_path.write_text("garbage, not a stats file\n")

    async def build_once():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)
        return h

    h1 = asyncio.run(build_once())
    assert h1.state == "failed"
    st1 = bc.cache_status(wd, "fix", run, reg)
    assert st1.state == "failed" and "boxes_stats.txt" in st1.message

    stats_path.write_text(good_stats)
    h2 = asyncio.run(build_once())
    assert h2.state == "done"
    st2 = bc.cache_status(wd, "fix", run, reg)
    assert st2.state == "ready"
    # start_build (inside build_once's second call) cleared h1's error tmp
    # dir before spawning its own -- nothing named "fix.tmp-*" survives a
    # successful publish.
    assert not list(bc.cache_root(wd).glob("fix.tmp-*"))


def test_start_build_clears_dead_and_error_tmp_but_not_live(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    wd = Path(project["work_dir"])
    root = bc.cache_root(wd)
    root.mkdir(parents=True, exist_ok=True)

    dead = root / "fix.tmp-dead"
    dead.mkdir()
    (dead / "progress.json").write_text(json.dumps({"phase": "state", "exit": None}))
    old_t = time.time() - 2 * bc.LIVE_TMP_SECONDS
    os.utime(dead / "progress.json", (old_t, old_t))

    errored = root / "fix.tmp-err"
    errored.mkdir()
    (errored / "progress.json").write_text(json.dumps({"phase": "error", "exit": 1}))

    live = root / "fix.tmp-live"
    live.mkdir()
    (live / "progress.json").write_text(json.dumps({"phase": "state", "exit": None}))
    # fresh mtime (just written) -- simulates another worker's in-flight build

    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)

    asyncio.run(go())

    assert not dead.exists()
    assert not errored.exists()
    assert live.exists()


# --- Review round 1 findings ------------------------------------------------


def test_run_build_survives_publish_raising(env, monkeypatch):
    """Important 2: publish() raising after a real, successful CLI run must
    not wedge the handle in "building" forever -- it must end "failed", be
    popped from the registry, and never block a fresh build for the same key.
    """
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    real_publish = bc.publish
    state = {"raise": True}

    def flaky_publish(tmp_dir, run_id):
        if state["raise"]:
            raise RuntimeError("boom")
        return real_publish(tmp_dir, run_id)

    monkeypatch.setattr(bc, "publish", flaky_publish)
    reg = bc.BuildRegistry()

    async def build_once():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)
        return h

    h1 = asyncio.run(build_once())
    assert h1.state == "failed"
    assert reg.get(h1.key) is None
    prog = bc._read_json(h1.tmp_dir / "progress.json")
    assert prog is not None and prog.get("phase") == "error" and "boom" in prog.get("error", "")

    state["raise"] = False
    h2 = asyncio.run(build_once())
    assert h2.state == "done" and h2 is not h1
    assert bc.cache_status(Path(project["work_dir"]), "fix", run, reg).state == "ready"


def test_cancel_task_while_queued_behind_worker_cap(env, monkeypatch):
    """Important 2 follow-up: a build's own asyncio task can be cancelled
    directly (e.g. asyncio.run's own task-cancellation on loop teardown, or
    a real server shutdown) while it is still queued behind
    MAX_BUILDS_PER_WORKER, i.e. still awaiting registry.semaphore()'s
    __aenter__ -- BEFORE the try/finally that normally guarantees a
    terminal state and a registry pop has even been entered. The semaphore
    acquisition must sit INSIDE the try for this to be caught at all;
    otherwise the handle stays "queued" forever and is never popped.
    """
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    monkeypatch.setattr(bc, "MAX_BUILDS_PER_WORKER", 1)
    monkeypatch.setattr(bc, "MAX_BUILDS_PER_USER", 2)  # both builds are alice's
    other = run.parent / "other"
    make_box_run(other, days=1)
    reg = bc.BuildRegistry()

    async def go():
        h1 = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        h2 = await bc.start_build(
            reg, project=project, run_id="other", run_dir=other, user=user, config=cfg
        )
        # Give the loop a few cycles so h1's task actually acquires the
        # (uncontended) semaphore first and h2's task genuinely parks on it.
        for _ in range(50):
            await asyncio.sleep(0.01)
            if h1.state == "building":
                break
        assert h1.state == "building"
        assert h2.state == "queued"

        h2.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await h2.task
        assert h2.state == "cancelled"
        assert reg.get(h2.key) is None
        assert not h2.tmp_dir.exists()

        await _wait(h1)
        assert h1.state == "done"

    asyncio.run(go())


def test_run_id_must_be_a_safe_slug(env, monkeypatch):
    """Important 4: run_id reaches glob()/mkdir() unvalidated otherwise -- a
    run_id of "../../victim" must be rejected before any filesystem access.
    """
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    wd = Path(project["work_dir"])

    with pytest.raises(ValueError, match="run_id"):
        asyncio.run(
            bc.start_build(
                bc.BuildRegistry(),
                project=project,
                run_id="../../victim",
                run_dir=run,
                user=user,
                config=cfg,
            )
        )
    with pytest.raises(ValueError, match="run_id"):
        bc.cache_status(wd, "../../victim", run, None)
    with pytest.raises(ValueError, match="run_id"):
        bc.cache_dir_for(wd, "../../victim")
    with pytest.raises(ValueError, match="run_id"):
        bc._clear_stale_tmp_dirs(bc.cache_root(wd), "../../victim")

    # start_build validated run_id before touching the filesystem at all --
    # nothing was created anywhere, not even the cache root itself.
    assert not bc.cache_root(wd).exists()


# --- Controller ruling on concern 3 (real-child concurrency) ---------------
#
# Measured with a standalone timing script (make_box_run + the real CLI,
# same box count as the fixture default): days=400 -> fixture generation
# ~0.7s, CLI parse+write ~2.6s (days=200 -> ~1.6s, days=800 -> ~4.9s). 400
# days gives several seconds of "state"-phase parsing to interrupt while
# keeping each test's wall time well under the ~10s budget.
_BIG_DAYS = 400


async def _wait_for_phase(tmp_dir: Path, phase: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        prog = bc._read_json(tmp_dir / "progress.json")
        if prog and prog.get("phase") == phase:
            return prog
        await asyncio.sleep(0.02)
    raise AssertionError(f"progress.json never reached phase={phase!r} within {timeout}s")


def _kill_process_group_if_alive(pid: int | None) -> None:
    """Best-effort cleanup for the real-child tests below: a failed
    assertion inside ``go()`` must never leave an orphaned
    boxmodel_cache_cli process behind.
    """
    if pid is None:
        return
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def test_cancel_mid_run_kills_real_child(env, monkeypatch):
    cfg, user, project, run = env
    big = run.parent / "big"
    make_box_run(big, days=_BIG_DAYS)
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()
    h_box: list = [None]

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="big", run_dir=big, user=user, config=cfg
        )
        h_box[0] = h
        await _wait_for_phase(h.tmp_dir, "state")
        pid = h.pid
        assert pid is not None
        ok = await bc.cancel_build(reg, h.key, project=project, user=user)
        assert ok
        assert h.state == "cancelled"
        # _run_build's own tmp-dir cleanup runs concurrently (triggered once
        # _terminate's SIGTERM makes the child's proc.wait() resolve), so give
        # it a short grace period rather than asserting immediately.
        for _ in range(60):  # up to ~3s
            if not h.tmp_dir.exists():
                break
            await asyncio.sleep(0.05)
        assert not h.tmp_dir.exists()
        return pid

    try:
        pid = asyncio.run(go())
    finally:
        if h_box[0] is not None:
            _kill_process_group_if_alive(h_box[0].pid)

    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_timeout_marks_failed_with_timeout_message(env, monkeypatch):
    cfg, user, project, run = env
    big = run.parent / "big2"
    make_box_run(big, days=_BIG_DAYS)
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    cfg.command_timeout_seconds = 1
    reg = bc.BuildRegistry()
    h_box: list = [None]

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="big2", run_dir=big, user=user, config=cfg
        )
        h_box[0] = h
        await _wait(h, timeout=15)
        return h

    try:
        h = asyncio.run(go())
    finally:
        if h_box[0] is not None:
            _kill_process_group_if_alive(h_box[0].pid)

    assert h.state == "failed"
    # Design choice: on a timeout the tmp dir is kept (not deleted) and its
    # progress.json is overwritten to an error phase naming the timeout --
    # the child never gets a chance to write its own error phase (it is
    # killed from the outside), so without this the tmp dir would either
    # vanish silently or freeze on its last "state"-phase snapshot with no
    # indication of *why* the build stopped. This matches the visibility
    # already given to a genuine CLI failure (test_status_failed_build_...
    # above) rather than introducing a second, silent failure mode.
    prog = bc._read_json(h.tmp_dir / "progress.json")
    assert prog is not None and prog.get("phase") == "error"
    assert "timed out" in (prog.get("error") or "").lower()
    st = bc.cache_status(Path(project["work_dir"]), "big2", big, None)
    assert st.state == "failed" and "timed out" in st.message.lower()
    with pytest.raises(ProcessLookupError):
        os.kill(h.pid, 0)


def _stale_tmp(root: Path, name: str) -> Path:
    """A ``.tmp-*`` directory whose liveness signal is far older than the cap."""
    tmp = root / name
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "progress.json").write_text(json.dumps({"phase": "state", "exit": None}))
    old_t = time.time() - 10 * bc.LIVE_TMP_SECONDS
    os.utime(tmp / "progress.json", (old_t, old_t))
    os.utime(tmp, (old_t, old_t))
    return tmp


def test_reconcile_keeps_a_tmp_dir_whose_build_is_live_in_this_registry(tmp_path):
    """Review Important 1: every page load runs reconcile_tmp_dirs, and the
    age rule alone cannot tell "abandoned" from "busy". A build in THIS
    worker that has not written progress.json for longer than
    LIVE_TMP_SECONDS (slow disk, long Parquet write, a phase with no
    heartbeat) would have its own output directory deleted underneath it.
    A live registry handle for (project_id, run_id) must veto the removal.
    """
    root = bc.cache_root(tmp_path)
    tmp = _stale_tmp(root, "fix.tmp-x")

    reg = bc.BuildRegistry()
    reg.put(bc.BuildHandle(key=(7, "fix"), owner_id=1, tmp_dir=tmp, state="building"))

    msgs = bc.reconcile_tmp_dirs(tmp_path, registry=reg, project_id=7)
    assert tmp.is_dir(), "a live build's tmp dir must survive a page-load reconcile"
    assert msgs == []

    # ... and the age rule still applies to everything the registry does not
    # claim: same directory, no handle -> removed.
    assert bc.reconcile_tmp_dirs(tmp_path) == ["removed dead fix.tmp-x"]
    assert not tmp.exists()


def test_reconcile_registry_veto_needs_both_registry_and_project_id(tmp_path):
    """Half the key is not a key: with only a registry (or only a project id)
    the function must fall back to the age rule rather than silently keeping
    -- or silently removing -- directories."""
    root = bc.cache_root(tmp_path)
    tmp = _stale_tmp(root, "fix.tmp-y")
    reg = bc.BuildRegistry()
    reg.put(bc.BuildHandle(key=(7, "fix"), owner_id=1, tmp_dir=tmp, state="building"))

    assert bc.reconcile_tmp_dirs(tmp_path, registry=reg) == ["removed dead fix.tmp-y"]
    assert not tmp.exists()


def test_reconcile_registry_veto_ignores_a_finished_handle(tmp_path):
    """``BuildRegistry.get`` only returns queued/building handles, so a
    handle left in a terminal state must not keep a dead directory alive."""
    root = bc.cache_root(tmp_path)
    tmp = _stale_tmp(root, "fix.tmp-z")
    reg = bc.BuildRegistry()
    reg.put(bc.BuildHandle(key=(7, "fix"), owner_id=1, tmp_dir=tmp, state="done"))

    assert bc.reconcile_tmp_dirs(tmp_path, registry=reg, project_id=7) == ["removed dead fix.tmp-z"]
    assert not tmp.exists()


def test_reconcile_leaves_a_live_builds_finished_dir_to_its_own_publish(tmp_path):
    """A finished-but-unpublished tmp dir whose handle is still live belongs
    to ``_run_build``: reconcile must not race it into ``publish``."""
    root = bc.cache_root(tmp_path)
    tmp = root / "fix.tmp-w"
    tmp.mkdir(parents=True)
    (tmp / "meta.json").write_text("{}")
    (tmp / "progress.json").write_text(json.dumps({"phase": "done", "exit": 0}))
    reg = bc.BuildRegistry()
    reg.put(bc.BuildHandle(key=(7, "fix"), owner_id=1, tmp_dir=tmp, state="building"))

    assert bc.reconcile_tmp_dirs(tmp_path, registry=reg, project_id=7) == []
    assert tmp.is_dir() and not (root / "fix").exists()

    # Without the handle the page load publishes it, exactly as before.
    assert bc.reconcile_tmp_dirs(tmp_path) == ["published fix"]
    assert (root / "fix" / "meta.json").is_file()


def test_get_registry_is_a_lazy_process_wide_singleton():
    """PR 2 follow-up: the service, not the page, owns the process-wide
    registry so every caller (page, tests, a future CLI status probe) shares
    the same handles and semaphore."""
    reg = bc.get_registry()
    assert isinstance(reg, bc.BuildRegistry)
    assert bc.get_registry() is reg
    # a hand-built registry is still a separate object (tests rely on that)
    assert bc.BuildRegistry() is not reg


def test_service_uses_the_shared_helpers():
    """The private copies moved to ``shyfem_ui.boxmodel_common``; the service
    must use them rather than keep a drifting duplicate."""
    from shyfem_ui import boxmodel_common as bcm

    assert bc.check_run_id is bcm.check_run_id
    assert bc.atomic_json is bcm.atomic_json
    for private in ("_RUN_ID_RE", "_check_run_id", "_atomic_json"):
        assert not hasattr(bc, private), private


# --- the absolute age cap ----------------------------------------------------
#
# The 90 s mtime window used to do two jobs: liveness AND hang detection. Now
# that the child beats progress.json from a daemon thread, a CRASHED child
# still stops beating (the thread dies with the process) but a HUNG one beats
# forever -- so age is measured a second way, from the ``started`` stamp the
# child writes once, which no heartbeat refreshes.


def _beating_tmp(root: Path, name: str, *, age_seconds: float, started: bool = True) -> Path:
    """A ``.tmp-*`` whose heartbeat is FRESH but whose build began long ago."""
    tmp = root / name
    tmp.mkdir(parents=True, exist_ok=True)
    payload = {"phase": "state", "records": 10, "exit": None, "pid": 4242}
    if started:
        begin = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        payload["started"] = begin.isoformat(timespec="seconds")
    (tmp / "progress.json").write_text(json.dumps(payload))
    return tmp


def test_a_tmp_dir_past_the_cap_is_dead_even_with_a_fresh_heartbeat(tmp_path):
    root = bc.cache_root(tmp_path)
    hung = _beating_tmp(root, "fix.tmp-hung", age_seconds=bc.HARD_TMP_AGE_FLOOR_SECONDS + 60)
    assert bc.reconcile_tmp_dirs(tmp_path) == ["removed dead fix.tmp-hung"]
    assert not hung.exists()


def test_a_long_but_within_cap_build_survives_the_reaper(tmp_path):
    """The control for the test above: the cap must be generous enough that a
    slow-but-healthy build is never reaped mid-flight."""
    root = bc.cache_root(tmp_path)
    busy = _beating_tmp(root, "fix.tmp-busy", age_seconds=bc.HARD_TMP_AGE_FLOOR_SECONDS / 2)
    assert bc.reconcile_tmp_dirs(tmp_path) == []
    assert busy.is_dir()


def test_the_cap_is_skipped_for_a_progress_file_with_no_start_stamp(tmp_path):
    """A foreign or pre-upgrade ``progress.json`` has no ``started``. Falling
    back to the mtime rule alone keeps the old behaviour rather than treating
    an unknown birth time as infinitely old."""
    root = bc.cache_root(tmp_path)
    old = _beating_tmp(root, "fix.tmp-nostamp", age_seconds=10 * 3600, started=False)
    assert bc.reconcile_tmp_dirs(tmp_path) == []
    assert old.is_dir()


def test_an_unparsable_start_stamp_does_not_reap_a_beating_build(tmp_path):
    root = bc.cache_root(tmp_path)
    tmp = _beating_tmp(root, "fix.tmp-junk", age_seconds=1)
    payload = json.loads((tmp / "progress.json").read_text())
    payload["started"] = "not a timestamp"
    (tmp / "progress.json").write_text(json.dumps(payload))
    assert bc.reconcile_tmp_dirs(tmp_path) == []
    assert tmp.is_dir()


def test_caller_supplied_cap_overrides_the_floor(tmp_path):
    root = bc.cache_root(tmp_path)
    tmp = _beating_tmp(root, "fix.tmp-short", age_seconds=120)
    assert bc.reconcile_tmp_dirs(tmp_path, max_tmp_age=60) == ["removed dead fix.tmp-short"]
    assert not tmp.exists()


def test_cache_status_does_not_report_a_capped_out_tmp_dir_as_building(tmp_path):
    """Precedence (b) reports another worker's live tmp dir as ``building``.
    A hung build beats forever, so without the cap the page would say "build
    in progress" for good -- including for a viewer, whose page load skips
    the reconcile that would otherwise remove the directory."""
    root = bc.cache_root(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _beating_tmp(root, "fix.tmp-hung", age_seconds=bc.HARD_TMP_AGE_FLOOR_SECONDS + 60)
    assert bc.cache_status(tmp_path, "fix", run_dir, None).state == "missing"
    _beating_tmp(root, "fix.tmp-busy", age_seconds=30)
    assert bc.cache_status(tmp_path, "fix", run_dir, None).state == "building"


def test_tmp_age_cap_seconds_rises_with_the_configured_build_timeout():
    """Sizing must not be two independent knobs: an operator who raises the
    subprocess timeout to bound a long build raises the cap with it, so the
    reaper can never judge a build dead before the parent would kill it."""
    assert bc.tmp_age_cap_seconds(None) == float(bc.HARD_TMP_AGE_FLOOR_SECONDS)
    assert bc.tmp_age_cap_seconds(0) == float(bc.HARD_TMP_AGE_FLOOR_SECONDS)
    generous = bc.HARD_TMP_AGE_FLOOR_SECONDS + 10_000
    assert bc.tmp_age_cap_seconds(generous) == generous + bc.TMP_AGE_MARGIN_SECONDS
    assert bc.tmp_age_cap_seconds(generous) > generous, "the cap must outlast the timeout"
    # A timeout below the floor never shrinks the cap.
    assert bc.tmp_age_cap_seconds(60) == float(bc.HARD_TMP_AGE_FLOOR_SECONDS)


def test_clear_stale_tmp_dirs_applies_the_cap_to_a_beating_build(tmp_path):
    """``start_build`` clears stale directories for the run it is about to
    build. A hung predecessor that is still beating must not shadow the new
    build's publish; a genuinely busy one (another worker) must survive."""
    root = bc.cache_root(tmp_path)
    hung = _beating_tmp(root, "fix.tmp-hung", age_seconds=bc.HARD_TMP_AGE_FLOOR_SECONDS + 60)
    busy = _beating_tmp(root, "fix.tmp-busy", age_seconds=30)
    bc._clear_stale_tmp_dirs(root, "fix")
    assert not hung.exists()
    assert busy.is_dir()


def test_clear_stale_tmp_dirs_honours_an_explicit_cap(tmp_path):
    """The cap argument must reach the decision, not just the signature: on a
    deployment whose configured build timeout exceeds the floor, start_build
    passes a wider cap and a foreign build inside it must survive."""
    root = bc.cache_root(tmp_path)
    doomed = _beating_tmp(root, "fix.tmp-old", age_seconds=120)
    bc._clear_stale_tmp_dirs(root, "fix", 60)
    assert not doomed.exists()

    spared = _beating_tmp(root, "fix.tmp-new", age_seconds=bc.HARD_TMP_AGE_FLOOR_SECONDS + 600)
    bc._clear_stale_tmp_dirs(root, "fix", bc.HARD_TMP_AGE_FLOOR_SECONDS + 4 * 3600)
    assert spared.is_dir(), "a cap wider than the floor must be the one applied"


def test_reconcile_leaves_an_error_phase_tmp_dir_for_cache_status(tmp_path):
    """A failed build's directory is the ONLY record of why it failed:
    cache_status reports it (with the message) and start_build clears it when
    the run is next built. If the reaper removed it the page would offer a
    rebuild with no explanation instead of reporting the failure."""
    root = bc.cache_root(tmp_path)
    tmp = root / "fix.tmp-err"
    tmp.mkdir(parents=True)
    (tmp / "progress.json").write_text(
        json.dumps({"phase": "error", "error": "no state file", "exit": 1})
    )
    old_t = time.time() - 10 * bc.LIVE_TMP_SECONDS
    os.utime(tmp / "progress.json", (old_t, old_t))
    os.utime(tmp, (old_t, old_t))

    assert bc.reconcile_tmp_dirs(tmp_path) == []
    assert tmp.is_dir(), "the reaper removed the only record of the failure"

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    st = bc.cache_status(tmp_path, "fix", run_dir, None)
    assert st.state == "failed"
    assert "no state file" in st.message


# --- the hourly frame is read by window, never whole -------------------------


def _hourly_build(env, monkeypatch) -> Path:
    """Build the fixture run WITH the hourly frame; return its cache dir."""
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg, hourly=True
        )
        await _wait(h)

    asyncio.run(go())
    return bc.cache_dir_for(Path(project["work_dir"]), "fix")


def test_load_cache_does_not_materialise_the_hourly_frame(env, monkeypatch):
    """The published Curonian caches carry a 183-207 MB state_hourly.parquet
    (6.1M rows, ~250 MB in memory). load_cache read it unconditionally and the
    page's cached_result() calls exactly that loader, so every session on that
    project pulled the whole thing into the worker for data no tab displayed.
    It is read by window now (see read_hourly_window), so the eager load must
    not come back."""
    cache_dir = _hourly_build(env, monkeypatch)
    assert (cache_dir / "state_hourly.parquet").is_file(), "the fixture must have hourly data"

    cr = bc.load_cache(cache_dir, "fix")

    assert cr.state_hourly is None, "load_cache must not materialise the hourly frame"
    assert cr.meta["hourly"] is True, "...while meta still says the data is there"
    assert not cr.state_daily.empty, "the daily frames still load"


def test_read_hourly_window_returns_only_the_window(env, monkeypatch):
    cache_dir = _hourly_build(env, monkeypatch)

    lo = pd.Timestamp("2009-01-02 00:00:00")
    hi = pd.Timestamp("2009-01-02 23:59:59")
    frame = bc.read_hourly_window(cache_dir, lo, hi)

    assert not frame.empty
    assert frame["stamp"].min() >= lo and frame["stamp"].max() <= hi
    assert set(frame["box"]) == {1, 2, 3}
    for column in ("temp", "salt", "act_eta"):
        assert column in frame.columns
    # Genuinely a window: the run is 3 days, so one day is a strict subset.
    whole = bc.read_hourly_window(cache_dir, pd.Timestamp("2009-01-01"), pd.Timestamp("2009-01-05"))
    assert len(frame) < len(whole)


def test_read_hourly_window_is_empty_when_there_is_no_hourly_frame(env, monkeypatch):
    """A daily-only cache is the normal case and must not raise: the page falls
    back to daily rather than showing an error."""
    cfg, user, project, run = env
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None
    )
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(
            reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg
        )
        await _wait(h)

    asyncio.run(go())
    cache_dir = bc.cache_dir_for(Path(project["work_dir"]), "fix")
    assert not (cache_dir / "state_hourly.parquet").exists()

    frame = bc.read_hourly_window(cache_dir, pd.Timestamp("2009-01-01"), pd.Timestamp("2009-01-05"))
    assert frame is not None and frame.empty
