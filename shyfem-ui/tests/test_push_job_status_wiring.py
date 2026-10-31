"""Job status reaches the pages by push (Shiny 1.9 ``run_once_when_idle``)
when the queue publishes events and Shiny can deliver them; the per-session
polls stay only as the fallback (Celery queue, or an older Shiny)."""

from __future__ import annotations

import inspect
import re


def _src_of(module, name):
    """Source of a top-level function, also when a decorator (``@module.server``)
    hides it behind a wrapper: slice the module's own source."""
    src = inspect.getsource(module)
    start = src.index(f"\ndef {name}(") + 1
    nxt = re.search(r"\n(?=(def |class |@))", src[start + 1 :])
    return src[start:] if nxt is None else src[start : start + 1 + nxt.start()]


def test_app_notifications_subscribe_and_keep_the_poll_only_as_fallback():
    import shyfem_ui.app as app_mod

    src = _src_of(app_mod, "_build_server")
    assert "_push = push_supported(session, job_queue)" in src
    poll = src.index("def _poll_job_notifications():")
    assert src.index("subscribe_session_to_job_events(") < poll
    # The legacy poll keeps its shape (other tests slice it by text) and
    # steps aside with an early return when push is on.
    first = src[poll + len("def _poll_job_notifications():") :].lstrip()
    assert first.startswith("if _push:"), first[:60]
    assert "id(session)" not in src


def test_run_page_refreshes_on_events_and_keeps_the_poll_only_as_fallback():
    from shyfem_ui.pages import run

    src = _src_of(run, "run_server")
    assert "_push = push_supported(session, job_queue)" in src
    assert "subscribe_session_to_job_events(" in src
    assert "workflow_engine.add_status_callback" in src
    poll = src.index("async def _auto_refresh():")
    assert src.index("subscribe_session_to_job_events(") < poll
    assert "if not _push:" in src[:poll]


def test_ensemble_page_refreshes_on_events_and_keeps_the_poll_only_as_fallback():
    from shyfem_ui.pages import ensemble

    src = _src_of(ensemble, "ensemble_server")
    assert "_push = push_supported(session, job_queue)" in src
    poll = src.index("async def _poll_ensemble():")
    assert src.index("subscribe_session_to_job_events(") < poll
    assert "if not _push:" in src[:poll]


def test_push_needs_a_shiny_with_run_once_when_idle():
    from types import SimpleNamespace

    from shyfem_ui.components.job_feed import push_supported

    queue = SimpleNamespace(supports_events=True)
    assert push_supported(SimpleNamespace(run_once_when_idle=lambda fn: None), queue)
    assert not push_supported(SimpleNamespace(), queue)  # an older Shiny keeps the polls
    assert not push_supported(
        SimpleNamespace(run_once_when_idle=lambda fn: None), SimpleNamespace(supports_events=False)
    )


def test_the_push_refresh_retries_and_follows_the_log_tail():
    from shyfem_ui.pages import run

    src = _src_of(run, "run_server")
    eff = src[src.index("async def _refresh_on_job_events():") :]
    eff = eff[: eff.index("if not _push:")]
    assert "await _refresh_log()" in eff
    assert "invalidate_later(5)" in eff


def test_the_run_handler_ignores_progress_of_jobs_it_does_not_show():
    from shyfem_ui.pages import run

    src = _src_of(run, "run_server")
    h = src[src.index("def _on_job_events(events)") :]
    h = h[: h.index("subscribe_session_to_job_events(")]
    assert "_shown_active_ids" in h and 'e.kind == "status"' in h
    code = "\n".join(
        line.split("#")[0] for line in h.split("with reactive.isolate():")[0].splitlines()
    )
    assert ".get()" not in code  # no reactive read per batch


def test_the_toast_handler_skips_batches_without_an_ended_job():
    import shyfem_ui.app as app_mod

    src = _src_of(app_mod, "_build_server")
    h = src[src.index("def _toast_job_events(events)") :]
    assert h.index("is_terminal") < h.index("current_user()")
