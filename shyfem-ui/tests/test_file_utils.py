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
