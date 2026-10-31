"""The startup tutorial bootstrap shares only ITS project (H-09).

It looked the project up by name alone, so any user's project called
"Mar Menor Tutorial" was taken for it and shared, as editor, with the
tutorial account at every start.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path / "shyfem"))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))

    import shyfem_ui.config as cfg_mod
    import shyfem_ui.db.base as db_mod

    cfg_mod._config = None
    db_mod._engine = None
    db_mod._SessionLocal = None
    from shyfem_ui.db.base import init_db

    init_db()
    src = tmp_path / "shyfem" / "testcases" / "examples" / "mar_menor"
    (src / "GRID").mkdir(parents=True)
    (src / "GRID" / "MM_coarse.grd").write_text("1 1 0 0.0 0.0\n")
    yield
    db_mod._engine = None
    db_mod._SessionLocal = None
    cfg_mod._config = None


@pytest.fixture
def users():
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.user import User

    with db_session() as db:
        ids = {}
        for name, role in (("admin", "admin"), ("tutor", "tutorial"), ("bob", "user")):
            u = User(username=name, password_hash="x", role=role)
            db.add(u)
            db.flush()
            ids[name] = u.id
    return ids


def _project(name, work_dir, owner_id):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project

    with db_session() as db:
        p = Project(name=name, work_dir=str(work_dir), owner_id=owner_id)
        db.add(p)
        db.flush()
        return p.id


def _shared_with(user_id):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.user import ProjectPermission

    with db_session() as db:
        return sorted(
            (r.project_id, r.role)
            for r in db.query(ProjectPermission).filter_by(user_id=user_id).all()
        )


def _tutorial_rows(admin_id):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project

    with db_session() as db:
        return [
            (p.id, p.work_dir)
            for p in db.query(Project).filter_by(owner_id=admin_id).order_by(Project.id).all()
        ]


def test_a_users_project_with_the_tutorial_name_is_not_shared(users, tmp_path, caplog):
    """Project names are unique, so the bootstrap cannot add its own beside
    it: it skips, says so in the log, and shares nothing."""
    from shyfem_ui.app import _bootstrap_tutorial_project
    from shyfem_ui.config import get_config

    config = get_config()
    _project("Mar Menor Tutorial", tmp_path / "home" / "bob" / "mine", users["bob"])

    _bootstrap_tutorial_project(users["admin"], users["tutor"], config)

    assert _shared_with(users["tutor"]) == []
    assert _tutorial_rows(users["admin"]) == []
    assert not (config.work_dir / "Mar Menor Tutorial").exists()
    assert "not bootstrapping" in caplog.text


def test_the_bootstrapped_project_is_found_again(users):
    """Idempotent: a second start reuses the admin's project, even renamed."""
    from shyfem_ui.app import _bootstrap_tutorial_project
    from shyfem_ui.config import get_config
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project

    config = get_config()
    _bootstrap_tutorial_project(users["admin"], users["tutor"], config)
    ((pid, _),) = _tutorial_rows(users["admin"])
    with db_session() as db:
        db.query(Project).filter_by(id=pid).one().name = "Mar Menor (renamed)"

    _bootstrap_tutorial_project(users["admin"], users["tutor"], config)

    assert [p for p, _ in _tutorial_rows(users["admin"])] == [pid]
    assert _shared_with(users["tutor"]) == [(pid, "editor")]


def test_a_folder_owned_by_someone_else_is_left_alone(users):
    """A row at the bootstrap folder that the admin does not own is neither
    shared nor duplicated."""
    from shyfem_ui.app import _bootstrap_tutorial_project
    from shyfem_ui.config import get_config

    config = get_config()
    _project("something", config.work_dir / "Mar Menor Tutorial", users["bob"])

    _bootstrap_tutorial_project(users["admin"], users["tutor"], config)

    assert _tutorial_rows(users["admin"]) == []
    assert _shared_with(users["tutor"]) == []
