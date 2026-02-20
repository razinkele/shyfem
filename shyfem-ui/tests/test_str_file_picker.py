"""Tests for STR editor file picker integration."""

import pytest


class TestDetectFileParams:

    def test_wind_detected_as_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("wind") is True

    def test_boundn_detected_as_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("boundn") is True

    def test_idt_not_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("idt") is False

    def test_ilin_not_file_param(self):
        from shyfem_ui.components.file_picker import is_file_param
        assert is_file_param("ilin") is False


class TestBuildFormPanelWithFilePicker:
    """Test that _build_form_panel uses file picker for file params when project_id is set."""

    def test_form_panel_renders_file_picker_for_wind(self):
        from shyfem_ui.services.parser_str import StrParser
        from shyfem_ui.components.str_editor import _build_form_panel

        content = "$name\n    wind = 'INPUT/wind.fem'\n$end\n"
        parsed = StrParser.parse(content)
        # With project_id=123, file params should get file_picker_ui
        html = _build_form_panel(parsed, project_id=123)
        rendered = str(html)
        # Should contain file-picker-component class (from file_picker_ui)
        assert "file-picker-component" in rendered

    def test_form_panel_renders_text_input_without_project(self):
        from shyfem_ui.services.parser_str import StrParser
        from shyfem_ui.components.str_editor import _build_form_panel

        content = "$name\n    wind = 'INPUT/wind.fem'\n$end\n"
        parsed = StrParser.parse(content)
        # Without project_id, should fall back to text input
        html = _build_form_panel(parsed, project_id=None)
        rendered = str(html)
        assert "file-picker-component" not in rendered

    def test_form_panel_regular_param_unaffected(self):
        from shyfem_ui.services.parser_str import StrParser
        from shyfem_ui.components.str_editor import _build_form_panel

        content = "$para\n    idt = 300\n$end\n"
        parsed = StrParser.parse(content)
        html = _build_form_panel(parsed, project_id=123)
        rendered = str(html)
        # idt should NOT get a file picker
        assert "file-picker-component" not in rendered
