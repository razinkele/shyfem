"""The four fields that name a NEW thing (project folder, upload subdir,
Save As path, mesh export name) are create-capable pickers: existing entries
offered, any name still typeable. Source/render-level wiring tests in the
style of the picker suites."""

import inspect

from tests._test_helpers import get_server_source


class TestHomeProjectFolder:
    def test_modal_uses_folder_selectize_rooted_in_the_caller_area(self):
        import shyfem_ui.pages.home as mod

        src = get_server_source(mod, "home_server")
        assert 'str_file_selectize(\n                "project_dir"' in src
        assert "dir_name_choices(root)" in src
        assert 'config.user_data_root / user["username"]' in src
        assert 'ui.input_text(\n                "project_dir"' not in src

    def test_create_roots_a_bare_name_before_validating(self):
        import shyfem_ui.pages.home as mod

        src = get_server_source(mod, "home_server")
        create = src[src.index("def _create_project(") :]
        norm = create.index("if not Path(work_dir).is_absolute():")
        assert norm < create.index("config.confine_path(candidate")
        assert norm < create.index("config.validate_save_path(work_dir)")


class TestFilesUploadSubdir:
    def test_upload_card_offers_project_subdirs_and_accepts_typed_names(self):
        import shyfem_ui.pages.files as mod

        src = get_server_source(mod, "files_server")
        assert 'str_file_selectize(\n                "upload_subdir"' in src
        assert "project_rel_dir_choices(" in src
        assert 'ui.input_text(\n                "upload_subdir"' not in src
        # consumer unchanged: empty -> project root
        assert "subdir = input.upload_subdir() or None" in src


class TestSimulationSaveAs:
    def test_modal_offers_project_str_files_relative_and_suggests_copy(self):
        import shyfem_ui.pages.simulation as mod

        src = get_server_source(mod, "simulation_server")
        show = src[src.index("def _show_save_modal(") : src.index("def _confirm_save(")]
        assert 'str_file_selectize(\n                "save_path"' in show
        assert 'project_rel_file_choices(proj, usr, config, (".str",))' in show
        assert "_copy.str" in show
        assert "ui.input_text(" not in show

    def test_confirm_save_roots_relative_values_then_confines(self):
        import shyfem_ui.pages.simulation as mod

        src = get_server_source(mod, "simulation_server")
        confirm = src[src.index("def _confirm_save(") :]
        root = confirm.index("if not Path(path_str).is_absolute():")
        assert root < confirm.index("config.confine_path(path_str, _usr, for_write=True)")
        assert "Open a project to save a relative path" in confirm


class TestMeshExportFilename:
    def test_export_panel_renders_picker_and_download_name_is_a_basename(self):
        import shyfem_ui.pages.mesh_builder as mod

        panel = inspect.getsource(mod._step_export_panel)
        assert 'ui.output_ui("export_filename_picker")' in panel
        assert 'ui.input_text(\n                "export_filename"' not in panel
        src = get_server_source(mod, "mesh_builder_server")
        assert "def export_filename_picker(" in src
        assert 'project_rel_file_choices(proj, usr, config, (".grd",))' in src
        assert 'Path(input.export_filename() or "mesh_output.grd").name' in src

    def test_helper_signature_has_placeholder(self):
        from shyfem_ui.components.project_select import str_file_selectize

        assert "placeholder" in inspect.signature(str_file_selectize).parameters
