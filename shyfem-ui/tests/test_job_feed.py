"""The session feed: service events -> one Shiny session, through
``session.run_once_when_idle`` (Shiny 1.9), coalesced per cycle.

A fake session stands in for Shiny: it records the idle functions and the
end callbacks, and the test runs them.
"""

from __future__ import annotations

import asyncio
import logging

from shyfem_ui.components import job_feed
from shyfem_ui.services.job_queue import JobEvent, JobStatus


class _FakeSession:
    def __init__(self):
        self.id = "sess-1"
        self.idle_fns: list = []
        self.ended: list = []

    def run_once_when_idle(self, fn):
        self.idle_fns.append(fn)

    def on_ended(self, fn):
        self.ended.append(fn)
        return lambda: None

    def run_idle(self):
        fns, self.idle_fns = self.idle_fns, []
        for fn in fns:
            fn()

    def end(self):
        for fn in self.ended:
            fn()


class _Source:
    """A stand-in for a queue's add/remove_event_callback pair."""

    def __init__(self):
        self.callbacks: dict = {}

    def add_event_callback(self, key, cb):
        self.callbacks[key] = cb

    def remove_event_callback(self, key):
        self.callbacks.pop(key, None)

    def publish(self, ev):
        for cb in list(self.callbacks.values()):
            cb(ev)


def _ev(job_id="j1", status=JobStatus.RUNNING):
    return JobEvent(
        job_id=job_id, name="n", status=status, previous=None, user_id=None, project_id=None
    )


async def test_subscribing_registers_under_the_session_id_and_unregisters_at_its_end():
    session, source, got = _FakeSession(), _Source(), []
    job_feed.subscribe_session_to_job_events(session, source, got.append)
    assert len(source.callbacks) == 1 and "sess-1" in next(iter(source.callbacks))
    session.end()
    assert source.callbacks == {}


async def test_events_before_the_session_is_idle_arrive_as_one_batch():
    session, source, got = _FakeSession(), _Source(), []
    job_feed.subscribe_session_to_job_events(session, source, got.append)
    for i in range(3):
        source.publish(_ev(job_id=f"j{i}"))
    await asyncio.sleep(0)  # the feed hands events to the loop first
    assert len(session.idle_fns) == 1  # coalesced: one idle run, not three
    session.run_idle()
    assert [[e.job_id for e in batch] for batch in got] == [["j0", "j1", "j2"]]


async def test_an_event_after_a_flush_schedules_a_new_flush():
    session, source, got = _FakeSession(), _Source(), []
    job_feed.subscribe_session_to_job_events(session, source, got.append)
    source.publish(_ev("a"))
    await asyncio.sleep(0)
    session.run_idle()
    source.publish(_ev("b"))
    await asyncio.sleep(0)
    assert len(session.idle_fns) == 1
    session.run_idle()
    assert [[e.job_id for e in b] for b in got] == [["a"], ["b"]]


async def test_an_event_published_from_another_thread_still_arrives():
    session, source, got = _FakeSession(), _Source(), []
    job_feed.subscribe_session_to_job_events(session, source, got.append)
    await asyncio.to_thread(source.publish, _ev("t"))
    await asyncio.sleep(0.01)
    session.run_idle()
    assert [e.job_id for b in got for e in b] == ["t"]


async def test_events_after_the_session_ended_are_dropped():
    session, source, got = _FakeSession(), _Source(), []
    cb_holder = {}
    job_feed.subscribe_session_to_job_events(session, source, got.append)
    cb_holder.update(source.callbacks)
    session.end()
    for cb in cb_holder.values():  # a publisher that still held the callback
        cb(_ev("late"))
    await asyncio.sleep(0)
    assert session.idle_fns == [] and got == []


async def test_a_failing_handler_is_logged_and_does_not_escape_the_idle_run(caplog):
    session, source = _FakeSession(), _Source()

    def boom(batch):
        raise RuntimeError("handler broke")

    job_feed.subscribe_session_to_job_events(session, source, boom)
    source.publish(_ev())
    await asyncio.sleep(0)
    with caplog.at_level(logging.ERROR):
        session.run_idle()  # must not raise: an error here would close the session
    assert any(
        "handler broke" in r.getMessage() or "job event" in r.getMessage().lower()
        for r in caplog.records
    )


def test_the_idle_function_is_synchronous():
    # Shiny rejects an async fn for run_once_when_idle; the feed must hand it a plain one.
    session, source = _FakeSession(), _Source()

    async def _run():
        job_feed.subscribe_session_to_job_events(session, source, lambda b: None)
        source.publish(_ev())
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert session.idle_fns and not asyncio.iscoroutinefunction(session.idle_fns[0])
