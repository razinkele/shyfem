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
