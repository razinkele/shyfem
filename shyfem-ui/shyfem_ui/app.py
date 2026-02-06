"""Main SHYFEM UI Shiny application."""

import argparse
import base64
import hashlib
import hmac
import sys
from pathlib import Path
from typing import Optional

from shiny import App, reactive, ui

try:
    import shinyswatch
    HAS_SHINYSWATCH = True
except ImportError:
    HAS_SHINYSWATCH = False

from shyfem_ui.config import Config, get_config, set_config
from shyfem_ui.db.base import init_db
from shyfem_ui.pages import grid_prep, home, partitioning, postprocess, run, simulation, visualize
from shyfem_ui.services.job_queue import JobQueue, JobQueueFactory


def create_app(config: Optional[Config] = None) -> App:
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
        _build_server(input, output, session, config, job_queue)

    app = App(app_ui, server)

    # Wrap with basic auth middleware in server mode
    if config.auth_enabled and config.auth_password:
        app = BasicAuthMiddleware(app, config.auth_username, config.auth_password)
    elif config.deployment_mode == "server" and not config.auth_enabled:
        print(
            "WARNING: Running in server mode without authentication. "
            "Set SHYFEM_UI_AUTH_ENABLED=true and SHYFEM_UI_AUTH_PASSWORD=<password> "
            "to enable basic auth."
        )

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
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                [b"www-authenticate", f'Basic realm="{self.REALM}"'.encode()],
                [b"content-type", b"text/plain"],
                [b"content-length", str(len(response_body)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": response_body,
        })

    def _check_credentials(self, auth_header: str) -> bool:
        if not auth_header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth_header[6:]).decode()
            username, password = decoded.split(":", 1)
        except Exception:
            return False

        password_hash = hashlib.sha256(password.encode()).digest()
        return (
            hmac.compare_digest(username.encode(), self.username.encode())
            and hmac.compare_digest(password_hash, self._password_hash)
        )


def _build_ui(config: Config) -> ui.Tag:
    """Build the application UI."""
    # Navigation bar with pages
    nav_items = [
        ui.nav_panel("Dashboard", home.home_ui("home")),
        ui.nav_panel("Grid Prep", grid_prep.grid_prep_ui("grid_prep")),
        ui.nav_panel("Partitioning", partitioning.partitioning_ui("partitioning")),
        ui.nav_panel("Simulation", simulation.simulation_ui("simulation")),
        ui.nav_panel("Run", run.run_ui("run")),
        ui.nav_panel("Post-Process", postprocess.postprocess_ui("postprocess")),
        ui.nav_panel("Visualize", visualize.visualize_ui("visualize")),
    ]

    # Add spacer and info
    nav_items.append(ui.nav_spacer())
    nav_items.append(
        ui.nav_menu(
            "Help",
            ui.nav_control(
                ui.a(
                    "Documentation",
                    href="https://shyfem.readthedocs.io/",
                    target="_blank",
                    class_="dropdown-item",
                )
            ),
            ui.nav_control(
                ui.a(
                    "About SHYFEM",
                    href="https://github.com/shyfem/shyfem",
                    target="_blank",
                    class_="dropdown-item",
                )
            ),
        )
    )

    # Build page with optional theme
    theme = None
    if HAS_SHINYSWATCH:
        theme = getattr(shinyswatch.theme, config.theme, shinyswatch.theme.flatly)

    return ui.page_navbar(
        *nav_items,
        title="SHYFEM Workbench",
        id="main_navbar",
        fillable=True,
        theme=theme,
    )


def _build_server(input, output, session, config: Config, job_queue: JobQueue):
    """Build the application server logic."""
    # Initialize page servers
    home.home_server("home", config, job_queue)
    grid_prep.grid_prep_server("grid_prep", config)
    partitioning.partitioning_server("partitioning", config)
    simulation.simulation_server("simulation", config)
    run.run_server("run", config, job_queue)
    postprocess.postprocess_server("postprocess", config)
    visualize.visualize_server("visualize", config)


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

    # Create and run app
    print(f"Starting SHYFEM Workbench...")
    print(f"  Mode: {config.deployment_mode}")
    print(f"  SHYFEM Dir: {config.shyfem_dir}")
    print(f"  Work Dir: {config.work_dir}")
    print(f"  URL: http://{host}:{port}")
    print()

    app = create_app(config)

    # Run with Shiny's built-in server
    from shiny import run_app
    run_app(
        app,
        host=host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
