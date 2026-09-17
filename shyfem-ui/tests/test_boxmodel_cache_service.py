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
import time
from pathlib import Path

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
