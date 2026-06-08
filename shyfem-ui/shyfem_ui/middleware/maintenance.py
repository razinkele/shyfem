"""ASGI lifespan wrapper that runs the periodic maintenance loop.

Starting a process-global background task needs a running event loop, which
exists only once the server is up — so we hook the ASGI ``lifespan`` protocol:
launch the loop on ``lifespan.startup`` and cancel it on ``lifespan.shutdown``,
while forwarding every lifespan event to the inner app so its own startup still
runs. Non-lifespan scopes pass straight through.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class MaintenanceMiddleware:
    """Launch ``task_factory()`` as a background task on lifespan startup.

    ``task_factory`` is a zero-arg callable returning a coroutine (the
    maintenance loop). Pass ``None`` to disable (pure pass-through).
    """

    def __init__(self, app, task_factory):
        self.app = app
        self._task_factory = task_factory
        self._task = None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "lifespan":
            return await self.app(scope, receive, send)

        async def wrapped_receive():
            message = await receive()
            if message["type"] == "lifespan.startup":
                if self._task is None and self._task_factory is not None:
                    self._task = asyncio.ensure_future(self._task_factory())
                    logger.info("maintenance task launched on lifespan startup")
            elif message["type"] == "lifespan.shutdown":
                if self._task is not None:
                    self._task.cancel()
            return message

        return await self.app(scope, wrapped_receive, send)
