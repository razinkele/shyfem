"""Test-specific Shiny app entry point.

Runs the REAL run_server. Historically it was stubbed out here because its
_auto_refresh effect self-invalidated (read-then-write of active_jobs_data
with identity-compared set()) and spun the reactive flush loop, freezing
every output in the session. That loop is fixed (dedup in _update_job_lists);
keeping the real module in the test app makes the E2E suite the regression
gate for it.

Uses the new sidebar layout (matching app.py) so that E2E selectors
like `.sf-nav-item[data-nav='...']` and `#sf-sidebar` work correctly.
"""

import argparse
import sys
from pathlib import Path

from shiny import App, reactive, ui

# Ensure the package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shyfem_ui.app import _HEAD_EXTRAS, _build_sidebar_nav

# deck.gl/MapLibre CDN bundle — without this the MapWidget div stays empty
# (the real app injects it at app.py's page root; mirror that here so
# browser tests can exercise the map canvas).
try:
    from shiny_deckgl import head_includes as deckgl_head_includes
except ImportError:  # pragma: no cover
    deckgl_head_includes = None
from shyfem_ui.config import get_config, set_config
from shyfem_ui.db.base import init_db
from shyfem_ui.pages import (
    about,
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
from shyfem_ui.services.job_queue import JobQueueFactory


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

    # Top bar (simplified for tests; includes the About/Changelog/Feedback
    # cluster so E2E can exercise the topbar modals)
    topbar = ui.div(
        ui.div(
            ui.tags.i(class_="bi bi-tsunami me-2", style="font-size:1.3rem"),
            ui.span("SHYFEM Workbench", style="font-weight:600;font-size:1rem"),
            class_="d-flex align-items-center",
        ),
        ui.div(
            about.about_topbar_ui("about"),
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
        ui.div(physics.physics_ui("physics"), id="sf-page-Physics", class_="sf-page"),
        ui.div(simulation.simulation_ui("simulation"), id="sf-page-Simulation", class_="sf-page"),
        ui.div(run.run_ui("run"), id="sf-page-Run", class_="sf-page"),
        ui.div(ibm.ibm_ui("ibm"), id="sf-page-IBM", class_="sf-page"),
        ui.div(
            postprocess.postprocess_ui("postprocess"),
            id="sf-page-Post-Process",
            class_="sf-page",
        ),
        ui.div(visualize.visualize_ui("visualize"), id="sf-page-Visualize", class_="sf-page"),
        ui.div(compare.compare_ui("compare"), id="sf-page-Compare", class_="sf-page"),
        ui.div(ensemble.ensemble_ui("ensemble"), id="sf-page-Ensemble", class_="sf-page"),
        ui.div(files.files_ui("files"), id="sf-page-Files", class_="sf-page"),
        ui.div(admin.admin_ui("admin"), id="sf-page-Admin", class_="sf-page"),
        class_="sf-content",
    )

    # Test-only debug hook: exposes window.__test_set_active_project so
    # Playwright can drive `active_project` from the test side. Mirrored
    # by a server-side @reactive.event listener on
    # input._test_set_active_project (defined inside `server` below).
    # This is scoped to the test app -- it never ships in production.
    _test_active_project_script = ui.tags.script("""
window.__test_set_active_project = function(projectDict) {
    Shiny.setInputValue(
        '_test_set_active_project',
        projectDict,
        {priority: 'event'}
    );
};
""")

    app_ui = ui.page_fillable(
        ui.head_content(_HEAD_EXTRAS, _test_active_project_script),
        # NOT inside head_content — HTMLDependency handles <head> injection
        # itself and wrapping it would silently drop the scripts.
        *([] if deckgl_head_includes is None else [deckgl_head_includes()]),
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

        # Test-only debug hook: lets Playwright tests inject an
        # active_project value directly via Shiny.setInputValue.
        # The corresponding JS-side helper is registered above in the
        # head_content extras (window.__test_set_active_project).
        @reactive.effect
        @reactive.event(input._test_set_active_project)
        def _test_active_project_hook():
            value = input._test_set_active_project()
            active_project.set(value if value else None)

        home.home_server(
            "home", config, job_queue, active_project=active_project, nav_callback=None
        )
        tutorial.tutorial_server(
            "tutorial",
            config,
            active_project=active_project,
            nav_callback=None,
            tutorial_context=tutorial_context,
        )
        mesh_builder.mesh_builder_server(
            "mesh_builder", config, active_project=active_project, tutorial_context=tutorial_context
        )
        grid_prep.grid_prep_server(
            "grid_prep", config, active_project=active_project, tutorial_context=tutorial_context
        )
        partitioning.partitioning_server("partitioning", config, active_project=active_project)
        physics.physics_server("physics", config, active_project=active_project)
        simulation.simulation_server(
            "simulation", config, active_project=active_project, tutorial_context=tutorial_context
        )
        ibm.ibm_server("ibm", config, active_project=active_project)
        # Real run_server: its _auto_refresh poll used to self-invalidate
        # (read-then-write of active_jobs_data with identity-compared set())
        # and spin the flush loop, freezing every output in the session --
        # which is why a stub existed here. The loop is fixed by dedup in
        # _update_job_lists; running the real thing makes the whole E2E
        # suite the regression gate for it.
        run.run_server("run", config, job_queue, active_project=active_project)
        postprocess.postprocess_server(
            "postprocess", config, active_project=active_project, tutorial_context=tutorial_context
        )
        visualize.visualize_server(
            "visualize", config, active_project=active_project, tutorial_context=tutorial_context
        )
        compare.compare_server("compare", config, job_queue, active_project=active_project)
        ensemble.ensemble_server("ensemble", config, job_queue, active_project=active_project)
        files.files_server("files", config, active_project=active_project)
        about.about_server("about", config)
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
