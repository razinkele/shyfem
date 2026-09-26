"""Tests for STR editor file picker integration."""


class TestDetectFileParams:

    def test_wind_detected_as_file_param(self):
        from shyfem_ui.components.project_select import is_file_param

        assert is_file_param("wind") is True

    def test_boundn_detected_as_file_param(self):
        from shyfem_ui.components.project_select import is_file_param

        assert is_file_param("boundn") is True

    def test_idt_not_file_param(self):
        from shyfem_ui.components.project_select import is_file_param

        assert is_file_param("idt") is False

    def test_ilin_not_file_param(self):
        from shyfem_ui.components.project_select import is_file_param

        assert is_file_param("ilin") is False


class TestBuildFormPanelFileFields:
    """File parameters render as a selectize-with-create over the project's
    data files (project-relative), so a name can be picked or typed. The
    field is visible with or without a project -- the old rendering hid the
    text box behind a dead file-picker whenever a project was open."""

    def _panel(self, content: str, **kwargs) -> str:
        from shyfem_ui.components.str_editor import _build_form_panel
        from shyfem_ui.services.parser_str import StrParser

        return str(_build_form_panel(StrParser.parse(content), **kwargs))

    def test_wind_renders_selectize_with_create_and_current_value(self):
        html = self._panel(
            "$name\n    wind = 'INPUT/wind.fem'\n$end\n",
            project_id=123,
            file_choices=["INPUT/wind.fem", "INPUT/rain.fem"],
        )
        assert 'id="form_name_wind"' in html
        assert '"create": true' in html
        assert '<option value="INPUT/wind.fem" selected="">INPUT/wind.fem</option>' in html
        assert '<option value="INPUT/rain.fem">INPUT/rain.fem</option>' in html
        # no dead picker, no hidden text box for the file field
        assert "file-picker-component" not in html
        assert "display:none" not in html
        assert 'id="form_name_wind" type="text"' not in html

    def test_file_field_renders_without_project_and_keeps_unlisted_value(self):
        html = self._panel("$name\n    wind = 'custom/w.dat'\n$end\n", project_id=None)
        assert 'id="form_name_wind"' in html
        assert '"create": true' in html
        assert '<option value="custom/w.dat" selected="">custom/w.dat</option>' in html

    def test_regular_param_stays_text_input(self):
        html = self._panel("$para\n    idt = 300\n$end\n", project_id=123, file_choices=["a.txt"])
        assert 'id="form_para_idt"' in html
        assert '"create": true' not in html


class TestEditorsReceiveProjectFileChoices:
    def test_str_editor_server_accepts_file_choices_and_passes_them_to_the_panel(self):
        import inspect

        from shyfem_ui.components import str_editor as mod
        from tests._test_helpers import get_server_source

        inner = mod.str_editor_server.__closure__[0].cell_contents
        assert "file_choices" in inspect.signature(inner).parameters
        src = get_server_source(mod, "str_editor_server")
        assert "choices = list(file_choices()) if file_choices is not None else []" in src
        assert "file_choices=choices" in src
        assert "file_picker_ui" not in inspect.getsource(mod)

    def test_boundary_editor_server_accepts_file_choices_and_uses_selectize(self):
        import inspect

        from shyfem_ui.components import boundary_editor as mod
        from tests._test_helpers import get_server_source

        inner = mod.boundary_editor_server.__closure__[0].cell_contents
        assert "file_choices" in inspect.signature(inner).parameters
        src = get_server_source(mod, "boundary_editor_server")
        assert (
            "str_file_selectize(\n" in src
            and 'f"bound_file_{bid}", "", b["boundn"], choices' in src
        )
        # computed once per render (inside boundary_list), not per row
        render = src[src.index("def boundary_list(") :]
        assert render.index("choices = list(file_choices())") < render.index("for b in bounds:")

    def test_simulation_wires_one_choices_closure_into_both_editors(self):
        import shyfem_ui.pages.simulation as mod
        from tests._test_helpers import get_server_source

        src = get_server_source(mod, "simulation_server")
        assert "def _str_file_choices()" in src
        assert "project_rel_file_choices_cached(_str_choices_cache, proj, usr, config)" in src
        assert "file_choices=_str_file_choices" in src
        assert src.count("file_choices=_str_file_choices") == 2

    def test_physics_file_fields_use_selectize(self):
        import inspect

        import shyfem_ui.pages.physics as mod
        from tests._test_helpers import get_server_source

        block = inspect.getsource(mod._assimil_block)
        assert "file_choices" in inspect.signature(mod._assimil_block).parameters
        assert block.count("str_file_selectize(") == 2
        assert "ui.input_text(" not in block
        src = get_server_source(mod, "physics_server")
        assert "def _str_file_choices()" in src
        assert 'str_file_selectize(\n                        "boundn"' in src
        assert '_assimil_block(sf, "Temperature", "t", 12, choices)' in src
