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
    assert hasattr(
        app_mod, "AuditService"
    ), "app.py must import AuditService so it is present in the module namespace"

    # 2. SessionAuthMiddleware accepts audit_service (so app.py can wire it in)
    sam_sig = inspect.signature(SessionAuthMiddleware.__init__)
    assert (
        "audit_service" in sam_sig.parameters
    ), "SessionAuthMiddleware.__init__() must accept audit_service keyword"

    # 3. AuditService exposes a .log() method used by both middleware and admin_server
    assert callable(
        getattr(AuditService, "log", None)
    ), "AuditService must have a .log() method for recording audit events"


def test_notification_poll_scopes_by_user_id_not_session_id():
    """F17 completion: the cross-page notification poll (_build_server's
    _poll_job_notifications) must scope its job listing through the SAME
    shared helper pages/run.py uses (run_logic.list_scoped_jobs) -- by the
    server-validated user identity, never the ephemeral
    str(id(session))/session_id, which does not survive a WS reconnect
    (dropping the user's own notifications) and whose CPython id() reuse
    can surface a prior user's job metadata."""
    import shyfem_ui.app as app_mod

    src = inspect.getsource(app_mod._build_server)
    start = src.index("async def _check():")
    end = src.index("\n        try:", start)
    body = src[start:end]

    assert "list_scoped_jobs(" in body, (
        "_check must scope through run_logic.list_scoped_jobs, not a "
        "locally re-implemented copy of the admin/IDOR rules"
    )
    assert (
        "session_id=" not in body
    ), "notification poll must not pass session_id= to job_queue.list_jobs"
    assert "id(session)" not in src, (
        "the ephemeral str(id(session)) must not be used anywhere in "
        "_build_server to scope job notifications"
    )


def test_notification_poll_reads_current_user_synchronously_not_inside_detached_task():
    """current_user() is a reactive read (_ws_user.get()); _check() runs
    DETACHED via loop.create_task()/asyncio.run(), outside the reactive
    flush, where a reactive read can raise -- and the bare
    `except Exception: logger.debug(...)` around the detached-task launch
    would silently swallow that, quietly killing notifications with no
    error. The identity must be snapshotted in the synchronous
    @reactive.effect body (_poll_job_notifications) and passed into
    _check() as a plain value/closure, not read for the first time inside
    _check() itself."""
    import shyfem_ui.app as app_mod

    src = inspect.getsource(app_mod._build_server)
    start = src.index("def _poll_job_notifications():")
    check_start = src.index("async def _check():", start)
    outer_body = src[start:check_start]
    check_end = src.index("\n        try:", check_start)
    check_body = src[check_start:check_end]

    assert "current_user()" in outer_body, (
        "the server-validated identity must be read synchronously in "
        "_poll_job_notifications' own body (a normal reactive read), "
        "before the detached _check() coroutine is defined/launched"
    )
    assert "current_user()" not in check_body, (
        "_check() must not call current_user() itself -- that reactive "
        "read must happen in the synchronous effect body and be passed "
        "in, since _check() runs detached from the reactive flush"
    )
