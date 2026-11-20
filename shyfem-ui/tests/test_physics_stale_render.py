"""A physics Save or Preview reads only what the browser shows for the current renders.

After a Load or a Save the server renders every panel again; until the
browser has bound the new panels it still holds the old ones' values, and
Shiny never clears the server value of an input the browser removed. Each
panel render records a stamp and the input ids it drew (see the comment
above _STAMP_PREFIX in physics.py). CI 2026-11-20: a Save in that window
wrote a.str's ilin into c.str; and a scalar beachrate input left over from
one file flattened the next file's per-area array.
"""

import pytest
from shiny import ui
from shiny._namespaces import namespace_context
from shiny.types import SilentException

from shyfem_ui.components.project_select import str_file_selectize
from shyfem_ui.pages import physics
from shyfem_ui.pages.physics import (
    _STAMP_PREFIX,
    PHYSICS_PANELS,
    _collect_into_copy,
    _current_panel_inputs,
    _PanelInputs,
    _PanelRender,
    _rendered_input_ids,
    _stamp_input,
)
from shyfem_ui.services.parser_str import StrParser


class _Inputs:
    """A stand-in for Shiny's input object: inputs[id]() like the real one."""

    def __init__(self, values: dict[str, object]):
        self._values = values

    def __getitem__(self, key):
        if key not in self._values:

            def never_set():
                raise SilentException()

            return never_set
        value = self._values[key]
        return lambda: value


ALL = list(PHYSICS_PANELS)


def _renders(file_stamp="3", ids=None):
    """Every panel rendered once for *file_stamp*; panel i drew ids[panel] or {panel}."""
    ids = ids or {}
    return {
        pid: _PanelRender(f"{file_stamp}.{n}", frozenset(ids.get(pid, {f"{pid}_x"})))
        for n, pid in enumerate(ALL, start=1)
    }


def _browser(renders, **values):
    """The values the server holds once the browser has bound *renders*."""
    shown = {f"{_STAMP_PREFIX}{pid}": r.stamp for pid, r in renders.items()}
    return _Inputs({**shown, **values})


# --- the stamp check ---


def test_panels_showing_their_latest_render_pass():
    renders = _renders()
    current, stale = _current_panel_inputs(_browser(renders), renders, "3", frozenset())
    assert stale == [] and isinstance(current, _PanelInputs)


def test_a_panel_the_browser_has_not_rebound_yet_is_stale():
    renders = _renders()
    inputs = _browser(renders)
    inputs._values[f"{_STAMP_PREFIX}hydrodynamics"] = "3.0"  # an older render
    current, stale = _current_panel_inputs(inputs, renders, "3", frozenset())
    assert current is None and stale == ["hydrodynamics"]


def test_a_save_before_the_panels_render_for_the_new_file_is_stale():
    # Load sets a new file state (stamp 4) and the Save runs before the
    # panels re-render: their records and the browser still agree on the
    # file-3 renders, which must not pass.
    renders = _renders("3")
    current, stale = _current_panel_inputs(_browser(renders), renders, "4", frozenset())
    assert current is None and stale == ALL


def test_a_stamp_never_received_is_stale():
    renders = _renders()
    inputs = _browser(renders)
    del inputs._values[f"{_STAMP_PREFIX}timing"]
    assert _current_panel_inputs(inputs, renders, "3", frozenset())[1] == ["timing"]


def test_a_panel_with_no_render_record_is_stale():
    renders = _renders()
    inputs = _browser(renders)
    del renders["vertical"]
    assert _current_panel_inputs(inputs, renders, "3", frozenset())[1] == ["vertical"]


def test_a_panel_whose_render_failed_is_not_checked():
    renders = _renders()
    inputs = _browser(renders)
    del renders["turbulence"]
    del inputs._values[f"{_STAMP_PREFIX}turbulence"]
    current, stale = _current_panel_inputs(inputs, renders, "3", frozenset({"turbulence"}))
    assert stale == [] and current is not None


# --- the leftover filter ---


def test_only_ids_the_current_renders_drew_are_read():
    renders = _renders(ids={"lagrangian": {"ibeach"}})
    inputs = _browser(renders, ibeach="3", beachrate="0.3")  # beachrate: earlier render
    current, _ = _current_panel_inputs(inputs, renders, "3", frozenset())
    assert current["ibeach"]() == "3"
    with pytest.raises(SilentException):
        current["beachrate"]()


def test_a_failed_panels_ids_are_not_read():
    renders = _renders(ids={"turbulence": {"iturb"}})
    inputs = _browser(renders, iturb="2")
    current, _ = _current_panel_inputs(inputs, renders, "3", frozenset({"turbulence"}))
    with pytest.raises(SilentException):
        current["iturb"]()


def test_the_collector_takes_only_checked_inputs():
    sf = StrParser.parse("$para\n        idt = 300\n$end\n")
    with pytest.raises(TypeError):
        _collect_into_copy(_Inputs({"idt": 600}), sf)


def test_a_leftover_value_is_not_saved():
    sf = StrParser.parse("$para\n        idt = 300\n        ilin = 1\n$end\n")
    drawn = _PanelInputs(_Inputs({"idt": 600, "ilin": 0}), frozenset({"idt"}))
    working, errors, _ = _collect_into_copy(drawn, sf)
    assert errors == []
    assert working.get_param("para", "idt") == 600
    assert working.get_param("para", "ilin") == 1


# --- what a render records ---


def test_every_widget_kind_the_panels_use_is_found():
    # The panels draw these kinds (physics.py: _select, ui.input_select,
    # ui.input_numeric, ui.input_text, ui.input_checkbox and
    # str_file_selectize), namespaced like the physics module. A missed id
    # would drop a real edit.
    with namespace_context("p"):
        tag = ui.div(
            physics._select("sel", "Sel", choices={"0": "0", "1": "1"}, selected="1"),
            ui.input_select("plain", "Plain", choices=["a", "b"]),
            ui.input_numeric("num", "Num", value=1),
            ui.input_text("txt", "Txt", value="x"),
            ui.input_checkbox("chk", "Chk", value=True),
            str_file_selectize("file", "File", "a.dat", ["a.dat", "b.dat"]),
            ui.input_checkbox_group("grp", "Grp", choices=["a", "b"]),
            ui.input_radio_buttons("rad", "Rad", choices=["a", "b"]),
            ui.input_text_area("area", "Area"),
        )
    ids = _rendered_input_ids(tag, "p-")
    assert {"sel", "plain", "num", "txt", "chk", "file", "grp", "rad", "area"} <= ids


def test_ids_outside_the_module_namespace_are_ignored():
    with namespace_context("p"):
        mine = ui.input_text("a", "A")
    with namespace_context("other"):
        theirs = ui.input_text("b", "B")
    ids = _rendered_input_ids(ui.div(mine, theirs), "p-")
    assert "a" in ids and "b" not in ids


def test_the_stamp_input_is_hidden_and_carries_the_stamp():
    html = str(_stamp_input("timing", "4.12"))
    assert f'id="{_STAMP_PREFIX}timing"' in html
    assert 'value="4.12"' in html
    assert "d-none" in html
