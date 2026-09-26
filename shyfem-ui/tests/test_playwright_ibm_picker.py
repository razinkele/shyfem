"""Playwright tests for the IBM page's project-file dropdown (LGR file)."""

import pytest


@pytest.mark.e2e
class TestIbmDropdownNoProject:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_prompts_to_open_project_and_no_free_text_box(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='IBM']").click(force=True)
        pw_page.wait_for_timeout(1000)
        picker = pw_page.locator("#ibm-lgr_path_picker")
        picker.wait_for(state="attached", timeout=5000)
        assert "Open a project" in picker.inner_text()
        # The old free-text path box and FileService picker are gone.
        assert pw_page.locator("input#ibm-lgr_path").count() == 0
        assert pw_page.locator("#ibm-fp_lgr-file_select").count() == 0

    def test_lists_and_preselects_project_lgr_when_project_active(
        self, pw_page, live_server, tmp_path
    ):
        (tmp_path / "traj.lgr").write_text("x")
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / "later.lgr").write_text("x")
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
        pw_page.locator(".sf-nav-item[data-nav='IBM']").click(force=True)
        pw_page.wait_for_timeout(1000)
        select = pw_page.locator("select#ibm-lgr_path")
        select.wait_for(state="attached", timeout=5000)
        labels = select.locator("option").all_inner_texts()
        # Recursive listing, project-relative labels ...
        assert any("traj.lgr" in t for t in labels)
        assert any("runs/later.lgr" in t for t in labels)
        # ... and the first .lgr in sorted recursive order is preselected
        # (the successor of the old work_dir glob auto-fill): "runs/later.lgr"
        # sorts before "traj.lgr". A value that did not match an option value
        # exactly would leave the select on "" (— select a file —).
        assert select.input_value().endswith("/runs/later.lgr")
