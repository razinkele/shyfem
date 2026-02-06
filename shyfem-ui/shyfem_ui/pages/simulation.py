"""Simulation configuration page - .str file editor."""

from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.components.str_editor import str_editor_server, str_editor_ui
from shyfem_ui.config import Config
from shyfem_ui.services.parser_str import COMMON_PARAMS, COMMON_SECTIONS, StrFile, StrParser


@module.ui
def simulation_ui():
    """Simulation configuration page UI."""
    return ui.page_fluid(
        ui.h3("Simulation Configuration"),
        ui.p("Edit .str parameter files for SHYFEM simulations.", class_="text-muted"),
        ui.layout_sidebar(
            ui.sidebar(
                # File selection
                ui.h5("Parameter File"),
                ui.input_text(
                    "str_path",
                    "File Path (.str)",
                    placeholder="/path/to/simulation.str",
                ),
                ui.div(
                    ui.input_action_button(
                        "load_btn",
                        "Load",
                        class_="btn-outline-primary btn-sm me-2",
                    ),
                    ui.input_action_button(
                        "new_btn",
                        "New",
                        class_="btn-outline-secondary btn-sm me-2",
                    ),
                    ui.input_action_button(
                        "save_as_btn",
                        "Save As...",
                        class_="btn-outline-secondary btn-sm",
                    ),
                    class_="mt-2",
                ),
                ui.hr(),
                # Quick settings
                ui.h5("Quick Settings"),
                ui.input_text(
                    "quick_start",
                    "Start Time",
                    placeholder="2020-01-01",
                ),
                ui.input_text(
                    "quick_end",
                    "End Time",
                    placeholder="2020-01-02",
                ),
                ui.input_text(
                    "quick_dt",
                    "Time Step",
                    placeholder="300s",
                ),
                ui.input_text(
                    "quick_output",
                    "Output Interval",
                    placeholder="1h",
                ),
                ui.input_action_button(
                    "apply_quick_btn",
                    "Apply Quick Settings",
                    class_="btn-outline-primary btn-sm w-100 mt-2",
                ),
                ui.hr(),
                # Templates
                ui.h5("Templates"),
                ui.input_select(
                    "template_select",
                    "Load Template",
                    choices={
                        "": "Select template...",
                        "basic_2d": "Basic 2D Simulation",
                        "basic_3d": "Basic 3D Simulation",
                        "wind_driven": "Wind-driven Flow",
                        "tidal": "Tidal Simulation",
                    },
                ),
                width=300,
            ),
            # Main content
            ui.navset_card_tab(
                ui.nav_panel(
                    "Editor",
                    str_editor_ui("str_editor"),
                ),
                ui.nav_panel(
                    "Sections",
                    ui.output_ui("sections_view"),
                ),
                ui.nav_panel(
                    "Parameter Reference",
                    ui.output_ui("param_reference"),
                ),
            ),
        ),
        # Save As modal
        ui.modal(
            ui.input_text(
                "save_path",
                "Save Path",
                placeholder="/path/to/new_simulation.str",
            ),
            title="Save As",
            footer=ui.div(
                ui.input_action_button(
                    "confirm_save_btn",
                    "Save",
                    class_="btn-primary",
                ),
                ui.input_action_button(
                    "cancel_save_btn",
                    "Cancel",
                    class_="btn-secondary ms-2",
                ),
            ),
            id="save_as_modal",
        ),
    )


@module.server
def simulation_server(
    input,
    output,
    session,
    config: Config,
):
    """Simulation configuration page server logic."""
    # State
    current_file_path = reactive.value(None)
    parsed_str = reactive.value(None)

    # Initialize str_editor
    editor_state = str_editor_server("str_editor", current_file_path)

    @reactive.effect
    @reactive.event(input.load_btn)
    def _load_file():
        path_str = input.str_path()
        if not path_str:
            ui.notification_show("Please enter a file path", type="warning")
            return

        try:
            path = config.validate_path(path_str, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            ui.notification_show(str(e), type="error")
            return

        try:
            current_file_path.set(path)
            str_file = StrParser.parse_file(path)
            parsed_str.set(str_file)
            ui.notification_show(f"Loaded: {path.name}", type="message")
        except Exception as e:
            ui.notification_show(f"Error loading file: {e}", type="error")

    @reactive.effect
    @reactive.event(input.new_btn)
    def _new_file():
        # Create a new template
        template = generate_template("basic_2d")
        new_str = StrParser.parse(template)
        parsed_str.set(new_str)
        current_file_path.set(None)
        ui.notification_show("Created new parameter file", type="message")

    @reactive.effect
    @reactive.event(input.save_as_btn)
    def _show_save_modal():
        # Pre-fill with current path or suggest new one
        current = current_file_path.get()
        if current:
            suggested = str(current.parent / f"{current.stem}_copy.str")
        else:
            suggested = str(config.work_dir / "simulation.str")
        ui.update_text("save_path", value=suggested)
        ui.modal_show("save_as_modal")

    @reactive.effect
    @reactive.event(input.cancel_save_btn)
    def _cancel_save():
        ui.modal_remove("save_as_modal")

    @reactive.effect
    @reactive.event(input.confirm_save_btn)
    def _confirm_save():
        path_str = input.save_path()
        if not path_str:
            ui.notification_show("Please enter a save path", type="warning")
            return

        try:
            path = config.validate_save_path(path_str)
        except ValueError as e:
            ui.notification_show(str(e), type="error")
            return

        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            str_file = parsed_str.get()
            if str_file:
                StrParser.save(str_file, path)
            current_file_path.set(path)
            ui.update_text("str_path", value=str(path))
            ui.modal_remove("save_as_modal")
            ui.notification_show(f"Saved: {path.name}", type="message")
        except Exception as e:
            ui.notification_show(f"Error saving file: {e}", type="error")

    @reactive.effect
    @reactive.event(input.apply_quick_btn)
    def _apply_quick_settings():
        str_file = parsed_str.get()
        if str_file is None:
            str_file = StrFile()

        # Get quick settings
        start = input.quick_start()
        end = input.quick_end()
        dt = input.quick_dt()
        output_int = input.quick_output()

        # Update para section
        if start:
            str_file.set_param("para", "itanf", f"'{start}'")
        if end:
            str_file.set_param("para", "itend", f"'{end}'")
        if dt:
            str_file.set_param("para", "idt", f"'{dt}'")
        if output_int:
            str_file.set_param("para", "idtout", f"'{output_int}'")

        parsed_str.set(str_file)
        ui.notification_show("Applied quick settings", type="message")

    @reactive.effect
    @reactive.event(input.template_select)
    def _load_template():
        template_name = input.template_select()
        if not template_name:
            return

        template = generate_template(template_name)
        str_file = StrParser.parse(template)
        parsed_str.set(str_file)
        current_file_path.set(None)
        ui.notification_show(f"Loaded template: {template_name}", type="message")

        # Reset dropdown
        ui.update_select("template_select", selected="")

    @render.ui
    def sections_view():
        str_file = parsed_str.get()
        if str_file is None:
            return ui.p("No file loaded. Load or create a parameter file.", class_="text-muted")

        section_cards = []
        for name, section in str_file.sections.items():
            params = []
            for key, value in section.parameters.items():
                if key == "_standalone":
                    for item in value:
                        params.append(
                            ui.div(
                                ui.span(f"Node {item['id']}", class_="fw-bold"),
                                ui.span(f": {item['description']}", class_="text-muted"),
                            )
                        )
                else:
                    params.append(
                        ui.div(
                            ui.span(key, class_="fw-bold"),
                            ui.span(" = ", class_="text-muted"),
                            ui.code(str(value)),
                        )
                    )

            section_cards.append(
                ui.div(
                    ui.div(
                        ui.h6(f"${name}", class_="mb-0"),
                        class_="card-header",
                    ),
                    ui.div(
                        *params if params else [ui.p("(empty)", class_="text-muted")],
                        class_="card-body",
                    ),
                    class_="card mb-2",
                )
            )

        return ui.div(*section_cards)

    @render.ui
    def param_reference():
        sections = []

        for section_name, description in COMMON_SECTIONS.items():
            params_html = []
            section_params = COMMON_PARAMS.get(section_name, {})

            for param_name, (desc, param_type) in section_params.items():
                params_html.append(
                    ui.tags.tr(
                        ui.tags.td(ui.code(param_name)),
                        ui.tags.td(desc),
                        ui.tags.td(ui.span(param_type, class_="text-muted small")),
                    )
                )

            if params_html:
                table = ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(
                            ui.tags.th("Parameter"),
                            ui.tags.th("Description"),
                            ui.tags.th("Type"),
                        )
                    ),
                    ui.tags.tbody(*params_html),
                    class_="table table-sm",
                )
            else:
                table = ui.p("No documented parameters", class_="text-muted small")

            sections.append(
                ui.div(
                    ui.h6(f"${section_name}", class_="text-primary"),
                    ui.p(description, class_="text-muted small"),
                    table,
                    class_="mb-4",
                )
            )

        return ui.div(*sections)

    return {
        "current_file_path": current_file_path,
        "parsed_str": parsed_str,
    }


def generate_template(template_name: str) -> str:
    """Generate a template .str file."""
    templates = {
        "basic_2d": """
#------------------------------------------------------------------------
# Basic 2D Simulation Template
#------------------------------------------------------------------------

$title
        Basic 2D Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3
$end

$extra
        1     'output node 1'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "basic_3d": """
#------------------------------------------------------------------------
# Basic 3D Simulation Template
#------------------------------------------------------------------------

$title
        Basic 3D Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D settings
        nlv = 10
        hlv = 1 2 3 4 5 6 8 10 15 20
$end

$extra
        1     'output node 1'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "wind_driven": """
#------------------------------------------------------------------------
# Wind-driven Flow Simulation Template
#------------------------------------------------------------------------

$title
        Wind-driven Flow
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3
$end

$extra
        1     'center'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
        "tidal": """
#------------------------------------------------------------------------
# Tidal Simulation Template
#------------------------------------------------------------------------

$title
        Tidal Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-03'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3
$end

$bound
        ! Boundary conditions (type value)
        1  1  1  0.5    ! Open boundary with M2 tide
$end

$extra
        1     'tidal gauge'
$end

$name
        ! bound = 'INPUT/tide.txt'
$end
""",
    }

    return templates.get(template_name, templates["basic_2d"])
