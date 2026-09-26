"""Unit tests for the dashboard's Import Grid modal: the grid is chosen from a
dropdown of ``.grd`` files under the *target* project's directory, not typed
as a free-text path."""

from pathlib import Path

import pytest

from shyfem_ui.config import Config


class TestProjectLookup:
    def test_finds_project_row_by_id_string(self):
        from shyfem_ui.pages.home import _project_by_id

        rows = [
            {"id": 3, "name": "a", "work_dir": "/x/a"},
            {"id": 7, "name": "b", "work_dir": "/x/b"},
        ]
        assert _project_by_id(rows, "7") == rows[1]
        assert _project_by_id(rows, 3) == rows[0]

    @pytest.mark.parametrize("pid", ["", None, "abc", "99"])
    def test_none_when_unselected_or_unknown(self, pid):
        from shyfem_ui.pages.home import _project_by_id

        rows = [{"id": 3, "name": "a", "work_dir": "/x/a"}]
        assert _project_by_id(rows, pid) is None


class TestPickerLists:
    def test_lists_grd_files_under_target_project(self, tmp_path: Path):
        """The dropdown offers the target project's .grd files (values are
        absolute paths, so the unchanged confine-and-copy handler keeps
        working) and nothing else."""
        from shyfem_ui.components.project_select import project_file_select

        root = tmp_path / "proj"
        (root / "GRID").mkdir(parents=True)
        (root / "GRID" / "mesh.grd").write_text("")
        (root / "notes.txt").write_text("")
        config = Config(deployment_mode="local", work_dir=str(tmp_path))
        proj = {"id": 1, "name": "proj", "work_dir": str(root)}

        html = str(
            project_file_select(
                "import_grd_path",
                "Grid File (.grd)",
                (".grd",),
                proj=proj,
                user=None,
                config=config,
            )
        )
        assert 'id="import_grd_path"' in html
        assert f'value="{root / "GRID" / "mesh.grd"}"' in html
        assert "notes.txt" not in html

    def test_prompts_when_no_project_selected(self, tmp_path: Path):
        from shyfem_ui.components.project_select import project_file_select

        config = Config(deployment_mode="local", work_dir=str(tmp_path))
        html = str(
            project_file_select(
                "import_grd_path",
                "Grid File (.grd)",
                (".grd",),
                proj=None,
                user=None,
                config=config,
            )
        )
        assert "Open a project" in html
        assert "disabled" in html  # placeholder select, so the input id still exists


class TestModuleWiring:
    def test_import_grid_modal_uses_project_file_dropdown(self):
        import shyfem_ui.pages.home as home_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(home_mod, "home_server")
        # The modal carries a rendered dropdown placeholder ...
        assert 'ui.output_ui("import_grd_path_picker")' in src
        # ... rendered from the target project chosen in the modal ...
        assert "def import_grd_path_picker(" in src
        assert 'project_file_select(\n            "import_grd_path"' in src
        assert "input.import_project_id()" in src
        # ... and the free-text path box is gone.
        assert '"import_grd_path",\n                "Grid File Path (.grd)"' not in src
        assert 'ui.input_text(\n                "import_grd_path"' not in src
        # New-project directory and grid name stay free text.
        assert 'ui.input_text(\n                "import_grid_name"' in src
        # The import handler still reads and confines the selected value.
        assert "grd_path_str = input.import_grd_path()" in src
        assert "config.confine_path(grd_path_str, _usr, must_exist=True)" in src
        # A pick that already sits in GRID/ is registered, not copied onto itself.
        assert "dest_path.samefile(src_path)" in src
