"""Shared test fixtures for unit and browser tests.

Provides:
- Environment isolation (strips SHYFEM_UI_* env vars)
- Temporary config/database isolation for all tests
- A live Shiny app server on a free port for browser tests
- Playwright browser/page fixtures
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

# ---------------------------------------------------------------------------
# Foreign-key enforcement for the whole test session
# ---------------------------------------------------------------------------
# Production turns on PRAGMA foreign_keys via the base.py connect-listener, but
# most DB test fixtures build their own create_engine("sqlite:///:memory:") and
# would bypass it — so the suite couldn't prove the delete paths are FK-clean.
# Register the PRAGMA on the Engine class so EVERY SQLite connection opened
# during tests enforces foreign keys, matching production exactly.


@event.listens_for(Engine, "connect")
def _tests_enforce_sqlite_foreign_keys(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


# ---------------------------------------------------------------------------
# Environment isolation — prevent host env vars from leaking into tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def _isolate_env(tmp_path_factory):
    """Isolate the test session from ambient SHYFEM_UI_* configuration.

    Pydantic Settings reads env vars automatically AND from an ``.env`` file
    (``env_file=".env"``). Stripping env VARS alone is not enough: the
    production checkout carries ``SHYFEM_UI_DEPLOYMENT_MODE=server`` in ``.env``,
    which still leaks into ``Config()`` after the strip and flips the
    fail-closed auth gates (editor_denied_reason / load_project_context) to deny
    on user=None — making the suite pass in a worktree (no .env) but fail in the
    main checkout (this broke the Phase 3B merge). So we also pin
    DEPLOYMENT_MODE=local explicitly; an env var overrides the .env file in
    pydantic's precedence, giving a deterministic default. Tests that need
    server mode opt in with monkeypatch.setenv (which overrides per-test).

    Also pin DATABASE_URL to a session-temp path. The default url is a RELATIVE
    ``sqlite:///./shyfem_ui.db`` — i.e. the PRODUCTION DB — so any test that
    inits the global engine (e.g. a LocalJobQueue load/persist) would otherwise
    read and WRITE the real database (this had leaked hundreds of test job rows
    into prod). The temp DB is left uninitialised, so the job-queue load/persist
    paths no-op exactly as the tests expect, and prod is never touched. Tests
    needing a real schema set up their own DB (monkeypatch + init_db).
    """
    saved = {}
    for key in list(os.environ):
        if key.startswith("SHYFEM_UI_"):
            saved[key] = os.environ.pop(key)
    os.environ["SHYFEM_UI_DEPLOYMENT_MODE"] = "local"
    _db = tmp_path_factory.mktemp("global_db") / "session.db"
    os.environ["SHYFEM_UI_DATABASE_URL"] = f"sqlite:///{_db}"

    # Drop any cached engine/config so the temp URL takes effect from first use.
    import shyfem_ui.config as _cfg
    import shyfem_ui.db.base as _db_base

    _cfg._config = None
    _db_base._engine = None
    _db_base._SessionLocal = None
    yield
    os.environ.pop("SHYFEM_UI_DEPLOYMENT_MODE", None)
    os.environ.pop("SHYFEM_UI_DATABASE_URL", None)
    os.environ.update(saved)
    _cfg._config = None
    _db_base._engine = None
    _db_base._SessionLocal = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Playwright default timeout for the shared browser pages. 30s (not 15s):
# CI runners are slow/contended — 3 session-scoped Shiny server subprocesses
# + Chromium share ~2 cores — so element actionability and reactive re-renders
# that take <1s locally can exceed a 15s default under load. The full suite
# passes 190/190 locally; this margin is purely for the slower CI environment.
_PW_DEFAULT_TIMEOUT_MS = 30000


def _find_free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = 30.0) -> bool:
    """Wait until the server accepts TCP connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


# ---------------------------------------------------------------------------
# App server fixture (session-scoped – one server for all browser tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app_port():
    """Return the port the test app will listen on."""
    return _find_free_port()


@pytest.fixture(scope="session")
def app_url(app_port):
    """Return the base URL for the running test app."""
    return f"http://127.0.0.1:{app_port}"


@pytest.fixture(scope="session")
def _app_server(tmp_path_factory, app_port):
    """Start the Shiny app in a subprocess for the test session.

    The server is killed when the session ends.
    """
    tmp_dir = tmp_path_factory.mktemp("shyfem_ui_test")
    db_path = tmp_dir / "test.db"
    work_dir = tmp_dir / "work"
    work_dir.mkdir()

    env = os.environ.copy()
    env.update(
        {
            "SHYFEM_UI_HOST": "127.0.0.1",
            "SHYFEM_UI_PORT": str(app_port),
            "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db_path}",
            "SHYFEM_UI_WORK_DIR": str(work_dir),
            "SHYFEM_UI_DEPLOYMENT_MODE": "local",
            "SHYFEM_UI_AUTH_ENABLED": "false",
            "SHYFEM_UI_DEBUG": "false",
        }
    )

    python = sys.executable
    # Use the test-specific app entry point that stubs the run module's
    # server to avoid its reactive effects deadlocking the event loop.
    test_app = str(Path(__file__).resolve().parent / "_test_app.py")
    proc = subprocess.Popen(
        [
            python,
            test_app,
            "--port",
            str(app_port),
            "--host",
            "127.0.0.1",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    if not _wait_for_server("127.0.0.1", app_port, timeout=30):
        proc.kill()
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        pytest.fail(f"Shiny app did not start within 30 s.\nOutput:\n{stdout}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def live_server(_app_server, app_url):
    """Ensure the live server is running and return its base URL."""
    return app_url


# ---------------------------------------------------------------------------
# Playwright fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pw_browser():
    """Launch a Playwright Chromium browser for the test session."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed — pip install pytest-playwright")

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:
        pw.stop()
        pytest.skip(
            f"Playwright browsers not installed: {exc}\n"
            "Run: python -m playwright install chromium --with-deps"
        )
    yield browser
    browser.close()
    pw.stop()


@pytest.fixture(autouse=True)
def _reset_active_project_state(request):
    """Reset `active_project` to None before every Playwright test.

    `pw_page` is session-scoped (Shiny's single-threaded asyncio server
    can't reliably accept new WebSocket connections after disconnect) so
    page state — including `active_project = reactive.value(None)` in
    `_test_app.py` — leaks across tests. Without this reset, the first
    test in alphabetically-prior file `test_playwright_*.py` to set an
    active_project pollutes every subsequent test that expects None.

    Originally added per-class in Section M's picker tests (autouse on
    `TestGridPrepPickerNoProject` etc.). Promoted to conftest in
    Section M.2 follow-up so existing TestFilesTab tests (which assume
    no-project state but have no class-level reset) also pass.

    Skipped if the `pw_page` fixture isn't requested by the test —
    avoids importing playwright in non-Playwright tests.
    """
    if "pw_page" not in request.fixturenames:
        yield
        return
    page = request.getfixturevalue("pw_page")
    # Reset active_project via the test hook. Use empty string (not
    # null) — Shiny.setInputValue silently drops null, but coerces
    # "" through the @reactive.event hook in _test_app.py whose
    # `value if value else None` then sets active_project.set(None).
    #
    # We do NOT navigate to a specific tab here: cumulative test
    # classes (e.g. TestMeshCreationFlow) rely on the page state
    # left by the previous test in their class. Each test that
    # depends on no-active-project navigates to its target tab
    # itself, which fires a fresh render against the now-None
    # active_project value.
    page.evaluate("""
        if (typeof window.__test_set_active_project === 'function') {
            window.__test_set_active_project("");
        }
    """)
    page.wait_for_timeout(300)
    yield


@pytest.fixture(scope="session")
def pw_page(pw_browser, live_server):
    """A single Playwright page (Shiny session) shared across ALL tests.

    Shiny's single-threaded asyncio server cannot reliably accept new WebSocket
    connections after a previous one disconnects, so we keep one page alive for
    the entire session.  Tests must clean up after themselves (close modals,
    switch back to Dashboard tab).
    """
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(_PW_DEFAULT_TIMEOUT_MS)
    page.goto(live_server, wait_until="networkidle", timeout=30000)
    # Wait for Shiny to fully connect AND reactive outputs to render.
    # We probe `home-system_health_count` (the dashboard "Tools Ready" badge)
    # — a small reactive output that renders early, so once it's no longer
    # `recalculating`, the WebSocket is live and the home page is hydrated.
    page.wait_for_function(
        "() => {"
        '  const el = document.getElementById("home-system_health_count");'
        '  return el && !el.classList.contains("recalculating") && el.children.length > 0;'
        "}",
        timeout=30000,
    )
    # Dismiss any modal / backdrop that may have appeared during initialization
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()


def _dismiss_modals(page):
    """Remove any lingering modal / backdrop via JS.

    Shiny's modal system can leave behind backdrop elements that intercept
    pointer events.  We aggressively remove ALL modal-related overlays.
    """
    page.evaluate("""() => {
        // Remove backdrops entirely
        document.querySelectorAll('.modal-backdrop').forEach(el => el.remove());
        // Remove modal elements entirely so Shiny recreates them fresh
        // (setting display:none breaks Shiny's modal reuse since the inline
        // style persists even after Shiny adds the .show class)
        document.querySelectorAll('.modal').forEach(el => el.remove());
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
    }""")
    page.wait_for_timeout(100)


# ---------------------------------------------------------------------------
# Server-mode app (with authentication) for auth/sharing E2E tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def auth_app_port():
    """Return a free port for the server-mode test app."""
    return _find_free_port()


@pytest.fixture(scope="session")
def _auth_app_server(tmp_path_factory, auth_app_port):
    """Start a server-mode Shiny app with authentication enabled."""
    tmp_dir = tmp_path_factory.mktemp("shyfem_ui_auth_test")
    db_path = tmp_dir / "auth_test.db"
    work_dir = tmp_dir / "work"
    work_dir.mkdir()

    env = os.environ.copy()
    env = {k: v for k, v in env.items() if not k.startswith("SHYFEM_UI_")}
    env.update(
        {
            "SHYFEM_UI_HOST": "127.0.0.1",
            "SHYFEM_UI_PORT": str(auth_app_port),
            "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db_path}",
            "SHYFEM_UI_WORK_DIR": str(work_dir),
            "SHYFEM_UI_DEPLOYMENT_MODE": "server",
            "SHYFEM_UI_DEFAULT_ADMIN_USERNAME": "admin",
            "SHYFEM_UI_DEFAULT_ADMIN_PASSWORD": "testpass",
            "SHYFEM_UI_AUTH_SESSION_TTL_HOURS": "24",
            "SHYFEM_UI_DEBUG": "false",
        }
    )

    python = sys.executable
    test_app = str(Path(__file__).resolve().parent / "_test_auth_app.py")
    proc = subprocess.Popen(
        [
            python,
            test_app,
            "--port",
            str(auth_app_port),
            "--host",
            "127.0.0.1",
            "--db",
            str(db_path),
            "--workdir",
            str(work_dir),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    if not _wait_for_server("127.0.0.1", auth_app_port, timeout=30):
        proc.kill()
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        pytest.fail(f"Auth app did not start within 30 s.\nOutput:\n{stdout}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def auth_live_server(_auth_app_server, auth_app_port):
    """Ensure the auth server is running and return its base URL."""
    return f"http://127.0.0.1:{auth_app_port}"


def _login(page, base_url: str, username: str, password: str):
    """Log into the server-mode app by filling the login form."""
    page.goto(f"{base_url}/login", wait_until="networkidle", timeout=15000)
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_url(f"{base_url}/", timeout=15000)
    page.wait_for_timeout(2000)


def _wait_auth_identity_resolved(page):
    """Block until server-mode WS identity has resolved **server-side**.

    In server mode, write handlers are fail-closed on ``current_user() is None``
    (the Phase 3B WS-auth guards). After login the page renders before the async
    identity round-trip finishes: the client fetches ``api/whoami`` and pushes a
    ``_wsauth`` token, which the server's ``_resolve_ws_identity`` effect turns
    into the real user (a DB lookup) — only THEN is ``current_user()`` non-None
    and writes allowed.

    We wait on ``#sf_ws_identity_ready`` — a hidden output the app renders to
    ``"ready"`` from ``current_user()`` itself — NOT the client-side
    ``#sf-current-username`` (set the moment whoami returns, before the server
    resolves the token). Waiting on the client signal was insufficient: writes
    still fired before resolution on slow CI runners and were silently denied.
    """
    page.wait_for_function(
        "() => !!document.getElementById('sf-ws-ready-marker')",
        timeout=30000,
    )


@pytest.fixture(scope="session")
def pw_auth_page(pw_browser, auth_live_server):
    """A Playwright page logged into the server-mode app as admin."""
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(_PW_DEFAULT_TIMEOUT_MS)
    _login(page, auth_live_server, "admin", "testpass")
    _wait_auth_identity_resolved(page)
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()


# ---------------------------------------------------------------------------
# WS trusted-identity (Phase 4) — seeded server with a non-admin viewer
# ---------------------------------------------------------------------------
#
# A SEPARATE server (own DB, own port) from `_auth_app_server` so the seeded
# users/projects can't interfere with the admin-only auth E2E suite. Seeds
# `viewer1` + a `Shared` project (viewer permission) + a `Private` project
# (not shared) — see tests/_test_ws_identity_app.py.

VIEWER_USERNAME = "viewer1"
VIEWER_PASSWORD = "viewerpass"


@pytest.fixture(scope="session")
def ws_identity_app_port():
    """Return a free port for the seeded WS-identity test app."""
    return _find_free_port()


@pytest.fixture(scope="session")
def _ws_identity_app_server(tmp_path_factory, ws_identity_app_port):
    """Start the seeded server-mode app for WS trusted-identity E2E tests."""
    tmp_dir = tmp_path_factory.mktemp("shyfem_ui_ws_identity")
    db_path = tmp_dir / "ws_identity.db"
    work_dir = tmp_dir / "work"
    work_dir.mkdir()

    env = os.environ.copy()
    env = {k: v for k, v in env.items() if not k.startswith("SHYFEM_UI_")}
    env.update(
        {
            "SHYFEM_UI_HOST": "127.0.0.1",
            "SHYFEM_UI_PORT": str(ws_identity_app_port),
            "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db_path}",
            "SHYFEM_UI_WORK_DIR": str(work_dir),
            "SHYFEM_UI_DEPLOYMENT_MODE": "server",
            "SHYFEM_UI_DEFAULT_ADMIN_USERNAME": "admin",
            "SHYFEM_UI_DEFAULT_ADMIN_PASSWORD": "testpass",
            "SHYFEM_UI_AUTH_SESSION_TTL_HOURS": "24",
            "SHYFEM_UI_DEBUG": "false",
        }
    )

    python = sys.executable
    test_app = str(Path(__file__).resolve().parent / "_test_ws_identity_app.py")
    proc = subprocess.Popen(
        [
            python,
            test_app,
            "--port",
            str(ws_identity_app_port),
            "--host",
            "127.0.0.1",
            "--db",
            str(db_path),
            "--workdir",
            str(work_dir),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).resolve().parent.parent),
    )

    if not _wait_for_server("127.0.0.1", ws_identity_app_port, timeout=30):
        proc.kill()
        stdout = proc.stdout.read().decode() if proc.stdout else ""
        pytest.fail(f"WS-identity app did not start within 30 s.\nOutput:\n{stdout}")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="session")
def ws_identity_live_server(_ws_identity_app_server, ws_identity_app_port):
    """Ensure the seeded WS-identity server is running and return its base URL."""
    return f"http://127.0.0.1:{ws_identity_app_port}"


def _wait_hydrated(page):
    """Block until Shiny's WS is live and the dashboard health badge rendered."""
    page.wait_for_function(
        "() => {"
        '  const el = document.getElementById("home-system_health_count");'
        '  return el && !el.classList.contains("recalculating") && el.children.length > 0;'
        "}",
        timeout=30000,
    )


@pytest.fixture(scope="session")
def pw_viewer_page(pw_browser, ws_identity_live_server):
    """A Playwright page logged into the seeded server as the viewer1 account.

    Session-scoped: Shiny can't reliably accept a fresh WS after disconnect,
    so the whole WS-identity suite shares this one logged-in viewer session.
    """
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(_PW_DEFAULT_TIMEOUT_MS)
    _login(page, ws_identity_live_server, VIEWER_USERNAME, VIEWER_PASSWORD)
    _wait_hydrated(page)
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()
