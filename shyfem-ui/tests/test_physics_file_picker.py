"""Unit tests for physics page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_str_path(self):
        from shyfem_ui.pages.physics import physics_ui

        tag = physics_ui("test")
        html = str(tag)

        assert 'id="test-fp_str-file_select"' in html
        picker_pos = html.find('id="test-fp_str-file_select"')
        input_pos = html.find('id="test-str_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_physics_wires_file_picker_server(self):
        import shyfem_ui.pages.physics as page_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "physics_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["str"]' in src
        assert 'fill_picker_input("str_path"' in src
        # Pin that physics_server has an _on_project_changed effect
        # (historically absent; the rollout adds one).
        assert "_on_project_changed" in src
        assert "reactive.isolate()" in src
