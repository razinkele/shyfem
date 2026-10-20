"""Shared pieces of a detached local job (J-01).

A local job used to run as a child of the Shiny worker, joined to it by an
asyncio task and two pipes. Shiny Server stops an idle worker 5 s after its
last connection; uvicorn's shutdown then cancelled every task, and the
cancel branch killed the job's process group. A run therefore lived only as
long as some browser tab stayed open.

A detached job is owned by a small supervisor process instead
(``python -m shyfem_ui.job_runner``). The supervisor runs in its own session,
writes the tool's stdout and stderr straight to files, records the exit
status, and finalizes the job's DB row itself. The web worker only watches.
If the worker goes away, the run carries on; the next worker finds the
supervisor alive and watches again, or finds the exit record and reports it.

Every file lives next to the job's existing ``<job_id>.stdout``:

- ``<job_id>.job``  launch record: command, cwd, tool, output snapshot
- ``<job_id>.pid``  supervisor pid and the tool's process-group id
- ``<job_id>.exit`` exit record: return code and whether it timed out

Exactly one writer ends a job: :func:`finalize_job_row` changes a row only
while it is still active, so the supervisor, a watching worker and a user's
cancel cannot both win, and only the winner sends the completion email.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shyfem_ui.services.job_queue import JobStatus

logger = logging.getLogger(__name__)

#: Sidecar suffixes, for code that hides or skips job bookkeeping files.
SIDECAR_SUFFIXES = (".job", ".pid", ".exit")

ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)


@dataclass(frozen=True)
class JobFiles:
    """The files of one detached job, all derived from its stdout path."""

    stdout: Path
    stderr: Path
    spec: Path
    pid: Path
    exit: Path

    @classmethod
    def for_stdout(cls, stdout_file: str | Path) -> JobFiles:
        stdout = Path(stdout_file)
        stem = stdout.with_suffix("")  # <wd>/<job_id>
        return cls(
            stdout=stdout,
            stderr=stem.with_suffix(".stderr"),
            spec=stem.with_suffix(".job"),
            pid=stem.with_suffix(".pid"),
            exit=stem.with_suffix(".exit"),
        )

    def all(self) -> tuple[Path, ...]:
        return (self.stdout, self.stderr, self.spec, self.pid, self.exit)


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` so a reader sees either nothing or the whole record."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path) -> dict[str, Any] | None:
    """The record at ``path``, or None if it is absent or unreadable."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def supervisor_alive(pid: int | None, job_id: str) -> bool:
    """True if ``pid`` is a live supervisor for ``job_id``.

    A pid can be reused after a reboot or a long uptime, so a bare existence
    check would keep a dead job "running" for ever. The supervisor's command
    line names its launch record, which contains the job id.
    """
    if not pid or pid <= 0:
        return False
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    if not raw:  # a zombie has an empty cmdline
        return False
    return job_id.encode() in raw and b"shyfem_ui.job_runner" in raw


def tail_text(text: str, limit: int = 1000) -> str:
    """The last ``limit`` characters: a tool prints its fatal error last."""
    return text if len(text) <= limit else text[-limit:]


def read_tail(path: Path, limit: int = 1000) -> str:
    """The last ``limit`` characters of a text file, or "" if unreadable."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 4 * limit))
            return tail_text(fh.read().decode("utf-8", errors="replace"), limit)
    except OSError:
        return ""


def finalize_job_row(
    job_id: str,
    status: JobStatus,
    *,
    return_code: int | None = None,
    error_message: str | None = None,
    output_files: list[str] | None = None,
    progress: float | None = None,
    completed_at: datetime | None = None,
) -> bool:
    """End the job's row if it is still active. Returns True if this call did.

    The guard is in the UPDATE itself, so two processes racing to end the same
    job (the supervisor and a watching worker, or either of them and a user's
    cancel) cannot both succeed; the loser sees False and must not email.
    """
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Job

    values: dict[str, Any] = {
        Job.status: status,
        Job.completed_at: completed_at or datetime.now(),
        Job.return_code: return_code,
        Job.error_message: error_message,
    }
    if output_files is not None:
        values[Job.output_files] = list(output_files)
    if progress is not None:
        values[Job.progress] = progress
    with db_session() as db:
        changed = (
            db.query(Job)
            .filter(Job.job_uuid == job_id, Job.status.in_(ACTIVE_STATUSES))
            .update(values, synchronize_session=False)
        )
    return changed == 1
