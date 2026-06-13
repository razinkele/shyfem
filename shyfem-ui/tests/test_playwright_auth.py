"""Playwright tests for authentication and server-mode features."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e]


_TAB = ".sf-nav-item[data-nav='{name}']"
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
        page.goto(f"{auth_live_server}/login", wait_until="domcontentloaded", timeout=15000)
        assert page.locator("#username").count() == 1
        assert page.locator("#password").count() == 1
        assert page.locator("button[type='submit']").count() == 1
        page.close()
        ctx.close()

    def test_login_failure(self, pw_browser, auth_live_server):
        """Bad credentials show error alert on login page."""
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        page.goto(f"{auth_live_server}/login", wait_until="domcontentloaded", timeout=15000)
        page.locator("#username").fill("admin")
        page.locator("#password").fill("wrongpassword")
        # The form POST returns a 200 with the login page re-rendered
        # (including the error alert). Use expect_navigation with
        # domcontentloaded to avoid CDN timeouts.
        with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
            page.locator("button[type='submit']").click()
        # Login error uses class "error-alert" (rendered by SessionAuthMiddleware
        # in middleware/session_auth.py:_serve_login_page).
        assert page.locator(".error-alert").count() >= 1
        page.close()
        ctx.close()

    def test_login_success_redirects(self, pw_browser, auth_live_server):
        """Valid credentials redirect to main app (/).

        Note: We use a fresh context so we don't interfere with pw_auth_page.
        We only check the redirect, not the full Shiny app load (WS limitation).
        """
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        page.goto(f"{auth_live_server}/login", wait_until="domcontentloaded", timeout=15000)
        page.locator("#username").fill("admin")
        page.locator("#password").fill("testpass")
        # The form POST triggers a 302 redirect to /; wait for navigation
        with page.expect_navigation(timeout=15000):
            page.locator("button[type='submit']").click()
        # Should redirect away from /login
        assert "/login" not in page.url
        page.close()
        ctx.close()

    def test_unauthenticated_redirects_to_login(self, pw_browser, auth_live_server):
        """Accessing / without session redirects to /login."""
        ctx = pw_browser.new_context()
        page = ctx.new_page()
        page.goto(f"{auth_live_server}/", wait_until="domcontentloaded", timeout=15000)
        assert "/login" in page.url
        page.close()
        ctx.close()


class TestAuthenticatedApp:
    """Tests that the authenticated app works after login."""

    def test_main_navbar_visible(self, pw_auth_page):
        """After login, main navbar is visible."""
        assert pw_auth_page.locator("#sf-sidebar").count() == 1

    def test_logout_button_visible(self, pw_auth_page):
        """Logout button is visible in the navbar."""
        assert pw_auth_page.locator("#logout-btn").count() == 1


class TestAdminPanel:
    """Tests for admin user management in server mode."""

    def test_admin_user_table_shows_admin(self, pw_auth_page):
        """Admin tab lists the seeded admin user."""
        _switch_tab(pw_auth_page, "Admin")
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

        # Fill form. Email is required for user/admin roles per recent
        # validation hardening — supply one to avoid creation failure.
        pw_auth_page.locator("#admin-new_username").fill("testuser")
        pw_auth_page.locator("#admin-new_password").fill("testpass123")
        # Form validation requires a "." after "@" — localhost alone fails.
        pw_auth_page.locator("#admin-new_email").fill("testuser@example.com")
        pw_auth_page.wait_for_timeout(300)

        # Submit via the confirm button
        pw_auth_page.locator("#admin-confirm_create_user").click(force=True)
        pw_auth_page.wait_for_timeout(2000)

        # User should now appear in the table
        _dismiss_modals(pw_auth_page)
        assert pw_auth_page.locator("text=testuser").count() >= 1

    def test_admin_user_has_action_buttons(self, pw_auth_page):
        """Action buttons (Reset PW, Toggle) exist for users."""
        _switch_tab(pw_auth_page, "Admin")
        pw_auth_page.wait_for_timeout(500)
        # Look for any reset password link
        reset_links = pw_auth_page.locator("[id^='admin-reset_pw_']")
        assert reset_links.count() >= 1

    def test_admin_active_badges_visible(self, pw_auth_page):
        """Active/role badges are visible in the admin table."""
        _switch_tab(pw_auth_page, "Admin")
        pw_auth_page.wait_for_timeout(500)
        badges = pw_auth_page.locator(
            ".badge.bg-success, .badge.bg-secondary, .badge.bg-danger, .badge.bg-primary"
        )
        assert badges.count() >= 1


class TestSharingUI:
    """Tests for the project sharing modal (requires a project to exist)."""

    def _ensure_project(self, pw_auth_page):
        """Create a project if none exists, return to Dashboard."""
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(1000)

        # Check if any project links exist
        project_links = pw_auth_page.locator("[id^='home-project_']")
        if project_links.count() == 0:
            # Create a new project
            pw_auth_page.locator("#home-new_project_btn").click(force=True)
            pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
            pw_auth_page.locator("#home-project_name").fill("TestProject")
            pw_auth_page.locator("#home-create_project_btn").click(force=True)
            pw_auth_page.wait_for_timeout(3000)
            _dismiss_modals(pw_auth_page)

    def test_share_button_visible_for_owner(self, pw_auth_page):
        """Share button appears on owned projects."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(1000)
        share_btns = pw_auth_page.locator("[id^='home-share_']")
        assert share_btns.count() >= 1

    def test_share_modal_opens(self, pw_auth_page):
        """Clicking Share opens the sharing modal."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(1000)
        pw_auth_page.locator("[id^='home-share_']").first.click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
        # Modal should mention "Share" in title
        modal_text = pw_auth_page.locator(".modal.show").inner_text()
        assert "Share" in modal_text or "Current Access" in modal_text or "Add User" in modal_text
        _dismiss_modals(pw_auth_page)

    def test_share_modal_has_role_selector(self, pw_auth_page):
        """Share modal has a role selector (requires testuser from TestAdminPanel)."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(1000)
        pw_auth_page.locator("[id^='home-share_']").first.click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
        pw_auth_page.wait_for_timeout(500)
        # Role selector is rendered when shareable users exist
        role_select = pw_auth_page.locator("#home-share_role")
        assert role_select.count() >= 1
        _dismiss_modals(pw_auth_page)

    def test_share_modal_has_user_selector(self, pw_auth_page):
        """Share modal has a user dropdown (requires testuser from TestAdminPanel)."""
        self._ensure_project(pw_auth_page)
        _switch_tab(pw_auth_page, "Dashboard")
        pw_auth_page.wait_for_timeout(1000)
        pw_auth_page.locator("[id^='home-share_']").first.click(force=True)
        pw_auth_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
        pw_auth_page.wait_for_timeout(500)
        user_select = pw_auth_page.locator("#home-share_user_id")
        assert user_select.count() >= 1
        _dismiss_modals(pw_auth_page)
