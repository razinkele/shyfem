"""Tests for ensemble page helper functions."""

import pytest

from shyfem_ui.pages.ensemble import _cancel_jobs


class _MockJobQueue:
    """Mock job queue for testing cancel behavior."""
    def __init__(self, results: dict[str, bool | Exception]):
        self._results = results
        self.cancel_calls = []

    async def cancel(self, job_id: str) -> bool:
        self.cancel_calls.append(job_id)
        result = self._results.get(job_id, False)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
class TestCancelJobs:
    async def test_all_succeed(self):
        queue = _MockJobQueue({"j1": True, "j2": True, "j3": True})
        count = await _cancel_jobs(queue, ["j1", "j2", "j3"])
        assert count == 3
        assert queue.cancel_calls == ["j1", "j2", "j3"]

    async def test_some_fail(self):
        queue = _MockJobQueue({"j1": True, "j2": False, "j3": True})
        count = await _cancel_jobs(queue, ["j1", "j2", "j3"])
        assert count == 2

    async def test_exception_continues(self):
        queue = _MockJobQueue({"j1": True, "j2": RuntimeError("oops"), "j3": True})
        count = await _cancel_jobs(queue, ["j1", "j2", "j3"])
        assert count == 2
        assert len(queue.cancel_calls) == 3  # all three were attempted

    async def test_empty_list(self):
        queue = _MockJobQueue({})
        count = await _cancel_jobs(queue, [])
        assert count == 0
