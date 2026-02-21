"""Playwright tests for authentication and server-mode features."""

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
        assert page.locator(".alert-danger").count() >= 1
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
        assert pw_auth_page.locator("#main_navbar").count() == 1

    def test_logout_button_visible(self, pw_auth_page):
        """Logout button is visible in the navbar."""
        assert pw_auth_page.locator("#logout-btn").count() == 1
