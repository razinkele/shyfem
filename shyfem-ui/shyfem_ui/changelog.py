"""Read the repo's README / CHANGELOG and parse the latest release.

Used by the About page (renders README.md / CHANGELOG.md) and the "what's new"
startup modal (shows the latest release section once per browser version).
"""

import re
from pathlib import Path

# "## [label] ..." section headers (Keep a Changelog format).
_HEADER = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)

# README / CHANGELOG live at the repo root (parent of the shyfem-ui package dir).
# Resolved from the package location -- not config.shyfem_dir -- so it always
# finds THIS package's docs (config.shyfem_dir may point at a different SHYFEM
# install, and tests override it). .resolve() canonicalizes the deployed symlink.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# name -> (mtime, content). Re-reads only when the file changes on disk, so the
# deployed (symlinked) tree picks up edits without re-reading on every render.
_cache: dict[str, tuple[float, str]] = {}


def read_repo_markdown(name: str) -> str:
    """Read a markdown file from the repo root (e.g. README.md / CHANGELOG.md).

    ``name`` must be a bare filename (no path separators). Returns a friendly
    fallback string if the file is missing.
    """
    if "/" in name or "\\" in name or name in ("", ".", ".."):
        return f"*{name} not available.*"
    path = _REPO_ROOT / name
    try:
        if not path.is_file():
            return f"*{name} not available.*"
        mtime = path.stat().st_mtime
    except OSError:
        return f"*{name} not available.*"
    cached = _cache.get(name)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    content = path.read_text(encoding="utf-8")
    _cache[name] = (mtime, content)
    return content


def parse_latest_release(text: str) -> tuple[str, str] | None:
    """Return ``(version_label, section_markdown)`` of the first dated release.

    The CHANGELOG's first ``## [...]`` section is literally ``[Unreleased]``;
    this skips it (case-insensitive) and returns the first real release section,
    so the modal keys off a version label that changes on each release.
    """
    matches = list(_HEADER.finditer(text or ""))
    for i, m in enumerate(matches):
        label = m.group(1).strip()
        if label.lower() == "unreleased":
            continue
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        return label, text[start:end].strip()
    return None


def latest_release_version(text: str | None = None) -> str | None:
    """Return just the latest release label (e.g. ``'shyfem-ui 0.2.0'``), or None."""
    if text is None:
        text = read_repo_markdown("CHANGELOG.md")
    parsed = parse_latest_release(text)
    return parsed[0] if parsed else None
