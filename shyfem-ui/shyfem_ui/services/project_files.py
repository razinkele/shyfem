"""List selectable data files inside a project directory.

Shared by the Visualize page's data pickers and the time-series component's
observation-overlay picker so both offer the same project-relative choices
instead of a free-text path box.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

#: Default cap so a large project can't build an unwieldy dropdown.
MAX_PROJECT_FILES = 500


def list_project_files(
    root: Path, exts: Sequence[str], max_files: int = MAX_PROJECT_FILES
) -> list[str]:
    """Project-relative paths of files under ``root`` with a matching suffix.

    Recursive; hidden trees (e.g. the ``.boxmodel_cache`` parquet store) are
    skipped and the result is capped at ``max_files``. Extensions are matched
    case-insensitively and must include the leading dot (e.g. ``".csv"``).
    Path confinement is the caller's job; nothing here is opened.
    """
    lowered = tuple(e.lower() for e in exts)
    out: list[str] = []
    if not lowered:
        return out
    try:
        for p in sorted(root.rglob("*")):
            if len(out) >= max_files:
                break
            if not p.is_file() or p.suffix.lower() not in lowered:
                continue
            rel = p.relative_to(root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            out.append(str(rel))
    except OSError:
        pass
    return out
