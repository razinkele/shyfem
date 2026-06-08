"""Tests for the ASGI lifespan wrapper that launches the maintenance loop."""

import asyncio

import pytest


class _FakeInner:
    """Inner ASGI app that records the scope types / lifespan messages it sees."""

    def __init__(self):
        self.scopes = []
        self.lifespan_msgs = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope["type"])
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                self.lifespan_msgs.append(msg["type"])
                if msg["type"] == "lifespan.shutdown":
                    return


class TestMaintenanceMiddleware:
    @pytest.mark.asyncio
    async def test_startup_launches_task_and_forwards_lifespan(self):
        from shyfem_ui.middleware.maintenance import MaintenanceMiddleware

        factory_calls = []

        async def fake_loop():
            await asyncio.sleep(10)

        def factory():
            factory_calls.append(True)
            return fake_loop()

        inner = _FakeInner()
        mw = MaintenanceMiddleware(inner, factory)
        msgs = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive():
            return next(msgs)

        async def send(_m):
            pass

        await mw({"type": "lifespan"}, receive, send)
        # task factory was invoked on startup, and the inner app still saw both events
        assert factory_calls == [True]
        assert inner.lifespan_msgs == ["lifespan.startup", "lifespan.shutdown"]

    @pytest.mark.asyncio
    async def test_non_lifespan_is_pure_passthrough(self):
        from shyfem_ui.middleware.maintenance import MaintenanceMiddleware

        inner = _FakeInner()
        mw = MaintenanceMiddleware(inner, lambda: asyncio.sleep(0))

        async def receive():
            return {}

        async def send(_m):
            pass

        await mw({"type": "http"}, receive, send)
        assert inner.scopes == ["http"]

    @pytest.mark.asyncio
    async def test_none_factory_does_not_launch(self):
        from shyfem_ui.middleware.maintenance import MaintenanceMiddleware

        inner = _FakeInner()
        mw = MaintenanceMiddleware(inner, None)
        msgs = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive():
            return next(msgs)

        async def send(_m):
            pass

        await mw({"type": "lifespan"}, receive, send)  # no task, still forwards
        assert inner.lifespan_msgs == ["lifespan.startup", "lifespan.shutdown"]
