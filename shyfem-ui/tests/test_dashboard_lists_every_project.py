"""H-01: the Dashboard is the only place a project can be opened, and it
listed only the 10 most recently updated, so an 11th project could never be
opened again (and the "Projects" count said 10)."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User
from shyfem_ui.pages.home import _dashboard_projects

N = 25


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    admin = User(username="admin", password_hash="x", role="admin", display_name="A")
    alice = User(username="alice", password_hash="x", role="user", display_name="Al")
    bob = User(username="bob", password_hash="x", role="user", display_name="B")
    s.add_all([admin, alice, bob])
    s.flush()
    for i in range(N):
        s.add(Project(name=f"alice {i}", work_dir=f"/tmp/a{i}", owner_id=alice.id))
    shared = Project(name="bob shared", work_dir="/tmp/bs", owner_id=bob.id)
    s.add_all([shared, Project(name="bob private", work_dir="/tmp/bp", owner_id=bob.id)])
    s.flush()
    s.add(ProjectPermission(project_id=shared.id, user_id=alice.id, role="viewer"))
    s.commit()
    yield s, {u.username: {"id": u.id, "role": u.role} for u in (admin, alice, bob)}
    s.close()


def test_a_user_sees_all_their_projects_and_shares(db):
    s, users = db
    names = {p.name for p in _dashboard_projects(s, users["alice"], is_server_mode=True)}
    assert len(names) == N + 1
    assert "bob shared" in names and "bob private" not in names


def test_an_admin_sees_every_project(db):
    s, users = db
    assert len(_dashboard_projects(s, users["admin"], is_server_mode=True)) == N + 2


def test_local_mode_lists_every_project(db):
    s, _ = db
    assert len(_dashboard_projects(s, None, is_server_mode=False)) == N + 2


def test_unresolved_identity_still_sees_nothing_in_server_mode(db):
    s, _ = db
    assert _dashboard_projects(s, None, is_server_mode=True) == []
