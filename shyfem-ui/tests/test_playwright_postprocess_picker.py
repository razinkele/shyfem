"""Playwright tests for the postprocess output-file dropdown."""

import pytest


@pytest.mark.e2e
class TestPostprocessOutputDropdown:
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
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(1000)
        picker = pw_page.locator("#postprocess-shy_path_picker")
        picker.wait_for(state="attached", timeout=5000)
        # With no active project the output picker shows a hint, not a select.
        assert "Open a project" in picker.inner_text()
        # The old free-text path box is gone entirely.
        assert pw_page.locator("input#postprocess-shy_path").count() == 0

    def test_lists_project_shy_files_when_project_active(self, pw_page, live_server, tmp_path):
        shy = tmp_path / "output.shy"
        shy.write_text("x")
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
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(1000)
        select = pw_page.locator("#postprocess-shy_path")
        select.wait_for(state="attached", timeout=5000)
        assert any("output.shy" in t for t in select.locator("option").all_inner_texts())
