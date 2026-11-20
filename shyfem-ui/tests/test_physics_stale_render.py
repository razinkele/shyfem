"""A physics Save or Preview refuses inputs the browser has not yet re-rendered.

After a Load or a Save the server re-renders every panel; until the browser
has bound the new panels it still holds the previous file state's input
values. Each panel carries a render stamp, and _stale_panels names the
panels whose stamp is not the current one (CI 2026-11-20: a Save in that
window wrote a.str's ilin and idtsyn into c.str).
"""

from shiny.types import SilentException

from shyfem_ui.pages.physics import (
    _STAMP_PREFIX,
    PHYSICS_PANELS,
    _stale_panels,
    _stamp_input,
)


def _inputs(stamps: dict[str, str]):
    """A stand-in for Shiny's input object: inputs[id]() like the real one."""

    def reader(value):
        def read():
            return value

        return read

    def never_set():
        raise SilentException()

    table = {f"{_STAMP_PREFIX}{pid}": reader(v) for pid, v in stamps.items()}

    class Inputs:
        def __getitem__(self, key):
            return table.get(key, never_set)

    return Inputs()


ALL = list(PHYSICS_PANELS)


def test_every_panel_showing_the_current_render_is_not_stale():
    assert _stale_panels(_inputs({pid: "7" for pid in ALL}), "7", frozenset()) == []


def test_a_panel_still_showing_the_previous_render_is_stale():
    stamps = {pid: "7" for pid in ALL}
    stamps["hydrodynamics"] = "6"
    assert _stale_panels(_inputs(stamps), "7", frozenset()) == ["hydrodynamics"]


def test_every_panel_is_stale_right_after_a_load():
    assert _stale_panels(_inputs({pid: "6" for pid in ALL}), "7", frozenset()) == ALL


def test_a_stamp_never_received_is_stale():
    stamps = {pid: "7" for pid in ALL if pid != "timing"}
    assert _stale_panels(_inputs(stamps), "7", frozenset()) == ["timing"]


def test_a_panel_whose_render_failed_is_not_checked():
    # Its inputs are skipped by the save, and it carries no stamp.
    stamps = {pid: "7" for pid in ALL if pid != "turbulence"}
    assert _stale_panels(_inputs(stamps), "7", frozenset({"turbulence"})) == []


def test_the_stamp_input_is_hidden_and_carries_the_stamp():
    html = str(_stamp_input("timing", "12"))
    assert f'id="{_STAMP_PREFIX}timing"' in html
    assert 'value="12"' in html
    assert "d-none" in html
