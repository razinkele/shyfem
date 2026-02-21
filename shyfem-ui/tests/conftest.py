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


# ---------------------------------------------------------------------------
# Environment isolation — prevent host env vars from leaking into tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _isolate_env():
    """Strip all SHYFEM_UI_* environment variables for the test session.

    Pydantic Settings reads env vars automatically.  If the host shell has
    e.g. SHYFEM_UI_DEPLOYMENT_MODE=server, tests that create Config() without
    explicit overrides will see the host value instead of the default.
    """
    saved = {}
    for key in list(os.environ):
        if key.startswith("SHYFEM_UI_"):
            saved[key] = os.environ.pop(key)
    yield
    os.environ.update(saved)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    env.update({
        "SHYFEM_UI_HOST": "127.0.0.1",
        "SHYFEM_UI_PORT": str(app_port),
        "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db_path}",
        "SHYFEM_UI_WORK_DIR": str(work_dir),
        "SHYFEM_UI_DEPLOYMENT_MODE": "local",
        "SHYFEM_UI_AUTH_ENABLED": "false",
        "SHYFEM_UI_DEBUG": "false",
    })

    python = sys.executable
    # Use the test-specific app entry point that stubs the run module's
    # server to avoid its reactive effects deadlocking the event loop.
    test_app = str(Path(__file__).resolve().parent / "_test_app.py")
    proc = subprocess.Popen(
        [
            python, test_app,
            "--port", str(app_port),
            "--host", "127.0.0.1",
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
    page.set_default_timeout(15000)
    page.goto(live_server, wait_until="networkidle", timeout=30000)
    # Wait for Shiny to fully connect AND reactive outputs to render
    page.wait_for_function(
        '() => {'
        '  const el = document.getElementById("home-system_status");'
        '  return el && !el.classList.contains("recalculating") && el.children.length > 0;'
        '}',
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
    env.update({
        "SHYFEM_UI_HOST": "127.0.0.1",
        "SHYFEM_UI_PORT": str(auth_app_port),
        "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db_path}",
        "SHYFEM_UI_WORK_DIR": str(work_dir),
        "SHYFEM_UI_DEPLOYMENT_MODE": "server",
        "SHYFEM_UI_DEFAULT_ADMIN_USERNAME": "admin",
        "SHYFEM_UI_DEFAULT_ADMIN_PASSWORD": "testpass",
        "SHYFEM_UI_AUTH_SESSION_TTL_HOURS": "24",
        "SHYFEM_UI_DEBUG": "false",
    })

    python = sys.executable
    test_app = str(Path(__file__).resolve().parent / "_test_auth_app.py")
    proc = subprocess.Popen(
        [
            python, test_app,
            "--port", str(auth_app_port),
            "--host", "127.0.0.1",
            "--db", str(db_path),
            "--workdir", str(work_dir),
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


@pytest.fixture(scope="session")
def pw_auth_page(pw_browser, auth_live_server):
    """A Playwright page logged into the server-mode app as admin."""
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(15000)
    _login(page, auth_live_server, "admin", "testpass")
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()
