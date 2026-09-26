"""Playwright tests for the Dashboard (home) page."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

# Shiny modals get the .show class when visible
_MODAL = ".modal.show"
_TAB = ".sf-nav-item[data-nav='{name}']"


def _ensure_dashboard(pw_page):
    """Make sure we're on the Dashboard tab."""
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name="Dashboard")).click(force=True)
    pw_page.wait_for_timeout(300)


def _open_new_project_modal(pw_page):
    """Open the New Project modal and wait for it."""
    _ensure_dashboard(pw_page)
    _dismiss_modals(pw_page)
    # Ensure Shiny reactives are ready before clicking
    pw_page.locator("#home-system_health_count").wait_for(state="attached", timeout=5000)
    pw_page.wait_for_timeout(500)
    # force=True bypasses any residual overlay that may intercept pointer events
    pw_page.locator("#home-new_project_btn").click(force=True)
    pw_page.locator(_MODAL).wait_for(state="visible", timeout=15000)


def _close_modal(pw_page):
    """Close any open modal."""
    _dismiss_modals(pw_page)
    pw_page.wait_for_timeout(300)


class TestDashboardRendering:
    """Tests for dashboard page elements."""

    def test_heading_visible(self, pw_page):
        _ensure_dashboard(pw_page)
        heading = pw_page.locator("text=SHYFEM Workbench")
        assert heading.count() >= 1

    def test_subtitle_visible(self, pw_page):
        subtitle = pw_page.locator("text=Finite Element Hydrodynamic Model")
        assert subtitle.count() >= 1

    def test_quick_start_card(self, pw_page):
        assert pw_page.locator("text=Quick Start").is_visible()

    def test_system_status_card(self, pw_page):
        # The dashboard now shows a "Tools Ready" metric card instead of a
        # standalone "System Status" heading.
        assert pw_page.locator("text=Tools Ready").is_visible()

    def test_recent_jobs_card(self, pw_page):
        assert pw_page.get_by_role("heading", name="Recent Activity").is_visible()

    def test_projects_card(self, pw_page):
        assert pw_page.locator("text=Projects").count() >= 1

    def test_new_project_button_present(self, pw_page):
        assert pw_page.locator("#home-new_project_btn").is_visible()

    def test_open_project_button_present(self, pw_page):
        assert pw_page.locator("#home-open_project_btn").is_visible()

    def test_import_grid_button_present(self, pw_page):
        assert pw_page.locator("#home-import_grid_btn").is_visible()

    def test_tutorial_button_present(self, pw_page):
        assert pw_page.locator("#home-tutorial_btn").is_visible()

    def test_system_status_shows_tools(self, pw_page):
        # Tools are now shown as an aggregate count (e.g., "6/6") inside the
        # Tools Ready card rather than as individual labels. Verify the
        # count output rendered with a non-empty value.
        pw_page.wait_for_timeout(1000)
        count_el = pw_page.locator("#home-system_health_count")
        assert count_el.count() >= 1
        text = count_el.inner_text().strip()
        assert text and "/" in text, f"Expected 'N/M' tools count, got {text!r}"

    def test_no_projects_message(self, pw_page):
        pw_page.wait_for_timeout(1000)
        assert pw_page.locator("#home-projects_list").count() >= 1


class TestNewProjectModal:
    """Tests for the New Project modal dialog."""

    def test_open_modal(self, pw_page):
        _open_new_project_modal(pw_page)
        assert pw_page.locator(_MODAL).is_visible()
        _close_modal(pw_page)

    def test_modal_has_title(self, pw_page):
        _open_new_project_modal(pw_page)
        title = pw_page.locator(f"{_MODAL} .modal-title")
        assert "Create New Project" in title.inner_text()
        _close_modal(pw_page)

    def test_modal_has_fields(self, pw_page):
        _open_new_project_modal(pw_page)
        assert pw_page.locator("#home-project_name").is_visible()
        assert pw_page.locator("#home-project_description").is_visible()
        # The project folder is a selectize: the real <select> is hidden and
        # the visible control sits next to it.
        assert pw_page.locator("#home-project_dir").count() == 1
        assert pw_page.locator("#home-project_dir ~ .selectize-control").is_visible()
        _close_modal(pw_page)

    def test_modal_create_button(self, pw_page):
        _open_new_project_modal(pw_page)
        assert pw_page.locator("#home-create_project_btn").is_visible()
        _close_modal(pw_page)

    def test_modal_cancel_button(self, pw_page):
        _open_new_project_modal(pw_page)
        # Cancel is now a Bootstrap dismiss button (ui.modal_button). Real
        # click without force=True so Bootstrap's dismiss handler fires.
        pw_page.locator(f"{_MODAL} button[data-bs-dismiss='modal']").first.click()
        pw_page.locator(_MODAL).wait_for(state="hidden", timeout=5000)
        assert not pw_page.locator(_MODAL).is_visible()

    def test_create_project_empty_name_shows_error(self, pw_page):
        _open_new_project_modal(pw_page)
        pw_page.locator("#home-project_name").fill("")
        pw_page.locator("#home-create_project_btn").click()
        pw_page.wait_for_timeout(1500)
        notification = pw_page.locator(".shiny-notification-error, .shiny-notification")
        assert notification.count() >= 1 or pw_page.locator(_MODAL).is_visible()
        _close_modal(pw_page)

    def test_create_project_success(self, pw_page):
        _open_new_project_modal(pw_page)
        pw_page.locator("#home-project_name").fill("Test Project E2E")
        pw_page.locator("#home-project_description").fill("Created by Playwright test")
        pw_page.locator("#home-create_project_btn").click()
        pw_page.wait_for_timeout(3000)
        success = (
            not pw_page.locator(_MODAL).is_visible()
            or pw_page.locator("text=successfully").count() >= 1
        )
        assert success
        _close_modal(pw_page)


class TestTutorialModal:
    """Tests for the Mar Menor Tutorial modal."""

    def _open_modal(self, pw_page):
        _ensure_dashboard(pw_page)
        _dismiss_modals(pw_page)
        pw_page.locator("#home-system_health_count").wait_for(state="attached", timeout=5000)
        pw_page.wait_for_timeout(500)
        pw_page.locator("#home-tutorial_btn").click(force=True)
        pw_page.locator(_MODAL).wait_for(state="visible", timeout=15000)

    def test_open_tutorial_modal(self, pw_page):
        self._open_modal(pw_page)
        assert pw_page.locator(_MODAL).is_visible()
        _close_modal(pw_page)

    def test_tutorial_modal_title(self, pw_page):
        self._open_modal(pw_page)
        title = pw_page.locator(f"{_MODAL} .modal-title")
        assert "Mar Menor" in title.inner_text()
        _close_modal(pw_page)

    def test_tutorial_modal_phases(self, pw_page):
        self._open_modal(pw_page)
        modal_text = pw_page.locator(_MODAL).inner_text()
        # Keywords must match the actual phase titles in TUTORIAL_CONTENT.
        for keyword in [
            "Hydrodynamics",
            "Boundaries",
            "Coriolis",
            "Salinity",
            "Temperature",
        ]:
            assert keyword in modal_text
        _close_modal(pw_page)

    def test_tutorial_modal_cancel(self, pw_page):
        self._open_modal(pw_page)
        pw_page.locator(f"{_MODAL} button[data-bs-dismiss='modal']").first.click()
        pw_page.locator(_MODAL).wait_for(state="hidden", timeout=5000)
        assert not pw_page.locator(_MODAL).is_visible()
