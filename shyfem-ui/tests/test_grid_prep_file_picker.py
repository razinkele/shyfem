"""Unit tests for the grid_prep page's project-file dropdowns."""

import re


class TestPickerUiRenders:
    def test_dropdown_placeholders_present_and_no_text_boxes(self):
        from shyfem_ui.pages.grid_prep import grid_prep_ui

        html = str(grid_prep_ui("test"))
        # Grid file and output directory are rendered dropdown placeholders ...
        assert 'id="test-grd_path_picker"' in html
        assert 'id="test-output_dir_picker"' in html
        # ... not free-text path boxes, and the old companion picker is gone.
        assert 'id="test-grd_path"' not in html
        assert 'id="test-output_dir"' not in html
        assert "fp_grd" not in html
        # The upload browser and the "Load from Path" button are untouched.
        assert 'id="test-grd_file-' in html
        assert 'id="test-load_path_btn"' in html


class TestModuleWiring:
    def test_grid_prep_renders_project_file_dropdowns(self):
        import shyfem_ui.pages.grid_prep as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "grid_prep_server")
        # Two render.ui dropdowns backed by a project-dir scan ...
        assert "def grd_path_picker(" in src
        assert "def output_dir_picker(" in src
        # ... built on the shared project_select helpers, preselecting the
        # project's first grid like the old text box auto-filled.
        assert 'project_file_select(\n            "grd_path"' in src
        assert 'project_dir_select(\n            "output_dir"' in src
        assert 'default_project_file(proj, "grd")' in src
        # Output dir keeps the handlers' "same directory as the grid" fallback.
        assert 'default_label="— same directory as the grid file —"' in src
        # ... and the old file_picker / free-text wiring is gone.
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
        assert "project_id_val" not in src
        assert 'ui.update_text(\n            "grd_path"' not in src
        assert 'ui.update_text("grd_path"' not in src
        assert not hasattr(page_mod, "file_picker_server")
        assert not hasattr(page_mod, "file_picker_ui")
        assert not hasattr(page_mod, "fill_picker_input")

    def test_sample_and_tutorial_paths_go_through_preselect_reactive(self):
        """Paths outside the project (bundled sample, tutorial asset) cannot be
        pushed into a dropdown with ui.update_select -- a value that is not one
        of the options is a silent no-op. The page keeps ONE reactive that the
        sample/tutorial effects set and the picker render reads, injecting the
        path as an extra option and preselecting it."""
        import shyfem_ui.pages.grid_prep as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "grid_prep_server")
        assert "preselect_grd" in src
        # Both producers set the reactive (no update_text left anywhere).
        assert "ui.update_text(" not in src
        assert re.search(r"preselect_grd\.set\(\s*\(str\(grd_path\),\s*f\"Sample: ", src)
        assert re.search(r"preselect_grd\.set\(\s*\(str\(path\),\s*f\"Tutorial: ", src)
        # The render reads it and hands it to the helper as selected + extra.
        picker_src = src[src.index("def grd_path_picker(") : src.index("def output_dir_picker(")]
        assert "preselect_grd.get()" in picker_src
        assert "selected=" in picker_src
        assert "extra=" in picker_src

    def test_handlers_still_read_the_same_input_ids(self):
        """Option VALUES are absolute paths, so the confining handlers keep
        reading input.grd_path() / input.output_dir() unchanged."""
        import shyfem_ui.pages.grid_prep as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "grid_prep_server")
        assert "path_str = input.grd_path()" in src
        assert "output_dir = input.output_dir() or str(grd_path.parent)" in src
        assert "output_dir = input.output_dir()" in src
