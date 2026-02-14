# Phase 25: Real-Time Log Streaming — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable real-time log output during SHYFEM simulations by fixing the full pipeline: incremental file writes, wired auto-refresh, configurable polling, and efficient tail reads.

**Architecture:** Three existing files are modified — no new services or classes. `job_local.py` writes stdout incrementally to disk via append mode. `run.py` wires the broken auto-refresh callback. `log_viewer.py` honors the existing `log_refresh_interval` config. A shared `tail_file()` utility replaces the inefficient read-entire-file pattern in both job queue implementations.

**Tech Stack:** Python asyncio, Shiny reactive effects, pathlib/io for seek-based tail

---

### Task 1: Add `tail_file()` utility and tests

**Files:**
- Create: `shyfem_ui/services/file_utils.py`
- Create: `tests/test_file_utils.py`

**Step 1: Write tests**

Create `tests/test_file_utils.py`:

```python
"""Tests for file utility functions."""

from pathlib import Path

from shyfem_ui.services.file_utils import tail_file


class TestTailFile:
    """Tests for tail_file()."""

    def test_nonexistent_file(self, tmp_path: Path):
        result = tail_file(tmp_path / "missing.txt", tail=10)
        assert result == ""

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = tail_file(f, tail=10)
        assert result == ""

    def test_fewer_lines_than_tail(self, tmp_path: Path):
        f = tmp_path / "short.txt"
        f.write_text("line1\nline2\nline3\n")
        result = tail_file(f, tail=10)
        assert result == "line1\nline2\nline3"

    def test_exact_tail_count(self, tmp_path: Path):
        f = tmp_path / "exact.txt"
        f.write_text("a\nb\nc\n")
        result = tail_file(f, tail=3)
        assert result == "a\nb\nc"

    def test_more_lines_than_tail(self, tmp_path: Path):
        f = tmp_path / "long.txt"
        lines = [f"line{i}" for i in range(100)]
        f.write_text("\n".join(lines) + "\n")
        result = tail_file(f, tail=5)
        assert result == "line95\nline96\nline97\nline98\nline99"

    def test_tail_zero_returns_all(self, tmp_path: Path):
        f = tmp_path / "all.txt"
        f.write_text("a\nb\nc\n")
        result = tail_file(f, tail=0)
        assert result == "a\nb\nc"

    def test_large_file_seeks_from_end(self, tmp_path: Path):
        """Verify large files are handled via seek, not full read."""
        f = tmp_path / "large.txt"
        # Write >64KB of content
        lines = [f"line{i:06d} padding" for i in range(5000)]
        f.write_text("\n".join(lines) + "\n")
        result = tail_file(f, tail=3)
        assert result == "line004997 padding\nline004998 padding\nline004999 padding"

    def test_no_trailing_newline(self, tmp_path: Path):
        f = tmp_path / "no_nl.txt"
        f.write_text("a\nb\nc")
        result = tail_file(f, tail=2)
        assert result == "b\nc"

    def test_binary_safe_encoding(self, tmp_path: Path):
        """Non-UTF8 bytes don't crash."""
        f = tmp_path / "binary.txt"
        f.write_bytes(b"line1\nline2\n\xff\xfe\nline3\n")
        result = tail_file(f, tail=2)
        assert "line3" in result
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_utils.py -v`
Expected: FAIL (ImportError — module doesn't exist yet)

**Step 3: Implement `tail_file()`**

Create `shyfem_ui/services/file_utils.py`:

```python
"""File utility functions for log streaming."""

from pathlib import Path

# Seek buffer size — read last 64KB to find tail lines
_TAIL_BUFFER_SIZE = 65536


def tail_file(path: Path | str, tail: int = 100) -> str:
    """Read the last N lines of a file efficiently.

    Uses seek-from-end for large files to avoid loading the entire file
    into memory. Falls back to full read for small files.

    Args:
        path: File path to read.
        tail: Number of lines to return. 0 means return all lines.

    Returns:
        Last N lines joined by newlines, or empty string if file
        doesn't exist or is empty.
    """
    path = Path(path)
    if not path.exists():
        return ""

    try:
        size = path.stat().st_size
        if size == 0:
            return ""

        if tail == 0 or size <= _TAIL_BUFFER_SIZE:
            # Small file or all lines requested — read everything
            content = path.read_text(errors="replace")
            lines = content.splitlines()
            if tail == 0:
                return "\n".join(lines)
            return "\n".join(lines[-tail:])

        # Large file — seek from end
        with open(path, "rb") as fh:
            fh.seek(-_TAIL_BUFFER_SIZE, 2)
            chunk = fh.read().decode("utf-8", errors="replace")

        lines = chunk.splitlines()
        # First line is likely partial (we seeked mid-line), drop it
        if len(lines) > 1:
            lines = lines[1:]
        return "\n".join(lines[-tail:])
    except Exception:
        return ""
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_utils.py -v`
Expected: 9 passed

**Step 5: Commit**

```bash
git add shyfem_ui/services/file_utils.py tests/test_file_utils.py
git commit -m "feat: add tail_file() utility for efficient log reading"
```

---

### Task 2: Use `tail_file()` in both job queue implementations

**Files:**
- Modify: `shyfem_ui/services/job_local.py` (lines 346-369)
- Modify: `shyfem_ui/services/job_celery.py` (lines 347-372)

**Step 1: Update `LocalJobQueue.get_output()`**

In `shyfem_ui/services/job_local.py`, replace the `get_output` method body (lines 346-369):

```python
    async def get_output(
        self, job_id: str, stream: str = "stdout", tail: int = 100
    ) -> str:
        """Get job output."""
        job = self._jobs.get(job_id)
        if not job:
            return ""

        file_path = job.stdout_file if stream == "stdout" else job.stderr_file
        if not file_path:
            return ""

        from shyfem_ui.services.file_utils import tail_file

        return tail_file(file_path, tail=tail)
```

**Step 2: Update `CeleryJobQueue.get_output()`**

In `shyfem_ui/services/job_celery.py`, replace the `get_output` method body (lines 347-372):

```python
    async def get_output(
        self, job_id: str, stream: str = "stdout", tail: int = 100
    ) -> str:
        """Get job output."""
        rc = self._get_redis_client()
        job_info = _load_job_info(rc, job_id)
        if not job_info:
            return ""

        file_path = job_info.stdout_file if stream == "stdout" else job_info.stderr_file
        if not file_path:
            return ""

        from shyfem_ui.services.file_utils import tail_file

        return tail_file(file_path, tail=tail)
```

**Step 3: Run existing tests to verify no regressions**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 429+ passed, 0 failed

**Step 4: Commit**

```bash
git add shyfem_ui/services/job_local.py shyfem_ui/services/job_celery.py
git commit -m "refactor: use tail_file() in job queue get_output()"
```

---

### Task 3: Incremental stdout writing in `job_local.py`

**Files:**
- Modify: `shyfem_ui/services/job_local.py` (lines 226-277)
- Create: `tests/test_incremental_output.py`

**Step 1: Write tests**

Create `tests/test_incremental_output.py`:

```python
"""Tests for incremental stdout writing during job execution."""

from pathlib import Path
from unittest.mock import MagicMock


def test_output_callback_writes_incrementally(tmp_path: Path):
    """Verify output_callback writes each line to file immediately."""
    stdout_file = tmp_path / "test.stdout"

    # Simulate the output_callback pattern from job_local.py
    fh = open(stdout_file, "a")
    try:
        def output_callback(line: str):
            fh.write(line + "\n")
            fh.flush()

        output_callback("line 1")
        # File should have content immediately (not buffered until close)
        assert stdout_file.read_text() == "line 1\n"

        output_callback("line 2")
        assert stdout_file.read_text() == "line 1\nline 2\n"

        output_callback("line 3")
        assert stdout_file.read_text() == "line 1\nline 2\nline 3\n"
    finally:
        fh.close()


def test_output_callback_handles_empty_lines(tmp_path: Path):
    """Empty lines are written correctly."""
    stdout_file = tmp_path / "test.stdout"

    fh = open(stdout_file, "a")
    try:
        def output_callback(line: str):
            fh.write(line + "\n")
            fh.flush()

        output_callback("")
        output_callback("data")
        output_callback("")
        assert stdout_file.read_text() == "\ndata\n\n"
    finally:
        fh.close()


def test_file_handle_closed_on_error(tmp_path: Path):
    """Verify file handle is closed even if callback raises."""
    stdout_file = tmp_path / "test.stdout"
    fh = open(stdout_file, "a")

    fh.write("before\n")
    fh.flush()
    fh.close()

    # After close, file should be readable
    assert stdout_file.read_text() == "before\n"
    assert fh.closed
```

**Step 2: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_incremental_output.py -v`
Expected: 3 passed (these test the pattern, not the actual code yet)

**Step 3: Modify `_execute_job()` in `job_local.py`**

In `shyfem_ui/services/job_local.py`, replace lines 226-277 (from `stdout_lines = []` through `Path(job.stderr_file).write_text(result.stderr)`).

The changes:
1. Replace `stdout_lines = []` and `output_callback` with file-handle-based writing
2. Remove the post-completion `Path(job.stdout_file).write_text(result.stdout)` for stdout
3. Keep stderr write-at-end (small, captured by wrapper)
4. Close the file handle in the `finally` block

Replace lines 226-277 with:

```python
            stdout_fh = None
            if job.stdout_file:
                Path(job.stdout_file).touch()
                stdout_fh = open(job.stdout_file, "a")

            def progress_callback(progress: float, message: str):
                job.progress = progress
                job.progress_message = message
                # Legacy single callback
                if self._progress_callback:
                    self._progress_callback(job_id, progress, message)
                # Multi-session callbacks
                self._notify_progress(job_id, progress, message)

            def output_callback(line: str):
                if stdout_fh:
                    stdout_fh.write(line + "\n")
                    stdout_fh.flush()

            try:
                if spec.tool_name == "shyfem" and spec.mpi_enabled and spec.mpi_np > 1:
                    # MPI execution
                    result = await self.wrapper.run_shyfem(
                        spec.args[-1] if spec.args else "",
                        spec.working_dir,
                        mpi_enabled=True,
                        mpi_np=spec.mpi_np,
                        mpirun_path="mpirun",
                        options=spec.args[:-1] if len(spec.args) > 1 else None,
                        progress_callback=progress_callback,
                        output_callback=output_callback,
                    )
                else:
                    result = await self.wrapper.run_command(
                        spec.tool_name,
                        spec.args,
                        spec.working_dir,
                        progress_callback,
                        output_callback,
                    )

                # Update job with result
                job.return_code = result.return_code
                job.output_files = result.output_files
                job.progress = 1.0

                if result.success:
                    job.status = JobStatus.COMPLETED
                else:
                    job.status = JobStatus.FAILED
                    job.error_message = result.stderr[:1000] if result.stderr else "Unknown error"

                # Write stderr (small, captured at end by wrapper)
                if job.stderr_file and result.stderr:
                    Path(job.stderr_file).write_text(result.stderr)
```

Also update the `except`/`finally` block (lines 279-291) to close the file handle:

```python
            except asyncio.CancelledError:
                job.status = JobStatus.CANCELLED
                job.error_message = "Job was cancelled"
            except Exception as e:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
            finally:
                if stdout_fh:
                    stdout_fh.close()
                job.completed_at = datetime.now()
                self._running_count -= 1
                # Clean up task reference
                self._tasks.pop(job_id, None)
                # Persist final state to DB
                self._persist_job(job)
```

**Step 4: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 432+ passed, 0 failed

**Step 5: Commit**

```bash
git add shyfem_ui/services/job_local.py tests/test_incremental_output.py
git commit -m "feat: write stdout incrementally during job execution"
```

---

### Task 4: Wire auto-refresh in run page and honor config in log viewer

**Files:**
- Modify: `shyfem_ui/pages/run.py` (lines 284, 297-300)
- Modify: `shyfem_ui/components/log_viewer.py` (lines 117-148)

**Step 1: Fix `run.py` — wire `on_refresh` and add log refresh to auto-loop**

In `shyfem_ui/pages/run.py`, line 284, replace:

```python
    log_viewer_server("job_log", log_content, on_refresh=lambda: None)
```

with:

```python
    log_viewer_server("job_log", log_content, on_refresh=_refresh_log)
```

In `shyfem_ui/pages/run.py`, in the `_auto_refresh` effect (around line 297-300), add a call to `_refresh_log()` after `_refresh_tick`. Replace:

```python
            if active or wf_active:
                reactive.invalidate_later(2)
                _refresh_tick.set(_refresh_tick.get() + 1)
            await _refresh_jobs()
```

with:

```python
            if active or wf_active:
                reactive.invalidate_later(2)
                _refresh_tick.set(_refresh_tick.get() + 1)
            await _refresh_jobs()
            await _refresh_log()
```

**Step 2: Fix `log_viewer.py` — accept `refresh_interval` parameter**

In `shyfem_ui/components/log_viewer.py`, update the `log_viewer_server` signature (line 118) to accept an interval:

```python
@module.server
def log_viewer_server(
    input,
    output,
    session,
    log_content_val: reactive.Value[str],
    on_refresh: Callable[[], None] | None = None,
    refresh_interval: int = 5,
):
```

Update the docstring to mention the new parameter:

```python
    """Log viewer component server logic.

    Args:
        log_content_val: Reactive value containing log text.
            Supports both plain text and structured format with
            "=== STDOUT ===" / "=== STDERR ===" separators.
        on_refresh: Callback when refresh is clicked
        refresh_interval: Seconds between auto-refresh polls (default: 5)
    """
```

Replace the hardcoded `reactive.invalidate_later(2)` on line 144:

```python
    @reactive.effect
    def _auto_poll_effect():
        try:
            if input.auto_poll():
                reactive.invalidate_later(refresh_interval)
                if on_refresh:
                    on_refresh()
        except Exception:
            pass
```

**Step 3: Pass config interval from `run.py`**

In `shyfem_ui/pages/run.py`, update the `log_viewer_server` call to pass the config value. The run page already has access to config (check imports). Replace the line from Step 1:

```python
    log_viewer_server("job_log", log_content, on_refresh=_refresh_log)
```

with:

```python
    from shyfem_ui.config import get_config
    log_viewer_server(
        "job_log",
        log_content,
        on_refresh=_refresh_log,
        refresh_interval=get_config().log_refresh_interval,
    )
```

**Step 4: Also update ensemble page if it uses log_viewer_server**

Check whether ensemble.py calls `log_viewer_server`. If not, no change needed.

Run: `grep -n "log_viewer_server" shyfem_ui/pages/ensemble.py`
(If no matches, skip this step.)

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 432+ passed, 0 failed

**Step 6: Commit**

```bash
git add shyfem_ui/pages/run.py shyfem_ui/components/log_viewer.py
git commit -m "feat: wire auto-refresh and configurable polling interval for logs"
```

---

### Task 5: Final verification and TODO update

**Step 1: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v 2>&1 | tail -20`
Expected: 432+ passed, 0 failed

**Step 2: Verify app launches**

Run: `timeout 5 /opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app 2>&1 || true`
Expected: App starts without import errors or warnings

**Step 3: Update TODO_NEXT.md**

Mark Phase 25 items as complete. Update the description to reflect the actual implementation (pipeline fix, not LogBroadcaster).

**Step 4: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 25 log streaming complete in TODO_NEXT.md"
```
