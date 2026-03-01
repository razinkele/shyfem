"""Main SHYFEM UI Shiny application."""

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import shutil
import time
from collections import defaultdict
from pathlib import Path

from shiny import App, reactive, render, ui

from shyfem_ui.config import Config, get_config, set_config
from shyfem_ui.db.base import init_db
from shyfem_ui.middleware.session_auth import SessionAuthMiddleware, get_current_user
from shyfem_ui.pages import (
    admin,
    compare,
    ensemble,
    files,
    grid_prep,
    home,
    partitioning,
    postprocess,
    run,
    simulation,
    tutorial,
    visualize,
)
from shyfem_ui.services.auth_service import AuthService
from shyfem_ui.services.job_queue import JobQueue, JobQueueFactory
from shyfem_ui.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

SIDEBAR_GROUPS = [
    {
        "name": "Overview",
        "items": [
            {"label": "Dashboard", "icon": "bi-house", "value": "Dashboard"},
            {"label": "Tutorial", "icon": "bi-mortarboard", "value": "Tutorial"},
        ],
    },
    {
        "name": "Prepare",
        "items": [
            {"label": "Grid Prep", "icon": "bi-grid-3x3", "value": "Grid Prep"},
            {"label": "Partitioning", "icon": "bi-diagram-3", "value": "Partitioning"},
        ],
    },
    {
        "name": "Simulate",
        "items": [
            {"label": "Configuration", "icon": "bi-sliders", "value": "Simulation"},
            {"label": "Run", "icon": "bi-play-circle", "value": "Run"},
        ],
    },
    {
        "name": "Analyze",
        "items": [
            {"label": "Post-Process", "icon": "bi-gear", "value": "Post-Process"},
            {"label": "Visualize", "icon": "bi-graph-up", "value": "Visualize"},
            {"label": "Compare", "icon": "bi-layout-split", "value": "Compare"},
            {"label": "Ensemble", "icon": "bi-collection", "value": "Ensemble"},
        ],
    },
    {
        "name": "Manage",
        "items": [
            {"label": "Files", "icon": "bi-folder", "value": "Files"},
            {"label": "Admin", "icon": "bi-shield-lock", "value": "Admin"},
        ],
    },
]


def _check_db_health() -> float:
    """Probe database with SELECT 1, return response time in ms."""
    from sqlalchemy import text

    from shyfem_ui.db.base import get_engine

    start = time.monotonic()
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return round((time.monotonic() - start) * 1000, 1)


def _bootstrap_tutorial_project(admin_id: int, user_id: int, config: Config) -> None:
    """Seed a shared Mar Menor tutorial project if it doesn't already exist.

    Creates the project directory (via copytree from testcases), DB records
    (Project, Grid, Simulations), and shares with the tutorial user. All steps
    are idempotent.
    """
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Grid, Project, Simulation
    from shyfem_ui.services.sharing_service import SharingService
    from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

    project_name = "Mar Menor Tutorial"

    # Check if project already exists
    with db_session() as db:
        existing = db.query(Project).filter_by(name=project_name).first()
        if existing is not None:
            # Ensure sharing is still in place
            SharingService().share_project(existing.id, user_id, role="editor")
            logger.debug("Tutorial project already exists (id=%d)", existing.id)
            return

    # Copy tutorial files
    mar_menor_src = config.testcases_dir / "mar_menor"
    if not mar_menor_src.is_dir():
        logger.warning("Tutorial source not found: %s — skipping bootstrap", mar_menor_src)
        return

    project_path = config.work_dir / project_name
    if not project_path.exists():
        config.ensure_work_dir()
        try:
            shutil.copytree(mar_menor_src, project_path)
        except Exception:
            logger.exception("Failed to copy tutorial files to %s", project_path)
            return

    # Create DB records
    try:
        with db_session() as db:
            project = Project(
                name=project_name,
                description="Mar Menor tutorial — 6-phase guided introduction to SHYFEM",
                work_dir=str(project_path),
                owner_id=admin_id,
            )
            db.add(project)
            db.flush()

            grid = Grid(
                project_id=project.id,
                name="MM_coarse",
                description="Mar Menor coarse grid",
                grd_file="GRID/MM_coarse.grd",
                bas_file="GRID/MM_coarse.bas",
            )
            db.add(grid)
            db.flush()

            for phase in TUTORIAL_CONTENT:
                for tsim in phase["simulations"]:
                    str_path = project_path / tsim["str_file"]
                    if not str_path.exists():
                        continue
                    sim = Simulation(
                        project_id=project.id,
                        grid_id=grid.id,
                        name=tsim["name"],
                        description=f"{phase['title']}: {tsim['title']}",
                        str_file=tsim["str_file"],
                    )
                    db.add(sim)

            project_id = project.id

        # Share with tutorial user
        SharingService().share_project(project_id, user_id, role="editor")
        logger.info("Bootstrapped tutorial project '%s' (id=%d)", project_name, project_id)

    except Exception:
        logger.exception("Failed to create tutorial project DB records")
        if project_path.exists():
            shutil.rmtree(project_path, ignore_errors=True)


def create_app(config: Config | None = None) -> App:
    """Create and return the Shiny application.

    Args:
        config: Optional configuration object. If not provided, will load from environment.

    Returns:
        Configured Shiny App instance.
    """
    # Initialize configuration
    if config is None:
        config = get_config()
    else:
        set_config(config)

    # Ensure work directory exists
    config.ensure_work_dir()

    # Initialize database
    init_db()

    # Register Plotly theme
    from shyfem_ui.plotly_theme import register_shyfem_template
    register_shyfem_template(dark=False)

    # Initialize auth service and ensure default admin exists
    auth_service = AuthService()
    if config.deployment_mode == "server":
        if config.default_admin_password:
            admin = auth_service.ensure_admin(
                config.default_admin_username, config.default_admin_password
            )
        elif config.auth_enabled and config.auth_password:
            # Backward compat: migrate from basic auth config
            admin = auth_service.ensure_admin(config.auth_username, config.auth_password)
        else:
            admin = None

        # Bootstrap default tutorial user + shared project
        if admin and config.default_user_password:
            tutorial_user = auth_service.ensure_user(
                config.default_user_username, config.default_user_password
            )
            _bootstrap_tutorial_project(admin["id"], tutorial_user["id"], config)

    # Initialize job queue
    queue_mode = "celery" if config.use_celery else "local"
    job_queue = JobQueueFactory.create(
        mode=queue_mode,
        shyfem_dir=config.shyfem_dir,
        max_workers=config.max_workers,
        redis_url=config.redis_url if config.use_celery else None,
    )

    # Build UI
    app_ui = _build_ui(config)

    # Build server
    def server(input, output, session):
        _build_server(input, output, session, config, job_queue, auth_service)

    app = App(app_ui, server, static_assets=Path(__file__).parent / "www")

    # Cache headers for static assets
    if config.static_cache_max_age > 0:
        app = CacheHeaderMiddleware(app, max_age=config.static_cache_max_age)

    # Session-based auth (replaces basic auth)
    is_local = config.deployment_mode == "local"
    app = SessionAuthMiddleware(
        app,
        auth_service=auth_service,
        local_mode=is_local,
        session_ttl_hours=config.auth_session_ttl_hours,
        root_path=config.root_path,
    )
    if not is_local and not config.default_admin_password and not config.auth_password:
        logger.warning(
            "Running in server mode without authentication credentials. "
            "Set SHYFEM_UI_DEFAULT_ADMIN_PASSWORD to enable user login."
        )

    # Rate limiting (server mode only)
    if config.deployment_mode == "server" and config.rate_limit_rpm > 0:
        app = RateLimitMiddleware(
            app, rpm=config.rate_limit_rpm, trusted_proxies=config.trusted_proxies
        )

    # Request ID correlation (middleware + logging filter)
    from shyfem_ui.middleware.request_id import RequestIdFilter, RequestIdMiddleware

    app = RequestIdMiddleware(app)
    root_logger = logging.getLogger()
    if not any(isinstance(f, RequestIdFilter) for f in root_logger.filters):
        root_logger.addFilter(RequestIdFilter())

    # Health check endpoint (outermost — bypasses auth and rate limiting)
    app = HealthCheckMiddleware(app, db_check=_check_db_health, job_queue=job_queue)

    return app


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


def get_client_ip(scope: dict, trusted_proxies: list[str]) -> str:
    """Extract real client IP, respecting trusted proxy X-Forwarded-For.

    Uses the rightmost-untrusted algorithm: walk X-Forwarded-For from right
    to left, skipping IPs that match a trusted CIDR, and return the first
    untrusted IP. If all are trusted, return the leftmost.

    Args:
        scope: ASGI scope dict (needs 'client' and 'headers').
        trusted_proxies: List of CIDR strings (e.g., ["127.0.0.0/8"]).

    Returns:
        Client IP string.
    """
    client = scope.get("client")
    raw_ip = client[0] if client else "unknown"

    if not trusted_proxies:
        return raw_ip

    # Parse trusted networks
    try:
        networks = [ipaddress.ip_network(cidr, strict=False) for cidr in trusted_proxies]
    except ValueError:
        return raw_ip

    # Check if the direct client is a trusted proxy
    try:
        client_addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        return raw_ip

    if not any(client_addr in net for net in networks):
        return raw_ip

    # Client is trusted — parse X-Forwarded-For
    xff = None
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"x-forwarded-for":
            xff = header_value.decode("latin-1")
            break

    if not xff:
        return raw_ip

    # Walk right-to-left, find rightmost non-trusted IP
    ips = [ip.strip() for ip in xff.split(",") if ip.strip()]
    if not ips:
        return raw_ip

    for ip_str in reversed(ips):
        try:
            addr = ipaddress.ip_address(ip_str)
            if not any(addr in net for net in networks):
                return ip_str
        except ValueError:
            continue

    # All trusted — return leftmost
    return ips[0]


class RateLimitMiddleware:
    """ASGI middleware that enforces per-client request rate limits."""

    def __init__(
        self,
        app,
        rpm: int = 120,
        trusted_proxies: list[str] | None = None,
        max_clients: int = 10000,
    ):
        self.app = app
        self.rpm = rpm
        self.trusted_proxies = trusted_proxies or []
        self._window = 60.0  # 1 minute sliding window
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._max_clients = max_clients

    def _prune_clients(self, now: float):
        """Evict stale client entries when dict exceeds max_clients."""
        if len(self._requests) <= self._max_clients:
            return
        cutoff = now - self._window
        # First pass: remove clients with no recent timestamps
        stale = [k for k, v in self._requests.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._requests[k]
        if len(self._requests) <= self._max_clients:
            return
        # Second pass: evict least-recently-active (oldest max timestamp)
        by_recency = sorted(self._requests.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
        to_remove = len(self._requests) - self._max_clients
        for k, _ in by_recency[:to_remove]:
            del self._requests[k]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        client_key = get_client_ip(scope, self.trusted_proxies)
        now = time.monotonic()

        self._prune_clients(now)

        # Prune old entries outside the window
        timestamps = self._requests[client_key]
        cutoff = now - self._window
        self._requests[client_key] = [t for t in timestamps if t > cutoff]
        timestamps = self._requests[client_key]

        if len(timestamps) >= self.rpm:
            body = b"Rate limit exceeded. Try again later."
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        [b"content-type", b"text/plain"],
                        [b"content-length", str(len(body)).encode()],
                        [b"retry-after", b"60"],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        timestamps.append(now)
        return await self.app(scope, receive, send)


_STATIC_EXTENSIONS = frozenset(
    {
        ".css",
        ".js",
        ".woff2",
        ".woff",
        ".ttf",
        ".png",
        ".svg",
        ".ico",
    }
)


class CacheHeaderMiddleware:
    """ASGI middleware that adds Cache-Control headers to static asset responses."""

    def __init__(self, app, max_age: int = 86400):
        self.app = app
        self.max_age = max_age

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.max_age <= 0:
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        dot = path.rfind(".")
        ext = path[dot:].lower() if dot != -1 else ""

        if ext not in _STATIC_EXTENSIONS:
            return await self.app(scope, receive, send)

        cache_value = f"public, max-age={self.max_age}".encode()

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"cache-control", cache_value])
                message = {**message, "headers": headers}
            result = send(message)
            if result is not None:
                await result

        return await self.app(scope, receive, send_with_cache)


class HealthCheckMiddleware:
    """ASGI middleware that serves a /health JSON endpoint.

    Placed as the outermost middleware so it bypasses auth and rate limiting.
    """

    def __init__(self, app, db_check=None, job_queue=None):
        self.app = app
        self._start_time = time.monotonic()
        self._db_check = db_check
        self._job_queue = job_queue

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if scope.get("path") != "/health" or scope["method"] != "GET":
            return await self.app(scope, receive, send)

        from shyfem_ui import __version__

        # Probe database
        db_ok = True
        db_response_time_ms = -1.0
        try:
            if self._db_check:
                result = self._db_check()
                if isinstance(result, (int, float)):
                    db_response_time_ms = result
        except Exception:
            db_ok = False

        # Probe job queue (active_jobs and queue_depth are the same value)
        active_jobs = -1
        queue_ok = True
        try:
            val = getattr(self._job_queue, "active_job_count", -1)
            active_jobs = val() if callable(val) else val
        except Exception:
            active_jobs = -1
            queue_ok = False
        queue_depth = active_jobs

        worker_count = -1
        try:
            wc = getattr(self._job_queue, "max_workers", -1)
            worker_count = wc() if callable(wc) else wc
        except Exception:
            worker_count = -1

        status = "ok" if db_ok and queue_ok else "degraded"

        payload = {
            "status": status,
            "version": __version__,
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "database": "ok" if db_ok else "error",
            "db_response_time_ms": db_response_time_ms,
            "active_jobs": active_jobs,
            "queue_depth": queue_depth,
            "worker_count": worker_count,
        }

        body = json.dumps(payload).encode()
        result = send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"content-length", str(len(body)).encode()],
                ],
            }
        )
        if result is not None:
            await result
        result = send({"type": "http.response.body", "body": body})
        if result is not None:
            await result


def _build_sidebar_nav() -> ui.Tag:
    """Build the sidebar navigation HTML."""
    nav_items = []
    for group in SIDEBAR_GROUPS:
        nav_items.append(
            ui.div(
                ui.span(group["name"], class_="sf-nav-group-header"),
            )
        )
        for item in group["items"]:
            active_class = " active" if item["value"] == "Dashboard" else ""
            nav_items.append(
                ui.div(
                    ui.tags.i(class_=f"bi {item['icon']} sf-nav-icon"),
                    ui.span(item["label"], class_="sf-nav-label"),
                    class_=f"sf-nav-item{active_class}",
                    data_nav=item["value"],
                    onclick=f"shyfemNavTo('{item['value']}')",
                )
            )

    return ui.div(
        ui.div(*nav_items, class_="sf-nav-items"),
        ui.div(
            ui.tags.i(class_="bi bi-chevron-bar-left sf-nav-icon"),
            ui.span("Collapse", class_="sf-nav-label"),
            class_="sf-nav-item sf-collapse-btn",
            onclick="shyfemToggleSidebar()",
        ),
        class_="sf-sidebar",
        id="sf-sidebar",
    )


_HEAD_EXTRAS = ui.TagList(
    # NOTE: Bootstrap 5 CSS/JS is NOT loaded here — page_fillable() already injects it.
    # Bootstrap Icons
    ui.tags.link(
        rel="stylesheet",
        href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ),
    # Google Fonts (Inter + JetBrains Mono)
    ui.tags.link(
        rel="stylesheet",
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap",
    ),
    # Custom design system CSS
    ui.tags.link(rel="stylesheet", href="css/shyfem.css"),
    # WebSocket reconnection with exponential backoff
    ui.tags.script("""
(function() {
  var maxRetries = 5, retryDelay = 2000;
  var origWS = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    var ws = protocols ? new origWS(url, protocols) : new origWS(url);
    var retries = 0;
    ws.addEventListener('close', function(e) {
      if (e.code !== 1000 && e.code !== 1001 && retries < maxRetries) {
        retries++;
        var delay = retryDelay * retries;
        console.log('[SHYFEM] WebSocket closed (' + e.code + '), reconnecting in ' + delay + 'ms...');
        setTimeout(function() { window.location.reload(); }, delay);
      }
    });
    return ws;
  };
  window.WebSocket.prototype = origWS.prototype;
})();
"""),
    # Dark mode, sidebar, and navigation handler
    ui.tags.script("""
document.addEventListener('DOMContentLoaded', function() {
  // Dark mode init
  var saved = localStorage.getItem('shyfem-dark-mode');
  if (saved === 'true') {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
    var btn = document.getElementById('dark-mode-toggle');
    if (btn) { var icon = btn.querySelector('i'); if (icon) icon.className = 'bi bi-sun'; }
  }
  // Sidebar collapse init
  var collapsed = localStorage.getItem('shyfem-sidebar-collapsed');
  if (collapsed === 'true') {
    var sb = document.getElementById('sf-sidebar');
    if (sb) sb.classList.add('sf-sidebar-collapsed');
  }
});

function shyfemToggleDark() {
  var html = document.documentElement;
  var isDark = html.getAttribute('data-bs-theme') === 'dark';
  html.setAttribute('data-bs-theme', isDark ? 'light' : 'dark');
  localStorage.setItem('shyfem-dark-mode', String(!isDark));
  var btn = document.getElementById('dark-mode-toggle');
  if (btn) {
    var icon = btn.querySelector('i');
    if (icon) icon.className = isDark ? 'bi bi-moon' : 'bi bi-sun';
  }
  if (window.Shiny && Shiny.setInputValue) {
    Shiny.setInputValue('_dark_mode', !isDark);
  }
}

function shyfemNavTo(name) {
  // Update active sidebar item
  document.querySelectorAll('.sf-nav-item').forEach(function(el) {
    el.classList.remove('active');
  });
  var clicked = document.querySelector('.sf-nav-item[data-nav="' + name + '"]');
  if (clicked) clicked.classList.add('active');

  // Show/hide pages (IDs use hyphens instead of spaces)
  document.querySelectorAll('.sf-page').forEach(function(el) {
    el.classList.remove('active');
  });
  var pageId = 'sf-page-' + name.replace(/ /g, '-');
  var page = document.getElementById(pageId);
  if (page) {
    page.classList.add('active');
    page.classList.add('sf-page-enter');
    setTimeout(function() { page.classList.remove('sf-page-enter'); }, 250);
  }

  // Notify Shiny
  if (window.Shiny && Shiny.setInputValue) {
    Shiny.setInputValue('_active_nav', name, {priority: 'event'});
  }

  // Auto-close sidebar on mobile after navigation
  if (window.innerWidth <= 768) { shyfemCloseMobile(); }
}

function shyfemToggleSidebar() {
  var sb = document.getElementById('sf-sidebar');
  if (!sb) return;
  sb.classList.toggle('sf-sidebar-collapsed');
  var isCollapsed = sb.classList.contains('sf-sidebar-collapsed');
  localStorage.setItem('shyfem-sidebar-collapsed', String(isCollapsed));
  var icon = sb.querySelector('.sf-collapse-btn i');
  if (icon) {
    icon.className = isCollapsed ? 'bi bi-chevron-bar-right sf-nav-icon' : 'bi bi-chevron-bar-left sf-nav-icon';
  }
}

function shyfemToggleMobile() {
  var sb = document.getElementById('sf-sidebar');
  var bd = document.getElementById('sf-sidebar-backdrop');
  if (!sb) return;
  var isOpen = sb.classList.contains('sf-sidebar-open');
  sb.classList.toggle('sf-sidebar-open', !isOpen);
  if (bd) bd.classList.toggle('active', !isOpen);
}

function shyfemCloseMobile() {
  var sb = document.getElementById('sf-sidebar');
  var bd = document.getElementById('sf-sidebar-backdrop');
  if (sb) sb.classList.remove('sf-sidebar-open');
  if (bd) bd.classList.remove('active');
}

// Server-initiated navigation
$(document).on('shiny:connected', function() {
  Shiny.addCustomMessageHandler('shyfem_nav', function(msg) {
    shyfemNavTo(msg.tab);
  });
});
"""),
    # Meta tags
    ui.tags.meta(
        name="description",
        content="SHYFEM Workbench — finite element hydrodynamic simulation interface",
    ),
    ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1"),
    # Inline SVG favicon (water wave icon)
    ui.tags.link(
        rel="icon",
        type="image/svg+xml",
        href="data:image/svg+xml,"
        "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
        "%3Ctext y='28' font-size='28'%3E%F0%9F%8C%8A%3C/text%3E%3C/svg%3E",
    ),
)


def _build_ui(config: Config) -> ui.Tag:
    """Build the application UI with sidebar navigation."""
    sidebar = _build_sidebar_nav()

    # Top bar
    topbar = ui.div(
        ui.div(
            ui.tags.button(
                ui.tags.i(class_="bi bi-list"),
                class_="sf-hamburger me-2",
                onclick="shyfemToggleMobile()",
                title="Toggle navigation",
                **{"aria-label": "Toggle navigation"},
            ),
            ui.tags.i(class_="bi bi-tsunami me-2", style="font-size:1.3rem"),
            ui.span("SHYFEM Workbench", style="font-weight:600;font-size:1rem"),
            class_="d-flex align-items-center",
        ),
        ui.div(
            ui.tags.button(
                ui.tags.i(class_="bi bi-moon"),
                id="dark-mode-toggle",
                class_="btn btn-sm sf-topbar-btn me-2",
                onclick="shyfemToggleDark()",
                title="Toggle dark mode",
            ),
            ui.span(
                ui.tags.i(class_="bi bi-person-circle me-1"),
                ui.output_text("_current_username", inline=True),
                class_="me-3",
                style="color:rgba(255,255,255,0.75);font-size:0.85rem;",
            ),
            ui.tags.a(
                ui.tags.i(class_="bi bi-box-arrow-right me-1"),
                "Logout",
                href=f"{config.root_path}/logout",
                class_="btn btn-sm sf-topbar-btn",
                id="logout-btn",
            ),
            class_="d-flex align-items-center",
        ),
        class_="sf-topbar",
    )

    # Content panels -- one div per page, toggled by CSS
    content_panels = ui.div(
        ui.div(home.home_ui("home"), id="sf-page-Dashboard", class_="sf-page active"),
        ui.div(tutorial.tutorial_ui("tutorial"), id="sf-page-Tutorial", class_="sf-page"),
        ui.div(grid_prep.grid_prep_ui("grid_prep"), id="sf-page-Grid-Prep", class_="sf-page"),
        ui.div(
            partitioning.partitioning_ui("partitioning"),
            id="sf-page-Partitioning",
            class_="sf-page",
        ),
        ui.div(
            simulation.simulation_ui("simulation"), id="sf-page-Simulation", class_="sf-page"
        ),
        ui.div(run.run_ui("run"), id="sf-page-Run", class_="sf-page"),
        ui.div(
            postprocess.postprocess_ui("postprocess"),
            id="sf-page-Post-Process",
            class_="sf-page",
        ),
        ui.div(
            visualize.visualize_ui("visualize"), id="sf-page-Visualize", class_="sf-page"
        ),
        ui.div(compare.compare_ui("compare"), id="sf-page-Compare", class_="sf-page"),
        ui.div(ensemble.ensemble_ui("ensemble"), id="sf-page-Ensemble", class_="sf-page"),
        ui.div(files.files_ui("files"), id="sf-page-Files", class_="sf-page"),
        ui.div(admin.admin_ui("admin"), id="sf-page-Admin", class_="sf-page"),
        class_="sf-content",
    )

    return ui.page_fillable(
        ui.head_content(_HEAD_EXTRAS),
        ui.busy_indicators.use(spinners=True, pulse=True),
        topbar,
        ui.div(
            sidebar,
            content_panels,
            class_="sf-layout",
        ),
        ui.div(class_="sf-sidebar-backdrop", id="sf-sidebar-backdrop", onclick="shyfemCloseMobile()"),
        title="SHYFEM Workbench",
    )


def _build_server(
    input,
    output,
    session,
    config: Config,
    job_queue: JobQueue,
    auth_service: AuthService | None = None,
):
    """Build the application server logic."""
    active_project = reactive.value(None)
    tutorial_context = reactive.value(None)

    def nav_to(tab_name: str):
        """Navigate to a tab via client-side JavaScript."""
        session.send_custom_message("shyfem_nav", {"tab": tab_name})

    # Cancel orphaned running jobs when the browser session disconnects
    _cleanup_session_id = str(id(session))
    _is_server = config.deployment_mode == "server"
    _current_user = get_current_user()
    _user_id = _current_user["id"] if _current_user else None

    @render.text
    def _current_username():
        if _current_user:
            return _current_user.get("display_name") or _current_user.get("username", "")
        return ""

    async def _on_session_ended():
        try:
            sid = _cleanup_session_id if _is_server else None
            jobs = await job_queue.list_jobs(limit=100, session_id=sid)
            for job in jobs:
                if job.is_active:
                    logger.info("Session ended — cancelling orphaned job %s", job.id)
                    await job_queue.cancel(job.id)
        except Exception as exc:
            logger.warning("Session cleanup failed: %s", exc)

    session.on_ended(_on_session_ended)

    @reactive.effect
    @reactive.event(input._dark_mode)
    def _update_plotly_theme():
        from shyfem_ui.plotly_theme import register_shyfem_template
        is_dark = input._dark_mode()
        register_shyfem_template(dark=bool(is_dark))

    # Initialize page servers
    home.home_server("home", config, job_queue, active_project=active_project, nav_callback=nav_to)
    tutorial.tutorial_server(
        "tutorial",
        config,
        active_project=active_project,
        nav_callback=nav_to,
        tutorial_context=tutorial_context,
    )
    grid_prep.grid_prep_server(
        "grid_prep", config, active_project=active_project, tutorial_context=tutorial_context
    )
    partitioning.partitioning_server("partitioning", config, active_project=active_project)
    simulation.simulation_server(
        "simulation", config, active_project=active_project, tutorial_context=tutorial_context
    )
    run.run_server(
        "run", config, job_queue, active_project=active_project, tutorial_context=tutorial_context
    )
    postprocess.postprocess_server(
        "postprocess", config, active_project=active_project, tutorial_context=tutorial_context
    )
    visualize.visualize_server(
        "visualize", config, active_project=active_project, tutorial_context=tutorial_context
    )
    compare.compare_server("compare", config, job_queue, active_project=active_project)
    ensemble.ensemble_server("ensemble", config, job_queue, active_project=active_project)
    files.files_server("files", config, active_project=active_project)

    if auth_service:
        admin.admin_server("admin", config, auth_service)

    # --- Cross-page job notifications ---
    _notification_svc = NotificationService()

    @reactive.effect
    def _poll_job_notifications():
        reactive.invalidate_later(5)  # Poll every 5 seconds

        import asyncio

        async def _check():
            sid = _cleanup_session_id if _is_server else None
            jobs = await job_queue.list_jobs(limit=100, session_id=sid)
            job_dicts = [{"id": j.id, "name": j.name, "status": j.status.value} for j in jobs]
            events = _notification_svc.check_transitions(job_dicts)
            for event in events:
                status = event["new_status"]
                name = event["job_name"]
                if status == "completed":
                    ui.notification_show(
                        f"Job '{name}' completed successfully.",
                        type="message",
                        duration=8,
                    )
                elif status == "failed":
                    ui.notification_show(
                        f"Job '{name}' failed.",
                        type="error",
                        duration=10,
                    )
                elif status == "cancelled":
                    ui.notification_show(
                        f"Job '{name}' was cancelled.",
                        type="warning",
                        duration=5,
                    )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_check())
            else:
                asyncio.run(_check())
        except Exception:
            logger.debug("Notification poll error", exc_info=True)


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description="SHYFEM Web Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  shyfem-ui                          # Start with default settings
  shyfem-ui --port 8080              # Start on port 8080
  shyfem-ui --host 0.0.0.0           # Listen on all interfaces
  shyfem-ui --shyfem-dir /path/to    # Specify SHYFEM directory

Environment variables (can be used instead of arguments):
  SHYFEM_UI_HOST              Host to bind to
  SHYFEM_UI_PORT              Port to bind to
  SHYFEM_UI_SHYFEM_DIR        SHYFEM installation directory
  SHYFEM_UI_DEPLOYMENT_MODE   'local' or 'server'
  SHYFEM_UI_USE_CELERY        'true' for Celery job queue (server mode)
  SHYFEM_UI_DATABASE_URL      Database URL (default: sqlite)
  SHYFEM_UI_ROOT_PATH         Root path for reverse proxy (e.g., '/shyfem-ui')
        """,
    )

    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (default: 127.0.0.1 for local, 0.0.0.0 for server)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: 8000)",
    )
    parser.add_argument(
        "--shyfem-dir",
        type=Path,
        default=None,
        help="SHYFEM installation directory",
    )
    parser.add_argument(
        "--mode",
        choices=["local", "server"],
        default=None,
        help="Deployment mode",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of job queue workers",
    )

    args = parser.parse_args()

    # Load base config from environment
    config = Config()

    # Override with command line arguments
    if args.shyfem_dir:
        config.shyfem_dir = args.shyfem_dir
    if args.mode:
        config.deployment_mode = args.mode
    if args.workers:
        config.max_workers = args.workers

    # Determine host/port
    host = args.host or config.host
    if host is None:
        host = "0.0.0.0" if config.deployment_mode == "server" else "127.0.0.1"

    port = args.port or config.port

    # Create and run app (RequestIdFilter already added in create_app())
    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format="%(asctime)s [%(name)s] [%(request_id)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger.info("Starting SHYFEM Workbench...")
    logger.info("  Mode: %s", config.deployment_mode)
    logger.info("  SHYFEM Dir: %s", config.shyfem_dir)
    logger.info("  Work Dir: %s", config.work_dir)
    logger.info("  URL: http://%s:%s", host, port)

    app = create_app(config)

    # Run with Shiny's built-in server
    from shiny import run_app

    run_kwargs = dict(host=host, port=port, reload=args.reload)
    if config.root_path:
        run_kwargs["root_path"] = config.root_path
        logger.info("  Root Path: %s", config.root_path)
    run_app(app, **run_kwargs)


if __name__ == "__main__":
    main()
