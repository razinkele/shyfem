"""Tests for changelog parsing + repo markdown reading."""

from shyfem_ui.changelog import (
    core_version,
    filter_changelog,
    latest_release_version,
    parse_latest_release,
    read_repo_markdown,
)

SAMPLE = """# Changelog

## [Unreleased]

### Changed
- something still pending

## [shyfem-ui 0.2.0] — 2026-06-14

### Added
- trips feature

## [8.2.0] — 2026-06-13

### Added
- core stuff
"""


def test_parse_skips_unreleased():
    label, section = parse_latest_release(SAMPLE)
    assert label == "shyfem-ui 0.2.0"
    assert "trips feature" in section
    assert "something still pending" not in section  # did not bleed [Unreleased]


def test_parse_section_ends_at_next_header():
    _, section = parse_latest_release(SAMPLE)
    assert "core stuff" not in section  # stops before the 8.2.0 section


def test_parse_no_release_returns_none():
    assert parse_latest_release("# Changelog\n\n## [Unreleased]\n\n- x\n") is None
    assert parse_latest_release("") is None


def test_read_repo_markdown_real_files():
    assert read_repo_markdown("README.md").startswith("# SHYFEM")
    assert "Changelog" in read_repo_markdown("CHANGELOG.md")
    # The UI's own README is on the allowlist for the About → SHYFEM UI modal.
    assert "SHYFEM UI" in read_repo_markdown("shyfem-ui/README.md")


def test_read_repo_markdown_rejects_paths_and_missing():
    assert "not available" in read_repo_markdown("../etc/passwd")
    assert "not available" in read_repo_markdown("nonexistent_file_xyz.md")
    assert "not available" in read_repo_markdown("sub/dir.md")
    # Allowlist, not just separator filtering: repo files that exist but are
    # not on the list stay unreadable.
    assert "not available" in read_repo_markdown("VERSION")
    assert "not available" in read_repo_markdown("shyfem-ui/pyproject.toml")


def test_latest_release_version_from_real_changelog():
    version = latest_release_version()
    assert version
    assert version.lower() != "unreleased"


def test_filter_changelog_splits_ui_and_core():
    ui_view = filter_changelog(SAMPLE, "ui")
    core_view = filter_changelog(SAMPLE, "core")
    # UI view: unreleased + shyfem-ui sections, no core section.
    assert "something still pending" in ui_view
    assert "trips feature" in ui_view
    assert "core stuff" not in ui_view
    # Core view: unreleased + bare-version sections, no UI section.
    assert "something still pending" in core_view
    assert "core stuff" in core_view
    assert "trips feature" not in core_view
    # Preamble kept in both.
    assert ui_view.startswith("# Changelog")
    assert core_view.startswith("# Changelog")


def test_filter_changelog_edge_cases():
    import pytest

    assert filter_changelog("", "ui") == ""
    assert filter_changelog("no headers here", "core") == "no headers here"
    with pytest.raises(ValueError):
        filter_changelog(SAMPLE, "everything")


def test_filter_changelog_real_file():
    text = read_repo_markdown("CHANGELOG.md")
    ui_view = filter_changelog(text, "ui")
    core_view = filter_changelog(text, "core")
    assert "[shyfem-ui" in ui_view
    assert "[shyfem-ui" not in core_view.replace("[Unreleased]", "")
    assert "[8.2.0]" in core_view
    assert "[8.2.0]" not in ui_view


def test_core_version_from_real_repo():
    version = core_version()
    assert version
    # VERSION's first line is e.g. "version  8_2_0  ..." -> "8.2.0"
    assert version[0].isdigit()
    assert "_" not in version
