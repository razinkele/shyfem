"""F-02 (clone half): a server-mode clone lands in its owner's home.

Clone wrote into the shared ``config.work_dir`` while import and new
projects go to ``user_data_root/<user>``; the owner's write confinement then
refused the clone's own folder (runs, saves, Grid Prep output).
"""

import ast
from pathlib import Path

import pytest

from shyfem_ui.config import Config

_HOME_PY = Path(__file__).resolve().parents[1] / "shyfem_ui" / "pages" / "home.py"


def _cfg(tmp_path, mode="server"):
    for d in ("users", "work", "shyfem"):
        (tmp_path / d).mkdir(exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode=mode,
        user_data_root=tmp_path / "users",
        work_dir=tmp_path / "work",
        shyfem_dir=tmp_path / "shyfem",
        default_admin_password="strongpass123",
    )


ALICE = {"id": 2, "username": "alice", "role": "user"}


def test_server_root_is_the_owners_home_created_on_demand(tmp_path):
    cfg = _cfg(tmp_path)
    root = cfg.user_projects_root(ALICE)
    assert root == (cfg.user_data_root / "alice").resolve() and root.is_dir()
    # The owner can write a project there (the bug: clones in work_dir could not).
    cfg.confine_path(root / "Clone_of_x" / "a.str", ALICE, for_write=True)


def test_server_root_refuses_an_unresolved_or_unsafe_identity(tmp_path):
    cfg = _cfg(tmp_path)
    for bad in (None, {"id": 3, "username": "../bob", "role": "user"}):
        with pytest.raises(ValueError):
            cfg.user_projects_root(bad)


def test_local_root_is_work_dir(tmp_path):
    cfg = _cfg(tmp_path, mode="local")
    assert cfg.user_projects_root(None) == cfg.work_dir.resolve()


def _fn(name):
    tree = ast.parse(_HOME_PY.read_text())
    return next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )


@pytest.mark.parametrize("handler", ["_do_clone", "_do_import_project"])
def test_clone_and_import_take_their_root_from_user_projects_root(handler):
    src = ast.unparse(_fn(handler))
    assert "user_projects_root(" in src
    assert "config.work_dir" not in src, "server-mode copies must not go to the shared work_dir"
