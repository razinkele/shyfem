"""Main SHYFEM UI Shiny application."""

import argparse
import asyncio
import logging
import shutil
import time
from pathlib import Path

from shiny import App, reactive, render, ui

from shyfem_ui.config import Config, get_config, set_config
from shyfem_ui.db.base import init_db
from shyfem_ui.middleware.cache_headers import CacheHeaderMiddleware
from shyfem_ui.middleware.health_check import HealthCheckMiddleware
from shyfem_ui.middleware.rate_limit import RateLimitMiddleware
from shyfem_ui.middleware.session_auth import SessionAuthMiddleware, get_current_user
from shyfem_ui.pages import (
    about,
    admin,
    boxmodel,
    compare,
    ensemble,
    files,
    grid_prep,
    home,
    ibm,
    mesh_builder,
    partitioning,
    physics,
    postprocess,
    run,
    simulation,
    tutorial,
    visualize,
)

try:
    from shiny_deckgl import head_includes as deckgl_head_includes
except ImportError:
    deckgl_head_includes = None

from shyfem_ui.services.audit_service import AuditService
from shyfem_ui.services.auth_service import AuthService
from shyfem_ui.services.feedback_service import FeedbackService
from shyfem_ui.services.job_queue import JobQueue, JobQueueFactory
from shyfem_ui.services.notification_service import JobTransitionDetector
from shyfem_ui.services.notification_service import NotificationService as EmailNotificationService
from shyfem_ui.services.run_logic import list_scoped_jobs

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
            {"label": "Mesh Builder", "icon": "bi-pencil-square", "value": "Mesh Builder"},
            {"label": "Grid Prep", "icon": "bi-grid-3x3", "value": "Grid Prep"},
            {"label": "Partitioning", "icon": "bi-diagram-3", "value": "Partitioning"},
            {"label": "Physics Config", "icon": "bi-cpu", "value": "Physics"},
        ],
    },
    {
        "name": "Simulate",
        "items": [
            {"label": "Configuration", "icon": "bi-sliders", "value": "Simulation"},
            {"label": "Run", "icon": "bi-play-circle", "value": "Run"},
            {"label": "IBM", "icon": "bi-wind", "value": "IBM"},
        ],
    },
    {
        "name": "Analyze",
        "items": [
            {"label": "Post-Process", "icon": "bi-gear", "value": "Post-Process"},
            {"label": "Visualize", "icon": "bi-graph-up", "value": "Visualize"},
            {"label": "Compare", "icon": "bi-layout-split", "value": "Compare"},
            {"label": "Box model", "icon": "bi-grid-3x3-gap", "value": "Box-model"},
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


# Pages accessible to tutorial (read-only demo) accounts
_TUTORIAL_ALLOWED_PAGES = {"Tutorial"}


def _filter_sidebar_for_role(groups: list[dict], role: str) -> list[dict]:
    """Return a filtered copy of SIDEBAR_GROUPS for the given user role.

    - "admin"    — all pages
    - "user"     — all pages except Admin
    - "tutorial" — Tutorial page only
    """
    _hidden = {
        "user": {"Admin"},
        "tutorial": {
            item["value"]
            for group in groups
            for item in group["items"]
            if item["value"] not in _TUTORIAL_ALLOWED_PAGES
        },
    }.get(role, set())

    filtered = []
    for group in groups:
        items = [i for i in group["items"] if i["value"] not in _hidden]
        if items:
            filtered.append({**group, "items": items})
    return filtered


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


#: Format shared by both logging paths. ``request_id`` is supplied by
#: ``RequestIdFilter``, which must sit on the HANDLER: a filter attached to a
#: logger only sees records logged directly to it, never records propagated up
#: from child loggers, so every ``shyfem_ui.*`` record would fail to format.
LOG_FORMAT = "%(asctime)s [%(name)s] [%(request_id)s] %(levelname)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def configure_logging(config: Config) -> logging.Logger:
    """Configure the ``shyfem_ui`` package logger. Idempotent.

    Called from ``create_app``, because that is the only entry point BOTH
    deployments share: Shiny Server imports the top-level ``app.py`` and calls
    ``create_app()``, so ``main()`` never runs in production and the
    ``logging.basicConfig`` there configured nothing. Unconfigured, Python's
    last-resort handler still passed WARNING and above to stderr, but every
    INFO breadcrumb this package writes -- cache reconciles, project opens,
    build starts -- was dropped, which is exactly what you want when reading a
    worker log to find out what a session did.

    Configures the package logger rather than the root, so third-party
    chatter is not swept in with it. Propagation stays ON: under Shiny Server
    the root has no handler, so a record is emitted exactly once, and leaving
    it on is what lets pytest's ``caplog`` (a root handler) see these loggers
    at all -- turning it off here silently blinded ten existing tests and
    would have done the same to every future one. The CLI path, which DOES
    configure the root, opts out instead: see ``configure_cli_logging``.
    """
    from shyfem_ui.middleware.request_id import RequestIdFilter

    logger_ = logging.getLogger("shyfem_ui")
    logger_.setLevel(logging.DEBUG if config.debug else config.log_level)
    if not logger_.handlers:
        handler = logging.StreamHandler()  # stderr -> the Shiny Server worker log
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
        handler.addFilter(RequestIdFilter())
        logger_.addHandler(handler)
    return logger_


def configure_cli_logging(config: Config) -> None:
    """Configure the ROOT logger for ``python -m shyfem_ui.app``.

    ``create_app`` has already configured the package logger, so this exists
    for everything else the CLI should show -- uvicorn and friends. Because
    the root now has a handler of its own, the package logger stops
    propagating here, and only here: that is where a record would otherwise be
    written twice.

    The root handler needs ``RequestIdFilter`` as well, or ``%(request_id)s``
    in the shared format raises for every record that did not come from a
    request. ``basicConfig`` installs no filters of its own.
    """
    from shyfem_ui.middleware.request_id import RequestIdFilter

    logging.basicConfig(
        level=logging.DEBUG if config.debug else logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATEFMT,
    )
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())
    logging.getLogger("shyfem_ui").propagate = False


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

    # Before anything that logs: under Shiny Server this is the ONLY place
    # logging is ever configured (see configure_logging).
    configure_logging(config)

    # Ensure work directory exists
    config.ensure_work_dir()

    # Initialize database
    init_db()

    # Register Plotly theme
    from shyfem_ui.plotly_theme import register_shyfem_template

    register_shyfem_template(dark=False)

    # Initialize auth + audit + feedback services
    auth_service = AuthService()
    audit_service = AuditService()
    feedback_service = FeedbackService()
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
                config.default_user_username, config.default_user_password, role="tutorial"
            )
            _bootstrap_tutorial_project(admin["id"], tutorial_user["id"], config)

    # Initialize job queue
    queue_mode = "celery" if config.use_celery else "local"
    notification_svc = EmailNotificationService(config)
    job_queue = JobQueueFactory.create(
        mode=queue_mode,
        shyfem_dir=config.shyfem_dir,
        max_workers=config.max_workers,
        redis_url=config.redis_url if config.use_celery else None,
        notification_service=notification_svc,
    )

    # Build UI
    app_ui = _build_ui(config)

    # Build server
    def server(input, output, session):
        _build_server(input, output, session, config, job_queue, auth_service, audit_service)

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
        use_secure_cookies=config.use_secure_cookies,
        audit_service=audit_service,
        trusted_proxies=config.trusted_proxies,
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

    # Periodic maintenance (server mode): prune old jobs + expired sessions/tokens.
    # Launched on ASGI lifespan startup; without this the cleanups never run and
    # the jobs/auth_sessions/ws_auth_tokens tables grow unbounded. Wrapped INSIDE
    # the health-check layer (which forwards lifespan), so HealthCheck stays
    # outermost for monitoring.
    from shyfem_ui.middleware.maintenance import MaintenanceMiddleware
    from shyfem_ui.services.maintenance import run_maintenance_loop

    _maint_factory = None
    if config.deployment_mode == "server" and config.maintenance_interval_seconds > 0:

        def _maint_factory():
            return run_maintenance_loop(
                job_queue,
                auth_service,
                interval_s=config.maintenance_interval_seconds,
                job_retention_days=config.job_retention_days,
                audit_service=audit_service,
                audit_retention_days=config.audit_retention_days,
                feedback_service=feedback_service,
                feedback_retention_days=config.feedback_retention_days,
            )

    app = MaintenanceMiddleware(app, _maint_factory)

    # Health check endpoint (outermost — bypasses auth and rate limiting)
    app = HealthCheckMiddleware(app, db_check=_check_db_health, job_queue=job_queue)

    return app


_ADMIN_ONLY_ITEMS = {"Admin"}


def _build_sidebar_nav() -> ui.Tag:
    """Build the sidebar navigation HTML."""
    nav_items = []
    for group in SIDEBAR_GROUPS:
        nav_items.append(
            ui.div(
                ui.span(group["name"], class_="sf-nav-group-header"),
                data_group=group["name"],
            )
        )
        for item in group["items"]:
            active_class = " active" if item["value"] == "Dashboard" else ""
            extra_attrs: dict = {}
            if item["value"] in _ADMIN_ONLY_ITEMS:
                extra_attrs["data_admin_only"] = "1"
            if item["value"] not in {"Tutorial"}:
                extra_attrs["data_hidden_for_tutorial"] = "1"
            nav_items.append(
                ui.div(
                    ui.tags.i(class_=f"bi {item['icon']} sf-nav-icon"),
                    ui.span(item["label"], class_="sf-nav-label"),
                    class_=f"sf-nav-item{active_class}",
                    data_nav=item["value"],
                    onclick=f"shyfemNavTo('{item['value']}')",
                    **extra_attrs,
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
  // Fetch current username and role via HTTP (WebSocket doesn't forward cookies behind proxy)
  fetch('api/whoami').then(function(r) { return r.json(); }).then(function(data) {
    var el = document.getElementById('sf-current-username');
    if (el) el.textContent = data.display_name || data.username || '';
    // Push role + WS-auth token (server-side identity) into Shiny. whoami can
    // answer before Shiny's initialize() has defined setInputValue -- the two
    // land within a millisecond -- and a push skipped then is never retried:
    // the session stays fail-closed (no projects, no writes) until a reload.
    // initializedPromise exists from shiny.js load and resolves on
    // shiny:sessioninitialized, after the init message (sending earlier, at
    // shiny:connected, kills the session with a ProtocolError).
    if (window.Shiny && window.Shiny.initializedPromise) {
      window.Shiny.initializedPromise.then(function() {
        // Role so server-side guards can use input.current_user_role()
        window.Shiny.setInputValue('current_user_role', data.role || '');
        // Token so the server can resolve identity in the WebSocket scope
        if (data.ws_token) {
          window.Shiny.setInputValue('_wsauth', data.ws_token, {priority: 'event'});
        }
      });
    } else {
      console.error('[SHYFEM] Shiny not loaded; WS identity not pushed');
    }

    // Hide admin-only sidebar items and pages for non-admin users
    if (data.role && data.role !== 'admin') {
      // Hide admin-only nav items
      document.querySelectorAll('.sf-nav-item[data-admin-only]').forEach(function(item) {
        item.style.display = 'none';
        // Hide the corresponding page panel
        var nav = item.getAttribute('data-nav');
        if (nav) {
          var pageId = 'sf-page-' + nav.replace(/ /g, '-');
          var page = document.getElementById(pageId);
          if (page) page.style.display = 'none';
        }
      });
      // Hide non-Tutorial nav items for tutorial-role users
      if (data.role === 'tutorial') {
        document.querySelectorAll('.sf-nav-item[data-hidden-for-tutorial]').forEach(function(el) {
          el.style.display = 'none';
        });
      }
      // Hide group headers whose visible items are all hidden
      document.querySelectorAll('[data-group]').forEach(function(header) {
        var next = header.nextElementSibling;
        var hasVisible = false;
        while (next && !next.hasAttribute('data-group')) {
          if (next.classList.contains('sf-nav-item') && next.style.display !== 'none') {
            hasVisible = true;
            break;
          }
          next = next.nextElementSibling;
        }
        if (!hasVisible) header.style.display = 'none';
      });
      // Switch default landing from Dashboard to Tutorial
      var dashNav = document.querySelector('.sf-nav-item[data-nav="Dashboard"]');
      if (dashNav) dashNav.classList.remove('active');
      var dashPage = document.getElementById('sf-page-Dashboard');
      if (dashPage) dashPage.classList.remove('active');
      shyfemNavTo('Tutorial');
    }
  }).catch(function() {});

  // Auto-close mobile sidebar overlay when viewport grows past the
  // mobile breakpoint. Without this, resizing from mobile to desktop
  // leaves the overlay state stuck open. Debounced to avoid spam.
  var resizeTimer = null;
  window.addEventListener('resize', function() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function() {
      if (window.innerWidth > 768) shyfemCloseMobile();
    }, 200);
  });
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
    // Tell Shiny that outputs in the newly visible page are no longer hidden.
    // Shiny's IntersectionObserver does not reliably re-fire after a parent
    // transitions from display:none to display:block via class toggle.
    if (page) {
      setTimeout(function() {
        page.querySelectorAll('.shiny-bound-output').forEach(function(el) {
          if (el.id) {
            Shiny.setInputValue('.clientdata_output_' + el.id + '_hidden', false);
          }
        });
      }, 0);
    }
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
  Shiny.addCustomMessageHandler('download_file', function(msg) {
    var a = document.createElement('a');
    a.href = msg.href;
    a.download = msg.filename || 'download';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  });

  // What's-new modal: persist dismissals, and report the last-seen changelog
  // version (per browser) so the server can decide whether to show the modal.
  Shiny.addCustomMessageHandler('shyfem_whatsnew_seen', function(v) {
    try { localStorage.setItem('shyfem-whatsnew-version', v); } catch (e) {}
  });
  // Deferred: sending an input synchronously inside shiny:connected trips
  // Shiny's session-state guard (ProtocolError "Invalid method for the current
  // session state"), which kills the session before any output renders. Report
  // once the session has settled (mirrors the deferred sends below).
  setTimeout(function() {
    if (window.Shiny && Shiny.setInputValue) {
      Shiny.setInputValue('_whatsnew_seen',
        localStorage.getItem('shyfem-whatsnew-version') || '', {priority: 'event'});
    }
  }, 500);

  // On connect, mark outputs in the currently active page as visible.
  // Shiny's IntersectionObserver may not detect display:block pages reliably.
  setTimeout(function() {
    var active = document.querySelector('.sf-page.active');
    if (active) {
      active.querySelectorAll('.shiny-bound-output').forEach(function(el) {
        if (el.id) {
          Shiny.setInputValue('.clientdata_output_' + el.id + '_hidden', false);
        }
      });
    }
  }, 100);
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
            ui.output_ui("active_project_badge", inline=True),
            class_="d-flex align-items-center",
        ),
        ui.div(
            about.about_topbar_ui("about"),
            ui.tags.button(
                ui.tags.i(class_="bi bi-moon"),
                id="dark-mode-toggle",
                class_="btn btn-sm sf-topbar-btn me-2",
                onclick="shyfemToggleDark()",
                title="Toggle dark mode",
            ),
            ui.span(
                ui.tags.i(class_="bi bi-person-circle me-1"),
                ui.span(id="sf-current-username"),
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
        ui.div(
            mesh_builder.mesh_builder_ui("mesh_builder"),
            id="sf-page-Mesh-Builder",
            class_="sf-page",
        ),
        ui.div(grid_prep.grid_prep_ui("grid_prep"), id="sf-page-Grid-Prep", class_="sf-page"),
        ui.div(
            partitioning.partitioning_ui("partitioning"),
            id="sf-page-Partitioning",
            class_="sf-page",
        ),
        ui.div(physics.physics_ui("physics"), id="sf-page-Physics", class_="sf-page"),
        ui.div(simulation.simulation_ui("simulation"), id="sf-page-Simulation", class_="sf-page"),
        ui.div(run.run_ui("run"), id="sf-page-Run", class_="sf-page"),
        ui.div(ibm.ibm_ui("ibm"), id="sf-page-IBM", class_="sf-page"),
        ui.div(
            postprocess.postprocess_ui("postprocess"),
            id="sf-page-Post-Process",
            class_="sf-page",
        ),
        ui.div(visualize.visualize_ui("visualize"), id="sf-page-Visualize", class_="sf-page"),
        ui.div(compare.compare_ui("compare"), id="sf-page-Compare", class_="sf-page"),
        ui.div(boxmodel.boxmodel_ui("boxmodel"), id="sf-page-Box-model", class_="sf-page"),
        ui.div(ensemble.ensemble_ui("ensemble"), id="sf-page-Ensemble", class_="sf-page"),
        ui.div(files.files_ui("files"), id="sf-page-Files", class_="sf-page"),
        ui.div(admin.admin_ui("admin"), id="sf-page-Admin", class_="sf-page"),
        class_="sf-content",
    )

    return ui.page_fillable(
        ui.head_content(_HEAD_EXTRAS),
        *([] if deckgl_head_includes is None else [deckgl_head_includes()]),
        ui.busy_indicators.use(spinners=True, pulse=True),
        topbar,
        ui.div(
            sidebar,
            content_panels,
            class_="sf-layout",
        ),
        ui.div(
            class_="sf-sidebar-backdrop", id="sf-sidebar-backdrop", onclick="shyfemCloseMobile()"
        ),
        title="SHYFEM Workbench",
    )


#: Strong references to in-flight custom-message tasks.
#:
#: ``asyncio`` keeps only a weak reference to a task, so without this a message
#: can be garbage-collected before it is written to the websocket.
_PENDING_SENDS: set[asyncio.Task] = set()


def _send_message_soon(session, name: str, payload) -> asyncio.Task | None:
    """Send a custom message from a SYNCHRONOUS reactive effect.

    ``Session.send_custom_message`` is a coroutine. Calling it without
    ``await`` builds a coroutine nobody ever runs: the browser receives
    nothing, and the only trace is a ``RuntimeWarning`` in a worker log that
    Shiny Server deletes on clean exit. Prefer making the effect ``async`` and
    awaiting directly; use this only where the caller cannot be async, as with
    ``nav_to``, which other page modules hold as a plain callback and call from
    their own sync effects.

    The loop is looked up BEFORE the coroutine is created, so the no-loop path
    cannot leave an orphan coroutine behind -- which would reintroduce exactly
    the warning this helper exists to remove.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("custom message %r dropped: no running event loop", name)
        return None
    task = loop.create_task(session.send_custom_message(name, payload))
    _PENDING_SENDS.add(task)
    task.add_done_callback(_PENDING_SENDS.discard)
    return task


def _build_server(
    input,
    output,
    session,
    config: Config,
    job_queue: JobQueue,
    auth_service: AuthService | None = None,
    audit_service: AuditService | None = None,
):
    """Build the application server logic."""
    active_project = reactive.value(None)
    tutorial_context = reactive.value(None)

    @render.ui
    def active_project_badge():
        """Topbar indicator of the currently loaded project."""
        proj = active_project.get()
        if not proj:
            return ui.span(
                ui.tags.i(class_="bi bi-folder2 me-1"),
                "No project",
                class_="badge rounded-pill bg-secondary ms-3",
                title="No project loaded — open one from the Workbench",
            )
        return ui.span(
            ui.tags.i(class_="bi bi-folder2-open me-1"),
            proj.get("name") or "Project",
            class_="badge rounded-pill bg-info text-dark ms-3",
            title="Loaded project",
        )

    def nav_to(tab_name: str):
        """Navigate to a tab via client-side JavaScript.

        Handed to the Dashboard and Tutorial servers as a plain callback and
        called from their sync effects, so it cannot await -- see
        ``_send_message_soon``. Until that scheduling was added the message was
        never sent and every "go to this page" button did nothing.
        """
        _send_message_soon(session, "shyfem_nav", {"tab": tab_name})

    # Jobs are owned by users, not by WebSocket sessions (N13): a session
    # ending (page refresh, network blip, laptop sleep) must NEVER cancel a
    # running job — Shiny has no reconnection, so that coupling was cancelling
    # legitimate long-running simulations on every disconnect. Jobs now end
    # only by completing, explicit cancel, or startup reconciliation of
    # phantom rows left by a previous process (see LocalJobQueue.
    # _load_history_from_db). _is_server is still used below (notification
    # poll scoping, F17 completion -- by user_id via list_scoped_jobs, never
    # the ephemeral per-connection session identifier, which doesn't survive
    # a WS reconnect).
    _is_server = config.deployment_mode == "server"
    _current_user = get_current_user()
    _user_id = _current_user["id"] if _current_user else None

    @reactive.effect
    @reactive.event(input._dark_mode)
    def _update_plotly_theme():
        from shyfem_ui.plotly_theme import register_shyfem_template

        is_dark = input._dark_mode()
        register_shyfem_template(dark=bool(is_dark))

    # "What's new" modal: shown once per browser per release. The browser
    # reports its last-seen version via input._whatsnew_seen (top-level, JS-set);
    # the server compares against the latest CHANGELOG release and shows the
    # modal if they differ. Dismissal persists the latest label to localStorage.
    _whatsnew_label: reactive.Value[str | None] = reactive.value(None)

    @reactive.effect
    @reactive.event(input._whatsnew_seen)
    def _maybe_show_whats_new():
        if not config.whats_new_enabled:
            return  # disabled (e.g. in E2E, where an undismissed modal blocks tests)
        from shyfem_ui.changelog import parse_latest_release, read_repo_markdown

        parsed = parse_latest_release(read_repo_markdown("CHANGELOG.md"))
        if not parsed:
            return
        label, section = parsed
        if input._whatsnew_seen() == label:
            return  # this browser has already seen the current release
        _whatsnew_label.set(label)
        ui.modal_show(
            ui.modal(
                ui.markdown(section),
                title=f"What's new — {label}",
                easy_close=True,
                size="l",
                footer=ui.input_action_button("_whatsnew_ok", "Got it", class_="btn-primary"),
            )
        )

    @reactive.effect
    @reactive.event(input._whatsnew_ok)
    async def _dismiss_whats_new():
        # async so the message can be awaited: unawaited, the browser never
        # stored the label, so the modal reappeared for every user on every
        # visit -- and it intercepts the first click on the page.
        label = _whatsnew_label.get()
        if label:
            await session.send_custom_message("shyfem_whatsnew_seen", label)
        ui.modal_remove()

    # Reactive calc for the current user's role.
    # Must live in the top-level server (no Shiny module namespace) so that
    # input.current_user_role — set by JS via Shiny.setInputValue — is reachable.
    # Modules receive this as a callable parameter instead of reading it themselves.
    @reactive.calc
    def _current_role():
        try:
            return input.current_user_role()
        except Exception:
            return _current_user.get("role") if _current_user else None

    # WS-scope identity — resolves the per-session WS-auth token pushed by the
    # browser as input._wsauth into a real user dict. Consumed by current_user()
    # below, which every page server receives and feeds to the fail-closed
    # editor_denied_reason / load_project_context guards.
    # Imports are lazy to avoid import-time DB/engine setup and circular imports.
    _ws_user: reactive.Value[dict | None] = reactive.value(None)

    @reactive.effect
    def _resolve_ws_identity():
        from shyfem_ui.services.ws_identity import resolve_ws_user

        tok = input._wsauth() if "_wsauth" in input else None
        svc = auth_service
        if svc is None:
            from shyfem_ui.services.auth_service import AuthService

            svc = AuthService()
        try:
            _ws_user.set(resolve_ws_user(tok, svc))
        except Exception:
            # Fail closed: leaving the user unresolved (None) denies every
            # edit-level mutation in server mode (editor_denied_reason), so a
            # transient validation/DB error can never silently fail OPEN.
            logger.warning("WS identity resolution failed; user set to None", exc_info=True)
            _ws_user.set(None)

    def current_user() -> dict | None:
        """Return the real, server-validated user in the WS scope (fallback path)."""
        return _ws_user.get()

    _ws_ready_marked = {"done": False}

    @reactive.effect
    def _signal_ws_identity_ready():
        """Insert a hidden DOM marker once server-side WS identity has resolved.

        Re-runs when ``_ws_user`` changes; on resolution it injects
        ``#sf-ws-ready-marker`` into the page via ``insert_ui`` (the same
        session channel as notifications, which flush reliably here — unlike
        top-level Shiny outputs, which do not). E2E waits on that marker before
        issuing a write, so it never fires while the fail-closed guards would
        still deny it (current_user() is None). Guarded to insert at most once.
        """
        if current_user() and not _ws_ready_marked["done"]:
            _ws_ready_marked["done"] = True
            ui.insert_ui(
                ui.tags.div(id="sf-ws-ready-marker", style="display:none;"),
                selector="body",
                where="beforeend",
            )

    # Initialize page servers
    home.home_server(
        "home",
        config,
        job_queue,
        active_project=active_project,
        nav_callback=nav_to,
        current_user=current_user,
    )
    tutorial.tutorial_server(
        "tutorial",
        config,
        active_project=active_project,
        nav_callback=nav_to,
        tutorial_context=tutorial_context,
    )
    about.about_server("about", config, current_user=current_user)
    mesh_builder.mesh_builder_server(
        "mesh_builder",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    grid_prep.grid_prep_server(
        "grid_prep",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    partitioning.partitioning_server(
        "partitioning",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    physics.physics_server(
        "physics", config, active_project=active_project, current_user=current_user
    )
    simulation.simulation_server(
        "simulation",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    run.run_server(
        "run",
        config,
        job_queue,
        active_project=active_project,
        tutorial_context=tutorial_context,
        user_role=_current_role,
        current_user=current_user,
    )
    ibm.ibm_server(
        "ibm",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    postprocess.postprocess_server(
        "postprocess",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    visualize.visualize_server(
        "visualize",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    compare.compare_server(
        "compare",
        config,
        job_queue,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    boxmodel.boxmodel_server(
        "boxmodel",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    ensemble.ensemble_server(
        "ensemble",
        config,
        job_queue,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
    files.files_server(
        "files",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )

    if auth_service:
        admin.admin_server(
            "admin",
            config,
            auth_service,
            user_role=_current_role,
            audit_service=audit_service,
            current_user=current_user,
        )

    # --- Cross-page job notifications ---
    _notification_svc = JobTransitionDetector()

    @reactive.effect
    def _poll_job_notifications():
        reactive.invalidate_later(5)  # Poll every 5 seconds

        import asyncio

        # Snapshot the server-validated identity HERE, in the synchronous
        # reactive flush. current_user() is a reactive read (_ws_user.get());
        # _check() below runs DETACHED via loop.create_task()/asyncio.run(),
        # outside the reactive context, where calling current_user() would
        # raise -- and the bare `except Exception` a few lines down would
        # silently swallow that, quietly killing notifications with no
        # error. F17 completion: scope by this user_id, never the ephemeral
        # per-connection session identifier (doesn't survive a WS reconnect,
        # dropping the user's own notifications; CPython id() reuse could
        # also surface a prior user's job metadata).
        _usr = current_user() if current_user is not None else None

        async def _check():
            jobs = await list_scoped_jobs(
                job_queue, _is_server, lambda: _usr, show_all_fn=lambda: False, limit=100
            )
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
    configure_cli_logging(config)
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
