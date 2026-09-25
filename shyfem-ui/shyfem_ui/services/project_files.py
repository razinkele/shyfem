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


#: Default caps for directory listings (dropdown of output/working dirs).
MAX_PROJECT_DIRS = 200
MAX_PROJECT_DIR_DEPTH = 2


def list_project_dirs(
    root: Path,
    max_depth: int = MAX_PROJECT_DIR_DEPTH,
    max_dirs: int = MAX_PROJECT_DIRS,
) -> list[str]:
    """Project-relative directories under ``root``: ``"."`` first, then the
    non-hidden subdirectories down to ``max_depth`` levels, sorted, capped at
    ``max_dirs``. Returns ``[]`` when ``root`` is not a directory. Path
    confinement is the caller's job; nothing here is opened or created.
    """
    if max_depth < 1 or max_dirs < 1:
        return []
    try:
        if not root.is_dir():
            return []
    except OSError:
        return []
    out: list[str] = ["."]

    def _walk(d: Path, depth: int) -> None:
        if depth > max_depth or len(out) >= max_dirs:
            return
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            return
        for child in children:
            if len(out) >= max_dirs:
                return
            out.append(str(child.relative_to(root)))
            _walk(child, depth + 1)

    _walk(root, 1)
    return out
