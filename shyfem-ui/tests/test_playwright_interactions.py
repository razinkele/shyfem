"""Playwright tests for interactive form workflows and real-time updates."""

import pytest
from playwright.sync_api import expect

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_TAB = ".sf-nav-item[data-nav='{name}']"


def _switch_tab(pw_page, tab_name: str):
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name=tab_name)).click(force=True)
    pw_page.wait_for_timeout(800)


class TestJobSubmissionForm:
    """Tests for filling and submitting the job form on the Run page."""

    def test_fill_job_form(self, pw_page):
        """Fill the free-text/select fields; the STR file and working
        directory are project dropdowns that prompt when no project is open."""
        _switch_tab(pw_page, "Run")

        pw_page.locator("#run-job_name").fill("e2e_test_job")
        pw_page.locator("#run-tool_select").select_option("shyfem")

        assert pw_page.locator("#run-job_name").input_value() == "e2e_test_job"
        assert pw_page.locator("#run-tool_select").input_value() == "shyfem"
        for name in ("input_file", "working_dir"):
            picker = pw_page.locator(f"#run-{name}_picker")
            expect(picker).to_contain_text("Open a project", timeout=10000)
            assert pw_page.locator(f"input#run-{name}").count() == 0, name

    def test_tool_select_options(self, pw_page):
        """Test all tool options are available in dropdown."""
        _switch_tab(pw_page, "Run")
        select = pw_page.locator("#run-tool_select")
        options_text = " ".join(select.locator("option").all_inner_texts())
        for tool in ["shyfem", "shypre", "shybas", "shyparts", "shyelab", "shyplot"]:
            assert tool in options_text, f"Tool '{tool}' not found in dropdown"

    def test_mpi_toggle(self, pw_page):
        """Test enabling MPI shows the process count input."""
        _switch_tab(pw_page, "Run")
        pw_page.locator("#run-tool_select").select_option("shyfem")
        pw_page.wait_for_timeout(800)

        # Ensure shyfem_options has rendered and the checkbox exists.
        mpi_cb = pw_page.locator("#run-mpi_enabled")
        mpi_cb.wait_for(state="attached", timeout=5000)
        # Use click() — .check() can be ambiguous in headless mode if the
        # element wraps a hidden native input under a styled label.
        mpi_cb.click()
        pw_page.wait_for_timeout(800)

        np_input = pw_page.locator("#run-mpi_np")
        np_input.wait_for(state="visible", timeout=5000)
        assert np_input.is_visible()

    def test_submit_without_input_no_crash(self, pw_page):
        """Test submitting with missing input does not crash the UI."""
        _switch_tab(pw_page, "Run")

        pw_page.locator("#run-job_name").fill("")
        # No project open -> no STR dropdown to pick from; submit anyway.
        pw_page.locator("#run-submit_btn").click()

        pw_page.wait_for_timeout(1500)
        # The page should still be functional
        assert pw_page.locator("#run-submit_btn").is_visible()


class TestWorkflowForm:
    """Tests for the workflow launch form on the Run page."""

    def test_workflow_tab_accessible(self, pw_page):
        """Test Workflows sub-tab can be activated."""
        _switch_tab(pw_page, "Run")
        wf_tab = pw_page.locator("a:has-text('Workflows'), [role='tab']:has-text('Workflows')")
        wf_tab.first.click()
        pw_page.wait_for_timeout(500)

    def test_workflow_template_select(self, pw_page):
        """Test workflow template dropdown exists."""
        _switch_tab(pw_page, "Run")
        pw_page.locator("a:has-text('Workflows'), [role='tab']:has-text('Workflows')").first.click()
        pw_page.wait_for_timeout(500)
        template = pw_page.locator("#run-wf_template")
        assert template.is_visible()

    def test_workflow_launch_button(self, pw_page):
        """Test Launch Workflow button exists."""
        _switch_tab(pw_page, "Run")
        pw_page.locator("a:has-text('Workflows'), [role='tab']:has-text('Workflows')").first.click()
        pw_page.wait_for_timeout(500)
        btn = pw_page.locator("#run-wf_launch_btn")
        assert btn.is_visible()


class TestGridPrepInteractions:
    """Tests for Grid Prep page interactions."""

    def test_grd_path_picker_prompts_without_project(self, pw_page):
        """The grid file is a project-file dropdown (no free-text box); with
        no project open it prompts to open one."""
        _switch_tab(pw_page, "Grid Prep")
        picker = pw_page.locator("#grid_prep-grd_path_picker")
        expect(picker).to_contain_text("Open a project", timeout=10000)
        assert pw_page.locator("input#grid_prep-grd_path").count() == 0

    def test_switch_subtabs(self, pw_page):
        """Test switching between sub-tabs on Grid Prep page."""
        _switch_tab(pw_page, "Grid Prep")
        # Scope tab lookup to the visible Grid Prep page div — other pages
        # (e.g., Mesh Builder) also have nav tabs with overlapping names like
        # "Log" that would otherwise be matched first.
        page_scope = pw_page.locator("#sf-page-Grid-Prep")
        for tab in ["Statistics", "Node Inspector", "Log", "Interactive Map"]:
            page_scope.locator(f"[role='tab']:has-text('{tab}')").first.click()
            pw_page.wait_for_timeout(300)


class TestPartitioningInteractions:
    """Tests for Partitioning page interactions."""

    def test_change_partition_count(self, pw_page):
        """Test changing the number of partitions."""
        _switch_tab(pw_page, "Partitioning")
        num = pw_page.locator("#partitioning-num_partitions")
        num.fill("8")
        assert num.input_value() == "8"

    def test_toggle_weighted_checkbox(self, pw_page):
        """Test toggling the 'Use weighted partitioning' checkbox.

        Replaces test_change_partition_method — partition_method was
        removed in 75ee406 (2026-04-30); the active partition control
        is now the weighted checkbox (default ON per partitioning_ui).
        """
        _switch_tab(pw_page, "Partitioning")
        weighted = pw_page.locator("#partitioning-weighted")
        # Default value=True per partitioning_ui:input_checkbox.
        assert weighted.is_checked() is True
        weighted.uncheck()
        pw_page.wait_for_timeout(300)
        assert weighted.is_checked() is False
        weighted.check()
        pw_page.wait_for_timeout(300)
        assert weighted.is_checked() is True


class TestPostProcessInteractions:
    """Tests for Post-Process page interactions."""

    def test_change_operation(self, pw_page):
        """Test changing post-process operation."""
        _switch_tab(pw_page, "Post-Process")
        op = pw_page.locator("#postprocess-operation")
        op.select_option("extract_nc")
        pw_page.wait_for_timeout(300)
        assert op.input_value() == "extract_nc"

    def test_output_picker_present(self, pw_page):
        """The output file is chosen via a dropdown picker, not a text box."""
        _switch_tab(pw_page, "Post-Process")
        picker = pw_page.locator("#postprocess-shy_path_picker")
        assert picker.is_visible()
        assert pw_page.locator("input#postprocess-shy_path").count() == 0

    def test_switch_subtabs(self, pw_page):
        """Test switching between visible post-process sub-tabs."""
        _switch_tab(pw_page, "Post-Process")
        for tab in ["File Info", "Output Files"]:
            pw_page.locator(f"a[role='tab']:visible:has-text('{tab}')").first.click()
            pw_page.wait_for_timeout(300)


class TestCompareInteractions:
    """Tests for Compare page interactions."""

    def test_str_file_dropdowns(self, pw_page):
        """STR files A/B are dropdowns over the project's .str files (no
        free-text paths); with no project open only the placeholder remains."""
        _switch_tab(pw_page, "Compare")
        for name in ("str_file_a", "str_file_b"):
            sel = pw_page.locator(f"select#compare-{name}")
            expect(sel).to_be_attached(timeout=10000)
            assert pw_page.locator(f"input#compare-{name}").count() == 0, name
            labels = sel.locator("option").all_inner_texts()
            assert any("no .str files" in t for t in labels), labels

    def test_ts_file_dropdowns(self, pw_page):
        """Time-series files A/B are dropdowns (no free-text paths); with no
        project open only the placeholder remains."""
        _switch_tab(pw_page, "Compare")
        for name in ("ts_file_a", "ts_file_b"):
            sel = pw_page.locator(f"select#compare-{name}")
            expect(sel).to_be_attached(timeout=10000)
            assert pw_page.locator(f"input#compare-{name}").count() == 0, name
            labels = sel.locator("option").all_inner_texts()
            assert any("no time-series files" in t for t in labels), labels

    def test_switch_compare_subtabs(self, pw_page):
        """Test switching between visible compare sub-tabs."""
        _switch_tab(pw_page, "Compare")
        for tab in ["Runtime Stats", "Parameter Diff", "Summary"]:
            pw_page.locator(f"a[role='tab']:visible:has-text('{tab}')").first.click()
            pw_page.wait_for_timeout(300)


class TestWebSocketConnection:
    """Tests for WebSocket connectivity (Shiny's communication layer)."""

    def test_websocket_connected(self, pw_page):
        """Test that the Shiny WebSocket connection is established."""
        pw_page.wait_for_timeout(2000)
        # Reactive outputs only render after WS connects — probe the
        # "Tools Ready" badge which is one of the earliest reactive renders.
        system_status = pw_page.locator("#home-system_health_count")
        assert system_status.count() >= 1

    def test_reactive_update_on_tab_switch(self, pw_page):
        """Test that switching tabs triggers reactive rendering."""
        _switch_tab(pw_page, "Run")
        pw_page.wait_for_timeout(1000)
        dashboard = pw_page.locator("#run-dashboard")
        assert dashboard.count() >= 1
