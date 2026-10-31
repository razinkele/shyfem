"""Service events delivered into one Shiny session, by push.

Shiny 1.9 gives a session ``run_once_when_idle(fn)``: ``fn`` runs once this
session's effects have finished and its outputs were sent, with the session
current. That is the one safe way to change a session's reactive state from
outside its reactive graph (a queue callback, a timer, another thread). A
feed collects the events a service publishes, hands them to the session's
loop (any thread may publish), coalesces everything that arrives before the
session is idle into one batch, and calls the page's handler with it. The
handler is synchronous: it sets reactive values (or shows a notification);
async work follows in an effect that depends on those values.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class SessionEventFeed:
    """Events from one callback source into one session, a batch per idle cycle."""

    def __init__(self, session, on_events: Callable[[list[Any]], None], *, key: str):
        self._session = session
        self._on_events = on_events
        self._key = key
        # The session's loop, captured here: ``push`` may run on another thread.
        self._loop = asyncio.get_running_loop()
        self._pending: list[Any] = []
        self._scheduled = False
        self._closed = False
        self._remove: Callable[[], None] | None = None

    @property
    def key(self) -> str:
        return self._key

    def attach(
        self,
        add_callback: Callable[[str, Callable[[Any], None]], None],
        remove_callback: Callable[[str], None],
    ) -> SessionEventFeed:
        """Subscribe ``push`` under this feed's key; unsubscribe when the session ends."""
        add_callback(self._key, self.push)
        self._remove = lambda: remove_callback(self._key)
        self._session.on_ended(self.close)
        return self

    def push(self, event: Any) -> None:
        """Take one event; safe to call from any thread."""
        if self._closed:
            return
        self._loop.call_soon_threadsafe(self._enqueue, event)

    def _enqueue(self, event: Any) -> None:
        if self._closed:
            return
        self._pending.append(event)
        if self._scheduled:
            return  # the pending idle run picks this one up too
        self._scheduled = True
        try:
            self._session.run_once_when_idle(self._flush)
        except Exception:
            self._scheduled = False
            logger.exception("could not schedule job events for %s", self._key)

    def _flush(self) -> None:
        # Runs with the session current. An error here would close the
        # session (run_once_when_idle's contract), so none may escape.
        batch, self._pending = self._pending, []
        self._scheduled = False
        if self._closed or not batch:
            return
        try:
            self._on_events(batch)
        except Exception:
            logger.exception("job event handler failed (%s)", self._key)

    def close(self) -> None:
        """Stop delivering; drop what is pending; unsubscribe from the source."""
        self._closed = True
        self._pending.clear()
        remove, self._remove = self._remove, None
        if remove is not None:
            try:
                remove()
            except Exception:
                logger.debug("unsubscribe failed for %s", self._key, exc_info=True)


def subscribe_session_to_job_events(
    session, job_queue, on_events: Callable[[list[Any]], None], *, key: str = "job-events"
) -> SessionEventFeed:
    """Wake ``session`` with each batch of the queue's :class:`JobEvent`s.

    ``key`` names the subscriber (one feed per page per session); the
    session's own id makes it unique across sessions.
    """
    feed = SessionEventFeed(session, on_events, key=f"{key}:{session.id}")
    return feed.attach(job_queue.add_event_callback, job_queue.remove_event_callback)
