"""Playwright tests for newer tabs: Tutorial, Files, Admin."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_TAB = ".sf-nav-item[data-nav='{name}']"


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
        assert "active" in (
            tab.get_attribute("class") or ""
        ), f"Tab '{tab_name}' did not become active"


class TestTutorialTab:
    """Tests for the Tutorial page rendering."""

    def test_tutorial_renders_heading(self, pw_page):
        _switch_tab(pw_page, "Tutorial")
        assert pw_page.locator("text=Tutorial Phases").count() >= 1

    def test_tutorial_has_progress_bar(self, pw_page):
        _switch_tab(pw_page, "Tutorial")
        progress = pw_page.locator("#tutorial-progress_bar")
        assert progress.count() >= 1

    def test_tutorial_has_phase_navigator(self, pw_page):
        _switch_tab(pw_page, "Tutorial")
        nav = pw_page.locator("#tutorial-phase_navigator")
        assert nav.count() >= 1


class TestFilesTab:
    """Tests for the Files page rendering (no active project)."""

    def test_files_renders_heading(self, pw_page):
        _switch_tab(pw_page, "Files")
        assert pw_page.locator("text=Project Files").count() >= 1

    def test_files_no_project_message(self, pw_page):
        """Without an active project, show guidance message."""
        _switch_tab(pw_page, "Files")
        assert pw_page.locator("text=No project selected").count() >= 1

    def test_files_no_storage_bar_without_project(self, pw_page):
        """Storage bar should not appear without an active project."""
        _switch_tab(pw_page, "Files")
        # Files content area should show "No project selected", not storage info
        files_content = pw_page.locator("#files-files_content")
        assert files_content.count() >= 1
        text = files_content.inner_text()
        assert "No project selected" in text


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
        summary = pw_page.locator("#admin-user_summary")
        assert summary.count() >= 1
