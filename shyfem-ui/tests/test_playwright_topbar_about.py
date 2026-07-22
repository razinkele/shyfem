"""Playwright tests for the topbar About / Changelog / Feedback modals.

Regression coverage for the About/Changelog blank-page bug: these outputs
went blank whenever the reactive flush loop was starved (run.py's
_auto_refresh self-invalidation), so asserting real markdown content here
also guards the session's first flush completing at all.
"""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]


def _open_modal(pw_page, button_id):
    _dismiss_modals(pw_page)
    pw_page.locator(f"#{button_id}").click()
    modal = pw_page.locator(".modal.show")
    modal.wait_for(state="visible", timeout=10000)
    return modal


def _close_modal(pw_page):
    pw_page.locator(".modal.show .modal-footer button").click()
    pw_page.locator(".modal.show").wait_for(state="hidden", timeout=5000)


class TestTopbarAboutCluster:
    def test_topbar_buttons_present(self, pw_page):
        for button_id in ("about-show_about", "about-show_changelog", "about-show_feedback"):
            assert pw_page.locator(f"#{button_id}").count() == 1

    def test_about_modal_renders_readme(self, pw_page):
        modal = _open_modal(pw_page, "about-show_about")
        assert "About SHYFEM Workbench" in modal.locator(".modal-title").inner_text()
        body = modal.locator(".modal-body").inner_text()
        assert "SHYFEM" in body
        assert len(body) > 500, "README content missing from About modal"
        _close_modal(pw_page)

    def test_changelog_modal_renders_changelog(self, pw_page):
        modal = _open_modal(pw_page, "about-show_changelog")
        assert "Changelog" in modal.locator(".modal-title").inner_text()
        body = modal.locator(".modal-body").inner_text()
        assert len(body) > 500, "CHANGELOG content missing from Changelog modal"
        _close_modal(pw_page)

    def test_feedback_modal_submits(self, pw_page):
        modal = _open_modal(pw_page, "about-show_feedback")
        modal.locator("#about-fb_title").fill("E2E feedback title")
        modal.locator("#about-fb_desc").fill("E2E feedback description text.")
        modal.locator("#about-fb_submit").click()
        status = pw_page.locator("#about-fb_status")
        status.wait_for(state="visible", timeout=10000)
        assert "recorded" in status.inner_text()
        _close_modal(pw_page)
