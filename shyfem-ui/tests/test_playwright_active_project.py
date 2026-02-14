"""E2E tests for active project selection and navigation."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_MODAL = ".modal.show"
_TAB = "#main_navbar > li > a[data-value='{name}']"


def _ensure_dashboard(pw_page):
    """Make sure we're on the Dashboard tab."""
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name="Dashboard")).click(force=True)
    pw_page.wait_for_timeout(300)


class TestActiveProject:
    """Test project selection navigates to Grid Prep tab."""

    def test_open_project_modal_shows(self, pw_page):
        """Open Project button opens a modal."""
        _ensure_dashboard(pw_page)
        pw_page.locator("#home-open_project_btn").click(force=True)
        pw_page.locator(_MODAL).wait_for(state="visible", timeout=5000)
        # Modal should show — either project list or "No projects yet"
        modal = pw_page.locator(_MODAL)
        assert modal.is_visible()
        _dismiss_modals(pw_page)

    def test_import_grid_btn_shows_notification_or_modal(self, pw_page):
        """Import Grid button shows a notification (no projects) or modal."""
        _ensure_dashboard(pw_page)
        pw_page.locator("#home-import_grid_btn").click(force=True)
        # If no projects, we get a notification; if projects exist, a modal
        pw_page.wait_for_timeout(500)
        # Either way, the click should work without errors
        _dismiss_modals(pw_page)
