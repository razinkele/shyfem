"""Unit tests for the postprocess output-file dropdown (no free-text path)."""


class TestPickerUiRenders:
    def test_output_dropdown_placeholder_present_and_no_text_box(self):
        from shyfem_ui.pages.postprocess import postprocess_ui

        html = str(postprocess_ui("test"))
        # The output file is chosen via a rendered dropdown placeholder ...
        assert 'id="test-shy_path_picker"' in html
        # ... not a free-text path box.
        assert 'id="test-shy_path"' not in html


class TestModuleWiring:
    def test_postprocess_renders_shy_path_dropdown_over_project_and_runs(self):
        import shyfem_ui.pages.postprocess as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "postprocess_server")
        # A render.ui builds the dropdown, consolidating project files and the
        # manifest's run directories ...
        assert "def shy_path_picker(" in src
        assert '"shy_path"' in src
        assert "list_project_files(" in src
        assert "load_manifest(" in src
        assert 'list_project_files(Path(run.dir), (".shy", ".nc"))' in src
        # ... and the old free-text / file_picker wiring is gone.
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
