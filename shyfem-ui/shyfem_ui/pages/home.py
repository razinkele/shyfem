"""Home/Dashboard page for SHYFEM UI."""

import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path

from shiny import module, reactive, render, ui
from sqlalchemy import or_

from shyfem_ui.config import Config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, Simulation
from shyfem_ui.models.user import ProjectPermission
from shyfem_ui.services.job_queue import JobQueue, JobStatus
from shyfem_ui.tutorial_content import TUTORIAL_CONTENT


def _safe_filename(name: str) -> str:
    """Sanitize a project name for use as a filename.

    Replaces non-alphanumeric characters (except hyphens, underscores, and
    spaces) with underscores and strips leading/trailing whitespace.

    Args:
        name: Raw project name string.

    Returns:
        Sanitized string safe for use in filenames.
    """
    return "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()


def get_visible_projects(db, user_id: int, role: str, limit: int = 10) -> list:
    """Return projects visible to a user based on ownership and permissions.

    Admins see all projects. Regular users see their own projects
    plus projects shared with them.
    """
    if role == "admin":
        return db.query(Project).order_by(Project.updated_at.desc()).limit(limit).all()

    return (
        db.query(Project)
        .filter(
            or_(
                Project.owner_id == user_id,
                Project.id.in_(
                    db.query(ProjectPermission.project_id).filter(
                        ProjectPermission.user_id == user_id
                    )
                ),
            )
        )
        .order_by(Project.updated_at.desc())
        .limit(limit)
        .all()
    )


def _should_show_share_button(project: dict, user: dict | None) -> bool:
    """Return True if user should see the Share button for this project.

    Only project owners and admins can share.
    """
    if user is None:
        return False
    if user.get("role") == "admin":
        return True
    return project.get("owner_id") == user.get("id")


def _build_permissions_table_data(permissions: list[dict]) -> list[dict]:
    """Format permission dicts for display in the share modal table."""
    return [
        {
            "user_id": p["user_id"],
            "username": p["username"],
            "display_name": p.get("display_name") or p["username"],
            "role": p["role"],
        }
        for p in permissions
    ]


@module.ui
def home_ui() -> ui.Tag:
    """Dashboard page UI — rich metrics, project cards, activity timeline."""
    return ui.div(
        # Welcome header
        ui.div(
            ui.h3("Welcome to SHYFEM Workbench", class_="mb-1"),
            ui.p(
                "Finite Element Hydrodynamic Model — Web Interface",
                class_="text-muted mb-0",
                style="font-size:0.9rem",
            ),
            class_="mb-4",
        ),
        # Main two-column layout
        ui.row(
            # Left column (8/12) — metrics + projects
            ui.column(
                8,
                # Metric cards row
                ui.row(
                    ui.column(
                        4,
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.tags.i(class_="bi bi-folder", style="font-size:1.4rem"),
                                    class_="sf-metric-icon",
                                    style="background:rgba(26,107,138,0.1);color:var(--sf-ocean-mid)",
                                ),
                                ui.div(
                                    ui.output_ui("project_count"),
                                    ui.span("Projects", class_="sf-metric-label"),
                                    class_="sf-metric-text",
                                ),
                                class_="d-flex align-items-center gap-3",
                            ),
                            class_="card p-3",
                        ),
                    ),
                    ui.column(
                        4,
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.tags.i(class_="bi bi-activity", style="font-size:1.4rem"),
                                    class_="sf-metric-icon",
                                    style="background:rgba(61,184,160,0.1);color:var(--sf-teal)",
                                ),
                                ui.div(
                                    ui.output_ui("active_job_count"),
                                    ui.span("Active Jobs", class_="sf-metric-label"),
                                    class_="sf-metric-text",
                                ),
                                class_="d-flex align-items-center gap-3",
                            ),
                            class_="card p-3",
                        ),
                    ),
                    ui.column(
                        4,
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.tags.i(class_="bi bi-cpu", style="font-size:1.4rem"),
                                    class_="sf-metric-icon",
                                    style="background:rgba(61,184,160,0.1);color:var(--sf-teal)",
                                ),
                                ui.div(
                                    ui.output_ui("system_health_count"),
                                    ui.span("Tools Ready", class_="sf-metric-label"),
                                    class_="sf-metric-text",
                                ),
                                class_="d-flex align-items-center gap-3",
                            ),
                            class_="card p-3",
                        ),
                    ),
                    class_="mb-3",
                ),
                # Projects section
                ui.div(
                    ui.div(
                        ui.h5("Projects", class_="mb-0"),
                        class_="sf-card-header",
                    ),
                    ui.output_ui("projects_list"),
                    class_="card p-3",
                ),
            ),
            # Right column (4/12) — activity + quick start
            ui.column(
                4,
                # Recent activity
                ui.div(
                    ui.div(
                        ui.h5("Recent Activity", class_="mb-0"),
                        ui.output_ui("show_all_toggle_ui"),
                        class_="sf-card-header",
                    ),
                    ui.output_ui("recent_jobs"),
                    class_="card p-3 mb-3",
                ),
                # Quick start
                ui.div(
                    ui.div(
                        ui.h5("Quick Start", class_="mb-0"),
                        class_="sf-card-header",
                    ),
                    ui.input_action_button(
                        "new_project_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-plus-lg me-2"), "New Project"),
                        class_="btn-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "open_project_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-folder2-open me-2"), "Open Project"),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "import_grid_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-upload me-2"), "Import Grid"),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "import_project_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-box-arrow-in-down me-2"), "Import Project"),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.hr(),
                    ui.input_action_button(
                        "tutorial_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-mortarboard me-2"), "Mar Menor Tutorial"),
                        class_="btn-success w-100",
                    ),
                    class_="card p-3",
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
    job_queue: JobQueue | None = None,
    active_project=None,
    nav_callback=None,
) -> None:
    """Dashboard page server logic."""
    projects = reactive.value([])
    recent_jobs_list = reactive.value([])
    _session_id = str(id(session))
    _is_server_mode = config.deployment_mode == "server"

    from shyfem_ui.middleware.session_auth import get_current_user as _get_user

    _current_user = _get_user()

    @render.ui
    def show_all_toggle_ui():
        if not _is_server_mode:
            return ui.span()  # hidden in local mode
        return ui.input_switch("show_all_jobs", "All jobs", value=False)

    # Load initial data
    @reactive.effect
    async def _load_data():
        try:
            _refresh_projects()
            await _refresh_jobs()
        except Exception as e:
            ui.notification_show(f"Error loading data: {e}", type="error", duration=6)

    def _refresh_projects():
        from shyfem_ui.middleware.session_auth import get_current_user

        user = get_current_user()
        with db_session() as db:
            if user and user.get("role") != "admin":
                project_list = get_visible_projects(db, user["id"], user["role"])
            else:
                project_list = db.query(Project).order_by(Project.updated_at.desc()).limit(10).all()
            projects.set(
                [
                    {
                        "id": p.id,
                        "name": p.name,
                        "description": p.description,
                        "work_dir": p.work_dir,
                        "updated_at": p.updated_at,
                        "owner_id": getattr(p, "owner_id", None),
                    }
                    for p in project_list
                ]
            )

    async def _refresh_jobs():
        if job_queue:
            try:
                show_all = input.show_all_jobs() if _is_server_mode else True
            except Exception:
                show_all = False  # input not yet rendered on startup
            sid = None if show_all else _session_id
            jobs = await job_queue.list_jobs(limit=5, session_id=sid)
            recent_jobs_list.set(jobs)

    @render.ui
    def project_count():
        count = len(projects.get())
        return ui.span(str(count), class_="sf-metric-number")

    @render.ui
    def active_job_count():
        jobs = recent_jobs_list.get()
        active = sum(1 for j in jobs if j.status in (JobStatus.RUNNING, JobStatus.QUEUED))
        pulse = " sf-pulse" if active > 0 else ""
        return ui.span(str(active), class_=f"sf-metric-number{pulse}")

    @render.ui
    def system_health_count():
        from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

        wrapper = ShyfemWrapper(config.shyfem_dir)
        tools = ["shypre", "shybas", "shyparts", "shyfem", "shyelab", "shyplot"]
        available = sum(1 for t in tools if wrapper.check_available(t))
        color = "var(--sf-teal)" if available == len(tools) else "var(--sf-coral)"
        return ui.span(
            f"{available}/{len(tools)}",
            class_="sf-metric-number",
            style=f"color:{color}",
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
            share_btn = ui.span()
            if _should_show_share_button(p, _current_user):
                share_btn = ui.input_action_link(
                    f"share_{p['id']}",
                    "Share",
                    class_="btn btn-sm btn-outline-success me-1",
                )

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
                        p["updated_at"].strftime("%Y-%m-%d %H:%M") if p["updated_at"] else "-"
                    ),
                    ui.tags.td(
                        share_btn,
                        ui.input_action_link(
                            f"export_{p['id']}",
                            "Export",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"clone_{p['id']}",
                            "Clone",
                            class_="btn btn-sm btn-outline-secondary",
                        ),
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
                    ui.tags.th("Actions"),
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
                ui.modal_button("Cancel"),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.create_project_btn)
    def _create_project():
        name = input.project_name()
        description = input.project_description()
        work_dir = input.project_dir()

        if not name:
            ui.notification_show("Project name is required", type="error", duration=6)
            return

        if not work_dir:
            ui.notification_show("Project directory is required", type="error", duration=6)
            return

        # Validate and create directory
        try:
            project_path = config.validate_save_path(work_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            ui.notification_show(f"Failed to create directory: {e}", type="error", duration=6)
            return

        # Create project in database
        try:
            with db_session() as db:
                from shyfem_ui.middleware.session_auth import get_current_user

                user = get_current_user()
                project = Project(
                    name=name,
                    description=description or None,
                    work_dir=str(project_path),
                    owner_id=user["id"] if user else None,
                )
                db.add(project)

            ui.notification_show(f"Project '{name}' created successfully", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()

        except Exception as e:
            ui.notification_show(f"Failed to create project: {e}", type="error", duration=6)

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
                        ui.span(phase["title"], class_="fw-bold"),
                        ui.span(f" — {phase['description']}", class_="text-muted"),
                        ui.br(),
                        ui.code(
                            ", ".join(sim["str_file"] for sim in phase["simulations"]),
                            class_="small",
                        ),
                    )
                    for phase in TUTORIAL_CONTENT
                ],
                class_="small",
            ),
            title="Mar Menor Tutorial",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "confirm_tutorial_btn",
                    "Create Tutorial Project",
                    class_="btn-primary",
                ),
                ui.modal_button("Cancel"),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.confirm_tutorial_btn)
    def _create_tutorial_project():
        name = input.tutorial_project_name().strip()
        if not name:
            ui.notification_show("Project name is required", type="error", duration=6)
            return

        # Check source directory exists
        mar_menor_src = config.testcases_dir / "mar_menor"
        if not mar_menor_src.is_dir():
            ui.notification_show(f"Tutorial source not found: {mar_menor_src}", type="error", duration=6)
            return

        # Create project directory
        project_path = config.work_dir / name
        try:
            config.ensure_work_dir()
            if project_path.exists():
                ui.notification_show(f"Directory already exists: {project_path}", type="error", duration=6)
                return
            shutil.copytree(mar_menor_src, project_path)
        except Exception as e:
            ui.notification_show(f"Failed to copy tutorial files: {e}", type="error", duration=6)
            return

        # Create database records
        try:
            with db_session() as db:
                from shyfem_ui.middleware.session_auth import get_current_user

                user = get_current_user()
                project = Project(
                    name=name,
                    description="Mar Menor tutorial — 6-phase guided introduction to SHYFEM",
                    work_dir=str(project_path),
                    owner_id=user["id"] if user else None,
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

                for phase in TUTORIAL_CONTENT:
                    for tsim in phase["simulations"]:
                        str_path = project_path / tsim["str_file"]
                        if not str_path.exists():
                            continue
                        sim = Simulation(
                            project_id=project.id,
                            grid_id=grid.id,
                            name=tsim["name"],
                            description=f"{phase['title']}: {tsim['title']}",
                            str_file=tsim["str_file"],
                        )
                        db.add(sim)

                project_id = project.id

            # Activate project so target pages can auto-fill fields
            from shyfem_ui.services.project_context import load_project_context

            ctx = load_project_context(project_id, user=_current_user)
            if ctx and active_project is not None:
                active_project.set(ctx)

            ui.notification_show(f"Tutorial project '{name}' created successfully!", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()
            if nav_callback:
                nav_callback("Tutorial")

        except Exception as e:
            # Clean up copied directory on DB failure
            if project_path.exists():
                shutil.rmtree(project_path, ignore_errors=True)
            ui.notification_show(f"Failed to create tutorial project: {e}", type="error", duration=6)

    # --- Active project handlers ---

    def _activate_project(project_id: int):
        """Load project context, set active, navigate to Grid Prep."""
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(project_id, user=_current_user)
        if ctx is None:
            ui.notification_show("Project not found", type="error", duration=6)
            return
        if active_project is not None:
            active_project.set(ctx)
        ui.notification_show(f"Opened project: {ctx['name']}", type="message", duration=4)
        if nav_callback:
            nav_callback("Grid Prep")

    @reactive.effect
    @reactive.event(input.open_project_btn)
    def _show_open_project_modal():
        project_data = projects.get()
        if not project_data:
            m = ui.modal(
                ui.p("No projects yet. Create one first!", class_="text-muted"),
                title="Open Project",
                easy_close=True,
            )
            ui.modal_show(m)
            return

        project_links = []
        for p in project_data:
            project_links.append(
                ui.div(
                    ui.input_action_link(
                        f"open_proj_{p['id']}",
                        ui.span(p["name"], class_="fw-bold"),
                    ),
                    ui.span(
                        f" — {p['description'] or 'No description'}",
                        class_="text-muted small",
                    ),
                    ui.br(),
                    ui.code(p["work_dir"], class_="small text-muted"),
                    class_="mb-2 p-2 border rounded",
                )
            )

        m = ui.modal(
            *project_links,
            title="Open Project",
            easy_close=True,
        )
        ui.modal_show(m)

    @reactive.effect
    def _register_open_proj_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_open_proj_handler(p["id"])

    def _make_open_proj_handler(pid: int):
        @reactive.effect
        @reactive.event(input[f"open_proj_{pid}"])
        def _open():
            ui.modal_remove()
            _activate_project(pid)

    @reactive.effect
    def _register_project_link_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_project_link_handler(p["id"])

    def _make_project_link_handler(pid: int):
        @reactive.effect
        @reactive.event(input[f"project_{pid}"])
        def _click():
            _activate_project(pid)

    # --- Import grid handlers ---

    @reactive.effect
    @reactive.event(input.import_grid_btn)
    def _show_import_grid_modal():
        project_data = projects.get()
        if not project_data:
            ui.notification_show("Create a project first before importing a grid", type="warning")
            return

        choices = {str(p["id"]): p["name"] for p in project_data}

        m = ui.modal(
            ui.input_select("import_project_id", "Target Project", choices=choices),
            ui.input_text(
                "import_grd_path",
                "Grid File Path (.grd)",
                placeholder="/path/to/grid.grd",
            ),
            ui.input_text(
                "import_grid_name",
                "Grid Name (optional)",
                placeholder="Leave blank to use filename",
            ),
            title="Import Grid",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button("import_confirm_btn", "Import", class_="btn-primary"),
                ui.modal_button("Cancel"),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.import_confirm_btn)
    def _do_import_grid():
        grd_path_str = input.import_grd_path()
        project_id_str = input.import_project_id()
        grid_name = input.import_grid_name().strip()

        if not grd_path_str:
            ui.notification_show("Grid file path is required", type="error", duration=6)
            return
        if not project_id_str:
            ui.notification_show("Select a target project", type="error", duration=6)
            return

        # Validate source file
        try:
            src_path = config.validate_path(grd_path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        # Look up project work_dir
        project_id = int(project_id_str)
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(project_id, user=_current_user)
        if ctx is None:
            ui.notification_show("Project not found", type="error", duration=6)
            return

        work_dir = Path(ctx["work_dir"])
        grid_dir = work_dir / "GRID"
        grid_dir.mkdir(parents=True, exist_ok=True)

        dest_path = grid_dir / src_path.name
        if not grid_name:
            grid_name = src_path.stem

        try:
            shutil.copy2(src_path, dest_path)
        except Exception as e:
            ui.notification_show(f"Failed to copy grid file: {e}", type="error", duration=6)
            return

        # Create DB record
        try:
            with db_session() as db:
                grid = Grid(
                    project_id=project_id,
                    name=grid_name,
                    grd_file=f"GRID/{src_path.name}",
                )
                db.add(grid)

            ui.notification_show(f"Imported grid '{grid_name}' into project", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()
        except Exception as e:
            ui.notification_show(f"Failed to create grid record: {e}", type="error", duration=6)

    # --- Export/Import/Clone project handlers ---

    @reactive.effect
    def _register_export_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_export_handler(p["id"], p["name"])

    def _make_export_handler(pid: int, pname: str):
        @reactive.effect
        @reactive.event(input[f"export_{pid}"])
        async def _export():
            await _do_export(pid, pname)

    async def _do_export(project_id: int, project_name: str):
        """Export a project as ZIP and trigger browser download."""
        import base64

        from shyfem_ui.services.project_context import load_project_context
        from shyfem_ui.services.project_export import export_project

        ctx = load_project_context(project_id, user=_current_user)
        if ctx is None:
            ui.notification_show("Project not found", type="error", duration=6)
            return

        work_dir = Path(ctx["work_dir"])
        if not work_dir.is_dir():
            ui.notification_show("Project directory not found", type="error", duration=6)
            return

        meta = {
            "name": ctx["name"],
            "description": ctx.get("description"),
            "grids": ctx.get("grids", []),
            "simulations": ctx.get("simulations", []),
        }

        try:
            zip_buf = export_project(work_dir, meta)
            b64 = base64.b64encode(zip_buf.read()).decode("ascii")
            filename = f"{_safe_filename(project_name)}.zip"
            await session.send_custom_message(
                "download_file",
                {"href": f"data:application/zip;base64,{b64}", "filename": filename},
            )
            ui.notification_show(f"Exported '{project_name}'", type="message", duration=4)
        except Exception as e:
            ui.notification_show(f"Export failed: {e}", type="error", duration=6)

    @reactive.effect
    def _register_clone_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_clone_handler(p["id"], p["name"])

    def _make_clone_handler(pid: int, pname: str):
        @reactive.effect
        @reactive.event(input[f"clone_{pid}"])
        def _clone():
            _do_clone(pid, pname)

    def _do_clone(project_id: int, project_name: str):
        """Clone a project."""
        from shyfem_ui.services.project_context import load_project_context
        from shyfem_ui.services.project_export import clone_project

        ctx = load_project_context(project_id, user=_current_user)
        if ctx is None:
            ui.notification_show("Project not found", type="error", duration=6)
            return

        work_dir = Path(ctx["work_dir"])
        if not work_dir.is_dir():
            ui.notification_show("Project directory not found", type="error", duration=6)
            return

        meta = {
            "name": ctx["name"],
            "description": ctx.get("description"),
            "grids": ctx.get("grids", []),
            "simulations": ctx.get("simulations", []),
        }

        try:
            result = clone_project(work_dir, meta, config.work_dir)
        except Exception as e:
            ui.notification_show(f"Clone failed: {e}", type="error", duration=6)
            return

        try:
            with db_session() as db:
                from shyfem_ui.middleware.session_auth import get_current_user

                user = get_current_user()
                project = Project(
                    name=result["name"],
                    description=result.get("description"),
                    work_dir=str(result["work_dir"]),
                    owner_id=user["id"] if user else None,
                )
                db.add(project)
                db.flush()

                grid_name_to_id = {}
                for g in result.get("grids", []):
                    grid = Grid(
                        project_id=project.id,
                        name=g["name"],
                        description=g.get("description"),
                        grd_file=g.get("grd_file"),
                        bas_file=g.get("bas_file"),
                    )
                    db.add(grid)
                    db.flush()
                    grid_name_to_id[g["name"]] = grid.id

                for s in result.get("simulations", []):
                    sim = Simulation(
                        project_id=project.id,
                        grid_id=grid_name_to_id.get(s.get("grid_name")),
                        name=s["name"],
                        description=s.get("description"),
                        str_file=s.get("str_file"),
                    )
                    db.add(sim)

            ui.notification_show(f"Cloned '{project_name}' as '{result['name']}'", type="message", duration=4)
            _refresh_projects()

        except Exception as e:
            wd = result.get("work_dir")
            if wd and Path(wd).exists():
                shutil.rmtree(wd, ignore_errors=True)
            ui.notification_show(f"Clone failed: {e}", type="error", duration=6)

    # Import project from ZIP
    @reactive.effect
    @reactive.event(input.import_project_btn)
    def _show_import_project_modal():
        m = ui.modal(
            ui.p("Upload a project ZIP archive (exported from SHYFEM UI)."),
            ui.input_file(
                "import_zip_file",
                "Select ZIP file",
                accept=[".zip"],
                multiple=False,
            ),
            title="Import Project",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "confirm_import_project_btn",
                    "Import",
                    class_="btn-primary",
                ),
                ui.modal_button("Cancel"),
            ),
        )
        ui.modal_show(m)

    @reactive.effect
    @reactive.event(input.confirm_import_project_btn)
    def _do_import_project():
        file_info = input.import_zip_file()
        if not file_info:
            ui.notification_show("No file selected", type="error", duration=6)
            return

        file_path = file_info[0]["datapath"]

        from shyfem_ui.services.project_export import import_project

        try:
            with open(file_path, "rb") as f:
                zip_data = BytesIO(f.read())
            result = import_project(zip_data, config.work_dir)
        except ValueError as e:
            ui.notification_show(f"Import failed: {e}", type="error", duration=6)
            return
        except Exception as e:
            ui.notification_show(f"Import failed: {e}", type="error", duration=6)
            return

        try:
            with db_session() as db:
                from shyfem_ui.middleware.session_auth import get_current_user

                user = get_current_user()
                project = Project(
                    name=result["name"],
                    description=result.get("description"),
                    work_dir=str(result["work_dir"]),
                    owner_id=user["id"] if user else None,
                )
                db.add(project)
                db.flush()

                grid_name_to_id = {}
                for g in result.get("grids", []):
                    grid = Grid(
                        project_id=project.id,
                        name=g["name"],
                        description=g.get("description"),
                        grd_file=g.get("grd_file"),
                        bas_file=g.get("bas_file"),
                        num_nodes=g.get("num_nodes"),
                        num_elements=g.get("num_elements"),
                        num_layers=g.get("num_layers"),
                        min_depth=g.get("min_depth"),
                        max_depth=g.get("max_depth"),
                    )
                    db.add(grid)
                    db.flush()
                    grid_name_to_id[g["name"]] = grid.id

                for s in result.get("simulations", []):
                    sim = Simulation(
                        project_id=project.id,
                        grid_id=grid_name_to_id.get(s.get("grid_name")),
                        name=s["name"],
                        description=s.get("description"),
                        str_file=s.get("str_file"),
                        start_time=s.get("start_time"),
                        end_time=s.get("end_time"),
                        time_step=s.get("time_step"),
                        mpi_enabled=s.get("mpi_enabled", False),
                        mpi_np=s.get("mpi_np", 1),
                    )
                    db.add(sim)

            ui.notification_show(f"Imported project '{result['name']}'", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()

        except Exception as e:
            wd = result.get("work_dir")
            if wd and Path(wd).exists():
                shutil.rmtree(wd, ignore_errors=True)
            ui.notification_show(f"Import failed: {e}", type="error", duration=6)

    # ------------------------------------------------------------------
    # Share project handlers
    # ------------------------------------------------------------------

    from shyfem_ui.services.sharing_service import SharingService

    # Dedup set prevents effect accumulation (Shiny for Python does not
    # auto-destroy child effects when a parent @reactive.effect re-runs).
    _registered_handlers: set = set()

    @reactive.effect
    def _register_share_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_share_handler(p["id"], p["name"])
            _make_confirm_share_handler(p["id"])

    def _make_share_handler(pid: int, pname: str):
        key = f"share_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _share():
            _show_share_modal(pid, pname)

    def _make_confirm_share_handler(pid: int):
        key = f"confirm_share_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _do_share():
            uid = int(input.share_user_id())
            role = input.share_role()
            svc_inner = SharingService()
            svc_inner.share_project(pid, uid, role)
            ui.notification_show("User added", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()

    def _show_share_modal(project_id: int, project_name: str):
        svc = SharingService()
        user_id = _current_user["id"] if _current_user else 0
        shareable = svc.list_shareable_users(project_id, exclude_user_id=user_id)
        perms = svc.list_permissions(project_id)
        perm_data = _build_permissions_table_data(perms)

        # Build user choices
        user_choices = {
            str(u["id"]): f"{u['username']} ({u['display_name'] or u['username']})"
            for u in shareable
        }

        # Build permissions table
        perm_rows = []
        for p in perm_data:
            perm_rows.append(
                ui.tags.tr(
                    ui.tags.td(p["display_name"]),
                    ui.tags.td(ui.span(p["role"], class_="badge bg-info")),
                    ui.tags.td(
                        ui.input_action_link(
                            f"unshare_{project_id}_{p['user_id']}",
                            "Remove",
                            class_="btn btn-sm btn-outline-danger",
                        ),
                    ),
                )
            )

        if perm_rows:
            perm_table = ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("User"),
                        ui.tags.th("Role"),
                        ui.tags.th(""),
                    )
                ),
                ui.tags.tbody(*perm_rows),
                class_="table table-sm",
            )
        else:
            perm_table = ui.p("No users shared with yet.", class_="text-muted small")

        if user_choices:
            user_select = ui.div(
                ui.input_select("share_user_id", "User", choices=user_choices),
                ui.input_select(
                    "share_role",
                    "Role",
                    choices={"viewer": "Viewer", "editor": "Editor"},
                ),
                ui.input_action_button(
                    f"confirm_share_{project_id}",
                    "Share",
                    class_="btn-primary mt-2",
                ),
            )
        else:
            user_select = ui.p("No users available to share with.", class_="text-muted small")

        m = ui.modal(
            ui.h6("Current Access"),
            perm_table,
            ui.hr(),
            ui.h6("Add User"),
            user_select,
            title=f"Share '{project_name}'",
            easy_close=True,
        )
        ui.modal_remove()
        ui.modal_show(m)

        # Register unshare handlers for existing permissions
        for p in perm_data:
            _make_unshare_handler(project_id, p["user_id"])

    def _make_unshare_handler(project_id: int, target_user_id: int):
        key = f"unshare_{project_id}_{target_user_id}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _unshare():
            svc = SharingService()
            svc.unshare_project(project_id, target_user_id)
            ui.notification_show("Access removed", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()

    return {
        "projects": projects,
    }
