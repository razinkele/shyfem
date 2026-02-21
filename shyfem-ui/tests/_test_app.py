"""Test-specific Shiny app entry point.

Patches the run module's server to avoid reactive effects that block Shiny's
async event loop.  The run module has many reactive.effect + render functions
whose interplay deadlocks the single-threaded event loop during the initial
flush cycle.  We replace run_server with a lightweight version that only
initialises state (so the UI elements exist) without the polling/refresh
effects.
"""

import argparse
import sys
from pathlib import Path

from shiny import App, module, reactive, render, ui

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shyfem_ui.config import Config, get_config, set_config
from shyfem_ui.db.base import init_db
from shyfem_ui.pages import (
    admin,
    compare,
    ensemble,
    files,
    grid_prep,
    home,
    partitioning,
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

    try:
        import shinyswatch
        theme = getattr(shinyswatch.theme, config.theme, shinyswatch.theme.flatly)
    except ImportError:
        theme = None

    app_ui = ui.page_fillable(
        ui.navset_tab(
            ui.nav_panel("Dashboard", home.home_ui("home")),
            ui.nav_panel("Grid Prep", grid_prep.grid_prep_ui("grid_prep")),
            ui.nav_panel("Partitioning", partitioning.partitioning_ui("partitioning")),
            ui.nav_panel("Simulation", simulation.simulation_ui("simulation")),
            ui.nav_panel("Run", run.run_ui("run")),
            ui.nav_panel("Post-Process", postprocess.postprocess_ui("postprocess")),
            ui.nav_panel("Visualize", visualize.visualize_ui("visualize")),
            ui.nav_panel("Compare", compare.compare_ui("compare")),
            ui.nav_panel("Ensemble", ensemble.ensemble_ui("ensemble")),
            ui.nav_panel("Files", files.files_ui("files")),
            ui.nav_panel("Tutorial", tutorial.tutorial_ui("tutorial")),
            ui.nav_panel("Admin", admin.admin_ui("admin")),
            id="main_navbar",
        ),
        title="SHYFEM Workbench",
        theme=theme,
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
        grid_prep.grid_prep_server("grid_prep", config,
                                   active_project=active_project,
                                   tutorial_context=tutorial_context)
        partitioning.partitioning_server("partitioning", config,
                                         active_project=active_project)
        simulation.simulation_server("simulation", config,
                                     active_project=active_project,
                                     tutorial_context=tutorial_context)
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

    return App(app_ui, server)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    app = create_test_app()

    from shiny import run_app
    run_app(app, host=args.host, port=args.port)
