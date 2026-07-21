"""Tests for output-file discovery by snapshot (N48).

_find_output_files used to glob() the whole working directory for a tool's
candidate extensions, unconditionally reporting every match. That meant job
results included pre-existing files (left over from an earlier job sharing
the same working directory) and any other job's files, breaking workflow
chaining ({step_name.output_files[0]} substitution in workflow.py) whenever
two steps reused a directory.

Fix: snapshot {path: mtime_ns} for the tool's extensions immediately before
launching the subprocess (_snapshot_output_files), then after completion only
report files that are new (absent from the snapshot) or modified (mtime
increased) (_find_output_files(..., before=snapshot)).

mtime comparisons use nanosecond resolution (stat().st_mtime_ns) and tests
bump mtimes explicitly via os.utime to avoid flakiness from filesystem mtime
granularity.
"""

import os
import time

import pytest

from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper


@pytest.fixture
def wrapper(tmp_path):
    """Create a wrapper with a temporary SHYFEM directory."""
    shyfem_dir = tmp_path / "shyfem"
    shyfem_dir.mkdir()
    (shyfem_dir / "bin").mkdir()
    return ShyfemWrapper(shyfem_dir)


class TestSnapshotOutputFiles:
    """_snapshot_output_files captures {path: mtime_ns} for the tool's
    candidate extensions only."""

    def test_snapshot_only_covers_tool_extensions(self, wrapper, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        matching = work_dir / "a.shy"
        matching.touch()
        (work_dir / "b.other").touch()

        snapshot = wrapper._snapshot_output_files("shyfem", work_dir)

        assert str(matching) in snapshot
        assert not any(str(work_dir / "b.other") == p for p in snapshot)

    def test_snapshot_records_mtime_ns(self, wrapper, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        f = work_dir / "a.bas"
        f.touch()

        snapshot = wrapper._snapshot_output_files("shypre", work_dir)

        assert snapshot[str(f)] == f.stat().st_mtime_ns

    def test_snapshot_empty_dir(self, wrapper, tmp_path):
        work_dir = tmp_path / "empty"
        work_dir.mkdir()

        assert wrapper._snapshot_output_files("shyfem", work_dir) == {}


class TestFindOutputFilesBySnapshot:
    """_find_output_files(tool, dir, before) only reports files that are new
    or modified relative to the ``before`` snapshot."""

    def test_preexisting_untouched_file_not_reported(self, wrapper, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        stale = work_dir / "stale.shy"
        stale.touch()
        before = wrapper._snapshot_output_files("shyfem", work_dir)

        files = wrapper._find_output_files("shyfem", work_dir, before)

        assert files == []

    def test_file_created_after_snapshot_is_reported(self, wrapper, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        before = wrapper._snapshot_output_files("shyfem", work_dir)

        new_file = work_dir / "new.shy"
        new_file.touch()

        files = wrapper._find_output_files("shyfem", work_dir, before)

        assert files == [str(new_file)]

    def test_preexisting_file_modified_after_snapshot_is_reported(self, wrapper, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        target = work_dir / "out.shy"
        target.touch()

        # Explicit mtime bumps (ns resolution) instead of relying on real
        # wall-clock deltas -- avoids flakes from coarse filesystem mtime
        # granularity.
        old_ns = target.stat().st_mtime_ns - 10_000_000_000  # 10s in the past
        os.utime(target, ns=(old_ns, old_ns))

        before = wrapper._snapshot_output_files("shyfem", work_dir)
        assert before[str(target)] == old_ns

        new_ns = old_ns + 5_000_000_000  # bumped forward, still < "now"
        os.utime(target, ns=(new_ns, new_ns))

        files = wrapper._find_output_files("shyfem", work_dir, before)

        assert files == [str(target)]

    def test_no_snapshot_treats_everything_as_new(self, wrapper, tmp_path):
        """Backward-compatible default: before=None reports every matching
        file (unit tests / callers that don't snapshot)."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        f = work_dir / "out.bas"
        f.touch()

        files = wrapper._find_output_files("shypre", work_dir)

        assert files == [str(f)]


class TestRunCommandOutputDiscovery:
    """End-to-end through run_command with a real subprocess: only files the
    run actually produced or modified come back in CommandResult.output_files."""

    @pytest.mark.asyncio
    async def test_run_command_reports_only_new_and_modified_files(self, wrapper, tmp_path):
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        # (a) pre-existing file with an old mtime, never touched during the run.
        stale = work_dir / "stale.shy"
        stale.touch()
        old_time = time.time() - 3600
        os.utime(stale, (old_time, old_time))

        # (c) pre-existing file that the run will rewrite.
        modified = work_dir / "modified.shy"
        modified.write_text("original\n")
        os.utime(modified, (old_time, old_time))

        exe = wrapper.bin_dir / "shyfem"
        exe.write_text(
            "#!/bin/bash\n"
            "echo appended >> modified.shy\n"  # (c) touch existing file
            "touch created.shy\n"  # (b) create a brand new file
        )
        exe.chmod(0o755)

        result = await wrapper.run_command("shyfem", [], work_dir)

        names = {os.path.basename(f) for f in result.output_files}

        assert "stale.shy" not in names, "untouched pre-existing file must not be reported"
        assert "created.shy" in names, "file created during the run must be reported"
        assert "modified.shy" in names, "pre-existing file modified during the run must be reported"

    @pytest.mark.asyncio
    async def test_run_command_second_run_does_not_report_first_runs_files(self, wrapper, tmp_path):
        """Simulates two jobs sharing a working directory (workflow chaining):
        the second run's output must not include the first run's file."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        exe = wrapper.bin_dir / "shyfem"
        exe.write_text("#!/bin/bash\ntouch $OUT_NAME\n")
        exe.chmod(0o755)

        result1 = await wrapper.run_command("shyfem", [], work_dir, env={"OUT_NAME": "first.shy"})
        assert [os.path.basename(f) for f in result1.output_files] == ["first.shy"]

        result2 = await wrapper.run_command("shyfem", [], work_dir, env={"OUT_NAME": "second.shy"})
        names2 = {os.path.basename(f) for f in result2.output_files}

        assert "second.shy" in names2
        assert "first.shy" not in names2


class TestCaptureStdout:
    """L36: run_command must be able to drop the retained stdout buffer for long
    simulations (which stream to a file via output_callback) while still firing
    the callback per line and always retaining stderr."""

    @pytest.mark.asyncio
    async def test_capture_stdout_false_empties_buffer_keeps_callback_and_stderr(
        self, wrapper, tmp_path
    ):
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        exe = wrapper.bin_dir / "shyfem"
        exe.write_text("#!/bin/bash\necho line-one\necho line-two\necho err-line >&2\n")
        exe.chmod(0o755)

        seen: list[str] = []
        result = await wrapper.run_command(
            "shyfem",
            [],
            work_dir,
            output_callback=seen.append,
            capture_stdout=False,
        )

        # Retained stdout buffer is dropped ...
        assert result.stdout == ""
        # ... but the per-line callback still received every stdout line ...
        assert "line-one" in seen and "line-two" in seen
        # ... and stderr is always retained (error messages must survive).
        assert "err-line" in result.stderr

    @pytest.mark.asyncio
    async def test_capture_stdout_true_retains_full_stdout(self, wrapper, tmp_path):
        """A stdout-parsing caller (default capture_stdout=True) still gets the
        full stdout — postprocess/shyelab depend on this."""
        work_dir = tmp_path / "work2"
        work_dir.mkdir()
        exe = wrapper.bin_dir / "shyfem"
        exe.write_text("#!/bin/bash\necho parseable-output\n")
        exe.chmod(0o755)

        result = await wrapper.run_command("shyfem", [], work_dir)

        assert "parseable-output" in result.stdout
