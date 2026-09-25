"""Playwright tests for the partitioning project-file dropdowns."""

import pytest
from playwright.sync_api import expect


@pytest.mark.e2e
class TestPartitioningDropdownsNoProject:
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
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(1000)
        bas = pw_page.locator("#partitioning-bas_path_picker")
        expect(bas).to_contain_text("Open a project", timeout=15000)
        expect(pw_page.locator("#partitioning-output_dir_picker")).to_contain_text(
            "Open a project", timeout=15000
        )
        # The old free-text path boxes are gone.
        assert pw_page.locator("input#partitioning-bas_path").count() == 0
        assert pw_page.locator("input#partitioning-grd_path").count() == 0
        assert pw_page.locator("input#partitioning-output_dir").count() == 0

    def test_lists_project_bas_and_grd_when_project_active(self, pw_page, live_server, tmp_path):
        (tmp_path / "mesh.bas").write_text("x")
        (tmp_path / "mesh.grd").write_text("x")
        result = pw_page.evaluate(
            """(wd) => {
                if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
                window.__test_set_active_project({
                    id: 1, name: 'p', work_dir: wd, description: null,
                    grids: [], simulations: [], files: [],
                });
                return 'set';
            }""",
            str(tmp_path),
        )
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(1000)
        bas = pw_page.locator("select#partitioning-bas_path")
        bas.wait_for(state="attached", timeout=15000)
        assert any("mesh.bas" in t for t in bas.locator("option").all_inner_texts())
        grd = pw_page.locator("select#partitioning-grd_path")
        assert any("mesh.grd" in t for t in grd.locator("option").all_inner_texts())
        out = pw_page.locator("select#partitioning-output_dir")
        out.wait_for(state="attached", timeout=15000)
        texts = out.locator("option").all_inner_texts()
        assert any("same directory" in t for t in texts)
        assert any(t == "p/" for t in texts)
        assert out.input_value() == ""
