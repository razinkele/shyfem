"""Home/Dashboard page for SHYFEM UI."""

import shutil
from datetime import datetime
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, Simulation
from shyfem_ui.services.job_queue import JobQueue, JobStatus

# Tutorial phases: (phase_name, description, list of .str file basenames)
TUTORIAL_PHASES = [
    (
        "1. Basic Hydrodynamics",
        "Minimal setup, output, wind forcing, friction",
        ["mm_hyd_00", "mm_hyd_01", "mm_hyd_02", "mm_hyd_03"],
    ),
    (
        "2. Tidal Boundaries",
        "Sea level boundary conditions",
        ["mm_hyd_11", "mm_hyd_12", "mm_hyd_13"],
    ),
    (
        "3. Coriolis & Rivers",
        "Coriolis force, advection, river discharge",
        ["mm_hyd_21", "mm_hyd_22", "mm_hyd_23"],
    ),
    (
        "4. Salinity (3D)",
        "Baroclinic salinity transport",
        ["mm_hyd_31"],
    ),
    (
        "5. Temperature (3D)",
        "Full 3D with temperature and turbulence",
        ["mm_hyd_41", "mm_hyd_42"],
    ),
    (
        "6. Advanced Numerics",
        "Non-linear free surface, Smagorinsky diffusion",
        ["mm_hyd_43"],
    ),
]


@module.ui
def home_ui():
    """Dashboard page UI."""
    return ui.div(
        # Header
        ui.div(
            ui.h2("SHYFEM Workbench"),
            ui.p(
                "Finite Element Hydrodynamic Model - Web Interface",
                class_="text-muted",
            ),
            class_="mb-4",
        ),
        # Quick actions row
        ui.row(
            ui.column(
                3,
                ui.div(
                    ui.h5("Quick Start"),
                    ui.input_action_button(
                        "new_project_btn",
                        "New Project",
                        class_="btn-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "open_project_btn",
                        "Open Project",
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "import_grid_btn",
                        "Import Grid",
                        class_="btn-outline-secondary w-100 mb-2",
                    ),
                    ui.hr(),
                    ui.h6("Tutorials", class_="text-muted"),
                    ui.input_action_button(
                        "tutorial_btn",
                        "Mar Menor Tutorial",
                        class_="btn-success w-100",
                    ),
                    class_="card p-3",
                ),
            ),
            ui.column(
                3,
                ui.div(
                    ui.h5("System Status"),
                    ui.output_ui("system_status"),
                    class_="card p-3",
                ),
            ),
            ui.column(
                6,
                ui.div(
                    ui.h5("Recent Jobs"),
                    ui.output_ui("recent_jobs"),
                    class_="card p-3",
                ),
            ),
        ),
        # Projects list
        ui.row(
            ui.column(
                12,
                ui.div(
                    ui.h5("Projects"),
                    ui.output_ui("projects_list"),
                    class_="card p-3 mt-3",
                ),
            ),
        ),
    )


@module.server
def home_server(
    input,
    output,
    session,
    config: Config,
    job_queue: Optional[JobQueue] = None,
):
    """Dashboard page server logic."""
    projects = reactive.value([])
    recent_jobs_list = reactive.value([])

    # Load initial data
    @reactive.effect
    async def _load_data():
        try:
            _refresh_projects()
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Error loading data: {e}", type="error")

    def _refresh_projects():
        with db_session() as db:
            project_list = db.query(Project).order_by(Project.updated_at.desc()).limit(10).all()
            # Convert to dicts to avoid detached instance errors
            projects.set([
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "work_dir": p.work_dir,
                    "updated_at": p.updated_at,
                }
                for p in project_list
            ])

    async def _refresh_jobs():
        if job_queue:
            jobs = await job_queue.list_jobs(limit=5)
            recent_jobs_list.set(jobs)

    @render.ui
    def system_status():
        # Check SHYFEM tools availability
        tools = ["shypre", "shybas", "shyparts", "shyfem", "shyelab", "shyplot"]
        tool_status = []

        from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
        wrapper = ShyfemWrapper(config.shyfem_dir)

        for tool in tools:
            available = wrapper.check_available(tool)
            icon = "check-circle" if available else "x-circle"
            color = "text-success" if available else "text-danger"
            tool_status.append(
                ui.div(
                    ui.span(tool, class_="me-2"),
                    ui.span(icon, class_=f"{color}"),
                    class_="d-flex justify-content-between",
                )
            )

        return ui.div(
            *tool_status,
            ui.hr(),
            ui.div(
                ui.span("SHYFEM Dir:", class_="text-muted"),
                ui.br(),
                ui.code(str(config.shyfem_dir), class_="small"),
            ),
        )

    @render.ui
    def recent_jobs():
        jobs = recent_jobs_list.get()
        if not jobs:
            return ui.p("No recent jobs", class_="text-muted")

        job_items = []
        for job in jobs:
            status_class = {
                JobStatus.COMPLETED: "text-success",
                JobStatus.FAILED: "text-danger",
                JobStatus.RUNNING: "text-primary",
                JobStatus.PENDING: "text-secondary",
                JobStatus.QUEUED: "text-info",
            }.get(job.status, "text-secondary")

            job_items.append(
                ui.div(
                    ui.span(job.name, class_="fw-bold"),
                    ui.span(f" ({job.tool_name})", class_="text-muted"),
                    ui.span(
                        f" - {job.status.value}",
                        class_=status_class,
                    ),
                    class_="mb-1",
                )
            )

        return ui.div(*job_items)

    @render.ui
    def projects_list():
        project_data = projects.get()
        if not project_data:
            return ui.p("No projects yet. Create one to get started!", class_="text-muted")

        rows = []
        for p in project_data:
            rows.append(
                ui.tags.tr(
                    ui.tags.td(
                        ui.input_action_link(
                            f"project_{p['id']}",
                            p["name"],
                            class_="fw-bold",
                        )
                    ),
                    ui.tags.td(p["description"] or "-"),
                    ui.tags.td(ui.code(p["work_dir"], class_="small")),
                    ui.tags.td(
                        p["updated_at"].strftime("%Y-%m-%d %H:%M")
                        if p["updated_at"] else "-"
                    ),
                )
            )

        return ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Name"),
                    ui.tags.th("Description"),
                    ui.tags.th("Directory"),
                    ui.tags.th("Last Updated"),
                )
            ),
            ui.tags.tbody(*rows),
            class_="table table-hover",
        )

    # Modal handlers
    @reactive.effect
    @reactive.event(input.new_project_btn)
    def _show_new_project_modal():
        default_dir = str(config.work_dir / f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        m = ui.modal(
            ui.input_text("project_name", "Project Name", placeholder="my_simulation"),
            ui.input_text_area(
                "project_description",
                "Description (optional)",
                placeholder="Brief description of the project",
            ),
            ui.input_text(
                "project_dir",
                "Project Directory",
                value=default_dir,
            ),
            title="Create New Project",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "create_project_btn",
                    "Create",
                    class_="btn-primary",
                ),
                ui.input_action_button(
                    "cancel_create_btn",
                    "Cancel",
                    class_="btn-secondary ms-2",
                ),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.cancel_create_btn)
    def _hide_modal():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.create_project_btn)
    def _create_project():
        name = input.project_name()
        description = input.project_description()
        work_dir = input.project_dir()

        if not name:
            ui.notification_show("Project name is required", type="error")
            return

        if not work_dir:
            ui.notification_show("Project directory is required", type="error")
            return

        # Validate and create directory
        try:
            project_path = config.validate_save_path(work_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return

        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            ui.notification_show(f"Failed to create directory: {e}", type="error")
            return

        # Create project in database
        try:
            with db_session() as db:
                project = Project(
                    name=name,
                    description=description or None,
                    work_dir=str(project_path),
                )
                db.add(project)

            ui.notification_show(f"Project '{name}' created successfully", type="message")
            ui.modal_remove()
            _refresh_projects()

        except Exception as e:
            ui.notification_show(f"Failed to create project: {e}", type="error")

    # Tutorial handlers
    @reactive.effect
    @reactive.event(input.tutorial_btn)
    def _show_tutorial_modal():
        m = ui.modal(
            ui.p(
                "Set up a guided tutorial project using the Mar Menor lagoon "
                "example. This copies the example grid and input files into a "
                "new project so you can work through the 6 tutorial phases."
            ),
            ui.input_text(
                "tutorial_project_name",
                "Project Name",
                value="mar_menor_tutorial",
            ),
            ui.hr(),
            ui.h6("Tutorial Phases"),
            ui.tags.ol(
                *[
                    ui.tags.li(
                        ui.span(phase, class_="fw-bold"),
                        ui.span(f" — {desc}", class_="text-muted"),
                        ui.br(),
                        ui.code(", ".join(f"{f}.str" for f in files), class_="small"),
                    )
                    for phase, desc, files in TUTORIAL_PHASES
                ],
                class_="small",
            ),
            title="Mar Menor Tutorial",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "confirm_tutorial_btn",
                    "Create Tutorial Project",
                    class_="btn-success",
                ),
                ui.input_action_button(
                    "cancel_tutorial_btn",
                    "Cancel",
                    class_="btn-secondary ms-2",
                ),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.cancel_tutorial_btn)
    def _hide_tutorial_modal():
        ui.modal_remove()

    @reactive.effect
    @reactive.event(input.confirm_tutorial_btn)
    def _create_tutorial_project():
        name = input.tutorial_project_name().strip()
        if not name:
            ui.notification_show("Project name is required", type="error")
            return

        # Check source directory exists
        mar_menor_src = config.testcases_dir / "mar_menor"
        if not mar_menor_src.is_dir():
            ui.notification_show(
                f"Tutorial source not found: {mar_menor_src}", type="error"
            )
            return

        # Create project directory
        project_path = config.work_dir / name
        try:
            config.ensure_work_dir()
            if project_path.exists():
                ui.notification_show(
                    f"Directory already exists: {project_path}", type="error"
                )
                return
            shutil.copytree(mar_menor_src, project_path)
        except Exception as e:
            ui.notification_show(f"Failed to copy tutorial files: {e}", type="error")
            return

        # Create database records
        try:
            with db_session() as db:
                project = Project(
                    name=name,
                    description="Mar Menor tutorial — 6-phase guided introduction to SHYFEM",
                    work_dir=str(project_path),
                )
                db.add(project)
                db.flush()

                grid = Grid(
                    project_id=project.id,
                    name="MM_coarse",
                    description="Mar Menor coarse grid",
                    grd_file="GRID/MM_coarse.grd",
                    bas_file="GRID/MM_coarse.bas",
                )
                db.add(grid)
                db.flush()

                for phase_name, phase_desc, str_files in TUTORIAL_PHASES:
                    for basename in str_files:
                        str_path = project_path / f"{basename}.str"
                        if not str_path.exists():
                            continue
                        sim = Simulation(
                            project_id=project.id,
                            grid_id=grid.id,
                            name=basename,
                            description=f"{phase_name}: {phase_desc}",
                            str_file=f"{basename}.str",
                        )
                        db.add(sim)

            ui.notification_show(
                f"Tutorial project '{name}' created successfully!", type="message"
            )
            ui.modal_remove()
            _refresh_projects()

        except Exception as e:
            # Clean up copied directory on DB failure
            if project_path.exists():
                shutil.rmtree(project_path, ignore_errors=True)
            ui.notification_show(f"Failed to create tutorial project: {e}", type="error")

    return {
        "projects": projects,
    }
