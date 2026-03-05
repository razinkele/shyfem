"""ASGI middleware for HTTP Basic Authentication."""

import base64
import hashlib
import hmac


class BasicAuthMiddleware:
    """ASGI middleware that enforces HTTP Basic Authentication."""

    REALM = "SHYFEM Workbench"

    def __init__(self, app, username: str, password: str):
        self.app = app
        self.username = username
        # Store a hash so the plaintext password isn't kept in memory
        self._password_hash = hashlib.sha256(password.encode()).digest()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()

        if self._check_credentials(auth_header):
            return await self.app(scope, receive, send)

        # Return 401 Unauthorized
        if scope["type"] == "websocket":
            # WebSocket connections can't send 401; just close
            await send({"type": "websocket.close", "code": 4001})
            return

        response_body = b"Authentication required"
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"www-authenticate", f'Basic realm="{self.REALM}"'.encode()],
                    [b"content-type", b"text/plain"],
                    [b"content-length", str(len(response_body)).encode()],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": response_body,
            }
        )

    def _check_credentials(self, auth_header: str) -> bool:
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            username, password = decoded.split(":", 1)
        except Exception:
            return False

        password_hash = hashlib.sha256(password.encode()).digest()
        return hmac.compare_digest(
            username.encode(), self.username.encode()
        ) and hmac.compare_digest(password_hash, self._password_hash)
