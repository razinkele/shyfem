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

import json

import pytest

from tests._test_ws_identity_app import (
    DEMOTEE_PASSWORD,
    DEMOTEE_USERNAME,
    VIEWER_PASSWORD,
    VIEWER_USERNAME,
)
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

    On connect the dashboard renders fail-closed (no projects) until
    ``_wsauth`` resolves; then the list holds exactly the projects viewer1 may
    see — ``Shared`` but not ``Private``. That content is the observable proof
    that ``current_user()`` returns the viewer, not None.

    A non-admin lands on Tutorial with the Dashboard hidden, and Shiny does
    not re-render hidden outputs, so open the Dashboard (as a real viewer
    does) once the server reports identity resolved. Before the push waited
    for Shiny's init, these tests passed only when the token happened to
    arrive before the Dashboard was hidden.
    """
    page.wait_for_function(
        "() => !!document.getElementById('sf-ws-ready-marker')",
        timeout=30000,
    )
    page.evaluate("() => shyfemNavTo('Dashboard')")
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


@pytest.fixture(scope="module")
def pw_unresolved_identity_page(pw_browser, ws_identity_live_server):
    """A logged-in viewer whose ``_wsauth`` NEVER resolves.

    Simulates the production proxy admit path: the user authenticates over HTTP
    (so the page loads), but the WebSocket carries no identity (Shiny Server's
    internal WS does not forward cookies) and the ``_wsauth`` token is never
    pushed. Here we reproduce that by intercepting ``api/whoami`` and stripping
    ``ws_token``, so ``resolve_ws_user`` never runs and ``current_user()`` stays
    None in the WS scope. Server-mode write guards must then fail CLOSED — the
    one path unit tests cannot reach end to end.
    """
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(15000)

    def _strip_ws_token(route):
        resp = route.fetch()
        try:
            data = resp.json()
        except Exception:
            data = {}
        data.pop("ws_token", None)  # identity never resolves in the WS scope
        route.fulfill(status=resp.status, content_type="application/json", body=json.dumps(data))

    page.route("**/api/whoami", _strip_ws_token)
    _login(page, ws_identity_live_server, VIEWER_USERNAME, VIEWER_PASSWORD)
    _wait_hydrated(page)
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()


class TestUnresolvedIdentityFailsClosed:
    def test_unresolved_identity_cannot_save_physics(self, pw_unresolved_identity_page):
        """With no resolved WS identity (``_wsauth`` never pushed), a physics
        save fired directly over the WS is denied fail-CLOSED in server mode —
        editor_denied_reason's ``user is None`` branch, not the viewer/permission
        branch. Proves the gate denies the unresolved-identity admit path, not
        just resolved-but-unauthorized users."""
        page = pw_unresolved_identity_page

        # Clear any prior notifications so we observe only our save attempt.
        page.evaluate(
            "() => document.querySelectorAll('.shiny-notification').forEach(e => e.remove())"
        )
        # Fire the privileged save directly over the WS, bypassing the UI.
        page.evaluate(
            "() => window.Shiny.setInputValue("
            "'physics-save_btn', Date.now(), {priority: 'event'})"
        )

        err = page.locator(".shiny-notification-error")
        err.first.wait_for(state="visible", timeout=10000)
        txt = err.first.inner_text().lower()
        # The server-mode unresolved-identity branch of editor_denied_reason.
        assert "could not be verified" in txt
        # ...and definitely NOT a successful save.
        assert page.locator(".shiny-notification").get_by_text("Saved", exact=False).count() == 0


class TestWriteGuardWSAuthBypass:
    def test_viewer_cannot_save_physics_via_direct_ws_input(self, pw_viewer_page):
        """A viewer firing physics-save_btn over the WS is rejected.

        Per-page write guards must re-check server-validated identity, not just
        page/button visibility: the ``save_btn`` input is live for the whole
        session regardless of which tab is shown. viewer1 has only *viewer*
        access to ``Shared``, so ``editor_denied_reason`` denies the save with
        an error notification — proving the guard is the enforcement point and
        the fix is wired end-to-end through the real ``_wsauth`` identity path.
        """
        page = pw_viewer_page
        _wait_identity_resolved_for_viewer(page)

        pid = _project_pid(page, "Shared")
        assert pid is not None, "Shared project link not found for viewer1"

        # Activate Shared — viewer access is sufficient to OPEN it, so the
        # write handler then has a non-None active project to guard against.
        page.evaluate(
            "(pid) => window.Shiny.setInputValue("
            "'home-project_' + pid, Date.now(), {priority: 'event'})",
            pid,
        )
        # Wait until activation has taken effect server-side.
        page.wait_for_timeout(1500)

        # Clear notifications left over from prior tests (this page/session is
        # shared) so we observe only the response to our save attempt.
        page.evaluate(
            "() => document.querySelectorAll('.shiny-notification')" ".forEach(e => e.remove())"
        )

        # Fire the privileged save directly over the WS, bypassing the UI.
        page.evaluate(
            "() => window.Shiny.setInputValue("
            "'physics-save_btn', Date.now(), {priority: 'event'})"
        )

        # The guard must reject with an editor-permission error.
        err = page.locator(".shiny-notification-error")
        err.first.wait_for(state="visible", timeout=10000)
        txt = err.first.inner_text().lower()
        assert "permission denied" in txt and "editor" in txt


@pytest.fixture(scope="module")
def pw_demotee_page(pw_browser, ws_identity_live_server):
    """A Playwright page logged in as ``demotee`` (editor on Shared)."""
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.set_default_timeout(15000)
    _login(page, ws_identity_live_server, DEMOTEE_USERNAME, DEMOTEE_PASSWORD)
    _wait_hydrated(page)
    _dismiss_modals(page)
    yield page
    page.close()
    ctx.close()


class TestLiveIdentityRevocation:
    def test_deactivated_user_cannot_write_in_open_session(
        self, pw_demotee_page, ws_identity_db_path
    ):
        """An account deactivated while its WebSocket is open loses write
        access at the next action, not at the next reconnect (L31).

        The identity used to be resolved once when ``_wsauth`` arrived and
        then frozen, so a deactivated (or demoted, or logged-out) user kept
        their old rights for the life of the socket. With the fix,
        ``current_user()`` re-validates the token on every call, the
        deactivated account reads as None, and the server-mode write guard
        denies with its unresolved-identity message.
        """
        import sqlite3

        page = pw_demotee_page
        # Identity resolved as demotee: Shared listed, Private hidden.
        _wait_identity_resolved_for_viewer(page)
        pid = _project_pid(page, "Shared")
        assert pid is not None, "Shared project link not found for demotee"

        # Open Shared while still active, so the save below has a project
        # and, before the fix, would be allowed on demotee's editor share.
        page.evaluate(
            "(pid) => window.Shiny.setInputValue("
            "'home-project_' + pid, Date.now(), {priority: 'event'})",
            pid,
        )
        page.wait_for_timeout(1500)

        def _clear_notifications():
            page.evaluate(
                "() => document.querySelectorAll('.shiny-notification')" ".forEach(e => e.remove())"
            )

        def _fire_save():
            page.evaluate(
                "() => window.Shiny.setInputValue("
                "'physics-save_btn', Date.now(), {priority: 'event'})"
            )

        def _set_active(active: int) -> int:
            con = sqlite3.connect(str(ws_identity_db_path))
            try:
                n = con.execute(
                    "UPDATE users SET is_active = ? WHERE username = ?",
                    (active, DEMOTEE_USERNAME),
                ).rowcount
                con.commit()
            finally:
                con.close()
            return n

        # Positive control: while active, the save gets PAST the editor guard
        # and stops at the next check (empty STR path) -- a warning, not an
        # authorization error. The physics tab is not rendered here, so the
        # path input is set explicitly; unset, it silently ends the handler.
        page.evaluate(
            "() => window.Shiny.setInputValue('physics-str_path', '', {priority: 'event'})"
        )
        _clear_notifications()
        _fire_save()
        warn = page.locator(".shiny-notification-warning")
        warn.first.wait_for(state="visible", timeout=10000)
        assert "no file path" in warn.first.inner_text().lower()
        assert page.locator(".shiny-notification-error").count() == 0

        # Deactivate the account in the server's DB, as the admin page does.
        assert _set_active(0) == 1
        try:
            _clear_notifications()
            _fire_save()
            err = page.locator(".shiny-notification-error")
            err.first.wait_for(state="visible", timeout=10000)
            assert "could not be verified" in err.first.inner_text().lower()
            assert page.locator(".shiny-notification-warning").count() == 0
        finally:
            _set_active(1)  # session-scoped server: leave the account usable

    def test_dashboard_list_drops_projects_after_deactivation(
        self, pw_demotee_page, ws_identity_db_path
    ):
        """The project list must follow the live identity without a reload.

        #99 made every *decision* re-validate, but ``projects_list`` only
        depended on the ``projects`` value, which was filled once: a
        deactivated user kept seeing (and being offered actions on) their
        projects until something else refreshed the page.
        """
        import sqlite3

        page = pw_demotee_page
        _wait_identity_resolved_for_viewer(page)
        page.wait_for_function(
            "() => [...document.querySelectorAll(\"#home-projects_list [id^='home-project_']\")]"
            ".some(e => e.textContent.trim() === 'Shared')",
            timeout=15000,
        )

        def _set_active(active: int) -> None:
            con = sqlite3.connect(str(ws_identity_db_path))
            try:
                con.execute(
                    "UPDATE users SET is_active = ? WHERE username = ?",
                    (active, DEMOTEE_USERNAME),
                )
                con.commit()
            finally:
                con.close()

        _set_active(0)
        try:
            # Fail-closed: an unresolved identity in server mode lists nothing.
            page.wait_for_function(
                "() => document.querySelectorAll(\"#home-projects_list [id^='home-project_']\").length === 0",
                timeout=30000,
            )
        finally:
            _set_active(1)
        # And it comes back once the account is active again.
        page.wait_for_function(
            "() => [...document.querySelectorAll(\"#home-projects_list [id^='home-project_']\")]"
            ".some(e => e.textContent.trim() === 'Shared')",
            timeout=30000,
        )


# Holds back Shiny's client ``initialize()`` -- the step that defines
# ``Shiny.setInputValue`` -- so ``api/whoami`` is guaranteed to answer first.
# Unforced, the two land within a millisecond of each other (measured
# 2026-10-16: whoami JSON at 570 ms, setInputValue at 570 ms), which is the
# order a slow CI runner sometimes flipped.
_DELAY_SHINY_INIT = """
(() => {
  let shiny;
  Object.defineProperty(window, 'Shiny', {
    configurable: true,
    get() { return shiny; },
    set(v) {
      shiny = v;
      if (v && typeof v.initialize === 'function' && !v.__sfDelayed) {
        v.__sfDelayed = true;
        const init = v.initialize.bind(v);
        v.initialize = () => new Promise((r) => setTimeout(r, 1500)).then(init);
      }
    },
  });
})();
"""


class TestIdentityPushSurvivesLateShinyInit:
    def test_identity_resolves_when_whoami_beats_shiny_init(
        self, pw_browser, ws_identity_live_server
    ):
        """The ``_wsauth`` push must wait for Shiny, not be skipped.

        whoami is fetched at DOMContentLoaded; Shiny defines ``setInputValue``
        a timer tick after jQuery-ready. When whoami won that race, the old
        ``if (window.Shiny && window.Shiny.setInputValue)`` guard dropped the
        token silently, ``current_user()`` stayed None for the whole session,
        and the dashboard rendered fail-closed: no projects, no Share button
        (the intermittent ``test_admin_sees_share_button`` CI failure).
        """
        ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(_DELAY_SHINY_INIT)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        try:
            _login(page, ws_identity_live_server, "admin", "testpass")
            _wait_hydrated(page)
            page.wait_for_function(
                "() => !!document.getElementById('sf-ws-ready-marker')",
                timeout=15000,
            )
            page.wait_for_function(
                "() => document.querySelectorAll("
                "\"#home-projects_list a[id^='home-share_']\").length >= 1",
                timeout=15000,
            )
        finally:
            page.close()
            ctx.close()

    def test_viewer_hydrates_when_whoami_beats_shiny_init(
        self, pw_browser, ws_identity_live_server
    ):
        """A non-admin whose Dashboard is hidden before Shiny's first flush.

        whoami's callback sends non-admins to Tutorial; when it runs before
        Shiny initialises, the Dashboard is hidden at bind time and its
        outputs (the hydration badge among them) never render until the user
        opens it. Hydration must not depend on a Dashboard output -- this is
        the ordering that took down every viewer fixture in CI.
        """
        ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(_DELAY_SHINY_INIT)
        page = ctx.new_page()
        page.set_default_timeout(15000)
        try:
            _login(page, ws_identity_live_server, VIEWER_USERNAME, VIEWER_PASSWORD)
            _wait_hydrated(page)
            _wait_identity_resolved_for_viewer(page)
        finally:
            page.close()
            ctx.close()
