"""Visualization page - interactive plots with Plotly.

Provides:
- Grid visualization: mesh, depth contour, boundaries, element quality
- Time series: line, scatter, area plots with multi-variable support
- NetCDF: contour, heatmap, 3D surface, vertical profiles, transect plots
- Spatial maps with node overlay, variable statistics
- Difference maps for two NetCDF datasets
- Configurable colormaps, time slider, side-by-side comparison
"""

import logging
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.grid_map import build_mesh_figure
from shyfem_ui.components.timeseries import timeseries_server, timeseries_ui
from shyfem_ui.config import Config
from shyfem_ui.services.parser_grd import GrdFile, GrdParser

logger = logging.getLogger(__name__)

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


def build_variable_table(ds) -> list[dict]:
    """Build a summary table of all variables in a NetCDF Dataset.

    Args:
        ds: xarray.Dataset

    Returns:
        List of dicts with keys: name, dims, dtype, units, long_name, min, max
    """
    rows = []
    for var_name in ds.data_vars:
        try:
            var = ds[var_name]
            values = var.values.flatten()
            valid = (
                values[~np.isnan(values)] if np.issubdtype(values.dtype, np.floating) else values
            )
            rows.append(
                {
                    "name": var_name,
                    "dims": " \u00d7 ".join(var.dims),
                    "dtype": str(var.dtype),
                    "units": str(var.attrs.get("units", "-")),
                    "long_name": str(var.attrs.get("long_name", "-")),
                    "min": float(np.min(valid)) if len(valid) > 0 else None,
                    "max": float(np.max(valid)) if len(valid) > 0 else None,
                }
            )
        except Exception:
            logger.debug("Failed to compute stats for variable %s", var_name, exc_info=True)
            continue
    return rows


def get_dim_label(ds, dim_name: str, index: int) -> str:
    """Get a human-readable label for a dimension index.

    Args:
        ds: xarray.Dataset
        dim_name: Name of the dimension
        index: Integer index into the dimension

    Returns:
        Formatted string label (timestamp, depth value, or plain index)
    """
    try:
        if dim_name not in ds.coords:
            return str(index)
        coord = ds.coords[dim_name]
        if index < 0 or index >= len(coord):
            return str(index)
        value = coord.values[index]

        # Time dimensions: format as datetime
        if np.issubdtype(coord.dtype, np.datetime64):
            import pandas as pd

            return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")

        # Numeric: show value
        if np.issubdtype(coord.dtype, np.number):
            units = coord.attrs.get("units", "")
            formatted = f"{float(value):.4g}"
            return f"{formatted} {units}".strip()

        return str(value)
    except Exception:
        return str(index)


def get_variable_attrs(ds, var_name: str) -> dict:
    """Extract key metadata attributes for a NetCDF variable.

    Args:
        ds: xarray.Dataset
        var_name: Name of the variable

    Returns:
        Dict with keys: long_name, standard_name, units, valid_range, _FillValue.
        Values are None if attribute is missing.
    """
    keys = ["long_name", "standard_name", "units", "valid_range", "_FillValue"]
    try:
        var = ds[var_name]
        return {k: var.attrs.get(k) for k in keys}
    except (KeyError, AttributeError):
        return {k: None for k in keys}


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
                        "grid": "Grid File (.grd/.bas)",
                        "timeseries": "Time Series (.ts)",
                        "netcdf": "NetCDF (.nc)",
                    },
                ),
                ui.input_text(
                    "data_path",
                    "File Path",
                    placeholder="/path/to/data",
                ),
                ui.input_action_button(
                    "load_data_btn",
                    "Load Data",
                    class_="btn-outline-primary btn-sm w-100 mb-3",
                ),
                ui.hr(),
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
                ui.input_checkbox("show_colorbar", "Show Colorbar", value=True),
                ui.input_checkbox("show_grid_lines", "Show Grid Lines", value=False),
                ui.input_checkbox("equal_aspect", "Equal Aspect Ratio", value=True),
                ui.hr(),
                # NetCDF-specific controls
                ui.output_ui("netcdf_controls"),
                # Comparison controls
                ui.h5("Compare"),
                ui.input_text(
                    "compare_path",
                    "Second File (optional)",
                    placeholder="/path/to/compare",
                ),
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
                    output_widget("main_plot"),
                ),
                ui.nav_panel(
                    "Data Info",
                    ui.output_ui("data_info"),
                    ui.output_ui("nc_variable_table"),
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
) -> None:
    """Visualization page server logic."""

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("data_path", value=proj["work_dir"])

    # Auto-fill from tutorial navigation
    @reactive.effect
    def _on_tutorial_context():
        if tutorial_context is None:
            return
        ctx = tutorial_context.get()
        if ctx is None or ctx.get("target_tab") != "Visualize":
            return
        ui.update_text("data_path", value=ctx["work_dir"])
        tutorial_context.set(None)

    # State
    loaded_data = reactive.value(None)
    data_type = reactive.value(None)
    data_info_val = reactive.value({})
    compare_data = reactive.value(None)
    compare_type = reactive.value(None)
    # NetCDF state
    nc_variables = reactive.value([])
    nc_dimensions = reactive.value({})
    # Time series reactive for the timeseries component
    ts_data_val = reactive.value(None)

    # Wire up the timeseries component
    timeseries_server("ts_viewer", ts_data_val, config=config)

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
        elif dtype == "netcdf":
            choices = {
                "contour": "Contour Plot",
                "heatmap": "Heatmap",
                "surface3d": "3D Surface",
                "profile": "Vertical Profile",
                "transect": "Transect",
            }
        else:
            choices = {
                "auto": "Auto-detect",
            }

        return ui.input_select("plot_type", "Plot Type", choices=choices)

    @render.ui
    def netcdf_controls():
        """Show NetCDF variable/dimension selectors when applicable."""
        dtype = input.data_type()
        if dtype != "netcdf":
            return None

        variables = nc_variables.get()
        dims = nc_dimensions.get()
        if not variables:
            return ui.p("Load a NetCDF file to configure.", class_="text-muted small")

        controls = [
            ui.input_select(
                "nc_variable",
                "Variable",
                choices={v: v for v in variables},
            ),
            ui.output_ui("nc_var_metadata"),
        ]
        # Add dimension slicers for dims with more than 2 values
        for dim_name, dim_size in dims.items():
            if dim_size > 1:
                controls.append(
                    ui.input_slider(
                        f"nc_dim_{dim_name}",
                        dim_name,
                        min=0,
                        max=dim_size - 1,
                        value=0,
                        step=1,
                    ),
                )
                controls.append(
                    ui.output_text(f"nc_dim_label_{dim_name}"),
                )

        # Transect controls
        controls.append(ui.hr())
        controls.append(ui.h6("Profile / Transect"))
        controls.append(
            ui.input_numeric("profile_x", "X index (node/col)", value=0, min=0),
        )
        controls.append(
            ui.input_numeric("profile_y", "Y index (node/row)", value=0, min=0),
        )

        return ui.div(
            ui.h6("NetCDF Controls"),
            *controls,
            ui.hr(),
        )

    @reactive.effect
    def _register_dim_labels():
        """Register text renderers for dimension coordinate labels."""
        dims = nc_dimensions.get()
        ds = loaded_data.get()
        if not dims or ds is None or data_type.get() != "netcdf":
            return

        for dim_name in dims:
            if dims[dim_name] <= 1:
                continue
            _dim = dim_name

            @output(id=f"nc_dim_label_{_dim}")
            @render.text
            def _label_text(_d=_dim):
                try:
                    idx = input[f"nc_dim_{_d}"]()
                    ds_val = loaded_data.get()
                    if ds_val is None:
                        return ""
                    return get_dim_label(ds_val, _d, int(idx))
                except Exception:
                    logger.debug("Dim slider for %s not ready", _d)
                    return ""

    @render.ui
    def nc_var_metadata():
        """Show metadata for the selected NetCDF variable."""
        ds = loaded_data.get()
        if ds is None or data_type.get() != "netcdf":
            return None
        try:
            var_name = input.nc_variable()
        except Exception:
            logger.debug("nc_variable input not ready for metadata panel")
            return None
        if not var_name:
            return None

        attrs = get_variable_attrs(ds, var_name)
        parts = []
        if attrs.get("long_name"):
            parts.append(ui.p(ui.em(str(attrs["long_name"])), class_="small mb-1"))
        meta_items = []
        if attrs.get("units"):
            meta_items.append(f"Units: {attrs['units']}")
        if attrs.get("standard_name"):
            meta_items.append(f"CF: {attrs['standard_name']}")
        if attrs.get("valid_range"):
            meta_items.append(f"Range: {attrs['valid_range']}")
        if attrs.get("_FillValue") is not None:
            meta_items.append(f"Fill: {attrs['_FillValue']}")
        if meta_items:
            parts.append(ui.p(" | ".join(meta_items), class_="small text-muted mb-1"))

        if not parts:
            return None
        return ui.div(*parts, class_="mb-2")

    @reactive.effect
    @reactive.event(input.load_data_btn)
    def _load_data():
        dtype = input.data_type()
        path_str = input.data_path()

        if not path_str:
            ui.notification_show("Please enter a file path", type="warning")
            return

        try:
            path = config.validate_path(path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        _do_load(path, dtype, is_compare=False)

    @reactive.effect
    @reactive.event(input.load_compare_btn)
    def _load_compare():
        path_str = input.compare_path()
        if not path_str:
            ui.notification_show("Enter a comparison file path", type="warning")
            return
        try:
            path = config.validate_path(path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return
        dtype = input.data_type()
        _do_load(path, dtype, is_compare=True)

    def _do_load(path: Path, dtype: str, is_compare: bool):
        """Load data from file into primary or comparison slot."""
        try:
            if dtype == "grid":
                grd = GrdParser.parse_file(path)
                if is_compare:
                    compare_data.set(grd)
                    compare_type.set("grid")
                else:
                    loaded_data.set(grd)
                    data_type.set("grid")
                    stats = GrdParser.get_statistics(grd)
                    data_info_val.set(stats)
                ui.notification_show(f"Loaded grid: {grd.num_nodes} nodes", type="message", duration=4)

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
                try:
                    import xarray as xr

                    # Use lazy loading — data stays on disk until accessed
                    ds = xr.open_dataset(path, chunks="auto")
                    if is_compare:
                        compare_data.set(ds)
                        compare_type.set("netcdf")
                    else:
                        loaded_data.set(ds)
                        data_type.set("netcdf")
                        nc_variables.set(list(ds.data_vars))
                        nc_dimensions.set(dict(ds.dims))
                        data_info_val.set(
                            {
                                "file": str(path),
                                "variables": list(ds.data_vars),
                                "dimensions": dict(ds.dims),
                                "coords": list(ds.coords),
                                "attrs": dict(ds.attrs) if ds.attrs else {},
                            }
                        )
                    ui.notification_show(f"Loaded NetCDF: {list(ds.data_vars)}", type="message")
                except ImportError:
                    ui.notification_show("xarray not installed", type="error", duration=6)

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
            show_cb = input.show_colorbar()
            show_grid = input.show_grid_lines()

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
                return _with_export_config(fig, "shyfem_main_plot")
            elif dtype == "timeseries":
                return _with_export_config(
                    _plotly_timeseries(data, plot_type, show_grid), "shyfem_main_plot"
                )
            elif dtype == "netcdf":
                if plot_type in ("profile", "transect"):
                    return _with_export_config(
                        _plotly_netcdf(data, "contour", colormap, show_cb, show_grid, input),
                        "shyfem_main_plot",
                    )
                return _with_export_config(
                    _plotly_netcdf(data, plot_type, colormap, show_cb, show_grid, input),
                    "shyfem_main_plot",
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

    @render.ui
    def nc_variable_table():
        """Show variable summary table for NetCDF datasets."""
        ds = loaded_data.get()
        if ds is None or data_type.get() != "netcdf":
            return None

        rows_data = build_variable_table(ds)
        if not rows_data:
            return ui.p("No variables found", class_="text-muted")

        table_rows = [
            ui.tags.tr(
                ui.tags.td(r["name"]),
                ui.tags.td(r["dims"]),
                ui.tags.td(r["dtype"]),
                ui.tags.td(r["units"]),
                ui.tags.td(r["long_name"]),
                ui.tags.td(f"{r['min']:.4g}" if r["min"] is not None else "-"),
                ui.tags.td(f"{r['max']:.4g}" if r["max"] is not None else "-"),
            )
            for r in rows_data
        ]

        return ui.div(
            ui.h6("Variable Summary"),
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Name"),
                        ui.tags.th("Dimensions"),
                        ui.tags.th("Type"),
                        ui.tags.th("Units"),
                        ui.tags.th("Description"),
                        ui.tags.th("Min"),
                        ui.tags.th("Max"),
                    ),
                ),
                ui.tags.tbody(*table_rows),
                class_="table table-sm table-bordered",
            ),
        )

    @render_widget
    def profile_plot():
        """Vertical profile or transect plot for NetCDF data."""
        data = loaded_data.get()
        dtype = data_type.get()

        if dtype != "netcdf" or data is None:
            fig = go.Figure()
            fig.add_annotation(
                text="Load NetCDF data to view vertical profiles",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=14,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig

        plot_type = input.plot_type()

        try:
            var_name = input.nc_variable()
        except Exception:
            logger.debug("nc_variable input not ready for profile plot")
            var_name = list(data.data_vars)[0] if data.data_vars else None

        if not var_name:
            fig = go.Figure()
            fig.add_annotation(
                text="No variable selected",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
            )
            fig.update_layout(height=500)
            return fig

        try:
            px = int(input.profile_x())
        except Exception:
            logger.debug("profile_x input not ready")
            px = 0
        try:
            py = int(input.profile_y())
        except Exception:
            logger.debug("profile_y input not ready")
            py = 0

        try:
            if plot_type == "transect":
                return _with_export_config(
                    _build_transect(data, var_name, py, input), "shyfem_profile"
                )
            else:
                return _with_export_config(
                    _build_vertical_profile(data, var_name, px, py, input), "shyfem_profile"
                )
        except Exception as exc:
            logger.exception("Error rendering profile plot")
            ui.notification_show(f"Profile plot error: {exc}", type="error", duration=6)
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
            fig.update_layout(height=500)
            return fig

    @render.ui
    def var_statistics():
        """Show variable statistics for loaded data."""
        data = loaded_data.get()
        dtype = data_type.get()

        if data is None:
            return ui.p("Load data to see statistics", class_="text-muted text-center mt-3")

        if dtype == "netcdf":
            return _netcdf_statistics(data)
        elif dtype == "timeseries":
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
        elif dtype == "netcdf":
            return _with_export_config(
                _compare_netcdf(primary, secondary, input), "shyfem_comparison"
            )
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
# NetCDF plots
# ---------------------------------------------------------------------------


def _plotly_netcdf(
    data, plot_type: str, colormap: str, show_colorbar: bool, show_grid: bool, input
) -> go.Figure:
    """Create an interactive Plotly figure for NetCDF data."""
    fig = go.Figure()

    try:
        try:
            var_name = input.nc_variable()
        except Exception:
            logger.debug("nc_variable input not yet available, using first data var")
            var_name = list(data.data_vars)[0]

        var = data[var_name]

        # Apply dimension slicing from sliders
        slice_info = {}
        for dim in list(var.dims):
            try:
                idx = input[f"nc_dim_{dim}"]()
                if idx is not None and data.sizes[dim] > 1:
                    var = var.isel({dim: int(idx)})
                    slice_info[dim] = int(idx)
            except Exception:
                logger.debug("Dimension slider for %s not available yet", dim)

        # Reduce to 2D if still higher-dimensional
        while len(var.dims) > 2:
            var = var.isel({var.dims[0]: 0})
            slice_info[var.dims[0]] = 0

        values = var.values
        dim_names = list(var.dims)

        # Get coordinate values if available
        coords = {}
        for d in dim_names:
            if d in var.coords:
                coords[d] = var.coords[d].values
            else:
                coords[d] = np.arange(values.shape[dim_names.index(d)])

        if plot_type == "contour":
            fig.add_trace(
                go.Contour(
                    z=values,
                    x=coords.get(dim_names[1], None) if len(dim_names) > 1 else None,
                    y=coords.get(dim_names[0], None),
                    colorscale=colormap,
                    showscale=show_colorbar,
                    colorbar=dict(title=var_name, thickness=15) if show_colorbar else None,
                    contours=dict(showlabels=True),
                )
            )
        elif plot_type == "heatmap":
            fig.add_trace(
                go.Heatmap(
                    z=values,
                    x=coords.get(dim_names[1], None) if len(dim_names) > 1 else None,
                    y=coords.get(dim_names[0], None),
                    colorscale=colormap,
                    showscale=show_colorbar,
                    colorbar=dict(title=var_name, thickness=15) if show_colorbar else None,
                )
            )
        elif plot_type == "surface3d":
            fig.add_trace(
                go.Surface(
                    z=values,
                    x=coords.get(dim_names[1], None) if len(dim_names) > 1 else None,
                    y=coords.get(dim_names[0], None),
                    colorscale=colormap,
                    showscale=show_colorbar,
                )
            )
            fig.update_layout(
                scene=dict(
                    zaxis_title=var_name,
                    xaxis_title=dim_names[1] if len(dim_names) > 1 else "",
                    yaxis_title=dim_names[0],
                )
            )
        else:
            fig.add_trace(
                go.Heatmap(
                    z=values,
                    colorscale=colormap,
                    showscale=show_colorbar,
                )
            )

        # Build title with slice info
        title = var_name
        if slice_info:
            slice_str = ", ".join(f"{k}={v}" for k, v in slice_info.items())
            title = f"{var_name} [{slice_str}]"
        fig.update_layout(title=title)

        if len(dim_names) >= 2 and plot_type != "surface3d":
            fig.update_xaxes(title=dim_names[1] if len(dim_names) > 1 else "")
            fig.update_yaxes(title=dim_names[0])

    except Exception as e:
        fig.add_annotation(
            text=f"Error: {e}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font_color="red",
        )

    fig.update_layout(height=600)

    if show_grid and plot_type != "surface3d":
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)")
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="rgba(0,0,0,0.1)")

    return fig


def _build_vertical_profile(ds, var_name: str, x_idx: int, y_idx: int, input) -> go.Figure:
    """Build a vertical profile plot at a given (x, y) location."""
    fig = go.Figure()

    try:
        var = ds[var_name]
        dims = list(var.dims)

        # Look for a vertical dimension (common names)
        vert_dims = [
            d
            for d in dims
            if d.lower()
            in (
                "level",
                "levels",
                "depth",
                "z",
                "sigma",
                "layer",
                "lev",
            )
        ]

        if not vert_dims:
            # Try to find any dim that's not time, x, or y
            spatial_dims = [
                d
                for d in dims
                if d.lower()
                not in (
                    "time",
                    "x",
                    "y",
                    "lon",
                    "lat",
                    "longitude",
                    "latitude",
                    "node",
                )
            ]
            if spatial_dims:
                vert_dims = [spatial_dims[0]]

        if not vert_dims:
            fig.add_annotation(
                text="No vertical dimension found in this variable",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=14,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig

        vert_dim = vert_dims[0]

        # Slice all other dimensions
        sel = {}
        for dim in dims:
            if dim == vert_dim:
                continue
            try:
                idx = input[f"nc_dim_{dim}"]()
                if idx is not None:
                    sel[dim] = int(idx)
                    continue
            except Exception:
                logger.debug("Dimension slider for %s not available yet", dim)

            # Use provided x/y indices for spatial dims
            dim_lower = dim.lower()
            if dim_lower in ("x", "lon", "longitude", "node"):
                sel[dim] = min(x_idx, ds.sizes[dim] - 1)
            elif dim_lower in ("y", "lat", "latitude"):
                sel[dim] = min(y_idx, ds.sizes[dim] - 1)
            elif dim_lower == "time":
                sel[dim] = 0
            else:
                sel[dim] = 0

        profile = var.isel(sel)
        values = profile.values

        # Get vertical coordinate
        if vert_dim in ds.coords:
            z_vals = ds.coords[vert_dim].values
        else:
            z_vals = np.arange(len(values))

        fig.add_trace(
            go.Scattergl(
                x=values,
                y=z_vals,
                mode="lines+markers",
                marker=dict(size=6),
                name=var_name,
            )
        )

        # Build info string
        slice_str = ", ".join(f"{k}={v}" for k, v in sel.items())
        fig.update_layout(
            title=f"Vertical Profile: {var_name} [{slice_str}]",
            xaxis_title=var_name,
            yaxis_title=vert_dim,
            yaxis=dict(autorange="reversed"),  # Depth increases downward
            height=500,
        )

    except Exception as e:
        fig.add_annotation(
            text=f"Error: {e}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font_color="red",
        )
        fig.update_layout(height=500)

    return fig


def _build_transect(ds, var_name: str, row_idx: int, input) -> go.Figure:
    """Build a transect (cross-section) plot along one axis."""
    fig = go.Figure()

    try:
        var = ds[var_name]
        dims = list(var.dims)

        # Fix time dimension if present
        sel = {}
        for dim in dims:
            try:
                idx = input[f"nc_dim_{dim}"]()
                if idx is not None and dim.lower() == "time":
                    sel[dim] = int(idx)
            except Exception:
                logger.debug("Dimension slider for %s not available yet", dim)

        if sel:
            var = var.isel(sel)
            dims = list(var.dims)

        if len(dims) < 2:
            fig.add_annotation(
                text="Variable needs at least 2 dimensions for transect",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=14,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig

        # Slice along the first spatial dimension at row_idx
        row_idx = min(row_idx, var.shape[0] - 1)
        transect = var.isel({dims[0]: row_idx})
        remaining_dims = list(transect.dims)

        if len(remaining_dims) == 1:
            # Simple 1D transect line
            values = transect.values
            if remaining_dims[0] in ds.coords:
                x_vals = ds.coords[remaining_dims[0]].values
            else:
                x_vals = np.arange(len(values))

            fig.add_trace(
                go.Scattergl(
                    x=x_vals,
                    y=values,
                    mode="lines+markers",
                    name=f"{var_name} at {dims[0]}={row_idx}",
                )
            )
            fig.update_layout(
                xaxis_title=remaining_dims[0],
                yaxis_title=var_name,
            )
        else:
            # 2D transect cross-section (heatmap)
            values = transect.values
            coords_x = (
                ds.coords[remaining_dims[1]].values if remaining_dims[1] in ds.coords else None
            )
            coords_y = (
                ds.coords[remaining_dims[0]].values if remaining_dims[0] in ds.coords else None
            )

            fig.add_trace(
                go.Heatmap(
                    z=values,
                    x=coords_x,
                    y=coords_y,
                    colorscale=input.colormap(),
                    colorbar=dict(title=var_name),
                )
            )
            fig.update_layout(
                xaxis_title=remaining_dims[1] if len(remaining_dims) > 1 else "",
                yaxis_title=remaining_dims[0],
            )

        fig.update_layout(
            title=f"Transect: {var_name} at {dims[0]}={row_idx}",
            height=500,
        )

    except Exception as e:
        fig.add_annotation(
            text=f"Error: {e}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font_color="red",
        )
        fig.update_layout(height=500)

    return fig


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _netcdf_statistics(ds) -> ui.Tag:
    """Compute and display statistics for all NetCDF variables."""
    rows = []
    for var_name in ds.data_vars:
        try:
            var = ds[var_name]
            values = var.values.flatten()
            values = values[~np.isnan(values)]
            if len(values) == 0:
                continue
            rows.append(
                ui.tags.tr(
                    ui.tags.td(ui.strong(var_name)),
                    ui.tags.td(str(var.dims)),
                    ui.tags.td(str(var.shape)),
                    ui.tags.td(f"{np.min(values):.4g}"),
                    ui.tags.td(f"{np.max(values):.4g}"),
                    ui.tags.td(f"{np.mean(values):.4g}"),
                    ui.tags.td(f"{np.std(values):.4g}"),
                    ui.tags.td(str(var.attrs.get("units", "-"))),
                )
            )
        except Exception:
            logger.debug("Failed to compute stats for variable %s", var_name, exc_info=True)
            continue

    if not rows:
        return ui.p("No computable statistics", class_="text-muted")

    return ui.div(
        ui.h5("Variable Statistics"),
        ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Variable"),
                    ui.tags.th("Dims"),
                    ui.tags.th("Shape"),
                    ui.tags.th("Min"),
                    ui.tags.th("Max"),
                    ui.tags.th("Mean"),
                    ui.tags.th("Std"),
                    ui.tags.th("Units"),
                ),
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-bordered table-hover",
        ),
    )


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


def _compare_netcdf(ds1, ds2, input) -> go.Figure:
    """Difference map between two NetCDF datasets."""
    try:
        var_name = input.nc_variable()
    except Exception:
        logger.debug("nc_variable input not ready for comparison")
        var_name = list(ds1.data_vars)[0] if ds1.data_vars else None

    if not var_name or var_name not in ds2.data_vars:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Variable '{var_name}' not found in comparison dataset",
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

    try:
        var1 = ds1[var_name]
        var2 = ds2[var_name]

        # Slice both to 2D using the same dimension indices
        for dim in list(var1.dims):
            try:
                idx = input[f"nc_dim_{dim}"]()
                if idx is not None and ds1.sizes[dim] > 1:
                    var1 = var1.isel({dim: int(idx)})
                    if dim in var2.dims:
                        var2 = var2.isel({dim: int(idx)})
            except Exception:
                logger.debug("Dimension slider for %s not available yet", dim)

        while len(var1.dims) > 2:
            var1 = var1.isel({var1.dims[0]: 0})
        while len(var2.dims) > 2:
            var2 = var2.isel({var2.dims[0]: 0})

        vals1 = var1.values
        vals2 = var2.values

        # Compute difference (handle shape mismatch)
        min_shape = tuple(min(s1, s2) for s1, s2 in zip(vals1.shape, vals2.shape, strict=True))
        diff = vals1[: min_shape[0], : min_shape[1]] - vals2[: min_shape[0], : min_shape[1]]

        dim_names = list(var1.dims)
        coords_x = (
            var1.coords[dim_names[1]].values[: min_shape[1]]
            if len(dim_names) > 1 and dim_names[1] in var1.coords
            else None
        )
        coords_y = (
            var1.coords[dim_names[0]].values[: min_shape[0]]
            if dim_names[0] in var1.coords
            else None
        )

        fig = make_subplots(
            rows=1,
            cols=3,
            subplot_titles=("Primary", "Comparison", "Difference"),
        )

        for col, (vals, _title) in enumerate(
            [(vals1, "Primary"), (vals2, "Comparison"), (diff, "Diff")], 1
        ):
            cmap = "RdBu_r" if col == 3 else input.colormap()
            fig.add_trace(
                go.Heatmap(
                    z=vals[: min_shape[0], : min_shape[1]] if col < 3 else vals,
                    x=coords_x,
                    y=coords_y,
                    colorscale=cmap,
                    showscale=(col == 3),
                    colorbar=dict(title="Diff" if col == 3 else "", x=1.02) if col == 3 else None,
                ),
                row=1,
                col=col,
            )

        fig.update_layout(
            title=f"NetCDF Comparison: {var_name}",
            height=500,
        )
        return fig

    except Exception as e:
        fig = go.Figure()
        fig.add_annotation(
            text=f"Comparison error: {e}",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font_color="red",
        )
        fig.update_layout(height=600)
        return fig
