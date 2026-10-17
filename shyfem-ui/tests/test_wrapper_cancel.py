"""Tests for job-cancellation process-group cleanup (N14) and run_shyfem's
options-list copy (F49).

N14: run_command() only killed the child on asyncio.TimeoutError. Task
cancellation (LocalJobQueue.cancel -> task.cancel()) raises CancelledError,
which is a BaseException that neither `except asyncio.TimeoutError` nor
`except Exception` catches, so the spawned shyfem/mpirun process (and any of
its own children) kept running unsupervised after the UI reported the job as
CANCELLED. Fix: spawn with start_new_session=True (child leads its own
process group) and terminate that whole group (SIGTERM, grace, SIGKILL) on
both cancellation and timeout, re-raising CancelledError afterwards.

F49: run_shyfem() did `args_list = options or []` then `args_list.append(...)`,
aliasing and mutating the caller's list. The other five wrapper methods
already copy (`list(options) if options else []`); run_shyfem did not.
"""

import asyncio
import os
import time

import pytest

from shyfem_ui.services.shyfem_wrapper import CommandResult, ShyfemWrapper


@pytest.fixture
def wrapper(tmp_path):
    """Create a wrapper with a temporary SHYFEM directory."""
    shyfem_dir = tmp_path / "shyfem"
    shyfem_dir.mkdir()
    (shyfem_dir / "bin").mkdir()
    return ShyfemWrapper(shyfem_dir)


async def _wait_for_file(path, timeout=5.0):
    """Poll until a file exists and has content, or raise on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        await asyncio.sleep(0.02)
    raise TimeoutError(f"{path} was never written")


class TestProcessGroupCleanup:
    """(a) and (b) from the task brief."""

    @pytest.mark.asyncio
    async def test_child_leads_its_own_process_group(self, wrapper, tmp_path):
        """The spawned child must be the leader of its own process group
        (pgid == pid), otherwise a killpg() would take down the whole
        server process tree instead of just the job."""
        pidfile = tmp_path / "pid.txt"
        exe = wrapper.bin_dir / "shyfem"
        exe.write_text(f"#!/bin/bash\necho $$ > '{pidfile}'\nsleep 1\n")
        exe.chmod(0o755)

        task = asyncio.create_task(wrapper.run_command("shyfem", [], tmp_path))
        try:
            pid = int(await _wait_for_file(pidfile))
            assert os.getpgid(pid) == pid, (
                "child is not its own process-group leader; "
                "start_new_session=True is required before any group kill"
            )
        finally:
            result = await task
            assert result.success is True

    @pytest.mark.asyncio
    async def test_cancel_kills_process_group_within_2s(self, wrapper, tmp_path):
        """Cancelling the asyncio task running run_command must leave no
        live child (including grandchildren spawned in the background,
        the way mpirun spawns rank processes) within ~2s."""
        pidfile = tmp_path / "child.pid"
        exe = wrapper.bin_dir / "shyfem"
        # The "real" work happens in a background grandchild so this test
        # actually proves process-GROUP cleanup, not just killing proc.pid.
        exe.write_text(f"#!/bin/bash\nsleep 60 &\necho $! > '{pidfile}'\nwait\n")
        exe.chmod(0o755)

        task = asyncio.create_task(wrapper.run_command("shyfem", [], tmp_path))
        child_pid = int(await _wait_for_file(pidfile))

        # Confirm the grandchild is alive before cancelling.
        os.kill(child_pid, 0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        deadline = time.monotonic() + 2.0
        alive = True
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                alive = False
                break
            await asyncio.sleep(0.05)

        assert not alive, (
            f"child pid {child_pid} still alive ~2s after task.cancel(); "
            "cancellation leaked the spawned subprocess"
        )


class TestRunShyfemOptionsNotMutated:
    """(c) from the task brief."""

    @pytest.fixture
    def wrapper(self, tmp_path):
        shyfem_dir = tmp_path / "shyfem"
        shyfem_dir.mkdir()
        (shyfem_dir / "bin").mkdir()
        return ShyfemWrapper(shyfem_dir)

    @pytest.mark.asyncio
    async def test_run_shyfem_does_not_mutate_options(self, wrapper, tmp_path, monkeypatch):
        captured = []

        async def fake_run(name, args, *a, **k):
            captured.append(list(args))
            return CommandResult(True, 0, "", "", name, str(tmp_path))

        monkeypatch.setattr(wrapper, "run_command", fake_run)
        opts = ["-noconsole"]

        await wrapper.run_shyfem("run1.str", tmp_path, options=opts)
        # the caller's list must be untouched
        assert opts == ["-noconsole"]
        assert captured[0][-1].endswith("run1.str")

        # a second run with the SAME list must not carry run1.str as an extra arg
        await wrapper.run_shyfem("run2.str", tmp_path, options=opts)
        assert opts == ["-noconsole"]
        assert captured[1].count("run1.str") == 0
        assert captured[1][-1].endswith("run2.str")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class TestUnexpectedErrorKillsProcessGroup:
    """Only a timeout and a cancellation used to terminate the child. Any
    other error while reading its output (a failing output_callback -- the
    local queue's log write on a full disk -- or a line over asyncio's 64 KiB
    readline limit) fell through to the outer handler, which reported the job
    failed and left the whole shyfem/mpirun group running unsupervised."""

    @pytest.mark.asyncio
    async def test_failing_output_callback_kills_the_group(self, wrapper, tmp_path):
        pidfile = tmp_path / "child.pid"
        exe = wrapper.bin_dir / "shyfem"
        exe.write_text(
            f"#!/bin/bash\nsleep 60 &\necho $! > '{pidfile}'\n"
            "while true; do echo working; sleep 0.1; done\n"
        )
        exe.chmod(0o755)

        def _disk_full(_line):
            raise OSError(28, "No space left on device")

        result = await asyncio.wait_for(
            wrapper.run_command("shyfem", [], tmp_path, output_callback=_disk_full), timeout=10
        )
        assert result.success is False
        assert "No space left on device" in result.stderr
        grandchild = int(pidfile.read_text().strip())
        deadline = time.monotonic() + 2
        while _alive(grandchild) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert not _alive(grandchild), "process group left running after the error"

    @pytest.mark.asyncio
    async def test_over_long_output_line_kills_the_group(self, wrapper, tmp_path):
        pidfile = tmp_path / "child.pid"
        exe = wrapper.bin_dir / "shyfem"
        exe.write_text(
            f"#!/bin/bash\nsleep 60 &\necho $! > '{pidfile}'\n"
            "head -c 200000 /dev/zero | tr '\\0' x\necho\nwait\n"
        )
        exe.chmod(0o755)

        result = await asyncio.wait_for(wrapper.run_command("shyfem", [], tmp_path), timeout=10)
        assert result.success is False
        grandchild = int(pidfile.read_text().strip())
        deadline = time.monotonic() + 2
        while _alive(grandchild) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert not _alive(grandchild), "process group left running after the error"

    @pytest.mark.asyncio
    async def test_failing_progress_callback_does_not_stop_the_run(self, wrapper, tmp_path, caplog):
        """Progress is advisory: a failing progress write (e.g. a Redis blip
        under Celery) must not fail -- or orphan -- a long simulation."""
        exe = wrapper.bin_dir / "shyfem"
        exe.write_text('#!/bin/bash\nfor i in 1 2 3; do echo "time = $i of 3"; done\n')
        exe.chmod(0o755)
        calls = []

        def _flaky(progress, _line):
            calls.append(progress)
            raise ConnectionError("redis blip")

        result = await wrapper.run_command("shyfem", [], tmp_path, progress_callback=_flaky)
        assert result.success is True
        assert len(calls) == 3
        assert caplog.text.count("Progress update failed") == 1  # logged once, not per line
