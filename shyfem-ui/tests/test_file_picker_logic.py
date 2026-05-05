"""Pure unit tests for resolve_picker_path helper in components.file_picker.

These tests do NOT need a Shiny session — resolve_picker_path is a pure
helper that takes a dict and a string and returns a string or None.
"""

import logging

from shyfem_ui.services.project_context import ProjectContext


# Full ProjectContext-compatible literal used by happy-path tests.
# Annotated as ProjectContext (not bare dict) so mypy --strict accepts
# passing the result to resolve_picker_path (which expects
# ProjectContext | None). TypedDicts are nominal in mypy — bare dict
# literals don't satisfy the type without explicit narrowing.
def _proj(work_dir: str, project_id: int = 7) -> ProjectContext:
    return {
        "id": project_id,
        "name": "test",
        "work_dir": work_dir,
        "description": None,
        "grids": [],
        "simulations": [],
        "files": [],
    }


class TestResolvePickerPath:
    def test_resolve_picker_path_basic(self, tmp_path):
        """Happy path: project + valid rel_path resolves to absolute."""
        from shyfem_ui.components.file_picker import resolve_picker_path

        result = resolve_picker_path(_proj(str(tmp_path)), "BAS/sim.bas")
        assert result == str((tmp_path / "BAS" / "sim.bas").resolve())

    def test_resolve_picker_path_returns_none_when_no_project(self):
        from shyfem_ui.components.file_picker import resolve_picker_path

        assert resolve_picker_path(None, "anything") is None

    def test_resolve_picker_path_returns_none_when_empty_relpath(self, tmp_path):
        from shyfem_ui.components.file_picker import resolve_picker_path

        assert resolve_picker_path(_proj(str(tmp_path)), "") is None
        assert resolve_picker_path(_proj(str(tmp_path)), None) is None

    def test_resolve_picker_path_rejects_traversal(self, tmp_path, caplog):
        """Path-traversal containment guard returns None and logs warning.

        Filtered to logger 'shyfem_ui.components.file_picker' so other
        loggers' warnings don't pollute the assertion.
        """
        from shyfem_ui.components.file_picker import resolve_picker_path

        proj = _proj(str(tmp_path))

        # Case 1: ../-style traversal
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path(proj, "../../etc/passwd") is None
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "../../etc/passwd" in recs[0].getMessage()

        # Case 2: absolute path silently overrides Path / __truediv__
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path(proj, "/etc/passwd") is None
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "/etc/passwd" in recs[0].getMessage()

    def test_resolve_picker_path_rejects_shape_defects(self, caplog):
        """Missing or empty work_dir returns None and logs warning."""
        from shyfem_ui.components.file_picker import resolve_picker_path

        # Missing work_dir key entirely
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path({"id": 7}, "x") is None  # type: ignore[arg-type]
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "7" in recs[0].getMessage()

        # Empty work_dir string
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path({"id": 8, "work_dir": ""}, "x") is None  # type: ignore[arg-type]
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "8" in recs[0].getMessage()

        # Explicit work_dir=None
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path({"id": 9, "work_dir": None}, "x") is None  # type: ignore[arg-type]
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "9" in recs[0].getMessage()

    def test_resolve_picker_path_accepts_project_context_shape(self, tmp_path):
        """Test 5b: full ProjectContext-shaped dict resolves correctly."""
        from shyfem_ui.components.file_picker import resolve_picker_path

        ctx: ProjectContext = {
            "id": 7,
            "name": "test",
            "work_dir": str(tmp_path),
            "description": None,
            "grids": [{"name": "g", "grd_file": "g.grd", "bas_file": "g.bas"}],
            "simulations": [],
            "files": [],
        }
        result = resolve_picker_path(ctx, "BAS/sim.bas")
        assert result == str((tmp_path / "BAS" / "sim.bas").resolve())


class TestFillPickerInput:
    """Tests for fill_picker_input — the extracted wrapper body.

    Helper takes the unwrapped `project: ProjectContext | None` (NOT a
    reactive container). Lambdas at call sites do `active_project.get()
    if active_project else None`.

    Patch ui.update_text and ui.notification_show so the test runs
    without a Shiny session.
    """

    def _make_proj(self, tmp_path, project_id: int = 7) -> dict:
        return {
            "id": project_id, "name": "p", "work_dir": str(tmp_path),
            "description": None,
            "grids": [], "simulations": [], "files": [],
        }

    def _patch_ui(self, monkeypatch) -> tuple[list, list]:
        from shyfem_ui.components import file_picker
        update_calls: list = []
        notify_calls: list = []
        monkeypatch.setattr(
            file_picker.ui, "update_text",
            lambda tid, value: update_calls.append((tid, value)),
        )
        monkeypatch.setattr(
            file_picker.ui, "notification_show",
            lambda *a, **kw: notify_calls.append((a, kw)),
        )
        return update_calls, notify_calls

    def test_fill_picker_input_success_calls_update_text(self, tmp_path, monkeypatch):
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path)
        file_picker.fill_picker_input("bas_path", proj, "BAS/sim.bas")
        assert len(update_calls) == 1
        target_id, value = update_calls[0]
        assert target_id == "bas_path"
        assert value == str((tmp_path / "BAS" / "sim.bas").resolve())
        assert notify_calls == []

    def test_fill_picker_input_silent_when_no_project(self, monkeypatch):
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        file_picker.fill_picker_input("bas_path", None, "anything")
        assert update_calls == []
        assert notify_calls == []

    def test_fill_picker_input_silent_when_empty_rel_path(self, tmp_path, monkeypatch):
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path)
        file_picker.fill_picker_input("bas_path", proj, "")
        assert update_calls == []
        assert notify_calls == []

    def test_fill_picker_input_warns_on_traversal(self, tmp_path, monkeypatch, caplog):
        import logging

        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path, project_id=42)
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            file_picker.fill_picker_input("bas_path", proj, "../../etc/passwd")
        assert update_calls == []
        assert len(notify_calls) == 1
        assert notify_calls[0][1].get("type") == "warning"
        recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
        assert len(recs) >= 2
        assert any("bas_path" in r.getMessage() for r in recs)

    def test_fill_picker_input_target_id_appears_in_log(self, tmp_path, monkeypatch, caplog):
        import logging

        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path, project_id=99)
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            file_picker.fill_picker_input("lgr_path", proj, "/etc/passwd")
        wrapper_recs = [
            r for r in caplog.records
            if r.name == "shyfem_ui.components.file_picker"
            and "target=" in r.getMessage()
        ]
        assert len(wrapper_recs) == 1
        assert "lgr_path" in wrapper_recs[0].getMessage()
