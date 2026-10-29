"""STR editor fixes from the 2026-10-19 UI review (S-04, S-05, S-06, S-09)."""

from shyfem_ui.components.str_editor import validate_str_content

_VALID_PARA = "$title\n    t\n$end\n$para\n    itanf = 0\n    itend = 3600\n    idt = 300\n"


class TestStructuralCheckMatchesTheParser:
    """S-09: the closing marker may carry a comment, and '&' works like '$'
    (nls.f90 nls_is_section). The hand-rolled scan flagged both as an
    unclosed section, and that error blocked the inline Save."""

    def test_end_with_a_trailing_comment_closes_the_section(self):
        content = _VALID_PARA + "$end  ! end of para\n"
        assert not [e for e in validate_str_content(content) if "not closed" in e]

    def test_ampersand_markers_close_the_section(self):
        content = _VALID_PARA.replace("$para", "&para") + "&end\n"
        result = validate_str_content(content)
        assert not [e for e in result if "not closed" in e or "Unexpected" in e], result

    def test_dollar_section_closed_by_ampersand_end(self):
        content = _VALID_PARA + "&end\n"
        assert not [e for e in validate_str_content(content) if "not closed" in e]

    def test_a_really_unclosed_section_is_still_reported(self):
        content = _VALID_PARA  # no $end for $para
        assert any("$para not closed" in e for e in validate_str_content(content))

    def test_a_stray_end_is_still_reported(self):
        content = _VALID_PARA + "$end\n$end ! again\n"
        assert any("Unexpected $end" in e for e in validate_str_content(content))


# ---------------------------------------------------------------------------
# Reactive harness for str_editor_server (same seam as test_boundary_editor:
# call the plain function inside @module.server with stand-in inputs).
# ---------------------------------------------------------------------------


class _FakeInputs:
    def __init__(self):
        self._values = {}

    def _cell(self, key):
        from shiny import reactive

        if key not in self._values:
            self._values[key] = reactive.Value(None)
        return self._values[key]

    def __getattr__(self, key):
        return self._cell(key).get

    def __getitem__(self, key):
        return self.__getattr__(key)

    def set(self, key, value):
        self._cell(key).set(value)


def _mount_str_editor(monkeypatch, path):
    from types import SimpleNamespace

    from shiny import reactive

    import shyfem_ui.config as config_mod
    from shyfem_ui.components import str_editor as se
    from shyfem_ui.services import access_control

    for name in ("notification_show", "update_text_area", "update_select"):
        monkeypatch.setattr(se.ui, name, lambda *a, **k: None)
    monkeypatch.setattr(access_control, "editor_denied_reason", lambda *a, **k: None)
    monkeypatch.setattr(
        config_mod,
        "get_config",
        lambda: SimpleNamespace(confine_path=lambda p, *a, **k: p),
    )
    inner = se.str_editor_server.__closure__[0].cell_contents
    fake_input = _FakeInputs()
    file_path = reactive.Value(path)
    result = inner(fake_input, None, None, file_path=file_path)
    return fake_input, result


_WITH_NOMP = (
    "$title\n    t\n$end\n$para\n    itanf = 0\n    itend = 3600\n    idt = 300\n"
    "    nomp = -1\n$end\n"
)


class TestInlineSaveBlocksOnErrorsOnly:
    """S-04: an unknown $para key (nomp, in 20 shipped STRs) is a warning,
    and the inline Save refused on any warning, so those files could not be
    saved there at all."""

    async def test_a_warning_does_not_block_the_save(self, monkeypatch, tmp_path):
        from shiny import reactive

        path = tmp_path / "run.str"
        path.write_text(_WITH_NOMP)
        fake_input, _ = _mount_str_editor(monkeypatch, path)
        await reactive.flush()

        edited = _WITH_NOMP.replace("idt = 300", "idt = 600")
        fake_input.set("editor_content", edited)
        await reactive.flush()
        fake_input.set("save_btn", 1)
        await reactive.flush()

        assert path.read_text() == edited

    async def test_an_error_still_blocks_the_save(self, monkeypatch, tmp_path):
        from shiny import reactive

        path = tmp_path / "run.str"
        path.write_text(_WITH_NOMP)
        fake_input, _ = _mount_str_editor(monkeypatch, path)
        await reactive.flush()

        fake_input.set("editor_content", _WITH_NOMP.replace("    idt = 300\n", ""))
        await reactive.flush()
        fake_input.set("save_btn", 1)
        await reactive.flush()

        assert path.read_text() == _WITH_NOMP


_EMPTY_WIND = "$name\n        wind = ''\n        rain = 'r.dat'\n$end\n"


class TestAnEmptyQuotedValueRoundTrips:
    """S-06: ``wind = ''`` parsed to None, the form showed it as "None", and
    Apply with no edit wrote ``wind = 'None'`` (a file the core then tries to
    open)."""

    def test_the_parser_keeps_an_empty_string(self):
        from shyfem_ui.services.parser_str import StrParser

        assert StrParser.parse(_EMPTY_WIND).get_param("name", "wind") == ""
        assert StrParser.parse('$name\n wind = ""\n$end\n').get_param("name", "wind") == ""

    def test_the_form_does_not_show_none(self):
        from shyfem_ui.components.str_editor import _build_form_panel
        from shyfem_ui.services.parser_str import StrParser

        html = str(_build_form_panel(StrParser.parse(_EMPTY_WIND)))
        assert "None" not in html

    def test_apply_with_no_edit_is_byte_exact(self):
        from shyfem_ui.components.str_editor import _apply_form_values, _build_form_panel
        from shyfem_ui.services.parser_str import StrParser

        parsed = StrParser.parse(_EMPTY_WIND)
        # Each field echoes the value the form rendered into it.
        shown = _rendered_field_values(str(_build_form_panel(parsed)))
        assert set(shown) == {"form_name_wind", "form_name_rain"}
        edited = _apply_form_values(parsed, shown.get)
        assert StrParser.generate(edited) == _EMPTY_WIND


def _rendered_field_values(html: str) -> dict[str, str]:
    """Field id -> the value the browser would send back for it."""
    import re

    values = {}
    for m in re.finditer(r'<select[^>]*id="(form_[^"]+)"[^>]*>(.*?)</select>', html, re.S):
        sel = re.search(r'<option value="([^"]*)" selected', m.group(2))
        values[m.group(1)] = sel.group(1) if sel else ""
    for m in re.finditer(r'<input id="(form_[^"]+)"[^>]*value="([^"]*)"', html):
        values[m.group(1)] = m.group(2)
    return values


def _mount_boundary_editor(monkeypatch, str_text):
    from shiny import reactive

    from shyfem_ui.components import boundary_editor as be
    from shyfem_ui.services.parser_str import StrParser

    notes = []
    monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: notes.append((a, k)))
    inner = be.boundary_editor_server.__closure__[0].cell_contents
    fake_input = _FakeInputs()
    parsed = reactive.Value(StrParser.parse(str_text) if str_text else None)
    result = inner(fake_input, None, None, parsed_str=parsed)
    return fake_input, result, notes


class TestBoundaryEditorEmptyFile:
    async def test_an_empty_boundn_is_not_generated_as_none(self, monkeypatch):
        from shiny import reactive

        fake_input, result, _ = _mount_boundary_editor(
            monkeypatch,
            "$bound1\n        kbound = 1 2\n        ibtyp = 1\n        boundn = ''\n$end\n",
        )
        await reactive.flush()
        with reactive.isolate():
            assert result["boundaries"].get()[0]["boundn"] == ""
        fake_input.set("generate_str_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            assert "None" not in result["generated_text"].get()
