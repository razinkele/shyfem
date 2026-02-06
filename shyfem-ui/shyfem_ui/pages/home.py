"""Home/Dashboard page for SHYFEM UI."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.config import Config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Job, Project
from shyfem_ui.services.job_queue import JobQueue, JobStatus


@module.ui
def home_ui():
    """Dashboard page UI."""
    return ui.page_fluid(
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
                        class_="btn-outline-secondary w-100",
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
        # New project modal
        ui.modal(
            ui.input_text("project_name", "Project Name", placeholder="my_simulation"),
            ui.input_text_area(
                "project_description",
                "Description (optional)",
                placeholder="Brief description of the project",
            ),
            ui.input_text(
                "project_dir",
                "Project Directory",
                placeholder="/path/to/project",
            ),
            title="Create New Project",
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
            id="new_project_modal",
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
        _refresh_projects()
        await _refresh_jobs()

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
        # Set default directory
        default_dir = str(config.work_dir / f"project_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        ui.update_text("project_dir", value=default_dir)
        ui.modal_show("new_project_modal")

    @reactive.effect
    @reactive.event(input.cancel_create_btn)
    def _hide_modal():
        ui.modal_remove("new_project_modal")

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
            ui.modal_remove("new_project_modal")
            _refresh_projects()

        except Exception as e:
            ui.notification_show(f"Failed to create project: {e}", type="error")

    return {
        "projects": projects,
    }
