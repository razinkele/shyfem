"""X-01: a SHYFEM run or tool call that stopped on an error is a failure.

gfortran's ``stop 'message'`` exits with status 0. The core has about a
thousand ``stop 'error stop …'`` sites, and every tool's command-line parser
ends an unknown option with ``stop 'clo_usage: usage displayed'``. The UI used
the exit status alone, so a missing basin, an over-long STR line, an end time
before the start, or a flag the tool does not have all showed as COMPLETED or
"completed successfully" (2026-10-19 UI review, X-01).
"""

import asyncio
import time
from pathlib import Path

import pytest

from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper, tool_failure

FOOTER = " simulation start:   2026-07-21::22:08:41\n simulation end:     2026-07-21::22:08:44\n"


class TestToolFailure:
    def test_error_stop_on_stderr(self):
        reason = tool_failure("shyfem", 0, FOOTER, "STOP error stop setup_time: dtend\n")
        assert reason and "setup_time: dtend" in reason

    def test_basin_not_found(self):
        stderr = "STOP error stop handle_basin_read: no bas or grd file\n"
        assert tool_failure("shyfem", 0, " reading basin: GRID/MM\n", stderr)

    def test_unknown_option_is_a_failure(self):
        stdout = " *** no such option: weighted\n Usage: shyparts [-h|-help] [-options] grd-file\n"
        reason = tool_failure("shyparts", 0, stdout, "STOP clo_usage: usage displayed\n")
        assert reason and "no such option: weighted" in reason

    def test_shyfem_without_its_end_footer_did_not_finish(self):
        assert tool_failure("shyfem", 0, " itanf,itend,idt : 0 300 300\n", "")

    def test_shyfem_petsc_needs_the_footer_too(self):
        assert tool_failure("shyfem-petsc", 0, "", "")
        assert tool_failure("shyfem-petsc", 0, FOOTER, "") is None

    def test_finished_shyfem_run_is_fine(self):
        assert tool_failure("shyfem", 0, "step lines\n" + FOOTER, "") is None

    def test_a_tool_that_says_done_is_fine(self):
        assert (
            tool_failure("shyelab", 0, " output written to file out.shy\n", "STOP shyelab1: done\n")
            is None
        )

    def test_a_nonzero_exit_is_left_to_the_exit_status(self):
        assert tool_failure("shyfem", 1, "", "") is None


@pytest.fixture
def wrapper(tmp_path):
    d = tmp_path / "shyfem"
    (d / "bin").mkdir(parents=True)
    return ShyfemWrapper(d)


def _tool(wrapper: ShyfemWrapper, name: str, body: str) -> None:
    exe = wrapper.bin_dir / name
    exe.write_text("#!/bin/bash\n" + body)
    exe.chmod(0o755)


@pytest.mark.asyncio
async def test_run_command_reports_an_error_stop_as_a_failure(wrapper, tmp_path):
    _tool(
        wrapper,
        "shybas",
        "echo ' *** no such option: info' \necho 'STOP clo_usage: usage displayed' >&2\n",
    )
    result = await wrapper.run_command("shybas", ["-info", "x.grd"], tmp_path / "w")
    assert result.return_code == 0
    assert result.success is False
    assert "no such option: info" in result.stderr


@pytest.mark.asyncio
async def test_run_command_without_stdout_capture_still_sees_the_footer(wrapper, tmp_path):
    _tool(wrapper, "shyfem", f"for i in $(seq 1 500); do echo step $i; done\nprintf '{FOOTER}'\n")
    result = await wrapper.run_command("shyfem", ["a.str"], tmp_path / "w", capture_stdout=False)
    assert result.success is True


# --- queued jobs, through the real supervisor -------------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    import shyfem_ui.config as cfg
    import shyfem_ui.db.base as dbb

    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
    monkeypatch.setattr(cfg, "_config", None)
    monkeypatch.setattr(dbb, "_engine", None)
    monkeypatch.setattr(dbb, "_SessionLocal", None)
    dbb.init_db()
    yield
    monkeypatch.setattr(dbb, "_engine", None)
    monkeypatch.setattr(dbb, "_SessionLocal", None)
    monkeypatch.setattr(cfg, "_config", None)


def _record_job_ends(queue) -> set[str]:
    """Ids of the jobs whose end ``queue`` has announced (register before submit).

    The queue announces a job's end only after the row records it, whether
    the job's supervisor wrote it or the queue did, so this, not the
    in-memory status, is when the row can be read.
    """
    from shyfem_ui.services.job_queue import JobStatus

    ended: set[str] = set()
    terminal = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)

    def on_event(event) -> None:
        if event.kind == "status" and event.status in terminal:
            ended.add(event.job_id)

    queue.add_event_callback("test-job-ends", on_event)
    return ended


async def _finished(queue, job_id, ended: set[str], timeout=15.0):
    """The job once the queue has announced its end.

    This used to return as soon as the in-memory status left the active
    states. That status changes when the tool exits, while the supervisor
    writes the row a moment later (after scanning for output files), so the
    row read right after was sometimes still "running" (flaky, about 1 run in
    15; every time with that write delayed by 0.5 s).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job_id in ended:
            return queue._jobs[job_id]
        await asyncio.sleep(0.05)
    raise AssertionError("the queue never announced the end of the job")


def _row_status(job_id):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Job

    with db_session() as s:
        return s.query(Job).filter(Job.job_uuid == job_id).one().status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body, expected",
    [
        (
            "echo ' reading basin: GRID/MM'\necho 'STOP error stop handle_basin_read: no bas' >&2\n",
            "failed",
        ),
        ("echo ' itanf,itend,idt : 0 0 300'\n", "failed"),
        (f"echo step\nprintf '{FOOTER}'\n", "completed"),
    ],
)
async def test_queued_shyfem_job_status(db, tmp_path, body, expected):
    from shyfem_ui.services.job_local import LocalJobQueue
    from shyfem_ui.services.job_queue import JobSpec

    shyfem_dir = tmp_path / "shyfem"
    (shyfem_dir / "bin").mkdir(parents=True)
    exe = shyfem_dir / "bin" / "shyfem"
    exe.write_text("#!/bin/bash\n" + body)
    exe.chmod(0o755)
    queue = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    queue._history_loaded = True
    ended = _record_job_ends(queue)
    job_id = await queue.submit(
        JobSpec(name="x01", tool_name="shyfem", args=["a.str"], working_dir=tmp_path / "work")
    )
    job = await _finished(queue, job_id, ended)

    assert job.status.value == expected
    assert _row_status(job_id).value == expected
    assert job.return_code == 0
    if expected == "failed":
        assert job.error_message and job.error_message != "Unknown error"
        assert Path(job.stderr_file).exists()
