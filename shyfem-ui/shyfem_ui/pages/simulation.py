"""Simulation configuration page - .str file editor."""

from shiny import module, reactive, render, ui

from shyfem_ui.components.boundary_editor import boundary_editor_server, boundary_editor_ui
from shyfem_ui.components.str_editor import str_editor_server, str_editor_ui
from shyfem_ui.config import Config
from shyfem_ui.services.parser_str import COMMON_PARAMS, COMMON_SECTIONS, StrFile, StrParser


@module.ui
def simulation_ui():
    """Simulation configuration page UI."""
    return ui.div(
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
                        "baroclinic": "Baroclinic (T/S)",
                        "lagrangian": "Lagrangian Tracking",
                    },
                ),
                ui.output_ui("template_preview"),
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
                    "Boundaries",
                    boundary_editor_ui("boundary_editor"),
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

    # Initialize str_editor and wire up its reactive state
    editor_state = str_editor_server("str_editor", current_file_path)

    # Initialize boundary editor
    boundary_editor_server("boundary_editor", parsed_str=parsed_str)

    # Guard to prevent infinite sync loops between editor and simulation state
    _syncing = reactive.value(False)

    # Sync editor -> simulation: when the editor's parsed_file changes, update parsed_str
    @reactive.effect
    def _sync_editor_to_simulation():
        editor_parsed = editor_state["parsed_file"].get()
        if editor_parsed is not None and not _syncing.get():
            _syncing.set(True)
            try:
                parsed_str.set(editor_parsed)
            finally:
                _syncing.set(False)

    # Sync simulation -> editor: when parsed_str changes (e.g. from templates/quick settings),
    # update the editor content via the text area
    @reactive.effect
    def _sync_simulation_to_editor():
        str_file = parsed_str.get()
        if str_file is not None and not _syncing.get():
            _syncing.set(True)
            try:
                text = StrParser.generate(str_file)
                editor_state["set_content"](text)
            finally:
                _syncing.set(False)

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
        try:
            template = generate_template("basic_2d")
            new_str = StrParser.parse(template)
            parsed_str.set(new_str)
            current_file_path.set(None)
            ui.notification_show("Created new parameter file", type="message")
        except Exception as e:
            ui.notification_show(f"Error creating new file: {e}", type="error")

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
        try:
            str_file = parsed_str.get()
            if str_file is None:
                str_file = StrFile()

            # Get quick settings
            start = input.quick_start()
            end = input.quick_end()
            dt = input.quick_dt()
            output_int = input.quick_output()

            # Update para section (strip existing quotes to avoid double-quoting)
            def quote_value(val: str) -> str:
                val = val.strip().strip("'\"")
                return f"'{val}'"

            if start:
                str_file.set_param("para", "itanf", quote_value(start))
            if end:
                str_file.set_param("para", "itend", quote_value(end))
            if dt:
                str_file.set_param("para", "idt", quote_value(dt))
            if output_int:
                str_file.set_param("para", "idtout", quote_value(output_int))

            parsed_str.set(str_file)
            ui.notification_show("Applied quick settings", type="message")
        except Exception as e:
            ui.notification_show(f"Error applying settings: {e}", type="error")

    @render.ui
    def template_preview():
        template_name = input.template_select()
        if not template_name:
            return None

        template = generate_template(template_name)
        # Show a compact preview of what the template contains
        parsed = StrParser.parse(template)
        section_names = list(parsed.sections.keys())
        param_count = sum(
            len([k for k in s.parameters if not k.startswith("_")])
            for s in parsed.sections.values()
        )

        return ui.div(
            ui.div(
                ui.span("Sections: ", class_="small fw-bold"),
                *[ui.span(f"${n} ", class_="badge bg-secondary me-1 small") for n in section_names],
                class_="mb-1",
            ),
            ui.div(
                ui.span(f"{param_count} parameters", class_="small text-muted"),
                class_="mb-2",
            ),
            ui.pre(
                template.strip()[:300] + ("..." if len(template.strip()) > 300 else ""),
                class_="small p-2 bg-light",
                style="max-height: 150px; overflow-y: auto; font-size: 11px;",
            ),
            ui.input_action_button(
                "apply_template_btn",
                "Apply Template",
                class_="btn-sm btn-outline-primary w-100 mt-1",
            ),
            class_="mt-2 p-2 border rounded",
        )

    @reactive.effect
    @reactive.event(input.apply_template_btn)
    def _load_template():
        template_name = input.template_select()
        if not template_name:
            return

        try:
            template = generate_template(template_name)
            str_file = StrParser.parse(template)
            parsed_str.set(str_file)
            current_file_path.set(None)
            ui.notification_show(f"Loaded template: {template_name}", type="message")

            # Reset dropdown
            ui.update_select("template_select", selected="")
        except Exception as e:
            ui.notification_show(f"Error loading template: {e}", type="error")

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

            for param_name, info in section_params.items():
                desc, ptype, default, units, options = info
                type_str = ptype
                if units:
                    type_str += f" ({units})"

                default_str = ""
                if default is not None:
                    default_str = str(default)

                opts_str = options or ""

                params_html.append(
                    ui.tags.tr(
                        ui.tags.td(ui.code(param_name)),
                        ui.tags.td(desc),
                        ui.tags.td(ui.span(type_str, class_="text-muted small")),
                        ui.tags.td(ui.code(default_str, class_="small") if default_str else ui.span("-", class_="text-muted")),
                        ui.tags.td(ui.span(opts_str, class_="text-muted small")),
                    )
                )

            if params_html:
                table = ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(
                            ui.tags.th("Parameter"),
                            ui.tags.th("Description"),
                            ui.tags.th("Type"),
                            ui.tags.th("Default"),
                            ui.tags.th("Options/Range"),
                        )
                    ),
                    ui.tags.tbody(*params_html),
                    class_="table table-sm table-hover",
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
        "baroclinic": """
#------------------------------------------------------------------------
# Baroclinic (Temperature/Salinity) Simulation Template
#------------------------------------------------------------------------

$title
        Baroclinic Simulation
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-10'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! Baroclinic mode: full T/S coupling
        ibarcl = 1
        itemp = 1
        isalt = 1

        ! Initial conditions
        temref = 15.0
        salref = 35.0

        ! 3D vertical settings
        nlv = 10
        iturb = 1      ! GOTM turbulence
        difmol = 1.0e-6
        vismol = 1.0e-6

        ! Horizontal mixing
        idhtyp = 2     ! Smagorinsky
        ahpar = 1.0
        dhpar = 1.0

        ! Heat flux
        iheat = 1
$end

$levels
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
        50.0
$end

$extra
        1     'monitoring station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! tempin = 'INPUT/temp_init.shy'
        ! saltin = 'INPUT/salt_init.shy'
        ! qflux = 'INPUT/heatflux.txt'
$end
""",
        "lagrangian": """
#------------------------------------------------------------------------
# Lagrangian Particle Tracking Template
#------------------------------------------------------------------------

$title
        Lagrangian Tracking
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-05'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! Lagrangian (concentration as tracer)
        iconz = 1
        iage = 1       ! Water age tracer mode
        conref = 0.0

        ! Transport scheme
        itvd = 1       ! TVD for horizontal advection
        chpar = 1.0    ! Horizontal diffusion for tracers
$end

$extra
        1     'release point'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
    }

    return templates.get(template_name, templates["basic_2d"])
