"""Server-mode test app entry point.

Uses the real create_app() with auth enabled so SessionAuthMiddleware
is active. Seeded with an admin user for E2E testing.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("SHYFEM_UI_DEPLOYMENT_MODE", "server")
os.environ.setdefault("SHYFEM_UI_DEFAULT_ADMIN_USERNAME", "admin")
os.environ.setdefault("SHYFEM_UI_DEFAULT_ADMIN_PASSWORD", "testpass")

from shyfem_ui.app import create_app  # noqa: E402
from shyfem_ui.config import Config, set_config  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", required=True, help="SQLite DB path")
    parser.add_argument("--workdir", required=True, help="Work directory path")
    args = parser.parse_args()

    config = Config(
        host=args.host,
        port=args.port,
        database_url=f"sqlite:///{args.db}",
        work_dir=Path(args.workdir),
        deployment_mode="server",
        default_admin_username="admin",
        default_admin_password="testpass",
        auth_session_ttl_hours=24,
        debug=False,
        root_path="",
    )
    set_config(config)

    app = create_app(config)

    from shiny import run_app
    run_app(app, host=args.host, port=args.port)
