"""Tests for incremental stdout writing during job execution.

Exercises the REAL write helper used by LocalJobQueue's output_callback
(shyfem_ui.services.job_local.write_output_line), not a re-implemented copy —
so these fail if the actual incremental-write behaviour regresses.
"""

from pathlib import Path

from shyfem_ui.services.job_local import write_output_line


def test_writes_each_line_immediately(tmp_path: Path):
    """Each line is appended with a newline and flushed right away."""
    stdout_file = tmp_path / "test.stdout"
    with open(stdout_file, "a") as fh:
        write_output_line(fh, "line 1")
        assert stdout_file.read_text() == "line 1\n"
        write_output_line(fh, "line 2")
        assert stdout_file.read_text() == "line 1\nline 2\n"
        write_output_line(fh, "line 3")
        assert stdout_file.read_text() == "line 1\nline 2\nline 3\n"


def test_handles_empty_lines(tmp_path: Path):
    """Empty lines are written as bare newlines."""
    stdout_file = tmp_path / "test.stdout"
    with open(stdout_file, "a") as fh:
        write_output_line(fh, "")
        write_output_line(fh, "data")
        write_output_line(fh, "")
    assert stdout_file.read_text() == "\ndata\n\n"


def test_none_handle_is_noop():
    """When the stdout handle could not be opened (None), writing is a no-op
    and must not raise — this is the guard the real callback relies on."""
    write_output_line(None, "ignored")  # no exception
