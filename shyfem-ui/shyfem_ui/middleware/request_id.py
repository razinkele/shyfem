"""Request ID middleware for correlation across logs."""

import contextvars
import logging
import re
import uuid

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

#: An incoming X-Request-Id is echoed in the response and written into every
#: log line, so only a short plain token is taken from the client (nginx's
#: ``$request_id`` is 32 hex chars, a UUID is 36). Anything else -- overlong,
#: control characters, spaces, brackets that could forge a log line -- is
#: replaced by a fresh UUID (SEC-07).
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


class RequestIdFilter(logging.Filter):
    """Logging filter that adds request_id to log records."""

    def filter(self, record):
        record.request_id = request_id_var.get() or "-"
        return True


class RequestIdMiddleware:
    """ASGI middleware that generates a unique request ID per HTTP request.

    - Sets a contextvars.ContextVar for log propagation
    - Adds X-Request-Id response header
    - Reuses an incoming X-Request-Id only if it is a short plain token
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
                candidate = header_value.decode("latin-1")
                if _VALID_REQUEST_ID.fullmatch(candidate):
                    req_id = candidate
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
