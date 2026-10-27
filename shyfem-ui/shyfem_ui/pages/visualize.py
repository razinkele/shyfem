"""Visualization page - interactive plots with Plotly.

Provides:
- Grid visualization: mesh, depth contour, boundaries, element quality
- Time series: line, scatter, area plots with multi-variable support
- SHYFEM results (.shy, converted once and cached, or SHYFEM NetCDF): the
  variable on the mesh map with a time slider, playback, legend and optional
  current arrows (``components/results_map.py``)
- Variable statistics, configurable colormaps, side-by-side comparison
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shiny import module, reactive, render, ui
from shiny.types import SilentException
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.grid_map import build_mesh_figure
from shyfem_ui.components.results_map import (
    results_map_controls_ui,
    results_map_server,
    results_map_ui,
)
from shyfem_ui.components.timeseries import timeseries_server, timeseries_ui
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.boxmodel_cache import cache_dir_for, load_cache_state
from shyfem_ui.services.boxmodel_manifest import ManifestError, load_manifest
from shyfem_ui.services.boxmodel_skill import (
    VARIABLE_COLUMNS,
    compute_metrics,
    load_observations,
    load_sites,
    model_series,
)
from shyfem_ui.services.parser_grd import GrdFile, GrdParser
from shyfem_ui.services.project_files import list_project_files
from shyfem_ui.services.results_cache import netcdf_for
from shyfem_ui.services.results_data import open_results
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

logger = logging.getLogger(__name__)

# File extensions each Data Type can plot -> drives the "Project files" picker.
# Grid is .grd only: .bas is a compiled binary basin file with no Python reader,
# so it parses to an empty grid rather than plotting (load the .grd instead).
_DATA_TYPE_EXTS: dict[str, tuple[str, ...]] = {
    "grid": (".grd",),
    "timeseries": (".ts", ".txt", ".csv"),
    # SHYFEM results: a .shy is converted to NetCDF once (cached); a .nc is read as is
    "netcdf": (".shy", ".nc"),
}
# Cap the picker so a large project can't build an unwieldy dropdown.
_MAX_PROJECT_FILES = 500


def _project_file_choices(root: Path, data_type: str) -> dict[str, str]:
    """Files under ``root`` the given Data Type can plot, as select choices.

    Returns ``{rel_path: rel_path}`` with a leading empty placeholder, or just
    the placeholder when nothing matches. Path confinement is the caller's
    job; the load handler re-validates on Load.
    """
    choices: dict[str, str] = {"": "— select a file —"}
    for rel in list_project_files(root, _DATA_TYPE_EXTS.get(data_type, ()), _MAX_PROJECT_FILES):
        choices[rel] = rel
    return choices


# Plotly modebar config — enables SVG export, better filenames, no logo
PLOTLY_CONFIG = {
    "displaylogo": False,
    "toImageButtonOptions": {
        "format": "svg",
        "filename": "shyfem_plot",
        "scale": 1,
    },
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}


def _with_export_config(fig: go.Figure, filename: str = "shyfem_plot") -> go.Figure:
    """Apply standard export config to a Plotly figure."""
    fig.update_layout(
        modebar=dict(
            orientation="v",
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    return fig


def _apply_equal_aspect(fig: go.Figure, enabled: bool) -> go.Figure:
    """Lock 1:1 x/y scaling on a spatial figure so geographic maps aren't
    stretched. No-op when disabled. Only call on map-like plots (the mesh) —
    not timeseries."""
    if enabled:
        fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


COLORMAPS = {
    "Viridis": "Viridis",
    "Plasma": "Plasma",
    "Inferno": "Inferno",
    "Magma": "Magma",
    "Cividis": "Cividis",
    "RdBu": "Red-Blue",
    "RdBu_r": "Red-Blue (rev)",
    "Jet": "Jet",
    "Turbo": "Turbo",
}


@module.ui
def visualize_ui() -> ui.Tag:
    """Visualization page UI."""
    return ui.div(
        ui.h3("Visualization"),
        ui.p("Create interactive plots from SHYFEM results and grid files.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # Data source
                ui.h5("Data Source"),
                ui.input_select(
                    "data_type",
                    "Data Type",
                    choices={
                        "grid": "Grid File (.grd)",
                        "timeseries": "Time Series (.ts/.txt/.csv)",
                        "netcdf": "SHYFEM results (.shy/.nc)",
                    },
                ),
                ui.output_ui("project_files_picker"),
                ui.input_action_button(
                    "load_data_btn",
                    "Load Data",
                    class_="btn-outline-primary btn-sm w-100 mb-3",
                ),
                ui.hr(),
                ui.panel_conditional(
                    "input.data_type !== 'netcdf'",
                    # Plot type (dynamic based on data type)
                    ui.h5("Plot Type"),
                    ui.output_ui("plot_type_select"),
                    ui.hr(),
                    # Plot options
                    ui.h5("Options"),
                    ui.input_select(
                        "colormap",
                        "Colormap",
                        choices=COLORMAPS,
                    ),
                    ui.input_checkbox("show_grid_lines", "Show Grid Lines", value=False),
                    ui.input_checkbox("equal_aspect", "Equal Aspect Ratio", value=True),
                    ui.hr(),
                ),
                # SHYFEM results: the map's controls
                ui.panel_conditional(
                    "input.data_type === 'netcdf'",
                    ui.h5("Results"),
                    results_map_controls_ui("results_map"),
                    ui.hr(),
                ),
                # Comparison controls
                ui.h5("Compare"),
                ui.output_ui("compare_files_picker"),
                ui.input_action_button(
                    "load_compare_btn",
                    "Load for Comparison",
                    class_="btn-outline-secondary btn-sm w-100",
                ),
                width=300,
            ),
            # Main content
            ui.navset_card_tab(
                ui.nav_panel(
                    "Plot",
                    ui.panel_conditional(
                        "input.data_type === 'netcdf'",
                        results_map_ui("results_map"),
                    ),
                    ui.panel_conditional(
                        "input.data_type !== 'netcdf'",
                        output_widget("main_plot"),
                    ),
                ),
                ui.nav_panel(
                    "Data Info",
                    ui.output_ui("data_info"),
                ),
                ui.nav_panel(
                    "Time Series",
                    timeseries_ui("ts_viewer"),
                ),
                ui.nav_panel(
                    "Vertical Profile",
                    output_widget("profile_plot"),
                ),
                ui.nav_panel(
                    "Statistics",
                    ui.output_ui("var_statistics"),
                ),
                ui.nav_panel(
                    "Comparison",
                    output_widget("compare_plot"),
                ),
                ui.nav_panel(
                    "Model vs Measured",
                    ui.output_ui("mvm_controls"),
                    output_widget("mvm_plot"),
                    ui.output_ui("mvm_stats"),
                ),
            ),
        ),
    )


@module.server
def visualize_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
    tutorial_context=None,
    current_user=None,
    project_files_rev=None,
) -> None:
    """Visualization page server logic."""

    # Files in the active project the current Data Type can plot -> dropdowns
    # that drive the primary and comparison loads (no free-text path box).
    def _picker_ui(select_id: str, label: str):
        if active_project is None:
            return None
        proj = active_project.get()
        if proj is None:
            return None
        if not _DATA_TYPE_EXTS.get(input.data_type()):
            return None
        usr = current_user() if current_user is not None else None
        if project_files_rev is not None:
            project_files_rev.get()  # relist when a run finishes
        try:
            root = Path(config.confine_path(proj["work_dir"], usr, must_exist=True))
        except (ValueError, OSError):
            return None
        choices = _project_file_choices(root, input.data_type())
        if len(choices) == 1:
            return ui.p("No matching files in this project.", class_="text-muted small mb-2")
        # A relist must not drop the user's pick.
        with reactive.isolate():
            try:
                current = getattr(input, select_id)()
            except Exception:
                current = ""
        return ui.input_select(
            select_id, label, choices=choices, selected=current if current in choices else ""
        )

    def _resolve_selection(rel: str) -> Path | None:
        """Confined absolute path for a picker selection, or None (+notify)."""
        if not rel:
            return None
        proj = active_project.get() if active_project is not None else None
        if proj is None:
            ui.notification_show("Open a project first", type="warning")
            return None
        usr = current_user() if current_user is not None else None
        try:
            return config.confine_path(str(Path(proj["work_dir"]) / rel), usr, must_exist=True)
        except (ValueError, FileNotFoundError) as exc:
            ui.notification_show(str(exc), type="error", duration=6)
            return None

    @render.ui
    def project_files_picker():
        return _picker_ui("project_file", "Project files")

    @render.ui
    def compare_files_picker():
        return _picker_ui("compare_file", "Compare file (optional)")

    # Auto-fill from tutorial navigation
    @reactive.effect
    def _on_tutorial_context():
        if tutorial_context is None:
            return
        ctx = tutorial_context.get()
        if ctx is None or ctx.get("target_tab") != "Visualize":
            return
        # No path box any more; landing on the tab is enough — the user picks
        # a file from the project dropdown.
        tutorial_context.set(None)

    # State
    loaded_data = reactive.value(None)
    data_type = reactive.value(None)
    data_info_val = reactive.value({})
    compare_data = reactive.value(None)
    compare_type = reactive.value(None)
    # Time series reactive for the timeseries component
    ts_data_val = reactive.value(None)

    # Wire up the timeseries component
    timeseries_server(
        "ts_viewer",
        ts_data_val,
        config=config,
        current_user=current_user,
        active_project=active_project,
    )

    # --- SHYFEM results (the "netcdf" Data Type) ---------------------------
    # One open file at a time, shown by the results map. A .shy is converted
    # to NetCDF in an extended task (off the reactive lock), cached in the
    # viewer's home; a .nc is read as is.
    wrapper = ShyfemWrapper(config.shyfem_dir)
    results_val = reactive.value(None)
    results_info = results_map_server("results_map", results=results_val)
    # Plain holders (also read by on_ended): (resolved path, st_size,
    # st_mtime_ns) of the file the user picked. The ResultsFile's own stamp is
    # the cached .nc's, which the cache's LRU touch changes.
    open_source: list = [None]  # what is open
    pending_source: list = [None]  # what the conversion in flight is for
    load_label: list = ["Load Data"]

    def _set_value(rv, value) -> None:
        """Compare before set (``Value.set`` dedups by identity only)."""
        with reactive.isolate():
            if rv.get() == value:
                return
        rv.set(value)

    def _source_stamp(path: Path) -> tuple:
        real = Path(path).resolve()
        st = real.stat()
        return (real, st.st_size, st.st_mtime_ns)

    def _close_after_flush(rf) -> None:
        """Close ``rf`` once this flush is done (the map has dropped it by then)."""
        session.on_flushed(rf.close, once=True)

    def _clear_results() -> None:
        """No results open: cancel any conversion, forget both stamps, close."""
        _convert.cancel()
        pending_source[0] = None
        open_source[0] = None
        with reactive.isolate():
            prev = results_val.get()
            was_results = data_type.get() == "netcdf"
        if prev is not None:
            results_val.set(None)
            _close_after_flush(prev)
        if was_results:
            data_type.set(None)
            data_info_val.set({})

    def _results_failed(message: str) -> None:
        _clear_results()
        ui.notification_show(message, type="error", duration=8)

    def _load_failed(message: str) -> None:
        """A Load failed before anything changed: keep what is open, if anything."""
        _convert.cancel()
        pending_source[0] = None
        with reactive.isolate():
            is_open = results_val.get() is not None
        if not is_open or open_source[0] is None:
            _results_failed(message)
            return
        ui.notification_show(
            f"{message} (still showing {open_source[0][0].name})", type="error", duration=8
        )

    @reactive.extended_task
    async def _convert(stamp: tuple, user):
        # ``stamp`` is the picked file's (resolved path, st_size, st_mtime_ns):
        # the result is matched against the pending stamp, not the path alone
        try:
            nc = await netcdf_for(stamp[0], user, config, wrapper)
        except Exception as exc:
            raise _LoadFailed(stamp, str(exc)) from exc
        return stamp, nc

    def _start_results_load(path: Path) -> None:
        """Load (results): a no-op for what is open, else convert in the task."""
        try:
            src = _source_stamp(path)
        except OSError as exc:
            _load_failed(f"Cannot read {Path(path).name}: {exc}")
            return
        with reactive.isolate():
            is_open = results_val.get() is not None
        if is_open and src == open_source[0]:
            # the latest request wins: drop a conversion started for another file
            _convert.cancel()
            pending_source[0] = None
            ui.notification_show(f"{src[0].name} is already open", type="message", duration=3)
            return
        if src == pending_source[0]:
            return  # its conversion is already running
        usr = current_user() if current_user is not None else None
        _convert.cancel()
        pending_source[0] = src
        _convert.invoke(src, usr)

    @reactive.effect
    def _convert_done():
        try:
            try:
                stamp, nc = _convert.result()
            except SilentException:
                raise
            except Exception as exc:
                # the conversion failed; ignore it unless it is the one waited for
                src = pending_source[0]
                if src is not None and getattr(exc, "source", None) == src:
                    _load_failed(str(exc))
                return
            with reactive.isolate():
                is_results = input.data_type() == "netcdf"
                prev = results_val.get()
            src = pending_source[0]
            if not is_results or src is None or stamp != src:
                return  # stale: a newer Load, a changed file or a Data Type switch
            pending_source[0] = None
            try:
                rf = open_results(nc)
            except Exception as exc:
                logger.warning("visualize: opening results failed: %s", exc, exc_info=True)
                _load_failed(f"Could not open the results file: {exc}")
                return
            # from here on the previous file is replaced: a failure clears the map
            # the new file first, the previous one closed after (this flush)
            results_val.set(rf)
            if prev is not None and prev is not rf:
                _close_after_flush(prev)
            open_source[0] = src
            _set_value(loaded_data, None)
            _set_value(data_type, "netcdf")
            data_info_val.set(_results_data_info(rf, src[0]))
            ui.notification_show(
                f"Loaded {src[0].name}: {len(rf.times)} records", type="message", duration=4
            )
        except SilentException:
            raise
        except Exception as exc:
            logger.warning("visualize: opening results failed: %s", exc, exc_info=True)
            _results_failed(f"Could not open the results file: {exc}")

    @reactive.effect
    def _convert_status():
        try:
            label = "Converting \u2026" if _convert.status() == "running" else "Load Data"
            if label != load_label[0]:
                load_label[0] = label
                ui.update_action_button("load_data_btn", label=label)
        except SilentException:
            raise
        except Exception as exc:
            logger.warning("visualize: load button relabel failed: %s", exc)

    @reactive.effect
    @reactive.event(input.data_type)
    def _on_data_type():
        try:
            if input.data_type() != "netcdf":
                _clear_results()  # stops playback: the map tears its scene down
        except SilentException:
            raise
        except Exception as exc:
            logger.warning("visualize: clearing results failed: %s", exc)

    def _on_ended() -> None:
        _convert.cancel()
        pending_source[0] = None
        open_source[0] = None
        with reactive.isolate():
            rf = results_val.get()
        if rf is not None:
            rf.close()

    session.on_ended(_on_ended)

    # --- Model vs Measured (box-model manifest driven) --------------------

    @reactive.calc
    def _mvm_manifest():
        proj = active_project.get() if active_project is not None else None
        if proj is None:
            return None
        usr = current_user() if current_user is not None else None
        try:
            project_dir = config.confine_path(proj["work_dir"], usr, must_exist=True)
            return load_manifest(project_dir, config, usr)
        except (ManifestError, ValueError, OSError):
            return None

    @reactive.calc
    def _mvm_runs() -> dict:
        """``{run_id: (label, CachedRun)}`` for manifest runs with a ready cache."""
        m = _mvm_manifest()
        proj = active_project.get() if active_project is not None else None
        if m is None or proj is None:
            return {}
        work_dir = Path(proj["work_dir"])
        out: dict = {}
        for run in m.runs:
            cd = cache_dir_for(work_dir, run.id)
            if (cd / "state_daily.parquet").is_file() and (cd / "meta.json").is_file():
                try:
                    out[run.id] = (run.label, load_cache_state(cd, run.id))
                except (OSError, ValueError, KeyError):
                    logger.warning("visualize mvm: cache for %s unreadable", run.id)
        return out

    @reactive.calc
    def _mvm_obs():
        m = _mvm_manifest()
        if m is None or not m.observations or not m.sites:
            return None, None
        try:
            obs, _report = load_observations(m.observations)
            sites = load_sites(m.sites)
            return obs, sites
        except Exception:
            logger.warning("visualize mvm: observations/sites could not be loaded", exc_info=True)
            return None, None

    @render.ui
    def mvm_controls():
        runs = _mvm_runs()
        obs, sites = _mvm_obs()
        if not runs:
            return ui.p(
                "This tab needs a project with a box-model manifest "
                "(boxmodel.json) and at least one ready run cache. Open such a "
                "project (e.g. Curonian 29-box), or build a run cache on the "
                "Box model page.",
                class_="text-muted",
            )
        if obs is None or sites is None:
            return ui.p(
                "The project manifest has no observations/sites configured.",
                class_="text-muted",
            )
        run_choices = {rid: lbl for rid, (lbl, _cr) in runs.items()}
        mapped = sites.dropna(subset=["box"])
        site_choices = {s: s for s in sorted(mapped["site"].astype(str).unique())}
        var_choices = {v: v.capitalize() for v in ("level", "salinity", "temperature")}
        return ui.layout_columns(
            ui.input_selectize(
                "mvm_run",
                "Runs",
                choices=run_choices,
                multiple=True,
                selected=list(run_choices),
            ),
            ui.input_select("mvm_site", "Station", choices=site_choices),
            ui.input_select("mvm_var", "Parameter", choices=var_choices),
            col_widths=(4, 4, 4),
        )

    def _mvm_data():
        """(measured series, variable, [(label, days, modelled, measured), ...])
        for the current selection of one or more runs, else None."""
        runs = _mvm_runs()
        obs, sites = _mvm_obs()
        if not runs or obs is None or sites is None:
            return None
        try:
            rids, site, var = input.mvm_run(), input.mvm_site(), input.mvm_var()
        except Exception:
            return None
        if isinstance(rids, str):
            rids = [rids]
        rids = [r for r in (rids or []) if r in runs]
        if not rids or var not in VARIABLE_COLUMNS:
            return None
        srow = sites[sites["site"].astype(str) == str(site)]
        if srow.empty or pd.isna(srow.iloc[0]["box"]):
            return None
        box = int(srow.iloc[0]["box"])
        o = (
            obs[(obs["site"].astype(str) == str(site)) & (obs["variable"] == var)]
            .set_index("date")["value"]
            .sort_index()
        )
        if o.empty:
            return None
        series = []
        for rid in rids:
            label, cr = runs[rid]
            mod = model_series(cr, box, VARIABLE_COLUMNS[var], o.index.min(), o.index.max())
            days = sorted(set(o.index) & set(mod.index))
            if not days:
                continue
            series.append(
                (
                    label,
                    days,
                    mod.reindex(days).to_numpy(dtype=float),
                    o.reindex(days).to_numpy(dtype=float),
                )
            )
        if not series:
            return None
        return o, var, series

    @render_widget
    def mvm_plot():
        data = _mvm_data()
        fig = go.Figure()
        if data is None:
            fig.add_annotation(
                text="Select one or more runs, a station and a parameter.",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=15,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig
        o, var, series = data
        is_level = var == "level"
        ylabel = "Level anomaly (m)" if is_level else var.capitalize()
        # Measured points once (anomaly for level so it overlays the models).
        meas_y = o.to_numpy(dtype=float)
        if is_level:
            meas_y = meas_y - np.nanmean(meas_y)
        fig.add_trace(
            go.Scattergl(
                x=list(o.index), y=meas_y, mode="markers", name="Measured", marker=dict(size=5)
            )
        )
        # One modelled line per selected run.
        for label, days, mod, _meas in series:
            y = mod - np.nanmean(mod) if is_level else mod
            fig.add_trace(go.Scattergl(x=days, y=y, mode="lines", name=label))
        fig.update_layout(
            height=500,
            xaxis_title="Date",
            yaxis_title=ylabel,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        return fig

    @render.ui
    def mvm_stats():
        data = _mvm_data()
        if data is None:
            return None
        _o, var, series = data

        def _f(x, d=3):
            return "—" if x is None else f"{x:.{d}f}"

        rows = []
        for label, _days, mod, meas in series:
            k = np.isfinite(meas) & np.isfinite(mod)
            if int(k.sum()) < 3:
                rows.append(ui.tags.tr(ui.tags.td(label), *[ui.tags.td("—") for _ in range(6)]))
                continue
            mt = compute_metrics(meas[k], mod[k], is_level=(var == "level"))
            bias = "—" if var == "level" else _f(mt.bias)
            rows.append(
                ui.tags.tr(
                    ui.tags.td(label),
                    ui.tags.td(str(mt.n)),
                    ui.tags.td(bias),
                    ui.tags.td(_f(mt.rmse)),
                    ui.tags.td(_f(mt.r, 2)),
                    ui.tags.td(_f(mt.r2, 2)),
                    ui.tags.td(_f(mt.sd_ratio, 2)),
                )
            )
        head = ui.tags.tr(
            *[ui.tags.th(h) for h in ("run", "n", "bias", "RMSE", "r", "R²", "sd_mod/sd_obs")]
        )
        return ui.tags.div(
            ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*rows), class_="table table-sm mt-2"),
            ui.tags.p(
                "Modelled lines vs measured points over each run's common days. "
                "Level is compared as anomalies (datum-independent), so bias is "
                "not shown for level.",
                class_="text-muted small",
            ),
        )

    @render.ui
    def plot_type_select():
        dtype = input.data_type()

        if dtype == "grid":
            choices = {
                "mesh": "Mesh View",
                "depth": "Depth Contour",
                "boundaries": "Boundaries",
                "quality": "Element Quality",
            }
        elif dtype == "timeseries":
            choices = {
                "line": "Line Plot",
                "scatter": "Scatter Plot",
                "area": "Area Plot",
            }
        else:
            choices = {
                "auto": "Auto-detect",
            }

        return ui.input_select("plot_type", "Plot Type", choices=choices)

    @reactive.effect
    @reactive.event(input.load_data_btn)
    async def _load_data():
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="viewer"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        dtype = input.data_type()
        try:
            rel = input.project_file()
        except Exception:
            rel = ""
        if not rel:
            ui.notification_show("Please select a file", type="warning")
            return

        path = _resolve_selection(rel)
        if path is None:
            return

        await _do_load(path, dtype, is_compare=False)

    @reactive.effect
    @reactive.event(input.load_compare_btn)
    async def _load_compare():
        # IDOR fix: same viewer-level access gate as _load_data (was missing).
        _usr = current_user() if current_user is not None else None
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="viewer"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        try:
            rel = input.compare_file()
        except Exception:
            rel = ""
        if not rel:
            ui.notification_show("Select a comparison file", type="warning")
            return
        path = _resolve_selection(rel)
        if path is None:
            return
        dtype = input.data_type()
        await _do_load(path, dtype, is_compare=True)

    async def _do_load(path: Path, dtype: str, is_compare: bool):
        """Load data from file into primary or comparison slot."""
        try:
            if dtype == "grid":
                grd = GrdParser.parse_file(path)
                if grd.num_nodes == 0:
                    # A binary .bas (or any non-.grd) read as text parses to an
                    # empty grid; surface that instead of "Loaded grid: 0 nodes".
                    raise ValueError(
                        "No nodes found — this is not a readable .grd grid "
                        "(binary .bas files can't be plotted; load the .grd instead)."
                    )
                if is_compare:
                    compare_data.set(grd)
                    compare_type.set("grid")
                else:
                    loaded_data.set(grd)
                    data_type.set("grid")
                    stats = GrdParser.get_statistics(grd)
                    data_info_val.set(stats)
                ui.notification_show(
                    f"Loaded grid: {grd.num_nodes} nodes", type="message", duration=4
                )

            elif dtype == "timeseries":
                ts = _load_timeseries(path)
                if is_compare:
                    compare_data.set(ts)
                    compare_type.set("timeseries")
                else:
                    loaded_data.set(ts)
                    data_type.set("timeseries")
                    ts_data_val.set(ts)  # Feed to timeseries component
                    data_info_val.set(
                        {
                            "file": str(path),
                            "columns": len(ts.get("columns", [])),
                            "rows": len(ts.get("data", [])),
                        }
                    )
                ui.notification_show("Loaded time series data", type="message", duration=4)

            elif dtype == "netcdf":
                if is_compare:
                    ui.notification_show(_COMPARE_NA, type="warning", duration=5)
                    return
                _start_results_load(path)

            else:
                ui.notification_show(f"Unsupported data type: {dtype}", type="error", duration=6)

        except Exception as e:
            ui.notification_show(f"Error loading data: {e}", type="error", duration=6)

    @render_widget
    def main_plot():
        data = loaded_data.get()
        dtype = data_type.get()

        if data is None:
            fig = go.Figure()
            fig.add_annotation(
                text="Load data to generate plot",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=16,
                font_color="gray",
            )
            fig.update_layout(height=600)
            return fig

        try:
            plot_type = input.plot_type()
            colormap = input.colormap()
            show_grid = input.show_grid_lines()
            equal_aspect = input.equal_aspect()

            if dtype == "grid":
                fig = build_mesh_figure(
                    data,
                    mode=plot_type,
                    colorscale=colormap,
                    show_boundaries=True,
                    show_nodes=False,
                )
                if show_grid:
                    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)")
                    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)")
                _apply_equal_aspect(fig, equal_aspect)
                return _with_export_config(fig, "shyfem_main_plot")
            elif dtype == "timeseries":
                return _with_export_config(
                    _plotly_timeseries(data, plot_type, show_grid), "shyfem_main_plot"
                )
            else:
                fig = go.Figure()
                fig.add_annotation(
                    text="Unsupported data type",
                    xref="paper",
                    yref="paper",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                )
                return fig
        except Exception as exc:
            logger.exception("Error rendering plot")
            ui.notification_show(f"Plot error: {exc}", type="error", duration=6)
            fig = go.Figure()
            fig.add_annotation(
                text=f"Error: {exc}",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_color="red",
            )
            fig.update_layout(height=600)
            return fig

    @render.ui
    def data_info():
        info = data_info_val.get()
        if not info:
            return ui.p("No data loaded", class_="text-muted")

        rows = []
        for key, value in info.items():
            if isinstance(value, (list, dict)):
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:100] + "..."
            else:
                value_str = str(value)

            rows.append(
                ui.tags.tr(
                    ui.tags.th(key.replace("_", " ").title()),
                    ui.tags.td(value_str),
                )
            )

        return ui.tags.table(
            ui.tags.tbody(*rows),
            class_="table table-sm",
        )

    @render_widget
    def profile_plot():
        """Vertical profiles: none of the Data Types has one yet."""
        if input.data_type() == "netcdf":
            return _message_figure(_PROFILE_NA, height=500)
        return _message_figure("Vertical profiles are not available for this data type", 500)

    @render.ui
    def var_statistics():
        """Show variable statistics for loaded data."""
        if input.data_type() == "netcdf":
            return _results_statistics(results_val.get(), results_info())

        data = loaded_data.get()
        dtype = data_type.get()

        if data is None:
            return ui.p("Load data to see statistics", class_="text-muted text-center mt-3")

        if dtype == "timeseries":
            return _timeseries_statistics(data)
        elif dtype == "grid":
            stats = data_info_val.get()
            if not stats:
                return ui.p("No statistics available", class_="text-muted")
            rows = []
            for k, v in stats.items():
                rows.append(
                    ui.tags.tr(
                        ui.tags.th(str(k)),
                        ui.tags.td(str(v)[:200]),
                    )
                )
            return ui.tags.table(
                ui.tags.tbody(*rows),
                class_="table table-sm table-bordered",
            )
        return ui.p("Statistics not available for this data type", class_="text-muted")

    @render_widget
    def compare_plot():
        """Side-by-side or difference comparison."""
        if input.data_type() == "netcdf":
            return _message_figure(_COMPARE_NA)
        primary = loaded_data.get()
        secondary = compare_data.get()
        dtype = data_type.get()

        if primary is None or secondary is None:
            fig = go.Figure()
            fig.add_annotation(
                text="Load both primary and comparison files",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=14,
                font_color="gray",
            )
            fig.update_layout(height=600)
            return fig

        if dtype == "grid":
            return _with_export_config(
                _compare_grids(primary, secondary, input.colormap()), "shyfem_comparison"
            )
        elif dtype == "timeseries":
            return _with_export_config(_compare_timeseries(primary, secondary), "shyfem_comparison")
        else:
            fig = go.Figure()
            fig.add_annotation(
                text="Comparison not supported for this data type",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            fig.update_layout(height=600)
            return fig

    return {}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def _load_timeseries(path: Path) -> dict:
    """Load time series data from file."""
    from shyfem_ui.services.timeseries_loader import load_timeseries

    return load_timeseries(path)


# ---------------------------------------------------------------------------
# Time series plots
# ---------------------------------------------------------------------------


def _plotly_timeseries(data: dict, plot_type: str, show_grid: bool) -> go.Figure:
    """Create an interactive Plotly time series figure."""
    fig = go.Figure()

    df = data.get("df")
    if df is not None:
        x_vals = df.iloc[:, 0]
        for col in df.columns[1:]:
            y_vals = df[col]
            if plot_type == "line":
                fig.add_trace(
                    go.Scattergl(
                        x=x_vals,
                        y=y_vals,
                        mode="lines",
                        name=col,
                    )
                )
            elif plot_type == "scatter":
                fig.add_trace(
                    go.Scattergl(
                        x=x_vals,
                        y=y_vals,
                        mode="markers",
                        marker=dict(size=4),
                        name=col,
                    )
                )
            elif plot_type == "area":
                fig.add_trace(
                    go.Scatter(
                        x=x_vals,
                        y=y_vals,
                        fill="tozeroy",
                        mode="lines",
                        name=col,
                        opacity=0.6,
                    )
                )
    else:
        arr = np.array(data.get("data", []))
        columns = data.get("columns", [])
        if arr.size > 0:
            for i in range(1, arr.shape[1]):
                col_name = columns[i] if i < len(columns) else f"col{i}"
                if plot_type == "line":
                    fig.add_trace(
                        go.Scattergl(
                            x=arr[:, 0].tolist(),
                            y=arr[:, i].tolist(),
                            mode="lines",
                            name=col_name,
                        )
                    )
                elif plot_type == "scatter":
                    fig.add_trace(
                        go.Scattergl(
                            x=arr[:, 0].tolist(),
                            y=arr[:, i].tolist(),
                            mode="markers",
                            marker=dict(size=4),
                            name=col_name,
                        )
                    )
                elif plot_type == "area":
                    fig.add_trace(
                        go.Scatter(
                            x=arr[:, 0].tolist(),
                            y=arr[:, i].tolist(),
                            fill="tozeroy",
                            mode="lines",
                            name=col_name,
                            opacity=0.6,
                        )
                    )

    fig.update_layout(
        xaxis_title="Time",
        yaxis_title="Value",
        height=600,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )

    if show_grid:
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)")
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)")

    fig.update_xaxes(rangeslider_visible=True)
    return fig


# ---------------------------------------------------------------------------
# SHYFEM results (the "netcdf" Data Type: shown by the results map)
# ---------------------------------------------------------------------------


class _LoadFailed(Exception):
    """A results conversion failed; ``source`` is the stamp it was for."""

    def __init__(self, source: tuple, message: str):
        super().__init__(message)
        self.source = source


_PROFILE_NA = "Vertical profiles are not available for SHYFEM results yet"
_COMPARE_NA = "Comparison is not available for SHYFEM results yet"


def _message_figure(text: str, height: int = 600, color: str = "gray") -> go.Figure:
    """An empty figure carrying ``text`` as its only annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text=text,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font_size=14,
        font_color=color,
    )
    fig.update_layout(height=height)
    return fig


def _results_data_info(rf, source: Path) -> dict:
    """Data Info rows for an open results file picked as ``source``."""
    fmt = "%Y-%m-%d %H:%M"
    return {
        "file": str(source),
        "variables": list(rf.variables),
        "records": len(rf.times),
        "first_time": rf.times[0].strftime(fmt) if rf.times else "-",
        "last_time": rf.times[-1].strftime(fmt) if rf.times else "-",
        "levels": rf.n_levels,
        "nodes": len(rf.node_x),
        "elements": len(rf.faces),
    }


def _results_statistics(rf, on_screen: dict | None) -> ui.Tag:
    """The colour range of the variable on the map and the units of all."""
    if rf is None:
        return ui.p("Load a SHYFEM results file to see statistics", class_="text-muted mt-3")
    parts = []
    if on_screen is not None:
        units = on_screen.get("units") or ""
        lo, hi = on_screen.get("vmin"), on_screen.get("vmax")
        if on_screen.get("no_values"):
            rng = "no valid values"
        elif lo is None or hi is None:
            rng = "computing\u2026"
        else:
            rng = f"{lo:.4g} \u2013 {hi:.4g} {units}".strip()
        parts.append(ui.h5("On the map"))
        parts.append(ui.p(ui.strong(on_screen.get("label", "")), f": {rng}", class_="mb-3"))
    rows = [
        ui.tags.tr(ui.tags.td(name), ui.tags.td(info.label), ui.tags.td(info.units or "-"))
        for name, info in rf.variables.items()
    ]
    parts.append(ui.h5("Variables"))
    parts.append(
        ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(ui.tags.th("Variable"), ui.tags.th("Label"), ui.tags.th("Units"))
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-bordered",
        )
    )
    return ui.div(*parts)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _timeseries_statistics(data: dict) -> ui.Tag:
    """Compute and display statistics for time series columns."""
    columns = data.get("columns", [])
    df = data.get("df")
    rows_data = data.get("data", [])

    stat_rows = []
    if df is not None:
        for col in df.columns[1:]:
            vals = df[col].dropna()
            if len(vals) == 0:
                continue
            stat_rows.append(
                ui.tags.tr(
                    ui.tags.td(ui.strong(col)),
                    ui.tags.td(f"{vals.min():.4g}"),
                    ui.tags.td(f"{vals.max():.4g}"),
                    ui.tags.td(f"{vals.mean():.4g}"),
                    ui.tags.td(f"{vals.std():.4g}"),
                    ui.tags.td(f"{vals.max() - vals.min():.4g}"),
                    ui.tags.td(str(len(vals))),
                )
            )
    elif rows_data:
        arr = np.array(rows_data)
        for i in range(1, arr.shape[1]):
            col_name = columns[i] if i < len(columns) else f"col{i}"
            vals = arr[:, i]
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                continue
            stat_rows.append(
                ui.tags.tr(
                    ui.tags.td(ui.strong(col_name)),
                    ui.tags.td(f"{np.min(vals):.4g}"),
                    ui.tags.td(f"{np.max(vals):.4g}"),
                    ui.tags.td(f"{np.mean(vals):.4g}"),
                    ui.tags.td(f"{np.std(vals):.4g}"),
                    ui.tags.td(f"{np.max(vals) - np.min(vals):.4g}"),
                    ui.tags.td(str(len(vals))),
                )
            )

    if not stat_rows:
        return ui.p("No statistics available", class_="text-muted")

    return ui.div(
        ui.h5("Column Statistics"),
        ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Column"),
                    ui.tags.th("Min"),
                    ui.tags.th("Max"),
                    ui.tags.th("Mean"),
                    ui.tags.th("Std"),
                    ui.tags.th("Range"),
                    ui.tags.th("Count"),
                ),
            ),
            ui.tags.tbody(*stat_rows),
            class_="table table-sm table-bordered table-hover",
        ),
    )


# ---------------------------------------------------------------------------
# Comparison plots
# ---------------------------------------------------------------------------


def _compare_grids(grd1: GrdFile, grd2: GrdFile, colormap: str) -> go.Figure:
    """Side-by-side comparison of two grids."""
    fig = make_subplots(rows=1, cols=2, subplot_titles=("Primary", "Comparison"))

    for col, grd in enumerate([grd1, grd2], 1):
        from shyfem_ui.components.grid_map import _build_edge_arrays

        edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)
        fig.add_trace(
            go.Scattergl(
                x=edge_x,
                y=edge_y,
                mode="lines",
                line=dict(color="#4a90d9", width=0.5),
                hoverinfo="skip",
                showlegend=False,
            ),
            row=1,
            col=col,
        )
        depths = np.array(
            [grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0 for nid in node_ids]
        )
        if not np.all(depths == 0):
            fig.add_trace(
                go.Scattergl(
                    x=x.tolist(),
                    y=y.tolist(),
                    mode="markers",
                    marker=dict(
                        size=3, color=depths.tolist(), colorscale=colormap, showscale=(col == 2)
                    ),
                    hoverinfo="skip",
                    showlegend=False,
                ),
                row=1,
                col=col,
            )
        fig.update_xaxes(scaleanchor=f"y{col}" if col == 1 else "y2", scaleratio=1, row=1, col=col)

    fig.update_layout(height=600, title="Grid Comparison")
    return fig


def _compare_timeseries(ts1: dict, ts2: dict) -> go.Figure:
    """Overlay comparison of two time series datasets."""
    fig = go.Figure()

    for ts_data, prefix, dash in [(ts1, "Primary", None), (ts2, "Compare", "dash")]:
        df = ts_data.get("df")
        if df is not None:
            for col in df.columns[1:]:
                fig.add_trace(
                    go.Scattergl(
                        x=df.iloc[:, 0],
                        y=df[col],
                        mode="lines",
                        line=dict(dash=dash),
                        name=f"{prefix}: {col}",
                    )
                )
        else:
            arr = np.array(ts_data.get("data", []))
            columns = ts_data.get("columns", [])
            if arr.size > 0:
                for i in range(1, arr.shape[1]):
                    col_name = columns[i] if i < len(columns) else f"col{i}"
                    fig.add_trace(
                        go.Scattergl(
                            x=arr[:, 0].tolist(),
                            y=arr[:, i].tolist(),
                            mode="lines",
                            line=dict(dash=dash),
                            name=f"{prefix}: {col_name}",
                        )
                    )

    fig.update_layout(
        height=600,
        title="Time Series Comparison",
        xaxis_title="Time",
        yaxis_title="Value",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(rangeslider_visible=True)
    return fig
