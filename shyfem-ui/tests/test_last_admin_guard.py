"""SEC-01: the last active admin cannot be removed, and startup survives one.

The sole admin could demote or deactivate themself in one click. After a
demotion the next worker start crashed in ``ensure_admin`` ("Username already
exists: admin", unwrapped in app.py, so the whole site failed to start); after
a deactivation nobody could sign in as admin again.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.models.user import User
from shyfem_ui.services.auth_service import AuthService

PW = "strongpass123"


@pytest.fixture()
def svc():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return AuthService(session_factory=sessionmaker(bind=engine))


def _row(svc, uid):
    s = svc._session_factory()
    try:
        u = s.query(User).filter_by(id=uid).one()
        return u.role, u.is_active
    finally:
        s.close()


@pytest.mark.parametrize("change", [{"role": "user"}, {"is_active": False}])
def test_the_only_admin_cannot_be_demoted_or_deactivated(svc, change):
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    with pytest.raises(ValueError, match="last active admin"):
        svc.update_user(admin["id"], **change)
    assert _row(svc, admin["id"]) == ("admin", True)


@pytest.mark.parametrize("change", [{"role": "user"}, {"is_active": False}])
def test_an_inactive_second_admin_does_not_count(svc, change):
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    other = svc.create_user("georg", PW, role="admin", email="georg@example.org")
    svc.update_user(other["id"], is_active=False)  # allowed: admin still active
    with pytest.raises(ValueError, match="last active admin"):
        svc.update_user(admin["id"], **change)


def test_with_two_active_admins_one_may_step_down(svc):
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    svc.create_user("georg", PW, role="admin", email="georg@example.org")
    assert svc.update_user(admin["id"], role="user")["role"] == "user"


def test_other_edits_of_the_last_admin_still_work(svc):
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    assert svc.update_user(admin["id"], display_name="Boss")["display_name"] == "Boss"
    assert svc.update_user(admin["id"], role="admin", is_active=True)["role"] == "admin"


def test_the_last_active_admin_cannot_be_deleted_even_with_an_inactive_one(svc):
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    other = svc.create_user("georg", PW, role="admin", email="georg@example.org")
    svc.update_user(other["id"], is_active=False)
    with pytest.raises(ValueError, match="last"):
        svc.delete_user(admin["id"])


def test_startup_restores_the_configured_admin_instead_of_crashing(svc):
    """A database left with no active admin (e.g. from before this guard)
    must not stop every worker from starting."""
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    s = svc._session_factory()
    s.query(User).filter_by(id=admin["id"]).update({"role": "user", "is_active": False})
    s.commit()
    s.close()
    got = svc.ensure_admin("admin", "a-different-password")
    assert got["id"] == admin["id"]
    assert _row(svc, admin["id"]) == ("admin", True)
    # The password is not reset by a restart.
    assert svc.authenticate("admin", PW) is not None


def test_startup_creates_the_admin_on_an_empty_database(svc):
    got = svc.ensure_admin("admin", PW)
    assert got["role"] == "admin"


def _force(svc, uid, **fields):
    s = svc._session_factory()
    s.query(User).filter_by(id=uid).update(fields)
    s.commit()
    s.close()


def test_startup_reactivates_a_deactivated_admin(svc):
    admin = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    _force(svc, admin["id"], is_active=False)  # role still admin, cannot sign in
    svc.ensure_admin("admin", PW)
    assert _row(svc, admin["id"]) == ("admin", True)


def test_demoting_an_already_inactive_admin_is_never_blocked(svc):
    """It changes nobody's ability to sign in as admin, so even a database
    with no active admin at all (pre-guard state) may tidy it up."""
    a = svc.create_user("admin", PW, role="admin", email="admin@example.org")
    b = svc.create_user("georg", PW, role="admin", email="georg@example.org")
    _force(svc, b["id"], is_active=False)
    _force(svc, a["id"], role="user")
    assert svc.update_user(b["id"], role="user")["role"] == "user"
