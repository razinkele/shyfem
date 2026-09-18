"""Box model page (spec §8): Map and Time-series tabs over the Parquet cache.

Everything below the page already exists as a reviewed service: the manifest
loader, the cache service (child-process builds + registry + two-step
publish), the skill metrics, the box polygons and the grid map's box layers.
This module is the integration layer, and it carries the page-level
obligations the reviews of those services handed forward:

* every manifest / observation / polygon / cache failure becomes a page
  message -- no exception ever escapes a render or an effect;
* no raw absolute host path reaches the browser: every user-facing
  string from a service -- exception text via :func:`_safe_error`, and
  ``CacheStatus.message`` via :func:`_safe_text` -- has its path-looking
  tokens rewritten with ``config.display_path``;
* all manifest-, label- and site-supplied text is emitted through
  ``ui.tags`` (never ``ui.HTML``), so it is escaped; the one place text
  reaches raw HTML is the deck.gl tooltip, and that is escaped where the
  HTML is built, in ``build_box_layers`` -- escaping it here as well
  would double-escape an ampersand in a legitimate site name;
* writes (build / cancel) are gated by ``editor_denied_reason`` *inside*
  the handler -- hiding a button is only cosmetic;
* builds run with a bounded timeout (``config.command_timeout_seconds``
  defaults to ``None`` = unbounded);
* ``reconcile_tmp_dirs`` runs at page load inside a ``try``;
* the status poller owns its own trigger: it re-arms itself only while a
  build is live and never reads anything it writes, so there is no
  reactive self-write loop.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.grid_map import (
    _detect_projected_crs,
    _is_geographic,
    build_box_layers,
    grid_map_server,
    grid_map_ui,
)
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.boxmodel_cache import (
    BuildRegistry,
    cache_dir_for,
    cache_status,
    cancel_build,
    load_cache,
    load_cache_state,
    reconcile_tmp_dirs,
    start_build,
)
from shyfem_ui.services.boxmodel_manifest import ManifestError, load_manifest
from shyfem_ui.services.boxmodel_polygons import (
    PolygonError,
    dissolve_boxes_from_grid,
    load_box_polygons,
)
from shyfem_ui.services.boxmodel_skill import (
    VARIABLE_COLUMNS,
    ObservationError,
    band_amplitude_ratios,
    load_observations,
    load_sites,
    model_series,
)
from shyfem_ui.services.boxmodel_skill import skill_table as compute_skill_table
from shyfem_ui.services.parser_grd import GrdParser

logger = logging.getLogger(__name__)

#: One registry per worker process -- every session on this worker shares it,
#: which is what makes the per-worker/per-user build caps meaningful.
REGISTRY = BuildRegistry()

# shiny 1.7 renamed @render.download to @render.download_button and the old
# name is deprecated; resolve whichever this shiny provides (mesh_builder.py).
_render_download = getattr(render, "download_button", None) or render.download

#: Fallback wall-clock cap for one cache build. ``Config.command_timeout_seconds``
#: defaults to ``None`` (unbounded) and ``start_build`` reads the timeout from
#: the Config it is handed, so the page supplies a bounded one.
BUILD_TIMEOUT_SECONDS = 30 * 60
POLL_SECONDS = 2
#: States in which no build is running, so the cache on disk is settled.
_TERMINAL_STATES = ("ready", "stale", "failed", "missing")
#: States in which a build is queued or running.
_LIVE_STATES = ("queued", "building")

VARIABLES = {"salt": "Salinity (psu)", "temp": "Temperature (°C)", "act_eta": "Water level (m)"}
#: Column order of the band-amplitude table, matching ``BANDS`` in
#: ``boxmodel_skill`` and the keys ``band_amplitude_ratios`` returns.
BAND_COLUMNS = ("2-4 d", "4-10 d", "10-30 d", "30-400 d")
BAND_NEEDS_DAYS = "needs \u2265 120 gap-free days"
NO_POLYGONS_MESSAGE = (
    "No box outlines: add boxes.polygons to the manifest or run the model "
    "with boxes_geom.txt output."
)
#: Everything a downloaded file name may contain; anything else is dropped.
_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
COLUMN_TO_VARIABLE = {v: k for k, v in VARIABLE_COLUMNS.items()}
MAP_MODES = {
    "day": "Value on the selected day",
    "mean": "Period mean",
    "bias": "Bias vs observations (posts)",
}
_STATE_BADGE = {
    "ready": "success",
    "stale": "warning",
    "building": "info",
    "queued": "info",
    "failed": "danger",
    "missing": "secondary",
}

# An absolute-path-looking token: a "/" that does NOT continue a word,
# followed by one or more segments. The lookbehind is what keeps ordinary
# prose intact -- in "3/24 rows" and "wind in m/s" the slash follows a word
# character, so neither is a path and neither is rewritten -- while a
# genuine single-segment root ("/etc", "/tmp") is still caught.
_ABS_PATH_RE = re.compile(r"(?<![\w])/[\w.@+~-]+(?:/[\w.@+~-]*)*")


def _safe_text(text: str, config, user) -> str:
    """Rewrite every absolute-path-looking token in ``text`` for display.

    ``Config.display_path`` reduces a server-mode path to ``~/rel`` or to its
    basename, and leaves a local-mode (single-user desktop) path alone. The
    surrounding words -- the part that says *what* is wrong -- are kept, so
    the message stays actionable.

    Use this for **any** service-provided string that reaches the browser,
    not just exceptions: ``CacheStatus.message`` carries the failed build
    child's own error text (e.g. a ``FileNotFoundError`` naming the absolute
    run directory), and it is rendered as the status badge's tooltip.
    """
    return _ABS_PATH_RE.sub(lambda m: config.display_path(m.group(0), user), str(text))


def _safe_error(exc: BaseException, config, user) -> str:
    """:func:`_safe_text` for an exception.

    ``ManifestError`` (and the ``ValueError`` ``confine_path`` raises inside
    ``load_manifest``/``start_build``) embeds the raw absolute path it
    rejected.
    """
    return _safe_text(str(exc), config, user)


def _bounded_timeout_config(config: Config) -> Config:
    """Return a Config whose ``command_timeout_seconds`` is bounded.

    ``start_build`` passes ``config.command_timeout_seconds`` straight to
    ``asyncio.wait_for``; ``None`` there means a wedged build occupies a
    worker slot forever. Never mutate the shared Config (one instance backs
    every session on this worker) -- hand ``start_build`` a copy instead.
    An operator-configured value is respected as-is; only the ``None``
    default is replaced.
    """
    if config.command_timeout_seconds is not None:
        return config
    return config.model_copy(update={"command_timeout_seconds": BUILD_TIMEOUT_SECONDS})


def _fmt(x, nd: int = 3) -> str:
    """Format a metric, rendering None/NaN as an empty cell."""
    if x is None:
        return ""
    try:
        value = float(x)
    except (TypeError, ValueError):
        return ""
    if value != value:  # NaN
        return ""
    return f"{value:.{nd}f}"


def _bias_cell(variable: str, bias) -> str:
    """Level skill is computed on anomalies (both reference scripts do this),
    so a level row's bias is structurally ~0 and means nothing. Show a dash
    rather than a number a reader would take for a real offset.
    """
    return "—" if variable == "level" else _fmt(bias)


def _band_ratio_rows(cached_run, obs, sites, start, end) -> list[dict]:
    """One row per LEVEL target (a site with a mapped box and level
    observations) with its band amplitude ratios, for the table beside the
    skill table (spec sec7).

    ``{"site": str, "ratios": dict | None}``; ``ratios`` is ``None`` when
    :func:`band_amplitude_ratios` cannot be computed -- it needs at least 120
    gap-free (one-per-calendar-day) common days, which is a much stronger
    requirement than the skill table's 30 matched days, so a run can have a
    full skill row and no band ratios at all.

    Module-level and reactive-free so it can be tested without a session.
    """
    rows: list[dict] = []
    if obs is None or sites is None or cached_run is None:
        return rows
    low, high = pd.Timestamp(start), pd.Timestamp(end)
    for _, site in sites.dropna(subset=["box"]).iterrows():
        picked = obs[(obs["site"] == site["site"]) & (obs["variable"] == "level")]
        picked = picked[(picked["date"] >= low) & (picked["date"] <= high)]
        if not len(picked):
            continue
        box = int(site["box"])
        observed = pd.Series(
            picked["value"].to_numpy(), index=pd.Index(picked["date"])
        ).sort_index()
        model = model_series(cached_run, box, VARIABLE_COLUMNS["level"], start, end)
        rows.append({"site": str(site["site"]), "ratios": band_amplitude_ratios(observed, model)})
    return rows


def _no_polygons_message(manifest_obj, cached_run) -> str | None:
    """The message for a project that has no box outlines at all.

    A manifest without ``boxes.polygons`` falls back to dissolving the boxes
    out of the grid, which needs ``meta["element_box"]`` -- i.e. the run must
    have been written with ``boxes_geom.txt``. With neither, the map is blank
    and nothing said why. Returns ``None`` while there is no cache yet: that
    is not "no outlines", it is "not known yet".
    """
    if manifest_obj is None or manifest_obj.polygons is not None:
        return None
    if cached_run is None or cached_run.meta.get("element_box"):
        return None
    return NO_POLYGONS_MESSAGE


def _series_filename(data) -> str:
    """Download name built from the box/variable ``series()`` actually
    resolved, not from the raw inputs.

    ``input.box()``/``input.variable()`` are client-supplied strings that
    reach a Content-Disposition header; ``series()`` has already validated
    both (``int(selected)``, ``column in VARIABLES``). Everything outside
    ``[A-Za-z0-9_-]`` is dropped as a second line of defence.
    """
    if not data:
        return "box_series.csv"
    box = _FILENAME_UNSAFE.sub("", str(data.get("box", ""))) or "x"
    variable = _FILENAME_UNSAFE.sub("", str(data.get("variable", ""))) or "series"
    return f"box{box}_{variable}.csv"


def _reconcile_cache_dir(config, user, work_dir, project_name=None, project_id=None) -> str | None:
    """Publish finished builds and clear dead tmp dirs -- if the caller may write.

    Returns a page notice, or ``None`` when there is nothing to report.

    ``reconcile_tmp_dirs`` RENAMES and DELETES inside the project, so it needs
    the WRITE confinement, not the read one the manifest load uses:
    ``for_write=False`` also admits a shared-project viewer and an
    analysis-root reader, and this page server is mounted for every session. A
    viewer has nothing to reconcile, so failing the write check just skips it,
    silently -- it is not an error the viewer could act on.

    ``REGISTRY`` and ``project_id`` are handed over so the reconcile can tell
    a build running in THIS worker from an abandoned directory: without them
    it decides purely on ``progress.json``'s age, and a page load during a
    long, quiet build phase would delete that build's own output directory.

    Module-level and dependency-free (it takes the config, the user and the
    directory) so the gate can be tested without a live Shiny session.
    """
    try:
        config.confine_path(Path(work_dir), user, must_exist=True, for_write=True)
    except (ValueError, OSError) as exc:
        logger.info("boxmodel: skipping cache reconcile (no write access): %s", exc)
        return None
    try:
        for msg in reconcile_tmp_dirs(Path(work_dir), registry=REGISTRY, project_id=project_id):
            logger.info("boxmodel cache reconcile (%s): %s", project_name, msg)
    except Exception as exc:  # noqa: BLE001 - page load must never die here
        logger.warning("boxmodel: cache reconcile failed: %s", exc, exc_info=True)
        return "Could not tidy the cache directory; a build may need to be re-run."
    return None


def _remember_good(last: dict, project_id, run_id: str, cached_run) -> None:
    """Remember a successfully loaded run, KEYED by the run it belongs to."""
    last["good"] = (project_id, run_id, cached_run)


def _pick_live_fallback(last: dict, project_id, run_id: str):
    """The previously loaded run to keep showing during a rebuild -- but only
    if it is the run currently selected.

    The slot must be keyed. Unkeyed, this sequence silently shows the wrong
    data: run A ready -> Build A -> switch to run B (ready, so B is loaded and
    remembered) -> switch back to A while A is still building -> the live
    branch hands back B's frame while the Run select and the badge both say A,
    so the map, the series and the skill table are all B's.
    """
    stored = last.get("good")
    if not stored:
        return None
    stored_project, stored_run, cached_run = stored
    if stored_project == project_id and stored_run == run_id:
        return cached_run
    return None


def _cache_period(cached_run) -> tuple:
    meta = cached_run.meta.get("period") or {}
    return pd.Timestamp(meta["start"]).date(), pd.Timestamp(meta["end"]).date()


@module.ui
def boxmodel_ui() -> ui.Tag:
    """Box-model page UI: run/variable/period controls plus Map and Time-series tabs."""
    return ui.div(
        ui.h3("Box model"),
        ui.p(
            "Aggregated box output for this project's runs: maps of a box variable "
            "and per-box time series against observations.",
            class_="text-muted",
        ),
        ui.output_ui("manifest_error"),
        ui.layout_columns(
            ui.input_select("run", "Run", choices={}),
            ui.input_select("variable", "Variable", choices=VARIABLES),
            ui.input_date_range("period", "Period"),
            ui.div(
                ui.output_ui("cache_state"),
                ui.input_action_button("build", "Build cache", class_="btn-primary btn-sm me-1"),
                ui.input_action_button("cancel", "Cancel", class_="btn-outline-secondary btn-sm"),
            ),
            col_widths=(3, 2, 4, 3),
        ),
        ui.navset_card_tab(
            ui.nav_panel(
                "Map",
                ui.layout_columns(
                    ui.div(
                        ui.input_select("map_mode", "Colour by", MAP_MODES),
                        ui.output_ui("day_slider"),
                    ),
                    grid_map_ui("boxmap", height="540px"),
                    ui.output_ui("map_legend"),
                    col_widths=(3, 7, 2),
                ),
            ),
            ui.nav_panel(
                "Time series",
                ui.layout_columns(
                    ui.input_select("box", "Box", choices={}),
                    ui.download_button(
                        "download_csv", "Export CSV", class_="btn-outline-primary btn-sm mt-4"
                    ),
                    col_widths=(3, 3),
                ),
                output_widget("ts_plot"),
                ui.output_ui("skill_table"),
                ui.output_ui("band_ratios"),
            ),
            ui.nav_panel(
                "Run comparison",
                ui.p(
                    "Fit statistics of every ready run against observations, "
                    "over the days all runs share.",
                    class_="text-muted small",
                ),
                ui.output_ui("run_comparison_table"),
            ),
            id="tabs",
        ),
    )


@module.server
def boxmodel_server(
    input,
    output,
    session,
    config: Config,
    active_project: reactive.Value,
    tutorial_context=None,
    current_user=None,
) -> dict:
    """Box-model page server."""
    extra_layers: reactive.Value = reactive.value([])
    legend_bins: reactive.Value = reactive.value([])
    grd_file: reactive.Value = reactive.value(None)
    grd_error: reactive.Value = reactive.value(None)
    selected_box: reactive.Value = reactive.value(None)
    # Three write-only-for-their-writer values, deliberately kept apart:
    #
    # * poll_kick     -- written ONLY by the build/cancel handlers, read ONLY
    #                    by the poller (so a fresh build restarts polling);
    # * status_tick   -- written ONLY by the poller, read ONLY by status(),
    #                    which only the badge renders. It ticks every 2 s
    #                    during a build so the records/expected progress
    #                    moves;
    # * cache_generation -- written ONLY by the poller, and only when the
    #                    cache's *contents* can actually have changed (a
    #                    terminal state reached or left). Everything
    #                    expensive hangs off THIS, not off status_tick:
    #                    cached_result -> polygons_result/series/skill.
    #                    Coupling them would re-run load_box_polygons (a
    #                    fiona re-open, on the event loop) and push a fresh
    #                    layer set every 2 s while a build runs -- the map
    #                    would flicker and the worker would do real work per
    #                    tick for nothing.
    #
    # No value here is ever read by the effect that writes it: a read-then-write
    # on the same reactive pegs the worker at 100% CPU and freezes every output
    # (see the shiny reactive-loop postmortem).
    poll_kick: reactive.Value = reactive.value(0)
    status_tick: reactive.Value = reactive.value(0)
    cache_generation: reactive.Value = reactive.value(0)
    # Plain (non-reactive) per-session bookkeeping, deliberately not
    # reactive.Values: read-then-write on a reactive from the same effect is
    # exactly the loop above.
    counters = {"kick": 0, "tick": 0, "generation": 0}
    last = {
        "state": None,
        "runs": None,
        "boxes": None,
        "period": None,
        "grd": False,
        "good": None,
        "project": None,
    }

    def _user():
        return current_user() if current_user is not None else None

    def _project():
        return active_project.get() if active_project is not None else None

    def _err(exc: BaseException) -> str:
        return _safe_error(exc, config, _user())

    def _text(text: str) -> str:
        """Sanitise a service-provided string before it reaches the browser."""
        return _safe_text(text, config, _user())

    def _kick_poller() -> None:
        counters["kick"] += 1
        poll_kick.set(counters["kick"])

    def _bump_status() -> None:
        """Badge-only refresh (build progress). Cheap: nothing heavy reads it."""
        counters["tick"] += 1
        status_tick.set(counters["tick"])

    def _bump_cache_generation() -> None:
        """The cache's contents may have changed -- re-read it and everything
        derived from it. Only ever called on a terminal-state transition."""
        counters["generation"] += 1
        cache_generation.set(counters["generation"])

    # --- manifest ---------------------------------------------------------

    @reactive.calc
    def manifest_result() -> tuple:
        """``(manifest, error, notice)`` -- never raises.

        The project's work_dir is routed through ``confine_path`` before it
        reaches ``load_manifest`` (the loader confines the paths *inside* the
        manifest but not the project directory it is handed -- that is the
        caller's job).
        """
        proj = _project()
        if proj is None:
            return None, "Open a project first.", None
        usr = _user()
        try:
            project_dir = config.confine_path(
                Path(proj["work_dir"]), usr, must_exist=True, for_write=False
            )
        except (ValueError, OSError) as exc:
            logger.warning("boxmodel: project directory rejected: %s", exc)
            return None, _err(exc), None
        try:
            manifest_obj = load_manifest(project_dir, config, usr)
        except ManifestError as exc:
            return None, _err(exc), None
        except (OSError, ValueError) as exc:
            logger.warning("boxmodel: manifest could not be read: %s", exc)
            return None, _err(exc), None

        # Publish any build that finished while nobody was watching and clear
        # dead tmp dirs -- before anything reads the cache status, so a
        # just-finished build shows as "ready" straight away. Gated on the
        # WRITE confinement and never raising; see _reconcile_cache_dir.
        notice = _reconcile_cache_dir(
            config, usr, proj["work_dir"], proj.get("name"), proj.get("id")
        )
        return manifest_obj, None, notice

    def manifest():
        return manifest_result()[0]

    @reactive.effect
    def _forget_cached_run_on_project_change():
        """Drop the remembered run when the project changes.

        ``_pick_live_fallback`` already refuses to hand back a run that is not
        the selected one, so this is not what makes the fallback correct -- it
        is so a session that moves to another project stops holding the old
        project's DataFrames.
        """
        proj = _project()
        project_id = proj["id"] if proj else None
        if project_id != last["project"]:
            last["project"] = project_id
            last["good"] = None

    @reactive.effect
    def _fill_runs():
        manifest_obj = manifest()
        choices = {r.id: r.label for r in manifest_obj.runs} if manifest_obj is not None else {}
        if choices == last["runs"]:
            return
        last["runs"] = choices
        ui.update_select("run", choices=choices, selected=next(iter(choices), None))

    @reactive.effect
    def _load_grd():
        """Parse the manifest's .grd once per manifest change.

        ``grid_map_server`` expects a parsed ``GrdFile`` in its ``grd_file``
        reactive, not a path, and the box layers must always be paired with a
        real grid (the no-grid path in grid_map renders no basemap and no
        legend).
        """
        manifest_obj = manifest()
        path = str(manifest_obj.grd) if manifest_obj is not None else None
        if last["grd"] and path == last.get("grd_path"):
            return
        last["grd"] = True
        last["grd_path"] = path
        if path is None:
            grd_file.set(None)
            grd_error.set(None)
            return
        try:
            grd_file.set(GrdParser.parse_file(Path(path)))
            grd_error.set(None)
        except Exception as exc:  # noqa: BLE001 - any parser failure is a page message
            logger.warning("boxmodel: grid could not be parsed: %s", exc)
            grd_file.set(None)
            grd_error.set(f"Grid: {_err(exc)}")

    def _run_entry():
        manifest_obj = manifest()
        run_id = input.run()
        runs = manifest_obj.runs if manifest_obj is not None else []
        return next((r for r in runs if r.id == run_id), None)

    # --- cache status and the poller --------------------------------------

    def _status_now():
        """Current cache status, deliberately independent of ``status_tick``.

        Both the poller and ``cached_result`` call this rather than
        ``status()``: the poller so that bumping the tick cannot re-trigger
        itself, and ``cached_result`` so that the 2 s badge tick does not drag
        the whole parquet/polygon/layer chain along with it.
        """
        manifest_obj = manifest()
        run = _run_entry()
        proj = _project()
        if manifest_obj is None or run is None or proj is None:
            return None
        try:
            return cache_status(Path(proj["work_dir"]), run.id, run.dir, REGISTRY)
        except (OSError, ValueError) as exc:
            logger.warning("boxmodel: cache status failed: %s", exc)
            return None

    @reactive.calc
    def status():
        status_tick.get()
        return _status_now()

    @reactive.effect
    def _poll():
        """Poller-owned trigger: re-arm only while a build is actually live.

        Reads ``poll_kick`` (bumped by the build/cancel handlers) so a fresh
        build starts it; writes ``status_tick`` and ``cache_generation``,
        neither of which it reads, so refreshing the UI cannot refresh the
        poller. Once no build is queued or building, it publishes the
        terminal state once and stops -- no timer keeps running on an idle
        page.

        The two writes are deliberately not the same signal. ``status_tick``
        fires on every 2 s tick, because the badge shows live
        records/expected progress. ``cache_generation`` fires only when the
        state crosses into or out of a terminal state -- i.e. only when the
        cache on disk can actually have changed -- because everything
        expensive (re-reading the parquet, re-opening the polygons with
        fiona, rebuilding the map layers) hangs off it.
        """
        poll_kick.get()
        current = _status_now()
        state = current.state if current is not None else None
        previous = last["state"]
        changed = previous != state
        last["state"] = state
        live = state in _LIVE_STATES
        if changed:
            _bump_status()
            # A terminal state was reached, or one was left: the published
            # cache may be new (or gone). This is the ONLY path that
            # invalidates the cached run and everything derived from it.
            if state in _TERMINAL_STATES or previous in _TERMINAL_STATES:
                _bump_cache_generation()
        if not live:
            return
        # Tick the badge every poll, not only on a state change: the
        # records/expected numbers move while the state stays "building".
        if not changed:
            _bump_status()
        reactive.invalidate_later(POLL_SECONDS)

    @render.ui
    def cache_state():
        current = status()
        if current is None:
            return ui.tags.span("no run selected", class_="text-muted")
        text = current.state
        progress = current.progress or {}
        if current.state in _LIVE_STATES and progress:
            text = f"{text} {progress.get('records', 0)}/{progress.get('expected', '?')}"
        return ui.tags.span(
            text,
            class_=f"badge bg-{_STATE_BADGE.get(current.state, 'secondary')}",
            # CacheStatus.message carries the failed build child's own
            # error text, which can name the absolute run directory.
            title=_text(current.message or ""),
        )

    # --- build / cancel (writes: gated inside the handler) -----------------

    @reactive.effect
    @reactive.event(input.build)
    async def _build():
        proj = _project()
        run = _run_entry()
        usr = _user()
        if proj is None or run is None:
            ui.notification_show("Select a run first.", type="warning", duration=5)
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6)
            return
        try:
            await start_build(
                REGISTRY,
                project=proj,
                run_id=run.id,
                run_dir=run.dir,
                user=usr,
                config=_bounded_timeout_config(config),
            )
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            ui.notification_show(_err(exc), type="error", duration=8)
            return
        ui.notification_show(f"Building cache for {run.label}", type="message", duration=4)
        _kick_poller()

    @reactive.effect
    @reactive.event(input.cancel)
    async def _cancel():
        proj = _project()
        run = _run_entry()
        usr = _user()
        if proj is None or run is None:
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6)
            return
        try:
            cancelled = await cancel_build(
                REGISTRY, (int(proj["id"]), run.id), project=proj, user=usr
            )
        except (PermissionError, ValueError, RuntimeError, OSError) as exc:
            ui.notification_show(_err(exc), type="error", duration=8)
            return
        ui.notification_show(
            "Build cancelled" if cancelled else "No build to cancel", type="message", duration=4
        )
        _kick_poller()

    # --- cached run -------------------------------------------------------

    @reactive.calc
    def cached_result() -> tuple:
        """The loaded cache, and a page message if it could not be read.

        Depends on ``cache_generation`` and NOT on ``status_tick``: this is
        the head of the expensive chain (parquet read -> polygons -> layers
        -> series -> skill), so it must not re-run on the poller's 2 s badge
        tick. ``_status_now()`` is the non-reactive status probe for the same
        reason.
        """
        cache_generation.get()
        proj = _project()
        run = _run_entry()
        current = _status_now()
        state = current.state if current is not None else None
        if proj is None or run is None:
            last["good"] = None
            return None, None
        if state in _LIVE_STATES:
            # A rebuild is running. cache_status() reports the registry
            # handle before the published cache, so the state is "building"
            # even though last build's parquet is still on disk and still
            # valid -- keep showing it rather than blanking map, series and
            # skill table for the whole rebuild. The badge still says
            # building, with progress. Only ever the run that is actually
            # selected: see _pick_live_fallback.
            return _pick_live_fallback(last, proj["id"], run.id), None
        if state not in ("ready", "stale"):
            last["good"] = None
            return None, None
        try:
            cached_run = load_cache(cache_dir_for(Path(proj["work_dir"]), run.id), run.id)
            # Validate here, inside the try, what every consumer downstream
            # assumes: cache_status() reports "ready" for any meta.json that
            # merely parses as JSON, so a hand-edited or foreign cache dir can
            # reach this point without a period or a box column. Touching both
            # now turns that into this page message instead of a KeyError
            # raised later from inside an effect (which kills the session) or
            # from inside a render.
            _cache_period(cached_run)
            if "box" not in cached_run.state_daily.columns:
                raise KeyError("state_daily has no 'box' column")
            _remember_good(last, proj["id"], run.id, cached_run)
            return cached_run, None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("boxmodel: cache could not be loaded: %s", exc)
            last["good"] = None
            return None, f"Cache: {_err(exc)}"

    def cached():
        return cached_result()[0]

    @reactive.effect
    def _fill_period_and_boxes():
        cached_run = cached()
        if cached_run is None:
            return
        start, end = _cache_period(cached_run)
        if (start, end) != last["period"]:
            last["period"] = (start, end)
            ui.update_date_range("period", start=start, end=end, min=start, max=end)
        boxes = {
            str(b): f"box {b}"
            for b in sorted(int(b) for b in cached_run.state_daily["box"].unique())
        }
        if boxes != last["boxes"]:
            last["boxes"] = boxes
            ui.update_select("box", choices=boxes, selected=next(iter(boxes), None))

    def _period():
        """The selected period, clamped to what the cache actually covers.

        ``input_date_range`` starts on today/today, so before
        ``update_date_range`` lands the raw input would select nothing at
        all; an out-of-range pick would do the same.
        """
        cached_run = cached()
        if cached_run is None:
            return None
        low, high = _cache_period(cached_run)
        chosen = input.period()
        if chosen and chosen[0] is not None and chosen[1] is not None:
            start, end = max(low, chosen[0]), min(high, chosen[1])
            if start <= end:
                return start, end
        return low, high

    # --- observations and polygons ---------------------------------------

    @reactive.calc
    def observations_result() -> tuple:
        manifest_obj = manifest()
        if manifest_obj is None or not manifest_obj.observations or not manifest_obj.sites:
            return None, None, None
        try:
            obs, report = load_observations(manifest_obj.observations)
            sites = load_sites(manifest_obj.sites)
        except (ObservationError, OSError, ValueError) as exc:
            logger.warning("boxmodel: observations could not be loaded: %s", exc)
            return None, None, f"Observations: {_err(exc)}"
        if report.get("dropped_nonfinite") or report.get("dropped_level_le0"):
            logger.info("boxmodel observations report: %s", report)
        return obs, sites, None

    def observations():
        obs, sites, _error = observations_result()
        return obs, sites

    @reactive.calc
    def polygons_result() -> tuple:
        manifest_obj = manifest()
        if manifest_obj is None:
            return {}, None
        cached_run = cached()
        try:
            # Inside the try: meta["boxes"] comes off disk, so a foreign or
            # hand-edited cache can hand us entries without a "box" key.
            expected = None
            if cached_run is not None:
                expected = {int(b["box"]) for b in cached_run.meta.get("boxes", [])} or None
            if manifest_obj.polygons is not None:
                return (
                    load_box_polygons(
                        manifest_obj.polygons,
                        manifest_obj.polygons_layer,
                        manifest_obj.id_field,
                        expected_boxes=expected,
                    ),
                    None,
                )
            if cached_run is not None and cached_run.meta.get("element_box"):
                # Hand the dissolve the EPSG the grid map itself would use:
                # a geographic grid needs none, a projected one must not be
                # silently treated as lon/lat.
                grd = grd_file.get()
                epsg = None if (grd is None or _is_geographic(grd)) else _detect_projected_crs(grd)
                return (
                    dissolve_boxes_from_grid(
                        manifest_obj.grd, cached_run.meta["element_box"], epsg=epsg
                    ),
                    None,
                )
        except (PolygonError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("boxmodel: box polygons unavailable: %s", exc)
            return {}, f"Box polygons: {_err(exc)}"
        # Neither source of outlines exists: without this the map renders
        # blank and says nothing about why (Review Important 6). The message
        # is fixed text -- no path, nothing from the manifest -- so it needs
        # no sanitising.
        return {}, _no_polygons_message(manifest_obj, cached_run)

    def polygons():
        return polygons_result()[0]

    # --- page messages ----------------------------------------------------

    @render.ui
    def manifest_error():
        """Every page-level message in one place; all text via ui.tags."""
        _manifest_obj, error, notice = manifest_result()
        blocks = []
        if error:
            blocks.append(
                ui.div(
                    ui.tags.strong("Box model: "),
                    ui.tags.span(error),
                    class_="alert alert-warning",
                )
            )
        for message in (
            grd_error.get(),
            observations_result()[2],
            polygons_result()[1],
            cached_result()[1],
        ):
            if message:
                blocks.append(ui.div(ui.tags.span(message), class_="alert alert-warning"))
        if notice:
            blocks.append(ui.div(ui.tags.span(notice), class_="alert alert-info"))
        return ui.div(*blocks) if blocks else None

    # --- map --------------------------------------------------------------

    @render.ui
    def day_slider():
        cached_run = cached()
        period = _period()
        if cached_run is None or period is None or input.map_mode() != "day":
            return None
        return ui.input_slider(
            "day",
            "Day",
            min=period[0],
            max=period[1],
            value=period[0],
            step=timedelta(days=1),
            width="100%",
        )

    @reactive.calc
    def box_values() -> tuple:
        cached_run = cached()
        period = _period()
        column = input.variable()
        if cached_run is None or period is None or column not in VARIABLES:
            return None, ""
        state_daily = cached_run.state_daily
        mode = input.map_mode()
        if mode == "day":
            day = input.day() if "day" in input else period[0]
            day = min(max(day, period[0]), period[1])
            selection = state_daily[state_daily["date"] == pd.Timestamp(day)]
            values = dict(
                zip(selection["box"].astype(int), selection[column].astype(float), strict=True)
            )
            return values, f"{VARIABLES[column]} on {day}"
        window = state_daily[
            (state_daily["date"] >= pd.Timestamp(period[0]))
            & (state_daily["date"] <= pd.Timestamp(period[1]))
        ]
        if mode == "mean":
            grouped = window.groupby("box")[column].mean()
            return {int(k): float(v) for k, v in grouped.items()}, f"mean {VARIABLES[column]}"
        obs, sites = observations()
        if obs is None or sites is None:
            return {}, "bias (no observations)"
        try:
            table = compute_skill_table({cached_run.run_id: cached_run}, obs, sites, *period)
        except (ValueError, KeyError) as exc:
            logger.warning("boxmodel: skill table failed: %s", exc)
            return {}, "bias (unavailable)"
        variable = COLUMN_TO_VARIABLE[column]
        table = table[table["variable"] == variable]
        values = {int(b): float(v) for b, v in zip(table["box"], table["bias"], strict=True)}
        label = f"bias of {VARIABLES[column]}"
        if variable == "level":
            label += " (anomaly: ~0 by construction)"
        return values, label

    @reactive.calc
    def posts() -> list[dict]:
        _obs, sites = observations()
        values, _label = box_values()
        if sites is None:
            return []
        out = []
        for _, site in sites.iterrows():
            if not (pd.notna(site["lat"]) and pd.notna(site["lon"])):
                continue
            box = site["box"]
            value = values.get(int(box)) if (values and pd.notna(box)) else None
            out.append(
                {
                    # Passed through raw on purpose. This ends up in a
                    # deck.gl tooltip rendered as innerHTML, and sites.csv is
                    # user-supplied -- but the escaping belongs to the code
                    # that builds the HTML (``build_box_layers``), which does
                    # escape it. Escaping here too would double-escape, so a
                    # site legitimately named "Smith & Co" would render as
                    # "Smith &amp; Co".
                    "site": str(site["site"]),
                    "lon": float(site["lon"]),
                    "lat": float(site["lat"]),
                    "value": value,
                }
            )
        return out

    @reactive.effect
    def _layers():
        """Rebuild the box layers. Writes ``extra_layers``/``legend_bins`` and
        reads neither, so pushing new layers can never re-trigger this effect
        (``grid_map_server`` only reads them).

        The upstream calls are inside the ``try`` as well: an exception
        escaping a ``reactive.effect`` ends the session, so any failure here
        has to degrade to empty layers plus a log line.
        """
        try:
            polys = polygons()
            values, label = box_values()
            layers, bins = build_box_layers(
                polys,
                values if polys else None,
                label=label,
                posts=posts(),
                selected=selected_box.get(),
            )
        except Exception as exc:  # noqa: BLE001 - a layer failure must not kill the session
            logger.warning("boxmodel: box layers could not be built: %s", exc, exc_info=True)
            layers, bins = [], []
        extra_layers.set(layers)
        legend_bins.set(bins)

    @render.ui
    def map_legend():
        bins = legend_bins.get()
        if not bins:
            return None
        rows = [
            ui.tags.div(
                ui.tags.span(
                    style=(
                        "display:inline-block;width:14px;height:14px;"
                        f"background:rgb({r},{g},{b});margin-right:6px"
                    )
                ),
                ui.tags.span(f"{low:.3g} – {high:.3g}"),
            )
            for (low, high, (r, g, b)) in bins
        ]
        return ui.tags.div(ui.tags.strong("Legend"), *rows, class_="small")

    def _on_box(box: int) -> None:
        """Box click from the map.

        ``update_select`` is given this page's ``session`` explicitly: this
        callback runs inside the grid map module's own session scope, so the
        default would resolve the id against ``boxmodel-boxmap-`` instead of
        ``boxmodel-``.
        """
        if selected_box.get() != box:
            selected_box.set(box)
        ui.update_select("box", selected=str(box), session=session)

    grid_map_server("boxmap", grd_file, extra_layers=extra_layers, on_box_click=_on_box)

    # --- time series ------------------------------------------------------

    @reactive.calc
    def series():
        cached_run = cached()
        period = _period()
        column = input.variable()
        selected = input.box()
        if cached_run is None or period is None or not selected or column not in VARIABLES:
            return None
        try:
            box = int(selected)
        except (TypeError, ValueError):
            return None
        state_daily = cached_run.state_daily
        model = model_series(cached_run, box, column, *period)
        low = (
            model_series(cached_run, box, f"{column}_min", *period)
            if f"{column}_min" in state_daily
            else None
        )
        high = (
            model_series(cached_run, box, f"{column}_max", *period)
            if f"{column}_max" in state_daily
            else None
        )
        obs, sites = observations()
        observed = None
        if obs is not None and sites is not None:
            mapped = sites.dropna(subset=["box"])
            names = mapped[mapped["box"].astype("int64") == box]["site"].tolist()
            rows = obs[obs["site"].isin(names) & (obs["variable"] == COLUMN_TO_VARIABLE[column])]
            rows = rows[
                (rows["date"] >= pd.Timestamp(period[0]))
                & (rows["date"] <= pd.Timestamp(period[1]))
            ]
            if len(rows):
                observed = pd.Series(
                    rows["value"].to_numpy(), index=pd.Index(rows["date"])
                ).sort_index()
        return {
            "box": box,
            # The VALIDATED variable key (column in VARIABLES), which is what
            # the download name is built from -- never the raw input.
            "variable": column,
            "model": model,
            "low": low,
            "high": high,
            "obs": observed,
            "label": VARIABLES[column],
        }

    @render_widget
    def ts_plot():
        figure = go.Figure()
        data = series()
        if data is None:
            figure.add_annotation(
                text="Select a run with a ready cache",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            figure.update_layout(height=420)
            return figure
        if data["low"] is not None and data["high"] is not None:
            figure.add_trace(
                go.Scatter(
                    x=data["high"].index,
                    y=data["high"].values,
                    line={"width": 0},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            figure.add_trace(
                go.Scatter(
                    x=data["low"].index,
                    y=data["low"].values,
                    fill="tonexty",
                    line={"width": 0},
                    name="daily min–max",
                    opacity=0.3,
                )
            )
        figure.add_trace(
            go.Scatter(
                x=data["model"].index,
                y=data["model"].values,
                name=f"model box {data['box']}",
                mode="lines",
            )
        )
        if data["obs"] is not None:
            figure.add_trace(
                go.Scatter(
                    x=data["obs"].index,
                    y=data["obs"].values,
                    name="observed",
                    mode="markers",
                    marker={"size": 5},
                )
            )
        figure.update_layout(
            height=420,
            yaxis_title=data["label"],
            margin={"l": 40, "r": 20, "t": 30, "b": 40},
        )
        return figure

    @render.ui
    def skill_table():
        cached_run = cached()
        period = _period()
        obs, sites = observations()
        if cached_run is None or period is None or obs is None or sites is None:
            return ui.tags.p("No observations configured for this project.", class_="text-muted")
        try:
            table = compute_skill_table({cached_run.run_id: cached_run}, obs, sites, *period)
        except (ValueError, KeyError) as exc:
            logger.warning("boxmodel: skill table failed: %s", exc)
            return ui.tags.p(f"Skill table: {_err(exc)}", class_="text-muted")
        if table.empty:
            return ui.tags.p(
                "No target has 30 or more common days in this period.", class_="text-muted"
            )
        head = ui.tags.tr(
            *[
                ui.tags.th(c)
                for c in (
                    "site",
                    "variable",
                    "box",
                    "n",
                    "bias",
                    "RMSE",
                    "r",
                    "R²",
                    "sd_mod/sd_obs",
                )
            ]
        )
        body = [
            ui.tags.tr(
                ui.tags.td(str(row.site)),
                ui.tags.td(str(row.variable)),
                ui.tags.td(str(row.box)),
                ui.tags.td(str(row.n)),
                ui.tags.td(_bias_cell(row.variable, row.bias)),
                ui.tags.td(_fmt(row.rmse)),
                ui.tags.td(_fmt(row.r, 2)),
                ui.tags.td(_fmt(row.r2, 2)),
                ui.tags.td(_fmt(row.sd_ratio, 2)),
            )
            for row in table.itertuples()
        ]
        return ui.tags.div(
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "Judge amplitude by sd_mod/sd_obs (1.00 is right) and phase by r; R² is shown "
                "but is not the headline. Level skill is computed on anomalies, so a level "
                "row has no meaningful bias (—).",
                class_="text-muted small",
            ),
        )

    @reactive.calc
    def all_run_states() -> dict:
        """``{run_id: CachedRun}`` (state_daily only) for every manifest run
        whose cache is ready/stale -- the multi-run skill comparison input.

        Depends on ``cache_generation`` (so a finished rebuild refreshes it)
        but reads only ``state_daily``, so loading every run stays cheap.
        """
        cache_generation.get()
        manifest_obj = manifest()
        proj = _project()
        if manifest_obj is None or proj is None:
            return {}
        work_dir = Path(proj["work_dir"])
        states: dict = {}
        for run in manifest_obj.runs:
            try:
                st = cache_status(work_dir, run.id, run.dir, REGISTRY)
            except (ValueError, OSError):
                continue
            if st.state not in ("ready", "stale"):
                continue
            try:
                states[run.id] = load_cache_state(cache_dir_for(work_dir, run.id), run.id)
            except (OSError, ValueError, KeyError) as exc:
                logger.warning("boxmodel: run %s state cache unreadable: %s", run.id, exc)
        return states

    @render.ui
    def run_comparison_table():
        manifest_obj = manifest()
        obs, sites = observations()
        states = all_run_states()
        if manifest_obj is None:
            return ui.tags.p("Open a project first.", class_="text-muted")
        if obs is None or sites is None:
            return ui.tags.p("No observations configured for this project.", class_="text-muted")
        if not states:
            return ui.tags.p("No ready run caches to compare yet.", class_="text-muted")
        # Widest span across runs; skill_table intersects the shared days.
        starts = [r.state_daily["date"].min() for r in states.values()]
        ends = [r.state_daily["date"].max() for r in states.values()]
        try:
            table = compute_skill_table(states, obs, sites, min(starts), max(ends))
        except (ValueError, KeyError) as exc:
            logger.warning("boxmodel: run-comparison skill failed: %s", exc)
            return ui.tags.p(f"Run comparison: {_err(exc)}", class_="text-muted")
        if table.empty:
            return ui.tags.p(
                "No target has enough common days across the runs.", class_="text-muted"
            )
        labels = {run.id: run.label for run in manifest_obj.runs}
        table = table.sort_values(["site", "variable", "run"])
        head = ui.tags.tr(
            *[
                ui.tags.th(c)
                for c in (
                    "run",
                    "site",
                    "variable",
                    "box",
                    "n",
                    "bias",
                    "RMSE",
                    "r",
                    "R²",
                    "sd_mod/sd_obs",
                )
            ]
        )
        body = [
            ui.tags.tr(
                ui.tags.td(_text(labels.get(row.run, row.run))),
                ui.tags.td(str(row.site)),
                ui.tags.td(str(row.variable)),
                ui.tags.td(str(row.box)),
                ui.tags.td(str(row.n)),
                ui.tags.td(_bias_cell(row.variable, row.bias)),
                ui.tags.td(_fmt(row.rmse)),
                ui.tags.td(_fmt(row.r, 2)),
                ui.tags.td(_fmt(row.r2, 2)),
                ui.tags.td(_fmt(row.sd_ratio, 2)),
            )
            for row in table.itertuples()
        ]
        return ui.tags.div(
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "All runs are compared on the days they all produced, so the window is the "
                "runs' overlap. Aim for lower RMSE, sd_mod/sd_obs near 1.00, and higher r.",
                class_="text-muted small",
            ),
        )

    @render.ui
    def band_ratios():
        """Band amplitude ratios beside the skill table (spec sec7).

        Depends on the cache through ``cached()`` -- i.e. on
        ``cache_generation`` -- and never on ``status_tick``: an FFT per level
        target must not re-run on the poller's 2 s badge tick.
        """
        cached_run = cached()
        period = _period()
        obs, sites = observations()
        if cached_run is None or period is None or obs is None or sites is None:
            return None
        try:
            rows = _band_ratio_rows(cached_run, obs, sites, *period)
        except (ValueError, KeyError, TypeError) as exc:
            logger.warning("boxmodel: band ratios failed: %s", exc)
            return ui.tags.p(f"Band amplitude: {_err(exc)}", class_="text-muted small")
        if not rows:
            return None
        head = ui.tags.tr(*[ui.tags.th(c) for c in ("site", *BAND_COLUMNS)])

        def _cells(ratios):
            """One row's band cells -- or a single spanning cell saying why
            there are none (the 120-gap-free-day rule)."""
            if not ratios:
                return [ui.tags.td(BAND_NEEDS_DAYS, colspan=str(len(BAND_COLUMNS)))]
            return [ui.tags.td(_fmt(ratios.get(column), 2)) for column in BAND_COLUMNS]

        if all(row["ratios"] is None for row in rows):
            # Nothing to compare anywhere: say it once rather than repeating
            # the same explanation on every site row.
            body = [ui.tags.tr(ui.tags.td("—"), *_cells(None))]
        else:
            body = [ui.tags.tr(ui.tags.td(row["site"]), *_cells(row["ratios"])) for row in rows]
        return ui.tags.div(
            ui.tags.strong("Band amplitude (model / observed), water level"),
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
            ui.tags.p(
                "1.00 means the model reproduces that period band's amplitude; matching the "
                "total variance can still hide compensating errors between bands. Needs at "
                "least 120 gap-free common days.",
                class_="text-muted small",
            ),
            class_="mt-3",
        )

    @_render_download(filename=lambda: _series_filename(series()))
    def download_csv():
        data = series()
        if data is None:
            yield ""
            return
        frame = pd.DataFrame({"date": data["model"].index, "model": data["model"].values})
        if data["obs"] is not None:
            frame = frame.merge(
                pd.DataFrame({"date": data["obs"].index, "observed": data["obs"].values}),
                on="date",
                how="left",
            )
        buffer = io.StringIO()
        frame.to_csv(buffer, index=False)
        yield buffer.getvalue()

    return {"selected_box": selected_box}
