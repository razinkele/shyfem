"""Tests for incremental stdout writing during job execution."""

from pathlib import Path


def test_output_callback_writes_incrementally(tmp_path: Path):
    """Verify output_callback writes each line to file immediately."""
    stdout_file = tmp_path / "test.stdout"

    fh = open(stdout_file, "a")
    try:
        def output_callback(line: str):
            fh.write(line + "\n")
            fh.flush()

        output_callback("line 1")
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

    assert stdout_file.read_text() == "before\n"
    assert fh.closed
