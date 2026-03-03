"""Job comparison page - compare 2+ simulation results.

Features:
- Compare runtime statistics across jobs
- Parameter diff table between simulations
- Overlaid time series plots
- Output file comparison
"""

import logging
from pathlib import Path

import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.job_status import format_datetime, format_duration
from shyfem_ui.config import Config
from shyfem_ui.services.job_queue import JobQueue, JobQueueFactory, JobStatus
from shyfem_ui.services.parser_str import StrParser
from shyfem_ui.services.report import generate_comparison_report

logger = logging.getLogger(__name__)

_DIFF_TYPE_CLASSES = {
    "only_a": "table-danger",
    "only_b": "table-success",
    "changed": "table-warning",
}


@module.ui
def compare_ui():
    """Job comparison page UI."""
    return ui.div(
        ui.h3("Compare Simulations"),
        ui.p("Compare parameters, runtime, and results across simulations.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                ui.h5("Select Jobs"),
                ui.output_ui("job_selector"),
                ui.hr(),
                ui.h5("Compare STR Files"),
                ui.output_ui("str_file_inputs"),
                ui.input_action_button(
                    "compare_str_btn",
                    "Compare Parameters",
                    class_="btn-outline-primary btn-sm w-100 mb-2",
                ),
                ui.hr(),
                ui.h5("Compare Time Series"),
                ui.input_text(
                    "ts_file_a",
                    "Time Series A",
                    placeholder="/path/to/result_a.ts",
                ),
                ui.input_text(
                    "ts_file_b",
                    "Time Series B",
                    placeholder="/path/to/result_b.ts",
                ),
                ui.input_action_button(
                    "compare_ts_btn",
                    "Compare Time Series",
                    class_="btn-outline-primary btn-sm w-100",
                ),
                ui.hr(),
                ui.h5("Report"),
                ui.input_action_button(
                    "generate_report_btn",
                    "Generate Comparison Report",
                    class_="btn-outline-success btn-sm w-100",
                ),
                width=300,
            ),
            ui.navset_card_tab(
                ui.nav_panel(
                    "Runtime Stats",
                    ui.output_ui("runtime_comparison"),
                ),
                ui.nav_panel(
                    "Parameter Diff",
                    ui.output_ui("param_diff"),
                ),
                ui.nav_panel(
                    "Time Series",
                    output_widget("ts_comparison_plot"),
                ),
                ui.nav_panel(
                    "Summary",
                    ui.output_ui("comparison_summary"),
                ),
            ),
        ),
    )


@module.server
def compare_server(
    input,
    output,
    session,
    config: Config,
    job_queue: JobQueue | None = None,
    active_project=None,
):
    """Job comparison page server logic."""
    if job_queue is None:
        queue_mode = "celery" if config.use_celery else "local"
        job_queue = JobQueueFactory.create(
            mode=queue_mode,
            shyfem_dir=config.shyfem_dir,
            max_workers=config.max_workers,
            redis_url=config.redis_url if config.use_celery else None,
        )

    # State
    all_jobs = reactive.value([])
    selected_jobs = reactive.value([])
    param_diff_data = reactive.value(None)
    ts_data = reactive.value(None)

    # Load jobs on init
    @reactive.effect
    async def _load_jobs():
        try:
            jobs = await job_queue.list_jobs(limit=100)
            all_jobs.set(jobs)
        except Exception as e:
            ui.notification_show(f"Failed to load jobs: {e}", type="error", duration=6)

    @render.ui
    def job_selector():
        jobs = all_jobs.get()
        completed = [j for j in jobs if j.status == JobStatus.COMPLETED]
        if not completed:
            return ui.p("No completed jobs available for comparison.", class_="text-muted")

        choices = {j.id: f"{j.name} ({j.tool_name})" for j in completed}
        return ui.div(
            ui.input_select(
                "job_a",
                "Job A",
                choices=choices,
            ),
            ui.input_select(
                "job_b",
                "Job B",
                choices=choices,
            ),
            ui.input_action_button(
                "compare_jobs_btn",
                "Compare Jobs",
                class_="btn-primary btn-sm w-100 mt-2",
            ),
        )

    @render.ui
    def str_file_inputs():
        proj = active_project.get() if active_project is not None else None
        choices = _extract_str_choices(proj)
        if choices:
            select_choices = {"": "Select..."} | choices
            return ui.div(
                ui.input_select(
                    "str_file_a",
                    "STR File A",
                    choices=select_choices,
                ),
                ui.input_select(
                    "str_file_b",
                    "STR File B",
                    choices=select_choices,
                ),
            )
        return ui.div(
            ui.input_text(
                "str_file_a",
                "STR File A",
                placeholder="/path/to/file_a.str",
            ),
            ui.input_text(
                "str_file_b",
                "STR File B",
                placeholder="/path/to/file_b.str",
            ),
        )

    @reactive.effect
    @reactive.event(input.compare_jobs_btn)
    async def _compare_jobs():
        try:
            job_a_id = input.job_a()
            job_b_id = input.job_b()
        except Exception:
            logger.debug("Job ID inputs unavailable, skipping comparison")
            return

        if not job_a_id or not job_b_id:
            return

        jobs = all_jobs.get()
        pair = []
        for j in jobs:
            if j.id in (job_a_id, job_b_id):
                pair.append(j)
        selected_jobs.set(pair)

    @reactive.effect
    @reactive.event(input.compare_str_btn)
    def _compare_str_files():
        path_a = input.str_file_a()
        path_b = input.str_file_b()
        if not path_a or not path_b:
            ui.notification_show("Both STR file paths are required", type="warning")
            return

        try:
            file_a = config.validate_path(path_a, must_exist=True)
            file_b = config.validate_path(path_b, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        str_a = StrParser.parse_file(file_a)
        str_b = StrParser.parse_file(file_b)

        diff = _compute_param_diff(str_a, str_b, str(file_a.name), str(file_b.name))
        param_diff_data.set(diff)

    @reactive.effect
    @reactive.event(input.compare_ts_btn)
    def _compare_ts_files():
        path_a = input.ts_file_a()
        path_b = input.ts_file_b()
        if not path_a or not path_b:
            ui.notification_show("Both time series paths are required", type="warning")
            return
        try:
            file_a = config.validate_path(path_a, must_exist=True)
            file_b = config.validate_path(path_b, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        ts_data.set(
            {
                "a": _load_ts(file_a),
                "b": _load_ts(file_b),
                "name_a": file_a.name,
                "name_b": file_b.name,
            }
        )

    @render.ui
    def runtime_comparison():
        jobs = selected_jobs.get()
        if len(jobs) < 2:
            return ui.p(
                "Select two jobs to compare runtime statistics.",
                class_="text-muted text-center mt-3",
            )

        job_a, job_b = jobs[0], jobs[1]

        rows = []
        metrics = [
            ("Name", job_a.name, job_b.name),
            ("Tool", job_a.tool_name, job_b.tool_name),
            ("Status", job_a.status.value, job_b.status.value),
            ("Duration", format_duration(job_a.duration), format_duration(job_b.duration)),
            ("Created", format_datetime(job_a.created_at), format_datetime(job_b.created_at)),
            ("Return Code", str(job_a.return_code), str(job_b.return_code)),
            ("Output Files", str(len(job_a.output_files)), str(len(job_b.output_files))),
        ]

        # MPI info
        mpi_a = job_a.metadata.get("mpi_np", "-")
        mpi_b = job_b.metadata.get("mpi_np", "-")
        metrics.append(("MPI Processes", str(mpi_a), str(mpi_b)))

        for label, val_a, val_b in metrics:
            diff_class = ""
            if val_a != val_b:
                diff_class = "table-warning"
            rows.append(
                ui.tags.tr(
                    ui.tags.th(label),
                    ui.tags.td(val_a),
                    ui.tags.td(val_b),
                    class_=diff_class,
                )
            )

        return ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Metric"),
                    ui.tags.th(f"Job A: {job_a.name}"),
                    ui.tags.th(f"Job B: {job_b.name}"),
                ),
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-bordered",
        )

    @render.ui
    def param_diff():
        diff = param_diff_data.get()
        if diff is None:
            return ui.p(
                "Load two STR files to see parameter differences.",
                class_="text-muted text-center mt-3",
            )

        if not diff["rows"]:
            return ui.div(
                ui.p("No parameter differences found.", class_="text-success text-center mt-3"),
                ui.p(
                    "Both files have identical parameters in compared sections.",
                    class_="text-muted small text-center",
                ),
            )

        rows = []
        for row in diff["rows"]:
            diff_class = _DIFF_TYPE_CLASSES.get(row.get("diff_type", ""), "")
            rows.append(
                ui.tags.tr(
                    ui.tags.td(ui.code(row["section"])),
                    ui.tags.td(ui.code(row["param"])),
                    ui.tags.td(row["value_a"]),
                    ui.tags.td(row["value_b"]),
                    class_=diff_class,
                )
            )

        return ui.div(
            ui.p(f"Comparing: {diff['name_a']} vs {diff['name_b']}", class_="small text-muted"),
            ui.p(f"{diff['diff_count']} differences found", class_="fw-bold"),
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Section"),
                        ui.tags.th("Parameter"),
                        ui.tags.th(diff["name_a"]),
                        ui.tags.th(diff["name_b"]),
                    ),
                ),
                ui.tags.tbody(*rows),
                class_="table table-sm table-bordered",
            ),
        )

    @render_widget
    def ts_comparison_plot():
        data = ts_data.get()
        if data is None:
            fig = go.Figure()
            fig.add_annotation(
                text="Load two time series files to compare",
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

        fig = go.Figure()
        for dataset, label, dash in [
            (data["a"], data["name_a"], None),
            (data["b"], data["name_b"], "dash"),
        ]:
            if not dataset:
                continue
            x = [row[0] for row in dataset]
            for col_idx in range(1, len(dataset[0]) if dataset else 0):
                y = [row[col_idx] for row in dataset]
                fig.add_trace(
                    go.Scattergl(
                        x=x,
                        y=y,
                        mode="lines",
                        line=dict(dash=dash),
                        name=f"{label}: col{col_idx}",
                    )
                )

        fig.update_layout(
            title="Time Series Comparison",
            xaxis_title="Time",
            yaxis_title="Value",
            height=500,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        fig.update_xaxes(rangeslider_visible=True)
        return fig

    @render.ui
    def comparison_summary():
        jobs = selected_jobs.get()
        diff = param_diff_data.get()

        parts = []
        if len(jobs) >= 2:
            job_a, job_b = jobs[0], jobs[1]
            parts.append(ui.h5("Runtime Comparison"))
            # Speed comparison
            if job_a.duration and job_b.duration:
                ratio = job_a.duration / job_b.duration if job_b.duration > 0 else 0
                if ratio > 1:
                    parts.append(
                        ui.p(
                            f"Job B ({job_b.name}) was {ratio:.1f}x faster than Job A ({job_a.name})",
                            class_="text-success",
                        )
                    )
                elif ratio < 1 and ratio > 0:
                    parts.append(
                        ui.p(
                            f"Job A ({job_a.name}) was {1/ratio:.1f}x faster than Job B ({job_b.name})",
                            class_="text-success",
                        )
                    )
                else:
                    parts.append(ui.p("Both jobs had similar runtime"))

        if diff:
            parts.append(ui.hr())
            parts.append(ui.h5("Parameter Differences"))
            parts.append(
                ui.p(f"{diff['diff_count']} parameters differ between the two configurations.")
            )

        if not parts:
            return ui.p("Run comparisons to see a summary.", class_="text-muted text-center")

        return ui.div(*parts)

    @reactive.effect
    @reactive.event(input.generate_report_btn)
    def _generate_comparison_report():
        jobs = selected_jobs.get()
        if len(jobs) < 2:
            ui.notification_show(
                "Select and compare at least two jobs first",
                type="warning",
            )
            return

        try:
            output_dir = Path(config.work_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"comparison_{jobs[0].id[:8]}_{jobs[1].id[:8]}.html"

            report_path = generate_comparison_report(
                jobs=jobs,
                title=f"Comparison: {jobs[0].name} vs {jobs[1].name}",
                output_path=output_path,
            )
            ui.notification_show(
                f"Report generated: {report_path}",
                type="message",
                duration=8,
            )
        except Exception as e:
            ui.notification_show(f"Report generation failed: {e}", type="error", duration=6)

    return {}


def _extract_str_choices(project_ctx: dict | None) -> dict[str, str]:
    """Extract STR file choices from a project context dict.

    Returns ``{absolute_path: human_label}`` for every STR file found in the
    project's simulations and uploaded project files.  Simulation entries take
    priority when the same path appears in both sources.  Returns an empty
    dict when *project_ctx* is ``None`` or contains no STR files.
    """
    if project_ctx is None:
        return {}

    choices: dict[str, str] = {}

    # 1. Project files with file_type == "str"
    work_dir = project_ctx.get("work_dir", "")
    for f in project_ctx.get("files", []):
        if f.get("file_type") == "str":
            path = str(Path(work_dir) / f["rel_path"])
            choices[path] = f["filename"]

    # 2. Simulations (overwrite any duplicate paths from step 1)
    for sim in project_ctx.get("simulations", []):
        str_file = sim.get("str_file")
        if str_file:
            label = f"{sim['name']} ({Path(str_file).name})"
            choices[str_file] = label

    return choices


def _compute_param_diff(str_a, str_b, name_a: str, name_b: str) -> dict:
    """Compute parameter differences between two parsed STR files."""
    rows = []
    all_sections = set(str_a.sections.keys()) | set(str_b.sections.keys())

    for section_name in sorted(all_sections):
        sec_a = str_a.sections.get(section_name)
        sec_b = str_b.sections.get(section_name)
        params_a = sec_a.parameters if sec_a else {}
        params_b = sec_b.parameters if sec_b else {}
        all_params = set(params_a.keys()) | set(params_b.keys())

        for param in sorted(all_params):
            val_a = str(params_a.get(param, "-"))
            val_b = str(params_b.get(param, "-"))
            if val_a != val_b:
                if val_b == "-":
                    diff_type = "only_a"
                elif val_a == "-":
                    diff_type = "only_b"
                else:
                    diff_type = "changed"
                rows.append(
                    {
                        "section": section_name,
                        "param": param,
                        "value_a": val_a,
                        "value_b": val_b,
                        "diff_type": diff_type,
                    }
                )

    return {
        "name_a": name_a,
        "name_b": name_b,
        "rows": rows,
        "diff_count": len(rows),
    }


def _load_ts(path: Path) -> list[list[float]]:
    """Load time series data as list of float rows."""
    data = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            try:
                data.append([float(p) for p in parts])
            except ValueError:
                logger.debug("Skipping non-numeric line in time series")
                continue
    return data
