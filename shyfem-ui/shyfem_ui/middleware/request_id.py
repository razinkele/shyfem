"""Request ID middleware for correlation across logs."""

import contextvars
import logging
import uuid

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class RequestIdFilter(logging.Filter):
    """Logging filter that adds request_id to log records."""

    def filter(self, record):
        record.request_id = request_id_var.get() or "-"
        return True


class RequestIdMiddleware:
    """ASGI middleware that generates a unique request ID per HTTP request.

    - Sets a contextvars.ContextVar for log propagation
    - Adds X-Request-Id response header
    - Passes through non-HTTP scopes unchanged
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Check for incoming X-Request-Id header (proxy forwarding)
        req_id = None
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-request-id":
                req_id = header_value.decode("latin-1")
                break

        if not req_id:
            req_id = str(uuid.uuid4())

        token = request_id_var.set(req_id)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"x-request-id", req_id.encode("latin-1")])
                message = {**message, "headers": headers}
            result = send(message)
            if result is not None:
                await result

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
