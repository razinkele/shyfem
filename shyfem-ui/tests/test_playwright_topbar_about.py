"""Playwright tests for the topbar About / Changelog / Feedback modals.

Regression coverage for the About/Changelog blank-page bug: these outputs
went blank whenever the reactive flush loop was starved (run.py's
_auto_refresh self-invalidation), so asserting real markdown content here
also guards the session's first flush completing at all.

About and Changelog are dropdowns with separate SHYFEM (core) and
SHYFEM UI entries; each entry opens its own modal.
"""

import pytest
from playwright.sync_api import expect

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]


def _open_menu_modal(pw_page, toggle_id, item_id):
    """Open a topbar dropdown, click one of its entries, return the modal."""
    _dismiss_modals(pw_page)
    pw_page.locator(f"#{toggle_id}").click()
    item = pw_page.locator(f"#{item_id}")
    item.wait_for(state="visible", timeout=5000)
    item.click()
    modal = pw_page.locator(".modal.show")
    modal.wait_for(state="visible", timeout=10000)
    return modal


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
    def test_topbar_controls_present(self, pw_page):
        for dom_id in (
            "sf-about-menu",
            "sf-changelog-menu",
            "about-show_about_core",
            "about-show_about_ui",
            "about-show_changelog_core",
            "about-show_changelog_ui",
            "about-show_feedback",
        ):
            assert pw_page.locator(f"#{dom_id}").count() == 1

    def test_about_core_modal_renders_repo_readme(self, pw_page):
        modal = _open_menu_modal(pw_page, "sf-about-menu", "about-show_about_core")
        assert "About SHYFEM" in modal.locator(".modal-title").inner_text()
        body = modal.locator(".modal-body").inner_text()
        assert "SHYFEM" in body
        assert len(body) > 500, "repo README content missing from About SHYFEM modal"
        _close_modal(pw_page)

    def test_about_ui_modal_renders_ui_readme(self, pw_page):
        modal = _open_menu_modal(pw_page, "sf-about-menu", "about-show_about_ui")
        assert "About SHYFEM Workbench (UI)" in modal.locator(".modal-title").inner_text()
        body = modal.locator(".modal-body").inner_text()
        assert "SHYFEM UI" in body
        assert len(body) > 500, "UI README content missing from About SHYFEM UI modal"
        _close_modal(pw_page)

    def test_changelog_core_modal_filters_ui_sections(self, pw_page):
        modal = _open_menu_modal(pw_page, "sf-changelog-menu", "about-show_changelog_core")
        assert "Changelog — SHYFEM" in modal.locator(".modal-title").inner_text()
        body = modal.locator(".modal-body").inner_text()
        assert "8.2.0" in body
        assert "shyfem-ui 0." not in body, "UI sections leaked into the core changelog view"
        _close_modal(pw_page)

    def test_changelog_ui_modal_filters_core_sections(self, pw_page):
        modal = _open_menu_modal(pw_page, "sf-changelog-menu", "about-show_changelog_ui")
        assert "Changelog — SHYFEM UI" in modal.locator(".modal-title").inner_text()
        body = modal.locator(".modal-body").inner_text()
        assert "shyfem-ui 0." in body
        assert "[8.2.0]" not in body, "core sections leaked into the UI changelog view"
        _close_modal(pw_page)

    def test_feedback_modal_submits(self, pw_page):
        modal = _open_modal(pw_page, "about-show_feedback")
        modal.locator("#about-fb_title").fill("E2E feedback title")
        modal.locator("#about-fb_desc").fill("E2E feedback description text.")
        modal.locator("#about-fb_submit").click()
        # Auto-retrying: the element turns visible a beat before Shiny fills
        # its text, so wait_for(visible) + inner_text() raced (flaked in CI).
        expect(pw_page.locator("#about-fb_status")).to_contain_text("recorded", timeout=10000)
        _close_modal(pw_page)
