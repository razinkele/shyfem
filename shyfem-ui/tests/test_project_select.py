"""Unit tests for the shared project-file / project-dir dropdown helpers.

These back every page that replaced a free-text path box with a dropdown of
files (or directories) under the active project's work_dir.
"""

from pathlib import Path

import pytest

from shyfem_ui.config import Config
from shyfem_ui.services.project_files import list_project_dirs


@pytest.fixture
def project_tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "INPUT").mkdir(parents=True)
    (root / "GRID" / "sub").mkdir(parents=True)
    (root / ".boxmodel_cache" / "run1").mkdir(parents=True)
    (root / "OUT").mkdir()
    (root / "a.str").write_text("$title\n$end\n")
    (root / "INPUT" / "b.str").write_text("$title\n$end\n")
    (root / "GRID" / "mesh.grd").write_text("")
    (root / "GRID" / "mesh.bas").write_bytes(b"")
    (root / "OUT" / "hydro.shy").write_bytes(b"")
    (root / ".boxmodel_cache" / "run1" / "x.str").write_text("")
    return root


@pytest.fixture
def config(project_tree: Path) -> Config:
    # Local mode: confine_path resolves against the shared roots and imposes
    # no per-user sandbox, so tmp_path projects are reachable.
    return Config(deployment_mode="local", work_dir=str(project_tree.parent))


def _proj(root: Path, **extra) -> dict:
    base = {
        "id": 1,
        "name": "proj",
        "work_dir": str(root),
        "description": None,
        "grids": [],
        "simulations": [],
        "files": [],
    }
    base.update(extra)
    return base


class TestListProjectDirs:
    def test_lists_root_and_non_hidden_subdirs_relative(self, project_tree):
        got = list_project_dirs(project_tree)
        assert got[0] == "."
        assert "INPUT" in got and "GRID" in got and "OUT" in got
        assert str(Path("GRID") / "sub") in got
        assert not any(part.startswith(".") for d in got for part in Path(d).parts if d != ".")

    def test_respects_max_depth(self, project_tree):
        got = list_project_dirs(project_tree, max_depth=1)
        assert "GRID" in got
        assert str(Path("GRID") / "sub") not in got

    def test_caps_result_count(self, tmp_path):
        for i in range(30):
            (tmp_path / f"d{i:02d}").mkdir()
        got = list_project_dirs(tmp_path, max_dirs=5)
        assert len(got) == 5
        assert got[0] == "."

    def test_symlinked_dirs_are_not_followed(self, project_tree, tmp_path):
        other = tmp_path / "elsewhere" / "secret"
        other.mkdir(parents=True)
        (project_tree / "link").symlink_to(other.parent, target_is_directory=True)
        got = list_project_dirs(project_tree)
        assert "link" not in got
        assert not any("secret" in d for d in got)

    def test_missing_root_returns_empty(self, tmp_path):
        assert list_project_dirs(tmp_path / "nope") == []


class TestProjectFileSelect:
    def test_no_project_renders_prompt(self, config):
        from shyfem_ui.components.project_select import project_file_select

        html = str(
            project_file_select(
                "str_path", "STR file", (".str",), proj=None, user=None, config=config
            )
        )
        assert "Open a project" in html
        assert "disabled" in html  # placeholder select, so the input id still exists

    def test_no_project_but_extra_renders_select_with_extra_only(self, config, tmp_path):
        from shyfem_ui.components.project_select import project_file_select

        sample = tmp_path / "mm_hyd_03.str"
        sample.write_text("")
        html = str(
            project_file_select(
                "str_path",
                "STR file",
                (".str",),
                proj=None,
                user=None,
                config=config,
                selected=str(sample),
                extra={str(sample): "Sample: mm_hyd_03.str"},
            )
        )
        assert "<select" in html
        assert f'<option value="{sample}" selected="">Sample: mm_hyd_03.str</option>' in html
        assert "Open a project" not in html

    def test_lists_matching_files_with_absolute_values(self, config, project_tree):
        from shyfem_ui.components.project_select import project_file_select

        html = str(
            project_file_select(
                "str_path",
                "STR file",
                (".str",),
                proj=_proj(project_tree),
                user=None,
                config=config,
            )
        )
        assert 'id="str_path"' in html
        assert f'value="{project_tree / "a.str"}"' in html
        assert f'value="{project_tree / "INPUT" / "b.str"}"' in html
        assert ">INPUT/b.str<" in html
        # hidden trees and other extensions are excluded
        assert ".boxmodel_cache" not in html
        assert "mesh.grd" not in html
        # empty placeholder option first, selected by default
        assert 'value=""' in html

    def test_no_matching_files_renders_notice(self, config, project_tree):
        from shyfem_ui.components.project_select import project_file_select

        html = str(
            project_file_select(
                "lgr", "LGR file", (".lgr",), proj=_proj(project_tree), user=None, config=config
            )
        )
        assert "No .lgr files" in html
        assert 'id="lgr"' in html and "disabled" in html

    def test_selected_preselects_when_in_choices(self, config, project_tree):
        from shyfem_ui.components.project_select import project_file_select

        want = str(project_tree / "INPUT" / "b.str")
        html = str(
            project_file_select(
                "str_path",
                "STR file",
                (".str",),
                proj=_proj(project_tree),
                user=None,
                config=config,
                selected=want,
            )
        )
        assert f'<option value="{want}" selected="">' in html

    def test_extra_path_outside_project_is_injected_and_selected(
        self, config, project_tree, tmp_path
    ):
        from shyfem_ui.components.project_select import project_file_select

        sample = tmp_path / "samples" / "mm_hyd_03.str"
        sample.parent.mkdir()
        sample.write_text("")
        html = str(
            project_file_select(
                "str_path",
                "STR file",
                (".str",),
                proj=_proj(project_tree),
                user=None,
                config=config,
                selected=str(sample),
                extra={str(sample): "Sample: mm_hyd_03.str"},
            )
        )
        assert f'<option value="{sample}" selected="">Sample: mm_hyd_03.str</option>' in html

    def test_extra_alone_renders_select_even_without_project_files(
        self, config, project_tree, tmp_path
    ):
        from shyfem_ui.components.project_select import project_file_select

        sample = tmp_path / "s.lgr"
        sample.write_bytes(b"")
        html = str(
            project_file_select(
                "lgr",
                "LGR",
                (".lgr",),
                proj=_proj(project_tree),
                user=None,
                config=config,
                extra={str(sample): "Sample: s.lgr"},
            )
        )
        assert "<select" in html and "Sample: s.lgr" in html

    def test_multiple_renders_selectize_without_placeholder_option(self, config, project_tree):
        from shyfem_ui.components.project_select import project_file_select

        html = str(
            project_file_select(
                "batch",
                "Files",
                (".shy",),
                proj=_proj(project_tree),
                user=None,
                config=config,
                multiple=True,
            )
        )
        assert "multiple" in html
        assert f'value="{project_tree / "OUT" / "hydro.shy"}"' in html
        assert 'value=""' not in html

    def test_unavailable_project_dir_renders_notice(self, config, tmp_path):
        from shyfem_ui.components.project_select import project_file_select

        html = str(
            project_file_select(
                "x", "X", (".str",), proj=_proj(tmp_path / "gone"), user=None, config=config
            )
        )
        assert "unavailable" in html.lower()
        assert 'id="x"' in html and "disabled" in html

    def test_include_runs_adds_manifest_run_files(
        self, config, project_tree, tmp_path, monkeypatch
    ):
        from shyfem_ui.components import project_select as ps

        run_dir = tmp_path / "runs" / "r1"
        run_dir.mkdir(parents=True)
        (run_dir / "out.shy").write_bytes(b"")

        class _Run:
            dir = str(run_dir)
            label = "Run one"

        class _Manifest:
            runs = [_Run()]

        monkeypatch.setattr(ps, "_load_manifest_or_none", lambda root, config, user: _Manifest())
        html = str(
            ps.project_file_select(
                "shy",
                "Output",
                (".shy", ".nc"),
                proj=_proj(project_tree),
                user=None,
                config=config,
                include_runs=True,
            )
        )
        assert f'value="{run_dir / "out.shy"}"' in html
        assert "Run one / out.shy" in html


class TestSymlinkedWorkDir:
    def test_selected_via_symlinked_work_dir_still_matches_resolved_option(
        self, config, project_tree, tmp_path
    ):
        """default_project_file builds `selected` from the raw work_dir; option
        values come from the confine_path-resolved root. They must still match."""
        from shyfem_ui.components.project_select import (
            default_project_file,
            project_dir_select,
            project_file_select,
        )

        link = tmp_path / "link"
        link.symlink_to(project_tree, target_is_directory=True)
        proj = _proj(link, simulations=[{"name": "s", "str_file": "INPUT/b.str"}])
        want = default_project_file(proj, "str")
        assert want == str(link / "INPUT" / "b.str")
        html = str(
            project_file_select(
                "str_path", "STR", (".str",), proj=proj, user=None, config=config, selected=want
            )
        )
        assert f'<option value="{project_tree / "INPUT" / "b.str"}" selected="">' in html
        html = str(
            project_dir_select(
                "wd", "WD", proj=proj, user=None, config=config, selected=str(link / "OUT")
            )
        )
        assert f'<option value="{project_tree / "OUT"}" selected="">' in html


class TestProjectDirSelect:
    def test_no_project_renders_prompt(self, config):
        from shyfem_ui.components.project_select import project_dir_select

        html = str(
            project_dir_select("output_dir", "Output dir", proj=None, user=None, config=config)
        )
        assert "Open a project" in html
        assert "disabled" in html  # placeholder select, so the input id still exists

    def test_lists_root_and_subdirs_with_absolute_values(self, config, project_tree):
        from shyfem_ui.components.project_select import project_dir_select

        html = str(
            project_dir_select(
                "output_dir",
                "Output dir",
                proj=_proj(project_tree),
                user=None,
                config=config,
                default_label="— same as input file —",
            )
        )
        assert 'id="output_dir"' in html
        assert '<option value="" selected="">— same as input file —</option>' in html
        assert f'value="{project_tree}"' in html
        assert f'value="{project_tree / "GRID" / "sub"}"' in html
        assert ".boxmodel_cache" not in html
        # root is labelled as the project itself, not "."
        assert ">proj/<" in html

    def test_no_default_label_preselects_root(self, config, project_tree):
        from shyfem_ui.components.project_select import project_dir_select

        html = str(
            project_dir_select(
                "working_dir", "Working dir", proj=_proj(project_tree), user=None, config=config
            )
        )
        assert 'value=""' not in html
        assert f'<option value="{project_tree}" selected="">' in html

    def test_selected_subdir_is_honoured(self, config, project_tree):
        from shyfem_ui.components.project_select import project_dir_select

        want = str(project_tree / "OUT")
        html = str(
            project_dir_select(
                "working_dir",
                "Working dir",
                proj=_proj(project_tree),
                user=None,
                config=config,
                selected=want,
            )
        )
        assert f'<option value="{want}" selected="">' in html


class TestProjectDirSelectExtra:
    def test_extra_dir_outside_project_is_injected_and_selected(
        self, config, project_tree, tmp_path
    ):
        from shyfem_ui.components.project_select import project_dir_select

        sample = tmp_path / "mar_menor"
        sample.mkdir()
        html = str(
            project_dir_select(
                "working_dir",
                "Working dir",
                proj=_proj(project_tree),
                user=None,
                config=config,
                selected=str(sample),
                extra={str(sample): "Sample: mar_menor/"},
            )
        )
        assert f'<option value="{sample}" selected="">Sample: mar_menor/</option>' in html
        assert f'value="{project_tree}"' in html

    def test_no_project_but_extra_renders_select_with_extra_only(self, config, tmp_path):
        from shyfem_ui.components.project_select import project_dir_select

        sample = tmp_path / "mar_menor"
        sample.mkdir()
        html = str(
            project_dir_select(
                "working_dir",
                "Working dir",
                proj=None,
                user=None,
                config=config,
                extra={str(sample): "Sample: mar_menor/"},
            )
        )
        assert "<select" in html and "Open a project" not in html
        assert f'<option value="{sample}" selected="">Sample: mar_menor/</option>' in html


class TestProjectDefaults:
    def test_default_str_and_grd_from_project_context(self, project_tree):
        from shyfem_ui.components.project_select import default_project_file

        proj = _proj(
            project_tree,
            grids=[{"grd_file": "GRID/mesh.grd", "bas_file": "GRID/mesh.bas"}],
            simulations=[{"name": "s", "str_file": "INPUT/b.str"}],
        )
        assert default_project_file(proj, "str") == str(project_tree / "INPUT" / "b.str")
        assert default_project_file(proj, "grd") == str(project_tree / "GRID" / "mesh.grd")
        assert default_project_file(proj, "bas") == str(project_tree / "GRID" / "mesh.bas")

    def test_default_is_none_when_missing(self, project_tree):
        from shyfem_ui.components.project_select import default_project_file

        assert default_project_file(None, "str") is None
        assert default_project_file(_proj(project_tree), "str") is None
        assert default_project_file(_proj(project_tree, grids=[{}]), "grd") is None


class TestStrFileSelectize:
    """Selectize-with-create for STR-content file fields: project-relative
    choices, free text still allowed, empty value round-trips as empty."""

    def test_choices_are_project_relative_and_filtered(self, config, project_tree):
        from shyfem_ui.components.project_select import (
            STR_DATA_EXTS,
            project_rel_file_choices,
        )

        got = project_rel_file_choices(_proj(project_tree), None, config)
        assert "GRID/mesh.grd" in got and "GRID/mesh.bas" in got
        # .str files are not data files an STR parameter would point at
        assert not any(c.endswith(".str") for c in got)
        assert all(not c.startswith("/") for c in got)
        assert ".grd" in STR_DATA_EXTS and ".fem" in STR_DATA_EXTS

    def test_no_project_gives_empty_choices(self, config):
        from shyfem_ui.components.project_select import project_rel_file_choices

        assert project_rel_file_choices(None, None, config) == []

    def test_empty_value_selects_the_empty_option_not_the_first_file(self):
        from shyfem_ui.components.project_select import str_file_selectize

        html = str(
            str_file_selectize("boundn", "Boundary file", "", ["INPUT/a.txt", "INPUT/b.txt"])
        )
        assert '<option value="" selected=""></option>' in html
        assert '<option value="INPUT/a.txt">INPUT/a.txt</option>' in html
        assert 'value="INPUT/a.txt" selected' not in html

    def test_value_not_in_choices_is_injected_and_selected(self):
        from shyfem_ui.components.project_select import str_file_selectize

        html = str(
            str_file_selectize("boundn", "Boundary file", "custom/tide.dat", ["INPUT/a.txt"])
        )
        assert '<option value="custom/tide.dat" selected="">custom/tide.dat</option>' in html
        assert '<option value="INPUT/a.txt">INPUT/a.txt</option>' in html

    def test_listed_value_is_preselected(self):
        from shyfem_ui.components.project_select import str_file_selectize

        html = str(str_file_selectize("boundn", "Boundary file", "INPUT/a.txt", ["INPUT/a.txt"]))
        assert '<option value="INPUT/a.txt" selected="">INPUT/a.txt</option>' in html

    def test_create_on_blur_enabled_and_placeholder_present(self):
        from shyfem_ui.components.project_select import str_file_selectize

        html = str(str_file_selectize("boundn", "Boundary file", "", []))
        assert '"create": true' in html
        assert '"createOnBlur": true' in html
        assert '"persist": false' in html
        assert "placeholder" in html
        assert 'id="boundn"' in html

    def test_none_value_treated_as_empty(self):
        from shyfem_ui.components.project_select import str_file_selectize

        html = str(str_file_selectize("boundn", "", None, []))
        assert '<option value="" selected=""></option>' in html


class TestStrChoicesCache:
    """The editors re-render on every debounced keystroke; the project scan
    behind the file-field choices must not run each time."""

    def _counting(self, monkeypatch):
        from shyfem_ui.components import project_select as ps

        calls = {"n": 0}
        real = ps.list_project_files

        def counted(root, exts, *a, **k):
            calls["n"] += 1
            return real(root, exts, *a, **k)

        monkeypatch.setattr(ps, "list_project_files", counted)
        return calls

    def test_hit_within_ttl_does_not_rescan(self, config, project_tree, monkeypatch):
        from shyfem_ui.components.project_select import project_rel_file_choices_cached

        calls = self._counting(monkeypatch)
        cache: dict = {}
        clock = {"t": 100.0}
        proj = _proj(project_tree)
        a = project_rel_file_choices_cached(cache, proj, None, config, now=lambda: clock["t"])
        clock["t"] += 5
        b = project_rel_file_choices_cached(cache, proj, None, config, now=lambda: clock["t"])
        assert a == b and calls["n"] == 1

    def test_ttl_expiry_and_project_change_rescan(
        self, config, project_tree, tmp_path, monkeypatch
    ):
        from shyfem_ui.components.project_select import project_rel_file_choices_cached

        calls = self._counting(monkeypatch)
        cache: dict = {}
        clock = {"t": 100.0}
        proj = _proj(project_tree)
        project_rel_file_choices_cached(cache, proj, None, config, now=lambda: clock["t"])
        clock["t"] += 31
        project_rel_file_choices_cached(cache, proj, None, config, now=lambda: clock["t"])
        assert calls["n"] == 2
        other = tmp_path / "other"
        other.mkdir()
        project_rel_file_choices_cached(
            cache, _proj(other, id=2), None, config, now=lambda: clock["t"]
        )
        assert calls["n"] == 3

    def test_no_project_is_cheap_and_empty(self, config, monkeypatch):
        from shyfem_ui.components.project_select import project_rel_file_choices_cached

        calls = self._counting(monkeypatch)
        assert project_rel_file_choices_cached({}, None, None, config) == []
        assert calls["n"] == 0

    def test_restart_and_gotm_namelist_extensions_are_listed(self, config, project_tree):
        from shyfem_ui.components.project_select import STR_DATA_EXTS, project_rel_file_choices

        (project_tree / "INPUT" / "warm.rst").write_bytes(b"")
        (project_tree / "INPUT" / "gotmturb.nml").write_text("")
        got = project_rel_file_choices(_proj(project_tree), None, config)
        assert "INPUT/warm.rst" in got and "INPUT/gotmturb.nml" in got
        assert ".rst" in STR_DATA_EXTS and ".nml" in STR_DATA_EXTS


class TestNameFieldHelpers:
    def test_placeholder_is_configurable(self):
        from shyfem_ui.components.project_select import str_file_selectize

        html = str(
            str_file_selectize("d", "Folder", "", ["INPUT"], placeholder="pick or type a folder")
        )
        assert '"placeholder": "pick or type a folder"' in html

    def test_project_rel_dir_choices_exclude_root_and_hidden(self, config, project_tree):
        from shyfem_ui.components.project_select import project_rel_dir_choices

        got = project_rel_dir_choices(_proj(project_tree), None, config)
        assert "." not in got
        assert "INPUT" in got and "GRID" in got and str(Path("GRID") / "sub") in got
        assert not any(".boxmodel_cache" in d for d in got)
        assert project_rel_dir_choices(None, None, config) == []

    def test_dir_name_choices_lists_only_direct_children(self, project_tree, tmp_path):
        from shyfem_ui.components.project_select import dir_name_choices

        got = dir_name_choices(project_tree)
        assert got == sorted(got)
        assert "INPUT" in got and "GRID" in got
        assert not any("/" in d for d in got)
        assert dir_name_choices(tmp_path / "missing") == []
