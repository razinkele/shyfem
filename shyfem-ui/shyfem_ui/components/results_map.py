"""Results map: SHYFEM results on a deck.gl map with a time slider and
server-driven playback.

Two UIs share one module namespace: :func:`results_map_controls_ui` (the
sidebar controls) and :func:`results_map_ui` (the map, time label, legend and
messages). :func:`results_map_server` drives both from a ``reactive.Value``
holding the open :class:`~shyfem_ui.services.results_data.ResultsFile`.

A full ``MapWidget.update`` (layers + fit to bounds) happens only when the
scene changes (file, variable, layer or projection); every frame, palette or
colour-range change is a ``patch_layer`` of the mesh colours, so the user's
zoom is kept.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime

import numpy as np
from shiny import module, reactive, render, ui
from shiny.types import SilentException
from shiny_deckgl import MapWidget, fullscreen_widget, screenshot_widget, zoom_widget

from shyfem_ui.components.grid_map import PALETTES, _detect_projected_crs
from shyfem_ui.components.results_map_layers import (
    ARROWS_LAYER_ID,
    RESULTS_LAYER_ID,
    NeedsProjection,
    arrow_paths,
    arrows_layer,
    color_patch,
    legend_html,
    mesh_geometry,
    mesh_layer,
    mesh_lonlat,
    node_colors,
)
from shyfem_ui.services.parser_grd import GrdFile, Node
from shyfem_ui.services.results_data import CURRENT_SPEED, frame, value_range, velocity

_log = logging.getLogger(__name__)

_SPEEDS = {"1": "1 fps", "2": "2 fps", "4": "4 fps"}
_RANGE_MODES = {"auto": "Auto", "manual": "Manual"}
_EPSG_CHOICES = {
    "": "Auto",
    "32630": "UTM 30N",
    "32633": "UTM 33N",
    "32634": "UTM 34N",
    "3003": "Gauss-Boaga W",
    "3004": "Gauss-Boaga E",
    "4326": "WGS84",
}
_MANUAL_RANGE_MSG = "Manual range needs min < max; using auto"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _opt(input, name: str, default):
    """Value of an input that is rendered only sometimes, else ``default``.

    ``name in input`` registers a reactive dependency, so the caller re-runs
    when the input appears.
    """
    return input[name]() if name in input else default


def clamp_index(t: int, n: int) -> int:
    """``t`` clamped to ``0 .. n-1`` (0 when ``n == 0``)."""
    if n <= 0:
        return 0
    return max(0, min(int(t), n - 1))


def next_index(t: int, n: int) -> int:
    """The record after ``t``, wrapping to 0 after the last (0 when ``n == 0``)."""
    if n <= 0:
        return 0
    t = clamp_index(t, n)
    return 0 if t >= n - 1 else t + 1


def format_time(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def pick_variable(current: str | None, rf) -> str:
    """``current`` if the file has it, else the file's first variable."""
    if current in rf.variables:
        return current
    if not rf.variables:
        raise ValueError("the results file has no variables to show")
    return next(iter(rf.variables))


def note_push(pending: list[int], value: int, current_input: int) -> None:
    """Record a server push of the slider to ``value`` so its echo is ignored.

    No echo comes for an unchanged value, and two identical pushes in one
    flush give a single echo.
    """
    if value == current_input:
        return
    if pending and pending[-1] == value:
        return
    pending.append(value)


def pending_echo(pending: list[int], v: int, t: int) -> str:
    """Classify a slider value ``v`` from the client.

    ``"echo"``: the echo of a server push (everything up to and including its
    last occurrence is consumed: one flush batches several pushes into one
    echo); ``"same"``: already the current record; ``"move"``: the user moved it.
    """
    if v in pending:
        last = len(pending) - 1 - pending[::-1].index(v)
        del pending[: last + 1]
        return "echo"
    if v == t:
        return "same"
    return "move"


def _detect_epsg(rf) -> int | None:
    """Gauss-Boaga detection of ``grid_map`` applied to the results mesh."""
    nodes = {
        i + 1: Node(i + 1, 0, float(x), float(y))
        for i, (x, y) in enumerate(zip(rf.node_x, rf.node_y, strict=True))
    }
    return _detect_projected_crs(GrdFile(nodes=nodes))


def _bounds(lonlat: np.ndarray) -> list[list[float]]:
    return [
        [float(lonlat[:, 0].min()), float(lonlat[:, 1].min())],
        [float(lonlat[:, 0].max()), float(lonlat[:, 1].max())],
    ]


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


@module.ui
def results_map_controls_ui():
    """Sidebar controls: variable/level/arrows, playback, range, palette, CRS."""
    return ui.div(
        ui.output_ui("var_controls"),
        ui.div(
            ui.input_action_button(
                "step_back", "◀", class_="btn-sm btn-outline-secondary", title="Previous"
            ),
            ui.input_action_button("play", "Play", class_="btn-sm btn-primary"),
            ui.input_action_button(
                "step_fwd", "▶", class_="btn-sm btn-outline-secondary", title="Next"
            ),
            class_="d-flex gap-1 mb-2",
        ),
        ui.input_slider("t_index", "Record", min=0, max=1, value=0, step=1),
        ui.input_select("speed", "Speed", _SPEEDS, selected="2"),
        ui.input_radio_buttons(
            "range_mode", "Colour range", _RANGE_MODES, selected="auto", inline=True
        ),
        ui.div(
            ui.input_numeric("vmin", "Min", value=None),
            ui.input_numeric("vmax", "Max", value=None),
            class_="d-flex gap-2",
        ),
        ui.input_select(
            "palette", "Palette", {k: k.capitalize() for k in PALETTES}, selected="ocean"
        ),
        ui.input_select("epsg", "Projection", _EPSG_CHOICES, selected=""),
        class_="results-map-controls",
    )


@module.ui
def results_map_ui(height: str = "600px"):
    """The map, the current time, the legend and messages."""
    # MapWidget takes a raw HTML id (not namespaced by @module.ui).
    _map = MapWidget(id=module.resolve_id("deckgl_map"))
    return ui.div(
        ui.output_ui("map_message"),
        ui.div(ui.output_text("time_label"), class_="fw-semibold mb-1"),
        _map.ui(width="100%", height=height),
        ui.div(ui.output_ui("legend"), class_="mt-2"),
        class_="results-map-component",
    )


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


@module.server
def results_map_server(input, output, session, results: reactive.Value):
    """Drive the results map from ``results`` (a ``ResultsFile`` or ``None``).

    Returns a ``reactive.calc`` giving ``{"var", "label", "units", "vmin",
    "vmax"}`` for what is on screen, or ``None``.
    """
    _map = MapWidget(id=module.resolve_id("deckgl_map"))

    t = reactive.value(0)
    playing = reactive.value(False)
    scene = reactive.value(None)
    label_v = reactive.value("")
    legend_v = reactive.value("")
    proj_message = reactive.value("")
    range_message = reactive.value("")
    pending_key: list = [None]
    last_path: list = [None]
    pending: list[int] = []
    warned: set = set()

    def _set(rv: reactive.Value, value) -> None:
        """Compare before set (``Value.set`` dedups by identity only)."""
        with reactive.isolate():
            if rv.get() == value:
                return
        rv.set(value)

    def _clear_scene() -> None:
        with reactive.isolate():
            if scene.get() is None:
                return
        scene.set(None)

    def _push_slider(v: int, max_: int | None = None) -> None:
        with reactive.isolate():
            current = int(input.t_index())
        note_push(pending, v, current)
        if max_ is None:
            ui.update_slider("t_index", value=v, step=1)
        else:
            ui.update_slider("t_index", value=v, step=1, max=max_)

    async def _full_update(layers: list[dict]) -> None:
        await _map.update(
            session,
            layers,
            widgets=[
                zoom_widget(),
                fullscreen_widget(placement="top-right"),
                screenshot_widget(placement="top-right"),
            ],
        )

    @reactive.extended_task
    async def _ranges(key, rf, var, level):
        # value_range loops over every record: off the event loop.
        vmin, vmax = await asyncio.to_thread(value_range, rf, var, level)
        speed_max = None
        if rf.has_currents:
            _, speed_max = await asyncio.to_thread(value_range, rf, CURRENT_SPEED, level)
        return key, vmin, vmax, speed_max

    @reactive.calc
    def effective_range():
        sc = scene.get()
        if sc is None:
            return None
        if input.range_mode() == "manual":
            lo, hi = input.vmin(), input.vmax()
            if (
                lo is not None
                and hi is not None
                and math.isfinite(lo)
                and math.isfinite(hi)
                and lo < hi
            ):
                _set(range_message, "")
                return (float(lo), float(hi))
            _set(range_message, _MANUAL_RANGE_MSG)
            return sc["auto"]
        _set(range_message, "")
        return sc["auto"]

    # (a) scene: file, variable, level, projection -> full update
    @reactive.effect
    async def _scene():
        try:
            rf = results.get()
            if rf is None:
                _ranges.cancel()
                pending_key[0] = None
                _set(playing, False)
                _clear_scene()
                _set(t, 0)
                _push_slider(0)
                await _full_update([])
                _set(proj_message, "")
                _set(label_v, "")
                _set(legend_v, "")
                return
            var = pick_variable(_opt(input, "variable", None), rf)
            level = int(_opt(input, "level", 0))
            level = min(max(level, 0), rf.n_levels - 1)
            epsg = int(input.epsg()) if input.epsg() else None
            key = (id(rf), rf.path, rf.stamp, var, level, epsg)
            if key == pending_key[0]:
                return
            n = len(rf.times)
            try:
                lonlat = mesh_lonlat(rf, epsg)
            except NeedsProjection as exc:
                detected = _detect_epsg(rf) if epsg is None else None
                if detected is None:
                    _ranges.cancel()
                    pending_key[0] = None
                    await _full_update([])
                    _set(proj_message, f"{exc} (Projection, in the controls).")
                    _clear_scene()
                    _set(playing, False)
                    _set(label_v, "")
                    _set(legend_v, "")
                    _set(t, 0)
                    _push_slider(0, max_=max(n - 1, 0))
                    return
                lonlat = mesh_lonlat(rf, detected)
            _set(proj_message, "")
            pending_key[0] = key
            geometry = mesh_geometry(lonlat, rf.faces)
            with reactive.isolate():
                t_now = t.get()
                palette = input.palette()
            t0 = 0 if rf.path != last_path[0] else clamp_index(t_now, n)
            last_path[0] = rf.path
            grey = node_colors(np.full(len(lonlat), np.nan), 0.0, 1.0, palette)
            layers = [mesh_layer(geometry, grey)]
            if rf.has_currents:
                layers.append({**arrows_layer([]), "visible": False})
            await _full_update(layers)
            await _map.fit_bounds(session, bounds=_bounds(lonlat), max_zoom=18, duration=800)
            # interim scene (range still computing): never None while playing
            scene.set(
                {
                    "key": key,
                    "rf": rf,
                    "var": var,
                    "level": level,
                    "geometry": geometry,
                    "lonlat": lonlat,
                    "n": n,
                    "auto": None,
                    "speed_max": None,
                }
            )
            _set(t, t0)
            _push_slider(t0, max_=max(n - 1, 0))
            _ranges.cancel()
            _ranges.invoke(key, rf, var, level)
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: scene update failed: %s", exc, exc_info=True)

    # (a2) the colour range (and arrow scale) of the current scene
    @reactive.effect
    def _ranges_done():
        try:
            key, vmin, vmax, speed_max = _ranges.result()
            if key != pending_key[0]:
                return
            with reactive.isolate():
                sc = scene.get()
            if sc is None:
                return
            scene.set({**sc, "auto": (vmin, vmax), "speed_max": speed_max})
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: colour range failed: %s", exc)
            _set(range_message, f"Could not compute the colour range: {exc}")

    # (b) the user moved the slider
    @reactive.effect
    @reactive.event(input.t_index)
    def _slider():
        try:
            v = int(input.t_index())
            with reactive.isolate():
                cur = t.get()
                sc = scene.get()
            if pending_echo(pending, v, cur) != "move":
                return
            _set(playing, False)
            _set(t, clamp_index(v, sc["n"] if sc else 0))
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: slider failed: %s", exc)

    # (c) play / pause
    @reactive.effect
    @reactive.event(input.play)
    def _play_button():
        try:
            with reactive.isolate():
                sc = scene.get()
                is_playing = playing.get()
            if sc is None:
                return
            playing.set(not is_playing)
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: play button failed: %s", exc)

    # (d) the playback ticker
    @reactive.effect
    def _ticker():
        try:
            is_playing = playing.get()
            fps = float(input.speed())
            with reactive.isolate():
                cur = t.get()
                sc = scene.get()
            if not is_playing or sc is None:
                return
            reactive.invalidate_later(1.0 / fps)
            _set(t, next_index(cur, sc["n"]))
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: playback tick failed: %s", exc)

    # (e) draw the current record: colour patches only
    @reactive.effect
    async def _frame():
        try:
            cur = t.get()
            sc = scene.get()
            if sc is None:
                return
            rng = effective_range()
            if rng is None:
                return  # range still computing
            palette = input.palette()
            rf = sc["rf"]
            arrows = bool(_opt(input, "arrows", False)) if rf.has_currents else False
            n = sc["n"]
            if n == 0:
                return
            tc = clamp_index(cur, n)
            vmin, vmax = rng
            colors = node_colors(frame(rf, sc["var"], tc, sc["level"]), vmin, vmax, palette)
            if len(colors) != len(sc["lonlat"]):
                if sc["key"] not in warned:
                    warned.add(sc["key"])
                    _log.warning(
                        "results map: %d colours for %d nodes; frame skipped",
                        len(colors),
                        len(sc["lonlat"]),
                    )
                return
            await _map.patch_layer(session, RESULTS_LAYER_ID, **color_patch(colors))
            if rf.has_currents and sc["speed_max"] is not None:
                data: list[dict] = []
                if arrows:
                    u, v = velocity(rf, tc, sc["level"])
                    data = arrow_paths(sc["lonlat"], u, v, speed_max=sc["speed_max"])
                await _map.patch_layer(session, ARROWS_LAYER_ID, data=data, visible=arrows)
            info = rf.variables[sc["var"]]
            _set(label_v, f"{format_time(rf.times[tc])} — record {tc + 1} / {n}")
            _set(legend_v, legend_html(palette, vmin, vmax, info.units, info.label))
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: frame failed: %s", exc)

    # (f) step back / forward
    def _step(delta: int) -> None:
        with reactive.isolate():
            cur = t.get()
            sc = scene.get()
        _set(playing, False)
        new = clamp_index(cur + delta, sc["n"] if sc else 0)
        _set(t, new)
        _push_slider(new)

    @reactive.effect
    @reactive.event(input.step_back)
    def _step_back():
        try:
            _step(-1)
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: step back failed: %s", exc)

    @reactive.effect
    @reactive.event(input.step_fwd)
    def _step_fwd():
        try:
            _step(1)
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: step forward failed: %s", exc)

    # (g) play-state button label; the slider catches up on pause
    @reactive.effect
    def _play_state():
        try:
            is_playing = playing.get()
            ui.update_action_button("play", label="Pause" if is_playing else "Play")
            if not is_playing:
                with reactive.isolate():
                    cur = t.get()
                _push_slider(cur)
        except SilentException:
            raise
        except Exception as exc:
            _log.warning("results map: play state failed: %s", exc)

    # ---- outputs -----------------------------------------------------------

    @render.ui
    def var_controls():
        rf = results.get()
        if rf is None:
            return ui.p("No results file loaded.", class_="text-muted small")
        if not rf.variables:
            return ui.p("This file has no variables to show.", class_="text-muted small")
        with reactive.isolate():
            cur_var = _opt(input, "variable", None)
            cur_level = _opt(input, "level", "0")
            cur_arrows = _opt(input, "arrows", False)
        children = [
            ui.input_select(
                "variable",
                "Variable",
                {name: info.label for name, info in rf.variables.items()},
                selected=pick_variable(cur_var, rf),
            )
        ]
        if rf.n_levels > 1:
            try:
                lev = int(cur_level)
            except (TypeError, ValueError):
                lev = 0
            lev = min(max(lev, 0), rf.n_levels - 1)
            levels = {str(i): f"Level {i + 1}" for i in range(rf.n_levels)}
            levels["0"] = "Level 1 (surface)"
            children.append(ui.input_select("level", "Level", levels, selected=str(lev)))
        if rf.has_currents:
            children.append(ui.input_checkbox("arrows", "Current arrows", value=bool(cur_arrows)))
        return ui.TagList(*children)

    @render.text
    def time_label():
        return label_v.get()

    @render.ui
    def legend():
        html = legend_v.get()
        return ui.HTML(html) if html else None

    @render.ui
    def map_message():
        msgs = [m for m in (proj_message.get(), range_message.get()) if m]
        if not msgs:
            return None
        return ui.div(*[ui.div(m) for m in msgs], class_="alert alert-warning py-1 px-2 mb-2")

    # ---- on screen, for the Statistics panel ------------------------------

    @reactive.calc
    def on_screen():
        sc = scene.get()
        if sc is None:
            return None
        info = sc["rf"].variables[sc["var"]]
        rng = effective_range()
        return {
            "var": sc["var"],
            "label": info.label,
            "units": info.units,
            "vmin": rng[0] if rng else None,
            "vmax": rng[1] if rng else None,
        }

    def _close() -> None:
        _ranges.cancel()
        with reactive.isolate():
            rf = results.get()
        if rf is not None:
            rf.close()

    session.on_ended(_close)

    return on_screen
