"""Playwright tests for individual page content and interactions."""

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_TAB = ".sf-nav-item[data-nav='{name}']"


def _switch_tab(pw_page, tab_name: str):
    """Click a main navbar tab and wait for its content."""
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name=tab_name)).click(force=True)
    pw_page.wait_for_timeout(800)


class TestGridPrepPage:
    """Tests for the Grid Prep page."""

    def test_page_renders(self, pw_page):
        """Test Grid Prep page renders without error."""
        _switch_tab(pw_page, "Grid Prep")
        assert pw_page.locator("text=shypre").count() >= 1

    def test_sidebar_visible(self, pw_page):
        """Test sidebar with grid file input is visible."""
        _switch_tab(pw_page, "Grid Prep")
        sidebar = pw_page.locator(".bslib-sidebar-layout, .sidebar")
        assert sidebar.count() >= 1

    def test_run_shypre_button(self, pw_page):
        """Test Run shypre button is present."""
        _switch_tab(pw_page, "Grid Prep")
        btn = pw_page.locator("#grid_prep-run_shypre_btn")
        assert btn.is_visible()

    def test_run_shybas_button(self, pw_page):
        """Test Run shybas button is present."""
        _switch_tab(pw_page, "Grid Prep")
        btn = pw_page.locator("#grid_prep-run_shybas_btn")
        assert btn.is_visible()

    def test_subtabs_present(self, pw_page):
        """Test sub-tabs are present."""
        _switch_tab(pw_page, "Grid Prep")
        for tab in ["Interactive Map", "Static Plot", "Statistics", "Node Inspector", "Log"]:
            assert pw_page.locator(f"a:has-text('{tab}'), [role='tab']:has-text('{tab}')").count() >= 1, \
                f"Sub-tab '{tab}' not found on Grid Prep page"

    def test_grd_path_input(self, pw_page):
        """Test grid file path input exists."""
        _switch_tab(pw_page, "Grid Prep")
        grd_input = pw_page.locator("#grid_prep-grd_path")
        assert grd_input.is_visible()


class TestPartitioningPage:
    """Tests for the Partitioning page."""

    def test_page_renders(self, pw_page):
        """Test Partitioning page renders."""
        _switch_tab(pw_page, "Partitioning")
        assert pw_page.locator("text=shyparts").count() >= 1

    def test_num_partitions_input(self, pw_page):
        """Test partition count input exists."""
        _switch_tab(pw_page, "Partitioning")
        num_parts = pw_page.locator("#partitioning-num_partitions")
        assert num_parts.is_visible()

    def test_weighted_checkbox_present(self, pw_page):
        """Test 'Use weighted partitioning' checkbox is present.

        Replaces test_partition_method_select — the partition_method
        select (metis/manual) was removed in 75ee406 (2026-04-30) when
        the non-functional 'manual' method was deleted. The remaining
        partition control is the weighted checkbox.
        """
        _switch_tab(pw_page, "Partitioning")
        weighted = pw_page.locator("#partitioning-weighted")
        assert weighted.is_visible()

    def test_run_shyparts_button(self, pw_page):
        """Test Run shyparts button is present."""
        _switch_tab(pw_page, "Partitioning")
        btn = pw_page.locator("#partitioning-run_shyparts_btn")
        assert btn.is_visible()

    def test_validate_button(self, pw_page):
        """Test Validate Partitions button is present."""
        _switch_tab(pw_page, "Partitioning")
        btn = pw_page.locator("#partitioning-validate_btn")
        assert btn.is_visible()

    def test_subtabs_present(self, pw_page):
        """Test sub-tabs are present."""
        _switch_tab(pw_page, "Partitioning")
        for tab in ["Partition Map", "Load Balance", "Partition Info", "Statistics", "Log"]:
            assert pw_page.locator(f"a:has-text('{tab}'), [role='tab']:has-text('{tab}')").count() >= 1


class TestSimulationPage:
    """Tests for the Simulation (STR editor) page."""

    def test_page_renders(self, pw_page):
        """Test Simulation page renders."""
        _switch_tab(pw_page, "Simulation")
        assert pw_page.locator(_TAB.format(name="Simulation")).count() >= 1

    def test_sidebar_visible(self, pw_page):
        """Test sidebar is visible."""
        _switch_tab(pw_page, "Simulation")
        sidebar = pw_page.locator(".bslib-sidebar-layout, .sidebar")
        assert sidebar.count() >= 1


class TestRunPage:
    """Tests for the Run (job execution) page."""

    def test_page_renders(self, pw_page):
        """Test Run page renders."""
        _switch_tab(pw_page, "Run")
        assert pw_page.locator("#run-submit_btn").count() >= 1

    def test_job_name_input(self, pw_page):
        """Test job name input exists."""
        _switch_tab(pw_page, "Run")
        name = pw_page.locator("#run-job_name")
        assert name.is_visible()

    def test_tool_select(self, pw_page):
        """Test tool dropdown exists."""
        _switch_tab(pw_page, "Run")
        select = pw_page.locator("#run-tool_select")
        assert select.is_visible()

    def test_input_file_field(self, pw_page):
        """Test input file field exists."""
        _switch_tab(pw_page, "Run")
        input_file = pw_page.locator("#run-input_file")
        assert input_file.is_visible()

    def test_working_dir_field(self, pw_page):
        """Test working directory field exists."""
        _switch_tab(pw_page, "Run")
        wd = pw_page.locator("#run-working_dir")
        assert wd.is_visible()

    def test_submit_button(self, pw_page):
        """Test Submit Job button is present."""
        _switch_tab(pw_page, "Run")
        btn = pw_page.locator("#run-submit_btn")
        assert btn.is_visible()

    def test_refresh_button(self, pw_page):
        """Test Refresh button is present."""
        _switch_tab(pw_page, "Run")
        btn = pw_page.locator("#run-refresh_btn")
        assert btn.is_visible()

    def test_subtabs_present(self, pw_page):
        """Test monitoring sub-tabs are present."""
        _switch_tab(pw_page, "Run")
        # These are inside the Run page as inner tabs
        for tab in ["Active Jobs", "Job History"]:
            assert pw_page.locator(f"a:has-text('{tab}'), [role='tab']:has-text('{tab}')").count() >= 1

    def test_mpi_controls_hidden_for_shybas(self, pw_page):
        """Test MPI controls not visible when non-MPI tool is selected."""
        _switch_tab(pw_page, "Run")
        pw_page.locator("#run-tool_select").select_option("shybas")
        pw_page.wait_for_timeout(500)
        mpi_checkbox = pw_page.locator("#run-mpi_enabled")
        assert not mpi_checkbox.is_visible()

    def test_mpi_controls_visible_for_shyfem(self, pw_page):
        """Test MPI controls appear when shyfem is selected."""
        _switch_tab(pw_page, "Run")
        pw_page.locator("#run-tool_select").select_option("shyfem")
        pw_page.wait_for_timeout(500)
        mpi_checkbox = pw_page.locator("#run-mpi_enabled")
        assert mpi_checkbox.is_visible()


class TestPostProcessPage:
    """Tests for the Post-Process page."""

    def test_page_renders(self, pw_page):
        """Test Post-Process page renders."""
        _switch_tab(pw_page, "Post-Process")
        assert pw_page.locator("text=shyelab").count() >= 1

    def test_shy_path_input(self, pw_page):
        """Test .shy file path input exists."""
        _switch_tab(pw_page, "Post-Process")
        shy_input = pw_page.locator("#postprocess-shy_path")
        assert shy_input.is_visible()

    def test_operation_select(self, pw_page):
        """Test operation dropdown exists."""
        _switch_tab(pw_page, "Post-Process")
        op = pw_page.locator("#postprocess-operation")
        assert op.is_visible()

    def test_run_button(self, pw_page):
        """Test Run shyelab button is present."""
        _switch_tab(pw_page, "Post-Process")
        btn = pw_page.locator("#postprocess-run_btn")
        assert btn.is_visible()

    def test_subtabs_present(self, pw_page):
        """Test sub-tabs are present."""
        _switch_tab(pw_page, "Post-Process")
        for tab in ["File Info", "Output Files", "Log"]:
            assert pw_page.locator(f"a:has-text('{tab}'), [role='tab']:has-text('{tab}')").count() >= 1


class TestVisualizePage:
    """Tests for the Visualize page."""

    def test_page_renders(self, pw_page):
        """Test Visualize page renders."""
        _switch_tab(pw_page, "Visualize")
        assert pw_page.locator(_TAB.format(name="Visualize")).count() >= 1

    def test_sidebar_visible(self, pw_page):
        """Test sidebar is visible."""
        _switch_tab(pw_page, "Visualize")
        sidebar = pw_page.locator(".bslib-sidebar-layout, .sidebar")
        assert sidebar.count() >= 1


class TestComparePage:
    """Tests for the Compare page."""

    def test_page_renders(self, pw_page):
        """Test Compare page renders."""
        _switch_tab(pw_page, "Compare")
        heading = pw_page.locator("text=Compare Simulations")
        assert heading.count() >= 1

    def test_str_file_inputs(self, pw_page):
        """Test STR file comparison inputs exist."""
        _switch_tab(pw_page, "Compare")
        a = pw_page.locator("#compare-str_file_a")
        b = pw_page.locator("#compare-str_file_b")
        assert a.is_visible()
        assert b.is_visible()

    def test_compare_buttons(self, pw_page):
        """Test compare action buttons exist."""
        _switch_tab(pw_page, "Compare")
        assert pw_page.locator("#compare-compare_str_btn").is_visible()
        assert pw_page.locator("#compare-compare_ts_btn").is_visible()

    def test_subtabs_present(self, pw_page):
        """Test sub-tabs are present."""
        _switch_tab(pw_page, "Compare")
        for tab in ["Runtime Stats", "Parameter Diff", "Time Series", "Summary"]:
            assert pw_page.locator(f"a:has-text('{tab}'), [role='tab']:has-text('{tab}')").count() >= 1


class TestEnsemblePage:
    """Tests for the Ensemble page."""

    def test_page_renders(self, pw_page):
        """Test Ensemble page renders."""
        _switch_tab(pw_page, "Ensemble")
        assert pw_page.locator(_TAB.format(name="Ensemble")).count() >= 1

    def test_sidebar_visible(self, pw_page):
        """Test sidebar is visible."""
        _switch_tab(pw_page, "Ensemble")
        sidebar = pw_page.locator(".bslib-sidebar-layout, .sidebar")
        assert sidebar.count() >= 1
