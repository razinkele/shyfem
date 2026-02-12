"""Job execution page - submit and monitor simulations.

Features:
- Submit jobs with tool selection, MPI options, working directory
- Live progress dashboard with real-time progress bars, timestep, ETA
- Multi-job sortable table with status badges
- Job dependency visualization
- Auto-refresh for active jobs
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.job_status import format_datetime, format_duration, get_status_badge, job_list_table
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.config import Config
from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobQueueFactory, JobSpec, JobStatus


@module.ui
def run_ui():
    """Job execution page UI."""
    return ui.page_fluid(
        ui.h3("Run Simulation"),
        ui.p("Submit and monitor SHYFEM simulation jobs.", class_="text-muted"),
        ui.row(
            # Left panel - Submit job
            ui.column(
                4,
                ui.div(
                    ui.h5("Submit New Job"),
                    ui.input_text(
                        "job_name",
                        "Job Name",
                        placeholder="my_simulation",
                    ),
                    ui.input_select(
                        "tool_select",
                        "Tool",
                        choices={
                            "shyfem": "shyfem (Simulation)",
                            "shypre": "shypre (Grid Prep)",
                            "shybas": "shybas (Basin Analysis)",
                            "shyparts": "shyparts (Partitioning)",
                            "shyelab": "shyelab (Post-process)",
                            "shyplot": "shyplot (Plotting)",
                        },
                    ),
                    ui.input_text(
                        "input_file",
                        "Input File",
                        placeholder="/path/to/input.str",
                    ),
                    ui.input_text(
                        "working_dir",
                        "Working Directory",
                        placeholder="/path/to/workdir",
                    ),
                    ui.hr(),
                    # MPI options (shown for shyfem)
                    ui.panel_conditional(
                        "input.tool_select === 'shyfem'",
                        ui.h6("MPI Options"),
                        ui.input_checkbox("mpi_enabled", "Enable MPI", value=False),
                        ui.panel_conditional(
                            "input.mpi_enabled",
                            ui.input_numeric(
                                "mpi_np",
                                "Number of Processes",
                                value=4,
                                min=2,
                                max=128,
                            ),
                        ),
                    ),
                    # Job dependency (optional)
                    ui.hr(),
                    ui.h6("Dependencies (optional)"),
                    ui.input_text(
                        "depends_on",
                        "Wait for Job ID",
                        placeholder="job-id-to-wait-for",
                    ),
                    ui.hr(),
                    ui.input_action_button(
                        "submit_btn",
                        "Submit Job",
                        class_="btn-primary w-100",
                    ),
                    class_="card p-3",
                ),
            ),
            # Right panel - Job monitoring
            ui.column(
                8,
                ui.navset_card_tab(
                    ui.nav_panel(
                        "Dashboard",
                        ui.output_ui("dashboard"),
                    ),
                    ui.nav_panel(
                        "Active Jobs",
                        ui.output_ui("active_jobs"),
                    ),
                    ui.nav_panel(
                        "Job History",
                        ui.output_ui("job_history"),
                    ),
                    ui.nav_panel(
                        "Job Timeline",
                        output_widget("timeline_chart"),
                    ),
                    ui.nav_panel(
                        "Selected Job",
                        ui.output_ui("selected_job_details"),
                    ),
                    ui.nav_panel(
                        "Log",
                        log_viewer_ui("job_log"),
                    ),
                ),
            ),
        ),
        # Auto-refresh timer
        ui.input_action_button(
            "refresh_btn",
            "Refresh",
            class_="btn-outline-secondary btn-sm mt-3",
        ),
    )


@module.server
def run_server(
    input,
    output,
    session,
    config: Config,
    job_queue: Optional[JobQueue] = None,
):
    """Job execution page server logic."""
    # Initialize job queue if not provided
    if job_queue is None:
        queue_mode = "celery" if config.use_celery else "local"
        job_queue = JobQueueFactory.create(
            mode=queue_mode,
            shyfem_dir=config.shyfem_dir,
            max_workers=config.max_workers,
            redis_url=config.redis_url if config.use_celery else None,
        )

    # State
    active_jobs_data = reactive.value([])
    all_jobs_data = reactive.value([])
    selected_job_id = reactive.value(None)
    selected_job = reactive.value(None)
    log_content = reactive.value("")

    # Initialize log viewer with auto-refresh callback
    async def _refresh_log():
        job = selected_job.get()
        if job is None:
            return
        try:
            stdout = await job_queue.get_output(job.id, "stdout", tail=500)
            stderr = await job_queue.get_output(job.id, "stderr", tail=100)
            log_content.set(f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}")
        except Exception as e:
            log_content.set(f"Error fetching log: {e}")

    log_viewer_server("job_log", log_content, on_refresh=lambda: None)

    # Refresh jobs periodically: poll every 2 seconds while there are active jobs
    @reactive.effect
    async def _auto_refresh():
        active = active_jobs_data.get()
        if active:
            reactive.invalidate_later(2)
        await _refresh_jobs()

    @reactive.effect
    @reactive.event(input.refresh_btn)
    async def _manual_refresh():
        await _refresh_jobs()

    async def _refresh_jobs():
        """Refresh job lists."""
        jobs = await job_queue.list_jobs(limit=50)
        _update_job_lists(jobs)

    def _update_job_lists(jobs: list[JobInfo]):
        # Apply any buffered progress updates from callbacks
        for job in jobs:
            if job.id in _latest_progress:
                job.progress, job.progress_message = _latest_progress[job.id]

        all_jobs_data.set(jobs)
        active = [j for j in jobs if j.is_active]
        active_jobs_data.set(active)

        # Update selected job if exists
        if selected_job_id.get():
            for job in jobs:
                if job.id == selected_job_id.get():
                    selected_job.set(job)
                    break

    @reactive.effect
    @reactive.event(input.submit_btn)
    async def _submit_job():
        name = input.job_name() or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tool = input.tool_select()
        input_file = input.input_file()
        working_dir = input.working_dir()

        if not input_file:
            ui.notification_show("Input file is required", type="error")
            return

        try:
            validated_input = config.validate_path(input_file, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        if not working_dir:
            working_dir = str(validated_input.parent)

        try:
            validated_workdir = config.validate_path(working_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return

        # Build job spec
        args = [str(validated_input)]
        metadata = {}

        # Check dependency
        depends_on = input.depends_on()
        if depends_on:
            metadata["depends_on"] = depends_on

        spec = JobSpec(
            name=name,
            tool_name=tool,
            args=args,
            working_dir=validated_workdir,
            mpi_enabled=input.mpi_enabled() if tool == "shyfem" else False,
            mpi_np=input.mpi_np() if (tool == "shyfem" and input.mpi_enabled()) else 1,
            metadata=metadata,
        )

        try:
            job_id = await job_queue.submit(spec)
            ui.notification_show(f"Job submitted: {job_id}", type="message")
            selected_job_id.set(job_id)
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Failed to submit job: {e}", type="error")

    @render.ui
    def dashboard():
        """Live progress dashboard for all active jobs."""
        active = active_jobs_data.get()
        all_jobs = all_jobs_data.get()

        # Summary stats
        total = len(all_jobs)
        running = sum(1 for j in all_jobs if j.status == JobStatus.RUNNING)
        queued = sum(1 for j in all_jobs if j.status in (JobStatus.PENDING, JobStatus.QUEUED))
        completed = sum(1 for j in all_jobs if j.status == JobStatus.COMPLETED)
        failed = sum(1 for j in all_jobs if j.status == JobStatus.FAILED)

        stat_cards = ui.div(
            _stat_card("Running", str(running), "bg-primary"),
            _stat_card("Queued", str(queued), "bg-info"),
            _stat_card("Completed", str(completed), "bg-success"),
            _stat_card("Failed", str(failed), "bg-danger"),
            class_="d-flex gap-2 mb-3",
        )

        if not active:
            return ui.div(
                stat_cards,
                ui.p("No active jobs. Submit a new job to get started.", class_="text-muted text-center mt-3"),
            )

        # Build progress cards for each active job
        progress_cards = []
        for job in active:
            progress_pct = int(job.progress * 100)
            eta_str = _estimate_eta(job)

            progress_cards.append(
                ui.div(
                    ui.div(
                        ui.div(
                            ui.span(job.name, class_="fw-bold"),
                            ui.span(f"({job.tool_name})", class_="text-muted small ms-2"),
                            get_status_badge(job.status),
                            class_="d-flex align-items-center gap-2",
                        ),
                        ui.div(
                            ui.div(
                                ui.div(
                                    f"{progress_pct}%",
                                    class_="progress-bar progress-bar-striped progress-bar-animated"
                                    + (" bg-success" if progress_pct > 90 else ""),
                                    style=f"width: {max(progress_pct, 2)}%",
                                    role="progressbar",
                                ),
                                class_="progress mt-2",
                                style="height: 20px;",
                            ),
                        ),
                        ui.div(
                            ui.span(
                                job.progress_message or "Starting...",
                                class_="small text-muted",
                            ),
                            ui.span(f"ETA: {eta_str}", class_="small text-muted ms-auto")
                            if eta_str else None,
                            class_="d-flex justify-content-between mt-1",
                        ),
                        ui.div(
                            ui.span(f"Started: {format_datetime(job.started_at)}", class_="small text-muted me-3"),
                            ui.span(f"ID: {job.id[:8]}...", class_="small text-muted"),
                            class_="mt-1",
                        ),
                        class_="card-body py-2",
                    ),
                    class_="card mb-2",
                    style="cursor: pointer;",
                )
            )

        return ui.div(
            stat_cards,
            *progress_cards,
        )

    @render.ui
    def active_jobs():
        jobs = active_jobs_data.get()
        if not jobs:
            return ui.div(
                ui.p("No active jobs", class_="text-muted text-center"),
                ui.p("Submit a new job to get started.", class_="text-center"),
            )

        # Build job selection dropdown + cards
        job_choices = {job.id: f"{job.name} ({job.tool_name})" for job in jobs}

        job_cards = []
        for job in jobs:
            progress_pct = int(job.progress * 100)
            is_selected = job.id == selected_job_id.get()

            job_cards.append(
                ui.div(
                    ui.div(
                        ui.div(
                            ui.span(job.name, class_="fw-bold"),
                            get_status_badge(job.status),
                            class_="d-flex justify-content-between",
                        ),
                        ui.div(
                            ui.div(
                                class_="progress-bar progress-bar-striped progress-bar-animated",
                                style=f"width: {progress_pct}%",
                                role="progressbar",
                            ),
                            class_="progress mt-2",
                            style="height: 10px;",
                        ),
                        ui.div(
                            ui.span(f"{progress_pct}%", class_="small text-muted"),
                            ui.span(job.progress_message or "", class_="small text-muted ms-2"),
                            class_="mt-1",
                        ),
                        class_="card-body",
                    ),
                    class_=f"card mb-2 {'border-primary' if is_selected else ''}",
                )
            )

        return ui.div(
            ui.div(
                ui.input_select(
                    "active_job_select",
                    "Select Job",
                    choices=job_choices,
                    selected=selected_job_id.get(),
                    width="100%",
                ),
                ui.div(
                    ui.input_action_button(
                        "view_active_job_btn",
                        "View Details",
                        class_="btn-sm btn-outline-primary me-2",
                    ),
                    ui.input_action_button(
                        "cancel_active_job_btn",
                        "Cancel",
                        class_="btn-sm btn-outline-danger",
                    ),
                    class_="mt-2 mb-3",
                ),
            ),
            *job_cards,
        )

    @reactive.effect
    @reactive.event(input.view_active_job_btn)
    async def _view_active_job():
        job_id = input.active_job_select()
        if job_id:
            selected_job_id.set(job_id)
            await _refresh_jobs()

    @reactive.effect
    @reactive.event(input.cancel_active_job_btn)
    async def _cancel_active_job():
        job_id = input.active_job_select()
        if not job_id:
            return
        try:
            success = await job_queue.cancel(job_id)
            if success:
                ui.notification_show("Job cancelled", type="message")
            else:
                ui.notification_show("Failed to cancel job", type="error")
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Error: {e}", type="error")

    @render.ui
    def job_history():
        jobs = all_jobs_data.get()
        completed = [j for j in jobs if not j.is_active]

        if not completed:
            return ui.p("No completed jobs", class_="text-muted text-center")

        return job_list_table(completed)

    @render_widget
    def timeline_chart():
        """Plotly timeline/Gantt chart of job execution."""
        jobs = all_jobs_data.get()
        if not jobs:
            fig = go.Figure()
            fig.add_annotation(
                text="No jobs to display",
                xref="paper", yref="paper", x=0.5, y=0.5,
                showarrow=False, font_size=16, font_color="gray",
            )
            fig.update_layout(height=400)
            return fig

        # Build Gantt-style chart
        status_colors = {
            JobStatus.PENDING: "#6c757d",
            JobStatus.QUEUED: "#17a2b8",
            JobStatus.RUNNING: "#0d6efd",
            JobStatus.COMPLETED: "#198754",
            JobStatus.FAILED: "#dc3545",
            JobStatus.CANCELLED: "#ffc107",
        }

        fig = go.Figure()
        for i, job in enumerate(reversed(jobs[:20])):  # Show last 20
            start = job.started_at or job.created_at
            end = job.completed_at or datetime.now()
            color = status_colors.get(job.status, "#6c757d")

            fig.add_trace(go.Bar(
                x=[(end - start).total_seconds()],
                y=[job.name],
                orientation="h",
                marker_color=color,
                text=f"{job.tool_name} - {job.status.value}",
                textposition="inside",
                hovertemplate=(
                    f"<b>{job.name}</b><br>"
                    f"Tool: {job.tool_name}<br>"
                    f"Status: {job.status.value}<br>"
                    f"Duration: {format_duration(job.duration)}<br>"
                    f"<extra></extra>"
                ),
                showlegend=False,
            ))

        fig.update_layout(
            title="Job Timeline (last 20 jobs)",
            xaxis_title="Duration (seconds)",
            yaxis_title="",
            height=max(300, len(jobs[:20]) * 35 + 100),
            barmode="stack",
            showlegend=False,
        )
        return fig

    @render.ui
    def selected_job_details():
        job = selected_job.get()
        if job is None:
            return ui.p("Select a job to view details", class_="text-muted text-center")

        eta_str = _estimate_eta(job)

        details = [
            ("Job ID", ui.code(job.id)),
            ("Name", job.name),
            ("Tool", ui.code(job.tool_name)),
            ("Status", get_status_badge(job.status)),
            ("Progress", f"{int(job.progress * 100)}%"),
            ("Working Dir", ui.code(job.working_dir, class_="small")),
            ("Created", format_datetime(job.created_at)),
        ]

        if job.started_at:
            details.append(("Started", format_datetime(job.started_at)))

        if eta_str:
            details.append(("ETA", eta_str))

        if job.completed_at:
            details.append(("Completed", format_datetime(job.completed_at)))
            details.append(("Duration", format_duration(job.duration)))

        if job.return_code is not None:
            details.append(("Return Code", str(job.return_code)))

        # Dependency info
        depends_on = job.metadata.get("depends_on")
        if depends_on:
            details.append(("Depends On", ui.code(depends_on)))

        detail_rows = [
            ui.div(
                ui.span(label + ":", class_="fw-bold me-2", style="width: 120px;"),
                value if isinstance(value, ui.Tag) else ui.span(str(value)),
                class_="d-flex mb-1",
            )
            for label, value in details
        ]

        # Error message
        error_section = None
        if job.error_message:
            error_section = ui.div(
                ui.strong("Error:"),
                ui.pre(job.error_message, class_="text-danger small mt-1 p-2 bg-light"),
                class_="mt-3",
            )

        # Output files
        files_section = None
        if job.output_files:
            file_items = [
                ui.li(ui.code(f, class_="small"))
                for f in job.output_files
            ]
            files_section = ui.div(
                ui.strong("Output Files:"),
                ui.tags.ul(*file_items, class_="mb-0 mt-1"),
                class_="mt-3",
            )

        # Actions
        actions = ui.div(
            ui.input_action_button(
                "view_log_btn",
                "View Log",
                class_="btn-sm btn-outline-primary me-2",
            ),
            class_="mt-3",
        )

        if job.is_active:
            actions = ui.div(
                ui.input_action_button(
                    "view_log_btn",
                    "View Log",
                    class_="btn-sm btn-outline-primary me-2",
                ),
                ui.input_action_button(
                    "cancel_selected_btn",
                    "Cancel Job",
                    class_="btn-sm btn-outline-danger",
                ),
                class_="mt-3",
            )

        return ui.div(
            *detail_rows,
            error_section,
            files_section,
            actions,
        )

    @reactive.effect
    @reactive.event(input.view_log_btn)
    async def _view_job_log():
        job = selected_job.get()
        if job is None:
            return

        try:
            stdout = await job_queue.get_output(job.id, "stdout", tail=500)
            stderr = await job_queue.get_output(job.id, "stderr", tail=100)

            log_text = f"=== STDOUT ===\n{stdout}\n\n=== STDERR ===\n{stderr}"
            log_content.set(log_text)
        except Exception as e:
            log_content.set(f"Error fetching log: {e}")

    @reactive.effect
    @reactive.event(input.cancel_selected_btn)
    async def _cancel_selected_job():
        job = selected_job.get()
        if job is None or not job.is_active:
            return

        try:
            success = await job_queue.cancel(job.id)
            if success:
                ui.notification_show("Job cancelled", type="message")
            else:
                ui.notification_show("Failed to cancel job", type="error")
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Error: {e}", type="error")

    # Latest progress data from callbacks, polled by _auto_refresh
    _latest_progress: dict[str, tuple[float, str]] = {}

    def on_progress(job_id: str, progress: float, message: str):
        _latest_progress[job_id] = (progress, message)

    job_queue.set_progress_callback(on_progress)

    return {
        "job_queue": job_queue,
        "selected_job": selected_job,
    }


def _stat_card(label: str, value: str, bg_class: str) -> ui.Tag:
    """Create a small stat card."""
    return ui.div(
        ui.span(value, class_="fs-4 fw-bold"),
        ui.br(),
        ui.span(label, class_="small"),
        class_=f"text-center text-white px-3 py-2 rounded {bg_class}",
        style="min-width: 80px;",
    )


def _estimate_eta(job: JobInfo) -> str:
    """Estimate time remaining for a running job."""
    if job.status != JobStatus.RUNNING or not job.started_at:
        return ""
    if job.progress <= 0:
        return "calculating..."

    elapsed = (datetime.now() - job.started_at).total_seconds()
    if elapsed <= 0:
        return ""

    estimated_total = elapsed / job.progress
    remaining = estimated_total - elapsed

    if remaining < 60:
        return f"{int(remaining)}s"
    elif remaining < 3600:
        return f"{int(remaining // 60)}m {int(remaining % 60)}s"
    else:
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return f"{h}h {m}m"
