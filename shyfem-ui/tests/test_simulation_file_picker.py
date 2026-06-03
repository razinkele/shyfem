"""Unit tests for simulation page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_str_path(self):
        from shyfem_ui.pages.simulation import simulation_ui

        tag = simulation_ui("test")
        html = str(tag)

        assert 'id="test-fp_str-file_select"' in html
        picker_pos = html.find('id="test-fp_str-file_select"')
        input_pos = html.find('id="test-str_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_simulation_wires_file_picker_server(self):
        import shyfem_ui.pages.simulation as page_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "simulation_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["str"]' in src
        import re

        assert re.search(r'fill_picker_input\(\s*"str_path"', src)
        # _on_project_changed gets isolate+empty-guard.
        # _on_tutorial_context typically does not read input.X() so
        # may add no isolate block. Pin to >= 1.
        assert src.count("reactive.isolate()") >= 1
        # Critical: pin that simulation reuses project_id_reactive
        # (existing reactive feeding str_editor_server) and did NOT
        # accidentally introduce a duplicate project_id_val.
        assert "project_id=project_id_reactive" in src, (
            "simulation must reuse project_id_reactive, not introduce "
            "a new project_id_val (would orphan str_editor_server)"
        )
