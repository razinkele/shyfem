"""Tests for changelog parsing + repo markdown reading."""

from shyfem_ui.changelog import (
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


def test_read_repo_markdown_rejects_paths_and_missing():
    assert "not available" in read_repo_markdown("../etc/passwd")
    assert "not available" in read_repo_markdown("nonexistent_file_xyz.md")
    assert "not available" in read_repo_markdown("sub/dir.md")


def test_latest_release_version_from_real_changelog():
    version = latest_release_version()
    assert version
    assert version.lower() != "unreleased"
