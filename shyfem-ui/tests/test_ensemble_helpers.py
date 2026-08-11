"""Tests for ensemble page helper functions."""

import pytest

from shyfem_ui.pages.ensemble import _cancel_jobs
from shyfem_ui.services.job_queue import JobInfo, JobStatus


def _job(jid: str, user_id=None, project_id=None) -> JobInfo:
    md: dict = {}
    if user_id is not None:
        md["user_id"] = user_id
    if project_id is not None:
        md["project_id"] = project_id
    return JobInfo(
        id=jid,
        name=jid,
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=JobStatus.RUNNING,
        metadata=md,
    )


class _MockJobQueue:
    """Mock job queue exposing get_status + cancel for authz-aware cancel tests."""

    def __init__(self, jobs: dict[str, JobInfo], cancel_results: dict | None = None):
        self._jobs = jobs
        self._results = cancel_results or {jid: True for jid in jobs}
        self.cancel_calls: list[str] = []

    async def get_status(self, job_id: str) -> JobInfo | None:
        return self._jobs.get(job_id)

    async def cancel(self, job_id: str) -> bool:
        self.cancel_calls.append(job_id)
        result = self._results.get(job_id, False)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
class TestCancelJobs:
    async def test_all_cancelled_local_mode(self):
        # Local mode (user=None legitimate): every job is cancellable.
        queue = _MockJobQueue({"j1": _job("j1"), "j2": _job("j2"), "j3": _job("j3")})
        cancelled, denied = await _cancel_jobs(
            queue, ["j1", "j2", "j3"], user=None, is_server_mode=False
        )
        assert (cancelled, denied) == (3, 0)
        assert queue.cancel_calls == ["j1", "j2", "j3"]

    async def test_owner_can_cancel_server_mode(self):
        jobs = {f"j{i}": _job(f"j{i}", user_id=5) for i in range(1, 4)}
        queue = _MockJobQueue(jobs)
        cancelled, denied = await _cancel_jobs(
            queue, list(jobs), user={"id": 5, "role": "user"}, is_server_mode=True
        )
        assert (cancelled, denied) == (3, 0)

    async def test_admin_can_cancel_server_mode(self):
        jobs = {f"j{i}": _job(f"j{i}", user_id=5) for i in range(1, 4)}
        queue = _MockJobQueue(jobs)
        cancelled, denied = await _cancel_jobs(
            queue, list(jobs), user={"id": 9, "role": "admin"}, is_server_mode=True
        )
        assert (cancelled, denied) == (3, 0)

    async def test_stranger_denied_server_mode(self):
        # Jobs owned by user 5, no project; actor 9 is neither owner nor admin.
        jobs = {f"j{i}": _job(f"j{i}", user_id=5) for i in range(1, 4)}
        queue = _MockJobQueue(jobs)
        cancelled, denied = await _cancel_jobs(
            queue, list(jobs), user={"id": 9, "role": "user"}, is_server_mode=True
        )
        assert (cancelled, denied) == (0, 3)
        assert queue.cancel_calls == []  # never reached the cancel sink

    async def test_unresolved_identity_denied_server_mode(self):
        jobs = {"j1": _job("j1", user_id=5)}
        queue = _MockJobQueue(jobs)
        cancelled, denied = await _cancel_jobs(queue, ["j1"], user=None, is_server_mode=True)
        assert (cancelled, denied) == (0, 1)

    async def test_missing_job_skipped(self):
        queue = _MockJobQueue({"j1": _job("j1")})
        cancelled, denied = await _cancel_jobs(
            queue, ["j1", "missing"], user=None, is_server_mode=False
        )
        assert cancelled == 1
        assert "missing" not in queue.cancel_calls

    async def test_cancel_failure_counted(self):
        queue = _MockJobQueue(
            {"j1": _job("j1"), "j2": _job("j2")}, cancel_results={"j1": True, "j2": False}
        )
        cancelled, denied = await _cancel_jobs(queue, ["j1", "j2"], user=None, is_server_mode=False)
        assert (cancelled, denied) == (1, 0)

    async def test_exception_continues(self):
        queue = _MockJobQueue(
            {"j1": _job("j1"), "j2": _job("j2"), "j3": _job("j3")},
            cancel_results={"j1": True, "j2": RuntimeError("oops"), "j3": True},
        )
        cancelled, denied = await _cancel_jobs(
            queue, ["j1", "j2", "j3"], user=None, is_server_mode=False
        )
        assert cancelled == 2
        assert len(queue.cancel_calls) == 3  # all attempted

    async def test_empty_list(self):
        queue = _MockJobQueue({})
        cancelled, denied = await _cancel_jobs(queue, [], user=None, is_server_mode=False)
        assert (cancelled, denied) == (0, 0)


class TestEnsembleSubmitSerializationFailure:
    """StrParser.save raises ValueError on a value the STR reader cannot
    express. Inside the per-combo submit loop that would abort mid-way:
    combos before the failure are already submitted and running, the
    failing combo leaves an orphan run directory with no job, and the
    remaining combos never exist — and since the raise escapes the
    effect, the session closes before any notification renders."""

    def _loop_source(self):
        import inspect

        from shyfem_ui.pages import ensemble

        src = inspect.getsource(ensemble)
        start = src.index("for i, combo in enumerate(combos)")
        return src[start : src.index("if job_ids:", start)]

    def test_per_combo_save_is_guarded(self):
        loop = self._loop_source()
        save = loop.index("StrParser.save(")
        assert "try:" in loop[:save], "the per-combo write must run inside a try block"
        assert "except ValueError" in loop[save:], "the writer's ValueError must be caught"

    def test_failure_reports_the_combo_and_continues(self):
        loop = self._loop_source()
        tail = loop[loop.index("StrParser.save(") :]
        handler = tail[tail.index("except ValueError") :]
        assert "notification_show" in handler, "the user must learn which run failed"
        assert "continue" in handler, "one bad combo must not abort the whole ensemble"
