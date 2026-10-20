"""Supervisor for one detached local job (J-01).

Started by the web worker as ``python -m shyfem_ui.job_runner <job>.job`` in a
session of its own, with the worker's working directory as cwd so that
``get_config()`` reads the same ``.env``. It outlives the worker: nothing
connects the two once it has started.

It runs the tool with stdout and stderr going to the job's files, enforces
the optional wall-clock timeout, writes ``<job>.exit``, then ends the job's DB
row (only if the row is still active) and, if it did, sends the completion
email. See :mod:`shyfem_ui.services.job_detached`.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from shyfem_ui.services.job_detached import (
    JobFiles,
    finalize_job_row,
    read_json,
    read_tail,
    write_json_atomic,
)
from shyfem_ui.services.job_queue import JobStatus

logger = logging.getLogger("shyfem_ui.job_runner")

POLL_SECONDS = 0.5
KILL_GRACE_SECONDS = 1.5


def _kill_group(pgid: int) -> None:
    """SIGTERM the tool's process group, then SIGKILL whatever is left."""
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run(spec: dict) -> int:
    """Run the job described by ``spec`` to completion. Returns its exit code."""
    files = JobFiles.for_stdout(spec["stdout_file"])
    env = os.environ.copy()
    env.update(spec.get("env") or {})
    timeout = spec.get("timeout")

    with open(files.stdout, "ab") as out, open(files.stderr, "ab") as err:
        child = subprocess.Popen(
            spec["cmd"],
            cwd=spec["cwd"],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            env=env,
            # The tool leads its own group, so a cancel can signal the whole
            # tool tree (mpirun and its ranks) without touching this process.
            start_new_session=True,
        )
    write_json_atomic(
        files.pid,
        {"runner_pid": os.getpid(), "pgid": child.pid, "started_at": time.time()},
    )

    timed_out = False
    started = time.monotonic()
    while True:
        try:
            child.wait(timeout=POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pass
        if timeout and time.monotonic() - started > timeout:
            timed_out = True
            _kill_group(child.pid)
            child.wait()
            break

    return_code = child.returncode
    write_json_atomic(
        files.exit,
        {"return_code": return_code, "timed_out": timed_out, "finished_at": time.time()},
    )
    _finalize(spec, files, return_code, timed_out)
    return return_code


def result_fields(spec: dict, files: JobFiles, return_code: int | None, timed_out: bool) -> dict:
    """The terminal fields of a job from its exit record and files.

    Shared by the supervisor and by a worker that finds an exit record left
    by a supervisor which died before it could end the row.
    """
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

    if timed_out:
        status = JobStatus.FAILED
        error = f"Command timed out after {spec.get('timeout')}s and was terminated"
    elif return_code == 0:
        status = JobStatus.COMPLETED
        error = None
    else:
        status = JobStatus.FAILED
        error = read_tail(files.stderr) or "Unknown error"
    wrapper = ShyfemWrapper(spec.get("shyfem_dir") or ".")
    output_files = wrapper._find_output_files(
        spec["tool_name"], Path(spec["cwd"]), spec.get("before_snapshot") or {}
    )
    return {
        "status": status,
        "return_code": return_code,
        "error_message": error,
        "output_files": output_files,
        "progress": 1.0,
        "completed_at": datetime.now(),
    }


def _finalize(spec: dict, files: JobFiles, return_code: int | None, timed_out: bool) -> None:
    """End the row and, if this process did, send the completion email."""
    job_id = spec["job_id"]
    fields = result_fields(spec, files, return_code, timed_out)
    status = fields.pop("status")
    if not finalize_job_row(job_id, status, **fields):
        return  # a cancel, or a watching worker, ended it first
    try:
        from shyfem_ui.config import get_config
        from shyfem_ui.services.job_local import load_job_info, send_completion_notification
        from shyfem_ui.services.notification_service import NotificationService

        job = load_job_info(job_id)
        if job is not None:
            send_completion_notification(NotificationService(get_config()), job)
    except Exception:
        logger.warning("Could not send the completion email for job %s", job_id, exc_info=True)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m shyfem_ui.job_runner <job>.job", file=sys.stderr)
        return 2
    # This process's stderr is the job's stderr file: problems here show up
    # in the job log, where the user and the admin look.
    logging.basicConfig(level=logging.WARNING, format="[job runner] %(levelname)s %(message)s")
    spec = read_json(Path(argv[1]))
    if spec is None:
        logger.error("Cannot read the launch record %s", argv[1])
        return 2
    try:
        rc = run(spec)
    except Exception as exc:
        logger.exception("The job could not be run")
        try:
            finalize_job_row(
                spec["job_id"], JobStatus.FAILED, error_message=f"Job runner failed: {exc}"
            )
        except Exception:
            logger.exception("Could not record the failure")
        return 1
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
