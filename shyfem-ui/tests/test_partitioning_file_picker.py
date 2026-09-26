"""Unit tests for the partitioning page's project-file dropdowns."""


class TestPickerUiRenders:
    def test_dropdown_placeholders_present_and_no_text_boxes(self):
        from shyfem_ui.pages.partitioning import partitioning_ui

        html = str(partitioning_ui("test"))
        # Basin and grid are chosen via rendered dropdown placeholders ...
        assert 'id="test-bas_path_picker"' in html
        assert 'id="test-grd_path_picker"' in html
        # ... not free-text path boxes.
        assert 'id="test-bas_path"' not in html
        assert 'id="test-grd_path"' not in html


class TestModuleWiring:
    def test_partitioning_renders_project_file_dropdowns(self):
        import shyfem_ui.pages.partitioning as part_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(part_mod, "partitioning_server")
        # Two render.ui dropdowns backed by a project-dir scan ...
        assert "def bas_path_picker(" in src
        assert "def grd_path_picker(" in src
        assert "def output_dir_picker(" in src
        # ... built on the shared project_select helpers, preselecting the
        # project's default basin/grid like the old text boxes auto-filled.
        assert 'project_file_select(\n            "bas_path"' in src
        assert 'project_file_select(\n            "grd_path"' in src
        assert 'project_dir_select(\n            "output_dir"' in src
        assert 'default_project_file(proj, "bas")' in src
        assert 'default_project_file(proj, "grd")' in src
        # ... and the old file_picker / free-text wiring is gone.
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
        assert not hasattr(part_mod, "file_picker_server")
