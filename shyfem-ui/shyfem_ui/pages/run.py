"""Job execution page - submit and monitor simulations."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

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
                        "Active Jobs",
                        ui.output_ui("active_jobs"),
                    ),
                    ui.nav_panel(
                        "Job History",
                        ui.output_ui("job_history"),
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

    # Initialize log viewer
    log_viewer_server("job_log", log_content)

    # Refresh jobs periodically
    @reactive.effect
    async def _initial_refresh():
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

        spec = JobSpec(
            name=name,
            tool_name=tool,
            args=args,
            working_dir=validated_workdir,
            mpi_enabled=input.mpi_enabled() if tool == "shyfem" else False,
            mpi_np=input.mpi_np() if (tool == "shyfem" and input.mpi_enabled()) else 1,
        )

        try:
            job_id = await job_queue.submit(spec)
            ui.notification_show(f"Job submitted: {job_id}", type="message")
            selected_job_id.set(job_id)
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Failed to submit job: {e}", type="error")

    @render.ui
    def active_jobs():
        jobs = active_jobs_data.get()
        if not jobs:
            return ui.div(
                ui.p("No active jobs", class_="text-muted text-center"),
                ui.p("Submit a new job to get started.", class_="text-center"),
            )

        job_cards = []
        for job in jobs:
            progress_pct = int(job.progress * 100)

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
                        ui.input_action_button(
                            f"view_job_{job.id}",
                            "View Details",
                            class_="btn-sm btn-outline-primary mt-2 me-2",
                        ),
                        ui.input_action_button(
                            f"cancel_job_{job.id}",
                            "Cancel",
                            class_="btn-sm btn-outline-danger mt-2",
                        ),
                        class_="card-body",
                    ),
                    class_="card mb-2",
                )
            )

        return ui.div(*job_cards)

    @render.ui
    def job_history():
        jobs = all_jobs_data.get()
        completed = [j for j in jobs if not j.is_active]

        if not completed:
            return ui.p("No completed jobs", class_="text-muted text-center")

        return job_list_table(completed)

    @render.ui
    def selected_job_details():
        job = selected_job.get()
        if job is None:
            return ui.p("Select a job to view details", class_="text-muted text-center")

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

        if job.completed_at:
            details.append(("Completed", format_datetime(job.completed_at)))
            details.append(("Duration", format_duration(job.duration)))

        if job.return_code is not None:
            details.append(("Return Code", str(job.return_code)))

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
            stdout = await job_queue.get_output(job.id, "stdout", tail=200)
            stderr = await job_queue.get_output(job.id, "stderr", tail=50)

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

    # Set progress callback
    def on_progress(job_id: str, progress: float, message: str):
        if job_id == selected_job_id.get():
            job = selected_job.get()
            if job:
                job.progress = progress
                job.progress_message = message
                selected_job.set(job)

    job_queue.set_progress_callback(on_progress)

    return {
        "job_queue": job_queue,
        "selected_job": selected_job,
    }
