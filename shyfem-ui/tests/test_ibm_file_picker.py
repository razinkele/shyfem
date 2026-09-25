"""Unit tests for the IBM page's project-file dropdown (LGR file)."""

import pytest


class TestPickerUiRenders:
    def test_dropdown_placeholder_present_and_no_text_box(self):
        # ibm_ui() renders an install hint instead of the page without it.
        pytest.importorskip("shiny_deckgl")
        from shyfem_ui.pages.ibm import ibm_ui

        html = str(ibm_ui("test"))
        # The .lgr file is chosen via a rendered dropdown placeholder ...
        assert 'id="test-lgr_path_picker"' in html
        # ... not a free-text path box, and the old FileService picker is gone.
        assert 'id="test-lgr_path"' not in html
        assert "fp_lgr" not in html


class TestModuleWiring:
    def test_ibm_renders_project_file_dropdown(self):
        import shyfem_ui.pages.ibm as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "ibm_server")
        # One render.ui dropdown backed by a project-dir scan ...
        assert "def lgr_path_picker(" in src
        # ... built on the shared project_select helper, preselecting the
        # project's first .lgr like the old text box auto-filled.
        assert 'project_file_select(\n            "lgr_path"' in src
        assert 'list_project_files(root, (".lgr",))' in src
        # ... and the old file_picker / free-text wiring is gone.
        assert "file_picker_server(" not in src
        assert "fill_picker_input(" not in src
        assert "project_id_val" not in src
        assert not hasattr(page_mod, "file_picker_server")
        assert not hasattr(page_mod, "fill_picker_input")


class TestGlobFallbackRemoved:
    """The dropdown lists the project's .lgr files itself (recursively), so
    the old ``Path(work).glob("*.lgr")`` auto-fill and its provenance INFO
    log ("filled lgr_path from work_dir glob") are gone: there is no second
    provenance path left to distinguish.
    """

    def test_no_work_dir_glob_or_provenance_log(self):
        import shyfem_ui.pages.ibm as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "ibm_server")
        assert '.glob("*.lgr")' not in src
        assert "filled lgr_path from work_dir glob" not in src
        assert 'ui.update_text("lgr_path"' not in src
