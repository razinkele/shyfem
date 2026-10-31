"""Job status reaches the pages by push (Shiny 1.9 ``run_once_when_idle``)
when the queue publishes events; the per-session polls stay only as the
fallback for a queue that does not (Celery)."""

from __future__ import annotations

import inspect


def _src_of(module, name):
    """Source of a top-level function, also when a decorator (``@module.server``)
    hides it behind a wrapper: slice the module's own source."""
    import re

    src = inspect.getsource(module)
    start = src.index(f"\ndef {name}(") + 1
    nxt = re.search(r"\n(?=(def |class |@))", src[start + 1 :])
    return src[start:] if nxt is None else src[start : start + 1 + nxt.start()]


def test_app_notifications_subscribe_and_keep_the_poll_only_as_fallback():
    import shyfem_ui.app as app_mod

    src = _src_of(app_mod, "_build_server")
    assert "subscribe_session_to_job_events(" in src
    poll = src.index("def _poll_job_notifications():")
    assert src.index("subscribe_session_to_job_events(") < poll
    # The legacy poll keeps its exact shape (other tests slice it by text) and
    # steps aside with an early return when the queue publishes events.
    first_statement = src[poll + len("def _poll_job_notifications():") :].lstrip()
    assert first_statement.startswith("if job_queue.supports_events:"), first_statement[:60]
    assert "id(session)" not in src


def test_run_page_refreshes_on_events_and_keeps_the_poll_only_as_fallback():
    from shyfem_ui.pages import run

    src = _src_of(run, "run_server")
    assert "subscribe_session_to_job_events(" in src
    assert "workflow_engine.add_status_callback" in src  # the session's engine too
    guard = src.index("if not job_queue.supports_events:")
    assert guard < src.index("def _auto_refresh():")
    assert "invalidate_later(2)" not in src[:guard]


def test_ensemble_page_refreshes_on_events_and_keeps_the_poll_only_as_fallback():
    from shyfem_ui.pages import ensemble

    src = _src_of(ensemble, "ensemble_server")
    assert "subscribe_session_to_job_events(" in src
    guard = src.index("if not job_queue.supports_events:")
    assert guard < src.index("def _poll_ensemble():")
