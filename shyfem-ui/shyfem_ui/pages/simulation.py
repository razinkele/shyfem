"""Simulation configuration page - .str file editor."""

import logging
from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.components.boundary_editor import boundary_editor_server, boundary_editor_ui
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
from shyfem_ui.components.sample_data import get_progressive_str_files, sample_data_card_ui
from shyfem_ui.components.str_editor import str_editor_server, str_editor_ui
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.parser_str import COMMON_PARAMS, COMMON_SECTIONS, StrParser
from shyfem_ui.services.simulation_logic import (  # re-exported for backward compat
    apply_quick_settings,
    generate_template,
)
from shyfem_ui.services.str_validator import validate_str

logger = logging.getLogger(__name__)


@module.ui
def simulation_ui() -> ui.Tag:
    """Simulation configuration page UI."""
    return ui.div(
        ui.h3("Simulation Configuration"),
        ui.p("Edit .str parameter files for SHYFEM simulations.", class_="text-muted"),
        sample_data_card_ui("simulation"),
        ui.layout_sidebar(
            ui.sidebar(
                # File selection
                ui.h5("Parameter File"),
                file_picker_ui("fp_str", label="Pick STR file from project"),
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
    current_user=None,
) -> None:
    """Simulation configuration page server logic."""

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        # NOTE: project_id_reactive is updated by the existing
        # _sync_project_id effect (defined below); do NOT duplicate
        # that work here.
        work_dir = proj["work_dir"]
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                with reactive.isolate():
                    str_empty = not input.str_path()
                if str_empty:
                    ui.update_text(
                        "str_path",
                        value=str(Path(work_dir) / sim["str_file"]),
                    )

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

    # File picker delegates resolve/log/notify branching to
    # fill_picker_input (see its docstring in components/file_picker.py).
    file_picker_server(
        "fp_str",
        project_id=project_id_reactive,  # reuse existing reactive
        file_types=["str"],
        on_selected=lambda rel: fill_picker_input(
            "str_path", active_project.get() if active_project else None, rel
        ),
    )

    # Initialize str_editor and wire up its reactive state
    editor_state = str_editor_server(
        "str_editor",
        current_file_path,
        project_id=project_id_reactive,
        current_user=current_user,
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
        # `selected` is a client-settable input — confine the resulting path so a
        # spoofed '../' value cannot read .str files outside the sample assets.
        _usr = current_user() if current_user is not None else None
        try:
            str_path = config.confine_path(
                config.testcases_dir / "mar_menor" / selected, _usr, must_exist=True
            )
        except (ValueError, FileNotFoundError):
            ui.notification_show(f"Sample STR not found: {selected}", type="error", duration=6)
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
            logger.exception("Failed to load sample STR file %r", selected)
            ui.notification_show(f"Error loading sample STR: {e}", type="error", duration=6)

    @reactive.effect
    @reactive.event(input.load_btn)
    def _load_file():
        path_str = input.str_path()
        if not path_str:
            ui.notification_show("Please enter a file path", type="warning")
            return

        _usr = current_user() if current_user is not None else None
        try:
            path = config.confine_path(path_str, _usr, must_exist=True)
        except (ValueError, FileNotFoundError) as e:
            logger.exception("Invalid STR file path %r", path_str)
            ui.notification_show(str(e), type="error", duration=6)
            return

        try:
            current_file_path.set(path)
            str_file = StrParser.parse_file(path)
            parsed_str.set(str_file)
            ui.notification_show(f"Loaded: {path.name}", type="message", duration=4)
        except Exception as e:
            logger.exception("Failed to parse STR file %s", path_str)
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
            logger.exception("Failed to create new STR file from template")
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
        _usr = current_user() if current_user is not None else None
        logger.info("User saving STR file to %r", input.save_path())
        _proj = active_project.get() if active_project is not None else None
        _denied = editor_denied_reason(
            _proj["id"] if _proj is not None else None, _usr, min_role="editor"
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        path_str = input.save_path()
        if not path_str:
            ui.notification_show("Please enter a save path", type="warning")
            return

        try:
            path = config.confine_path(path_str, _usr, for_write=True)
        except ValueError as e:
            logger.exception("Invalid save path %r for STR file", path_str)
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
            logger.exception("Failed to save STR file to %s", path_str)
            ui.notification_show(f"Error saving file: {e}", type="error", duration=6)

    @reactive.effect
    @reactive.event(input.apply_quick_btn)
    def _apply_quick_settings():
        logger.info(
            "User applying quick settings: start=%r end=%r dt=%r output=%r",
            input.quick_start(),
            input.quick_end(),
            input.quick_dt(),
            input.quick_output(),
        )
        try:
            str_file = apply_quick_settings(
                parsed_str.get(),
                start=input.quick_start(),
                end=input.quick_end(),
                dt=input.quick_dt(),
                output_int=input.quick_output(),
            )
            parsed_str.set(str_file)
            editor_state["set_content"](StrParser.generate(str_file))
            ui.notification_show("Applied quick settings", type="message", duration=4)
        except Exception as e:
            logger.exception("Failed to apply quick settings to STR file")
            ui.notification_show(f"Error applying settings: {e}", type="error", duration=6)

    @render.ui
    def template_preview():
        template_name = input.template_select()
        if not template_name:
            return ui.div()

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
                val_parts.append(
                    ui.div(
                        ui.tags.i(class_="bi bi-x-circle text-danger me-1"),
                        ui.span(m.message, class_="small"),
                    )
                )
        if warnings:
            for m in warnings:
                val_parts.append(
                    ui.div(
                        ui.tags.i(class_="bi bi-exclamation-triangle text-warning me-1"),
                        ui.span(m.message, class_="small"),
                    )
                )
        if infos:
            for m in infos:
                val_parts.append(
                    ui.div(
                        ui.tags.i(class_="bi bi-info-circle text-info me-1"),
                        ui.span(m.message, class_="small text-muted"),
                    )
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
            *(
                [
                    ui.div(
                        ui.span("Needs attention:", class_="small fw-bold text-warning"),
                        *val_parts,
                        class_="mb-2 p-1 border-start border-warning border-3 ps-2",
                    )
                ]
                if val_parts
                else []
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

        logger.info("User applying STR template %r", template_name)
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
            logger.exception("Failed to apply template %r", template_name)
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
