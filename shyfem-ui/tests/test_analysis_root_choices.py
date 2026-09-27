"""Run directories usually live OUTSIDE the project.

The one real manifest we have points all three of its runs at absolute paths
under an admin-declared analysis root, so a project-only dropdown could not
express it. These choices are what lets the manifest form offer them.

Listing depth-1 directory names under a root is strictly less than what any
authenticated user can already read from it: the Box model page reads run
output from analysis roots for every user by design.
"""

from pathlib import Path

import pytest

from shyfem_ui.components.project_select import analysis_root_dir_choices
from shyfem_ui.config import Config

#: A resolved identity. Server mode offers nothing without one.
USER = {"id": 7, "username": "razinka", "role": "user"}


@pytest.fixture
def roots(outside_tmp_dir):
    """An analysis root laid out like the live one: runs directly inside it."""
    root = Path(outside_tmp_dir) / "published_runs"
    for name in ("run9316", "run9314", "run9314_minijafix"):
        (root / name).mkdir(parents=True)
    (root / ".hidden_run").mkdir()
    (root / "notes.txt").write_text("not a directory")
    (root / "elsewhere").symlink_to(root / "run9316", target_is_directory=True)
    return root


def _server_config(root: Path) -> Config:
    return Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        analysis_roots=[str(root)],
    )


def test_the_runs_under_a_root_are_offered_as_absolute_paths(roots):
    """Absolute, because that is how a manifest has to name a directory
    outside the project; a relative value would be resolved against the
    project and rejected for escaping it."""
    choices = analysis_root_dir_choices(_server_config(roots), USER)

    assert str(roots / "run9316") in choices
    assert all(Path(c).is_absolute() for c in choices)
    assert choices == sorted(choices)


def test_hidden_entries_files_and_symlinks_are_skipped(roots):
    """The same guards the project listing uses: a symlink inside a root must
    not list another tree."""
    choices = analysis_root_dir_choices(_server_config(roots), USER)

    assert str(roots / ".hidden_run") not in choices
    assert str(roots / "notes.txt") not in choices
    assert str(roots / "elsewhere") not in choices
    assert len(choices) == 3


def test_no_roots_means_no_choices():
    """Local mode declares none, and the form must simply offer nothing extra
    rather than failing."""
    assert analysis_root_dir_choices(Config(_env_file=None, deployment_mode="local"), None) == []


def test_no_identity_means_no_listing_in_server_mode(roots):
    """An unresolved identity must not enumerate an admin's directories.
    confine_path refuses user=None in server mode; this matches it."""
    assert analysis_root_dir_choices(_server_config(roots), None) == []
