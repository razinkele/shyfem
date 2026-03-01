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
  <title>SHYFEM Workbench</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"
        rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'Inter', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #0B3D5B 0%, #1A6B8A 50%, #2D9CBA 100%);
      background-size: 400% 400%;
      animation: gradientShift 15s ease infinite;
    }}

    @keyframes gradientShift {{
      0%   {{ background-position: 0% 50%; }}
      50%  {{ background-position: 100% 50%; }}
      100% {{ background-position: 0% 50%; }}
    }}

    .login-card {{
      max-width: 440px;
      width: 95%;
      background: rgba(255, 255, 255, 0.12);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 16px;
      padding: 40px 36px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
      animation: cardEntrance 600ms ease-out both;
    }}

    @keyframes cardEntrance {{
      from {{
        opacity: 0;
        transform: translateY(30px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}

    .brand {{
      text-align: center;
      margin-bottom: 8px;
    }}

    .brand svg {{
      width: 48px;
      height: 48px;
      margin-bottom: 12px;
    }}

    .brand h1 {{
      font-size: 1.6rem;
      font-weight: 700;
      color: #fff;
      margin: 0;
      letter-spacing: -0.02em;
    }}

    .brand .tagline {{
      font-size: 0.85rem;
      color: rgba(255, 255, 255, 0.7);
      margin-top: 4px;
      font-weight: 400;
    }}

    .info {{
      background: rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      padding: 14px 18px;
      margin: 20px 0 28px;
      animation: cardEntrance 600ms ease-out 100ms both;
    }}

    .info ul {{
      list-style: none;
      padding: 0;
      margin: 0;
    }}

    .info li {{
      font-size: 0.82rem;
      color: rgba(255, 255, 255, 0.8);
      padding: 3px 0;
    }}

    .info li::before {{
      margin-right: 8px;
      opacity: 0.7;
    }}

    .form-group {{
      margin-bottom: 18px;
      animation: cardEntrance 500ms ease-out both;
    }}

    .form-group:nth-child(1) {{ animation-delay: 150ms; }}
    .form-group:nth-child(2) {{ animation-delay: 250ms; }}
    .form-group.btn-group       {{ animation-delay: 350ms; }}

    label {{
      display: block;
      font-size: 0.8rem;
      font-weight: 500;
      color: rgba(255, 255, 255, 0.85);
      margin-bottom: 6px;
      letter-spacing: 0.01em;
    }}

    input[type="text"],
    input[type="password"] {{
      width: 100%;
      padding: 10px 14px;
      font-size: 0.95rem;
      font-family: inherit;
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 8px;
      color: #fff;
      outline: none;
      transition: box-shadow 200ms ease, border-color 200ms ease;
    }}

    input[type="text"]::placeholder,
    input[type="password"]::placeholder {{
      color: rgba(255, 255, 255, 0.4);
    }}

    input[type="text"]:focus,
    input[type="password"]:focus {{
      border-color: #2D9CBA;
      box-shadow: 0 0 0 3px rgba(45, 156, 186, 0.35);
    }}

    .btn-signin {{
      width: 100%;
      padding: 11px;
      font-size: 0.95rem;
      font-weight: 600;
      font-family: inherit;
      color: #fff;
      background: linear-gradient(135deg, #1A6B8A, #2D9CBA);
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: transform 150ms ease, filter 150ms ease;
      letter-spacing: 0.01em;
    }}

    .btn-signin:hover {{
      transform: scale(1.02);
      filter: brightness(1.1);
    }}

    .btn-signin:active {{
      transform: scale(0.99);
    }}

    .error-alert {{
      background: rgba(220, 53, 69, 0.2);
      border: 1px solid rgba(220, 53, 69, 0.5);
      border-radius: 8px;
      color: #ffc9cf;
      padding: 10px 14px;
      font-size: 0.85rem;
      margin-bottom: 18px;
      animation: shake 400ms ease;
    }}

    @keyframes shake {{
      0%, 100% {{ transform: translateX(0); }}
      20%      {{ transform: translateX(-6px); }}
      40%      {{ transform: translateX(6px); }}
      60%      {{ transform: translateX(-4px); }}
      80%      {{ transform: translateX(4px); }}
    }}

    .footer {{
      text-align: center;
      margin-top: 24px;
      font-size: 0.7rem;
      color: rgba(255, 255, 255, 0.4);
      letter-spacing: 0.02em;
    }}

    @media (max-width: 480px) {{
      .login-card {{
        padding: 28px 22px;
      }}
      .brand h1 {{
        font-size: 1.35rem;
      }}
    }}
  </style>
</head>
<body>
  <div class="login-card">
    <div class="brand">
      <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M4 28c4-4 8-6 12-2s8 2 12-2 8-6 12-2" stroke="rgba(255,255,255,0.9)"
              stroke-width="2.5" stroke-linecap="round" fill="none"/>
        <path d="M4 34c4-4 8-6 12-2s8 2 12-2 8-6 12-2" stroke="rgba(255,255,255,0.5)"
              stroke-width="2" stroke-linecap="round" fill="none"/>
        <path d="M4 22c4-4 8-6 12-2s8 2 12-2 8-6 12-2" stroke="rgba(255,255,255,0.3)"
              stroke-width="1.5" stroke-linecap="round" fill="none"/>
      </svg>
      <h1>SHYFEM Workbench</h1>
      <div class="tagline">Finite element hydrodynamic simulation platform</div>
    </div>

    <div class="info">
      <ul>
        <li>\u2248 Lagoons, coastal seas &amp; estuaries</li>
        <li>\u2248 2D/3D modeling with MPI parallelization</li>
        <li>\u2248 Wind, tidal, baroclinic &amp; transport physics</li>
      </ul>
    </div>

    {error}

    <form method="post" action="{login_action}">
      <div class="form-group">
        <label for="username">Username</label>
        <input type="text" id="username" name="username" required autofocus
               placeholder="Enter your username">
      </div>
      <div class="form-group">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" required
               placeholder="Enter your password">
      </div>
      <div class="form-group btn-group">
        <button type="submit" class="btn-signin">Sign In</button>
      </div>
    </form>

    <div class="footer">System of HydroDYnamic Finite Element Modules</div>
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
                '<div class="error-alert" role="alert">'
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
