"""Playwright tests for the grid_prep project-file dropdowns."""

from pathlib import Path

import pytest

# The bundled sample the "Load Sample Data" card points at, resolved the same
# way the live app subprocess does (config.testcases_dir = shyfem_dir/testcases/examples).
_SAMPLE_GRD = (
    Path(__file__).resolve().parents[2]
    / "testcases"
    / "examples"
    / "mar_menor"
    / "GRID"
    / "MM_coarse.grd"
)


def _set_project(pw_page, work_dir: str) -> str:
    return pw_page.evaluate(
        """(wd) => {
            if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: wd, description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""",
        work_dir,
    )


@pytest.mark.e2e
class TestGridPrepDropdowns:
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
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(1000)
        grd = pw_page.locator("#grid_prep-grd_path_picker")
        grd.wait_for(state="attached", timeout=5000)
        assert "Open a project" in grd.inner_text()
        out = pw_page.locator("#grid_prep-output_dir_picker")
        assert "Open a project" in out.inner_text()
        # The old free-text path boxes and the companion picker are gone.
        assert pw_page.locator("input#grid_prep-grd_path").count() == 0
        assert pw_page.locator("input#grid_prep-output_dir").count() == 0
        assert pw_page.locator("#grid_prep-fp_grd-file_select").count() == 0

    def test_lists_project_grd_and_dirs_when_project_active(self, pw_page, live_server, tmp_path):
        (tmp_path / "mesh.grd").write_text("x")
        (tmp_path / "out").mkdir()
        if _set_project(pw_page, str(tmp_path)) == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(1000)
        grd = pw_page.locator("select#grid_prep-grd_path")
        grd.wait_for(state="attached", timeout=5000)
        assert any("mesh.grd" in t for t in grd.locator("option").all_inner_texts())
        out = pw_page.locator("select#grid_prep-output_dir")
        out.wait_for(state="attached", timeout=5000)
        texts = out.locator("option").all_inner_texts()
        # Empty default keeps the handlers' "same directory as the grid" fallback ...
        assert any("same directory as the grid file" in t for t in texts)
        assert out.input_value() == ""
        # ... and the project root + subdirectories are offered.
        assert any(t == "p/" for t in texts)
        assert any(t == "out/" for t in texts)

    def test_load_sample_injects_and_preselects_sample_grid(self, pw_page, live_server, tmp_path):
        """The bundled Mar Menor grid lives outside the project, so the sample
        loader cannot ui.update_select it in; it goes through the page's
        preselect reactive and shows up as an injected, preselected option.
        Runs last: the preselect persists on this session-scoped page."""
        if not _SAMPLE_GRD.exists():
            pytest.skip(f"sample grid not present: {_SAMPLE_GRD}")
        (tmp_path / "mesh.grd").write_text("x")
        if _set_project(pw_page, str(tmp_path)) == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(1000)
        grd = pw_page.locator("select#grid_prep-grd_path")
        grd.wait_for(state="attached", timeout=5000)
        assert not any("Sample:" in t for t in grd.locator("option").all_inner_texts())

        pw_page.locator("#grid_prep-load_sample_btn").click(force=True)
        pw_page.wait_for_timeout(2500)

        grd = pw_page.locator("select#grid_prep-grd_path")
        grd.wait_for(state="attached", timeout=5000)
        texts = grd.locator("option").all_inner_texts()
        assert any("Sample: MM_coarse.grd" in t for t in texts), texts
        # The project's own grid is still listed alongside the injected sample.
        assert any("mesh.grd" in t for t in texts), texts
        assert grd.input_value() == str(_SAMPLE_GRD)
