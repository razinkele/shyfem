"""Session-based authentication middleware for the SHYFEM UI ASGI app.

Reads a ``shyfem_session`` cookie, validates it via :class:`AuthService`,
and gates access to the inner application.  Unauthenticated HTTP requests
are redirected to ``/login``; unauthenticated WebSocket connections are
closed with code 4001.

In *local mode* authentication is bypassed entirely and a synthetic admin
user is injected into every request.
"""

import contextvars
import logging
import urllib.parse

logger = logging.getLogger(__name__)

# ContextVar holding the authenticated user dict for the current request.
_user_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "current_user", default=None
)

_SYNTHETIC_LOCAL_USER: dict = {
    "id": 0,
    "username": "local",
    "display_name": "Local User",
    "email": None,
    "role": "admin",
    "is_active": True,
}


def get_current_user() -> dict | None:
    """Return the authenticated user dict for the current ASGI scope.

    Returns ``None`` when called outside of an authenticated request context.
    """
    return _user_var.get()


# ------------------------------------------------------------------
# Cookie parsing helper
# ------------------------------------------------------------------


def _parse_cookie(raw: bytes) -> dict[str, str]:
    """Parse a raw ``Cookie`` header value into a ``{name: value}`` dict.

    Handles the common ``name=value; name2=value2`` format.  Cookies
    without a ``=`` are stored with an empty-string value.
    """
    if not raw:
        return {}
    text = raw.decode("latin-1")
    cookies: dict[str, str] = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
        else:
            cookies[part.strip()] = ""
    return cookies


# ------------------------------------------------------------------
# Login page HTML
# ------------------------------------------------------------------

_LOGIN_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SHYFEM Login</title>
  <link rel="stylesheet"
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YcnS/1Vb6E5lr8e9JOoFzF5ldQ3X6OR6poi"
        crossorigin="anonymous">
  <style>
    body {{
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .login-card {{
      max-width: 420px;
      width: 100%;
    }}
  </style>
</head>
<body>
  <div class="login-card">
    <div class="card shadow-lg">
      <div class="card-body p-4">
        <h3 class="card-title text-center mb-4">SHYFEM Login</h3>
        {error}
        <form method="post" action="{login_action}">
          <div class="mb-3">
            <label for="username" class="form-label">Username</label>
            <input type="text" class="form-control" id="username"
                   name="username" required autofocus>
          </div>
          <div class="mb-3">
            <label for="password" class="form-label">Password</label>
            <input type="password" class="form-control" id="password"
                   name="password" required>
          </div>
          <button type="submit" class="btn btn-primary w-100">Sign In</button>
        </form>
      </div>
    </div>
  </div>
</body>
</html>
"""


# ------------------------------------------------------------------
# ASGI Middleware
# ------------------------------------------------------------------


class SessionAuthMiddleware:
    """ASGI middleware that enforces cookie-based session authentication.

    Parameters
    ----------
    app:
        The inner ASGI application.
    auth_service:
        An :class:`AuthService` instance (or compatible mock).
    local_mode:
        When ``True``, bypass all authentication and inject a synthetic
        admin user into every request.
    session_ttl_hours:
        Default session time-to-live passed to ``create_session``.
    """

    def __init__(self, app, auth_service, local_mode=False, session_ttl_hours=24, root_path=""):
        self.app = app
        self.auth_service = auth_service
        self.local_mode = local_mode
        self.session_ttl_hours = session_ttl_hours
        self.root_path = root_path.rstrip("/")

    async def __call__(self, scope, receive, send):
        # ----------------------------------------------------------
        # Local mode: skip everything, inject synthetic admin
        # ----------------------------------------------------------
        if self.local_mode:
            token = _user_var.set(_SYNTHETIC_LOCAL_USER)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return

        # ----------------------------------------------------------
        # Extract session cookie and root_path from scope
        # ----------------------------------------------------------
        session_token = self._extract_session_token(scope)
        root_path = scope.get("root_path", "") or self.root_path

        # ----------------------------------------------------------
        # HTTP requests
        # ----------------------------------------------------------
        if scope["type"] == "http":
            path = scope.get("path", "/")
            method = scope.get("method", "GET")

            # GET /login -- serve the login page
            if path == "/login" and method == "GET":
                await self._serve_login_page(send, root_path=root_path)
                return

            # POST /login -- authenticate credentials
            if path == "/login" and method == "POST":
                await self._handle_login_post(receive, send, root_path=root_path)
                return

            # GET /logout -- destroy session
            if path == "/logout" and method == "GET":
                await self._handle_logout(session_token, send, root_path=root_path)
                return

            # All other paths: require valid session
            user = None
            if session_token:
                user = self.auth_service.validate_session(session_token)

            if user is None:
                await self._redirect(send, f"{root_path}/login")
                return

            token = _user_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return

        # ----------------------------------------------------------
        # WebSocket connections
        # ----------------------------------------------------------
        if scope["type"] == "websocket":
            user = None
            if session_token:
                user = self.auth_service.validate_session(session_token)

            if user is None and not self.root_path:
                # Direct deployment: reject unauthenticated WebSocket.
                # Behind reverse proxy (Shiny Server): skip WS auth
                # because the proxy gates access at the HTTP layer and
                # its internal WS connection doesn't forward cookies.
                await send({"type": "websocket.close", "code": 4001})
                return

            token = _user_var.set(user)
            try:
                await self.app(scope, receive, send)
            finally:
                _user_var.reset(token)
            return

        # ----------------------------------------------------------
        # Other scope types (e.g. lifespan): pass through
        # ----------------------------------------------------------
        await self.app(scope, receive, send)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_session_token(scope) -> str | None:
        """Read the ``shyfem_session`` cookie from ASGI scope headers."""
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                cookies = _parse_cookie(header_value)
                return cookies.get("shyfem_session")
        return None

    async def _serve_login_page(self, send, error: str = "", root_path: str = ""):
        """Send the login page HTML as a 200 response."""
        html = _LOGIN_HTML.format(error=error, login_action=f"{root_path}/login")
        body = html.encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": body,
            }
        )

    async def _handle_login_post(self, receive, send, root_path: str = ""):
        """Parse POST form data, authenticate, and redirect or re-render."""
        message = await receive()
        raw_body = message.get("body", b"")
        form = urllib.parse.parse_qs(raw_body.decode("utf-8"))
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]

        user = self.auth_service.authenticate(username, password)
        if user is None:
            error_html = (
                '<div class="alert alert-danger" role="alert">'
                "Invalid username or password."
                "</div>"
            )
            await self._serve_login_page(send, error=error_html, root_path=root_path)
            return

        # Create session and set cookie
        token = self.auth_service.create_session(user["id"], ttl_hours=self.session_ttl_hours)
        ttl_seconds = self.session_ttl_hours * 3600
        cookie_path = root_path or "/"
        cookie = (
            f"shyfem_session={token}; "
            f"Path={cookie_path}; HttpOnly; SameSite=Lax; Max-Age={ttl_seconds}"
        )
        redirect_to = f"{root_path}/" if root_path else "/"
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    (b"location", redirect_to.encode("utf-8")),
                    (b"set-cookie", cookie.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def _handle_logout(self, session_token, send, root_path: str = ""):
        """Delete the session and redirect to /login with cookie cleared."""
        if session_token:
            self.auth_service.delete_session(session_token)

        cookie_path = root_path or "/"
        cookie = f"shyfem_session=; Path={cookie_path}; HttpOnly; SameSite=Lax; Max-Age=0"
        redirect_to = f"{root_path}/login"
        await send(
            {
                "type": "http.response.start",
                "status": 302,
                "headers": [
                    (b"location", redirect_to.encode("utf-8")),
                    (b"set-cookie", cookie.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    @staticmethod
    async def _redirect(send, location: str, status: int = 302):
        """Send a minimal HTTP redirect."""
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"location", location.encode("utf-8")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})
