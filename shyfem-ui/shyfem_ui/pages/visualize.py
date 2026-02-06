"""Visualization page - interactive plots with Plotly/matplotlib."""

from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.services.parser_grd import GrdFile, GrdParser


@module.ui
def visualize_ui():
    """Visualization page UI."""
    return ui.page_fluid(
        ui.h3("Visualization"),
        ui.p("Create plots from SHYFEM results and grid files.", class_="text-muted"),
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
                        "shy": "SHYFEM Output (.shy)",
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
                # Plot type
                ui.h5("Plot Type"),
                ui.output_ui("plot_type_select"),
                ui.hr(),
                # Plot options
                ui.h5("Options"),
                ui.input_select(
                    "colormap",
                    "Colormap",
                    choices={
                        "viridis": "Viridis",
                        "plasma": "Plasma",
                        "inferno": "Inferno",
                        "magma": "Magma",
                        "cividis": "Cividis",
                        "coolwarm": "Coolwarm",
                        "RdBu_r": "Red-Blue (reversed)",
                        "jet": "Jet",
                    },
                ),
                ui.input_checkbox("show_colorbar", "Show Colorbar", value=True),
                ui.input_checkbox("show_grid", "Show Grid Lines", value=False),
                ui.input_checkbox("equal_aspect", "Equal Aspect Ratio", value=True),
                ui.hr(),
                # Export
                ui.h5("Export"),
                ui.input_select(
                    "export_format",
                    "Format",
                    choices={
                        "png": "PNG",
                        "pdf": "PDF",
                        "svg": "SVG",
                    },
                ),
                ui.input_numeric("dpi", "DPI", value=150, min=72, max=600),
                ui.input_action_button(
                    "export_btn",
                    "Export Plot",
                    class_="btn-outline-secondary w-100",
                ),
                width=300,
            ),
            # Main content
            ui.navset_card_tab(
                ui.nav_panel(
                    "Plot",
                    ui.output_plot("main_plot", height="600px"),
                ),
                ui.nav_panel(
                    "Data Info",
                    ui.output_ui("data_info"),
                ),
                ui.nav_panel(
                    "Time Series",
                    ui.output_plot("ts_plot", height="400px"),
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
):
    """Visualization page server logic."""
    # State
    loaded_data = reactive.value(None)
    data_type = reactive.value(None)
    data_info_val = reactive.value({})

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
                "vector": "Vector Field",
                "streamlines": "Streamlines",
            }
        else:
            choices = {
                "auto": "Auto-detect",
            }

        return ui.input_select(
            "plot_type",
            "Plot Type",
            choices=choices,
        )

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

        try:
            if dtype == "grid":
                grd = GrdParser.parse_file(path)
                loaded_data.set(grd)
                data_type.set("grid")
                stats = GrdParser.get_statistics(grd)
                data_info_val.set(stats)
                ui.notification_show(f"Loaded grid: {grd.num_nodes} nodes", type="message")

            elif dtype == "timeseries":
                # Load time series data
                ts_data = _load_timeseries(path)
                loaded_data.set(ts_data)
                data_type.set("timeseries")
                data_info_val.set({
                    "file": str(path),
                    "columns": len(ts_data.get("columns", [])),
                    "rows": len(ts_data.get("data", [])),
                })
                ui.notification_show("Loaded time series data", type="message")

            elif dtype == "netcdf":
                try:
                    import xarray as xr
                    ds = xr.open_dataset(path)
                    loaded_data.set(ds)
                    data_type.set("netcdf")
                    data_info_val.set({
                        "file": str(path),
                        "variables": list(ds.data_vars),
                        "dimensions": dict(ds.dims),
                    })
                    ui.notification_show(f"Loaded NetCDF: {list(ds.data_vars)}", type="message")
                except ImportError:
                    ui.notification_show("xarray not installed", type="error")

            else:
                ui.notification_show(f"Unsupported data type: {dtype}", type="error")

        except Exception as e:
            ui.notification_show(f"Error loading data: {e}", type="error")

    @render.plot
    def main_plot():
        data = loaded_data.get()
        dtype = data_type.get()

        if data is None:
            fig, ax = plt.subplots(figsize=(10, 8))
            ax.text(0.5, 0.5, "Load data to generate plot",
                   ha="center", va="center", fontsize=14, color="gray")
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            return fig

        plot_type = input.plot_type()
        colormap = input.colormap()
        show_colorbar = input.show_colorbar()
        show_grid = input.show_grid()
        equal_aspect = input.equal_aspect()

        if dtype == "grid":
            return _plot_grid(data, plot_type, colormap, show_colorbar, show_grid, equal_aspect)
        elif dtype == "timeseries":
            return _plot_timeseries(data, plot_type, show_grid)
        elif dtype == "netcdf":
            return _plot_netcdf(data, plot_type, colormap, show_colorbar, show_grid)
        else:
            fig, ax = plt.subplots()
            ax.text(0.5, 0.5, "Unsupported data type", ha="center", va="center")
            return fig

    @render.ui
    def data_info():
        info = data_info_val.get()
        if not info:
            return ui.p("No data loaded", class_="text-muted")

        rows = []
        for key, value in info.items():
            if isinstance(value, (list, dict)):
                value_str = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
            else:
                value_str = str(value)

            rows.append(
                ui.tags.tr(
                    ui.tags.th(key),
                    ui.tags.td(value_str),
                )
            )

        return ui.tags.table(
            ui.tags.tbody(*rows),
            class_="table table-sm",
        )

    @render.plot
    def ts_plot():
        data = loaded_data.get()
        dtype = data_type.get()

        if dtype != "timeseries" or data is None:
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.text(0.5, 0.5, "Load time series data to view",
                   ha="center", va="center", fontsize=12, color="gray")
            ax.axis("off")
            return fig

        return _plot_timeseries(data, "line", True)

    @reactive.effect
    @reactive.event(input.export_btn)
    def _export_plot():
        data = loaded_data.get()
        if data is None:
            ui.notification_show("No data to export", type="warning")
            return

        fmt = input.export_format()
        dpi = input.dpi()
        path_str = input.data_path()

        if path_str:
            base_path = Path(path_str).resolve().parent / f"plot.{fmt}"
        else:
            base_path = config.work_dir / f"plot.{fmt}"

        try:
            base_path = config.validate_save_path(base_path)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return

        try:
            # Generate the plot
            dtype = data_type.get()
            if dtype == "grid":
                fig = _plot_grid(
                    data, input.plot_type(), input.colormap(),
                    input.show_colorbar(), input.show_grid(), input.equal_aspect()
                )
            elif dtype == "timeseries":
                fig = _plot_timeseries(data, input.plot_type(), input.show_grid())
            else:
                ui.notification_show("Cannot export this data type", type="error")
                return

            fig.savefig(base_path, dpi=dpi, bbox_inches="tight")
            plt.close(fig)

            ui.notification_show(f"Exported to: {base_path}", type="message")
        except Exception as e:
            ui.notification_show(f"Export failed: {e}", type="error")

    return {}


def _load_timeseries(path: Path) -> dict:
    """Load time series data from file."""
    import pandas as pd

    try:
        # Try to read as CSV/TSV
        df = pd.read_csv(path, sep=None, engine="python")
        return {
            "columns": list(df.columns),
            "data": df.values.tolist(),
            "df": df,
        }
    except Exception:
        # Try simple whitespace-separated
        data = []
        columns = []
        with open(path) as f:
            for i, line in enumerate(f):
                parts = line.strip().split()
                if parts:
                    if i == 0 and not parts[0].replace(".", "").replace("-", "").isdigit():
                        columns = parts
                    else:
                        try:
                            data.append([float(p) for p in parts])
                        except ValueError:
                            continue

        if not columns:
            columns = [f"col{i}" for i in range(len(data[0]) if data else 0)]

        return {
            "columns": columns,
            "data": data,
            "df": None,
        }


def _plot_grid(
    grd: GrdFile,
    plot_type: str,
    colormap: str,
    show_colorbar: bool,
    show_grid: bool,
    equal_aspect: bool,
) -> plt.Figure:
    """Plot grid data."""
    fig, ax = plt.subplots(figsize=(10, 8))

    node_ids = list(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    if plot_type == "mesh":
        for elem in grd.elements.values():
            try:
                indices = [node_map[nid] for nid in elem.nodes if nid in node_map]
                if len(indices) < 3:
                    continue
                indices.append(indices[0])
                ax.plot(x[indices], y[indices], "b-", linewidth=0.5, alpha=0.7)
            except (KeyError, IndexError):
                continue
        ax.set_title(f"Mesh: {grd.num_nodes:,} nodes, {grd.num_elements:,} elements")

    elif plot_type == "depth":
        depths = np.array([
            grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0
            for nid in node_ids
        ])

        if not np.all(depths == 0):
            from matplotlib.tri import Triangulation
            triangles = []
            for elem in grd.elements.values():
                if elem.is_triangle:
                    try:
                        tri = [node_map[nid] for nid in elem.nodes]
                        triangles.append(tri)
                    except KeyError:
                        continue

            if triangles:
                tri = Triangulation(x, y, triangles)
                contour = ax.tricontourf(tri, depths, levels=20, cmap=colormap)
                if show_colorbar:
                    fig.colorbar(contour, ax=ax, label="Depth")
        ax.set_title("Depth Contour")

    elif plot_type == "boundaries":
        # Plot elements as background
        for elem in grd.elements.values():
            try:
                indices = [node_map[nid] for nid in elem.nodes if nid in node_map]
                if len(indices) >= 3:
                    indices.append(indices[0])
                    ax.plot(x[indices], y[indices], "lightgray", linewidth=0.3)
            except (KeyError, IndexError):
                continue

        # Plot boundaries
        line_types = grd.get_line_types()
        colors = plt.cm.Set1(np.linspace(0, 1, max(len(line_types), 1)))
        type_color_map = {lt: colors[i % len(colors)] for i, lt in enumerate(sorted(line_types))}

        for line in grd.lines.values():
            try:
                indices = [node_map[nid] for nid in line.nodes if nid in node_map]
                if len(indices) >= 2:
                    color = type_color_map.get(line.line_type, "blue")
                    ax.plot(x[indices], y[indices], color=color, linewidth=2)
            except (KeyError, IndexError):
                continue
        ax.set_title(f"Boundaries: {grd.num_lines:,} lines")

    elif plot_type == "quality":
        qualities = []
        centroids = []

        for elem in grd.elements.values():
            if not elem.is_triangle:
                continue
            try:
                indices = [node_map[nid] for nid in elem.nodes]
                ex = x[indices]
                ey = y[indices]

                sides = []
                for i in range(3):
                    j = (i + 1) % 3
                    side_len = np.sqrt((ex[j] - ex[i])**2 + (ey[j] - ey[i])**2)
                    sides.append(side_len)

                quality = min(sides) / max(sides) if max(sides) > 0 else 0
                qualities.append(quality)
                centroids.append((np.mean(ex), np.mean(ey)))
            except (KeyError, IndexError):
                continue

        if qualities:
            centroids = np.array(centroids)
            scatter = ax.scatter(
                centroids[:, 0], centroids[:, 1],
                c=qualities, s=10, cmap="RdYlGn", vmin=0, vmax=1
            )
            if show_colorbar:
                fig.colorbar(scatter, ax=ax, label="Quality")
        ax.set_title(f"Element Quality ({len(qualities):,} triangles)")

    ax.set_xlabel("X")
    ax.set_ylabel("Y")

    if equal_aspect:
        ax.set_aspect("equal")

    if show_grid:
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


def _plot_timeseries(data: dict, plot_type: str, show_grid: bool) -> plt.Figure:
    """Plot time series data."""
    fig, ax = plt.subplots(figsize=(10, 4))

    df = data.get("df")
    if df is not None:
        for col in df.columns[1:]:  # Skip first column (assume time)
            if plot_type == "line":
                ax.plot(df.iloc[:, 0], df[col], label=col)
            elif plot_type == "scatter":
                ax.scatter(df.iloc[:, 0], df[col], label=col, s=5)
            elif plot_type == "area":
                ax.fill_between(df.iloc[:, 0], df[col], alpha=0.5, label=col)
    else:
        arr = np.array(data.get("data", []))
        if arr.size > 0:
            for i in range(1, arr.shape[1]):
                col_name = data["columns"][i] if i < len(data["columns"]) else f"col{i}"
                if plot_type == "line":
                    ax.plot(arr[:, 0], arr[:, i], label=col_name)
                elif plot_type == "scatter":
                    ax.scatter(arr[:, 0], arr[:, i], label=col_name, s=5)
                elif plot_type == "area":
                    ax.fill_between(arr[:, 0], arr[:, i], alpha=0.5, label=col_name)

    ax.set_xlabel("Time")
    ax.set_ylabel("Value")
    ax.legend(loc="upper right")

    if show_grid:
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig


def _plot_netcdf(data, plot_type: str, colormap: str, show_colorbar: bool, show_grid: bool) -> plt.Figure:
    """Plot NetCDF data."""
    fig, ax = plt.subplots(figsize=(10, 8))

    try:
        # Get first data variable
        var_name = list(data.data_vars)[0]
        var = data[var_name]

        # Get 2D slice if needed
        while len(var.dims) > 2:
            var = var.isel({var.dims[0]: 0})

        if plot_type == "contour":
            var.plot(ax=ax, cmap=colormap, add_colorbar=show_colorbar)
        else:
            var.plot(ax=ax, cmap=colormap, add_colorbar=show_colorbar)

        ax.set_title(var_name)

    except Exception as e:
        ax.text(0.5, 0.5, f"Error: {e}", ha="center", va="center")

    if show_grid:
        ax.grid(True, alpha=0.3)

    fig.tight_layout()
    return fig
