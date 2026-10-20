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
    return FakeInputs(values)


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
    before = StrParser.generate(sf)
    working, errors, _purged = _collect_into_copy(_untouched_inputs(sf), sf)
    assert errors == []
    assert StrParser.generate(working) == before


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
