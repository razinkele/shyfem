"""Physics page save writes only what the user changed (S-01, S-02, S-08, S-10).

The save loop reads every rendered panel input back. Before this fix it
wrote each one unconditionally, and the renders showed ``value or default``,
so a save with no edit rewrote physics: ``ilin = 0`` became ``ilin = 1``,
``aapar = 0.`` became ``aapar = 1.0``, absent parameters appeared at their
UI default, and an opened Boundary panel added an unnumbered ``$bound``
the core stops on (``bnd: ibc out of bounds``).
"""

import ast
import inspect
import re
from pathlib import Path

import pytest

from shyfem_ui.pages import physics
from shyfem_ui.pages.physics import (
    _INPUT_ID_REMAP,
    PHYSICS_PANELS,
    _collect_into_copy,
    _shown,
    build_panel_params,
)
from shyfem_ui.services.parser_str import (
    COMMON_PARAMS,
    StrParser,
    format_param_display,
)
from shyfem_ui.services.str_validator import validate_str
from tests.test_physics_page import FakeInputs

_TESTCASES = Path(__file__).resolve().parent.parent.parent / "testcases"
_SHIPPED_STRS = sorted(_TESTCASES.glob("**/*.str")) if _TESTCASES.is_dir() else []


def _untouched_inputs(sf) -> FakeInputs:
    """Every panel input as a no-edit session shows it.

    A param whose shown value is None renders a blank field, and the save
    loop skips a blank field, so it is left out here.
    """
    values: dict = {}
    for panel_id in PHYSICS_PANELS:
        for param, value in build_panel_params(sf, panel_id).items():
            if value is not None:
                values[param] = format_param_display(value)
    for input_id, (section, param) in _INPUT_ID_REMAP.items():
        value = physics._baseline(sf, section, param)
        if value is not None:
            values[input_id] = format_param_display(value)
    for stream, on in physics._imetout_decode(sf.get_param("para", "imetout")).items():
        values[f"imetout_{stream}"] = on
    for prefix, ivar in (("t", 12), ("s", 11)):
        values.update(_rendered_assimil_inputs(sf, prefix, ivar))
    return FakeInputs(values)


def _rendered_assimil_inputs(sf, prefix: str, ivar: int) -> dict:
    """The input values the real _assimil_block HTML carries."""
    html = str(physics._assimil_block(sf, "Block", prefix, ivar))
    values: dict = {}
    for tag in re.findall(r"<input[^>]*>", html):
        input_id = re.search(r'id="assim_(\w+)"', tag)
        if not input_id:
            continue
        key = f"assim_{input_id.group(1)}"
        if 'type="checkbox"' in tag:
            values[key] = "checked" in tag
        else:
            value = re.search(r'value="([^"]*)"', tag)
            values[key] = float(value.group(1)) if value else None
    for select_id, body in re.findall(
        r'<select[^>]*id="(assim_\w+)"[^>]*>(.*?)</select>', html, re.S
    ):
        chosen = re.search(r'<option value="([^"]*)" selected', body)
        values[select_id] = chosen.group(1) if chosen else ""
    return values


def _save(text: str, values: dict | None = None):
    sf = StrParser.parse(text)
    inputs = _untouched_inputs(sf)
    inputs._values.update(values or {})
    working, errors, _purged = _collect_into_copy(inputs, sf)
    return working, errors


_KEPS = """$title
        keps test
        keps_40
        channel
$end
$para
        itanf = 0       itend = 3600    idt = 60
        ilin = 0
        aapar = 0.
        idtcon = 600
$end
"""


@pytest.mark.skipif(not _SHIPPED_STRS, reason="testcases/ not present")
@pytest.mark.parametrize("path", _SHIPPED_STRS, ids=lambda p: str(p.relative_to(_TESTCASES)))
def test_no_edit_save_round_trips_every_shipped_str(path):
    try:
        sf = StrParser.parse_file(path)
    except Exception as exc:  # not every testcase file is a valid STR
        pytest.skip(f"does not parse: {exc}")
    working, errors, _purged = _collect_into_copy(_untouched_inputs(sf), sf)
    assert errors == []
    assert StrParser.generate(working) == path.read_text()


def test_explicit_zero_is_kept_with_its_spelling():
    working, errors = _save(_KEPS)
    assert errors == []
    out = StrParser.generate(working)
    assert "ilin = 0\n" in out
    assert "aapar = 0.\n" in out
    assert "dlat" not in out


def test_an_edit_is_written():
    working, errors = _save(_KEPS, {"ilin": "1", "dlat": 45.0})
    assert errors == []
    assert working.get_param("para", "ilin") == 1
    assert working.get_param("para", "dlat") == 45.0
    assert working.get_param("para", "aapar") == 0.0


def test_render_shows_explicit_zero_not_default():
    assert _shown({"ilin": 0}, "ilin", 1) == 0
    assert _shown({"aapar": 0.0}, "aapar", 1.0) == 0.0
    assert _shown({"ilin": None}, "ilin", 1) == 1
    assert _shown({}, "ilin", 1) == 1


def test_no_render_coerces_falsy_values():
    """`params.get(...) or x` is the S-01 shape: any falsy value -> x."""
    tree = ast.parse(inspect.getsource(physics))
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BoolOp)
        and isinstance(node.op, ast.Or)
        and isinstance(node.values[0], ast.Call)
        and isinstance(node.values[0].func, ast.Attribute)
        and node.values[0].func.attr == "get"
        and isinstance(node.values[0].func.value, ast.Name)
        and node.values[0].func.value.id == "params"
    ]
    assert offenders == []


def test_untouched_boundary_panel_adds_no_section():
    working, errors = _save(_KEPS)
    assert errors == []
    assert "bound" not in working.sections
    assert "$bound\n" not in StrParser.generate(working)


def test_boundary_panel_edit_is_refused_not_written_unnumbered():
    working, errors = _save(_KEPS, {"ibtyp": "2"})
    assert "bound" not in working.sections
    assert any("$bound1" in e and "ibtyp" in e for e in errors), errors


def test_stale_duplicate_input_does_not_overwrite_an_edit():
    """idtcon is shown in two panels; only the one the user edited counts."""
    for edited in ("idtcon", "idtcon_out"):
        working, errors = _save(_KEPS, {edited: "1200"})
        assert errors == [], edited
        assert working.get_param("para", "idtcon") == 1200, edited


def test_conflicting_duplicate_inputs_are_reported():
    working, errors = _save(_KEPS, {"idtcon": "1200", "idtcon_out": "1800"})
    assert any("idtcon" in e for e in errors), errors
    assert working.get_param("para", "idtcon") == 600


def test_restart_and_boundary_defaults_match_the_core():
    """def_para.f90 addpar('ityrst',0.); bnd_admin.f90 addpar('intpol',0.)."""
    assert COMMON_PARAMS["para"]["ityrst"][2] == 0
    assert COMMON_PARAMS["bound"]["intpol"][2] == 0


def test_validator_rejects_unnumbered_bound():
    msgs = validate_str({"para": {"itend": 10, "idt": 1}, "bound": {"ibtyp": 1}})
    assert any(m.level == "error" and "$bound1" in m.message for m in msgs), msgs


def test_bound_template_is_numbered():
    from shyfem_ui.components.str_editor import generate_section_template

    template = generate_section_template("bound")
    assert template.startswith("$bound1\n")
    assert "kbound" in template


def test_every_panel_param_has_a_core_section_and_default():
    """A param registered in a section COMMON_PARAMS does not list for it has no
    baseline, so an untouched input writes -- `ilagr` in $para made the core
    stop with "nls_insert_variable: wrong section"."""
    wrong = [
        (panel_id, param, section)
        for panel_id, panel in PHYSICS_PANELS.items()
        for param, section in panel["params"].items()
        if param not in COMMON_PARAMS.get(section, {})
    ]
    wrong += [
        (input_id, param, section)
        for input_id, (section, param) in _INPUT_ID_REMAP.items()
        if param not in COMMON_PARAMS.get(section, {})
    ]
    assert wrong == []


def test_untouched_lagrangian_panel_writes_nothing_to_para():
    working, errors = _save(_KEPS)
    assert errors == []
    assert working.get_param("para", "ilagr") is None
    assert "lagrg" not in working.sections


@pytest.mark.parametrize("stored", [None, 0, 2])
def test_untouched_meteo_output_checkboxes_write_nothing(stored):
    text = (
        _KEPS
        if stored is None
        else _KEPS.replace(
            "        idtcon = 600\n", f"        idtcon = 600\n        imetout = {stored}\n"
        )
    )
    sf = StrParser.parse(text)
    flags = physics._imetout_decode(sf.get_param("para", "imetout"))
    inputs = {f"imetout_{f}": on for f, on in flags.items()}
    working, errors = _save(text, inputs)
    assert errors == []
    assert StrParser.generate(working) == text


def test_an_edited_meteo_output_checkbox_is_written():
    working, errors = _save(_KEPS, {f"imetout_{f}": f == "wind" for f in physics._IMETOUT_FIELDS})
    assert errors == []
    assert working.get_param("para", "imetout") == 1


def test_editor_validate_button_rejects_unnumbered_bound():
    from shyfem_ui.components.str_editor import validate_str_content

    errors = validate_str_content(
        "$para\n        itend = 10  idt = 1\n$end\n$bound\n        ibtyp = 1\n$end\n"
    )
    assert any("$bound1" in e for e in errors), errors


@pytest.mark.parametrize(
    "stored, shown",
    [("1", "1"), ("1.0", "1"), ("4", "4"), ("2.5", "2.5")],
)
def test_select_shows_the_stored_value(stored, shown):
    """A value outside the choices rendered the first choice, which a save wrote."""
    html = str(physics._select("x", "X", choices={"0": "off", "1": "on"}, selected=stored))
    assert f'<option value="{shown}" selected="">' in html, html


def test_a_failed_panel_skips_only_the_inputs_it_renders():
    """Output shows idtcon as idtcon_out; T&S renders the plain idtcon input."""
    ids = physics._panel_input_ids(frozenset({"output"}))
    assert {"idtcon_out", "icon_av_out", "idtout"} <= ids
    assert "idtcon" not in ids
    working, errors = _save(_KEPS, {"ilin": "1"})
    sf = StrParser.parse(_KEPS)
    inputs = _untouched_inputs(sf)
    inputs._values["ilin"] = "1"
    skipped, errors, _ = _collect_into_copy(inputs, sf, frozenset({"hydrodynamics"}))
    assert errors == []
    assert skipped.get_param("para", "ilin") == 0
    assert working.get_param("para", "ilin") == 1
