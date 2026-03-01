"""Sample data loading card and phase guidance for setup pages.

Provides a collapsible Bootstrap card with:
- Phase-specific guidance (what the page does, inputs/outputs, key parameters)
- "Load Sample Data" button using the Mar Menor tutorial dataset
- "Learn More in Tutorial" link
- For the simulation page: progressive STR file dropdown

Data is derived from tutorial_content.py — no duplication of descriptions.
"""

from __future__ import annotations

from shiny import ui

from shyfem_ui.tutorial_content import TUTORIAL_CONTENT

# ---------------------------------------------------------------------------
# Phase guidance text per page
# ---------------------------------------------------------------------------

PHASE_GUIDANCE: dict[str, dict[str, str]] = {
    "grid_prep": {
        "icon": "\U0001f5fa",  # world map emoji
        "title": "Grid Preparation",
        "what": (
            "Convert raw mesh files (.grd) into preprocessed basin files (.bas) "
            "that SHYFEM can use. Inspect grid quality, node/element statistics, "
            "and boundary assignments."
        ),
        "inputs": ".grd mesh file (finite element grid)",
        "outputs": ".bas preprocessed basin file",
        "key_params": "Optimize bandwidth (-opti), renumber nodes (-renumber)",
        "sample_desc": (
            "Mar Menor lagoon coarse mesh (~1,300 nodes, ~2,400 triangular elements). "
            "A good starting grid for learning the SHYFEM workflow."
        ),
    },
    "simulation": {
        "icon": "\u2699\ufe0f",  # gear emoji
        "title": "Simulation Configuration",
        "what": (
            "Edit .str parameter files that control every aspect of a SHYFEM "
            "simulation: time stepping, physics, forcing, output intervals, "
            "and boundary conditions."
        ),
        "inputs": ".str parameter file",
        "outputs": "Modified .str file ready for execution",
        "key_params": "itanf/itend (time window), idt (timestep), ilin (linearization)",
        "sample_desc": (
            "14 progressive STR files from the Mar Menor tutorial, building from "
            "a minimal run to full 3D baroclinic non-linear simulation."
        ),
    },
    "run": {
        "icon": "\u25b6\ufe0f",  # play button emoji
        "title": "Run Simulation",
        "what": (
            "Submit SHYFEM simulation jobs, monitor progress in real time, "
            "manage MPI parallel execution, and review job history."
        ),
        "inputs": ".str parameter file + preprocessed .bas basin",
        "outputs": ".shy binary output files (water level, velocity, tracers)",
        "key_params": "MPI processes, solver selection (SPARSKIT/PETSc)",
        "sample_desc": (
            "Mar Menor wind-driven simulation (mm_hyd_03.str) with bottom friction. "
            "Runs in ~3 seconds on a single core."
        ),
    },
    "postprocess": {
        "icon": "\U0001f4ca",  # bar chart emoji
        "title": "Post-Processing",
        "what": (
            "Process SHYFEM .shy output files using shyelab: extract time series, "
            "convert to NetCDF, compute statistics, split by variable, and more."
        ),
        "inputs": ".shy binary output files from a completed simulation",
        "outputs": "Time series (.txt), NetCDF (.nc), statistics, plots",
        "key_params": "Operation mode, variable/layer filters, time range",
        "sample_desc": (
            "Point to the Mar Menor working directory. You need to run a "
            "simulation first to generate .shy output files for post-processing."
        ),
    },
}


def get_progressive_str_files() -> list[dict[str, str]]:
    """Build the progressive STR file list from tutorial content.

    Returns a list of dicts with keys: name, file, label, description.
    Reuses TUTORIAL_CONTENT to avoid data duplication.
    """
    entries: list[dict[str, str]] = []
    for phase in TUTORIAL_CONTENT:
        for sim in phase["simulations"]:
            entries.append(
                {
                    "name": sim["name"],
                    "file": sim["str_file"],
                    "label": f"{sim['name']} — {sim['title']}",
                    "description": sim["summary"],
                }
            )
    return entries


def sample_data_card_ui(page_name: str) -> ui.Tag:
    """Render a collapsible guidance card for a setup page.

    Args:
        page_name: One of "grid_prep", "simulation", "run", "postprocess".

    Returns:
        A Bootstrap card with phase guidance and sample data button.
    """
    guidance = PHASE_GUIDANCE[page_name]
    collapse_id = f"guidance-{page_name}"

    # Build card body content
    body_items: list[ui.Tag] = [
        ui.p(guidance["what"], class_="mb-2"),
        ui.div(
            ui.tags.strong("Inputs: "),
            guidance["inputs"],
            class_="small text-muted mb-1",
        ),
        ui.div(
            ui.tags.strong("Outputs: "),
            guidance["outputs"],
            class_="small text-muted mb-1",
        ),
        ui.div(
            ui.tags.strong("Key parameters: "),
            guidance["key_params"],
            class_="small text-muted mb-2",
        ),
        ui.hr(),
        ui.div(
            ui.tags.strong("Sample Data: "),
            guidance["sample_desc"],
            class_="small mb-2",
        ),
    ]

    # Simulation page gets an extra STR file dropdown
    if page_name == "simulation":
        str_files = get_progressive_str_files()
        choices = {entry["file"]: entry["label"] for entry in str_files}
        body_items.append(
            ui.div(
                ui.input_select(
                    "sample_str_select",
                    "Select STR file:",
                    choices=choices,
                    selected="mm_hyd_03.str",
                    width="100%",
                ),
                ui.output_ui("sample_str_description"),
                class_="mb-2",
            )
        )

    # Load button + tutorial link
    body_items.append(
        ui.div(
            ui.input_action_button(
                "load_sample_btn",
                "Load Sample Data",
                class_="btn-outline-primary btn-sm me-2",
            ),
            ui.tags.a(
                "Learn More in Tutorial",
                href="#",
                onclick="shyfemNavTo('Tutorial'); return false;",
                class_="btn btn-link btn-sm",
            ),
            class_="d-flex align-items-center",
        )
    )

    return ui.div(
        ui.div(
            # Card header (clickable to collapse)
            ui.div(
                ui.tags.a(
                    f"{guidance['icon']} {guidance['title']} — Getting Started",
                    href=f"#{collapse_id}",
                    class_="text-decoration-none fw-bold",
                    **{
                        "data-bs-toggle": "collapse",
                        "aria-expanded": "true",
                        "aria-controls": collapse_id,
                    },
                ),
                class_="card-header py-2",
            ),
            # Card body (collapsible, starts expanded)
            ui.div(
                ui.div(
                    *body_items,
                    class_="card-body py-2",
                ),
                id=collapse_id,
                class_="collapse show",
            ),
            class_="card border-info mb-3",
        ),
    )
