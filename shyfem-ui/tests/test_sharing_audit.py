"""SEC-05: sharing a project and removing a user's access are written to the
audit log, like the admin page's user-management actions.

The handlers live inside ``@module.server home_server`` (driving run_server
deadlocks under pytest), so the audit write is a module-level helper tested
for behaviour here, and the handlers' call order and the app wiring are
pinned by source inspection (the established pattern, see
tests/test_home_user_hoist.py).
"""

import inspect
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import shyfem_ui.app as app_mod
import shyfem_ui.pages.home as home_page
from shyfem_ui.db.base import Base
from shyfem_ui.models.audit_log import AuditLog
from shyfem_ui.services.audit_service import AuditService
from tests._test_helpers import get_server_source


@pytest.fixture
def audit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    return AuditService(session_factory=factory), factory


def _rows(factory):
    db = factory()
    try:
        return [(r.username, r.action, r.detail) for r in db.query(AuditLog).all()]
    finally:
        db.close()


def test_share_is_audited_with_actor_project_target_and_role(audit):
    svc, factory = audit
    home_page._audit_sharing(svc, {"id": 1, "username": "alice"}, "share_project", 5, 7, "editor")
    assert _rows(factory) == [
        ("alice", "share_project", "project_id=5, target_user_id=7, role=editor")
    ]


def test_unshare_is_audited_without_role(audit):
    svc, factory = audit
    home_page._audit_sharing(svc, {"id": 1, "username": "alice"}, "unshare_project", 5, 7)
    assert _rows(factory) == [("alice", "unshare_project", "project_id=5, target_user_id=7")]


def test_unresolved_actor_reads_unknown(audit):
    svc, factory = audit
    home_page._audit_sharing(svc, None, "unshare_project", 5, 7)
    assert _rows(factory)[0][0] == "unknown"


def test_no_audit_service_is_a_noop():
    home_page._audit_sharing(None, {"username": "alice"}, "share_project", 5, 7, "viewer")


def test_audit_failure_does_not_escape_the_handler():
    class Boom:
        def log(self, **kw):
            raise RuntimeError("db gone")

    home_page._audit_sharing(Boom(), {"username": "alice"}, "share_project", 5, 7, "viewer")


def _handler_body(src: str, header: str) -> str:
    start = src.index(header)
    end = src.find("\n    def ", start + len(header))
    return src[start : end if end != -1 else None]


@pytest.mark.parametrize(
    "header, mutation, action",
    [
        ("def _do_share():", "share_project(pid, uid, role)", '"share_project"'),
        ("def _unshare():", "unshare_project(project_id, target_user_id)", '"unshare_project"'),
    ],
)
def test_sharing_handlers_audit_after_the_mutation(header, mutation, action):
    body = _handler_body(get_server_source(home_page, "home_server"), header)
    assert mutation in body
    m = re.search(r"_audit_sharing\(\s*audit_service,[^)]*" + re.escape(action), body)
    assert m, f"{header} does not write a {action} audit entry"
    assert body.index(mutation) < m.start(), f"{header} audits before the mutation"


def test_home_server_accepts_and_app_passes_audit_service():
    inner = home_page.home_server.__closure__[0].cell_contents
    assert "audit_service" in inspect.signature(inner).parameters
    src = inspect.getsource(app_mod._build_server)
    call = src[src.index("home.home_server(") :]
    call = call[: call.index("\n    )")]
    assert "audit_service=audit_service" in call, "app.py never hands audit_service to Dashboard"
