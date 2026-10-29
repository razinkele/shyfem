"""J-05: a cancelled workflow is recorded CANCELLED, not FAILED.

Each Run page session builds its own ``WorkflowEngine``, so the driver task
of a workflow lives in the session that launched it. A cancel from any other
session (an admin, or the owner after a reload) cancelled the step job and
wrote CANCELLED, but could not stop the driver: it then saw its job end
CANCELLED and overwrote the row with FAILED "Step ... failed", and between
steps it overwrote CANCELLED with RUNNING and went on to the next step.
"""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.models import workflow as _wf_model  # noqa: F401 -- register models
from shyfem_ui.services.job_queue import JobInfo, JobStatus
from shyfem_ui.services.workflow import WorkflowEngine, WorkflowStatus


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield lambda: session
    session.close()


@pytest.fixture()
def queue():
    q = MagicMock()
    jobs: dict[str, JobInfo] = {}

    async def submit(spec):
        job_id = f"job-{len(jobs) + 1}"
        jobs[job_id] = JobInfo(
            id=job_id,
            name=spec.name,
            tool_name=spec.tool_name,
            args=spec.args,
            working_dir=str(spec.working_dir),
            status=JobStatus.RUNNING,
            created_at=datetime.now(),
        )
        return job_id

    async def get_status(job_id):
        return jobs.get(job_id)

    async def cancel(job_id):
        if not jobs[job_id].is_active:
            return False  # like the real queues: a finished job stays as it ended
        jobs[job_id].status = JobStatus.CANCELLED
        jobs[job_id].error_message = "Job was cancelled"
        return True

    q.submit, q.get_status, q.cancel, q.jobs = submit, get_status, cancel, jobs
    return q


async def _wait(pred, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_cancel_from_another_session_is_recorded_cancelled(
    queue, session_factory, tmp_path, monkeypatch
):
    orig_wait = WorkflowEngine._wait_for_job

    async def fast_wait(self, job_id, poll_interval=2.0):
        return await orig_wait(self, job_id, poll_interval=0.01)

    monkeypatch.setattr(WorkflowEngine, "_wait_for_job", fast_wait)

    launcher = WorkflowEngine(queue, session_factory=session_factory)
    other = WorkflowEngine(queue, session_factory=session_factory)  # another session
    wf_id = await launcher.create_workflow(
        "full_simulation",
        working_dir=tmp_path,
        params={"input_grd": "/tmp/t.grd", "input_str": "/tmp/t.str"},
    )
    await _wait(lambda: "job-1" in queue.jobs)

    assert await other.cancel_workflow(wf_id) is True
    await _wait(lambda: wf_id not in launcher._polling_tasks)

    wf = launcher.get_workflow(wf_id)
    assert wf.status == WorkflowStatus.CANCELLED, (wf.status, wf.error_message)
    assert list(queue.jobs) == ["job-1"], "a cancelled workflow must not start its next step"


@pytest.mark.asyncio
async def test_a_cancel_landing_between_steps_is_kept(
    queue, session_factory, tmp_path, monkeypatch
):
    """The cancel lands after the step job finished (nothing left to kill):
    the driver's next save wrote RUNNING over CANCELLED and the next step
    started."""
    orig_wait = WorkflowEngine._wait_for_job
    gate = asyncio.Event()

    async def gated_wait(self, job_id, poll_interval=2.0):
        info = await orig_wait(self, job_id, poll_interval=0.01)
        await gate.wait()
        return info

    monkeypatch.setattr(WorkflowEngine, "_wait_for_job", gated_wait)

    launcher = WorkflowEngine(queue, session_factory=session_factory)
    other = WorkflowEngine(queue, session_factory=session_factory)
    wf_id = await launcher.create_workflow(
        "full_simulation",
        working_dir=tmp_path,
        params={"input_grd": "/tmp/t.grd", "input_str": "/tmp/t.str"},
    )
    await _wait(lambda: "job-1" in queue.jobs)
    queue.jobs["job-1"].status = JobStatus.COMPLETED
    queue.jobs["job-1"].return_code = 0
    queue.jobs["job-1"].output_files = ["/tmp/out.bas"]
    await asyncio.sleep(0.05)  # the driver has the finished step in hand

    assert await other.cancel_workflow(wf_id) is True
    gate.set()
    await _wait(lambda: wf_id not in launcher._polling_tasks)

    assert launcher.get_workflow(wf_id).status == WorkflowStatus.CANCELLED
    assert list(queue.jobs) == ["job-1"], "a cancelled workflow must not start its next step"
