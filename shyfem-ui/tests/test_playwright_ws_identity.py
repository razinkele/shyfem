"""E2E tests for WS trusted-identity on the Home dashboard (Phase 4).

These exercise the *production* identity path end to end:

    login → GET /api/whoami mints a ws_token → JS setInputValue('_wsauth')
          → resolve_ws_user() → current_user() → home page guards

Two things are covered that unit tests cannot reach:

1.  Share-button visibility is gated by the WS-resolved identity — a viewer
    who can *see* a project but does not own it gets no Share button, while an
    admin does.
2.  The share/unshare mutation handlers re-check server-validated identity, so
    a viewer firing ``confirm_share_<pid>`` directly over the WebSocket (the
    button is only a visibility hint, the input is still live) is rejected with
    an error notification — no silent no-op, no privilege escalation.

The file is named ``test_playwright_*`` so it is excluded from the default
pytest run (see pyproject ``addopts``); run it explicitly with the other
Playwright suites.
"""

import pytest

from tests.conftest import _dismiss_modals, _login, _wait_hydrated

PROJECTS_LIST = "#home-projects_list"


@pytest.fixture(scope="module")
def pw_ws_admin_page(pw_browser, ws_identity_live_server):
    """A Playwright page logged into the seeded WS-identity server as admin.

    The admin owns both seeded projects, so it is the positive control for
    Share-button visibility. Module-scoped: shares one WS session across this
    file's admin tests (Shiny cannot reliably re-accept a WS after disconnect).
    """
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(15000)
    _login(page, ws_identity_live_server, "admin", "testpass")
    _wait_hydrated(page)
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()


def _project_pid(page, name: str):
    """Return the DB id of the project rendered with the given display name."""
    return page.evaluate(
        """(name) => {
            const links = Array.from(
                document.querySelectorAll("[id^='home-project_']"));
            const hit = links.find(e => e.textContent.trim() === name);
            if (!hit) return null;
            const m = hit.id.match(/^home-project_(\\d+)$/);
            return m ? parseInt(m[1], 10) : null;
        }""",
        name,
    )


def _wait_identity_resolved_for_viewer(page):
    """Block until the async WS identity has resolved for viewer1.

    On connect the dashboard first renders the unauthenticated view (recent
    projects, no per-user filter). Once ``_wsauth`` resolves, the list is
    re-filtered to projects viewer1 may see — ``Private`` (not shared with
    viewer1) disappears. Its absence is the observable proof that
    ``current_user()`` now returns the viewer, not None.
    """
    page.wait_for_function(
        """() => {
            const links = Array.from(
                document.querySelectorAll("#home-projects_list [id^='home-project_']"));
            if (links.length === 0) return false;
            const names = links.map(e => e.textContent.trim());
            return names.includes("Shared") && !names.includes("Private");
        }""",
        timeout=30000,
    )


class TestShareButtonVisibilityWSIdentity:
    def test_viewer_has_no_share_button_on_visible_project(self, pw_viewer_page):
        """viewer1 sees the Shared project but, not owning it, no Share button."""
        page = pw_viewer_page
        _wait_identity_resolved_for_viewer(page)

        container = page.locator(PROJECTS_LIST)
        assert container.get_by_text("Shared", exact=True).count() >= 1
        # Share action links are rendered as <a id="home-share_<pid>">.
        assert container.locator("a[id^='home-share_']").count() == 0

    def test_admin_sees_share_button(self, pw_ws_admin_page):
        """The admin owns both seeded projects, so the Share button is shown."""
        page = pw_ws_admin_page
        # The button only appears once the admin identity has resolved.
        page.wait_for_function(
            "() => document.querySelectorAll("
            "\"#home-projects_list a[id^='home-share_']\").length >= 1",
            timeout=30000,
        )
        assert page.locator(f"{PROJECTS_LIST} a[id^='home-share_']").count() >= 1


class TestShareHandlerWSAuthBypass:
    def test_viewer_cannot_share_via_direct_ws_input(self, pw_viewer_page):
        """A viewer firing confirm_share_<pid> over the WS is rejected.

        Reproduces the auth-bypass: the ``confirm_share_<pid>`` reactive input
        is live for any project the viewer can see, so visibility-gating the
        button is not a guard. The server-side check must reject the action and
        surface an error (not a silent no-op).
        """
        page = pw_viewer_page
        _wait_identity_resolved_for_viewer(page)

        pid = _project_pid(page, "Shared")
        assert pid is not None, "Shared project link not found for viewer1"

        # Fire the privileged mutation directly, bypassing the (absent) button.
        page.evaluate(
            """(pid) => {
                window.Shiny.setInputValue('home-share_user_id', '1',
                    {priority: 'event'});
                window.Shiny.setInputValue('home-share_role', 'editor',
                    {priority: 'event'});
                window.Shiny.setInputValue('home-confirm_share_' + pid,
                    Date.now(), {priority: 'event'});
            }""",
            pid,
        )

        # The guard must reject with an authorization error...
        err = page.locator(".shiny-notification-error")
        err.first.wait_for(state="visible", timeout=10000)
        assert "authorized" in err.first.inner_text().lower()

        # ...and must NOT report a successful share.
        assert (
            page.locator(".shiny-notification").get_by_text("User added", exact=False).count() == 0
        )
