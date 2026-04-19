"""Smoke tests that app.py wires services together correctly."""

import importlib

from shyfem_ui.services.audit_service import AuditService  # noqa: F401  (import smoke)


def test_audit_service_is_instantiated_in_app():
    """Regression test: app.py must create an AuditService and pass it
    into both SessionAuthMiddleware and admin_server. This test asserts
    the import survives (catches accidental removal)."""
    mod = importlib.import_module("shyfem_ui.app")
    src = open(mod.__file__).read()
    assert "AuditService(" in src, "app.py must instantiate AuditService"
    assert "audit_service=audit_service" in src, (
        "app.py must pass audit_service into SessionAuthMiddleware / admin_server"
    )
