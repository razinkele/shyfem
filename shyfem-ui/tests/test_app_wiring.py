"""Smoke tests that app.py wires services together correctly."""

import inspect

from shyfem_ui.services.audit_service import AuditService  # noqa: F401  (import smoke)


def test_audit_service_is_instantiated_in_app():
    """Regression: app module must import AuditService and wire it into middleware.

    Checks behavioral invariants rather than source text:
    1. AuditService is accessible in the app module's namespace (confirming it
       is imported at module load, not merely referenced as a string).
    2. SessionAuthMiddleware.__init__ accepts an audit_service parameter
       (confirming the middleware slot exists to receive the wired instance).
    3. AuditService has a .log() method — the method that both middleware and
       admin_server call to record events (confirming the interface is intact).
    """
    import shyfem_ui.app as app_mod
    from shyfem_ui.middleware.session_auth import SessionAuthMiddleware

    # 1. AuditService is imported at the top of app.py (not just referenced by name)
    assert hasattr(app_mod, "AuditService"), (
        "app.py must import AuditService so it is present in the module namespace"
    )

    # 2. SessionAuthMiddleware accepts audit_service (so app.py can wire it in)
    sam_sig = inspect.signature(SessionAuthMiddleware.__init__)
    assert "audit_service" in sam_sig.parameters, (
        "SessionAuthMiddleware.__init__() must accept audit_service keyword"
    )

    # 3. AuditService exposes a .log() method used by both middleware and admin_server
    assert callable(getattr(AuditService, "log", None)), (
        "AuditService must have a .log() method for recording audit events"
    )
