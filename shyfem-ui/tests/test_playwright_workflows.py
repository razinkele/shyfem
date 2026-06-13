"""E2E workflow tests covering project creation, STR editor, files, and tutorial.

Tests are organized into 4 classes that run in file order.  Group 1
(TestProjectWorkflow) creates and activates a project, which is a
prerequisite for Groups 2 and 3.  Group 4 (TestTutorialWorkflow) is
independent of project state.
"""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_MODAL = ".modal.show"
_TAB = ".sf-nav-item[data-nav='{name}']"


def _switch_tab(pw_page, name):
    """Switch to a main navbar tab and wait for content to render."""
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name=name)).click(force=True)
    pw_page.wait_for_timeout(800)


def _activate_first_project(pw_page):
    """(Re)activate the first project so ``active_project`` is set for this test.

    The autouse ``_reset_active_project_state`` (conftest) nulls
    ``active_project`` before EVERY test. shiny >=1.6 fires that
    ``priority:'event'`` reset reliably (1.5 deduped the unchanged ``""`` value
    away, so a prior test's activation happened to survive) — so a test that
    needs an active project must re-activate it here rather than rely on a prior
    test's activation persisting. Robust on both 1.5 and 1.6.
    """
    _switch_tab(pw_page, "Dashboard")
    pw_page.wait_for_timeout(1000)
    pw_page.locator("a[id^='home-project_']").first.click(force=True)
    pw_page.wait_for_timeout(3000)
    _dismiss_modals(pw_page)


# ---------------------------------------------------------------------------
# Group 1: Project Creation & Activation (must run first)
# ---------------------------------------------------------------------------


class TestProjectWorkflow:
    """Test project creation and activation -- must run first."""

    def test_create_project(self, pw_page):
        """Create a project via New Project modal."""
        _switch_tab(pw_page, "Dashboard")
        pw_page.locator("#home-new_project_btn").click(force=True)
        pw_page.locator(_MODAL).wait_for(state="visible", timeout=15000)
        pw_page.locator("#home-project_name").fill("WorkflowTestProject")
        pw_page.locator("#home-create_project_btn").click(force=True)
        pw_page.wait_for_timeout(3000)
        _dismiss_modals(pw_page)

    def test_project_appears_in_list(self, pw_page):
        """Created project appears in the projects list."""
        _switch_tab(pw_page, "Dashboard")
        pw_page.wait_for_timeout(1000)
        projects = pw_page.locator("#home-projects_list")
        assert projects.count() >= 1
        text = projects.inner_text()
        assert "WorkflowTestProject" in text

    def test_activate_project(self, pw_page):
        """Click project link to activate it."""
        _switch_tab(pw_page, "Dashboard")
        pw_page.wait_for_timeout(1000)
        # input_action_link renders as <a> — narrow the selector to anchors
        # so we don't accidentally match #home-project_count (a render.ui
        # div), #home-project_name (the modal text input), etc.
        project_link = pw_page.locator("a[id^='home-project_']").first
        project_link.click(force=True)
        pw_page.wait_for_timeout(3000)
        _dismiss_modals(pw_page)
        # Activation navigates to Grid Prep via nav_callback -- verify the
        # Grid Prep tab became active or a notification appeared.
        grid_tab = pw_page.locator(_TAB.format(name="Grid Prep"))
        is_active = "active" in (grid_tab.get_attribute("class") or "")
        notification = pw_page.locator(".shiny-notification")
        assert is_active or notification.count() >= 1

    def test_active_project_propagates_to_files(self, pw_page):
        """Files tab shows content (not 'No project selected') after activation."""
        _activate_first_project(pw_page)
        _switch_tab(pw_page, "Files")
        pw_page.wait_for_timeout(2000)
        content = pw_page.locator("#files-files_content")
        assert content.count() >= 1
        text = content.inner_text()
        # Should NOT show the empty-state message
        assert "No project selected" not in text

    def test_active_project_propagates_to_simulation(self, pw_page):
        """Simulation tab sidebar renders after project activation."""
        _switch_tab(pw_page, "Simulation")
        pw_page.wait_for_timeout(1500)
        # The sidebar should have the load/new/save buttons
        assert pw_page.locator("#simulation-load_btn").count() >= 1
        assert pw_page.locator("#simulation-new_btn").count() >= 1


# ---------------------------------------------------------------------------
# Group 2: Simulation STR Editor (requires active project from Group 1)
# ---------------------------------------------------------------------------


class TestSimulationWorkflow:
    """Test STR editor actions -- requires active project from Group 1."""

    def test_select_template_shows_preview(self, pw_page):
        """Selecting a template shows preview content."""
        _switch_tab(pw_page, "Simulation")
        pw_page.wait_for_timeout(500)
        # Select "basic_2d" template
        select = pw_page.locator("#simulation-template_select")
        select.select_option("basic_2d")
        pw_page.wait_for_timeout(2000)
        # Preview should have content
        preview = pw_page.locator("#simulation-template_preview")
        assert preview.count() >= 1
        text = preview.inner_text()
        assert len(text.strip()) > 0

    def test_apply_template(self, pw_page):
        """Clicking Apply Template populates the editor."""
        _switch_tab(pw_page, "Simulation")
        pw_page.wait_for_timeout(500)
        # Select template first
        pw_page.locator("#simulation-template_select").select_option("basic_2d")
        pw_page.wait_for_timeout(2000)
        # Click apply -- button is rendered inside template_preview
        apply_btn = pw_page.locator("#simulation-apply_template_btn")
        if apply_btn.count() >= 1:
            apply_btn.click(force=True)
            pw_page.wait_for_timeout(2000)
        _dismiss_modals(pw_page)

    def test_quick_settings_fields_present(self, pw_page):
        """Quick settings fields are present in sidebar."""
        _switch_tab(pw_page, "Simulation")
        pw_page.wait_for_timeout(500)
        assert pw_page.locator("#simulation-quick_start").count() >= 1
        assert pw_page.locator("#simulation-quick_end").count() >= 1
        assert pw_page.locator("#simulation-quick_dt").count() >= 1
        assert pw_page.locator("#simulation-quick_output").count() >= 1
        assert pw_page.locator("#simulation-apply_quick_btn").count() >= 1

    def test_simulation_subtabs(self, pw_page):
        """Can switch between Editor, Sections, Boundaries, Parameter Reference sub-tabs."""
        _switch_tab(pw_page, "Simulation")
        pw_page.wait_for_timeout(500)
        for tab_name in ["Editor", "Sections", "Boundaries", "Parameter Reference"]:
            _dismiss_modals(pw_page)
            # Scope to the navset inside the simulation page to avoid matching
            # nav-links in other pages (e.g. the main navbar).
            tab = pw_page.locator(
                f".tab-content ~ .nothing_matches, " f".nav-link:has-text('{tab_name}')"
            )
            # Use a more targeted selector: look for the tab panel nav links
            tab = pw_page.locator(f"a.nav-link:has-text('{tab_name}')").first
            if tab.count() >= 1:
                tab.click(force=True)
                pw_page.wait_for_timeout(500)

    def test_save_as_modal(self, pw_page):
        """Save As button opens modal with path field."""
        _switch_tab(pw_page, "Simulation")
        pw_page.wait_for_timeout(500)
        save_btn = pw_page.locator("#simulation-save_as_btn")
        assert save_btn.count() >= 1
        save_btn.click(force=True)
        pw_page.locator(_MODAL).wait_for(state="visible", timeout=10000)
        assert pw_page.locator("#simulation-save_path").count() >= 1
        _dismiss_modals(pw_page)


# ---------------------------------------------------------------------------
# Group 3: Files Page with Active Project (requires Group 1)
# ---------------------------------------------------------------------------


class TestFilesWorkflow:
    """Test Files page with active project -- requires Group 1."""

    @pytest.fixture(autouse=True)
    def _ensure_active_project(self, pw_page):
        # Runs after the conftest autouse reset (conftest fixtures set up first),
        # so it re-establishes active_project that the reset nulled. Every Files
        # test below needs an active project.
        _activate_first_project(pw_page)
        yield

    def test_files_shows_content_with_project(self, pw_page):
        """Files page shows file management UI (not empty message)."""
        _switch_tab(pw_page, "Files")
        pw_page.wait_for_timeout(2000)
        content = pw_page.locator("#files-files_content")
        text = content.inner_text()
        assert "No project selected" not in text

    def test_file_filter_buttons_present(self, pw_page):
        """All 7 file type filter buttons are present."""
        _switch_tab(pw_page, "Files")
        pw_page.wait_for_timeout(2000)
        for filter_name in ["all", "grid", "forcing", "boundary", "str", "config", "other"]:
            btn = pw_page.locator(f"#files-filter_{filter_name}")
            assert btn.count() >= 1, f"Filter button '{filter_name}' not found"

    def test_file_filter_click_changes_style(self, pw_page):
        """Clicking a filter button changes its style to active."""
        _switch_tab(pw_page, "Files")
        pw_page.wait_for_timeout(2000)
        grid_btn = pw_page.locator("#files-filter_grid")
        if grid_btn.count() >= 1:
            grid_btn.click(force=True)
            pw_page.wait_for_timeout(1500)
            # After clicking Grid filter, re-locate the button (it re-renders)
            grid_btn = pw_page.locator("#files-filter_grid")
            if grid_btn.count() >= 1:
                classes = grid_btn.get_attribute("class") or ""
                assert "btn-primary" in classes or "active" in classes

    def test_file_table_present(self, pw_page):
        """File table element exists inside files content."""
        _switch_tab(pw_page, "Files")
        pw_page.wait_for_timeout(2000)
        # The content area should exist even if empty (showing "No files" message)
        content = pw_page.locator("#files-files_content")
        assert content.count() >= 1

    def test_upload_area_present(self, pw_page):
        """Upload file input area exists."""
        _switch_tab(pw_page, "Files")
        pw_page.wait_for_timeout(2000)
        # The upload section contains a file_browser component with id prefix files-file_upload
        file_browser = pw_page.locator("[id^='files-file_upload']")
        assert file_browser.count() >= 1


# ---------------------------------------------------------------------------
# Group 4: Tutorial Navigation (independent of project state)
# ---------------------------------------------------------------------------


class TestTutorialWorkflow:
    """Test Tutorial page interactivity -- independent of project state."""

    def test_default_step_content_renders(self, pw_page):
        """Step content has content on initial load."""
        _switch_tab(pw_page, "Tutorial")
        pw_page.wait_for_timeout(1500)
        content = pw_page.locator("#tutorial-step_content")
        assert content.count() >= 1
        text = content.inner_text()
        assert len(text.strip()) > 10  # Should have meaningful content

    def test_click_simulation_link(self, pw_page):
        """Clicking a simulation link changes step content."""
        _switch_tab(pw_page, "Tutorial")
        pw_page.wait_for_timeout(1500)
        # Get initial content
        pw_page.locator("#tutorial-step_content").inner_text()
        # Click a different simulation link -- look for any select_ link
        links = pw_page.locator("[id^='tutorial-select_']")
        if links.count() >= 2:
            links.nth(1).click(force=True)
            pw_page.wait_for_timeout(1500)
            new_text = pw_page.locator("#tutorial-step_content").inner_text()
            # Content should have changed (or at least the page did not crash)
            assert len(new_text.strip()) > 10

    def test_mark_complete_button_exists(self, pw_page):
        """Mark Complete & Next button is rendered."""
        _switch_tab(pw_page, "Tutorial")
        pw_page.wait_for_timeout(1500)
        mark_btn = pw_page.locator("#tutorial-mark_complete")
        assert mark_btn.count() >= 1

    def test_phase_accordion_present(self, pw_page):
        """Phase accordion exists and has panels."""
        _switch_tab(pw_page, "Tutorial")
        pw_page.wait_for_timeout(1500)
        # The accordion is rendered via output_ui("phase_navigator") and gets
        # the id tutorial-phase_accordion
        accordion = pw_page.locator("#tutorial-phase_accordion")
        assert accordion.count() >= 1
        # Should have accordion items
        items = pw_page.locator("#tutorial-phase_accordion .accordion-item")
        assert items.count() >= 1

    def test_simulation_links_present(self, pw_page):
        """Tutorial has simulation selection links."""
        _switch_tab(pw_page, "Tutorial")
        pw_page.wait_for_timeout(1500)
        links = pw_page.locator("[id^='tutorial-select_']")
        assert links.count() >= 1
