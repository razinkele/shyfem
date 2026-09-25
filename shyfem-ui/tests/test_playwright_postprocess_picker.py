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
        # The batch / output-dir pickers show the same hint.
        batch = pw_page.locator("#postprocess-batch_paths_picker")
        batch.wait_for(state="attached", timeout=5000)
        assert "Open a project" in batch.inner_text()
        outdir = pw_page.locator("#postprocess-output_dir_picker")
        outdir.wait_for(state="attached", timeout=5000)
        assert "Open a project" in outdir.inner_text()
        # The old free-text path box, batch text area and output-dir box are gone.
        assert pw_page.locator("input#postprocess-shy_path").count() == 0
        assert pw_page.locator("textarea#postprocess-batch_paths").count() == 0
        assert pw_page.locator("input#postprocess-output_dir").count() == 0

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
        # Batch mode is a multi-select over the same files ...
        batch = pw_page.locator("select#postprocess-batch_paths")
        batch.wait_for(state="attached", timeout=5000)
        assert batch.get_attribute("multiple") is not None
        # selectize.js owns the option list of a multi-select (the hidden
        # <select> only keeps the *selected* options), so read its registry.
        batch_labels = pw_page.evaluate("""() => {
                const el = document.getElementById('postprocess-batch_paths');
                if (el && el.selectize) {
                    return Object.values(el.selectize.options).map(o => String(o.label));
                }
                return Array.from(el.options).map(o => o.textContent);
            }""")
        assert any("output.shy" in t for t in batch_labels)
        # ... and the output directory is a dropdown whose empty default keeps
        # the "same directory as the input file" fallback.
        outdir = pw_page.locator("select#postprocess-output_dir")
        outdir.wait_for(state="attached", timeout=5000)
        labels = outdir.locator("option").all_text_contents()
        assert any("same directory" in t for t in labels)
        assert any(t == "p/" for t in labels)
        assert outdir.input_value() == ""
