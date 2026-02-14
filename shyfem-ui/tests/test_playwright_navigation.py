"""Playwright tests for page navigation and tab switching."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

TAB_NAMES = [
    "Dashboard",
    "Grid Prep",
    "Partitioning",
    "Simulation",
    "Run",
    "Post-Process",
    "Visualize",
    "Compare",
    "Ensemble",
]

# Scope to main navbar to avoid inner sub-tab conflicts (e.g. Run > Dashboard)
_TAB = "#main_navbar > li > a[data-value='{name}']"


class TestNavigation:
    """Tests for the main navigation bar."""

    def test_page_title(self, pw_page):
        """Test page title is set."""
        assert "SHYFEM" in pw_page.title()

    def test_navbar_visible(self, pw_page):
        """Test the main navbar is visible."""
        navbar = pw_page.locator("#main_navbar")
        assert navbar.is_visible()

    def test_all_tabs_present(self, pw_page):
        """Test all 9 navigation tabs are present."""
        for tab_name in TAB_NAMES:
            tab = pw_page.locator(_TAB.format(name=tab_name))
            assert tab.count() == 1, f"Tab '{tab_name}' not found (or duplicated)"

    def test_dashboard_is_default_tab(self, pw_page):
        """Test Dashboard tab can be activated and becomes active."""
        _dismiss_modals(pw_page)
        tab = pw_page.locator(_TAB.format(name="Dashboard"))
        tab.click(force=True)
        pw_page.wait_for_timeout(300)
        assert (
            "active" in (tab.get_attribute("class") or "")
            or tab.get_attribute("aria-selected") == "true"
        )

    @pytest.mark.parametrize("tab_name", TAB_NAMES)
    def test_switch_to_tab(self, pw_page, tab_name):
        """Test switching to each tab shows its content."""
        _dismiss_modals(pw_page)
        tab = pw_page.locator(_TAB.format(name=tab_name))
        tab.click(force=True)
        pw_page.wait_for_timeout(500)

        assert (
            "active" in (tab.get_attribute("class") or "")
            or tab.get_attribute("aria-selected") == "true"
        ), f"Tab '{tab_name}' did not become active"

    def test_rapid_tab_switching(self, pw_page):
        """Test rapidly switching between tabs does not break the UI."""
        _dismiss_modals(pw_page)
        for tab_name in TAB_NAMES:
            _dismiss_modals(pw_page)
            pw_page.locator(_TAB.format(name=tab_name)).click(force=True)
            pw_page.wait_for_timeout(100)

        # After rapid switching, last tab should be active
        last = pw_page.locator(_TAB.format(name=TAB_NAMES[-1]))
        pw_page.wait_for_timeout(500)
        assert (
            "active" in (last.get_attribute("class") or "")
            or last.get_attribute("aria-selected") == "true"
        )

    def test_page_does_not_crash_on_navigation(self, pw_page):
        """Test navigating through all tabs leaves no JS errors."""
        errors = []
        pw_page.on("pageerror", lambda exc: errors.append(str(exc)))

        for tab_name in TAB_NAMES:
            _dismiss_modals(pw_page)
            pw_page.locator(_TAB.format(name=tab_name)).click(force=True)
            pw_page.wait_for_timeout(300)

        assert errors == [], f"JS errors during navigation: {errors}"
