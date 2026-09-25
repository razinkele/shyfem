"""Unit tests for the physics page's project-file STR dropdown."""


class TestPickerUiRenders:
    def test_dropdown_placeholder_present_and_no_text_box(self):
        from shyfem_ui.pages.physics import physics_ui

        html = str(physics_ui("test"))
        # The STR file is chosen via a rendered dropdown placeholder ...
        assert 'id="test-str_path_picker"' in html
        # ... not a free-text path box nor the old modal file picker.
        assert 'id="test-str_path"' not in html
        assert 'id="test-fp_str-file_select"' not in html


class TestModuleWiring:
    def test_physics_renders_project_file_dropdown(self):
        import shyfem_ui.pages.physics as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "physics_server")
        # One render.ui dropdown backed by a project-dir scan ...
        assert "def str_path_picker(" in src
        # ... built on the shared project_select helper, preselecting the
        # first simulation's STR like the old text box auto-filled.
        assert 'project_file_select(\n            "str_path"' in src
        assert 'default_project_file(proj, "str")' in src
        # ... and the old file_picker / auto-fill wiring is gone.
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
        assert "_on_project_changed" not in src
        assert 'ui.update_text(\n                        "str_path"' not in src
        assert not hasattr(page_mod, "file_picker_server")
        assert not hasattr(page_mod, "fill_picker_input")

    def test_load_and_save_still_read_and_confine_str_path(self):
        import shyfem_ui.pages.physics as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "physics_server")
        # Option values are absolute paths, so the handlers keep reading
        # input.str_path() and re-confining it.
        assert "config.confine_path(input.str_path(), _usr, must_exist=True)" in src
        assert "path_str = input.str_path()" in src
        assert "config.confine_path(path_str, _usr, for_write=True)" in src
