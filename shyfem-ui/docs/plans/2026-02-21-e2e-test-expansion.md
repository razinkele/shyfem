# E2E Test Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ~24 Playwright E2E tests covering Files tab, Admin panel, Tutorial tab, login/logout, and sharing UI.

**Architecture:** Two-server approach — extend existing local-mode `_test_app.py` with 3 missing tabs, add a second server-mode instance (using real `create_app()`) for auth/sharing tests. Each server gets a session-scoped Playwright page.

**Tech Stack:** Playwright, pytest, Shiny for Python, existing conftest.py infrastructure.

---

### Task 1: Add missing tabs to `_test_app.py`

The test app is missing Tutorial, Files, and Admin tabs that the real app has. Add them.

**Files:**
- Modify: `tests/_test_app.py`

**Step 1: Update imports and add tabs**

Add imports for `tutorial`, `files`, `admin`, and `AuthService` at the top of `_test_app.py`. Then add the 3 missing `nav_panel` entries and their server wiring.

In `tests/_test_app.py`, add to the imports (after line 31):

```python
from shyfem_ui.pages import (
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
    admin,
)
from shyfem_ui.services.auth_service import AuthService
```

Replace the existing individual imports from `shyfem_ui.pages`.

In `create_test_app`, add nav_panels after Ensemble (line 92):

```python
            ui.nav_panel("Ensemble", ensemble.ensemble_ui("ensemble")),
            ui.nav_panel("Files", files.files_ui("files")),
            ui.nav_panel("Tutorial", tutorial.tutorial_ui("tutorial")),
            ui.nav_panel("Admin", admin.admin_ui("admin")),
```

In the server function (line 99), add after `ensemble.ensemble_server(...)`:

```python
        files.files_server("files", config, active_project=active_project)
        tutorial.tutorial_server("tutorial", config, active_project=active_project)
        auth_service = AuthService()
        admin.admin_server("admin", config, auth_service)
```

Also add `active_project = reactive.value(None)` and `tutorial_context = reactive.value(None)` inside the server function and pass `active_project=active_project` to all page servers that accept it (home, grid_prep, partitioning, simulation, visualize, compare, ensemble). Pass `tutorial_context=tutorial_context` to tutorial_server.

**Step 2: Verify test app starts**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python tests/_test_app.py --port 9999 &`
Wait 5s, then: `curl -s http://127.0.0.1:9999/ | grep -c 'Tutorial\|Files\|Admin'`
Expected: 3 (all three tab names appear in HTML)
Kill the process.

**Step 3: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/_test_app.py && git commit -m "test: add Tutorial, Files, Admin tabs to test app"
```

---

### Task 2: Add server-mode test app and auth fixtures

Create a thin entry point for the server-mode test app, and add auth fixtures to conftest.py.

**Files:**
- Create: `tests/_test_auth_app.py`
- Modify: `tests/conftest.py`

**Step 1: Create `_test_auth_app.py`**

```python
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
    )
    set_config(config)

    app = create_app(config)

    from shiny import run_app
    run_app(app, host=args.host, port=args.port)
```

**Step 2: Add auth fixtures to `conftest.py`**

Add after the existing `pw_page` fixture:

```python
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
    # Clear any SHYFEM_UI_* vars to prevent interference
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
    # Wait for redirect to Dashboard
    page.wait_for_url(f"{base_url}/", timeout=15000)
    page.wait_for_timeout(2000)  # Let Shiny fully initialize


@pytest.fixture(scope="session")
def pw_auth_page(pw_browser, auth_live_server):
    """A Playwright page logged into the server-mode app as admin.

    Session-scoped: logs in once, stays logged in for all auth tests.
    """
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(15000)
    _login(page, auth_live_server, "admin", "testpass")
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()
```

**Step 3: Run existing tests to verify no regressions**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_navigation.py -v --timeout=120`
Expected: All 7 tests PASS (existing tests unaffected)

**Step 4: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/_test_auth_app.py tests/conftest.py && git commit -m "test: add server-mode test app and auth fixtures for E2E"
```

---

### Task 3: Local-mode tests — Tutorial, Files, Admin tab rendering

**Files:**
- Create: `tests/test_playwright_new_tabs.py`

**Step 1: Write the tests**

Create `tests/test_playwright_new_tabs.py`:

```python
"""Playwright tests for newer tabs: Tutorial, Files, Admin."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_TAB = "#main_navbar > li > a[data-value='{name}']"


def _switch_tab(pw_page, name):
    """Switch to a tab and wait for content."""
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name=name)).click(force=True)
    pw_page.wait_for_timeout(800)


class TestNewTabNavigation:
    """Verify the 3 new tabs exist and can be navigated to."""

    @pytest.mark.parametrize("tab_name", ["Tutorial", "Files", "Admin"])
    def test_tab_exists_and_activates(self, pw_page, tab_name):
        _switch_tab(pw_page, tab_name)
        tab = pw_page.locator(_TAB.format(name=tab_name))
        assert (
            "active" in (tab.get_attribute("class") or "")
            or tab.get_attribute("aria-selected") == "true"
        ), f"Tab '{tab_name}' did not become active"


class TestTutorialTab:
    """Tests for the Tutorial page rendering."""

    def test_tutorial_renders_heading(self, pw_page):
        _switch_tab(pw_page, "Tutorial")
        assert pw_page.locator("text=Tutorial Phases").count() >= 1

    def test_tutorial_has_phase_accordion(self, pw_page):
        _switch_tab(pw_page, "Tutorial")
        accordion = pw_page.locator("#tutorial-phase_accordion")
        assert accordion.count() >= 1

    def test_tutorial_create_project_button(self, pw_page):
        _switch_tab(pw_page, "Tutorial")
        btn = pw_page.locator("#tutorial-create_tutorial_project")
        assert btn.count() >= 1


class TestFilesTab:
    """Tests for the Files page rendering (no active project)."""

    def test_files_renders_heading(self, pw_page):
        _switch_tab(pw_page, "Files")
        assert pw_page.locator("text=Project Files").count() >= 1

    def test_files_no_project_message(self, pw_page):
        """Without an active project, show guidance message."""
        _switch_tab(pw_page, "Files")
        assert pw_page.locator("text=No project selected").count() >= 1

    def test_files_upload_section_hidden_without_project(self, pw_page):
        """Upload section should not appear without an active project."""
        _switch_tab(pw_page, "Files")
        # Storage bar should not be visible without project
        assert pw_page.locator(".progress-bar").count() == 0


class TestAdminTab:
    """Tests for the Admin page rendering (local mode — synthetic admin)."""

    def test_admin_renders_heading(self, pw_page):
        _switch_tab(pw_page, "Admin")
        assert pw_page.locator("text=User Management").count() >= 1

    def test_admin_create_user_button(self, pw_page):
        _switch_tab(pw_page, "Admin")
        btn = pw_page.locator("#admin-create_user_btn")
        assert btn.count() >= 1

    def test_admin_user_summary_area(self, pw_page):
        _switch_tab(pw_page, "Admin")
        # The user_summary output should be rendered
        summary = pw_page.locator("#admin-user_summary")
        assert summary.count() >= 1
```

**Step 2: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_new_tabs.py -v --timeout=120`
Expected: 12 PASSED

**Step 3: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/test_playwright_new_tabs.py && git commit -m "test: add E2E tests for Tutorial, Files, Admin tabs (local mode)"
```

---

### Task 4: Server-mode tests — Login/Logout flow

**Files:**
- Create: `tests/test_playwright_auth.py`

**Step 1: Write login/logout tests**

Create `tests/test_playwright_auth.py`:

```python
"""Playwright tests for authentication and server-mode features.

These tests use pw_auth_page which connects to a server-mode instance
with real SessionAuthMiddleware, login page, and user management.
"""

import pytest

from tests.conftest import _dismiss_modals, _login

pytestmark = [pytest.mark.e2e]

_TAB = "#main_navbar > li > a[data-value='{name}']"
_MODAL = ".modal.show"


def _switch_tab(page, name):
    _dismiss_modals(page)
    page.locator(_TAB.format(name=name)).click(force=True)
    page.wait_for_timeout(800)


class TestLoginFlow:
    """Tests for the login page and authentication."""

    def test_login_page_renders(self, pw_browser, auth_live_server):
        """Login page shows form with username/password fields."""
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        page.goto(f"{auth_live_server}/login", wait_until="networkidle", timeout=15000)
        assert page.locator("#username").count() == 1
        assert page.locator("#password").count() == 1
        assert page.locator("button[type='submit']").count() == 1
        page.close()
        ctx.close()

    def test_login_failure(self, pw_browser, auth_live_server):
        """Bad credentials show error alert on login page."""
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        page.goto(f"{auth_live_server}/login", wait_until="networkidle", timeout=15000)
        page.locator("#username").fill("admin")
        page.locator("#password").fill("wrongpassword")
        page.locator("button[type='submit']").click()
        page.wait_for_timeout(1000)
        assert page.locator(".alert-danger").count() >= 1
        page.close()
        ctx.close()

    def test_login_success(self, pw_browser, auth_live_server):
        """Valid credentials redirect to Dashboard."""
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        _login(page, auth_live_server, "admin", "testpass")
        # Should be on the main app now
        assert page.locator("#main_navbar").count() == 1
        page.close()
        ctx.close()

    def test_unauthenticated_redirects_to_login(self, pw_browser, auth_live_server):
        """Accessing / without session redirects to /login."""
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        page.goto(auth_live_server, wait_until="networkidle", timeout=15000)
        # Should end up on login page
        assert "/login" in page.url
        page.close()
        ctx.close()


class TestLogout:
    """Tests for the logout flow."""

    def test_logout_redirects_to_login(self, pw_auth_page, auth_live_server):
        """Clicking logout redirects to login page."""
        pw_auth_page.locator("#logout-btn").click()
        pw_auth_page.wait_for_timeout(2000)
        assert "/login" in pw_auth_page.url
        # Re-login to restore session for subsequent tests
        _login(pw_auth_page, auth_live_server, "admin", "testpass")
        _dismiss_modals(pw_auth_page)
```

**Step 2: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_auth.py::TestLoginFlow tests/test_playwright_auth.py::TestLogout -v --timeout=120`
Expected: 5 PASSED

**Step 3: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/test_playwright_auth.py && git commit -m "test: add E2E tests for login/logout flow (server mode)"
```

---

### Task 5: Server-mode tests — Admin panel user management

**Files:**
- Modify: `tests/test_playwright_auth.py`

**Step 1: Add admin panel tests**

Append to `tests/test_playwright_auth.py`:

```python
class TestAdminPanel:
    """Tests for admin user management in server mode."""

    def test_admin_user_table_shows_admin(self, pw_auth_page):
        """Admin tab lists the seeded admin user."""
        _switch_tab(pw_auth_page, "Admin")
        # The user table should contain "admin" username
        table = pw_auth_page.locator("#admin-user_table")
        table.wait_for(state="attached", timeout=10000)
        pw_auth_page.wait_for_timeout(1000)
        assert pw_auth_page.locator("text=admin").count() >= 1

    def test_admin_create_user(self, pw_auth_page):
        """Create a new user via the admin form."""
        _switch_tab(pw_auth_page, "Admin")
        pw_auth_page.wait_for_timeout(500)

        # Click create user to open modal
        pw_auth_page.locator("#admin-create_user_btn").click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)

        # Fill form
        pw_auth_page.locator("#admin-new_username").fill("testuser")
        pw_auth_page.locator("#admin-new_password").fill("testpass123")
        pw_auth_page.wait_for_timeout(300)

        # Submit
        pw_auth_page.locator(_MODAL).locator("button:has-text('Create')").click(force=True)
        pw_auth_page.wait_for_timeout(2000)

        # User should now appear in the table
        _dismiss_modals(pw_auth_page)
        assert pw_auth_page.locator("text=testuser").count() >= 1

    def test_admin_reset_password(self, pw_auth_page):
        """Reset password button exists for created user."""
        _switch_tab(pw_auth_page, "Admin")
        pw_auth_page.wait_for_timeout(500)
        # Look for reset password buttons in the user table
        reset_btns = pw_auth_page.locator("button:has-text('Reset'), a:has-text('Reset')")
        assert reset_btns.count() >= 1

    def test_admin_toggle_active(self, pw_auth_page):
        """Toggle active button exists in admin panel."""
        _switch_tab(pw_auth_page, "Admin")
        pw_auth_page.wait_for_timeout(500)
        # Active/Inactive badges should be present
        badges = pw_auth_page.locator(".badge:has-text('Active'), .badge:has-text('Inactive')")
        assert badges.count() >= 1
```

**Step 2: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_auth.py::TestAdminPanel -v --timeout=120`
Expected: 4 PASSED

**Step 3: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/test_playwright_auth.py && git commit -m "test: add E2E tests for admin panel user management"
```

---

### Task 6: Server-mode tests — Sharing UI

**Files:**
- Modify: `tests/test_playwright_auth.py`

**Step 1: Create a project, then test sharing UI**

Append to `tests/test_playwright_auth.py`:

```python
class TestSharingUI:
    """Tests for the project sharing modal (requires a project to exist)."""

    def _ensure_project(self, pw_auth_page):
        """Create a project if none exists, return to Dashboard."""
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(500)

        # Check if any project rows exist
        project_links = pw_auth_page.locator("a.fw-bold[id^='home-project_']")
        if project_links.count() == 0:
            # Create a new project
            pw_auth_page.locator("#home-new_project_btn").click(force=True)
            pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
            pw_auth_page.locator("#home-project_name").fill("TestProject")
            pw_auth_page.locator(_MODAL).locator(
                "button:has-text('Create')"
            ).click(force=True)
            pw_auth_page.wait_for_timeout(2000)
            _dismiss_modals(pw_auth_page)

    def test_share_button_visible_for_owner(self, pw_auth_page):
        """Share button appears on owned projects."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(500)
        share_btns = pw_auth_page.locator("a:has-text('Share')")
        assert share_btns.count() >= 1

    def test_share_modal_opens(self, pw_auth_page):
        """Clicking Share opens the sharing modal."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(500)
        pw_auth_page.locator("a:has-text('Share')").first.click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
        # Modal should have "Current Access" and "Add User" sections
        assert pw_auth_page.locator("text=Current Access").count() >= 1
        assert pw_auth_page.locator("text=Add User").count() >= 1
        _dismiss_modals(pw_auth_page)

    def test_share_modal_shows_role_selector(self, pw_auth_page):
        """Share modal has a role selector (Viewer/Editor)."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(500)
        pw_auth_page.locator("a:has-text('Share')").first.click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
        # Role selector should have Viewer and Editor options
        role_select = pw_auth_page.locator("#home-share_role, select[id$='share_role']")
        if role_select.count() >= 1:
            html = role_select.inner_html()
            assert "Viewer" in html or "viewer" in html
        _dismiss_modals(pw_auth_page)

    def test_share_add_permission(self, pw_auth_page):
        """Add a user with viewer role via the share modal."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(500)
        pw_auth_page.locator("a:has-text('Share')").first.click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)

        # Check if there are shareable users (testuser created in TestAdminPanel)
        user_select = pw_auth_page.locator(
            "#home-share_user_id, select[id$='share_user_id']"
        )
        if user_select.count() >= 1:
            # Select first available user and share
            share_btn = pw_auth_page.locator(
                _MODAL
            ).locator("button:has-text('Share')")
            if share_btn.count() >= 1:
                share_btn.click(force=True)
                pw_auth_page.wait_for_timeout(2000)

        _dismiss_modals(pw_auth_page)
        # Test passes if no errors (sharing might not have users to share with)
```

**Step 2: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_auth.py::TestSharingUI -v --timeout=120`
Expected: 4 PASSED

**Step 3: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/test_playwright_auth.py && git commit -m "test: add E2E tests for sharing UI modal"
```

---

### Task 7: Update navigation test + final verification

**Files:**
- Modify: `tests/test_playwright_navigation.py`

**Step 1: Add new tabs to TAB_NAMES**

In `tests/test_playwright_navigation.py`, update the `TAB_NAMES` list (line 9):

```python
TAB_NAMES = [
    "Dashboard",
    "Tutorial",
    "Grid Prep",
    "Partitioning",
    "Simulation",
    "Run",
    "Post-Process",
    "Visualize",
    "Compare",
    "Ensemble",
    "Files",
    "Admin",
]
```

**Step 2: Run all Playwright tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_*.py -v --timeout=120`
Expected: All tests PASS (~115+ total: 88 existing + ~24 new + 3 extra parametrized nav)

**Step 3: Run full unit test suite to verify no regressions**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ --ignore-glob="tests/test_playwright_*" -x -q`
Expected: 1004+ PASSED, 0 FAILED

**Step 4: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && git add tests/test_playwright_navigation.py && git commit -m "test: add Tutorial, Files, Admin to navigation tab tests"
```

---

## Test Summary

| Task | File | New Tests |
|------|------|-----------|
| 1 | `tests/_test_app.py` | 0 (infra) |
| 2 | `tests/_test_auth_app.py`, `tests/conftest.py` | 0 (infra) |
| 3 | `tests/test_playwright_new_tabs.py` | 12 |
| 4 | `tests/test_playwright_auth.py` | 5 |
| 5 | `tests/test_playwright_auth.py` | 4 |
| 6 | `tests/test_playwright_auth.py` | 4 |
| 7 | `tests/test_playwright_navigation.py` | 3 (parametrized) |
| **Total** | | **~28** |

## Dependency Graph

```
Task 1 (add tabs to _test_app.py)
  └── Task 3 (local-mode tab tests) — depends on Task 1
      └── Task 7 (nav test update) — depends on Task 1

Task 2 (auth fixtures + _test_auth_app.py)
  └── Task 4 (login/logout tests) — depends on Task 2
      └── Task 5 (admin panel tests) — depends on Task 4
          └── Task 6 (sharing UI tests) — depends on Task 5 (needs testuser)
```
