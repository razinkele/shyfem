"""H-03: the tutorial-project name must not choose where the copy lands.

``_create_tutorial_project`` used ``config.work_dir / name`` straight from the
modal's text input and handed it to ``copytree``, so ``'../../escape_here'``
landed outside ``work_dir`` and ``'../users/bob/stolen_copy'`` in bob's home.
``Config.new_project_path`` is the one place a new project's folder is derived
from a typed name: a single plain path component, rooted in the owner's home in
server mode (F-02, tutorial half) and in ``work_dir`` locally.
"""

import ast
from pathlib import Path

import pytest

from shyfem_ui.config import Config

_HOME_PY = Path(__file__).resolve().parents[1] / "shyfem_ui" / "pages" / "home.py"


def _server_config(tmp_path: Path) -> Config:
    users = tmp_path / "users"
    work = tmp_path / "work"
    shyfem = tmp_path / "shyfem"
    for d in (users, work, shyfem):
        d.mkdir(parents=True, exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode="server",
        user_data_root=users,
        work_dir=work,
        shyfem_dir=shyfem,
        default_admin_password="strongpass123",
    )


def _local_config(tmp_path: Path) -> Config:
    work = tmp_path / "work"
    work.mkdir(parents=True, exist_ok=True)
    return Config(_env_file=None, deployment_mode="local", work_dir=work)


ALICE = {"id": 1, "username": "alice", "role": "user"}

BAD_NAMES = [
    "../../escape_here",
    "../bob/stolen_copy",
    "../../users/bob/stolen_copy",
    "/tmp/abs_target",
    "sub/dir",
    "back\\slash",
    ".",
    "..",
    "",
    "   ",
    ".hidden",
    "nul\x00byte",
]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_server_mode_refuses_a_name_that_is_not_one_plain_folder(tmp_path, name):
    cfg = _server_config(tmp_path)
    with pytest.raises(ValueError):
        cfg.new_project_path(name, ALICE)


@pytest.mark.parametrize("name", BAD_NAMES)
def test_local_mode_refuses_the_same_names(tmp_path, name):
    cfg = _local_config(tmp_path)
    with pytest.raises(ValueError):
        cfg.new_project_path(name, None)


def test_server_mode_roots_the_project_in_the_owners_home(tmp_path):
    cfg = _server_config(tmp_path)
    got = cfg.new_project_path("Mar Menor Tutorial", ALICE)
    assert got == (cfg.user_data_root / "alice" / "Mar Menor Tutorial").resolve()
    # Not in the shared work_dir, where alice's confine_path would reject it (F-02).
    assert not str(got).startswith(str(cfg.work_dir.resolve()))


def test_server_mode_unresolved_identity_is_refused(tmp_path):
    cfg = _server_config(tmp_path)
    with pytest.raises(ValueError):
        cfg.new_project_path("mar_menor_tutorial", None)


def test_server_mode_symlink_out_of_the_home_is_refused(tmp_path):
    cfg = _server_config(tmp_path)
    bob = cfg.user_data_root / "bob"
    bob.mkdir()
    alice = cfg.user_data_root / "alice"
    alice.mkdir()
    (alice / "proj").symlink_to(bob / "new_proj")  # dangling: copytree would follow it
    with pytest.raises(ValueError):
        cfg.new_project_path("proj", ALICE)


def test_local_mode_symlink_out_of_work_dir_is_refused(tmp_path):
    cfg = _local_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (cfg.work_dir / "proj").symlink_to(outside / "new_proj")
    with pytest.raises(ValueError):
        cfg.new_project_path("proj", None)


def test_local_mode_roots_the_project_in_work_dir(tmp_path):
    cfg = _local_config(tmp_path)
    assert cfg.new_project_path("mm", None) == (cfg.work_dir / "mm").resolve()


def _handler():
    tree = ast.parse(_HOME_PY.read_text())
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_create_tutorial_project"
    )


def test_tutorial_handler_derives_its_folder_from_new_project_path():
    fn = _handler()
    src = ast.unparse(fn)
    assert "new_project_path(" in src
    assert "work_dir / name" not in src, "the typed name must not be joined to work_dir"
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]

    def first_line(attr):
        lines = [
            c.lineno for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == attr
        ]
        assert lines, f"{attr} not called"
        return min(lines)

    assert first_line("new_project_path") < first_line("copytree")
