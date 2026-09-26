"""Unit tests for the simulation page's project-file STR dropdown."""

import re


class TestPickerUiRenders:
    def test_dropdown_placeholder_present_and_no_text_box(self):
        from shyfem_ui.pages.simulation import simulation_ui

        html = str(simulation_ui("test"))
        # The STR file is chosen via a rendered dropdown placeholder ...
        assert 'id="test-str_path_picker"' in html
        # ... not a free-text path box nor the old companion file picker.
        assert 'id="test-str_path"' not in html
        assert 'id="test-fp_str-file_select"' not in html
        # Save As still takes a NEW filename as text (out of scope here); the
        # modal is built server-side so nothing to assert in the static UI.


class TestModuleWiring:
    def test_simulation_renders_project_file_dropdown(self):
        import shyfem_ui.pages.simulation as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "simulation_server")
        # One render.ui dropdown backed by a project-dir scan ...
        assert "def str_path_picker(" in src
        # ... built on the shared project_select helper, preselecting the
        # project's first simulation STR like the old text box auto-filled.
        assert 'project_file_select(\n            "str_path"' in src
        assert 'default_project_file(proj, "str")' in src
        # ... and the old file_picker / free-text wiring is gone.
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
        assert 'ui.update_text("str_path"' not in src
        assert "_on_project_changed" not in src
        assert not hasattr(page_mod, "file_picker_server")
        assert not hasattr(page_mod, "fill_picker_input")
        assert not hasattr(page_mod, "file_picker_ui")
        # str_editor_server still consumes the project_id reactive.
        assert "project_id=project_id_reactive" in src

    def test_sample_tutorial_and_save_share_one_preselect_reactive(self):
        import shyfem_ui.pages.simulation as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "simulation_server")
        # Exactly one page-level preselect reactive ...
        assert src.count("preselect_str = reactive.value(None)") == 1
        # ... set by the sample loader, the tutorial hand-off and Save As ...
        assert re.search(r'preselect_str\.set\(\(str\(str_path\), "Sample"\)\)', src)
        assert re.search(r'"Tutorial"\)\)', src)
        assert re.search(r'preselect_str\.set\(\(str\(path\), "Saved"\)\)', src)
        # ... and read by the render so it re-renders and injects the option.
        picker_src = src[src.index("def str_path_picker(") : src.index("# State")]
        assert "preselect_str.get()" in picker_src
        assert "extra=" in picker_src
        assert "selected=" in picker_src


class TestPreselectExtraOption:
    """The injected-option rule: only paths outside the project get an extra."""

    def test_path_inside_project_is_not_injected(self, tmp_path):
        from shyfem_ui.pages.simulation import _preselect_option

        proj = {"work_dir": str(tmp_path)}
        inside = tmp_path / "sub" / "sim.str"
        selected, extra = _preselect_option((str(inside), "Saved"), proj)
        assert selected == str(inside.resolve())
        assert extra is None

    def test_path_outside_project_is_injected_with_origin_label(self, tmp_path):
        from shyfem_ui.pages.simulation import _preselect_option

        proj = {"work_dir": str(tmp_path / "proj")}
        outside = tmp_path / "testcases" / "mar_menor" / "mm_hyd_03.str"
        selected, extra = _preselect_option((str(outside), "Sample"), proj)
        assert selected == str(outside)
        assert extra == {str(outside): "Sample: mm_hyd_03.str"}

    def test_tutorial_label(self, tmp_path):
        from shyfem_ui.pages.simulation import _preselect_option

        proj = {"work_dir": str(tmp_path / "proj")}
        tut = tmp_path / "tutorial" / "mm_hyd_00.str"
        _, extra = _preselect_option((str(tut), "Tutorial"), proj)
        assert extra == {str(tut): "Tutorial: mm_hyd_00.str"}

    def test_no_project_counts_as_outside(self, tmp_path):
        from shyfem_ui.pages.simulation import _preselect_option

        p = tmp_path / "x.str"
        assert _preselect_option((str(p), "Sample"), None) == (
            str(p),
            {str(p): "Sample: x.str"},
        )
        assert _preselect_option((str(p), "Sample"), {"work_dir": ""})[1] is not None

    def test_no_preselect(self):
        from shyfem_ui.pages.simulation import _preselect_option

        assert _preselect_option(None, {"work_dir": "/tmp"}) == (None, None)

    def test_dotdot_inside_prefix_is_outside(self, tmp_path):
        from shyfem_ui.pages.simulation import _preselect_option

        proj = {"work_dir": str(tmp_path / "proj")}
        sneaky = tmp_path / "proj" / ".." / "other" / "a.str"
        _, extra = _preselect_option((str(sneaky), "Saved"), proj)
        assert extra is not None
