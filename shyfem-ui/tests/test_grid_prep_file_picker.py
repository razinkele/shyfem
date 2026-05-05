"""Unit tests for grid_prep page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_grd_path(self):
        from shyfem_ui.pages.grid_prep import grid_prep_ui

        tag = grid_prep_ui("test")
        html = str(tag)

        assert 'id="test-fp_grd-file_select"' in html
        picker_pos = html.find('id="test-fp_grd-file_select"')
        input_pos = html.find('id="test-grd_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_grid_prep_imports_and_wires_file_picker_server(self):
        import shyfem_ui.pages.grid_prep as page_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        assert hasattr(page_mod, "file_picker_server")
        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert hasattr(page_mod, "file_picker_ui")
        assert hasattr(page_mod, "fill_picker_input")
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "grid_prep_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["grid"]' in src
        assert 'fill_picker_input("grd_path"' in src
        assert "reactive.isolate()" in src
