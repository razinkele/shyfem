"""Test-specific Shiny app entry point.

Patches the run module's server to avoid reactive effects that block Shiny's
async event loop.  The run module has many reactive.effect + render functions
whose interplay deadlocks the single-threaded event loop during the initial
flush cycle.  We replace run_server with a lightweight version that only
initialises state (so the UI elements exist) without the polling/refresh
effects.

Uses the new sidebar layout (matching app.py) so that E2E selectors
like `.sf-nav-item[data-nav='...']` and `#sf-sidebar` work correctly.
"""

import argparse
import sys
from pathlib import Path

from shiny import App, module, reactive, render, ui

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shyfem_ui.app import SIDEBAR_GROUPS, _HEAD_EXTRAS, _build_sidebar_nav
from shyfem_ui.config import Config, get_config, set_config
from shyfem_ui.db.base import init_db
from shyfem_ui.pages import (
    admin,
    compare,
    ensemble,
    files,
    grid_prep,
    home,
    ibm,
    mesh_builder,
    partitioning,
    physics,
    postprocess,
    run,
    simulation,
    tutorial,
    visualize,
)
from shyfem_ui.services.auth_service import AuthService
from shyfem_ui.services.job_queue import JobQueue, JobQueueFactory


@module.server
def _stub_run_server(
    input, output, session, config: Config, job_queue: JobQueue = None,
):
    """Minimal run_server that doesn't block the event loop.

    Provides just enough state for the UI elements to render without
    the polling/refresh effects that deadlock the async event loop.
    """
    active_jobs_data = reactive.value([])
    all_jobs_data = reactive.value([])
    selected_job_id = reactive.value(None)
    selected_job = reactive.value(None)
    log_content = reactive.value("")

    @render.ui
    def dashboard():
        return ui.p("No active jobs.", class_="text-muted text-center")

    @render.ui
    def job_details_panel():
        return ui.p("Select a job.", class_="text-muted")

    # Render the MPI checkbox unconditionally so it has a stable position in
    # the DOM, then have a separate output for the conditional mpi_np input.
    # This avoids the @render.ui re-run not picking up input.mpi_enabled
    # changes when the checkbox is itself defined inside the same render.

    @render.ui
    def shyfem_options():
        """MPI/solver options for shyfem (reactive, no polling)."""
        try:
            tool = input.tool_select()
        except Exception:
            tool = None
        if tool != "shyfem":
            return ui.span()
        return ui.div(
            ui.h6("MPI Options"),
            ui.input_checkbox("mpi_enabled", "Enable MPI", value=False),
            ui.output_ui("mpi_np_control"),
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
        )

    @render.ui
    def mpi_np_control():
        """Show the process-count input only when MPI is enabled."""
        try:
            enabled = bool(input.mpi_enabled())
        except Exception:
            return ui.span()
        if not enabled:
            return ui.span()
        return ui.input_numeric(
            "mpi_np", "Number of Processes", value=4, min=2, max=128,
        )

    @render.ui
    def solver_hint():
        return ui.span()


def create_test_app(config=None):
    """Create a Shiny app suitable for browser testing."""
    if config is None:
        config = get_config()
    else:
        set_config(config)

    config.ensure_work_dir()
    init_db()

    job_queue = JobQueueFactory.create(
        mode="local",
        shyfem_dir=config.shyfem_dir,
        max_workers=config.max_workers,
    )

    sidebar = _build_sidebar_nav()

    # Top bar (simplified for tests)
    topbar = ui.div(
        ui.div(
            ui.tags.i(class_="bi bi-tsunami me-2", style="font-size:1.3rem"),
            ui.span("SHYFEM Workbench", style="font-weight:600;font-size:1rem"),
            class_="d-flex align-items-center",
        ),
        class_="sf-topbar",
    )

    # Content panels — one div per page, toggled by CSS (matches app.py)
    content_panels = ui.div(
        ui.div(home.home_ui("home"), id="sf-page-Dashboard", class_="sf-page active"),
        ui.div(tutorial.tutorial_ui("tutorial"), id="sf-page-Tutorial", class_="sf-page"),
        ui.div(
            mesh_builder.mesh_builder_ui("mesh_builder"),
            id="sf-page-Mesh-Builder",
            class_="sf-page",
        ),
        ui.div(grid_prep.grid_prep_ui("grid_prep"), id="sf-page-Grid-Prep", class_="sf-page"),
        ui.div(
            partitioning.partitioning_ui("partitioning"),
            id="sf-page-Partitioning",
            class_="sf-page",
        ),
        ui.div(
            physics.physics_ui("physics"), id="sf-page-Physics", class_="sf-page"
        ),
        ui.div(
            simulation.simulation_ui("simulation"), id="sf-page-Simulation", class_="sf-page"
        ),
        ui.div(run.run_ui("run"), id="sf-page-Run", class_="sf-page"),
        ui.div(ibm.ibm_ui("ibm"), id="sf-page-IBM", class_="sf-page"),
        ui.div(
            postprocess.postprocess_ui("postprocess"),
            id="sf-page-Post-Process",
            class_="sf-page",
        ),
        ui.div(
            visualize.visualize_ui("visualize"), id="sf-page-Visualize", class_="sf-page"
        ),
        ui.div(compare.compare_ui("compare"), id="sf-page-Compare", class_="sf-page"),
        ui.div(ensemble.ensemble_ui("ensemble"), id="sf-page-Ensemble", class_="sf-page"),
        ui.div(files.files_ui("files"), id="sf-page-Files", class_="sf-page"),
        ui.div(admin.admin_ui("admin"), id="sf-page-Admin", class_="sf-page"),
        class_="sf-content",
    )

    app_ui = ui.page_fillable(
        ui.head_content(_HEAD_EXTRAS),
        topbar,
        ui.div(
            sidebar,
            content_panels,
            class_="sf-layout",
        ),
        title="SHYFEM Workbench",
    )

    def server(input, output, session):
        active_project = reactive.value(None)
        tutorial_context = reactive.value(None)

        home.home_server("home", config, job_queue,
                         active_project=active_project, nav_callback=None)
        tutorial.tutorial_server("tutorial", config,
                                 active_project=active_project,
                                 nav_callback=None,
                                 tutorial_context=tutorial_context)
        mesh_builder.mesh_builder_server("mesh_builder", config,
                                         active_project=active_project,
                                         tutorial_context=tutorial_context)
        grid_prep.grid_prep_server("grid_prep", config,
                                   active_project=active_project,
                                   tutorial_context=tutorial_context)
        partitioning.partitioning_server("partitioning", config,
                                         active_project=active_project)
        physics.physics_server("physics", config, active_project=active_project)
        simulation.simulation_server("simulation", config,
                                     active_project=active_project,
                                     tutorial_context=tutorial_context)
        ibm.ibm_server("ibm", config, active_project=active_project)
        # Use stub run_server to avoid event loop deadlock
        _stub_run_server("run", config, job_queue)
        postprocess.postprocess_server("postprocess", config,
                                       active_project=active_project,
                                       tutorial_context=tutorial_context)
        visualize.visualize_server("visualize", config,
                                   active_project=active_project,
                                   tutorial_context=tutorial_context)
        compare.compare_server("compare", config, job_queue,
                               active_project=active_project)
        ensemble.ensemble_server("ensemble", config, job_queue,
                                 active_project=active_project)
        files.files_server("files", config, active_project=active_project)
        auth_service = AuthService()
        admin.admin_server("admin", config, auth_service)

    return App(app_ui, server, static_assets=Path(__file__).parent.parent / "shyfem_ui" / "www")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    app = create_test_app()

    from shiny import run_app
    run_app(app, host=args.host, port=args.port)
