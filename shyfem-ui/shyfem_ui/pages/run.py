"""Job execution page - submit and monitor simulations.

Features:
- Submit jobs with tool selection, MPI options, working directory
- Live progress dashboard with real-time progress bars, timestep, ETA
- Multi-job sortable table with status badges
- Job dependency visualization
- Auto-refresh for active jobs
"""

import logging
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.job_status import (
    format_datetime,
    format_duration,
    get_status_badge,
    job_list_table,
)
from shyfem_ui.components.log_viewer import log_viewer_server, log_viewer_ui
from shyfem_ui.components.sample_data import sample_data_card_ui
from shyfem_ui.config import Config
from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobQueueFactory, JobSpec, JobStatus
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.parser_str import StrParser
from shyfem_ui.services.str_validator import validate_str
from shyfem_ui.services.report import generate_job_report
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
from shyfem_ui.services.workflow import WORKFLOW_TEMPLATES, WorkflowEngine, WorkflowStatus

logger = logging.getLogger(__name__)


def _preflight_validate(simulation_id: int | None) -> list[str]:
    """Run pre-flight file validation for a simulation.

    Returns list of warning strings. Empty = all OK.
    Returns empty list for None or invalid simulation IDs (non-blocking).
    """
    if simulation_id is None:
        return []
    try:
        from shyfem_ui.services.file_service import FileService

        return FileService.validate_simulation_files(simulation_id)
    except (ValueError, Exception):
        return []


def _get_job_metadata(session_id: str, user_id: int | None = None) -> dict:
    """Build job metadata dict with session_id and optional user_id."""
    meta = {"session_id": session_id}
    if user_id is not None:
        meta["user_id"] = user_id
    return meta


def get_solver_recommendation(num_nodes: int | None, threshold: int) -> dict[str, str | None]:
    """Return solver recommendation based on mesh node count.

    Returns dict with 'solver' ('sparskit'/'petsc'/None) and 'hint' (display text).
    """
    if num_nodes is None:
        return {
            "solver": None,
            "hint": "Could not detect mesh size — select solver manually",
        }
    if num_nodes >= threshold:
        return {
            "solver": "petsc",
            "hint": (
                f"Mesh has {num_nodes:,} nodes. "
                f"Recommended: Iterative Solver (PETSc) — scales better for large meshes"
            ),
        }
    return {
        "solver": "sparskit",
        "hint": (
            f"Mesh has {num_nodes:,} nodes. "
            f"Recommended: Direct Solver (SPARSKIT) — fastest for small/medium meshes"
        ),
    }


def detect_mesh_node_count(str_file: Path | str, working_dir: Path | str) -> int | None:
    """Detect mesh node count from the grid file referenced in a STR file.

    The STR $title section's 3rd non-empty line is the basin name (e.g. 'GRID/MM_coarse').
    The grid file is {basnam}.grd relative to working_dir.
    Returns node count or None if detection fails.
    """
    str_path = Path(str_file)
    work_path = Path(working_dir)

    if not str_path.exists():
        return None

    try:
        content = str_path.read_text()
        parsed = StrParser.parse(content)
    except Exception:
        logger.debug("Failed to parse STR file %s", str_path, exc_info=True)
        return None

    title_sec = parsed.sections.get("title")
    if title_sec is None or len(title_sec.raw_lines) < 3:
        return None

    # 3rd non-empty, non-comment line in $title is the basin name
    lines = [
        ln.strip()
        for ln in title_sec.raw_lines
        if ln.strip() and not ln.strip().startswith(("#", "!"))
    ]
    if len(lines) < 3:
        return None
    basnam = lines[2]

    # Try .grd then .bas extension
    for ext in (".grd", ".bas"):
        grid_path = work_path / f"{basnam}{ext}"
        if grid_path.exists():
            try:
                grd = GrdParser.parse_file(grid_path)
                return grd.num_nodes
            except Exception:
                logger.debug("Failed to parse grid file %s", grid_path, exc_info=True)
                continue

    return None


@module.ui
def run_ui() -> ui.Tag:
    """Job execution page UI."""
    return ui.div(
        ui.h3("Run Simulation"),
        ui.p("Submit and monitor SHYFEM simulation jobs.", class_="text-muted"),
        sample_data_card_ui("run"),
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
                            "exgrd": "exgrd (Grid Extraction)",
                            "shyadj": "shyadj (Mesh Adjustment)",
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
                    # MPI + Solver options (rendered server-side for module compatibility)
                    ui.output_ui("shyfem_options"),
                    # Restart options (shyfem only)
                    ui.output_ui("restart_section"),
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
                    ui.nav_panel(
                        "Workflows",
                        ui.div(
                            ui.h5("Workflow Templates"),
                            ui.p(
                                "Chain multiple SHYFEM tools into automated pipelines.",
                                class_="text-muted small",
                            ),
                            ui.div(
                                ui.div(
                                    ui.input_select(
                                        "wf_template",
                                        "Template",
                                        choices={
                                            k: v["name"] for k, v in WORKFLOW_TEMPLATES.items()
                                        },
                                    ),
                                    class_="col-6",
                                ),
                                ui.div(
                                    ui.input_text(
                                        "wf_name",
                                        "Workflow Name",
                                        placeholder="my_workflow",
                                    ),
                                    class_="col-6",
                                ),
                                class_="row mb-2",
                            ),
                            ui.output_ui("wf_template_info"),
                            ui.hr(),
                            ui.h6("Parameters"),
                            ui.div(
                                ui.div(
                                    ui.input_text(
                                        "wf_input_str",
                                        "Input STR File",
                                        placeholder="/path/to/input.str",
                                    ),
                                    class_="col-6",
                                ),
                                ui.div(
                                    ui.input_text(
                                        "wf_input_grd",
                                        "Input GRD File",
                                        placeholder="/path/to/input.grd",
                                    ),
                                    class_="col-6",
                                ),
                                class_="row",
                            ),
                            ui.div(
                                ui.div(
                                    ui.input_text(
                                        "wf_working_dir",
                                        "Working Directory",
                                        placeholder="/path/to/workdir",
                                    ),
                                    class_="col-6",
                                ),
                                ui.div(
                                    ui.input_numeric(
                                        "wf_mpi_np",
                                        "MPI Processes",
                                        value=4,
                                        min=1,
                                        max=128,
                                    ),
                                    class_="col-6",
                                ),
                                class_="row",
                            ),
                            ui.input_action_button(
                                "wf_launch_btn",
                                "Launch Workflow",
                                class_="btn-primary mt-2",
                            ),
                            ui.hr(),
                            ui.output_ui("wf_progress"),
                            ui.hr(),
                            ui.h6("Workflow History"),
                            ui.output_ui("wf_history"),
                            class_="p-2",
                        ),
                    ),
                ),
            ),
        ),
        # Auto-refresh timer
        ui.output_ui("run_show_all_toggle_ui"),
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
    job_queue: JobQueue | None = None,
    active_project=None,
    tutorial_context=None,
    user_role=None,
) -> None:
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

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        ui.update_text("working_dir", value=proj["work_dir"])
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                ui.update_text("input_file", value=str(Path(proj["work_dir"]) / sim["str_file"]))

    # Auto-fill from tutorial navigation
    @reactive.effect
    def _on_tutorial_context():
        if tutorial_context is None:
            return
        ctx = tutorial_context.get()
        if ctx is None or ctx.get("target_tab") != "Run":
            return
        ui.update_text(
            "input_file",
            value=str(Path(ctx["work_dir"]) / ctx["str_file"]),
        )
        ui.update_text("working_dir", value=ctx["work_dir"])
        ui.update_select("tool_select", selected="shyfem")
        tutorial_context.set(None)

    # Load sample data handler
    @reactive.effect
    @reactive.event(input.load_sample_btn)
    def _load_sample_data():
        str_path = config.testcases_dir / "mar_menor" / "mm_hyd_03.str"
        work_dir = config.testcases_dir / "mar_menor"
        if not str_path.exists():
            ui.notification_show(
                f"Sample STR not found: {str_path}", type="error"
            , duration=6)
            return
        ui.update_text("input_file", value=str(str_path))
        ui.update_text("working_dir", value=str(work_dir))
        ui.update_select("tool_select", selected="shyfem")
        ui.notification_show(
            "Sample loaded: mm_hyd_03.str ready to run (~3s serial)",
            type="message",
            duration=4,
        )

    @render.ui
    def shyfem_options():
        """Render MPI + solver options only when shyfem is selected."""
        tool = input.tool_select()
        if tool != "shyfem":
            return ui.span()

        mpi_np_control = ui.span()
        try:
            if input.mpi_enabled():
                mpi_np_control = ui.input_numeric(
                    "mpi_np",
                    "Number of Processes",
                    value=4,
                    min=2,
                    max=128,
                )
        except Exception:
            logger.debug("MPI input not yet available", exc_info=True)

        return ui.div(
            ui.h6("MPI Options"),
            ui.input_checkbox("mpi_enabled", "Enable MPI", value=False),
            mpi_np_control,
            ui.hr(),
            ui.h6("Solver Options"),
            ui.input_select(
                "solver_select",
                "Solver",
                choices={
                    "sparskit": "Direct Solver (SPARSKIT)",
                    "petsc": "Iterative Solver (PETSc)",
                },
                selected="sparskit",
            ),
            ui.output_ui("solver_hint"),
        )

    @render.ui
    def solver_hint():
        """Show solver recommendation and availability hint."""
        # Check PETSc availability
        petsc_available = config.shyfem_dir and ShyfemWrapper(
            config.shyfem_dir
        ).check_solver_available("petsc")

        # Detect mesh size from input file
        input_file = input.input_file()
        working_dir = input.working_dir()
        num_nodes = None
        if input_file and working_dir:
            num_nodes = detect_mesh_node_count(input_file, working_dir)

        rec = get_solver_recommendation(num_nodes, config.solver_node_threshold)
        parts = []

        if not petsc_available:
            parts.append(
                ui.p(
                    "PETSc solver not installed. Build with: ",
                    ui.code("make petsc"),
                    class_="text-warning small mb-1",
                )
            )

        if rec["hint"]:
            parts.append(ui.p(rec["hint"], class_="text-muted small mb-0"))

        return ui.div(*parts) if parts else ui.div()

    @render.ui
    def restart_section():
        """Render restart dropdown only when shyfem is selected."""
        tool = input.tool_select()
        if tool != "shyfem":
            return ui.span()

        # Build choices from completed shyfem jobs that have .rst files
        choices: dict[str, str] = {"": "Fresh start (no restart)"}
        jobs = all_jobs_data.get()
        for job in jobs:
            if job.tool_name != "shyfem" or job.status != JobStatus.COMPLETED:
                continue
            work_dir = Path(job.working_dir)
            rst_files = sorted(work_dir.glob("*.rst"))
            if rst_files:
                label = f"{job.name} ({rst_files[-1].name})"
                choices[str(rst_files[-1])] = label

        return ui.div(
            ui.hr(),
            ui.h6("Restart"),
            ui.input_select(
                "restart_from",
                "Continue from job",
                choices=choices,
            ),
            ui.output_ui("restart_info"),
        )

    @render.ui
    def restart_info():
        """Show selected restart file path."""
        try:
            rst = input.restart_from()
        except Exception:
            return ui.span()
        if not rst:
            return ui.span()
        rst_path = Path(rst)
        if rst_path.exists():
            size_kb = rst_path.stat().st_size / 1024
            return ui.p(
                f"Restart file: {rst_path.name} ({size_kb:.0f} KB)",
                class_="text-muted small mb-0",
            )
        return ui.p(
            f"Warning: restart file not found: {rst}",
            class_="text-warning small mb-0",
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

    from shyfem_ui.config import get_config

    log_viewer_server(
        "job_log",
        log_content,
        on_refresh=_refresh_log,
        refresh_interval=get_config().log_refresh_interval,
    )

    # Single unified poll loop: refresh every 2s while jobs or workflows are active
    @reactive.effect
    async def _auto_refresh():
        try:
            active = active_jobs_data.get()
            wf_id = active_workflow_id.get()
            wf_active = False
            if wf_id:
                wf = workflow_engine.get_workflow(wf_id)
                wf_active = wf.is_active if wf else False

            if active or wf_active:
                reactive.invalidate_later(2)
                _refresh_tick.set(_refresh_tick.get() + 1)
            await _refresh_jobs()
            await _refresh_log()
        except Exception:
            logger.debug("Auto-refresh poll failed, retrying in 5s", exc_info=True)
            reactive.invalidate_later(5)

    @reactive.effect
    @reactive.event(input.refresh_btn)
    async def _manual_refresh():
        try:
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Refresh failed: {e}", type="error", duration=6)

    async def _refresh_jobs():
        """Refresh job lists."""
        show_all = input.show_all_run_jobs() if _is_server_mode else True
        sid = None if show_all else _session_id
        jobs = await job_queue.list_jobs(limit=50, session_id=sid)
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
        # Tutorial accounts are read-only.
        # Use user_role() from the top-level server where input.current_user_role
        # is reachable (Shiny module namespacing prevents accessing it here).
        try:
            _role = user_role() if user_role is not None else None
        except Exception:
            _role = _current_user.get("role") if _current_user else None
        if _role == "tutorial":
            ui.notification_show(
                "Tutorial accounts are read-only. Contact your admin for a full account.",
                type="warning",
                duration=6,
            )
            return

        # Access check: require editor role on active project
        if active_project is not None:
            _proj = active_project.get()
            if _proj is not None:
                from shyfem_ui.middleware.session_auth import get_current_user as _get_user
                from shyfem_ui.services.access_control import check_project_access

                _usr = _get_user()
                if (
                    _usr is not None
                    and check_project_access(_proj["id"], _usr, min_role="editor") is None
                ):
                    ui.notification_show(
                        "Permission denied: editor role required to submit jobs", type="error"
                    , duration=6)
                    return

        name = input.job_name() or f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        tool = input.tool_select()
        input_file = input.input_file()
        working_dir = input.working_dir()

        if not input_file:
            ui.notification_show("Input file is required", type="error", duration=6)
            return

        try:
            validated_input = config.validate_path(input_file, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        # Validate STR parameters before submission
        if tool == "shyfem" and validated_input.suffix == ".str":
            try:
                parsed_str = StrParser.parse_file(validated_input)
                msgs = validate_str(parsed_str.sections)
                errors = [m for m in msgs if m.level == "error"]
                warnings = [m for m in msgs if m.level == "warning"]
                if errors:
                    for m in errors:
                        ui.notification_show(f"STR error: {m.message}", type="error", duration=8)
                    return
                for m in warnings:
                    ui.notification_show(f"STR warning: {m.message}", type="warning", duration=6)
            except Exception:
                logger.debug("STR validation skipped (parse error)", exc_info=True)

        if not working_dir:
            working_dir = str(validated_input.parent)

        try:
            validated_workdir = config.validate_path(working_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        # Build job spec
        args = [str(validated_input)]
        metadata = _get_job_metadata(_session_id, _user_id)

        # Solver selection
        solver = input.solver_select() if tool == "shyfem" else "sparskit"
        if solver == "petsc":
            metadata["solver"] = "petsc"

        # Restart file selection
        if tool == "shyfem":
            try:
                restart_from = input.restart_from()
                if restart_from:
                    metadata["restart_file"] = restart_from
            except Exception:
                logger.warning("Could not set restart_from file", exc_info=True)

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
            ui.notification_show(f"Job submitted: {job_id}", type="message", duration=4)
            selected_job_id.set(job_id)
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Failed to submit job: {e}", type="error", duration=6)

    @render.ui
    def dashboard():
        """Live progress dashboard for all active jobs."""
        active = active_jobs_data.get()
        all_jobs = all_jobs_data.get()

        # Summary stats
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
                ui.p(
                    "No active jobs. Submit a new job to get started.",
                    class_="text-muted text-center mt-3",
                ),
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
                            (
                                ui.span(f"ETA: {eta_str}", class_="small text-muted ms-auto")
                                if eta_str
                                else None
                            ),
                            class_="d-flex justify-content-between mt-1",
                        ),
                        ui.div(
                            ui.span(
                                f"Started: {format_datetime(job.started_at)}",
                                class_="small text-muted me-3",
                            ),
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
                ui.notification_show("Job cancelled", type="message", duration=4)
            else:
                ui.notification_show("Failed to cancel job", type="error", duration=6)
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Error: {e}", type="error", duration=6)

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
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font_size=16,
                font_color="gray",
            )
            fig.update_layout(height=400)
            return fig

        try:
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
            for _i, job in enumerate(reversed(jobs[:20])):  # Show last 20
                start = job.started_at or job.created_at
                end = job.completed_at or datetime.now()
                color = status_colors.get(job.status, "#6c757d")

                fig.add_trace(
                    go.Bar(
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
                    )
                )

            fig.update_layout(
                title="Job Timeline (last 20 jobs)",
                xaxis_title="Duration (seconds)",
                yaxis_title="",
                height=max(300, len(jobs[:20]) * 35 + 100),
                barmode="stack",
                showlegend=False,
            )
            return fig
        except Exception as exc:
            logger.exception("Error rendering timeline chart")
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
            fig.update_layout(height=400)
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
            file_items = [ui.li(ui.code(f, class_="small")) for f in job.output_files]
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
            ui.input_action_button(
                "generate_report_btn",
                "Generate Report",
                class_="btn-sm btn-outline-success",
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
                    "generate_report_btn",
                    "Generate Report",
                    class_="btn-sm btn-outline-success me-2",
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
                ui.notification_show("Job cancelled", type="message", duration=4)
            else:
                ui.notification_show("Failed to cancel job", type="error", duration=6)
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Error: {e}", type="error", duration=6)

    # --- Generate Report handler ---

    @reactive.effect
    @reactive.event(input.generate_report_btn)
    def _generate_report():
        job = selected_job.get()
        if job is None:
            ui.notification_show("Select a job first", type="warning")
            return

        try:
            report_path = generate_job_report(job_info=job)
            ui.notification_show(
                f"Report generated: {report_path}",
                type="message",
                duration=8,
            )
        except Exception as e:
            ui.notification_show(f"Report generation failed: {e}", type="error", duration=6)

    # --- Workflow engine ---

    workflow_engine = WorkflowEngine(job_queue)
    active_workflow_id = reactive.value(None)
    _refresh_tick = reactive.value(0)  # bumped by _auto_refresh to trigger wf_progress re-render

    @render.ui
    def wf_template_info():
        try:
            key = input.wf_template()
        except Exception:
            logger.debug("Workflow template selection unavailable")
            return None

        tpl = WORKFLOW_TEMPLATES.get(key)
        if not tpl:
            return None

        steps_list = [
            ui.li(
                ui.code(step.tool_name),
                ui.span(f" - {step.name}", class_="text-muted"),
            )
            for step in tpl["steps"]
        ]

        return ui.div(
            ui.p(tpl["description"], class_="text-muted small"),
            ui.strong("Steps:"),
            ui.tags.ol(*steps_list, class_="small mb-0"),
            class_="p-2 bg-light rounded",
        )

    @reactive.effect
    @reactive.event(input.wf_launch_btn)
    async def _launch_workflow():
        template_key = input.wf_template()
        wf_name = input.wf_name() or None
        input_str = input.wf_input_str()
        input_grd = input.wf_input_grd()
        working_dir = input.wf_working_dir()
        mpi_np = input.wf_mpi_np()

        if not working_dir:
            ui.notification_show("Working directory is required", type="error", duration=6)
            return

        try:
            validated_workdir = config.validate_path(working_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        validated_workdir.mkdir(parents=True, exist_ok=True)

        params = {}
        if input_str:
            params["input_str"] = input_str
        if input_grd:
            params["input_grd"] = input_grd
        if mpi_np:
            params["mpi_np"] = str(mpi_np)

        try:
            wf_id = await workflow_engine.create_workflow(
                template_key=template_key,
                working_dir=validated_workdir,
                params=params,
                name=wf_name,
            )
            active_workflow_id.set(wf_id)
            ui.notification_show(f"Workflow launched: {wf_id[:8]}", type="message", duration=4)
        except Exception as e:
            ui.notification_show(f"Failed to launch workflow: {e}", type="error", duration=6)

    @render.ui
    def wf_progress():
        _refresh_tick.get()  # subscribe to poll cycle for auto re-render
        wf_id = active_workflow_id.get()
        if not wf_id:
            return ui.p("Launch a workflow to see progress.", class_="text-muted small")

        wf = workflow_engine.get_workflow(wf_id)
        if not wf:
            return ui.p("Workflow not found.", class_="text-muted")

        # Re-render is triggered by the unified _auto_refresh poll loop
        # (reads active_workflow_id which changes on each refresh cycle)

        # Status badge
        status_colors = {
            WorkflowStatus.PENDING: "bg-secondary",
            WorkflowStatus.RUNNING: "bg-primary",
            WorkflowStatus.COMPLETED: "bg-success",
            WorkflowStatus.FAILED: "bg-danger",
            WorkflowStatus.CANCELLED: "bg-warning",
            WorkflowStatus.PAUSED: "bg-info",
        }
        badge_class = status_colors.get(wf.status, "bg-secondary")

        # Progress bar
        progress_pct = int(wf.progress * 100)

        # Step-by-step status
        step_items = []
        for i, step in enumerate(wf.steps):
            if i < wf.current_step_index:
                step_badge = ui.span("Done", class_="badge bg-success ms-2")
            elif i == wf.current_step_index and wf.status == WorkflowStatus.RUNNING:
                step_badge = ui.span("Running", class_="badge bg-primary ms-2")
            elif wf.status == WorkflowStatus.FAILED and i == wf.current_step_index:
                step_badge = ui.span("Failed", class_="badge bg-danger ms-2")
            else:
                step_badge = ui.span("Pending", class_="badge bg-secondary ms-2")

            step_items.append(
                ui.div(
                    ui.span(f"{i + 1}. ", class_="fw-bold"),
                    ui.code(step.tool_name),
                    ui.span(f" ({step.name})", class_="text-muted small"),
                    step_badge,
                    class_="mb-1",
                )
            )

        error_section = None
        if wf.error_message:
            error_section = ui.div(
                ui.strong("Error: ", class_="text-danger"),
                ui.span(wf.error_message, class_="text-danger small"),
                class_="mt-2",
            )

        return ui.div(
            ui.h6("Active Workflow"),
            ui.div(
                ui.span(wf.name, class_="fw-bold me-2"),
                ui.span(wf.status.value.upper(), class_=f"badge {badge_class}"),
                class_="mb-2",
            ),
            ui.div(
                ui.div(
                    ui.div(
                        f"{progress_pct}%",
                        class_="progress-bar progress-bar-striped"
                        + (" progress-bar-animated" if wf.is_active else "")
                        + (" bg-success" if wf.status == WorkflowStatus.COMPLETED else ""),
                        style=f"width: {max(progress_pct, 2)}%",
                        role="progressbar",
                    ),
                    class_="progress mb-2",
                    style="height: 20px;",
                ),
            ),
            *step_items,
            error_section,
        )

    @render.ui
    def wf_history():
        # Trigger re-render when workflow state changes
        active_workflow_id.get()

        workflows = workflow_engine.list_workflows(limit=10)
        if not workflows:
            return ui.p("No workflows yet.", class_="text-muted small")

        rows = []
        for wf in workflows:
            status_colors = {
                WorkflowStatus.COMPLETED: "bg-success",
                WorkflowStatus.FAILED: "bg-danger",
                WorkflowStatus.RUNNING: "bg-primary",
                WorkflowStatus.CANCELLED: "bg-warning",
            }
            badge_class = status_colors.get(wf.status, "bg-secondary")

            rows.append(
                ui.tags.tr(
                    ui.tags.td(ui.code(wf.id[:8], class_="small")),
                    ui.tags.td(wf.name),
                    ui.tags.td(ui.span(wf.status.value, class_=f"badge {badge_class}")),
                    ui.tags.td(f"{int(wf.progress * 100)}%"),
                    ui.tags.td(format_duration(wf.duration) if wf.duration else "-"),
                )
            )

        return ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("ID"),
                    ui.tags.th("Name"),
                    ui.tags.th("Status"),
                    ui.tags.th("Progress"),
                    ui.tags.th("Duration"),
                ),
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-bordered",
        )

    # Latest progress data from callbacks, polled by _auto_refresh
    _latest_progress: dict[str, tuple[float, str]] = {}

    def on_progress(job_id: str, progress: float, message: str):
        _latest_progress[job_id] = (progress, message)

    # Session ID for multi-user isolation and per-session callbacks
    _session_id = str(id(session))
    _is_server_mode = config.deployment_mode == "server"

    # User context for job ownership
    from shyfem_ui.middleware.session_auth import get_current_user

    _current_user = get_current_user()
    _user_id = _current_user["id"] if _current_user else None

    @render.ui
    def run_show_all_toggle_ui():
        if not _is_server_mode:
            return ui.span()  # hidden in local mode
        return ui.input_switch("show_all_run_jobs", "All jobs", value=False)

    job_queue.add_progress_callback(_session_id, on_progress)

    # Clean up callback when session ends
    @session.on_ended
    async def _cleanup_session():
        job_queue.remove_progress_callback(_session_id)

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
