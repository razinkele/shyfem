"""Playwright tests for the Run page's project-file dropdowns.

Runs against the real run_server. The submit form's STR file / working
directory and the Workflow tab's STR / GRD / working directory are
``<select>``s over the active project's files (option values are absolute
paths); with no project open each picker renders an "Open a project" prompt.
The bundled Mar Menor sample lives outside the project, so "Load Sample Data"
injects it as an extra, preselected option (working dir falls back to the
project root -- project_dir_select has no ``extra``).
"""

import pytest
from playwright.sync_api import expect

_PICKERS = ("input_file", "working_dir")
_WF_PICKERS = ("wf_input_str", "wf_input_grd", "wf_working_dir")


def _open_run(pw_page):
    pw_page.locator(".sf-nav-item[data-nav='Run']").click(force=True)
    pw_page.wait_for_timeout(1000)


def _open_workflows_tab(pw_page):
    pw_page.locator("a:has-text('Workflows'), [role='tab']:has-text('Workflows')").first.click()
    pw_page.wait_for_timeout(500)


def _set_project(pw_page, work_dir) -> None:
    result = pw_page.evaluate(
        """(wd) => {
            if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: wd, description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""",
        str(work_dir),
    )
    if result == "no-hook":
        pytest.skip("test_app.py does not expose __test_set_active_project")


def _set_project_id(pw_page, pid: int, work_dir) -> None:
    pw_page.evaluate(
        """([pid, wd]) => {
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project({
                    id: pid, name: 'p', work_dir: wd, description: null,
                    grids: [], simulations: [], files: [],
                });
            }
        }""",
        [pid, str(work_dir)],
    )
    pw_page.wait_for_timeout(300)


@pytest.mark.e2e
class TestRunDropdownsNoProject:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_prompts_to_open_project_and_no_free_text_boxes(self, pw_page, live_server):
        _open_run(pw_page)
        for name in _PICKERS:
            picker = pw_page.locator(f"#run-{name}_picker")
            expect(picker).to_contain_text("Open a project", timeout=10000)
            # The old free-text path boxes (and companion picker) are gone.
            assert pw_page.locator(f"input#run-{name}").count() == 0, name
        assert pw_page.locator("#run-fp_input-file_select").count() == 0

    def test_workflow_pickers_prompt_to_open_project(self, pw_page, live_server):
        _open_run(pw_page)
        _open_workflows_tab(pw_page)
        for name in _WF_PICKERS:
            picker = pw_page.locator(f"#run-{name}_picker")
            expect(picker).to_contain_text("Open a project", timeout=10000)
            assert pw_page.locator(f"input#run-{name}").count() == 0, name


@pytest.mark.e2e
class TestRunDropdownsWithProject:
    def test_lists_project_str_and_dirs(self, pw_page, live_server, tmp_path):
        (tmp_path / "sim.str").write_text("x")
        (tmp_path / "runs").mkdir()
        _set_project(pw_page, tmp_path)
        _open_run(pw_page)

        sel = pw_page.locator("select#run-input_file")
        expect(sel).to_be_attached(timeout=10000)
        assert any("sim.str" in t for t in sel.locator("option").all_inner_texts())

        wd = pw_page.locator("select#run-working_dir")
        expect(wd).to_be_attached(timeout=10000)
        labels = wd.locator("option").all_inner_texts()
        assert any(t.strip() == "p/" for t in labels), labels
        assert any(t.strip() == "runs/" for t in labels), labels
        # Project root preselected (no "same as input" fallback option).
        assert wd.input_value() == str(tmp_path)

    def test_workflow_pickers_list_project_files(self, pw_page, live_server, tmp_path):
        (tmp_path / "sim.str").write_text("x")
        (tmp_path / "mesh.grd").write_text("x")
        _set_project(pw_page, tmp_path)
        _open_run(pw_page)
        _open_workflows_tab(pw_page)

        s = pw_page.locator("select#run-wf_input_str")
        expect(s).to_be_attached(timeout=10000)
        assert any("sim.str" in t for t in s.locator("option").all_inner_texts())
        g = pw_page.locator("select#run-wf_input_grd")
        assert any("mesh.grd" in t for t in g.locator("option").all_inner_texts())
        w = pw_page.locator("select#run-wf_working_dir")
        assert w.input_value() == str(tmp_path)


@pytest.mark.e2e
class TestRunSamplePreselect:
    """ "Load Sample Data" sets page-level preselect reactives that outlive
    the (session-scoped) Shiny page. A switch between two different projects
    drops them, so the teardown does exactly that before handing the shared
    page to the next test."""

    @pytest.fixture(autouse=True)
    def _drop_preselects_after(self, pw_page, tmp_path):
        yield
        _set_project_id(pw_page, 901, tmp_path)
        _set_project_id(pw_page, 902, tmp_path)
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(300)

    def test_load_sample_without_project_offers_sample_str_and_dir(self, pw_page, live_server):
        """Both helpers offer the injected sample entries even with no project
        open: the sample STR and the sample directory, each preselected."""
        _open_run(pw_page)
        expect(pw_page.locator("#run-input_file_picker")).to_contain_text(
            "Open a project", timeout=10000
        )
        pw_page.locator("#run-load_sample_btn").click()

        sel = pw_page.locator("select#run-input_file")
        expect(sel.locator("option:checked")).to_have_text("Sample: mm_hyd_03.str", timeout=10000)
        assert sel.input_value().endswith("/mar_menor/mm_hyd_03.str")
        wd = pw_page.locator("select#run-working_dir")
        expect(wd.locator("option:checked")).to_have_text("Sample: mar_menor/", timeout=10000)
        assert wd.input_value().endswith("/mar_menor")
        assert pw_page.locator("#run-tool_select").input_value() == "shyfem"

    def test_load_sample_injects_str_and_workdir_options(self, pw_page, live_server, tmp_path):
        """The sample STR and its directory are outside the project: both are
        injected as extra, preselected options next to the project's own
        entries, and the tool switches to shyfem."""
        (tmp_path / "sim.str").write_text("x")
        _set_project(pw_page, tmp_path)
        _open_run(pw_page)
        expect(pw_page.locator("select#run-input_file")).to_be_attached(timeout=10000)

        pw_page.locator("#run-load_sample_btn").click()

        sel = pw_page.locator("select#run-input_file")
        expect(sel.locator("option:checked")).to_have_text("Sample: mm_hyd_03.str", timeout=10000)
        assert sel.input_value().endswith("/mar_menor/mm_hyd_03.str")
        # The project's own STR is still offered alongside the sample.
        assert any("sim.str" in t for t in sel.locator("option").all_inner_texts())

        wd = pw_page.locator("select#run-working_dir")
        expect(wd.locator("option:checked")).to_have_text("Sample: mar_menor/", timeout=10000)
        assert wd.input_value().endswith("/mar_menor")
        # The project root is still offered alongside the sample directory.
        assert any(t == "p/" for t in wd.locator("option").all_inner_texts())
        assert pw_page.locator("#run-tool_select").input_value() == "shyfem"


@pytest.mark.e2e
class TestRunNoProjectFeedback:
    """With no project open the pickers render a disabled placeholder select,
    so the input ids still exist (value "") and Submit reaches its own
    "Input file is required" guard instead of aborting silently on a missing
    input (review finding, 2026-09-25)."""

    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(300)

    def test_submit_without_project_shows_required_notice(self, pw_page, live_server):
        _open_run(pw_page)
        expect(pw_page.locator("#run-input_file_picker")).to_contain_text(
            "Open a project", timeout=10000
        )
        # The placeholder select exists and is disabled.
        sel = pw_page.locator("select#run-input_file")
        expect(sel).to_be_attached(timeout=10000)
        assert sel.is_disabled()
        pw_page.locator("#run-submit_btn").click(force=True)
        expect(pw_page.locator(".shiny-notification").filter(has_text="required")).to_be_visible(
            timeout=10000
        )
