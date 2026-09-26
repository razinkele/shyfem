"""Unit tests for the postprocess project-file / directory dropdowns."""


class TestPickerUiRenders:
    def test_dropdown_placeholders_present_and_no_text_boxes(self):
        from shyfem_ui.pages.postprocess import postprocess_ui

        html = str(postprocess_ui("test"))
        # Output file, batch files and output directory are chosen via
        # rendered dropdown placeholders ...
        assert 'id="test-shy_path_picker"' in html
        assert 'id="test-batch_paths_picker"' in html
        assert 'id="test-output_dir_picker"' in html
        # ... not free-text boxes / text areas.
        assert 'id="test-shy_path"' not in html
        assert 'id="test-batch_paths"' not in html
        assert 'id="test-output_dir"' not in html
        # The remaining text inputs are untouched.
        assert 'id="test-tmin"' in html
        assert 'id="test-tmax"' in html


class TestModuleWiring:
    def test_postprocess_renders_project_file_dropdowns(self):
        import shyfem_ui.pages.postprocess as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "postprocess_server")
        # Three render.ui dropdowns built on the shared project_select helpers.
        assert "def shy_path_picker(" in src
        assert "def batch_paths_picker(" in src
        assert "def output_dir_picker(" in src
        assert 'project_file_select(\n            "shy_path"' in src
        assert 'project_file_select(\n            "batch_paths"' in src
        assert 'project_dir_select(\n            "output_dir"' in src
        # Output + batch pickers consolidate project files with the box-model
        # run directories; batch is a multi-select.
        assert src.count("include_runs=True") == 2
        assert "multiple=True" in src
        # The output directory keeps the handlers' "same dir as input" fallback.
        assert 'default_label="— same directory as the input file —"' in src
        # The batch handler consumes the multi-select tuple, not newline text.
        assert "paths = list(input.batch_paths() or ())" in src
        assert "splitlines(" not in src
        # ... and the old hand-rolled / free-text wiring is gone.
        assert "list_project_files(" not in src
        assert "load_manifest(" not in src
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
        assert "project_id_val" not in src

    def test_output_dir_fallback_call_sites_unchanged(self):
        import shyfem_ui.pages.postprocess as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "postprocess_server")
        # All handlers still fall back to the input file's directory when the
        # dropdown's empty "same directory" option is selected.
        assert src.count("input.output_dir() or str(path.parent)") == 3
