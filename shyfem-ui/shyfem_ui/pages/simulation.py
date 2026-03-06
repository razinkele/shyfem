"""Simulation configuration page - .str file editor."""

from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.components.boundary_editor import boundary_editor_server, boundary_editor_ui
from shyfem_ui.components.sample_data import get_progressive_str_files, sample_data_card_ui
from shyfem_ui.components.str_editor import str_editor_server, str_editor_ui
from shyfem_ui.config import Config
from shyfem_ui.services.parser_str import COMMON_PARAMS, COMMON_SECTIONS, StrFile, StrParser
from shyfem_ui.services.str_validator import validate_str


@module.ui
def simulation_ui():
    """Simulation configuration page UI."""
    return ui.div(
        ui.h3("Simulation Configuration"),
        ui.p("Edit .str parameter files for SHYFEM simulations.", class_="text-muted"),
        sample_data_card_ui("simulation"),
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
                        "wind_driven": "Wind-Driven Circulation",
                        "tidal": "Tidal Simulation",
                        "tidal_estuary": "Tidal Estuary (3D)",
                        "baroclinic": "Baroclinic (T/S)",
                        "eulerian_tracer": "Eulerian Tracer / Water Age",
                        "lagrangian": "Lagrangian Particle Tracking",
                        "sediment_transport": "Sediment Transport",
                        "water_quality": "Water Quality (EUTRO)",
                        "storm_surge": "Storm Surge",
                        "thermal": "Thermal / Heat Exchange",
                        "ice_model": "Ice Model",
                        "oil_spill": "Oil Spill (Lagrangian)",
                        "data_assimilation": "Data Assimilation",
                        "offline_tracer": "Offline Tracer Run",
                        "wave_coupled": "Wave-Coupled Storm Surge",
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
    )


@module.server
def simulation_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
    tutorial_context=None,
):
    """Simulation configuration page server logic."""

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                str_path = str(Path(proj["work_dir"]) / sim["str_file"])
                ui.update_text("str_path", value=str_path)

    # Auto-fill from tutorial navigation
    @reactive.effect
    def _on_tutorial_context():
        if tutorial_context is None:
            return
        ctx = tutorial_context.get()
        if ctx is None or ctx.get("target_tab") != "Simulation":
            return
        ui.update_text(
            "str_path",
            value=str(Path(ctx["work_dir"]) / ctx["str_file"]),
        )
        tutorial_context.set(None)

    # State
    current_file_path = reactive.value(None)
    parsed_str = reactive.value(None)

    # Create project_id reactive value for file picker integration
    project_id_reactive = reactive.value(None)

    @reactive.effect
    def _sync_project_id():
        if active_project is None:
            return
        proj = active_project.get()
        project_id_reactive.set(proj["id"] if proj else None)

    # Initialize str_editor and wire up its reactive state
    editor_state = str_editor_server(
        "str_editor", current_file_path, project_id=project_id_reactive
    )

    # Initialize boundary editor
    boundary_editor_server("boundary_editor", parsed_str=parsed_str)

    # One-way sync: editor -> parsed_str.
    # Handlers that modify parsed_str directly (templates, quick settings)
    # must also call editor_state["set_content"]() to update the editor.
    # This avoids the infinite reactive loop that bidirectional sync causes
    # (Shiny effects are scheduled asynchronously, so flag-based guards
    # cannot prevent the cycle).
    @reactive.effect
    def _sync_editor_to_simulation():
        editor_parsed = editor_state["parsed_file"].get()
        if editor_parsed is not None:
            parsed_str.set(editor_parsed)

    # Sample data: STR file description display
    _str_files_lookup = {e["file"]: e["description"] for e in get_progressive_str_files()}

    @render.ui
    def sample_str_description():
        selected = input.sample_str_select()
        desc = _str_files_lookup.get(selected, "")
        if not desc:
            return ui.div()
        return ui.p(desc, class_="text-muted small fst-italic mt-1")

    # Load sample STR file handler
    @reactive.effect
    @reactive.event(input.load_sample_btn)
    def _load_sample_data():
        selected = input.sample_str_select()
        if not selected:
            selected = "mm_hyd_03.str"
        str_path = config.testcases_dir / "mar_menor" / selected
        if not str_path.exists():
            ui.notification_show(
                f"Sample STR not found: {str_path}", type="error"
            , duration=6)
            return
        ui.update_text("str_path", value=str(str_path))
        try:
            current_file_path.set(str_path)
            str_file = StrParser.parse_file(str_path)
            parsed_str.set(str_file)
            ui.notification_show(
                f"Sample loaded: {selected}",
                type="message",
                duration=4,
            )
        except Exception as e:
            ui.notification_show(f"Error loading sample STR: {e}", type="error", duration=6)

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
            ui.notification_show(str(e), type="error", duration=6)
            return

        try:
            current_file_path.set(path)
            str_file = StrParser.parse_file(path)
            parsed_str.set(str_file)
            ui.notification_show(f"Loaded: {path.name}", type="message", duration=4)
        except Exception as e:
            ui.notification_show(f"Error loading file: {e}", type="error", duration=6)

    @reactive.effect
    @reactive.event(input.new_btn)
    def _new_file():
        try:
            template = generate_template("basic_2d")
            new_str = StrParser.parse(template)
            parsed_str.set(new_str)
            editor_state["set_content"](template)
            current_file_path.set(None)
            ui.notification_show("Created new parameter file", type="message", duration=4)
        except Exception as e:
            ui.notification_show(f"Error creating new file: {e}", type="error", duration=6)

    @reactive.effect
    @reactive.event(input.save_as_btn)
    def _show_save_modal():
        # Pre-fill with current path or suggest new one
        current = current_file_path.get()
        if current:
            suggested = str(current.parent / f"{current.stem}_copy.str")
        else:
            suggested = str(config.work_dir / "simulation.str")
        m = ui.modal(
            ui.input_text(
                "save_path",
                "Save Path",
                value=suggested,
                placeholder="/path/to/new_simulation.str",
            ),
            title="Save As",
            easy_close=True,
            footer=ui.div(
                ui.input_action_button(
                    "confirm_save_btn",
                    "Save",
                    class_="btn-primary",
                ),
                ui.modal_button("Cancel"),
            ),
        )
        ui.modal_show(m)

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
            ui.notification_show(str(e), type="error", duration=6)
            return

        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            str_file = parsed_str.get()
            if str_file:
                StrParser.save(str_file, path)
                # Validate after save
                msgs = validate_str(str_file.sections)
                for m in msgs:
                    if m.level == "error":
                        ui.notification_show(f"Error: {m.message}", type="error", duration=8)
                    elif m.level == "warning":
                        ui.notification_show(f"Warning: {m.message}", type="warning", duration=6)
            current_file_path.set(path)
            ui.update_text("str_path", value=str(path))
            ui.modal_remove()
            ui.notification_show(f"Saved: {path.name}", type="message", duration=4)
        except Exception as e:
            ui.notification_show(f"Error saving file: {e}", type="error", duration=6)

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
            editor_state["set_content"](StrParser.generate(str_file))
            ui.notification_show("Applied quick settings", type="message", duration=4)
        except Exception as e:
            ui.notification_show(f"Error applying settings: {e}", type="error", duration=6)

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

        # Validate template
        validation_msgs = validate_str(parsed.sections)
        val_parts = []
        errors = [m for m in validation_msgs if m.level == "error"]
        warnings = [m for m in validation_msgs if m.level == "warning"]
        infos = [m for m in validation_msgs if m.level == "info"]
        if errors:
            for m in errors:
                val_parts.append(ui.div(
                    ui.tags.i(class_="bi bi-x-circle text-danger me-1"),
                    ui.span(m.message, class_="small"),
                ))
        if warnings:
            for m in warnings:
                val_parts.append(ui.div(
                    ui.tags.i(class_="bi bi-exclamation-triangle text-warning me-1"),
                    ui.span(m.message, class_="small"),
                ))
        if infos:
            for m in infos:
                val_parts.append(ui.div(
                    ui.tags.i(class_="bi bi-info-circle text-info me-1"),
                    ui.span(m.message, class_="small text-muted"),
                ))

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
            *(
                [ui.div(
                    ui.span("Needs attention:", class_="small fw-bold text-warning"),
                    *val_parts,
                    class_="mb-2 p-1 border-start border-warning border-3 ps-2",
                )] if val_parts else []
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
            editor_state["set_content"](template)
            current_file_path.set(None)
            ui.notification_show(f"Loaded template: {template_name}", type="message", duration=4)

            # Reset dropdown
            ui.update_select("template_select", selected="")
        except Exception as e:
            ui.notification_show(f"Error loading template: {e}", type="error", duration=6)

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
                        ui.tags.td(
                            ui.code(default_str, class_="small")
                            if default_str
                            else ui.span("-", class_="text-muted")
                        ),
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
# Wind-Driven Circulation Template
# 2D barotropic flow with Coriolis and Smagorinsky diffusion
#------------------------------------------------------------------------

$title
        Wind-Driven Circulation
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

        ! Coriolis (beta-plane)
        icor = 1
        dlat = 45.0

        ! Horizontal diffusion (Smagorinsky)
        idhtyp = 2
        ahpar = 1.0
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
        "eulerian_tracer": """
#------------------------------------------------------------------------
# Eulerian Tracer / Water Age Template
#------------------------------------------------------------------------

$title
        Eulerian Tracer
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

        ! Eulerian tracer (concentration)
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
        "lagrangian": """
#------------------------------------------------------------------------
# Lagrangian Particle Tracking Template
#------------------------------------------------------------------------

$title
        Lagrangian Particle Tracking
        lagrangian_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3
$end

$lagrg
        ilagr = 2
        nbdy = 100
        nbdymax = 10000
        idtl = 3600
        rwhpar = 1.0
        idtlgr = 3600
$end

$extra
        1       'release point'
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "tidal_estuary": """
#------------------------------------------------------------------------
# Tidal Estuary Template
# 3D baroclinic with tidal boundary, river inflow, and salinity
#------------------------------------------------------------------------

$title
        Tidal Estuary
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

        ! 3D baroclinic mode
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Vertical layers
        nlv = 10

        ! Turbulence (GOTM)
        iturb = 1
        difmol = 1.0e-6
        vismol = 1.0e-6

        ! Horizontal mixing (Smagorinsky)
        idhtyp = 2
        ahpar = 1.0
        dhpar = 1.0

        ! Coriolis
        icor = 1
        dlat = 45.0
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

$bound
        ! Open boundary: tidal forcing
        1  1  1  0.5    ! M2 tidal amplitude [m]
        ! River inflow boundary
        ! 2  3  0  100.0  ! Discharge [m3/s], salinity = 0
$end

$extra
        1     'estuary mouth'
        2     'upstream station'
$end

$name
        wind = 'INPUT/wind.txt'
        ! bound = 'INPUT/tide.txt'
        ! saltin = 'INPUT/salt_init.shy'
$end
""",
        "sediment_transport": """
#------------------------------------------------------------------------
# Sediment Transport Template
# 3D with simple sedimentation module
#------------------------------------------------------------------------

$title
        Sediment Transport
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

        ! 3D setup
        nlv = 10
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Turbulence
        iturb = 1
        difmol = 1.0e-6

        ! Simple sedimentation module
        issedi = 1

        ! Horizontal mixing
        idhtyp = 2
        ahpar = 1.0
$end

$levels
        0.5
        1.0
        2.0
        3.0
        5.0
        7.0
        10.0
        15.0
        20.0
        30.0
$end

$extra
        1     'monitoring point'
$end

$name
        wind = 'INPUT/wind.txt'
$end

! For full sediment transport, use the $sedtr section instead of issedi:
! $sedtr
!         isedi = 1
!         sedgrs = '0.063 0.125 0.25 0.5'
!         percin = '0.25 0.25 0.25 0.25'
! $end
""",
        "water_quality": """
#------------------------------------------------------------------------
# Water Quality (EUTRO) Template
# 3D baroclinic with 9-variable eutrophication model
#------------------------------------------------------------------------

$title
        Water Quality
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-30'
        idt = '300s'
        idtout = '1h'
        idtext = '300s'
        idtcon = '1h'

        date = 20200101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3

        ! 3D baroclinic
        ibarcl = 1
        itemp = 1
        isalt = 1
        temref = 15.0
        salref = 35.0

        ! Vertical layers
        nlv = 10

        ! Turbulence
        iturb = 1
        difmol = 1.0e-6

        ! Water quality (WASP/EUTRO 9-variable model)
        ! Variables: NH3, NO3, OPO4, PHYT, CBOD, DO, ON, OP, ZOO
        ibio = 1

        ! Heat flux for temperature evolution
        iheat = 1

        ! Horizontal mixing
        idhtyp = 2
        ahpar = 1.0
        dhpar = 1.0
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
        ! bio2dn = 'INPUT/bio_boundary.txt'
        ! bioin = 'INPUT/bio_initial.shy'
$end
""",
        "storm_surge": """
#------------------------------------------------------------------------
# Storm Surge Template
# 2D barotropic with wetting/drying and meteorological forcing
#------------------------------------------------------------------------

$title
        Storm Surge
        simulation_name
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-03'
        idt = '60s'
        idtout = '30m'
        idtext = '60s'

        date = 20200101

        ilin = 1

        ! Wind drag (Wu 1982 - speed-dependent)
        iwtype = 3
        itdrag = 2
        wsmax = 60

        ! Bottom friction
        ireib = 5      czdef = 2.5e-3

        ! Coriolis
        icor = 1
        dlat = 45.0

        ! Spherical coordinates (for real-world domains)
        ! isphe = 1

        ! Wetting and drying
        hzoff = 0.05
        hzon = 0.10
        hzmin = 0.01

        ! Horizontal diffusion
        idhtyp = 2
        ahpar = 1.0
$end

$extra
        1     'tide gauge 1'
        2     'tide gauge 2'
$end

$name
        ! Wind file with optional atmospheric pressure (3rd column)
        wind = 'INPUT/wind.txt'
$end
""",
        "thermal": """
#------------------------------------------------------------------------
# Thermal / Heat Exchange Simulation Template
#------------------------------------------------------------------------

$title
        Thermal / Heat Exchange Simulation
        thermal_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-02-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        ibarcl = 1
        itemp = 1
        isalt = 0
        iheat = 6
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$name
        wind = 'INPUT/wind.txt'
        tempn = 'INPUT/temp_init.txt'
$end
""",
        "ice_model": """
#------------------------------------------------------------------------
# Ice Model Simulation Template
#------------------------------------------------------------------------

$title
        Ice Model Simulation
        ice_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-04-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        ibarcl = 1
        itemp = 1
        isalt = 1
        iheat = 6
        icemod = 1
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$name
        wind = 'INPUT/wind.txt'
        tempn = 'INPUT/temp_init.txt'
        saltn = 'INPUT/salt_init.txt'
$end
""",
        "oil_spill": """
#------------------------------------------------------------------------
# Oil Spill Simulation Template
#------------------------------------------------------------------------

$title
        Oil Spill Simulation
        oil_spill_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3
$end

$lagrg
        ilagr = 3
        nbdy = 1000
        nbdymax = 50000
        idtl = 3600
        rwhpar = 1.0
        ioil = 1
        lbeach = 0.5
        ldecay = 86400
        idtlgr = 3600
$end

$extra
        1       'spill source'
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
        "data_assimilation": """
#------------------------------------------------------------------------
# Data Assimilation Simulation Template
#------------------------------------------------------------------------

$title
        Data Assimilation Simulation
        assim_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-02-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        ibarcl = 4
        itemp = 1
        isalt = 1
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$nduge
        nvars = 3
        tramp = 43200
        ttau = 3600
        sigma = 5000
$end

$name
        wind = 'INPUT/wind.txt'
        tempn = 'INPUT/temp_obs.txt'
        saltn = 'INPUT/salt_obs.txt'
$end
""",
        "offline_tracer": """
#------------------------------------------------------------------------
# Offline Tracer Run Template
#------------------------------------------------------------------------

$title
        Offline Tracer Run
        offline_tracer_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-02-01'
        idt = '300s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1

        idtoff = -1
        iconz = 1
$end

$levels
        0.5 1 2 3 5 7 10 15 20
$end

$name
        ! wind = 'INPUT/wind.txt'
$end
""",
        "wave_coupled": """
#------------------------------------------------------------------------
# Wave-Coupled Storm Surge Template
#------------------------------------------------------------------------

$title
        Wave-Coupled Storm Surge
        wave_coupled_sim
        GRID/grid_name
$end

$para
        itanf = '2020-01-01'    itend = '2020-01-06'
        idt = '60s'
        idtout = '1h'           idtext = '300s'

        date = 20200101

        ilin = 1
        iwtype = 3              dragco = 2.5e-3
        ireib = 5               czdef = 2.5e-3

        iwave = 2
        dtwave = 300
$end

$name
        wind = 'INPUT/wind.txt'
$end
""",
    }

    return templates.get(template_name, templates["basic_2d"])
