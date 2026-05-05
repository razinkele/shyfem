"""Unit tests for postprocess page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_shy_path(self):
        from shyfem_ui.pages.postprocess import postprocess_ui

        tag = postprocess_ui("test")
        html = str(tag)

        assert 'id="test-fp_shy-file_select"' in html
        picker_pos = html.find('id="test-fp_shy-file_select"')
        input_pos = html.find('id="test-shy_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_postprocess_wires_file_picker_server(self):
        import shyfem_ui.pages.postprocess as page_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "postprocess_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["output"]' in src
        import re; assert re.search(r'fill_picker_input\(\s*"shy_path"', src)
        assert "reactive.isolate()" in src
