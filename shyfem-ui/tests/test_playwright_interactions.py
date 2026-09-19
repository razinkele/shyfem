"""Playwright tests for interactive form workflows and real-time updates."""

import pytest

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
        """Test filling all job form fields."""
        _switch_tab(pw_page, "Run")

        pw_page.locator("#run-job_name").fill("e2e_test_job")
        pw_page.locator("#run-tool_select").select_option("shyfem")
        pw_page.locator("#run-input_file").fill("/tmp/test.str")
        pw_page.locator("#run-working_dir").fill("/tmp/test_run")

        assert pw_page.locator("#run-job_name").input_value() == "e2e_test_job"
        assert pw_page.locator("#run-input_file").input_value() == "/tmp/test.str"

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
        pw_page.locator("#run-input_file").fill("")
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

    def test_fill_grd_path(self, pw_page):
        """Test filling grid file path input."""
        _switch_tab(pw_page, "Grid Prep")
        grd = pw_page.locator("#grid_prep-grd_path")
        grd.fill("/tmp/test.grd")
        assert grd.input_value() == "/tmp/test.grd"

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

    def test_fill_str_file_paths(self, pw_page):
        """Test filling STR file paths."""
        _switch_tab(pw_page, "Compare")
        pw_page.locator("#compare-str_file_a").fill("/tmp/a.str")
        pw_page.locator("#compare-str_file_b").fill("/tmp/b.str")
        assert pw_page.locator("#compare-str_file_a").input_value() == "/tmp/a.str"
        assert pw_page.locator("#compare-str_file_b").input_value() == "/tmp/b.str"

    def test_fill_ts_file_paths(self, pw_page):
        """Test filling time series file paths."""
        _switch_tab(pw_page, "Compare")
        pw_page.locator("#compare-ts_file_a").fill("/tmp/ts_a.dat")
        pw_page.locator("#compare-ts_file_b").fill("/tmp/ts_b.dat")
        assert pw_page.locator("#compare-ts_file_a").input_value() == "/tmp/ts_a.dat"
        assert pw_page.locator("#compare-ts_file_b").input_value() == "/tmp/ts_b.dat"

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
