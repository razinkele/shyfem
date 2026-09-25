"""Playwright tests for the Simulation page's project-file STR dropdown."""

import pytest


@pytest.mark.e2e
class TestSimulationStrDropdown:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_prompts_to_open_project_and_has_no_free_text_box(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(1000)
        picker = pw_page.locator("#simulation-str_path_picker")
        picker.wait_for(state="attached", timeout=5000)
        assert "Open a project" in picker.inner_text()
        assert pw_page.locator("input#simulation-str_path").count() == 0
        assert pw_page.locator("#simulation-fp_str-file_select").count() == 0

    def test_lists_and_preselects_project_str_when_project_active(
        self, pw_page, live_server, tmp_path
    ):
        (tmp_path / "sim.str").write_text("$title\n$end\n")
        result = pw_page.evaluate(
            """(wd) => {
                if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
                window.__test_set_active_project({
                    id: 1, name: 'p', work_dir: wd, description: null,
                    grids: [], simulations: [{name: 's', str_file: 'sim.str'}], files: [],
                });
                return 'set';
            }""",
            str(tmp_path),
        )
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(1000)
        select = pw_page.locator("select#simulation-str_path")
        select.wait_for(state="attached", timeout=5000)
        assert any("sim.str" in t for t in select.locator("option").all_inner_texts())
        assert select.input_value().endswith("sim.str")

    def test_sample_load_injects_and_preselects_sample_option(self, pw_page, live_server):
        """The bundled Mar Menor sample lives outside any project; loading it
        must still show up in the dropdown as an injected, preselected option."""
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(800)
        btn = pw_page.locator("#simulation-load_sample_btn")
        if btn.count() == 0:
            pytest.skip("sample-data card not rendered")
        btn.click(force=True)
        pw_page.wait_for_timeout(1500)
        select = pw_page.locator("select#simulation-str_path")
        select.wait_for(state="attached", timeout=5000)
        texts = select.locator("option").all_inner_texts()
        assert any(t.startswith("Sample:") for t in texts), texts
        assert select.input_value().endswith(".str")
