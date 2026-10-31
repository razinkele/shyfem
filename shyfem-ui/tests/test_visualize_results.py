"""Visualize page: the "SHYFEM results" Data Type (the results map replaces
the broken NetCDF plot, V-01). Pure helpers, the UI layout and source guards
that pin how ``visualize_server`` loads, converts, swaps and clears results.

Any server harness here uses Shiny internals (``AppSession``,
``MockConnection``, ``bookmark._restore_context_value``, the ``clientdata``
hidden flags) and is pinned to shiny ``>=1.8,<1.9``."""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from pathlib import Path

import plotly.graph_objects as go
import pytest

from shyfem_ui.pages import visualize

_SRC = inspect.getsource(visualize)
_TREE = ast.parse(_SRC)


def _server() -> ast.AST:
    for node in ast.walk(_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == "visualize_server":
            return node
    raise AssertionError("visualize_server not found")


def _fn(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in ast.walk(_server()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in visualize_server")


def _src(node: ast.AST) -> str:
    return textwrap.dedent(ast.unparse(node))


def _decorators(node) -> list[str]:
    return [ast.unparse(d) for d in node.decorator_list]


def _ui_html() -> str:
    return str(visualize.visualize_ui("visualize"))


# ---------------------------------------------------------------------------
# Data Type
# ---------------------------------------------------------------------------


def test_netcdf_type_lists_shy_and_nc(tmp_path):
    assert visualize._DATA_TYPE_EXTS["netcdf"] == (".shy", ".nc")
    html = _ui_html()
    assert "SHYFEM results (.shy/.nc)" in html
    assert "NetCDF (.nc)" not in html
    (tmp_path / "run.hydro.shy").write_text("x")
    (tmp_path / "run.ts.nc").write_text("x")
    (tmp_path / "run.grd").write_text("x")
    assert set(visualize._project_file_choices(tmp_path, "netcdf")) == {
        "",
        "run.hydro.shy",
        "run.ts.nc",
    }


# ---------------------------------------------------------------------------
# The old NetCDF plot is gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "_plotly_netcdf",
        "_compare_netcdf",
        "netcdf_controls",
        "_register_dim_labels",
        "nc_var_metadata",
        "nc_variable_table",
        "nc_dim_",
        "nc_variable",
        "_build_vertical_profile",
        "_build_transect",
        "_netcdf_statistics",
        "build_variable_table",
        "get_dim_label",
        "get_variable_attrs",
    ],
)
def test_old_netcdf_code_is_gone(name):
    assert name not in _SRC


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _conditional_blocks(html: str, condition: str) -> list[str]:
    """The inner HTML of every ``panel_conditional`` with ``condition``.

    A naive split: each block runs until the next ``shiny-panel-conditional``
    (the panels here are not nested).
    """
    cond = condition.replace("'", "&apos;")
    marker = f'data-display-if="{cond}"'
    parts = html.split(marker)[1:]
    return [p.split("shiny-panel-conditional")[0] for p in parts]


def test_sidebar_holds_results_controls_only_for_results():
    html = _ui_html()
    results = _conditional_blocks(html, "input.data_type === 'netcdf'")
    others = _conditional_blocks(html, "input.data_type !== 'netcdf'")
    assert any("visualize-results_map-play" in b for b in results), "controls in the sidebar"
    assert any("visualize-results_map-deckgl_map" in b for b in results), "map in the Plot tab"
    joined = "".join(others)
    for control in (
        "visualize-plot_type_select",
        "visualize-colormap",
        "visualize-show_grid_lines",
        "visualize-equal_aspect",
        "visualize-main_plot",
    ):
        assert control in joined, f"{control} hidden for results"
    for block in results:
        assert "visualize-main_plot" not in block
        assert "visualize-colormap" not in block
    # the source pins the exact calls
    assert 'results_map_controls_ui("results_map")' in _SRC
    assert re.search(
        r"ui\.panel_conditional\(\s*\"input\.data_type === 'netcdf'\",\s*"
        r"results_map_ui\(\"results_map\"\)",
        _SRC,
    )
    assert re.search(
        r"ui\.panel_conditional\(\s*\"input\.data_type !== 'netcdf'\",\s*"
        r"output_widget\(\"main_plot\"\)",
        _SRC,
    )


# ---------------------------------------------------------------------------
# Loading: async, extended task, stamps, swap order, clearing
# ---------------------------------------------------------------------------


def test_load_handlers_are_async_and_await_do_load():
    for name in ("_load_data", "_load_compare"):
        fn = _fn(name)
        assert isinstance(fn, ast.AsyncFunctionDef), f"{name} must be async"
        assert "await _do_load(" in _src(fn), name
    assert isinstance(_fn("_do_load"), ast.AsyncFunctionDef)


def test_conversion_is_an_extended_task_awaiting_netcdf_for():
    conv = _fn("_convert")
    assert "reactive.extended_task" in _decorators(conv)
    assert isinstance(conv, ast.AsyncFunctionDef)
    body = _src(conv)
    assert "await netcdf_for(" in body
    assert "return (stamp, nc)" in body or "return stamp, nc" in body
    assert "ShyfemWrapper(config.shyfem_dir)" in _src(_server())


def test_results_map_server_is_wired_to_results_val():
    server = _src(_server())
    assert "results_info = results_map_server('results_map', results=results_val)" in server
    assert "results_val = reactive.value(None)" in server


def test_load_compares_the_source_stamp_before_converting():
    body = _src(_fn("_start_results_load"))
    stamp = _src(_fn("_source_stamp"))
    assert ".resolve()" in stamp and "st_size" in stamp and "st_mtime_ns" in stamp
    # the no-op check precedes cancel/invoke (a cache hit would touch the entry)
    i_same = body.index("== open_source[0]")
    i_cancel = body.index("_convert.cancel()")
    i_invoke = body.index("_convert.invoke(")
    assert i_same < i_cancel < i_invoke
    assert "pending_source[0] = src" in body


def test_netcdf_branch_starts_the_task_and_refuses_comparison():
    body = _src(_fn("_do_load"))
    assert "_start_results_load(" in body
    i = body.index("dtype == 'netcdf'")
    branch = body[i:]
    assert branch.index("is_compare") < branch.index("_start_results_load(")
    assert "_COMPARE_NA" in branch


def test_result_effect_opens_sets_first_closes_after():
    eff = _fn("_convert_done")
    assert "reactive.effect" in _decorators(eff)
    body = _src(eff)
    assert "_convert.result()" in body
    assert "open_results(" in body
    assert "pending_source[0]" in body
    assert "input.data_type()" in body and "reactive.isolate()" in body
    # set the new file first, close the previous one after (after the flush)
    i_set = body.index("results_val.set(rf)")
    i_close = body.index("_close_after_flush(prev)")
    assert i_set < i_close < body.index("_results_data_info(")
    assert "open_source[0] = src" in body
    assert "pending_source[0] = None" in body
    close_after = _src(_fn("_close_after_flush"))
    assert "session.on_flushed(" in close_after
    # errors clear the map, but only a failure of the conversion waited for
    assert "_results_failed(" in body
    assert "getattr(exc, 'source', None) == src" in body
    assert "stamp != src" in body, "staleness is the full source stamp"
    assert "raise _LoadFailed(stamp, str(exc))" in _src(_fn("_convert"))


def test_clear_resets_both_stamps_cancels_and_closes():
    body = _src(_fn("_clear_results"))
    assert "_convert.cancel()" in body
    assert "pending_source[0] = None" in body
    assert "open_source[0] = None" in body
    assert "results_val.set(None)" in body
    assert "_close_after_flush(prev)" in body
    failed = _src(_fn("_results_failed"))
    assert "_clear_results()" in failed and "notification_show" in failed


def test_data_type_switch_clears_results():
    eff = _fn("_on_data_type")
    assert "reactive.event(input.data_type)" in _decorators(eff)
    body = _src(eff)
    assert "_clear_results()" in body


def test_load_button_relabels_while_converting():
    eff = _fn("_convert_status")
    body = _src(eff)
    assert "_convert.status()" in body
    assert "'running'" in body
    assert "Converting" in body and "Load Data" in body
    assert "update_action_button('load_data_btn'" in body


def test_on_ended_closes_under_isolate_and_resets():
    body = _src(_fn("_on_ended"))
    assert "with reactive.isolate():" in body
    assert "results_val.get()" in body and ".close()" in body
    assert "_convert.cancel()" in body
    assert "open_source[0] = None" in body and "pending_source[0] = None" in body
    assert "session.on_ended(_on_ended)" in _src(_server())


@pytest.mark.parametrize("name", ["_convert_done", "_on_data_type", "_convert_status"])
def test_new_effects_reraise_silent_then_log(name):
    eff = _fn(name)
    tries = [s for s in eff.body if isinstance(s, ast.Try)]
    assert tries, f"{name}: the body must be wrapped in try"
    handlers = tries[0].handlers
    assert ast.unparse(handlers[0].type) == "SilentException", name
    assert isinstance(handlers[0].body[0], ast.Raise) and handlers[0].body[0].exc is None
    assert ast.unparse(handlers[1].type) == "Exception", name
    assert ".warning(" in "\n".join(ast.unparse(s) for s in handlers[1].body), name


# ---------------------------------------------------------------------------
# Profile, Comparison, Statistics, Data Info
# ---------------------------------------------------------------------------


def test_profile_and_comparison_say_not_available_for_results():
    for text in (visualize._PROFILE_NA, visualize._COMPARE_NA):
        assert "not available for SHYFEM results yet" in text
        fig = visualize._message_figure(text, height=500)
        assert isinstance(fig, go.Figure)
        assert not fig.data
        assert "not available for SHYFEM results yet" in fig.layout.annotations[0].text
    for name, const in (("profile_plot", "_PROFILE_NA"), ("compare_plot", "_COMPARE_NA")):
        fn = _fn(name)
        assert "render_widget" in _decorators(fn)
        body = [
            s
            for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
        ]
        first = body[0]
        assert isinstance(first, ast.If), f"{name}: the results check comes first"
        assert "input.data_type() == 'netcdf'" in ast.unparse(first.test)
        assert f"_message_figure({const}" in ast.unparse(first.body)
    # "Load for Comparison" with results: the notice, no conversion
    body = _src(_fn("_do_load"))
    branch = body[body.index("dtype == 'netcdf'") :]
    compare = branch[branch.index("if is_compare") : branch.index("_start_results_load(")]
    assert "notification_show(_COMPARE_NA" in compare
    assert "return" in compare


class _Info:
    def __init__(self, name, label, units):
        self.name, self.label, self.units = name, label, units


class _RF:
    def __init__(self):
        from datetime import datetime

        import numpy as np

        self.path = None
        self.variables = {
            "water_level": _Info("water_level", "Water level", "m"),
            "salinity": _Info("salinity", "Salinity", "psu"),
        }
        self.times = [datetime(2001, 1, 1), datetime(2001, 1, 1, 6)]
        self.n_levels = 3
        self.node_x = np.zeros(5)
        self.faces = np.zeros((3, 3), dtype=int)


def test_results_statistics_shows_the_range_on_screen_and_all_units():
    html = str(
        visualize._results_statistics(
            _RF(),
            {"var": "salinity", "label": "Salinity", "units": "psu", "vmin": 30.0, "vmax": 36.5},
        )
    )
    assert "Salinity" in html and "30" in html and "36.5" in html
    assert "Water level" in html and "psu" in html and ">m<" in html
    computing = str(
        visualize._results_statistics(
            _RF(),
            {"var": "salinity", "label": "Salinity", "units": "psu", "vmin": None, "vmax": None},
        )
    )
    assert "computing" in computing
    empty = str(
        visualize._results_statistics(
            _RF(),
            {
                "var": "salinity",
                "label": "Salinity",
                "units": "psu",
                "vmin": None,
                "vmax": None,
                "no_values": True,
            },
        )
    )
    assert "no valid values" in empty and "computing" not in empty
    assert "Load a SHYFEM results file" in str(visualize._results_statistics(None, None))


def test_results_data_info():
    from pathlib import Path

    info = visualize._results_data_info(_RF(), Path("/p/run.hydro.shy"))
    assert info["file"] == "/p/run.hydro.shy"
    assert info["variables"] == ["water_level", "salinity"]
    assert info["records"] == 2
    assert info["nodes"] == 5 and info["elements"] == 3 and info["levels"] == 3
    assert info["first_time"] == "2001-01-01 00:00" and info["last_time"] == "2001-01-01 06:00"


def test_statistics_for_results_reads_the_map_calc():
    body = _src(_fn("var_statistics"))
    assert "input.data_type() == 'netcdf'" in body
    assert "_results_statistics(results_val.get(), results_info())" in body


# ---------------------------------------------------------------------------
# The page server on a mock session (no browser)
# ---------------------------------------------------------------------------


class _Page:
    """``visualize_server`` on a real ``AppSession`` over a mock connection."""

    def __init__(self, project_dir, home, monkeypatch):
        import json

        from shiny import App, reactive, ui
        from shiny._connection import MockConnection
        from shiny.session import session_context
        from shiny.session._session import AppSession
        from shiny.types import ActionButtonValue

        from shyfem_ui.config import Config
        from shyfem_ui.services import results_cache

        self.project_dir = Path(project_dir)
        self.sent: list[dict] = []
        self.converted: list = []
        self.opened: list = []
        sent, converted, opened = self.sent, self.converted, self.opened
        real_netcdf_for, real_open = results_cache.netcdf_for, visualize.open_results

        async def _netcdf_for(path, user, config, wrapper):
            converted.append(path)
            return await real_netcdf_for(path, user, config, wrapper)

        def _open(nc):
            rf = real_open(nc)
            opened.append(rf)
            return rf

        monkeypatch.setattr(visualize, "netcdf_for", _netcdf_for)
        monkeypatch.setattr(visualize, "open_results", _open)
        self.notes: list[str] = []
        real_notify = ui.notification_show
        notes = self.notes

        def _notify(msg, *a, **kw):
            notes.append(str(msg))
            return real_notify(msg, *a, **kw)

        monkeypatch.setattr(visualize.ui, "notification_show", _notify)

        class _Conn(MockConnection):
            async def send(self, message):
                sent.append(json.loads(message))

        self._abv = ActionButtonValue
        self.session = AppSession(App(ui.page_fluid(), None), "s1", _Conn())
        self.session.bookmark._restore_context_value = None
        self.scope = self.session.make_scope("v")
        self.project = reactive.value(
            {"id": 1, "name": "p", "work_dir": str(project_dir), "files": []}
        )
        self.clicks = {"load_data_btn": 0, "load_compare_btn": 0}
        cfg = Config(work_dir=home)
        with session_context(self.session):
            self.scope.input["data_type"]._set("grid")
            for b in self.clicks:
                self.scope.input[b]._set(ActionButtonValue(0))
            visualize.visualize_server("v", cfg, active_project=self.project)

    def set(self, name, value):
        self.scope.input[name]._set(value)

    def click(self, name):
        self.clicks[name] += 1
        self.scope.input[name]._set(self._abv(self.clicks[name]))

    async def flush(self):
        from shiny import reactive

        await reactive.flush()
        # Send the session's outputs. Shiny < 1.9 did that in `_flush()`;
        # 1.9 renamed the step `_output_flush()` and runs it in a task of its
        # own once the session's effects have finished (so it may send
        # nothing while an effect is still running; `settle()` flushes again).
        send = getattr(self.session, "_output_flush", None) or self.session._flush
        await send()

    async def settle(self, cond, timeout=5.0):
        import asyncio

        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while True:
            await self.flush()
            if cond():
                return
            assert loop.time() < end, "timed out"
            await asyncio.sleep(0.02)

    async def idle(self, n=10):
        import asyncio

        for _ in range(n):
            await self.flush()
            await asyncio.sleep(0.01)

    def load_labels(self):
        return [
            (msg["message"].get("label") or {}).get("html")
            for m in self.sent
            for msg in m.get("inputMessages", [])
            if msg["id"] == "v-load_data_btn"
        ]


@pytest.fixture
def make_page(tmp_path, monkeypatch):
    """Builds the page inside the (async) test, on the test's event loop."""
    from tests._ugrid_fixture import write_ugrid

    proj = tmp_path / "proj"
    proj.mkdir()
    write_ugrid(proj / "hydro.nc", n_time=6, kind="hydro")
    write_ugrid(proj / "ts.nc", n_time=3, kind="ts")
    (proj / "bad.nc").write_bytes(b"not a netcdf")
    pages: list[_Page] = []

    def _make() -> _Page:
        pages.append(_Page(proj, tmp_path / "home", monkeypatch))
        return pages[-1]

    yield _make
    for p in pages:
        for rf in p.opened:
            rf.close()


async def _load(p, rel):
    p.set("project_file", rel)
    p.click("load_data_btn")


async def test_page_loads_noops_swaps_and_clears(make_page):
    p = make_page()
    p.set("data_type", "netcdf")
    await p.flush()

    await _load(p, "hydro.nc")
    await p.settle(lambda: len(p.opened) == 1)
    hydro = p.opened[0]
    assert len(hydro.times) == 6 and not hydro._closed
    assert "Converting …" in p.load_labels() and p.load_labels()[-1] == "Load Data"

    # the same file again: no conversion, nothing reopened or closed
    await _load(p, "hydro.nc")
    await p.idle()
    assert len(p.converted) == 1 and len(p.opened) == 1 and not hydro._closed
    assert any("already open" in n for n in p.notes)

    # another file: the new one is opened, then the previous one closed
    await _load(p, "ts.nc")
    await p.settle(lambda: len(p.opened) == 2 and hydro._closed)
    ts = p.opened[1]
    assert not ts._closed

    # Comparison with results: a notice, no conversion
    p.set("compare_file", "hydro.nc")
    p.click("load_compare_btn")
    await p.idle()
    assert len(p.converted) == 2
    assert any("Comparison is not available for SHYFEM results yet" in n for n in p.notes)

    # switching the Data Type away closes the file and forgets what was open
    p.set("data_type", "grid")
    await p.settle(lambda: ts._closed)
    p.set("data_type", "netcdf")
    await p.flush()
    await _load(p, "ts.nc")
    await p.settle(lambda: len(p.opened) == 3)
    assert len(p.converted) == 3, "a cleared map reloads the file"

    # a file that is not a results file: an error, the open file stays open
    current = p.opened[2]
    await _load(p, "bad.nc")
    await p.settle(lambda: any("Could not open" in n for n in p.notes))
    await p.idle()
    assert len(p.opened) == 3 and not current._closed
    assert any("still showing ts.nc" in n for n in p.notes)

    # and the open file is still what is open: loading it again is a no-op
    n_notes = len(p.notes)
    await _load(p, "ts.nc")
    await p.idle()
    assert len(p.opened) == 3
    assert any("already open" in n for n in p.notes[n_notes:])

    await p.session._on_ended_callbacks.invoke()
    assert current._closed


async def test_page_drops_a_result_after_a_data_type_switch(make_page):
    p = make_page()
    p.set("data_type", "netcdf")
    await p.flush()
    await _load(p, "hydro.nc")
    p.set("data_type", "grid")  # before the task's result is read
    await p.idle(20)
    assert p.opened == [], "a result arriving after the switch is not opened"


async def test_page_reports_a_failed_conversion(make_page, monkeypatch):
    from shyfem_ui.services.results_cache import ConversionError

    p = make_page()

    async def _fail(path, user, config, wrapper):
        p.converted.append(path)
        raise ConversionError(f"Cannot convert {path.name}: boom")

    monkeypatch.setattr(visualize, "netcdf_for", _fail)
    p.set("data_type", "netcdf")
    await p.flush()
    await _load(p, "hydro.nc")
    await p.settle(lambda: any("Cannot convert hydro.nc: boom" in n for n in p.notes))
    assert p.opened == []
    assert p.load_labels()[-1] == "Load Data", "a failed conversion restores the button"


async def test_page_keeps_the_open_file_when_a_conversion_fails(make_page, monkeypatch):
    from shyfem_ui.services.results_cache import ConversionError

    p = make_page()
    p.set("data_type", "netcdf")
    await p.flush()
    await _load(p, "hydro.nc")
    await p.settle(lambda: len(p.opened) == 1)
    hydro = p.opened[0]

    async def _fail(path, user, config, wrapper):
        raise ConversionError(f"Cannot convert {path.name}: boom")

    monkeypatch.setattr(visualize, "netcdf_for", _fail)
    await _load(p, "ts.nc")
    await p.settle(lambda: any("Cannot convert ts.nc: boom" in n for n in p.notes))
    await p.idle()
    assert not hydro._closed, "a failed Load keeps the file on the map"
    assert any("still showing hydro.nc" in n for n in p.notes)
    assert p.load_labels()[-1] == "Load Data"

    # what is open is still known: the same file again is a no-op
    await _load(p, "hydro.nc")
    await p.idle()
    assert len(p.opened) == 1 and any("already open" in n for n in p.notes)


async def test_page_a_newer_load_wins_over_a_running_conversion(make_page, monkeypatch):
    """Load A, then B while A converts: only B opens; A's late error is ignored."""
    import asyncio

    p = make_page()
    gates = {"hydro.nc": asyncio.Event(), "ts.nc": asyncio.Event()}
    fail_a = {"on": False}

    async def _gated(path, user, config, wrapper):
        p.converted.append(path)
        try:
            await gates[path.name].wait()
        except asyncio.CancelledError:
            if fail_a["on"] and path.name == "hydro.nc":
                raise RuntimeError("A failed late") from None
            raise
        return path

    monkeypatch.setattr(visualize, "netcdf_for", _gated)
    p.set("data_type", "netcdf")
    await p.flush()

    # A then B: A is cancelled, B runs, only B is opened
    await _load(p, "hydro.nc")
    await p.idle()
    await _load(p, "ts.nc")
    await p.idle()
    gates["hydro.nc"].set()
    await p.idle()
    assert p.opened == [], "A's result is not opened"
    gates["ts.nc"].set()
    await p.settle(lambda: len(p.opened) == 1)
    assert len(p.opened[0].times) == 3, "B (ts) is what opened"
    assert [c.name for c in p.converted] == ["hydro.nc", "ts.nc"]

    # A fails while B is pending: no error, B still opens
    for g in gates.values():
        g.clear()
    fail_a["on"] = True
    p.set("data_type", "grid")  # forget what is open
    await p.idle()
    p.set("data_type", "netcdf")
    await p.flush()
    n_notes = len(p.notes)
    await _load(p, "hydro.nc")
    await p.idle()
    await _load(p, "ts.nc")
    await p.idle()
    gates["ts.nc"].set()
    await p.settle(lambda: len(p.opened) == 2)
    assert not any("A failed late" in n for n in p.notes[n_notes:])
    assert p.load_labels()[-1] == "Load Data"


async def test_page_closes_the_previous_file_when_a_later_step_fails(make_page, monkeypatch):
    p = make_page()
    p.set("data_type", "netcdf")
    await p.flush()
    await _load(p, "hydro.nc")
    await p.settle(lambda: len(p.opened) == 1)
    hydro = p.opened[0]

    def _boom(rf, source):
        raise RuntimeError("info failed")

    monkeypatch.setattr(visualize, "_results_data_info", _boom)
    await _load(p, "ts.nc")
    await p.settle(lambda: any("info failed" in n for n in p.notes))
    await p.idle()
    assert len(p.opened) == 2
    assert hydro._closed, "the previous file is closed even though a later step raised"
    assert p.opened[1]._closed, "the failed new file is closed too"


async def test_page_drops_a_result_for_a_file_changed_during_conversion(make_page, monkeypatch):
    """Staleness is the full source stamp: the same path, rewritten while it
    converts and loaded again, drops the old result and converts again."""
    import asyncio
    import os

    p = make_page()
    gates: list[asyncio.Event] = []

    async def _gated(path, user, config, wrapper):
        p.converted.append(path)
        gate = asyncio.Event()
        gates.append(gate)
        try:
            await gate.wait()
        except asyncio.CancelledError:
            pass  # finish anyway: the stale result must be dropped by its stamp
        return path

    monkeypatch.setattr(visualize, "netcdf_for", _gated)
    p.set("data_type", "netcdf")
    await p.flush()
    await _load(p, "hydro.nc")
    await p.settle(lambda: len(gates) == 1)

    src = p.project_dir / "hydro.nc"
    st = src.stat()
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    await _load(p, "hydro.nc")
    await p.idle()
    assert p.opened == [], "the result of the old stamp is not opened"
    await p.settle(lambda: len(gates) == 2)
    gates[1].set()
    await p.settle(lambda: len(p.opened) == 1)
    assert len(p.converted) == 2, "the changed file was converted again"

    # and the new stamp is what is open: Load again is a no-op
    await _load(p, "hydro.nc")
    await p.idle()
    assert len(p.converted) == 2 and len(p.opened) == 1
