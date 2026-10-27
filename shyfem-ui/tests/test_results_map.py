"""Results map component: pure helpers, UI build, and source guards that pin
the reactive dependency matrix of ``results_map_server`` (Task 4).

The server harness below uses Shiny internals (``AppSession``,
``MockConnection``, ``bookmark._restore_context_value``, the ``clientdata``
hidden flags) and is pinned to shiny ``>=1.8,<1.9``."""

from __future__ import annotations

import ast
import asyncio
import inspect
import textwrap
from datetime import datetime
from types import SimpleNamespace

import pytest
from shiny.types import ActionButtonValue

from shyfem_ui.components import results_map
from shyfem_ui.components.results_map import (
    _opt,
    clamp_index,
    format_time,
    next_index,
    note_push,
    pending_echo,
    pick_variable,
    results_map_controls_ui,
    results_map_ui,
)
from shyfem_ui.services.results_data import frame

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_next_index_wraps_and_clamps():
    assert next_index(0, 4) == 1
    assert next_index(2, 4) == 3
    assert next_index(3, 4) == 0, "wraps to 0 after the last record"
    assert next_index(9, 4) == 0, "an out-of-range index is clamped first"
    assert next_index(0, 1) == 0
    assert next_index(5, 0) == 0
    assert clamp_index(-3, 4) == 0
    assert clamp_index(7, 4) == 3
    assert clamp_index(2, 4) == 2
    assert clamp_index(2, 0) == 0


def test_format_time():
    assert format_time(datetime(2001, 1, 1, 6, 0)) == "2001-01-01 06:00"


def test_pick_variable_falls_back():
    rf = SimpleNamespace(variables={"water_level": 1, "u_velocity": 2})
    assert pick_variable("u_velocity", rf) == "u_velocity"
    assert pick_variable("salinity", rf) == "water_level"
    assert pick_variable(None, rf) == "water_level"


class _FakeInput:
    def __init__(self, values):
        self._values = values

    def __contains__(self, name):
        return name in self._values

    def __getitem__(self, name):
        return lambda: self._values[name]


def test_opt_returns_default_for_a_missing_input():
    inp = _FakeInput({"variable": "salinity"})
    assert _opt(inp, "level", 0) == 0
    assert _opt(inp, "variable", None) == "salinity"


def test_note_push_skips_unchanged():
    pending: list[int] = []
    note_push(pending, 0, 0)
    assert pending == [], "the client sends no echo for an unchanged value"


def test_note_push_dedups_consecutive():
    pending: list[int] = []
    note_push(pending, 3, 0)
    note_push(pending, 3, 0)
    assert pending == [3], "two identical pushes in one flush give one echo"
    assert pending_echo(pending, 3, 3) == "echo"
    assert pending == []
    assert pending_echo(pending, 3, 1) == "move", "a later user 3 is a move"


def test_pending_echo_replays():
    pending: list[int] = []
    note_push(pending, 5, 0)
    assert pending_echo(pending, 5, 5) == "echo"
    assert pending == []
    assert pending_echo(pending, 3, 5) == "move"
    assert pending_echo(pending, 0, 3) == "move"
    # one flush, two pushes -> the client sends only the last value
    note_push(pending, 1, 0)
    note_push(pending, 2, 0)
    assert pending_echo(pending, 2, 2) == "echo"
    assert pending == [], "the single echo consumes everything up to it"
    assert pending_echo(pending, 1, 2) == "move"


def test_pending_echo_same_value_is_same():
    assert pending_echo([], 4, 4) == "same"


# ---------------------------------------------------------------------------
# UI build
# ---------------------------------------------------------------------------


def test_both_uis_share_the_namespace():
    controls = str(results_map_controls_ui("x"))
    view = str(results_map_ui("x"))
    assert 'id="x-t_index"' in controls
    assert 'id="x-var_controls"' in controls
    assert "x-deckgl_map" in view
    assert 'id="x-time_label"' in view
    assert 'id="x-legend"' in view
    assert 'id="x-map_message"' in view


def test_slider_has_a_step_and_builds():
    html = str(results_map_controls_ui("x"))
    start = html.index('id="x-t_index"')
    tag = html[html.rindex("<input", 0, start) : html.index(">", start)]
    assert 'data-step="1"' in tag
    for ident in ("step_back", "play", "step_fwd", "speed", "range_mode", "vmin", "vmax"):
        assert f'id="x-{ident}"' in html
    assert 'id="x-palette"' in html and 'id="x-epsg"' in html


# ---------------------------------------------------------------------------
# Source guards (dependency matrix)
# ---------------------------------------------------------------------------

_SRC = inspect.getsource(results_map)
_TREE = ast.parse(_SRC)


def _server() -> ast.AST:
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "results_map_server":
            return node
    raise AssertionError("results_map_server not found")


def _fn(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(_server()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in results_map_server")


def _src(node: ast.AST) -> str:
    return ast.unparse(node)


def _decorators(node) -> list[str]:
    return [ast.unparse(d) for d in node.decorator_list]


def _is_isolate(with_node: ast.With) -> bool:
    return any(ast.unparse(item.context_expr) == "reactive.isolate()" for item in with_node.items)


def _calls_outside_isolate(fn) -> list[str]:
    """Unparsed calls in ``fn``'s body that are not inside ``with reactive.isolate():``."""
    found: list[str] = []

    def visit(node, isolated):
        if isinstance(node, ast.With) and _is_isolate(node):
            isolated = True
        if isinstance(node, ast.Call) and not isolated:
            found.append(ast.unparse(node))
        for child in ast.iter_child_nodes(node):
            visit(child, isolated)

    for stmt in fn.body:
        visit(stmt, False)
    return found


def _calls_inside_isolate(fn) -> list[str]:
    found: list[str] = []

    def visit(node, isolated):
        if isinstance(node, ast.With) and _is_isolate(node):
            isolated = True
        if isinstance(node, ast.Call) and isolated:
            found.append(ast.unparse(node))
        for child in ast.iter_child_nodes(node):
            visit(child, isolated)

    for stmt in fn.body:
        visit(stmt, False)
    return found


def _effects() -> list:
    return [
        node
        for node in ast.walk(_server())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "reactive.effect" in _decorators(node)
    ]


def test_slider_effect_is_an_event_on_t_index():
    assert "reactive.event(input.t_index)" in _decorators(_fn("_slider"))


def test_play_effect_reads_t_only_isolated_and_ticks():
    tick = _fn("_ticker")
    assert "t.get()" not in _calls_outside_isolate(tick)
    assert "t.get()" in _calls_inside_isolate(tick)
    assert "reactive.invalidate_later(" in _src(tick)
    assert "_push_slider(" not in _src(tick), "no slider push while playing"
    outside = _calls_outside_isolate(tick)
    assert "playing.get()" in outside and "input.speed()" in outside
    assert "scene.get()" not in outside


def test_frame_effect_patches_colours_and_never_updates():
    body = _src(_fn("_frame"))
    assert "patch_layer(" in body and "color_patch(" in body
    assert ".update(" not in body
    assert "fit_bounds(" not in body
    # arrows input only when the file has currents
    tree = _fn("_frame")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and ast.unparse(node).startswith("_opt(input, 'arrows'"):
            break
    else:
        raise AssertionError("arrows must be read through _opt")
    assert "has_currents" in body


def test_scene_effect_reads_t_only_isolated():
    scene = _fn("_scene")
    outside = _calls_outside_isolate(scene)
    assert "t.get()" not in outside
    assert "scene.get()" not in outside
    assert "input.palette()" not in outside
    assert "results.get()" in outside
    assert "input.epsg()" in outside


def test_var_controls_reads_only_results():
    vc = _fn("var_controls")
    assert "render.ui" in _decorators(vc)
    outside = _calls_outside_isolate(vc)
    reactive_reads = [
        c for c in outside if c.endswith(".get()") or c.startswith("input") or c.startswith("_opt(")
    ]
    assert reactive_reads == ["results.get()"]
    inside = _calls_inside_isolate(vc)
    assert any(c.startswith("_opt(input, 'variable'") for c in inside)
    assert any(c.startswith("_opt(input, 'level'") for c in inside)
    assert any(c.startswith("_opt(input, 'arrows'") for c in inside)


def test_every_effect_reraises_silent_then_logs():
    effects = _effects()
    names = {e.name for e in effects}
    expected = {
        "_scene",
        "_ranges_done",
        "_slider",
        "_play_button",
        "_ticker",
        "_frame",
        "_step_back",
        "_step_fwd",
        "_play_state",
    }
    assert expected <= names
    for eff in effects:
        tries = [s for s in eff.body if isinstance(s, ast.Try)]
        assert tries, f"{eff.name}: the body must be wrapped in try"
        handlers = tries[0].handlers
        assert len(handlers) >= 2, eff.name
        assert ast.unparse(handlers[0].type) == "SilentException", eff.name
        assert len(handlers[0].body) == 1 and isinstance(handlers[0].body[0], ast.Raise), eff.name
        assert handlers[0].body[0].exc is None, f"{eff.name}: bare raise"
        assert ast.unparse(handlers[1].type) == "Exception", eff.name
        assert ".warning(" in "\n".join(ast.unparse(s) for s in handlers[1].body), eff.name


def test_optional_inputs_only_through_opt():
    for name in ("level", "arrows", "variable"):
        assert f"input.{name}" not in _SRC
        assert f"input['{name}']" not in _SRC and f'input["{name}"]' not in _SRC
    opt = inspect.getsource(results_map._opt)
    assert "name in input" in opt


def test_outputs_are_renders_reading_values():
    for name in ("time_label", "legend", "map_message"):
        fn = _fn(name)
        assert any(d.startswith("render.") for d in _decorators(fn)), name
        assert ".get()" in _src(fn), name
    for eff in _effects():
        body = _src(eff)
        assert "output." not in body and "@render" not in body, eff.name
        assert not any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(d.startswith("render.") for d in _decorators(n))
            for n in ast.walk(eff)
        ), eff.name


def test_ranges_is_an_extended_task_off_the_event_loop():
    rng = _fn("_ranges")
    assert isinstance(rng, ast.AsyncFunctionDef)
    assert "reactive.extended_task" in _decorators(rng)
    body = _src(rng)
    assert body.count("asyncio.to_thread(") >= 2
    assert "value_range(" not in body.replace("asyncio.to_thread(value_range", "")


def test_scene_key_compares_with_pending_key():
    body = _src(_fn("_scene"))
    assert "key == pending_key[0]" in body
    assert "== scene" not in body and "scene.get()['key']" not in body
    assert "key = (id(rf)," in body
    i_level = body.index("level = int(_opt(input, 'level', 0))")
    i_clamp = body.index("level = min(max(level, 0), rf.n_levels - 1)")
    i_key = body.index("key = (id(rf),")
    assert i_level < i_clamp < i_key
    assert "int(input.epsg())" in body


def test_scene_cancels_before_invoking_ranges():
    body = _src(_fn("_scene"))
    i_cancel = body.rindex("_ranges.cancel()")
    i_invoke = body.index("_ranges.invoke(key, rf, var, level)")
    assert i_cancel < i_invoke


def test_ranges_done_ignores_a_stale_key_and_reports_errors():
    body = _src(_fn("_ranges_done"))
    assert "_ranges.result()" in body
    assert "!= pending_key[0]" in body
    assert "Could not compute the colour range" in body


def test_on_ended_reads_results_under_isolate():
    body = textwrap.dedent(_src(_fn("_close")))
    assert "with reactive.isolate():" in body and "results.get()" in body
    assert "close()" in body
    assert "session.on_ended(_close)" in _src(_server())


@pytest.mark.parametrize("name", ["_step_back", "_step_fwd"])
def test_step_effects_are_events(name):
    assert f"reactive.event(input.{name[1:]})" in _decorators(_fn(name))


def test_play_button_is_an_event_and_ignores_no_scene():
    fn = _fn("_play_button")
    assert "reactive.event(input.play)" in _decorators(fn)
    assert "playing.get()" not in _calls_outside_isolate(fn)


# ---------------------------------------------------------------------------
# Server, on a mock session (no browser)
# ---------------------------------------------------------------------------


class _Harness:
    """A real ``AppSession`` over a mock connection, recording what it sends."""

    def __init__(self):
        import json

        from shiny import App, reactive, ui
        from shiny._connection import MockConnection
        from shiny.session import session_context
        from shiny.session._session import AppSession

        from shyfem_ui.components.results_map import results_map_server

        self.sent: list[dict] = []
        sent = self.sent

        class _Conn(MockConnection):
            async def send(self, message):
                sent.append(json.loads(message))

        self.session = AppSession(App(ui.page_fluid(), None), "s1", _Conn())
        # set by the session's message loop, which a mock session never runs
        self.session.bookmark._restore_context_value = None
        self.scope = self.session.make_scope("x")
        self.results = reactive.value(None)
        defaults = {
            "t_index": 0,
            "speed": "4",
            "range_mode": "auto",
            "vmin": None,
            "vmax": None,
            "palette": "ocean",
            "epsg": "",
        }
        for button in ("play", "step_back", "step_fwd"):
            defaults[button] = ActionButtonValue(0)  # what an unclicked button sends
        from shiny._namespaces import ResolvedId

        for out in ("var_controls", "time_label", "legend", "map_message"):
            # outputs run only once the client reports them visible
            self.session.input[ResolvedId(f".clientdata_output_x-{out}_hidden")]._set(False)
        with session_context(self.session):
            for name, value in defaults.items():
                self.scope.input[name]._set(value)
            self.on_screen = results_map_server("x", results=self.results)

    def set_input(self, name, value):
        if name in ("play", "step_back", "step_fwd"):
            value = ActionButtonValue(value)
        self.scope.input[name]._set(value)

    async def flush(self):
        from shiny import reactive

        await reactive.flush()
        await self.session._flush()

    async def settle(self, cond, timeout=5.0):
        """Flush until ``cond()`` holds (the range task runs in a thread)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            await self.flush()
            if cond():
                return
            assert loop.time() < end, "timed out"
            await asyncio.sleep(0.02)

    def screen(self):
        from shiny import reactive

        with reactive.isolate():
            return self.on_screen()

    def custom(self, kind):
        return [m["custom"][kind] for m in self.sent if kind in m.get("custom", {})]

    def slider_pushes(self):
        return self.input_messages("t_index")

    def input_messages(self, name):
        return [
            msg["message"]
            for m in self.sent
            for msg in m.get("inputMessages", [])
            if msg["id"] == f"x-{name}"
        ]

    def values(self, name):
        key = f"x-{name}"
        return [m["values"][key] for m in self.sent if key in m.get("values", {})]


@pytest.fixture
def ugrid(tmp_path, caplog):
    from shyfem_ui.services.results_data import open_results
    from tests._ugrid_fixture import write_ugrid

    opened = []

    def _open(**kw):
        rf = open_results(write_ugrid(tmp_path / f"r{len(opened)}.nc", **kw))
        opened.append(rf)
        return rf

    caplog.set_level("WARNING", logger="shyfem_ui.components.results_map")
    yield _open
    for rf in opened:
        rf.close()
    caught = [r.getMessage() for r in caplog.records if r.name.endswith("results_map")]
    assert caught == [], "an effect swallowed an exception"


async def test_server_loads_a_scene_then_patches_colours(ugrid):
    h = _Harness()
    await h.flush()
    assert h.custom("deck_update")[-1]["layers"] == [], "no file: basemap only"
    assert h.screen() is None

    rf = ugrid(n_time=4)
    h.results.set(rf)
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    update = h.custom("deck_update")[-1]
    assert [lyr["id"] for lyr in update["layers"]] == ["results-mesh", "results-arrows"]
    assert update["layers"][1]["visible"] is False
    assert h.custom("deck_fit_bounds"), "a new scene fits the map to the mesh"
    screen = h.screen()
    assert screen["var"] == "water_level" and screen["units"] == "m"
    assert screen["vmin"] < screen["vmax"]
    patches = [lyr for p in h.custom("deck_partial_update") for lyr in p["layers"]]
    assert any(lyr["id"] == "results-mesh" and "_meshColors" in lyr for lyr in patches)
    assert h.values("time_label")[-1].endswith("record 1 / 4")
    assert any(p.get("max") == 3 and p["step"] == 1 for p in h.slider_pushes()), "max = n-1"

    # a step forward patches colours only (no new full update) and moves the slider
    n_updates = len(h.custom("deck_update"))
    h.set_input("step_fwd", 1)
    await h.flush()
    assert len(h.custom("deck_update")) == n_updates
    assert h.values("time_label")[-1].endswith("record 2 / 4")
    assert h.slider_pushes()[-1]["value"] == 1

    # the slider's echo of that push is not a user move
    h.set_input("t_index", 1)
    await h.flush()
    assert h.values("time_label")[-1].endswith("record 2 / 4")

    # a user drag moves the record
    h.set_input("t_index", 3)
    await h.flush()
    assert h.values("time_label")[-1].endswith("record 4 / 4")

    # a palette change is a colour patch, never a full update
    n_patches = len(h.custom("deck_partial_update"))
    h.set_input("palette", "viridis")
    await h.flush()
    assert len(h.custom("deck_update")) == n_updates
    assert len(h.custom("deck_partial_update")) > n_patches


async def test_server_play_advances_and_pause_syncs_the_slider(ugrid):
    h = _Harness()
    h.results.set(ugrid(n_time=4))
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    h.set_input("play", 1)
    await h.settle(lambda: h.values("time_label")[-1].endswith("record 3 / 4"))
    h.set_input("play", 2)
    await h.flush()
    labels = [msg["label"]["html"] for msg in h.input_messages("play")]
    assert "Pause" in labels and labels[-1] == "Play"
    shown = h.values("time_label")[-1]
    record = int(shown.split("record ")[1].split(" /")[0]) - 1
    assert h.slider_pushes()[-1]["value"] == record, "on pause the slider shows the record"


async def test_server_asks_for_a_projection_then_autodetects_gauss_boaga(ugrid):
    h = _Harness()
    rf = ugrid(n_time=2)
    rf.node_x = rf.node_x * 10_000  # 200 km easting: UTM-like, zone unknown
    rf.node_y = rf.node_y * 10_000
    h.results.set(rf)
    await h.flush()
    assert h.screen() is None
    assert "projection" in str(h.values("map_message")[-1]).lower()

    h.set_input("epsg", "32634")
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    assert h.custom("deck_update")[-1]["layers"], "the chosen EPSG places the mesh"

    gb = ugrid(n_time=2)
    gb.node_x = 1_500_000 + gb.node_x * 1_000  # Gauss-Boaga West false easting
    gb.node_y = 4_500_000 + gb.node_y * 1_000
    h.set_input("epsg", "")
    h.results.set(gb)
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    assert h.custom("deck_update")[-1]["layers"], "Gauss-Boaga is detected without asking"


async def test_server_clears_on_no_results_and_closes_on_end(ugrid):
    h = _Harness()
    rf = ugrid(n_time=3)
    h.results.set(rf)
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    h.results.set(None)
    await h.flush()
    assert h.screen() is None
    assert h.custom("deck_update")[-1]["layers"] == []
    assert h.values("time_label")[-1] == ""

    h.results.set(rf)
    await h.flush()
    await h.session._on_ended_callbacks.invoke()
    with pytest.raises(ValueError, match="closed"):
        frame(rf, "water_level", 0)


async def test_server_arrows_and_manual_range(ugrid):
    h = _Harness()
    h.results.set(ugrid(n_time=3))
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    await h.flush()  # var_controls rendered: the arrows checkbox exists now
    n_updates = len(h.custom("deck_update"))
    h.set_input("variable", "water_level")  # the re-rendered select resends it
    await h.flush()
    assert len(h.custom("deck_update")) == n_updates, "same selection: no new scene"
    h.set_input("arrows", True)
    await h.flush()
    arrows = [
        lyr
        for p in h.custom("deck_partial_update")
        for lyr in p["layers"]
        if lyr["id"] == "results-arrows"
    ]
    assert arrows[-1]["visible"] is True and arrows[-1]["data"], "arrows drawn"

    h.set_input("range_mode", "manual")
    h.set_input("vmin", 5.0)
    h.set_input("vmax", 1.0)
    await h.flush()
    assert "min &lt; max" in h.values("map_message")[-1]["html"]
    h.set_input("vmin", 0.0)
    await h.flush()
    assert h.values("map_message")[-1] is None
    assert (h.screen()["vmin"], h.screen()["vmax"]) == (0.0, 1.0)


async def test_server_ignores_late_echoes_of_quick_steps(ugrid):
    h = _Harness()
    h.results.set(ugrid(n_time=4))
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    h.set_input("step_fwd", 1)
    await h.flush()
    h.set_input("step_fwd", 2)
    await h.flush()
    assert h.values("time_label")[-1].endswith("record 3 / 4")
    h.set_input("t_index", 1)  # the client's late echo of the first push
    await h.flush()
    assert h.values("time_label")[-1].endswith("record 3 / 4"), "an echo is not a move"
    h.set_input("t_index", 2)
    await h.flush()
    assert h.values("time_label")[-1].endswith("record 3 / 4")


def _message_html(h):
    shown = h.values("map_message")[-1]
    return shown["html"] if shown else ""


def _is_playing_label(h):
    return [m["label"]["html"] for m in h.input_messages("play")][-1]


async def _broken_load_is_torn_down(h, bad, caplog, ugrid):
    good = ugrid(n_time=4)
    h.results.set(good)
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    h.set_input("play", 1)
    await h.flush()
    assert _is_playing_label(h) == "Pause"

    h.results.set(bad)
    await h.flush()
    assert h.screen() is None, "the previous scene is not left on screen"
    assert f"Could not show {bad.path.name}" in _message_html(h)
    assert _is_playing_label(h) == "Play", "playback stopped"
    assert h.custom("deck_update")[-1]["layers"] == [], "basemap only"
    assert h.values("time_label")[-1] == ""
    assert h.values("legend")[-1] is None
    assert h.slider_pushes()[-1]["value"] == 0
    assert any("scene update failed" in r.getMessage() for r in caplog.records)
    caplog.clear()

    again = ugrid(n_time=3)
    h.results.set(again)
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    assert _message_html(h) == ""
    assert h.values("time_label")[-1].endswith("record 1 / 3")


async def test_server_tears_down_a_file_with_no_variables(ugrid, caplog):
    h = _Harness()
    bad = ugrid(n_time=2)
    bad.variables = {}  # pick_variable raises
    bad.has_currents = False
    await _broken_load_is_torn_down(h, bad, caplog, ugrid)


async def test_server_tears_down_when_the_geometry_fails(ugrid, caplog, monkeypatch):
    h = _Harness()
    real = results_map.mesh_geometry
    bad = ugrid(n_time=2)

    def geometry(lonlat, faces):
        if h.results.get() is bad:
            raise RuntimeError("broken mesh")
        return real(lonlat, faces)

    monkeypatch.setattr(results_map, "mesh_geometry", geometry)
    await _broken_load_is_torn_down(h, bad, caplog, ugrid)


async def test_server_clears_the_old_legend_and_label_while_the_range_computes(ugrid, monkeypatch):
    import threading

    h = _Harness()
    h.results.set(ugrid(n_time=4))
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    assert h.values("legend")[-1] is not None

    release = threading.Event()
    real = results_map.value_range

    def slow(rf, var, level=0):
        release.wait(5)
        return real(rf, var, level)

    monkeypatch.setattr(results_map, "value_range", slow)
    h.results.set(ugrid(n_time=2))
    await h.flush()
    try:
        assert (h.screen() or {}).get("vmin") is None, "range still computing"
        assert h.values("legend")[-1] is None, "the old legend is gone"
        assert h.values("time_label")[-1].endswith("record 1 / 2"), "the new file's count"
    finally:
        release.set()
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    assert h.values("legend")[-1] is not None


def test_push_slider_survives_a_missing_controls_ui():
    body = _src(_fn("_push_slider"))
    assert "_opt(input, 't_index', 0)" in body and "input.t_index()" not in body


async def test_server_keeps_the_zoom_on_a_variable_change(ugrid):
    h = _Harness()
    h.results.set(ugrid(n_time=3))
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    await h.flush()  # var_controls rendered
    fits, updates = len(h.custom("deck_fit_bounds")), len(h.custom("deck_update"))
    assert fits == 1

    h.set_input("variable", "u_velocity")
    await h.settle(lambda: (h.screen() or {}).get("var") == "u_velocity")
    await h.settle(lambda: (h.screen() or {}).get("vmin") is not None)
    assert len(h.custom("deck_update")) == updates + 1, "the layers are rebuilt"
    assert len(h.custom("deck_fit_bounds")) == fits, "but the user's zoom is kept"

    # a lon/lat mesh ignores the projection: touching it is a no-op
    h.set_input("epsg", "32630")
    await h.flush()
    assert len(h.custom("deck_update")) == updates + 1
    assert len(h.custom("deck_fit_bounds")) == fits

    h.results.set(ugrid(n_time=2))
    await h.settle(lambda: len(h.custom("deck_fit_bounds")) == fits + 1)


async def test_server_says_so_when_a_variable_has_no_valid_values(ugrid):
    h = _Harness()
    h.results.set(ugrid(n_time=3, const=-999.0))  # every value is the fill value
    await h.settle(lambda: "No valid values" in str(h.values("map_message")[-1:]))
    await h.flush()
    assert (h.screen() or {}).get("vmin") is None
    assert (h.screen() or {}).get("no_values") is True
    assert h.values("legend")[-1] is None
    assert "nan" not in str(h.values("map_message")[-1]).lower()
    patches = [lyr for p in h.custom("deck_partial_update") for lyr in p["layers"]]
    assert any(lyr["id"] == "results-mesh" and "_meshColors" in lyr for lyr in patches)


async def test_server_shows_a_frame_that_cannot_be_read(ugrid, monkeypatch, caplog):
    def broken(rf, var, t, level=0):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(results_map, "frame", broken)
    h = _Harness()
    h.results.set(ugrid(n_time=3))
    await h.settle(lambda: "Could not read record 1" in str(h.values("map_message")[-1:]))
    assert "disk gone" in h.values("map_message")[-1]["html"]
    n = len(h.values("map_message"))
    h.set_input("step_fwd", 1)
    await h.flush()
    assert len(h.values("map_message")) == n, "shown once per scene, not on every tick"
    caplog.clear()
