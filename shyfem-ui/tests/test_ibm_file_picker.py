"""Unit tests for ibm page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_lgr_path(self):
        from shyfem_ui.pages.ibm import ibm_ui

        tag = ibm_ui("test")
        html = str(tag)

        assert 'id="test-fp_lgr-file_select"' in html
        picker_pos = html.find('id="test-fp_lgr-file_select"')
        input_pos = html.find('id="test-lgr_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_ibm_wires_file_picker_server(self):
        import shyfem_ui.pages.ibm as page_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "ibm_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["lagrangian"]' in src
        import re; assert re.search(r'fill_picker_input\(\s*"lgr_path"', src)
        assert "reactive.isolate()" in src


class TestLagrangianFileType:
    """Pin the dependency between ibm.py and the FileService taxonomy."""

    def test_lgr_extension_maps_to_lagrangian_file_type(self):
        from shyfem_ui.services.file_service import FileService

        assert FileService._infer_file_type("trajectories.lgr") == "lagrangian"


class TestGlobFallbackProvenance:
    """Section M.2: when ibm_server's _on_project_changed fills lgr_path
    from the work_dir glob (rather than a picker click), it must emit a
    logger.info so ops can distinguish the two provenance paths.

    Pins the log-string contract: a future refactor that drops the log
    line silently brings back the unobservable-provenance bug.
    """

    def test_glob_fallback_path_emits_info_log(self):
        """Source-inspection: the source of ibm_server contains the
        provenance log call inside the glob-fill branch.
        """
        import shyfem_ui.pages.ibm as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "ibm_server")
        # The log message must mention "filled lgr_path from" and
        # "glob" so log consumers can grep for the provenance event.
        assert "logger.info(" in src
        assert "filled lgr_path from work_dir glob" in src
