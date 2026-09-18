"""Interactive time series component with Plotly.

Features:
- Multi-variable time series with selectable columns
- Dual Y-axis support for variables with different units
- Statistics panel (min, max, mean, std, range)
- Observation data overlay for model-observation comparison
- CSV export of displayed data
- Range slider for time navigation
"""

import csv
import io
import logging
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.services.project_files import list_project_files

logger = logging.getLogger(__name__)


def _scatter_mode(style: str) -> str:
    """Map the UI plot style to a valid Plotly scatter ``mode``.

    The style select offers ``line``/``scatter``/``area``, but Plotly's
    ``mode`` flaglist only accepts ``lines``/``markers``/``text`` — passing
    ``"line"`` or ``"scatter"`` raises. ``area`` is drawn as filled lines.
    """
    return {"line": "lines", "scatter": "markers", "area": "lines"}.get(style, "lines")


@module.ui
def timeseries_ui(height: str = "500px"):
    """Interactive time series component UI."""
    return ui.div(
        # Controls bar
        ui.div(
            ui.div(
                ui.output_ui("column_selector"),
                class_="col-5",
            ),
            ui.div(
                ui.input_select(
                    "plot_style",
                    "Style",
                    choices={
                        "line": "Line",
                        "scatter": "Scatter",
                        "line+markers": "Line + Markers",
                        "area": "Area",
                    },
                    selected="line",
                    width="100%",
                ),
                class_="col-2",
            ),
            ui.div(
                ui.input_checkbox("dual_yaxis", "Dual Y-Axis", value=False),
                ui.input_checkbox("show_stats", "Show Statistics", value=True),
                class_="col-2 d-flex flex-column justify-content-center",
            ),
            ui.div(
                ui.input_action_button(
                    "export_csv_btn",
                    "Export CSV",
                    class_="btn-sm btn-outline-primary me-1",
                ),
                class_="col-3 d-flex align-items-center justify-content-end",
            ),
            class_="row mb-2 align-items-end",
        ),
        # Main plot
        output_widget("ts_plot"),
        # Statistics panel
        ui.output_ui("stats_panel"),
        # Observation overlay controls
        ui.div(
            ui.h6("Observation Overlay"),
            ui.div(
                ui.div(
                    ui.output_ui("obs_file_picker"),
                    class_="col-8",
                ),
                ui.div(
                    ui.input_action_button(
                        "load_obs_btn",
                        "Load",
                        class_="btn-sm btn-outline-secondary mt-4",
                    ),
                    ui.input_action_button(
                        "clear_obs_btn",
                        "Clear",
                        class_="btn-sm btn-outline-danger mt-4 ms-1",
                    ),
                    class_="col-4 d-flex",
                ),
                class_="row",
            ),
            class_="mt-2 p-2 border rounded",
        ),
        class_="timeseries-component",
    )


@module.server
def timeseries_server(
    input,
    output,
    session,
    ts_data: reactive.Value,
    config=None,
    current_user=None,
    active_project=None,
):
    """Time series component server logic.

    Args:
        ts_data: Reactive value containing time series data dict with keys:
            - columns: list[str] - column names (first is time/x-axis)
            - data: list[list[float]] - rows of data
            - df: Optional[pandas.DataFrame] - if available
        config: Optional Config for path validation
        active_project: Optional reactive.Value of the active project; drives
            the observation-overlay file picker (project files, no free-text
            path box).
    """
    obs_data = reactive.value(None)

    @render.ui
    def column_selector():
        data = ts_data.get()
        if not data:
            return ui.p("Load data to select columns", class_="text-muted small")

        columns = data.get("columns", [])
        if len(columns) <= 1:
            return ui.p("No data columns available", class_="text-muted small")

        # Skip first column (time/x-axis)
        choices = {col: col for col in columns[1:]}
        return ui.input_checkbox_group(
            "selected_columns",
            "Columns",
            choices=choices,
            selected=list(choices.keys())[:5],  # Select first 5 by default
            inline=True,
        )

    @render_widget
    def ts_plot():
        data = ts_data.get()
        if not data:
            fig = go.Figure()
            fig.add_annotation(
                text="No time series data loaded",
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=16,
                font_color="gray",
            )
            fig.update_layout(height=500)
            return fig

        columns = data.get("columns", [])
        rows = data.get("data", [])
        df = data.get("df")

        if not rows and df is None:
            fig = go.Figure()
            fig.add_annotation(
                text="No data rows available",
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

        # Get selected columns
        try:
            selected = input.selected_columns()
        except Exception:
            logger.debug("Column selection input unavailable, using defaults")
            selected = columns[1:] if len(columns) > 1 else []

        style = input.plot_style()
        dual = input.dual_yaxis()

        # Build figure
        if dual and len(selected) >= 2:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
        else:
            fig = go.Figure()

        # Get x-axis data
        if df is not None:
            x_vals = df.iloc[:, 0]
        else:
            arr = np.array(rows)
            x_vals = arr[:, 0].tolist() if arr.size > 0 else []

        for i, col in enumerate(selected):
            # Get y values
            if df is not None:
                if col in df.columns:
                    y_vals = df[col]
                else:
                    continue
            else:
                col_idx = columns.index(col) if col in columns else None
                if col_idx is None or arr.size == 0:
                    continue
                y_vals = arr[:, col_idx].tolist()

            secondary = dual and i >= len(selected) // 2

            # Map the UI style to a valid Plotly scatter mode: the select uses
            # "line"/"scatter"/"area", but Plotly needs "lines"/"markers".
            mode = _scatter_mode(style)
            fill = "tozeroy" if style == "area" else None

            trace_kwargs = dict(
                x=x_vals,
                y=y_vals,
                mode=mode,
                name=col,
                fill=fill,
                opacity=0.7 if style == "area" else 1.0,
            )

            if style == "scatter":
                trace_kwargs["marker"] = dict(size=4)

            if style == "area":
                trace = go.Scatter(**trace_kwargs)
            else:
                trace = go.Scattergl(**trace_kwargs)

            if dual and len(selected) >= 2:
                fig.add_trace(trace, secondary_y=secondary)
            else:
                fig.add_trace(trace)

        # Overlay observation data if loaded
        obs = obs_data.get()
        if obs:
            obs_cols = obs.get("columns", [])
            obs_rows = obs.get("data", [])
            if obs_rows and len(obs_cols) > 1:
                obs_arr = np.array(obs_rows)
                obs_x = obs_arr[:, 0].tolist()
                for j in range(1, len(obs_cols)):
                    fig.add_trace(
                        go.Scattergl(
                            x=obs_x,
                            y=obs_arr[:, j].tolist(),
                            mode="markers",
                            marker=dict(
                                size=6, symbol="diamond", line=dict(width=1, color="black")
                            ),
                            name=f"Obs: {obs_cols[j]}",
                        )
                    )

        # Layout
        fig.update_layout(
            xaxis_title=columns[0] if columns else "Time",
            yaxis_title="Value",
            height=500,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )

        if dual and len(selected) >= 2:
            half = len(selected) // 2
            fig.update_yaxes(title_text=", ".join(selected[:half]), secondary_y=False)
            fig.update_yaxes(title_text=", ".join(selected[half:]), secondary_y=True)

        fig.update_xaxes(rangeslider_visible=True)
        return fig

    @render.ui
    def stats_panel():
        if not input.show_stats():
            return None

        data = ts_data.get()
        if not data:
            return None

        columns = data.get("columns", [])
        rows = data.get("data", [])
        df = data.get("df")

        try:
            selected = input.selected_columns()
        except Exception:
            logger.debug("Column selection input unavailable, using defaults")
            selected = columns[1:] if len(columns) > 1 else []

        if not selected:
            return None

        stat_rows = []
        for col in selected:
            if df is not None:
                if col in df.columns:
                    vals = df[col].dropna()
                else:
                    continue
            else:
                arr = np.array(rows)
                col_idx = columns.index(col) if col in columns else None
                if col_idx is None or arr.size == 0:
                    continue
                vals = arr[:, col_idx]
                vals = vals[~np.isnan(vals)]

            if len(vals) == 0:
                continue

            stat_rows.append(
                ui.tags.tr(
                    ui.tags.td(ui.strong(col)),
                    ui.tags.td(f"{np.min(vals):.4g}"),
                    ui.tags.td(f"{np.max(vals):.4g}"),
                    ui.tags.td(f"{np.mean(vals):.4g}"),
                    ui.tags.td(f"{np.std(vals):.4g}"),
                    ui.tags.td(f"{np.max(vals) - np.min(vals):.4g}"),
                    ui.tags.td(f"{len(vals)}"),
                )
            )

        if not stat_rows:
            return None

        return ui.div(
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Variable"),
                        ui.tags.th("Min"),
                        ui.tags.th("Max"),
                        ui.tags.th("Mean"),
                        ui.tags.th("Std"),
                        ui.tags.th("Range"),
                        ui.tags.th("Count"),
                    ),
                ),
                ui.tags.tbody(*stat_rows),
                class_="table table-sm table-bordered mt-2",
            ),
        )

    # --- Observation overlay ---

    # --- Observation overlay ---

    @render.ui
    def obs_file_picker():
        """Dropdown of observation-shaped files (.csv/.txt) in the active
        project — replaces the old free-text path box."""
        proj = active_project.get() if active_project is not None else None
        if proj is None:
            return ui.p("Open a project to overlay observations.", class_="text-muted small mb-0")
        usr = current_user() if current_user is not None else None
        try:
            if config is not None:
                root = Path(config.confine_path(proj["work_dir"], usr, must_exist=True))
            else:
                root = Path(proj["work_dir"])
        except (ValueError, OSError):
            return ui.p("Project directory unavailable.", class_="text-muted small mb-0")
        choices = {"": "— select observations —"}
        for rel in list_project_files(root, (".csv", ".txt")):
            choices[rel] = rel
        if len(choices) == 1:
            return ui.p(
                "No .csv/.txt observation files in this project.", class_="text-muted small mb-0"
            )
        return ui.input_select("obs_file", "Observation File", choices=choices, selected="")

    @reactive.effect
    @reactive.event(input.load_obs_btn)
    def _load_obs():
        try:
            rel = input.obs_file()
        except Exception:
            rel = ""
        if not rel:
            ui.notification_show("Select an observation file", type="warning")
            return
        proj = active_project.get() if active_project is not None else None
        if proj is None:
            ui.notification_show("Open a project first", type="warning")
            return
        _usr = current_user() if current_user is not None else None
        target = str(Path(proj["work_dir"]) / rel)
        if config is not None:
            try:
                path = config.confine_path(target, _usr, must_exist=True)
            except (ValueError, FileNotFoundError) as e:
                ui.notification_show(str(e), type="error", duration=6)
                return
        else:
            path = Path(target)
            if not path.exists():
                ui.notification_show(f"File not found: {path}", type="error", duration=6)
                return

        try:
            obs = _load_obs_file(path)
            obs_data.set(obs)
            ui.notification_show(
                f"Loaded {len(obs['data'])} observation points",
                type="message",
            )
        except Exception as e:
            ui.notification_show(f"Error loading observations: {e}", type="error", duration=6)

    @reactive.effect
    @reactive.event(input.clear_obs_btn)
    def _clear_obs():
        obs_data.set(None)

    # --- CSV export ---

    @reactive.effect
    @reactive.event(input.export_csv_btn)
    async def _export_csv():
        data = ts_data.get()
        if not data:
            ui.notification_show("No data to export", type="warning")
            return

        columns = data.get("columns", [])
        rows = data.get("data", [])
        df = data.get("df")

        try:
            selected = input.selected_columns()
        except Exception:
            logger.debug("Column selection input unavailable, using defaults")
            selected = columns[1:] if len(columns) > 1 else []

        # Build CSV content
        buf = io.StringIO()
        writer = csv.writer(buf)

        # Header
        export_cols = [columns[0]] + list(selected) if columns else list(selected)
        writer.writerow(export_cols)

        # Data
        if df is not None:
            for _, row in df.iterrows():
                writer.writerow([row[c] for c in export_cols if c in df.columns])
        else:
            col_indices = [0] + [columns.index(c) for c in selected if c in columns]
            for row in rows:
                writer.writerow([row[i] for i in col_indices if i < len(row)])

        csv_text = buf.getvalue()

        import base64

        b64 = base64.b64encode(csv_text.encode("utf-8")).decode("ascii")
        await session.send_custom_message(
            "download_file",
            {"href": f"data:text/csv;base64,{b64}", "filename": "timeseries_export.csv"},
        )
        ui.notification_show("CSV exported", type="message", duration=4)

    return {
        "obs_data": obs_data,
    }


def _load_obs_file(path: Path) -> dict:
    """Load observation data from CSV or whitespace-delimited file."""
    from shyfem_ui.services.timeseries_loader import load_timeseries

    result = load_timeseries(path)
    return {
        "columns": result["columns"],
        "data": result["data"],
    }
