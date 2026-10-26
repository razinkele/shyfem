"""Admins can READ every project folder; writes stay in their own home.

An admin's Dashboard lists every project (access_control grants admins all
roles), but ``confine_path`` gave admins no read reach beyond their own home
and explicit shares. Opening another user's project therefore showed
"Project directory unavailable" in every file picker (Grid Prep on the
admin-owned Curonian 29-box, for the second admin account). The admin reach is
bounded by the app's two project-storage roots, never the whole filesystem.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.components.project_select import project_dir_select
from shyfem_ui.config import Config
from shyfem_ui.db.base import Base


def _empty_db_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _server_config(tmp_path: Path) -> Config:
    for d in ("users", "work", "shyfem"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode="server",
        user_data_root=tmp_path / "users",
        work_dir=tmp_path / "work",
        shyfem_dir=tmp_path / "shyfem",
        default_admin_password="strongpass123",
    )


GEORG = {"id": 8, "username": "georg", "role": "admin"}
ALICE = {"id": 2, "username": "alice", "role": "user"}
TUTOR = {"id": 3, "username": "user", "role": "tutorial"}


@pytest.fixture
def tree(tmp_path):
    cfg = _server_config(tmp_path)
    proj = cfg.user_data_root / "admin" / "Curonian 29-box"
    (proj / "GRID").mkdir(parents=True)
    (proj / "GRID" / "box.grd").write_text("grd")
    legacy = cfg.work_dir / "legacy_proj"
    legacy.mkdir()
    (legacy / "a.str").write_text("str")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("x")
    return cfg, proj, legacy, outside


def _confine(cfg, path, user, **kw):
    return cfg.confine_path(path, user, session_factory=_empty_db_factory(), **kw)


def test_admin_reads_a_project_in_another_users_home(tree):
    cfg, proj, _, _ = tree
    f = proj / "GRID" / "box.grd"
    assert _confine(cfg, f, GEORG, must_exist=True) == f.resolve()
    assert _confine(cfg, proj, GEORG, must_exist=True) == proj.resolve()


def test_admin_reads_a_project_in_the_shared_work_dir(tree):
    cfg, _, legacy, _ = tree
    assert _confine(cfg, legacy / "a.str", GEORG, must_exist=True) == (legacy / "a.str").resolve()


def test_admin_read_reach_stops_at_the_storage_roots(tree):
    cfg, _, _, outside = tree
    with pytest.raises(ValueError):
        _confine(cfg, outside / "secret", GEORG, must_exist=True)


def test_admin_read_cannot_leave_the_roots_through_a_symlink(tree):
    cfg, proj, _, outside = tree
    (proj / "link").symlink_to(outside / "secret")
    with pytest.raises(ValueError):
        _confine(cfg, proj / "link", GEORG, must_exist=True)


def test_admin_writes_stay_in_their_own_home(tree):
    cfg, proj, legacy, _ = tree
    for target in (proj / "GRID" / "out.grd", legacy / "out.grd"):
        with pytest.raises(ValueError):
            _confine(cfg, target, GEORG, for_write=True)
    own = cfg.user_data_root / "georg" / "p" / "out.grd"
    assert _confine(cfg, own, GEORG, for_write=True) == own.resolve()


@pytest.mark.parametrize("user", [ALICE, TUTOR], ids=["user", "tutorial"])
def test_other_roles_still_cannot_read_another_users_project(tree, user):
    cfg, proj, _, _ = tree
    with pytest.raises(ValueError):
        _confine(cfg, proj / "GRID" / "box.grd", user, must_exist=True)


def test_grid_prep_dir_picker_lists_another_users_project_for_an_admin(tree):
    cfg, proj, _, _ = tree
    p = {"id": 4, "name": "Curonian 29-box", "work_dir": str(proj)}
    html = str(project_dir_select("output_dir", "Output Directory", proj=p, user=GEORG, config=cfg))
    assert "Project directory unavailable" not in html
    assert "GRID/" in html
