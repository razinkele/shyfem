"""Read the repo's README / CHANGELOG files and parse the latest release.

Used by the topbar About/Changelog modals (README.md, shyfem-ui/README.md,
per-package CHANGELOG.md views) and the "what's new" startup modal (shows the
latest release section once per browser version).
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

# The only files the About/Changelog modals may read, relative to the repo
# root. An explicit allowlist (not merely "no path separators") because the
# UI's own README lives one level down; anything else is rejected.
_ALLOWED_FILES = {"README.md", "CHANGELOG.md", "shyfem-ui/README.md"}

# name -> (mtime, content). Re-reads only when the file changes on disk, so the
# deployed (symlinked) tree picks up edits without re-reading on every render.
_cache: dict[str, tuple[float, str]] = {}


def read_repo_markdown(name: str) -> str:
    """Read an allowlisted markdown file relative to the repo root.

    ``name`` must be one of ``_ALLOWED_FILES``. Returns a friendly fallback
    string if the name is not allowlisted or the file is missing.
    """
    if name not in _ALLOWED_FILES:
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


def core_version() -> str | None:
    """Return the SHYFEM core version from the repo-root ``VERSION`` file.

    Its first line looks like ``version  8_2_0  13-06-2026  VERS_8_2_0`` (the
    rest of the file is a long historical log — read only that line). Returns
    None if the file is missing or the line doesn't parse.
    """
    try:
        with (_REPO_ROOT / "VERSION").open(encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
    except OSError:
        return None
    parts = first.split()
    if len(parts) >= 2 and parts[0].lower() == "version":
        return parts[1].replace("_", ".")
    return None


def filter_changelog(text: str, package: str) -> str:
    """Return only one package's sections of the shared CHANGELOG.

    The repo keeps a single CHANGELOG.md for both packages: UI releases are
    labelled ``[shyfem-ui X.Y.Z]``, core releases carry a bare version label
    (e.g. ``[8.2.0]``). ``package`` is ``"core"`` or ``"ui"``. The preamble
    before the first section header and the ``[Unreleased]`` section are kept
    for both views.
    """
    if package not in ("core", "ui"):
        raise ValueError(f"package must be 'core' or 'ui', got {package!r}")
    matches = list(_HEADER.finditer(text or ""))
    if not matches:
        return text or ""
    parts = [text[: matches[0].start()]]
    for i, m in enumerate(matches):
        label = m.group(1).strip().lower()
        is_ui = label.startswith("shyfem-ui")
        keep = (
            label == "unreleased"
            or (package == "ui" and is_ui)
            or (package == "core" and not is_ui)
        )
        if keep:
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            parts.append(text[m.start() : end])
    return "".join(parts).strip()


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
