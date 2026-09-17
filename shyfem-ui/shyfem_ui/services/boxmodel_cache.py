"""Box-model cache: where it lives, what state it is in, how it is built
(child process, registry, two-step publish) and how pages load it (spec §6).
Nothing here touches reactive state; the page polls ``cache_status``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd

from shyfem_ui.config import Config

logger = logging.getLogger(__name__)

CACHE_DIRNAME = ".boxmodel_cache"
MAX_BUILDS_PER_WORKER = 2
MAX_BUILDS_PER_USER = 1
LIVE_TMP_SECONDS = 90  # a tmp dir whose progress.json is older than this is dead
KILL_GRACE_SECONDS = 5.0
CacheState = Literal["missing", "stale", "queued", "building", "ready", "failed"]


def cache_root(project_work_dir: Path) -> Path:
    return Path(project_work_dir) / CACHE_DIRNAME


def cache_dir_for(project_work_dir: Path, run_id: str) -> Path:
    return cache_root(project_work_dir) / run_id


@dataclass
class CacheStatus:
    state: CacheState
    progress: dict | None
    meta: dict | None
    message: str = ""


@dataclass
class BuildHandle:
    key: tuple[int, str]
    owner_id: int | None
    tmp_dir: Path
    task: asyncio.Task | None = None
    pid: int | None = None
    started: float = field(default_factory=time.time)
    state: str = "queued"  # queued | building | done | failed | cancelled
    proc: asyncio.subprocess.Process | None = None


class BuildRegistry:
    """Plain locked state shared by every session on this worker process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: dict[tuple[int, str], BuildHandle] = {}
        self._sem: asyncio.Semaphore | None = None

    def semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(MAX_BUILDS_PER_WORKER)
        return self._sem

    def get(self, key: tuple[int, str]) -> BuildHandle | None:
        with self._lock:
            h = self._handles.get(key)
            return h if h and h.state in ("queued", "building") else None

    def put(self, h: BuildHandle) -> None:
        with self._lock:
            self._handles[h.key] = h

    def active_for_user(self, user_id: int | None) -> int:
        with self._lock:
            return sum(
                1
                for h in self._handles.values()
                if h.owner_id == user_id and h.state in ("queued", "building")
            )

    def handles(self) -> list[BuildHandle]:
        with self._lock:
            return list(self._handles.values())


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None  # a half-written file reads as "unknown", callers treat it as building


def _sources_changed(meta: dict, run_dir: Path) -> bool:
    for name, rec in (meta.get("sources") or {}).items():
        p = run_dir / name
        if not p.is_file():
            return True
        st = p.stat()
        if st.st_size != rec.get("size") or st.st_mtime_ns != rec.get("mtime_ns"):
            return True
    return False


def cache_status(
    project_work_dir: Path, run_id: str, run_dir: Path, registry: BuildRegistry | None
) -> CacheStatus:
    root = cache_root(project_work_dir)
    if registry is not None:
        for h in registry.handles():
            if (
                h.key[1] == run_id
                and Path(h.tmp_dir).parent == root
                and h.state in ("queued", "building")
            ):
                return CacheStatus(
                    h.state, _read_json(h.tmp_dir / "progress.json"), None, "build in progress"
                )
    for tmp in sorted(root.glob(f"{run_id}.tmp-*")):
        prog = _read_json(tmp / "progress.json")
        pj = tmp / "progress.json"
        age = time.time() - pj.stat().st_mtime if pj.exists() else 1e9
        if prog and prog.get("phase") == "error":
            return CacheStatus("failed", prog, None, prog.get("error") or "build failed")
        if age < LIVE_TMP_SECONDS:
            return CacheStatus("building", prog, None, "build in progress (another worker)")
    cache_dir = root / run_id
    meta = _read_json(cache_dir / "meta.json") if (cache_dir / "meta.json").is_file() else None
    if meta is None:
        return CacheStatus("missing", None, None, "no cache yet")
    if _sources_changed(meta, run_dir):
        return CacheStatus("stale", None, meta, "run output changed since the cache was built")
    return CacheStatus("ready", None, meta, "ready")


def publish(tmp_dir: Path, run_id: str) -> Path:
    """Two-step publish: target -> .old-<token>, tmp -> target, remove old.

    Idempotent when interrupted: if a previous crash already left ``target``
    renamed to ``.old-*`` and/or ``tmp`` already renamed to ``target``, the
    ``os.rename`` calls below are individually skipped via the existence
    checks rather than raising, so re-running publish on the same tmp/target
    pair converges to the same end state.
    """
    target = tmp_dir.parent / run_id
    token = tmp_dir.name.split(".tmp-", 1)[-1] or secrets.token_hex(4)
    old = tmp_dir.parent / f"{run_id}.old-{token}"
    if target.exists():
        os.rename(target, old)
    if tmp_dir.exists():
        os.rename(tmp_dir, target)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    return target


def reconcile_tmp_dirs(project_work_dir: Path) -> list[str]:
    """Publish finished tmp dirs, remove dead tmp dirs and stray .old dirs.

    Never touches a live ``.tmp-*`` (``progress.json`` younger than
    ``LIVE_TMP_SECONDS``) or a published cache directory -- only entries
    whose name contains ``.tmp-`` or ``.old-`` are ever considered. Idempotent:
    running it again on an already-reconciled tree finds nothing to do.
    """
    root = cache_root(project_work_dir)
    msgs: list[str] = []
    if not root.is_dir():
        return msgs
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if ".old-" in d.name:
            shutil.rmtree(d, ignore_errors=True)
            msgs.append(f"removed stray {d.name}")
            continue
        if ".tmp-" not in d.name:
            continue
        run_id = d.name.split(".tmp-", 1)[0]
        prog = _read_json(d / "progress.json")
        if (
            prog
            and prog.get("phase") == "done"
            and prog.get("exit") == 0
            and (d / "meta.json").is_file()
        ):
            publish(d, run_id)
            msgs.append(f"published {run_id}")
            continue
        pj = d / "progress.json"
        age = time.time() - pj.stat().st_mtime if pj.exists() else 1e9
        if age >= LIVE_TMP_SECONDS and not (prog and prog.get("phase") == "error"):
            shutil.rmtree(d, ignore_errors=True)
            msgs.append(f"removed dead {d.name}")
    return msgs


async def start_build(
    registry: BuildRegistry,
    *,
    project: dict,
    run_id: str,
    run_dir: Path,
    user: dict | None,
    config: Config,
    hourly: bool = False,
) -> BuildHandle:
    """Validate, dedupe/cap, and launch a build as a detached child process.

    Order: editor gate -> confine ``run_dir`` (read) -> confine the project
    work dir (write) -> dedupe on ``(project_id, run_id)`` -> per-user cap ->
    create the tmp dir -> spawn. Both confinements happen before any registry
    mutation, so a rejected request never registers a handle.
    """
    from shyfem_ui.services.access_control import editor_denied_reason

    denied = editor_denied_reason(project["id"], user, min_role="editor")
    if denied:
        raise PermissionError(denied)

    run_dir = config.confine_path(run_dir, user, must_exist=True, for_write=False)
    work_dir = Path(project["work_dir"])
    # Validate only -- the cache lives under the project's own work_dir, and
    # cache_status()/cache_root() key off that same unresolved path, so we
    # deliberately don't rebind work_dir to confine_path's resolved value.
    config.confine_path(work_dir, user, must_exist=True, for_write=True)

    key = (int(project["id"]), run_id)
    existing = registry.get(key)
    if existing is not None:
        return existing

    owner_id = user.get("id") if user else None
    if registry.active_for_user(owner_id) >= MAX_BUILDS_PER_USER:
        raise RuntimeError(
            "Only one build at a time per user; wait for the running build to finish."
        )

    root = cache_root(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    tmp_dir = root / f"{run_id}.tmp-{secrets.token_hex(4)}"
    tmp_dir.mkdir()

    h = BuildHandle(key=key, owner_id=owner_id, tmp_dir=tmp_dir)
    registry.put(h)

    bases = [str(config.user_data_root.resolve()), str(Path(config.work_dir).resolve())]
    cmd = [
        sys.executable,
        "-m",
        "shyfem_ui.boxmodel_cache_cli",
        "--run",
        str(run_dir),
        "--out",
        str(tmp_dir),
    ]
    for b in bases:
        cmd += ["--trusted-base", b]
    if hourly:
        cmd.append("--hourly")

    h.task = asyncio.create_task(_run_build(registry, h, cmd, config.command_timeout_seconds))
    return h


async def _run_build(
    registry: BuildRegistry, h: BuildHandle, cmd: list[str], timeout: int | None
) -> None:
    async with registry.semaphore():
        if h.state == "cancelled":
            return
        h.state = "building"
        rc: int | None = None
        try:
            # stdout/stderr go straight to a real file, never asyncio.subprocess.PIPE
            # -- a PIPE that nobody reads fills its OS buffer and deadlocks the
            # child; a file has no such limit and needs no draining loop.
            with open(h.tmp_dir / "build.log", "wb") as log:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=log,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=str(h.tmp_dir),
                        start_new_session=True,
                    )
                except OSError as e:
                    logger.error("boxmodel cache build %s failed to start: %s", h.key, e)
                    h.state = "failed"
                    return
                h.proc, h.pid = proc, proc.pid
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("boxmodel cache build %s timed out", h.key)
                    await _terminate(proc)
                    rc = -1
        except Exception:
            # Never leave a build stuck mid-"building" -- log and fail closed.
            logger.exception("boxmodel cache build %s crashed", h.key)
            h.state = "failed"
            return

        if h.state == "cancelled":
            shutil.rmtree(h.tmp_dir, ignore_errors=True)
            return
        if rc == 0 and (h.tmp_dir / "meta.json").is_file():
            publish(h.tmp_dir, h.key[1])
            h.state = "done"
        else:
            h.state = "failed"
            if not (h.tmp_dir / "progress.json").exists():
                shutil.rmtree(h.tmp_dir, ignore_errors=True)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """SIGTERM the process group, a short grace period, then SIGKILL.

    Mirrors ``ShyfemWrapper._terminate_process_group``. Requires ``proc`` to
    have been spawned with ``start_new_session=True`` (so ``proc.pid`` is
    itself the process group id) -- otherwise this would signal the worker's
    own process group.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_SECONDS)
        return
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        await proc.wait()
    except Exception:
        logger.debug("Error awaiting killed process group", exc_info=True)


async def cancel_build(
    registry: BuildRegistry, key: tuple[int, str], *, project: dict, user: dict | None
) -> bool:
    from shyfem_ui.services.access_control import editor_denied_reason

    if editor_denied_reason(project["id"], user, min_role="editor"):
        return False
    h = registry.get(key)
    if h is None:
        return False
    h.state = "cancelled"
    if h.proc is not None:
        await _terminate(h.proc)
    else:
        shutil.rmtree(h.tmp_dir, ignore_errors=True)
    return True


@dataclass
class CachedRun:
    run_id: str
    meta: dict
    state_daily: pd.DataFrame
    flux_daily: pd.DataFrame
    meteo_daily: pd.DataFrame
    state_hourly: pd.DataFrame | None = None


def _to_ns(series: pd.Series) -> pd.Series:
    """Normalize a date32-sourced column to datetime64[ns].

    pandas/pyarrow hand a parquet ``date32`` column back as an ``object``
    column of ``datetime.date``; ``pd.to_datetime`` on that can resolve to a
    coarser unit (e.g. ``datetime64[s]``) depending on the pandas version, so
    callers that promise ``datetime64[ns]`` must force it explicitly.
    """
    return pd.to_datetime(series).astype("datetime64[ns]")


def load_cache(cache_dir: Path, run_id: str) -> CachedRun:
    """Load a *published* cache directory. Never reads a ``.tmp-*``/``.old-*``
    directory -- callers pass the published ``cache_dir_for(...)`` path.
    """
    meta = json.loads((cache_dir / "meta.json").read_text())
    sd = pd.read_parquet(cache_dir / "state_daily.parquet")
    sd["date"] = _to_ns(sd["date"])
    fd = pd.read_parquet(cache_dir / "flux_daily.parquet")
    fd["date"] = _to_ns(fd["date"])
    md = pd.read_parquet(cache_dir / "meteo_daily.parquet")
    md["date"] = _to_ns(md["date"])
    hp = cache_dir / "state_hourly.parquet"
    hourly = pd.read_parquet(hp) if hp.is_file() else None
    return CachedRun(run_id, meta, sd, fd, md, hourly)
