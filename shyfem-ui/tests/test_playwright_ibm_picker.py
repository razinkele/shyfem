"""Playwright tests for the IBM page's project-file dropdown (LGR file)."""

import re

import pytest
from playwright.sync_api import expect


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
        select = pw_page.locator("select#ibm-lgr_path")
        # Poll, never read once after a fixed wait: with no project the picker
        # is a disabled placeholder select with this SAME id ("Open a project
        # ..."), left by the reset fixture and the previous test, so a single
        # read can catch it before the project's listing renders (the first CI
        # run of #187 failed exactly so).
        # Recursive listing, project-relative labels ...
        expect(select.locator("option", has_text="traj.lgr")).to_have_count(1, timeout=15000)
        expect(select.locator("option", has_text="runs/later.lgr")).to_have_count(1)
        # ... and the first .lgr in sorted recursive order is preselected
        # (the successor of the old work_dir glob auto-fill): "runs/later.lgr"
        # sorts before "traj.lgr". A value that did not match an option value
        # exactly would leave the select on "" (— select a file —).
        expect(select).to_have_value(re.compile(r".*/runs/later\.lgr$"))
