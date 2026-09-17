"""Box-model cache: where it lives, what state it is in, how it is built
(child process, registry, two-step publish) and how pages load it (spec §6).
Nothing here touches reactive state; the page polls ``cache_status``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import signal
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

# Same shape as the CLI's own --out slug component and boxmodel_manifest's
# run id slug: [a-z0-9_-]{1,64}. run_id reaches glob()/mkdir() unvalidated
# otherwise -- a run_id of "../../victim" would let a caller escape the
# cache root entirely.
_RUN_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def _check_run_id(run_id: str) -> None:
    if not isinstance(run_id, str) or not _RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id: must match [a-z0-9_-]{1,64}")


def cache_root(project_work_dir: Path) -> Path:
    return Path(project_work_dir) / CACHE_DIRNAME


def cache_dir_for(project_work_dir: Path, run_id: str) -> Path:
    _check_run_id(run_id)
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
    # Set by cancel_build even before h.proc exists (i.e. while _run_build is
    # still awaiting create_subprocess_exec) so the build terminates itself
    # immediately once it actually has a process to signal, instead of
    # spawning an orphan nobody will ever cancel.
    cancel_requested: bool = False


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

    def pop(self, key: tuple[int, str], h: BuildHandle | None = None) -> None:
        """Remove the handle for ``key`` -- but only if it is still the SAME
        handle instance passed in (when one is given). Without the identity
        check, a ``_run_build`` task finishing late (its terminal state
        already excludes it from ``get()``, but it has not reached its own
        ``finally`` yet) could evict a *newer* handle a fresh ``start_build``
        has since installed for the same key. Also closes "handles are never
        pruned": every ``_run_build`` pops itself in its ``finally``.
        """
        with self._lock:
            cur = self._handles.get(key)
            if cur is not None and (h is None or cur is h):
                del self._handles[key]

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
    sources = meta.get("sources") or {}
    if not sources:
        # No recorded sources at all (malformed/foreign meta.json) means we
        # cannot verify the cache still matches the run -- fail closed to
        # "changed" rather than silently trusting an unverifiable cache.
        return True
    for name, rec in sources.items():
        p = run_dir / name
        if not p.is_file():
            return True
        st = p.stat()
        if st.st_size != rec.get("size") or st.st_mtime_ns != rec.get("mtime_ns"):
            return True
    return False


def _atomic_json(path: Path, payload: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _progress_age(tmp: Path) -> float:
    """Age (seconds) of a tmp dir's liveness signal.

    ``progress.json``'s own mtime when it exists; otherwise the directory's
    own mtime. A build still queued behind the per-worker cap has an empty,
    freshly created directory with no ``progress.json`` yet -- falling back
    to an "infinitely old" sentinel there would misjudge a perfectly live,
    just-queued build as long-dead and let it be removed out from under it.
    """
    pj = tmp / "progress.json"
    try:
        return time.time() - pj.stat().st_mtime
    except OSError:
        pass
    try:
        return time.time() - tmp.stat().st_mtime
    except OSError:
        return 1e9


def _tmp_dir_is_dead_or_error(tmp: Path) -> bool:
    prog = _read_json(tmp / "progress.json")
    return bool(prog and prog.get("phase") == "error") or _progress_age(tmp) >= LIVE_TMP_SECONDS


def _clear_stale_tmp_dirs(root: Path, run_id: str) -> None:
    """Remove every existing ``<run_id>.tmp-*`` that is error-phase or dead
    (see ``_progress_age``), so a successful build's later publish is never
    shadowed by an old failure (see ``cache_status``). Never removes a
    *live* tmp dir -- that is another build actually in flight (this
    worker's own in-flight builds for the same key are already caught by
    the registry dedupe in ``start_build``, so this only matters for
    another worker's build). Skips symlinks: never follow or remove
    something this directory does not actually own.
    """
    _check_run_id(run_id)
    for tmp in root.glob(f"{run_id}.tmp-*"):
        if tmp.is_symlink():
            continue
        if _tmp_dir_is_dead_or_error(tmp):
            shutil.rmtree(tmp, ignore_errors=True)


def cache_status(
    project_work_dir: Path, run_id: str, run_dir: Path, registry: BuildRegistry | None
) -> CacheStatus:
    """Precedence (a successful publish always wins over an old failure):

    (a) a registry handle in ``queued``/``building`` -> that state;
    (b) a live ``<run_id>.tmp-*`` (``progress.json`` younger than
        ``LIVE_TMP_SECONDS``, phase not ``error``) -> ``building`` (another
        worker's build -- this worker's own in-flight builds are already
        covered by (a));
    (c) a published ``<run_id>/`` with ``meta.json`` -> ``ready``/``stale``;
    (d) an ``error``-phase ``<run_id>.tmp-*`` -> ``failed``, surfacing its
        error message -- checked only once nothing valid was published;
    (e) otherwise ``missing``.

    A leftover error tmp dir from a failed build is only ever *reported*
    here, never removed -- ``start_build`` clears it (see
    ``_clear_stale_tmp_dirs``) the next time a build for the same
    ``run_id`` is actually launched.
    """
    _check_run_id(run_id)
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

    live_progress: dict | None = None
    error_progress: dict | None = None
    for tmp in sorted(root.glob(f"{run_id}.tmp-*")):
        prog = _read_json(tmp / "progress.json")
        age = _progress_age(tmp)
        if prog and prog.get("phase") == "error":
            error_progress = prog
        elif age < LIVE_TMP_SECONDS:
            live_progress = prog
    if live_progress is not None:
        return CacheStatus("building", live_progress, None, "build in progress (another worker)")

    cache_dir = root / run_id
    meta = _read_json(cache_dir / "meta.json") if (cache_dir / "meta.json").is_file() else None
    if meta is not None:
        if _sources_changed(meta, run_dir):
            return CacheStatus("stale", None, meta, "run output changed since the cache was built")
        return CacheStatus("ready", None, meta, "ready")

    if error_progress is not None:
        return CacheStatus(
            "failed", error_progress, None, error_progress.get("error") or "build failed"
        )
    return CacheStatus("missing", None, None, "no cache yet")


def publish(tmp_dir: Path, run_id: str) -> Path:
    """Two-step publish: target -> .old-<token>, tmp -> target, remove old.

    Safe to call on an already-published ``tmp_dir``: if it no longer
    exists, some earlier call already completed the rename for it, so this
    returns ``target`` untouched. This is reachable, not hypothetical: this
    worker's own ``_run_build`` can publish at the end of a build at the
    same moment another session's page-load ``reconcile_tmp_dirs`` has
    already listed that same finished tmp dir (from an earlier directory
    scan) and calls ``publish`` on it too. Without checking this FIRST, the
    second call would see ``target`` already holding the fresh content,
    rename it away to ``.old-<token>``, find ``tmp_dir`` gone (skipping step
    2), and then delete the ".old" -- destroying the only copy of the
    published cache.
    """
    target = tmp_dir.parent / run_id
    if not tmp_dir.exists():
        return target
    token = tmp_dir.name.split(".tmp-", 1)[-1] or secrets.token_hex(4)
    old = tmp_dir.parent / f"{run_id}.old-{token}"
    if target.exists():
        os.rename(target, old)
    os.rename(tmp_dir, target)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    return target


def reconcile_tmp_dirs(project_work_dir: Path) -> list[str]:
    """Publish finished tmp dirs, remove dead tmp dirs and stray .old dirs.

    Never touches a live ``.tmp-*`` (see ``_progress_age``) or a published
    cache directory -- only entries whose name contains ``.tmp-`` or
    ``.old-`` are ever considered, and a symlink is never followed or
    removed regardless of its name (it could point anywhere). A stray
    non-directory entry with a ``.tmp-``/``.old-`` name (never produced by
    this module, but nothing stops something else from leaving one) is
    unlinked rather than skipped forever. Idempotent: running it again on an
    already-reconciled tree finds nothing to do.
    """
    root = cache_root(project_work_dir)
    msgs: list[str] = []
    if not root.is_dir():
        return msgs
    for d in sorted(root.iterdir()):
        if d.is_symlink():
            continue
        if not d.is_dir():
            if ".old-" in d.name or ".tmp-" in d.name:
                try:
                    d.unlink()
                    msgs.append(f"removed stray file {d.name}")
                except OSError:
                    logger.warning("reconcile_tmp_dirs: could not remove stray file %s", d)
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
        if _progress_age(d) >= LIVE_TMP_SECONDS and not (prog and prog.get("phase") == "error"):
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

    Order: ``run_id`` shape -> editor gate -> confine ``run_dir`` (read) ->
    confine the project work dir (write) -> dedupe on ``(project_id,
    run_id)`` -> per-user cap -> compute the tmp dir's path -> spawn. Both
    confinements happen before any registry mutation, so a rejected request
    never registers a handle. The tmp dir itself is not created here -- see
    ``_run_build`` -- only its path is decided, so a build still queued
    behind the per-worker cap has no on-disk footprint at all yet.
    """
    _check_run_id(run_id)
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
    # A previous build's error tmp dir (kept around for cache_status to
    # report) is only ever cleaned up here, right before a new build for the
    # same run_id actually starts -- never by cache_status itself.
    _clear_stale_tmp_dirs(root, run_id)
    # Not created yet -- _run_build creates it only once the per-worker
    # semaphore is actually acquired (see below), so cancel_build's
    # pre-spawn cleanup of a still-queued build's tmp dir is a safe no-op
    # rather than removing something another build already occupies.
    tmp_dir = root / f"{run_id}.tmp-{secrets.token_hex(4)}"

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
    """Run one build to completion, always leaving ``h`` in a terminal state
    and always popping it from ``registry`` (see the ``finally`` block) --
    regardless of success, a genuine CLI failure, a spawn failure, a
    timeout, cancellation, or the asyncio task itself being cancelled (e.g.
    the worker's event loop shutting down).
    """
    proc: asyncio.subprocess.Process | None = None
    try:
        # The semaphore acquisition itself must be INSIDE the try: a task
        # cancelled while still queued (waiting on this await, behind
        # MAX_BUILDS_PER_WORKER) raises CancelledError from __aenter__,
        # before a `try` that started after it would ever be entered --
        # leaving the handle wedged "queued" forever and never popped. With
        # it inside, that cancellation is caught below like any other.
        async with registry.semaphore():
            if h.state == "cancelled":
                return
            h.state = "building"
            h.tmp_dir.mkdir(exist_ok=True)
            rc: int | None = None
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
                    if h.state != "cancelled":
                        h.state = "failed"
                        if h.tmp_dir.is_dir():
                            _write_error_progress(h.tmp_dir, f"failed to start: {e}")
                    return
                h.proc, h.pid = proc, proc.pid
                if h.cancel_requested:
                    # cancel_build ran while we were still awaiting
                    # create_subprocess_exec, before h.proc existed for it to
                    # signal -- terminate immediately now that we have one,
                    # rather than spawning an orphan nobody will ever cancel.
                    await _terminate(proc)
                    h.state = "cancelled"
                    return
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("boxmodel cache build %s timed out after %ss", h.key, timeout)
                    await _terminate(proc)  # waits for the child to actually exit
                    rc = -1
                    if h.state != "cancelled":
                        # The child never got a chance to write its own error
                        # phase (it was killed from the outside), so write one
                        # ourselves: keeps the tmp dir informative for
                        # cache_status instead of freezing on a stale snapshot.
                        _write_error_progress(h.tmp_dir, f"build timed out after {timeout}s")

            if h.state == "cancelled":
                return
            if rc == 0 and (h.tmp_dir / "meta.json").is_file():
                publish(h.tmp_dir, h.key[1])
                h.state = "done"
            else:
                h.state = "failed"
                if not (h.tmp_dir / "progress.json").exists():
                    # The CLI's own structural-validation refusal (exit 2)
                    # never creates a _Progress object at all, so nothing was
                    # written for it -- surface the reason via build.log's
                    # last line rather than leaving cache_status reporting
                    # "missing". A genuine exit-1 failure already wrote its
                    # own, more specific progress.json, so this branch is
                    # only ever reached when nothing else did.
                    last_line = _last_log_line(h.tmp_dir)
                    msg = f"build exited with code {rc}"
                    if last_line:
                        msg += f": {last_line}"
                    _write_error_progress(
                        h.tmp_dir, msg, exit_code=rc if isinstance(rc, int) else -1
                    )
    except asyncio.CancelledError:
        # The asyncio TASK itself was cancelled -- distinct from
        # cancel_build, which only ever flips h.state/h.cancel_requested and
        # never calls task.cancel(). Also the path for a build cancelled
        # while still queued (waiting on the semaphore above): proc is None
        # there, so _terminate is skipped and only h.state is set. Mirrors
        # ShyfemWrapper's own cancellation leg (shyfem_wrapper.py): never
        # leak the child, then re-raise so the awaiting caller still
        # observes it.
        logger.warning("boxmodel cache build %s task cancelled", h.key)
        if proc is not None:
            await _terminate(proc)
        h.state = "cancelled"
        raise
    except Exception as exc:
        # Never leave a build stuck mid-"building" -- log, fail closed, and
        # (unless a concurrent cancel already claimed this handle) make the
        # tmp dir's progress.json reflect THIS failure rather than whatever
        # the child last reported, since our own post-processing (e.g.
        # publish() itself raising) is what actually failed here, possibly
        # after the child had already finished successfully.
        logger.exception("boxmodel cache build %s crashed", h.key)
        if h.state != "cancelled":
            h.state = "failed"
            if h.tmp_dir.is_dir():
                _write_error_progress(h.tmp_dir, f"internal error: {exc}")
    finally:
        if h.state == "cancelled":
            shutil.rmtree(h.tmp_dir, ignore_errors=True)
        elif h.state in ("queued", "building"):
            # Should be unreachable given the branches above, but never
            # leave a handle wedged mid-build if some path was missed.
            h.state = "failed"
        registry.pop(h.key, h)


def _write_error_progress(tmp_dir: Path, message: str, *, exit_code: int = -1) -> None:
    """Write (or overwrite) ``progress.json`` with an error phase and
    ``message``.

    Used whenever the child never got a chance to write its own error phase
    (spawn failure; timeout; a non-zero exit via a code path -- the CLI's
    exit-2 structural-validation refusal -- that predates its own progress
    writer) or whenever our own post-processing failed *after* the child
    had already finished (``publish()`` raising). Keeps the tmp dir
    informative for ``cache_status`` instead of silently vanishing or
    freezing on a stale snapshot, exactly like a genuine CLI failure.
    """
    prev = _read_json(tmp_dir / "progress.json") or {}
    _atomic_json(
        tmp_dir / "progress.json",
        {
            "phase": "error",
            "records": prev.get("records", 0),
            "expected": prev.get("expected", 0),
            "error": message,
            "exit": exit_code,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )


def _last_log_line(tmp_dir: Path) -> str:
    """The last non-blank line of ``build.log``, or ``""`` if unavailable."""
    try:
        data = (tmp_dir / "build.log").read_bytes()
    except OSError:
        return ""
    lines = [ln for ln in data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


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
    # Set even before h.proc exists: if _run_build is still awaiting
    # create_subprocess_exec, it checks this flag right after obtaining the
    # process and terminates immediately instead of leaving an orphan.
    h.cancel_requested = True
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
