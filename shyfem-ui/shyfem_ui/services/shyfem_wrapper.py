"""Wrapper for SHYFEM Fortran CLI tools."""

import asyncio
import collections
import json
import logging
import os
import re
import shutil
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a SHYFEM command execution."""

    success: bool
    return_code: int
    stdout: str
    stderr: str
    command: str
    working_dir: str
    duration: float = 0.0
    output_files: list[str] = field(default_factory=list)


# gfortran's ``stop 'text'`` exits with status 0, so a SHYFEM run or tool that
# stopped on an error looks like a success to anything that only reads the
# exit status (X-01). These are the lines such a stop leaves behind.
_FATAL_LINE = re.compile(
    r"^\s*(?:STOP\s+error stop\b.*|STOP\s+clo_usage\b.*|ERROR STOP\b.*|\*\*\* no such option.*"
    # shyelab -outformat nc on a build without NetCDF: prints this, writes
    # nothing, exits 0.
    r"|NETCDF support has not been enabled.*)$",
    re.MULTILINE,
)
# A shyfem run that reached its end prints this in its last lines.
_SHYFEM_FOOTER = re.compile(r"^\s*simulation end:", re.MULTILINE)
# How much of a run's output is enough to judge how it ended.
TAIL_CHARS = 16_000


def tool_failure(tool_name: str, return_code: int | None, stdout_tail: str, stderr_tail: str):
    """Why a run that exited 0 actually failed, or None if it did not.

    ``stdout_tail``/``stderr_tail`` are the last few KB of the run's output.
    A non-zero exit is already a failure and is not looked at here.
    """
    if return_code != 0:
        return None
    lines = [
        m.group(0).strip()
        for text in (stderr_tail, stdout_tail)
        for m in _FATAL_LINE.finditer(text or "")
    ]
    if lines:
        # "no such option: x" says more than the usage stop that follows it.
        specific = [line for line in lines if "clo_usage" not in line]
        return f"Stopped on an error (exit status 0): {(specific or lines)[0]}"
    if tool_name.startswith("shyfem") and not _SHYFEM_FOOTER.search(stdout_tail or ""):
        return "shyfem stopped before the end of the simulation (no 'simulation end' line)"
    return None


@dataclass
class DetachedRun:
    """Run a command under a supervisor that outlives this process (J-01).

    ``stdout_file`` names the job's log; the other job files sit beside it
    (see :class:`shyfem_ui.services.job_detached.JobFiles`).
    ``kill_on_cancel`` is asked when the watching task is cancelled: True for
    a user's cancel (the tool is killed), False for a worker shutdown (the
    tool keeps running and a later worker reports its end).
    """

    job_id: str
    stdout_file: str
    kill_on_cancel: Callable[[], bool]


class ShyfemWrapper:
    """Wrapper for SHYFEM command-line tools.

    Provides async execution with output streaming and progress tracking.
    """

    ALLOWED_TOOLS = frozenset(
        {
            "shyfem",
            "shyfem-petsc",
            "shypre",
            "shybas",
            "shyparts",
            "shyelab",
            "shyplot",
            "exgrd",
            "shyadj",
            "rstinf",
            "lgrelab",
        }
    )

    # Map tool names to expected output file extensions
    OUTPUT_EXTENSIONS = {
        "shypre": [".bas"],
        "shybas": [".grd", ".xyz", ".png"],
        "shyparts": [".par"],
        "shyfem": [".shy", ".ext", ".flx", ".ts"],
        # out.shy/out.nc/out.fem (-out, -outformat), <var>.shy (-split),
        # <var>.0d.0 (-averbas), <var>.2d.<n>/.3d.<n> per node (-node).
        "shyelab": [".nc", ".txt", ".dat", ".shy", ".fem", ".0d.0", ".2d.[0-9]*", ".3d.[0-9]*"],
        "shyplot": [".png", ".pdf", ".eps"],
    }

    # Grace period between SIGTERM and SIGKILL when tearing down a process
    # group (cancellation or timeout).
    PROCESS_GROUP_KILL_GRACE_SECONDS = 1.5

    # Progress patterns for different tools
    PROGRESS_PATTERNS = {
        # One line per time step: "<date> <seconds> <dt> <it> / <nits> <pct> %"
        "shyfem": re.compile(r"(\d+)\s*/\s*(\d+)\s+[\d.]+\s*%\s*$"),
        "shyelab": re.compile(r"processing\s+record\s+(\d+)\s+of\s+(\d+)", re.IGNORECASE),
    }

    def __init__(self, shyfem_dir: Path | str):
        """Initialize wrapper with SHYFEM installation directory."""
        self.shyfem_dir = Path(shyfem_dir)
        self.bin_dir = self.shyfem_dir / "bin"

    def get_executable(self, tool_name: str) -> Path:
        """Get full path to a SHYFEM executable."""
        if tool_name not in self.ALLOWED_TOOLS:
            raise ValueError(
                f"{tool_name!r} is not an allowed SHYFEM tool. "
                f"Allowed: {sorted(self.ALLOWED_TOOLS)}"
            )
        exe = self.bin_dir / tool_name
        if exe.exists():
            return exe
        # Try without bin/ directory
        alt = self.shyfem_dir / tool_name
        if alt.exists():
            return alt
        # Check system PATH
        which = shutil.which(tool_name)
        if which:
            return Path(which)
        raise FileNotFoundError(f"Executable not found: {tool_name}")

    def check_available(self, tool_name: str) -> bool:
        """Check if a SHYFEM tool is available."""
        try:
            self.get_executable(tool_name)
            return True
        except FileNotFoundError:
            return False

    # Map solver names to executable names
    SOLVER_EXECUTABLES = {
        "sparskit": "shyfem",
        "petsc": "shyfem-petsc",
    }

    def check_solver_available(self, solver: str) -> bool:
        """Check if a solver variant is available."""
        exe_name = self.SOLVER_EXECUTABLES.get(solver)
        if exe_name is None:
            return False
        return self.check_available(exe_name)

    async def run_command(
        self,
        tool_name: str,
        args: list[str],
        working_dir: Path | str,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
        env: dict[str, str] | None = None,
        command_prefix: list[str] | None = None,
        capture_stdout: bool = True,
        detached: DetachedRun | None = None,
    ) -> CommandResult:
        """Run a SHYFEM command asynchronously.

        Args:
            tool_name: Name of the SHYFEM tool (shypre, shybas, etc.)
            args: Command arguments
            working_dir: Working directory for execution
            progress_callback: Called with (progress_fraction, message)
            output_callback: Called with each line of output
            env: Additional environment variables
            command_prefix: Optional prefix for the command (e.g. ["mpirun", "-np", "4"])
            capture_stdout: Retain stdout lines in memory for CommandResult.stdout.
                Set False for long-running simulations that stream their output to
                a file via output_callback — otherwise the full stdout is buffered
                in RAM for the whole run and grows unbounded. stderr is always
                retained (needed for error messages) and output_callback still
                fires per line regardless.
            detached: Hand the run to a supervisor process that writes the
                tool's output to the job's files and outlives this process.
                output_callback and capture_stdout do not apply: the log file
                is written by the supervisor. See :class:`DetachedRun`.

        Returns:
            CommandResult with execution details
        """
        exe = self.get_executable(tool_name)
        working_dir = Path(working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot pre-existing candidate output files (path -> mtime_ns)
        # BEFORE launching the subprocess, so completion only reports files
        # this run actually produced (new) or touched (modified) -- not
        # unrelated pre-existing files left by earlier jobs sharing the same
        # working directory (N48).
        before_snapshot = self._snapshot_output_files(tool_name, working_dir)

        # Build environment
        run_env = os.environ.copy()
        run_env["SHYFEMDIR"] = str(self.shyfem_dir)
        if env:
            run_env.update(env)

        # Build command
        if command_prefix:
            cmd = command_prefix + [str(exe)] + args
        else:
            cmd = [str(exe)] + args
        cmd_str = " ".join(cmd)

        if detached is not None:
            overrides = {"SHYFEMDIR": str(self.shyfem_dir), **(env or {})}
            return await self._run_detached(
                tool_name,
                cmd,
                working_dir,
                overrides,
                before_snapshot,
                detached,
                progress_callback,
            )

        start_time = datetime.now()
        stdout_lines = []
        stdout_tail: collections.deque[str] = collections.deque(maxlen=200)
        stderr_lines = []

        # Optional wall-clock timeout (None = disabled; preserves long sims).
        from shyfem_ui.config import get_config

        timeout = get_config().command_timeout_seconds

        try:
            # start_new_session=True makes the child the leader of its own
            # process group, distinct from the server's. That is required
            # before any group kill: without it, a killpg() on cancellation
            # or timeout would take down the whole server process tree
            # instead of just the spawned shyfem/mpirun job.
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=run_env,
                start_new_session=True,
            )

            progress_failed = False

            # Read output streams concurrently
            async def read_stream(stream, lines_list, is_stderr=False):
                nonlocal progress_failed
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").rstrip()
                    # Always retain stderr (error messages); retain stdout only
                    # when requested — a long sim would otherwise buffer all of
                    # stdout in memory for the whole run. The callback below
                    # still fires per line regardless, so streaming is unaffected.
                    if is_stderr or capture_stdout:
                        lines_list.append(decoded)
                    if not is_stderr:
                        stdout_tail.append(decoded)

                    if output_callback:
                        output_callback(decoded)

                    # Check for progress
                    if progress_callback and not is_stderr:
                        progress = self._parse_progress(tool_name, decoded)
                        if progress is not None:
                            # Progress is advisory: a failing update (a Redis
                            # blip under Celery) must not fail the run.
                            try:
                                progress_callback(progress, decoded)
                            except Exception:
                                if not progress_failed:
                                    progress_failed = True
                                    logger.warning(
                                        "Progress update failed for %r; the run continues",
                                        cmd_str,
                                        exc_info=True,
                                    )

            async def _drain_and_wait():
                readers = [
                    asyncio.ensure_future(read_stream(proc.stdout, stdout_lines)),
                    asyncio.ensure_future(read_stream(proc.stderr, stderr_lines, is_stderr=True)),
                ]
                try:
                    await asyncio.gather(*readers)
                except BaseException:
                    # gather does not cancel the sibling when one reader
                    # fails: stop it, or it keeps reading (and calling
                    # output_callback) after this call has given up.
                    for reader in readers:
                        reader.cancel()
                    await asyncio.gather(*readers, return_exceptions=True)
                    raise
                await proc.wait()

            try:
                if timeout:
                    await asyncio.wait_for(_drain_and_wait(), timeout=timeout)
                else:
                    await _drain_and_wait()
                return_code = proc.returncode

            except asyncio.TimeoutError:
                # A hung tool would otherwise wedge the job (and queue) forever.
                logger.warning("Command %r exceeded %ss timeout; terminating", cmd_str, timeout)
                await self._terminate_process_group(proc, cmd_str)
                return CommandResult(
                    success=False,
                    return_code=-1,
                    stdout="\n".join(stdout_lines),
                    stderr=f"Command timed out after {timeout}s and was terminated",
                    command=cmd_str,
                    working_dir=str(working_dir),
                )
            except asyncio.CancelledError:
                # Job cancellation (LocalJobQueue.cancel -> task.cancel())
                # raises CancelledError here. It must not leak the child:
                # terminate its whole process group, then re-raise so the
                # caller (job_local.py) still observes the cancellation.
                logger.warning("Command %r cancelled; terminating process group", cmd_str)
                await self._terminate_process_group(proc, cmd_str)
                raise
            except Exception as e:
                # Anything else while reading its output (a failing
                # output_callback, a line over the 64 KiB readline limit)
                # ends this call with a failure: the child must not outlive
                # it, unread and unsupervised.
                logger.warning(
                    "Command %r failed while running; terminating process group", cmd_str
                )
                await self._terminate_process_group(proc, cmd_str)
                return CommandResult(
                    success=False,
                    return_code=-1,
                    stdout="\n".join(stdout_lines),
                    stderr="\n".join([*stderr_lines, f"Run aborted: {e}"]),
                    command=cmd_str,
                    working_dir=str(working_dir),
                )

        except Exception as e:
            return CommandResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=str(e),
                command=cmd_str,
                working_dir=str(working_dir),
            )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Find output files: only ones new or modified since before_snapshot.
        output_files = self._find_output_files(tool_name, working_dir, before_snapshot)

        stderr_text = "\n".join(stderr_lines)
        failure = tool_failure(
            tool_name,
            return_code,
            "\n".join(stdout_tail)[-TAIL_CHARS:],
            stderr_text[-TAIL_CHARS:],
        )
        if failure:
            stderr_text = f"{stderr_text}\n{failure}".lstrip("\n")
        return CommandResult(
            success=return_code == 0 and failure is None,
            return_code=return_code,
            stdout="\n".join(stdout_lines),
            stderr=stderr_text,
            command=cmd_str,
            working_dir=str(working_dir),
            duration=duration,
            output_files=output_files,
        )

    # How often a watcher looks at a detached job's files.
    DETACHED_POLL_SECONDS = 0.5
    # Most log bytes a watcher parses per poll, and how much of an existing
    # log a re-attaching watcher reads back.
    DETACHED_READ_BYTES = 1 << 20
    DETACHED_TAIL_BYTES = 64 << 10

    async def _run_detached(
        self,
        tool_name: str,
        cmd: list[str],
        working_dir: Path,
        env_overrides: dict[str, str],
        before_snapshot: dict[str, int],
        detached: DetachedRun,
        progress_callback: Callable[[float, str], None] | None,
    ) -> CommandResult:
        """Start the supervisor for ``cmd`` and watch it until the tool ends."""
        from shyfem_ui.config import get_config
        from shyfem_ui.services.job_detached import JobFiles, write_json_atomic

        files = JobFiles.for_stdout(detached.stdout_file)
        spec = {
            "job_id": detached.job_id,
            "cmd": cmd,
            "cwd": str(working_dir),
            # Only the variables this run adds: the supervisor inherits the
            # rest from this process, and the launch record sits in a
            # user-visible directory, so it must not hold the environment.
            "env": env_overrides,
            "stdout_file": str(files.stdout),
            "tool_name": tool_name,
            "shyfem_dir": str(self.shyfem_dir),
            "timeout": get_config().command_timeout_seconds,
            "before_snapshot": before_snapshot,
        }
        for stale in (files.pid, files.exit):
            stale.unlink(missing_ok=True)
        # A copy for a later worker. Only the output snapshot is ever read
        # back from it: the user can write this directory, so the copy the
        # supervisor acts on comes over stdin.
        write_json_atomic(files.spec, spec)

        with open(files.stderr, "ab") as err:
            # Own session, and no pipe left open back to this process once
            # the record is sent: when the worker exits, nothing reaches the
            # supervisor (no signal, no SIGPIPE). cwd stays this process's,
            # so the supervisor reads the same .env.
            runner = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "shyfem_ui.job_runner",
                detached.job_id,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=err,
                cwd=os.getcwd(),
                start_new_session=True,
            )
        runner.stdin.write(json.dumps(spec).encode())
        await runner.stdin.drain()
        runner.stdin.close()
        return await self.watch_detached(
            tool_name,
            files.stdout,
            detached,
            progress_callback,
            runner=runner,
            working_dir=working_dir,
        )

    async def watch_detached(
        self,
        tool_name: str,
        stdout_file: str | Path,
        detached: DetachedRun,
        progress_callback: Callable[[float, str], None] | None = None,
        runner: asyncio.subprocess.Process | None = None,
        working_dir: str | Path | None = None,
    ) -> CommandResult:
        """Follow a detached job until its exit record appears.

        ``runner`` is the supervisor's handle when this process started it;
        a worker that re-attaches after a restart passes None and checks the
        supervisor's pid instead. Cancelling the watch stops the tool only if
        ``detached.kill_on_cancel()`` says so, and does it by asking the
        supervisor (SIGTERM), which kills the process group it started.
        ``working_dir`` is where output files are looked for; it comes from
        the job, never from the files in that directory.
        """
        from shyfem_ui.services.job_detached import (
            JobFiles,
            read_json,
            read_tail,
            supervisor_alive,
        )

        files = JobFiles.for_stdout(stdout_file)
        offset = 0
        pending = b""
        start = datetime.now()
        if runner is None:
            # Re-attaching to a run already in progress: its log may be
            # hundreds of MB. Only the latest progress line matters, so start
            # near the end instead of parsing the whole log on the loop.
            try:
                offset = max(0, files.stdout.stat().st_size - self.DETACHED_TAIL_BYTES)
            except OSError:
                offset = 0

        def follow_output() -> None:
            nonlocal offset, pending
            if progress_callback is None:
                return
            try:
                with open(files.stdout, "rb") as fh:
                    fh.seek(offset)
                    # Bounded per poll: what is left is read next time.
                    chunk = fh.read(self.DETACHED_READ_BYTES)
            except OSError:
                return
            offset += len(chunk)
            *lines, pending = (pending + chunk).split(b"\n")
            for raw in lines:
                line = raw.decode("utf-8", errors="replace").rstrip()
                progress = self._parse_progress(tool_name, line)
                if progress is not None:
                    try:
                        progress_callback(progress, line)
                    except Exception:
                        logger.debug("Progress update failed", exc_info=True)

        def supervisor_gone() -> bool:
            if runner is not None:
                return runner.returncode is not None
            pid_record = read_json(files.pid) or {}
            return not supervisor_alive(pid_record.get("runner_pid"), detached.job_id)

        exit_record = None
        try:
            while True:
                follow_output()
                exit_record = read_json(files.exit)
                if exit_record is not None:
                    break
                if supervisor_gone():
                    # It may have written the record just before exiting.
                    exit_record = read_json(files.exit)
                    break
                await asyncio.sleep(self.DETACHED_POLL_SECONDS)
        except asyncio.CancelledError:
            if detached.kill_on_cancel():
                await self._stop_supervisor(files, detached.job_id, runner)
            raise
        follow_output()

        spec = read_json(files.spec) or {}
        cwd = Path(working_dir) if working_dir is not None else files.stdout.parent
        if exit_record is None:
            return CommandResult(
                success=False,
                return_code=-1,
                stdout="",
                stderr=read_tail(files.stderr) or "The job supervisor stopped without a result",
                command=" ".join(spec.get("cmd") or []),
                working_dir=str(cwd),
            )
        return_code = exit_record.get("return_code")
        timed_out = bool(exit_record.get("timed_out"))
        failure = None
        if timed_out:
            stderr = f"Command timed out after {spec.get('timeout')}s and was terminated"
        else:
            stderr = read_tail(files.stderr, TAIL_CHARS)
            failure = tool_failure(
                spec.get("tool_name") or tool_name,
                return_code,
                read_tail(files.stdout, TAIL_CHARS),
                stderr,
            )
            if failure:
                stderr = f"{stderr}\n{failure}".lstrip("\n")
            stderr = stderr[-1000:]
        return CommandResult(
            success=return_code == 0 and not timed_out and failure is None,
            return_code=return_code if return_code is not None else -1,
            stdout="",
            stderr=stderr,
            command=" ".join(spec.get("cmd") or []),
            working_dir=str(cwd),
            duration=(datetime.now() - start).total_seconds(),
            output_files=self._find_output_files(tool_name, cwd, spec.get("before_snapshot") or {}),
        )

    async def _stop_supervisor(
        self, files, job_id: str, runner: asyncio.subprocess.Process | None
    ) -> None:
        """Ask a job's supervisor to kill its tool, and wait until it has.

        The supervisor's pid comes from this process's handle when it started
        the job. After a restart it is read from ``<job>.pid`` and accepted
        only if that process's command line is this job's supervisor, so an
        edited pid file cannot aim the signal at any other process.
        """
        from shyfem_ui.services.job_detached import read_json, supervisor_alive

        if runner is not None:
            pid = runner.pid if runner.returncode is None else None
        else:
            pid = (read_json(files.pid) or {}).get("runner_pid")
            if not isinstance(pid, int) or not supervisor_alive(pid, job_id):
                pid = None
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        # The supervisor needs its own kill grace plus one poll to finish.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.PROCESS_GROUP_KILL_GRACE_SECONDS + 3.0
        while loop.time() < deadline:
            if read_json(files.exit) is not None or not supervisor_alive(pid, job_id):
                return
            await asyncio.sleep(0.05)
        logger.warning("The supervisor of job %s did not stop after SIGTERM", job_id)

    async def _terminate_process_group(
        self, proc: asyncio.subprocess.Process, cmd_str: str
    ) -> None:
        """Terminate the process group led by proc: SIGTERM, a short grace
        period, then SIGKILL. Shared by both the cancellation and timeout
        cleanup paths so a hung/cancelled job never leaves an orphaned
        shyfem/mpirun tree running unsupervised.

        Requires the process to have been spawned with start_new_session=True
        (so proc.pid is itself the process group id) -- otherwise this would
        signal the server's own process group.
        """
        # start_new_session=True made proc.pid the group id. Signal the group
        # by that id, not by getpgid(proc.pid): once the leader has exited
        # (asyncio reaps it at once) the lookup fails while other members
        # may still run, and a reused pid would name some unrelated group. A
        # group id is not reused while any member of the group is alive.
        pgid = proc.pid
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return  # the whole group is gone

        try:
            await asyncio.wait_for(proc.wait(), timeout=self.PROCESS_GROUP_KILL_GRACE_SECONDS)
            return
        except asyncio.TimeoutError:
            logger.warning(
                "Command %r did not exit %ss after SIGTERM; sending SIGKILL",
                cmd_str,
                self.PROCESS_GROUP_KILL_GRACE_SECONDS,
            )

        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass

        try:
            await proc.wait()
        except Exception:
            logger.debug("Error awaiting killed process group", exc_info=True)

    def _parse_progress(self, tool_name: str, line: str) -> float | None:
        """Parse progress from output line."""
        pattern = self.PROGRESS_PATTERNS.get(tool_name)
        if not pattern:
            return None

        match = pattern.search(line)
        if match:
            try:
                current = float(match.group(1))
                total = float(match.group(2))
                if total > 0:
                    return min(1.0, current / total)
            except (ValueError, IndexError):
                pass
        return None

    def _snapshot_output_files(self, tool_name: str, working_dir: Path) -> dict[str, int]:
        """Snapshot {path: mtime_ns} for every file matching the tool's
        candidate output extensions, currently present in ``working_dir``.

        Taken immediately before launching the subprocess so
        ``_find_output_files`` can later tell apart files this run actually
        produced or modified from unrelated pre-existing files (N48).
        """
        extensions = self.OUTPUT_EXTENSIONS.get(tool_name, [])
        snapshot: dict[str, int] = {}
        for ext in extensions:
            for f in working_dir.glob(f"*{ext}"):
                try:
                    snapshot[str(f)] = f.stat().st_mtime_ns
                except OSError:
                    # File vanished between glob() and stat() -- ignore, it
                    # can't be a "before" state worth tracking.
                    continue
        return snapshot

    def _find_output_files(
        self,
        tool_name: str,
        working_dir: Path,
        before: dict[str, int] | None = None,
    ) -> list[str]:
        """Find output files this run actually produced.

        ``before`` is the {path: mtime_ns} snapshot taken by
        ``_snapshot_output_files`` right before the subprocess launched. A
        matching-extension file is reported only if it is new (absent from
        ``before``) or was modified during the run (mtime increased) -- so
        pre-existing, untouched files (e.g. left over from an earlier job in
        the same working directory) are never reported as this job's output
        (N48).
        """
        extensions = self.OUTPUT_EXTENSIONS.get(tool_name, [])
        before = before or {}
        output_files = []
        for ext in extensions:
            for f in working_dir.glob(f"*{ext}"):
                try:
                    mtime_ns = f.stat().st_mtime_ns
                except OSError:
                    continue
                prior = before.get(str(f))
                if prior is None or mtime_ns > prior:
                    output_files.append(str(f))
        return output_files

    # Convenience methods for specific tools

    async def run_shypre(
        self,
        grd_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shypre to convert .grd to .bas file.

        Args:
            grd_file: Path to input .grd file
            working_dir: Working directory
            options: Additional options like ["-opti", "-renumber"]
        """
        args = list(options) if options else []  # copy: never mutate caller's list
        args.append(str(grd_file))
        return await self.run_command(
            "shypre", args, working_dir, progress_callback, output_callback
        )

    async def run_shybas(
        self,
        bas_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shybas to analyze basin file.

        Args:
            bas_file: Path to input .bas file
            working_dir: Working directory
            options: Additional options like ["-quality", "-grd", "-xyz"]
        """
        args = list(options) if options else []  # copy: never mutate caller's list
        args.append(str(bas_file))
        return await self.run_command(
            "shybas", args, working_dir, progress_callback, output_callback
        )

    async def run_shyparts(
        self,
        bas_file: Path | str,
        working_dir: Path | str,
        np: int = 4,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyparts to partition mesh for MPI.

        Args:
            bas_file: Path to input .bas file
            working_dir: Working directory
            np: Number of partitions
            options: Additional options
        """
        args = list(options) if options else []  # copy: never mutate caller's list
        args.extend(["-np", str(np)])
        args.append(str(bas_file))
        return await self.run_command(
            "shyparts", args, working_dir, progress_callback, output_callback
        )

    async def run_shyfem(
        self,
        str_file: Path | str,
        working_dir: Path | str,
        mpi_enabled: bool = False,
        mpi_np: int = 1,
        mpirun_path: str = "mpirun",
        options: list[str] | None = None,
        solver: str = "sparskit",
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
        capture_stdout: bool = True,
        detached: DetachedRun | None = None,
    ) -> CommandResult:
        """Run shyfem simulation.

        Args:
            str_file: Path to input .str file
            working_dir: Working directory
            mpi_enabled: Whether to use MPI
            mpi_np: Number of MPI processes
            mpirun_path: Path to mpirun executable
            options: Additional options
            solver: Solver variant ('sparskit' or 'petsc')
            capture_stdout: See run_command. Set False for job-runner call sites
                that stream output to a file (a full sim's stdout is large).
        """
        tool_name = self.SOLVER_EXECUTABLES.get(solver, "shyfem")
        args_list = list(options) if options else []  # copy: never mutate caller's list
        args_list.append(str(str_file))

        prefix = None
        if mpi_enabled and mpi_np > 1:
            prefix = [mpirun_path, "-np", str(mpi_np)]

        return await self.run_command(
            tool_name,
            args_list,
            working_dir,
            progress_callback,
            output_callback,
            command_prefix=prefix,
            capture_stdout=capture_stdout,
            detached=detached,
        )

    async def run_shyelab(
        self,
        shy_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyelab to post-process output.

        Args:
            shy_file: Path to input .shy file
            working_dir: Working directory
            options: Additional options like ["-split", "-tmin", "0", "-tmax", "100"]
        """
        args = list(options) if options else []  # copy: never mutate caller's list
        # shyelab truncates a long file name ("file not existing"), so pass
        # the input relative to its working folder when that is shorter --
        # usually just the name, since outputs go next to the input.
        absolute = str(Path(shy_file).resolve())
        relative = os.path.relpath(absolute, Path(working_dir).resolve())
        args.append(relative if len(relative) < len(absolute) else absolute)
        return await self.run_command(
            "shyelab", args, working_dir, progress_callback, output_callback
        )
