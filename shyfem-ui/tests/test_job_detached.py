"""J-01: a local job outlives the web worker that started it.

Shiny Server stops an idle worker 5 s after its last connection. uvicorn's
shutdown cancels every asyncio task, and before J-01 the job's task then
killed the tool's process group and recorded "Job was cancelled". These tests
run a real supervisor (``python -m shyfem_ui.job_runner``) and a fake tool
script against a scratch database, and check:

- a cancel that the user did not ask for (a worker stopping) leaves the tool
  running and the row active;
- the supervisor ends the row itself when nobody is watching;
- a user's cancel still kills the tool and ends the job CANCELLED;
- a new worker re-attaches to a live supervisor, or reports the end from the
  exit record, instead of marking the job orphaned.
"""

import asyncio
import os
import signal
import time
from pathlib import Path

import pytest

from shyfem_ui.services.job_detached import JobFiles, read_json, write_json_atomic
from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.job_queue import JobSpec, JobStatus


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A scratch database that the supervisor subprocess also sees: it
    inherits SHYFEM_UI_DATABASE_URL from this process's environment."""
    import shyfem_ui.config as cfg
    import shyfem_ui.db.base as dbb

    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
    monkeypatch.setattr(cfg, "_config", None)
    monkeypatch.setattr(dbb, "_engine", None)
    monkeypatch.setattr(dbb, "_SessionLocal", None)
    dbb.init_db()
    yield
    # Leave the next test a fresh engine/config again.
    monkeypatch.setattr(dbb, "_engine", None)
    monkeypatch.setattr(dbb, "_SessionLocal", None)
    monkeypatch.setattr(cfg, "_config", None)


@pytest.fixture
def shyfem_dir(tmp_path):
    d = tmp_path / "shyfem"
    (d / "bin").mkdir(parents=True)
    return d


@pytest.fixture
def groups():
    """Process groups started by a test; any still alive are killed after it."""
    started: list[int] = []
    yield started
    for pgid in started:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _tool(shyfem_dir: Path, body: str, name: str = "shypre") -> None:
    exe = shyfem_dir / "bin" / name
    exe.write_text("#!/bin/bash\n" + body)
    exe.chmod(0o755)


def _queue(shyfem_dir: Path) -> LocalJobQueue:
    q = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    q._history_loaded = True  # fresh DB; nothing to load
    return q


def _spec(work: Path, tool: str = "shypre") -> JobSpec:
    return JobSpec(name="j01", tool_name=tool, args=[], working_dir=work)


def _row(job_id: str):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Job

    with db_session() as s:
        row = s.query(Job).filter(Job.job_uuid == job_id).first()
        return (
            None
            if row is None
            else {
                "status": row.status,
                "return_code": row.return_code,
                "error_message": row.error_message,
                "output_files": row.output_files,
            }
        )


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); it is not running.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


async def _until(predicate, timeout: float = 15.0, step: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(step)
    raise AssertionError("condition not met in time")


def _read_pid(path: Path):
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    return int(text) if text else None


async def _stop_watching(queue: LocalJobQueue, job_id: str) -> None:
    """What a worker shutdown does to a job's task: cancel it, with no
    user cancel recorded."""
    task = queue._tasks[job_id]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_worker_shutdown_leaves_the_tool_running(db, shyfem_dir, tmp_path, groups):
    pidfile = tmp_path / "tool.pid"
    _tool(shyfem_dir, f"echo $$ > '{pidfile}'\nwhile true; do echo tick; sleep 0.1; done\n")
    queue = _queue(shyfem_dir)
    job_id = await queue.submit(_spec(tmp_path / "work"))
    pid = await _until(lambda: _read_pid(pidfile))
    groups.append(os.getpgid(pid))

    await _stop_watching(queue, job_id)
    await asyncio.sleep(1.0)

    assert _alive(pid), "a worker stopping must not kill the job's tool"
    assert _row(job_id)["status"] == JobStatus.RUNNING
    # The tool keeps writing its log with no worker reading a pipe.
    stdout = Path(queue._jobs[job_id].stdout_file)
    size = stdout.stat().st_size
    await asyncio.sleep(0.5)
    assert stdout.stat().st_size > size


@pytest.mark.asyncio
async def test_job_ends_with_no_worker_watching(db, shyfem_dir, tmp_path, groups):
    pidfile = tmp_path / "tool.pid"
    _tool(shyfem_dir, f"echo $$ > '{pidfile}'\nsleep 1\necho made > out.bas\necho done\n")
    queue = _queue(shyfem_dir)
    job_id = await queue.submit(_spec(tmp_path / "work"))
    pid = await _until(lambda: _read_pid(pidfile))
    groups.append(os.getpgid(pid))
    await _stop_watching(queue, job_id)

    row = await _until(lambda: (r := _row(job_id)) and r["status"] != JobStatus.RUNNING and r)
    assert row["status"] == JobStatus.COMPLETED
    assert row["return_code"] == 0
    assert [Path(p).name for p in row["output_files"]] == ["out.bas"]


@pytest.mark.asyncio
async def test_user_cancel_kills_the_tool(db, shyfem_dir, tmp_path, groups):
    pidfile = tmp_path / "tool.pid"
    _tool(shyfem_dir, f"echo $$ > '{pidfile}'\nsleep 60\n")
    queue = _queue(shyfem_dir)
    job_id = await queue.submit(_spec(tmp_path / "work"))
    pid = await _until(lambda: _read_pid(pidfile))
    groups.append(os.getpgid(pid))

    assert await queue.cancel(job_id) is True

    await _until(lambda: not _alive(pid), timeout=5)
    await asyncio.sleep(1.0)  # let the supervisor try (and fail) to record a failure
    row = _row(job_id)
    assert row["status"] == JobStatus.CANCELLED
    assert row["error_message"] == "Job was cancelled"


@pytest.mark.asyncio
async def test_failure_keeps_the_end_of_stderr(db, shyfem_dir, tmp_path):
    _tool(
        shyfem_dir,
        "for i in $(seq 1 200); do echo 'warning: something minor' >&2; done\n"
        "echo 'STOP error stop handle_basin_read: no bas or grd file' >&2\nexit 2\n",
    )
    queue = _queue(shyfem_dir)
    job_id = await queue.submit(_spec(tmp_path / "work"))
    job = await _until(lambda: (j := queue._jobs[job_id]) and not j.is_active and j)

    assert job.status == JobStatus.FAILED
    assert job.return_code == 2
    assert job.error_message.rstrip().endswith("no bas or grd file")
    assert _row(job_id)["status"] == JobStatus.FAILED


@pytest.mark.asyncio
async def test_new_worker_watches_a_job_still_running(db, shyfem_dir, tmp_path, groups):
    pidfile = tmp_path / "tool.pid"
    _tool(shyfem_dir, f"echo $$ > '{pidfile}'\nsleep 2\necho done\n")
    first = _queue(shyfem_dir)
    job_id = await first.submit(_spec(tmp_path / "work"))
    pid = await _until(lambda: _read_pid(pidfile))
    groups.append(os.getpgid(pid))
    await _stop_watching(first, job_id)

    second = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)  # loads history
    job = await second.get_status(job_id)
    assert job.status == JobStatus.RUNNING, "a live job must not be reported orphaned"
    assert job_id in second._tasks, "the new worker must watch it"

    job = await _until(lambda: (j := second._jobs[job_id]) and not j.is_active and j)
    assert job.status == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_new_worker_reports_an_end_nobody_recorded(db, shyfem_dir, tmp_path):
    """The supervisor wrote its exit record but died before ending the row."""
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Job

    work = tmp_path / "work"
    work.mkdir()
    job_id = "11111111-2222-3333-4444-555555555555"
    files = JobFiles.for_stdout(work / f"{job_id}.stdout")
    files.stdout.write_text("done\n")
    (work / "out.bas").write_text("x")
    write_json_atomic(
        files.spec,
        {
            "job_id": job_id,
            "cmd": ["shypre"],
            "cwd": str(work),
            "stdout_file": str(files.stdout),
            "tool_name": "shypre",
            "before_snapshot": {},
        },
    )
    write_json_atomic(files.pid, {"runner_pid": 999999999, "pgid": 999999999})
    write_json_atomic(files.exit, {"return_code": 0, "timed_out": False})
    with db_session() as s:
        s.add(
            Job(
                job_uuid=job_id,
                name="j",
                job_type="shypre",
                working_dir=str(work),
                status=JobStatus.RUNNING,
                stdout_file=str(files.stdout),
            )
        )

    queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=2)
    job = await queue.get_status(job_id)

    assert job.status == JobStatus.COMPLETED
    assert [Path(p).name for p in job.output_files] == ["out.bas"]
    assert _row(job_id)["status"] == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_exit_record_and_pid_record_are_written(db, shyfem_dir, tmp_path):
    _tool(shyfem_dir, "echo hi\nexit 0\n")
    queue = _queue(shyfem_dir)
    job_id = await queue.submit(_spec(tmp_path / "work"))
    await _until(lambda: not queue._jobs[job_id].is_active)

    files = JobFiles.for_stdout(queue._jobs[job_id].stdout_file)
    assert read_json(files.exit)["return_code"] == 0
    assert read_json(files.pid)["runner_pid"] > 0
    assert files.stdout.read_text() == "hi\n"
    # The launch record holds only what the run adds, never this process's
    # environment: it sits in a directory the user can read.
    spec = read_json(files.spec)
    assert set(spec["env"]) == {"SHYFEMDIR"}


@pytest.mark.asyncio
async def test_cancel_after_a_restart_kills_the_tool(db, shyfem_dir, tmp_path, groups):
    """A user can still cancel a job the new worker only re-attached to."""
    pidfile = tmp_path / "tool.pid"
    _tool(shyfem_dir, f"echo $$ > '{pidfile}'\nsleep 60\n")
    first = _queue(shyfem_dir)
    job_id = await first.submit(_spec(tmp_path / "work"))
    pid = await _until(lambda: _read_pid(pidfile))
    groups.append(os.getpgid(pid))
    await _stop_watching(first, job_id)

    second = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    assert (await second.get_status(job_id)).status == JobStatus.RUNNING
    assert await second.cancel(job_id) is True

    await _until(lambda: not _alive(pid), timeout=5)
    assert _row(job_id)["status"] == JobStatus.CANCELLED


def test_job_file_names_cannot_be_uploaded():
    """A user must not plant or replace a job's log or bookkeeping files."""
    from shyfem_ui.services.file_service import _JOB_FILE_NAME

    job_id = "3b4a2e1a-1494-4d4c-b387-29ecfade0502"
    for suffix in ("stdout", "stderr", "job", "pid", "exit"):
        assert _JOB_FILE_NAME.match(f"{job_id}.{suffix}")
    for ok in ("run.pid", "results.job", f"{job_id}.str", "wind.fem"):
        assert not _JOB_FILE_NAME.match(ok)


@pytest.mark.asyncio
async def test_cancel_ignores_an_edited_pid_file(db, shyfem_dir, tmp_path, groups):
    """The pid file sits in a directory the user can write. Pointing it at
    another process must not make a cancel signal that process."""
    import subprocess

    bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
    groups.append(bystander.pid)
    pidfile = tmp_path / "tool.pid"
    _tool(shyfem_dir, f"echo $$ > '{pidfile}'\nsleep 60\n")
    queue = _queue(shyfem_dir)
    job_id = await queue.submit(_spec(tmp_path / "work"))
    pid = await _until(lambda: _read_pid(pidfile))
    groups.append(os.getpgid(pid))
    files = JobFiles.for_stdout(queue._jobs[job_id].stdout_file)
    await _until(lambda: files.pid.exists())
    write_json_atomic(files.pid, {"runner_pid": bystander.pid, "pgid": bystander.pid})

    assert await queue.cancel(job_id) is True

    await _until(lambda: not _alive(pid), timeout=5)
    assert bystander.poll() is None, "a cancel must not signal a process named in the file"
    bystander.kill()


@pytest.mark.asyncio
async def test_records_the_server_acts_on_are_not_in_the_job_dir(db, shyfem_dir, tmp_path):
    """Only the two logs go where the user can write; the launch, pid and
    exit records live in the server-only state directory."""
    from shyfem_ui.config import get_config

    _tool(shyfem_dir, "echo hi\n")
    queue = _queue(shyfem_dir)
    work = tmp_path / "work"
    job_id = await queue.submit(_spec(work))
    await _until(lambda: not queue._jobs[job_id].is_active)

    assert sorted(p.name for p in work.iterdir()) == [f"{job_id}.stderr", f"{job_id}.stdout"]
    state = Path(get_config().job_state_dir)
    assert {p.name for p in state.iterdir()} >= {f"{job_id}.job", f"{job_id}.pid", f"{job_id}.exit"}
    assert oct(state.stat().st_mode & 0o777) == oct(0o700)


def test_liveness_needs_the_exact_supervisor_command_line(tmp_path):
    """A process that merely mentions the job id and module is not it."""
    import subprocess

    from shyfem_ui.services.job_detached import supervisor_alive

    job_id = "3b4a2e1a-1494-4d4c-b387-29ecfade0502"
    impostor = subprocess.Popen(
        ["sleep", "30", "-m", f"shyfem_ui.job_runner{job_id}"],
        stderr=subprocess.DEVNULL,
    )
    try:
        assert not supervisor_alive(impostor.pid, job_id)
    finally:
        impostor.kill()
        impostor.wait()
