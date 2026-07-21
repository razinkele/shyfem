"""Home/Dashboard page for SHYFEM UI."""

import logging
import shutil
from datetime import datetime
from io import BytesIO
from pathlib import Path

from shiny import module, reactive, render, ui
from sqlalchemy import or_

from shyfem_ui.config import Config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, Simulation
from shyfem_ui.models.user import ROLE_ADMIN, ProjectPermission
from shyfem_ui.services.job_queue import JobQueue, JobStatus
from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

logger = logging.getLogger(__name__)


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
    if role == ROLE_ADMIN:
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


def _dashboard_projects(db, user: dict | None, is_server_mode: bool) -> list:
    """Return the Project rows to show on the dashboard, fail-CLOSED on an
    unresolved identity in server mode.

    Behind the Shiny Server proxy the reactive layer runs with ``user=None``
    until the ``_wsauth`` token resolves. A ``None`` user in server mode must
    see NOTHING — otherwise the first reactive flush of every session lists
    every user's recent projects (read-isolation failure). In local desktop
    mode there is no auth, so ``None`` legitimately lists all projects.
    """
    if is_server_mode and user is None:
        return []
    if user and user.get("role") != ROLE_ADMIN:
        return get_visible_projects(db, user["id"], user["role"])
    return db.query(Project).order_by(Project.updated_at.desc()).limit(10).all()


def recent_jobs_session_id(is_server_mode: bool, show_all: bool, user: dict | None, session_id):
    """Decide which session_id to filter the Dashboard's recent-jobs list by.

    Returns None to list every session's jobs, or ``session_id`` to scope to the
    current session. Local (single-user) mode always lists all. In server mode
    only admins may list every user's jobs — a non-admin (or unresolved WS
    identity) asking to "show all" is downgraded to their own session (IDOR
    guard).
    """
    if not is_server_mode:
        return None
    if show_all and not (user and user.get("role") == ROLE_ADMIN):
        show_all = False
    return None if show_all else session_id


def _should_show_share_button(project: dict, user: dict | None) -> bool:
    """Return True if user should see the Share button for this project.

    Only project owners and admins can share.
    """
    if user is None:
        return False
    if user.get("role") == ROLE_ADMIN:
        return True
    return project.get("owner_id") == user.get("id")


def _sharing_denied_reason(project_id: int, user: dict | None, session_factory=None) -> str | None:
    """Return a user-facing error if ``user`` may NOT modify sharing, else None.

    Only project owners and admins may share or unshare. The rendered Share
    button is only a visibility hint; a client can fire ``confirm_share_<pid>``
    / ``unshare_<pid>_<uid>`` directly over the WebSocket, so the mutation
    handlers must re-check server-validated identity. Distinguishes an
    unresolved actor (not signed in / WS identity missing) from a resolved but
    unauthorized one so each case surfaces its own notification.

    Sharing is a mutation, so the central tutorial read-only policy applies
    here too: a ROLE_TUTORIAL account that owns a project (e.g. a regular user
    later demoted to tutorial — ``update_user`` changes the role but leaves
    ownership/permission rows intact) would otherwise pass the owner check and
    mutate sharing. Deny it before the owner check, from the server-validated
    ``user`` dict, mirroring ``editor_denied_reason``.
    """
    from shyfem_ui.models.user import ROLE_TUTORIAL
    from shyfem_ui.services.access_control import _TUTORIAL_READONLY_MSG, check_project_access

    if user is None:
        return "You must be signed in to manage sharing."
    if user.get("role") == ROLE_TUTORIAL:
        return _TUTORIAL_READONLY_MSG
    if (
        check_project_access(project_id, user, min_role="owner", session_factory=session_factory)
        is None
    ):
        return "You are not authorized to manage sharing for this project."
    return None


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
                        ui.TagList(
                            ui.tags.i(class_="bi bi-box-arrow-in-down me-2"), "Import Project"
                        ),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.hr(),
                    ui.input_action_button(
                        "tutorial_btn",
                        ui.TagList(
                            ui.tags.i(class_="bi bi-mortarboard me-2"), "Mar Menor Tutorial"
                        ),
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
    current_user=None,
) -> None:
    """Dashboard page server logic."""
    projects = reactive.value([])
    recent_jobs_list = reactive.value([])
    _session_id = str(id(session))
    _is_server_mode = config.deployment_mode == "server"

    # Dedup set prevents effect accumulation (Shiny for Python does not
    # auto-destroy child effects when a parent @reactive.effect re-runs).
    # Per-session (declared inside home_server); keys are prefix-namespaced
    # (open_proj_, project_, details_, export_, clone_, share_, confirm_share_, unshare_)
    # so all per-project handler factories share this one set without collision.
    _registered_handlers: set = set()

    def _user():
        # Server-validated user in the WS scope (None in local mode).
        return current_user() if current_user is not None else None

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
            logger.exception("Failed to load initial dashboard data")
            ui.notification_show(f"Error loading data: {e}", type="error", duration=6)

    def _refresh_projects():
        user = _user()
        with db_session() as db:
            project_list = _dashboard_projects(db, user, _is_server_mode)
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
                logger.debug("show_all_jobs input not yet rendered, defaulting to False")
                show_all = False  # input not yet rendered on startup
            # IDOR guard (admin-only "show all") lives in recent_jobs_session_id.
            sid = recent_jobs_session_id(_is_server_mode, show_all, _user(), _session_id)
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
            if _should_show_share_button(p, (_user())):
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
                    ui.tags.td(
                        ui.code(config.display_path(p["work_dir"], _user()), class_="small")
                    ),
                    ui.tags.td(
                        p["updated_at"].strftime("%Y-%m-%d %H:%M") if p["updated_at"] else "-"
                    ),
                    ui.tags.td(
                        ui.input_action_link(
                            f"details_{p['id']}",
                            "Details",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
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

        logger.info("User creating project %r in %r", name, work_dir)

        if not name:
            ui.notification_show("Project name is required", type="error", duration=6)
            return

        if not work_dir:
            ui.notification_show("Project directory is required", type="error", duration=6)
            return

        # Fail-closed: in server mode an unresolved identity must not create an
        # owner_id=None orphan project.
        from shyfem_ui.services.access_control import identity_denied_reason

        user = _user()
        _denied = identity_denied_reason(user)
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        # Validate and create directory. In server mode, root the project under
        # the owner's home sandbox (user_data_root/{username}/<name>), deriving the
        # folder from the chosen basename so a typed absolute/`..` path cannot
        # escape into the shared work_dir or another user's data.
        try:
            if config.deployment_mode == "server" and user is not None:
                candidate = config.user_data_root / user["username"] / Path(work_dir).name
                project_path = config.confine_path(candidate, user, for_write=True)
            else:
                project_path = config.validate_save_path(work_dir)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        try:
            project_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.exception("Failed to create project directory %s", project_path)
            ui.notification_show(f"Failed to create directory: {e}", type="error", duration=6)
            return

        # Create project in database
        try:
            with db_session() as db:
                project = Project(
                    name=name,
                    description=description or None,
                    work_dir=str(project_path),
                    owner_id=user["id"] if user else None,
                )
                db.add(project)

            ui.notification_show(
                f"Project '{name}' created successfully", type="message", duration=4
            )
            ui.modal_remove()
            _refresh_projects()

        except Exception as e:
            logger.exception("Failed to create project %r", name)
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
        logger.info("User creating tutorial project %r", name)
        if not name:
            ui.notification_show("Project name is required", type="error", duration=6)
            return

        # Fail-closed: in server mode an unresolved identity must not create an
        # owner_id=None orphan project.
        from shyfem_ui.services.access_control import identity_denied_reason

        user = _user()
        _denied = identity_denied_reason(user)
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        # Check source directory exists
        mar_menor_src = config.testcases_dir / "mar_menor"
        if not mar_menor_src.is_dir():
            ui.notification_show(
                f"Tutorial source not found: {mar_menor_src}", type="error", duration=6
            )
            return

        # Create project directory
        project_path = config.work_dir / name
        try:
            config.ensure_work_dir()
            if project_path.exists():
                ui.notification_show(
                    f"Directory already exists: {project_path}", type="error", duration=6
                )
                return
            shutil.copytree(mar_menor_src, project_path)
        except Exception as e:
            logger.exception("Failed to copy tutorial files to %s", project_path)
            ui.notification_show(f"Failed to copy tutorial files: {e}", type="error", duration=6)
            return

        # Create database records
        try:
            with db_session() as db:
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

            ctx = load_project_context(project_id, user=(_user()))
            if ctx and active_project is not None:
                active_project.set(ctx)

            ui.notification_show(
                f"Tutorial project '{name}' created successfully!", type="message", duration=4
            )
            ui.modal_remove()
            _refresh_projects()
            if nav_callback:
                nav_callback("Tutorial")

        except Exception as e:
            # Clean up copied directory on DB failure
            if project_path.exists():
                shutil.rmtree(project_path, ignore_errors=True)
            logger.exception("Failed to save tutorial project %r to database", name)
            ui.notification_show(
                f"Failed to create tutorial project: {e}", type="error", duration=6
            )

    # --- Active project handlers ---

    def _activate_project(project_id: int):
        """Load project context, set active, navigate to Grid Prep."""
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(project_id, user=(_user()))
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
                    ui.code(config.display_path(p["work_dir"], _user()), class_="small text-muted"),
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
        key = f"open_proj_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _open():
            ui.modal_remove()
            _activate_project(pid)

    @reactive.effect
    def _register_details_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_details_handler(p["id"])

    def _make_details_handler(pid: int):
        key = f"details_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _show_details():
            from shyfem_ui.services.project_context import load_project_context

            # The viewer-level read gate is THIS call (fail-closed in server
            # mode). Handler registration filtering via projects.get() is NOT
            # a security boundary: _registered_handlers never shrinks, so a
            # handler registered while a project was shared outlives the
            # share's revocation for the rest of the session.
            ctx = load_project_context(pid, user=(_user()))
            if ctx is None:
                ui.notification_show("Project not found or access denied", type="error", duration=6)
                return

            def _fmt(value, suffix=""):
                return f"{value}{suffix}" if value is not None else "—"

            grid_rows = [
                ui.tags.tr(
                    ui.tags.td(g["name"]),
                    ui.tags.td(_fmt(g["num_layers"])),
                    ui.tags.td(_fmt(g["min_depth"], " m")),
                    ui.tags.td(_fmt(g["max_depth"], " m")),
                )
                for g in ctx["grids"]
            ]
            sim_rows = [
                ui.tags.tr(
                    ui.tags.td(s["name"]),
                    ui.tags.td(s["start_time"] or "—"),
                    ui.tags.td(s["end_time"] or "—"),
                    ui.tags.td(_fmt(s["time_step"], " s")),
                )
                for s in ctx["simulations"]
            ]
            grids_block = (
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(
                            ui.tags.th("Name"),
                            ui.tags.th("Layers"),
                            ui.tags.th("Min depth"),
                            ui.tags.th("Max depth"),
                        )
                    ),
                    ui.tags.tbody(*grid_rows),
                    class_="table table-sm",
                )
                if grid_rows
                else ui.p("No grids imported.", class_="text-muted")
            )
            sims_block = (
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(
                            ui.tags.th("Name"),
                            ui.tags.th("Start"),
                            ui.tags.th("End"),
                            ui.tags.th("Time step"),
                        )
                    ),
                    ui.tags.tbody(*sim_rows),
                    class_="table table-sm",
                )
                if sim_rows
                else ui.p("No simulations.", class_="text-muted")
            )
            m = ui.modal(
                ui.h6("Grids"),
                grids_block,
                ui.h6("Simulations"),
                sims_block,
                title=f"Project: {ctx['name']}",
                easy_close=True,
                footer=ui.modal_button("Close"),
                size="l",
            )
            ui.modal_show(m)

    @reactive.effect
    def _register_project_link_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_project_link_handler(p["id"])

    def _make_project_link_handler(pid: int):
        key = f"project_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
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

        logger.info("User importing grid %r into project %s", grd_path_str, project_id_str)

        if not grd_path_str:
            ui.notification_show("Grid file path is required", type="error", duration=6)
            return
        if not project_id_str:
            ui.notification_show("Select a target project", type="error", duration=6)
            return

        # Validate source file (confined to the requesting user's sandbox)
        _usr = _user()
        try:
            src_path = config.confine_path(grd_path_str, _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error", duration=6)
            return

        project_id = int(project_id_str)

        # Importing a grid WRITES into the target project, so require editor
        # access (load_project_context below is only a viewer-level read gate).
        from shyfem_ui.services.access_control import editor_denied_reason

        _denied = editor_denied_reason(project_id, _user(), min_role="editor")
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        # Look up project work_dir
        from shyfem_ui.services.project_context import load_project_context

        ctx = load_project_context(project_id, user=(_user()))
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
            logger.exception("Failed to copy grid file %s to %s", src_path, dest_path)
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

            ui.notification_show(
                f"Imported grid '{grid_name}' into project", type="message", duration=4
            )
            ui.modal_remove()
            _refresh_projects()
        except Exception as e:
            logger.exception(
                "Failed to create grid record for %r in project %s", grid_name, project_id
            )
            ui.notification_show(f"Failed to create grid record: {e}", type="error", duration=6)

    # --- Export/Import/Clone project handlers ---

    @reactive.effect
    def _register_export_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_export_handler(p["id"], p["name"])

    def _make_export_handler(pid: int, pname: str):
        key = f"export_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        async def _export():
            await _do_export(pid, pname)

    async def _do_export(project_id: int, project_name: str):
        """Export a project as ZIP and trigger browser download."""
        import base64

        from shyfem_ui.services.project_context import load_project_context
        from shyfem_ui.services.project_export import export_project

        logger.info("User exporting project %s %r", project_id, project_name)

        ctx = load_project_context(project_id, user=(_user()))
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
            zip_buf = await export_project(work_dir, meta)
            b64 = base64.b64encode(zip_buf.read()).decode("ascii")
            filename = f"{_safe_filename(project_name)}.zip"
            await session.send_custom_message(
                "download_file",
                {"href": f"data:application/zip;base64,{b64}", "filename": filename},
            )
            ui.notification_show(f"Exported '{project_name}'", type="message", duration=4)
        except Exception as e:
            logger.exception("Failed to export project %s %r", project_id, project_name)
            ui.notification_show(f"Export failed: {e}", type="error", duration=6)

    @reactive.effect
    def _register_clone_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_clone_handler(p["id"], p["name"])

    def _make_clone_handler(pid: int, pname: str):
        key = f"clone_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _clone():
            _do_clone(pid, pname)

    def _do_clone(project_id: int, project_name: str):
        """Clone a project."""
        from shyfem_ui.services.project_context import load_project_context
        from shyfem_ui.services.project_export import clone_project

        logger.info("User cloning project %s %r", project_id, project_name)

        ctx = load_project_context(project_id, user=(_user()))
        if ctx is None:
            ui.notification_show("Project not found", type="error", duration=6)
            return

        # Cloning creates a NEW owned project (a write). load_project_context
        # above is only a viewer-level read gate, so also fail closed on an
        # unresolved identity AND on a read-only tutorial account before writing.
        from shyfem_ui.services.access_control import identity_denied_reason

        _denied = identity_denied_reason(_user())
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
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
            logger.exception("Failed to clone project %s %r", project_id, project_name)
            ui.notification_show(f"Clone failed: {e}", type="error", duration=6)
            return

        try:
            with db_session() as db:
                user = _user()
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

            ui.notification_show(
                f"Cloned '{project_name}' as '{result['name']}'", type="message", duration=4
            )
            _refresh_projects()

        except Exception as e:
            wd = result.get("work_dir")
            if wd and Path(wd).exists():
                shutil.rmtree(wd, ignore_errors=True)
            logger.exception("Failed to save cloned project %r to database", project_name)
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
    async def _do_import_project():
        file_info = input.import_zip_file()
        logger.info("User importing project from ZIP")
        if not file_info:
            ui.notification_show("No file selected", type="error", duration=6)
            return

        # Fail-closed: in server mode an unresolved identity must not create an
        # owner_id=None orphan project.
        from shyfem_ui.services.access_control import identity_denied_reason

        user = _user()
        _denied = identity_denied_reason(user)
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        file_path = file_info[0]["datapath"]
        size = file_info[0].get("size")
        max_size_bytes = config.max_upload_size_mb * 1024 * 1024
        if size is None:
            try:
                size = Path(file_path).stat().st_size
            except OSError as e:
                ui.notification_show(f"Import failed: {e}", type="error", duration=6)
                return
        if size > max_size_bytes:
            size_mb = size / (1024 * 1024)
            ui.notification_show(
                f"Import failed: ZIP is {size_mb:.1f} MB " f"(max {config.max_upload_size_mb} MB)",
                type="error",
                duration=6,
            )
            return

        from shyfem_ui.services.project_export import import_project

        # In server mode, extract under the owner's home sandbox so the imported
        # project is reachable once confine_path is enforced; local mode keeps
        # the shared work_dir.
        if config.deployment_mode == "server" and user is not None:
            import_root = config.user_data_root / user["username"]
            import_root.mkdir(parents=True, exist_ok=True)
        else:
            import_root = config.work_dir

        try:
            with open(file_path, "rb") as f:
                zip_data = BytesIO(f.read())
            result = await import_project(zip_data, import_root)
        except ValueError as e:
            logger.exception("Project ZIP import rejected: %s", file_path)
            ui.notification_show(f"Import failed: {e}", type="error", duration=6)
            return
        except Exception as e:
            logger.exception("Unexpected error importing project ZIP: %s", file_path)
            ui.notification_show(f"Import failed: {e}", type="error", duration=6)
            return

        try:
            with db_session() as db:
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
            logger.exception("Failed to save imported project to database")
            ui.notification_show(f"Import failed: {e}", type="error", duration=6)

    # ------------------------------------------------------------------
    # Share project handlers
    # ------------------------------------------------------------------

    from shyfem_ui.services.sharing_service import SharingService

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
            denied = _sharing_denied_reason(pid, _user())
            if denied:
                ui.notification_show(denied, type="error", duration=6)
                return
            uid = int(input.share_user_id())
            role = input.share_role()
            if role not in SharingService.SHAREABLE_ROLES:
                ui.notification_show(
                    "Invalid role; choose viewer or editor.", type="error", duration=6
                )
                return
            svc_inner = SharingService()
            svc_inner.share_project(pid, uid, role)
            ui.notification_show("User added", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()

    def _show_share_modal(project_id: int, project_name: str):
        _u = _user()
        denied = _sharing_denied_reason(project_id, _u)
        if denied:
            ui.notification_show(denied, type="error", duration=6)
            return
        svc = SharingService()
        user_id = _u["id"] if _u else 0
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
            denied = _sharing_denied_reason(project_id, _user())
            if denied:
                ui.notification_show(denied, type="error", duration=6)
                return
            svc = SharingService()
            svc.unshare_project(project_id, target_user_id)
            ui.notification_show("Access removed", type="message", duration=4)
            ui.modal_remove()
            _refresh_projects()

    return {
        "projects": projects,
    }
