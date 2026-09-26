"""STR file editor component with split view: raw text + structured form."""

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from shiny import module, reactive, render, ui

from shyfem_ui.components.project_select import is_file_param, str_file_selectize
from shyfem_ui.services.parser_str import (
    COMMON_PARAMS,
    COMMON_SECTIONS,
    StrFile,
    StrParser,
)

logger = logging.getLogger(__name__)

# Section color coding for visual differentiation
SECTION_COLORS = {
    "title": "#6c757d",
    "para": "#0d6efd",
    "extra": "#198754",
    "name": "#6f42c1",
    "bound": "#dc3545",
    "bound1": "#dc3545",
    "bound2": "#dc3545",
    "bound3": "#dc3545",
    "flux": "#fd7e14",
    "levels": "#20c997",
    "waves": "#0dcaf0",
    "sedtr": "#d63384",
    "wrt": "#adb5bd",
}


def _section_badge(name: str) -> ui.Tag:
    """Create a colored badge for a section name."""
    color = SECTION_COLORS.get(name, "#6c757d")
    return ui.span(
        f"${name}",
        class_="badge",
        style=f"background-color: {color}; font-family: monospace;",
    )


@module.ui
def str_editor_ui(height: str = "500px"):
    """STR file editor component UI with split view.

    Args:
        height: CSS height for the editor panels
    """
    return ui.div(
        # Toolbar
        ui.div(
            ui.input_action_button(
                "load_btn",
                "Load",
                class_="btn-sm btn-outline-primary me-2",
            ),
            ui.input_action_button(
                "save_btn",
                "Save",
                class_="btn-sm btn-success me-2",
            ),
            ui.input_action_button(
                "validate_btn",
                "Validate",
                class_="btn-sm btn-outline-info me-2",
            ),
            ui.span("|", class_="mx-2 text-muted"),
            ui.input_select(
                "insert_section",
                "",
                choices={"": "Insert Section...", **COMMON_SECTIONS},
                width="200px",
            ),
            ui.span("|", class_="mx-2 text-muted"),
            ui.input_radio_buttons(
                "view_mode",
                "",
                choices={"split": "Split", "raw": "Raw", "form": "Form"},
                selected="split",
                inline=True,
            ),
            class_="d-flex align-items-center mb-2 flex-wrap gap-1",
        ),
        # Split view container
        ui.output_ui("editor_view"),
        # Status bar
        ui.div(
            ui.output_ui("status_bar"),
            class_="str-editor-status mt-1",
        ),
        # Validation messages
        ui.output_ui("validation_messages"),
        class_="str-editor-component",
    )


@module.server
def str_editor_server(
    input,
    output,
    session,
    file_path: reactive.Value[Path | None],
    on_save: Callable[[Path, str], None] | None = None,
    project_id: reactive.Value | None = None,
    current_user: Callable[[], dict | None] | None = None,
    file_choices: Callable[[], Sequence[str]] | None = None,
):
    """STR file editor component server logic with split view support.

    Args:
        file_path: Reactive value containing the file path to edit
        on_save: Callback when file is saved
        project_id: Reactive value with current project ID
        file_choices: Callable returning project-relative data-file paths
            offered by the file-parameter fields (selectize with create; any
            name can still be typed). None -> free text only.
        current_user: Callable returning the server-validated user dict (or
            None). Used to fail-closed the inline Save in server mode — the
            handler writes to disk directly, so it must re-check identity.
    """
    content = reactive.value("")
    parsed_file = reactive.value(None)
    validation_errors = reactive.value([])
    is_modified = reactive.value(False)
    _form_syncing = False

    @reactive.effect
    def _load_file():
        path = file_path.get()
        if path and path.exists():
            try:
                text = path.read_text()
                content.set(text)
                parsed = StrParser.parse(text)
                parsed_file.set(parsed)
                validation_errors.set([])
                is_modified.set(False)
            except Exception as e:
                validation_errors.set([f"Error loading file: {e}"])

    @reactive.effect
    @reactive.event(input.editor_content)
    def _track_changes():
        nonlocal _form_syncing
        if _form_syncing:
            return
        is_modified.set(True)
        # Re-parse for form sync
        text = input.editor_content()
        if text:
            try:
                parsed = StrParser.parse(text)
                parsed_file.set(parsed)
            except Exception:
                logger.warning("Failed to re-parse editor content for form sync", exc_info=True)

    @reactive.effect
    @reactive.event(input.apply_form_btn)
    def _apply_form_changes():
        """Apply structured form edits back to the raw editor."""
        nonlocal _form_syncing
        parsed = parsed_file.get()
        if parsed is None:
            return

        # Collect form field values and update parsed sections
        for section_name, section in parsed.sections.items():
            section_params = COMMON_PARAMS.get(section_name, {})
            for param_name in section_params:
                if param_name in section.parameters or param_name.startswith("_"):
                    field_id = f"form_{section_name}_{param_name}"
                    try:
                        new_val = input[field_id]()
                        if new_val is not None and str(new_val).strip():
                            old_val = section.parameters.get(param_name)
                            converted = StrParser._convert_value(str(new_val).strip())
                            if converted != old_val:
                                parsed.set_param(section_name, param_name, converted)
                    except Exception:
                        logger.debug("Skipping form field %s conversion", field_id, exc_info=True)
                        continue

        # Regenerate text from modified parsed file. _format_value refuses
        # values the STR reader cannot express (it has no escape for either
        # quote delimiter), so serialization can fail on free-text input.
        _form_syncing = True
        try:
            text = StrParser.generate(parsed)
            content.set(text)
            ui.update_text_area("editor_content", value=text)
            is_modified.set(True)
        except ValueError as e:
            logger.exception("Regenerating STR text from form edits failed")
            ui.notification_show(f"Cannot apply: {e}", type="error", duration=8)
        finally:
            _form_syncing = False

    @reactive.effect
    @reactive.event(input.load_btn)
    def _handle_load():
        path = file_path.get()
        if path:
            file_path.set(None)
            file_path.set(path)

    @reactive.effect
    @reactive.event(input.save_btn)
    def _handle_save():
        path = file_path.get()
        if not path:
            validation_errors.set(["No file path specified"])
            return

        # Access check before writing to disk: require editor role on the
        # active project (fail-closed in server mode). The inline Save writes
        # path.write_text directly, so it must re-check server-validated
        # identity rather than rely on button visibility.
        from shyfem_ui.services.access_control import editor_denied_reason

        _usr = current_user() if current_user is not None else None
        _pid = project_id.get() if project_id is not None else None
        _denied = editor_denied_reason(_pid, _usr, min_role="editor")
        if _denied:
            validation_errors.set([_denied])
            return

        text = input.editor_content()
        try:
            errors = validate_str_content(text)
            if errors:
                validation_errors.set(errors)
                return

            path.write_text(text)
            content.set(text)
            parsed_file.set(StrParser.parse(text))
            validation_errors.set([])
            is_modified.set(False)

            if on_save:
                on_save(path, text)

        except Exception as e:
            validation_errors.set([f"Error saving file: {e}"])

    @reactive.effect
    @reactive.event(input.validate_btn)
    def _handle_validate():
        text = input.editor_content()
        errors = validate_str_content(text)
        validation_errors.set(errors if errors else ["File is valid"])

    @reactive.effect
    @reactive.event(input.insert_section)
    def _handle_insert_section():
        section = input.insert_section()
        if not section:
            return

        template = generate_section_template(section)
        current = input.editor_content() or ""

        new_content = current.rstrip() + "\n\n" + template
        ui.update_text_area("editor_content", value=new_content)
        ui.update_select("insert_section", selected="")

    # --- View rendering ---

    @render.ui
    def editor_view():
        mode = input.view_mode()
        parsed = parsed_file.get()

        raw_panel = ui.div(
            ui.input_text_area(
                "editor_content",
                "",
                height="500px",
                resize="vertical",
            ),
            class_="str-editor-area",
            style="font-family: monospace; font-size: 13px;",
        )

        # Compute search filter
        try:
            search_term = input.param_search()
        except Exception:
            search_term = ""
        search_filter = filter_sections(search_term, parsed)
        pid = project_id.get() if project_id else None
        choices = list(file_choices()) if file_choices is not None else []
        form_panel = _build_form_panel(
            parsed, search_filter=search_filter, project_id=pid, file_choices=choices
        )

        if mode == "raw":
            return raw_panel
        elif mode == "form":
            return form_panel
        else:
            # Split view
            return ui.row(
                ui.column(6, raw_panel),
                ui.column(6, form_panel),
            )

    @render.ui
    def status_bar():
        path = file_path.get()
        modified = is_modified.get()

        path_str = str(path) if path else "No file loaded"
        modified_str = " (modified)" if modified else ""

        parsed = parsed_file.get()
        sections_str = ""
        if parsed:
            section_count = len(parsed.sections)
            sections_str = f" | {section_count} sections"

        return ui.div(
            ui.span(path_str + modified_str, class_="text-muted small"),
            ui.span(sections_str, class_="text-info small"),
            class_="d-flex justify-content-between",
        )

    @render.ui
    def validation_messages():
        errors = validation_errors.get()
        if not errors:
            return None

        is_success = len(errors) == 1 and "valid" in errors[0].lower()

        items = [ui.tags.li(error, class_="small") for error in errors]

        return ui.div(
            ui.tags.ul(*items, class_="mb-0"),
            class_=f"alert {'alert-success' if is_success else 'alert-warning'} mt-2 py-2",
        )

    def set_content_text(text: str) -> None:
        """Update the editor content from an external caller.

        This avoids the parent having to know the internal input ID.
        """
        ui.update_text_area("editor_content", value=text)

    return {
        "content": content,
        "parsed_file": parsed_file,
        "is_modified": is_modified,
        "set_content": set_content_text,
    }


def _build_form_panel(
    parsed: StrFile | None,
    search_filter: dict[str, list[str]] | None = None,
    project_id: int | None = None,
    file_choices: Sequence[str] = (),
) -> ui.Tag:
    """Build the structured form panel from parsed STR file data.

    File parameters (wind, boundn, restrt, ...) render as a selectize over
    ``file_choices`` (project-relative) that also accepts a typed name.
    """
    if parsed is None or not parsed.sections:
        return ui.div(
            ui.p(
                "No file loaded. Load or create a parameter file to see structured form.",
                class_="text-muted text-center p-4",
            ),
        )

    section_cards = []
    for section_name, section in parsed.sections.items():
        if search_filter is not None and section_name not in search_filter:
            continue
        matching_params = search_filter.get(section_name) if search_filter is not None else None

        color = SECTION_COLORS.get(section_name, "#6c757d")
        section_desc = COMMON_SECTIONS.get(section_name, "")
        known_params = COMMON_PARAMS.get(section_name, {})

        fields = []
        # Known parameters with rich metadata
        for param_name, param_val in section.parameters.items():
            if param_name.startswith("_"):
                # Standalone entries
                if param_name == "_standalone" and isinstance(param_val, list):
                    for item in param_val:
                        fields.append(
                            ui.div(
                                ui.span(f"Node {item['id']}", class_="fw-bold small"),
                                ui.span(f": {item['description']}", class_="text-muted small"),
                                class_="mb-1",
                            )
                        )
                continue

            # Skip non-matching params when filter is active
            if matching_params is not None and param_name not in matching_params:
                continue

            highlight_style = (
                "background-color: #fff3cd; padding: 0 4px; border-radius: 2px;"
                if matching_params and param_name in matching_params
                else ""
            )

            info = known_params.get(param_name)
            field_id = f"form_{section_name}_{param_name}"

            if info:
                desc, ptype, default, units, options = info
                # Build tooltip text
                tooltip = desc
                if default is not None:
                    tooltip += f" (default: {default})"
                if options:
                    tooltip += f" [{options}]"

                label_parts = [ui.span(param_name, class_="fw-bold small", style=highlight_style)]
                if units:
                    label_parts.append(ui.span(f" ({units})", class_="text-muted small"))

                label = ui.div(*label_parts, title=tooltip)

                # Choose input type based on parameter type and options
                if ptype == "int" and options and "/" in options:
                    # Enumerated options like "0/1" or "0=off,1=on"
                    choices = _parse_options_to_choices(options, param_val)
                    fields.append(
                        ui.div(
                            label,
                            ui.input_select(
                                field_id,
                                "",
                                choices=choices,
                                selected=str(param_val),
                                width="100%",
                            ),
                            class_="mb-2",
                        )
                    )
                elif is_file_param(param_name):
                    fields.append(
                        ui.div(
                            label,
                            str_file_selectize(field_id, "", str(param_val), file_choices),
                            class_="mb-2",
                        )
                    )
                else:
                    fields.append(
                        ui.div(
                            label,
                            ui.input_text(
                                field_id,
                                "",
                                value=str(param_val),
                            ),
                            class_="mb-2",
                        )
                    )
            else:
                # Unknown parameter — check if it's a file param
                if is_file_param(param_name):
                    fields.append(
                        ui.div(
                            ui.span(param_name, class_="fw-bold small", style=highlight_style),
                            str_file_selectize(field_id, "", str(param_val), file_choices),
                            class_="mb-2",
                        )
                    )
                else:
                    fields.append(
                        ui.div(
                            ui.span(param_name, class_="fw-bold small", style=highlight_style),
                            ui.input_text(
                                field_id,
                                "",
                                value=str(param_val),
                            ),
                            class_="mb-2",
                        )
                    )

        section_cards.append(
            ui.div(
                ui.div(
                    _section_badge(section_name),
                    (
                        ui.span(f" {section_desc}", class_="text-muted small ms-2")
                        if section_desc
                        else None
                    ),
                    class_="card-header py-2",
                    style=f"border-left: 3px solid {color};",
                ),
                ui.div(
                    *fields if fields else [ui.p("(empty section)", class_="text-muted small")],
                    class_="card-body py-2 px-3",
                ),
                class_="card mb-2",
            )
        )

    # Build match count badge
    match_info = None
    if search_filter is not None:
        total_params = sum(len(v) for v in search_filter.values())
        total_sections = len(search_filter)
        if total_params > 0:
            match_info = ui.span(
                f"{total_params} param{'s' if total_params != 1 else ''} in "
                f"{total_sections} section{'s' if total_sections != 1 else ''}",
                class_="badge bg-info text-dark ms-2",
            )
        else:
            match_info = ui.span("No matches", class_="badge bg-secondary ms-2")

    return ui.div(
        # Search bar
        ui.div(
            ui.div(
                ui.input_text(
                    "param_search",
                    "",
                    placeholder="Search parameters (e.g. 'wind', 'time step')...",
                    width="100%",
                ),
                match_info,
                class_="d-flex align-items-center",
            ),
            class_="mb-2",
        ),
        ui.div(
            ui.input_action_button(
                "apply_form_btn",
                "Apply Form Changes",
                class_="btn-sm btn-primary mb-2",
            ),
            class_="d-flex justify-content-end",
        ),
        (
            ui.div(
                *section_cards,
                style="max-height: 500px; overflow-y: auto;",
            )
            if section_cards
            else ui.div(
                ui.p("No matching parameters.", class_="text-muted text-center p-4"),
            )
        ),
    )


def _parse_options_to_choices(options_str: str, current_val: Any) -> dict[str, str]:
    """Parse option strings like '0=off, 1=on' or '0/1' into select choices."""
    choices = {}
    # Try "key=desc" format first: "0=none,1=full,2=diagnostic"
    if "=" in options_str:
        for part in options_str.split(","):
            part = part.strip()
            if "=" in part:
                key, desc = part.split("=", 1)
                key = key.strip()
                choices[key] = f"{key} - {desc.strip()}"
    elif "/" in options_str:
        # Simple "0/1" format
        for val in options_str.split("/"):
            val = val.strip()
            choices[val] = val

    # Ensure current value is in choices
    val_str = str(current_val)
    if val_str not in choices:
        choices[val_str] = f"{val_str} (current)"

    return choices


def filter_sections(
    search_term: str,
    parsed: StrFile | None,
) -> dict[str, list[str]] | None:
    """Filter parsed STR sections/params by search term.

    Args:
        search_term: User's search text (case-insensitive substring).
        parsed: Parsed STR file.

    Returns:
        None if search_term is blank (meaning "show all").
        Otherwise dict mapping section_name -> list of matching param names.
        Sections with zero matches are omitted.
    """
    if not search_term or not search_term.strip():
        return None
    if parsed is None:
        return {}

    term = search_term.strip().lower()
    result: dict[str, list[str]] = {}

    for section_name, section in parsed.sections.items():
        matches = []
        known_params = COMMON_PARAMS.get(section_name, {})

        for param_name in section.parameters:
            if param_name.startswith("_"):
                continue

            # Match against param name
            if term in param_name.lower():
                matches.append(param_name)
                continue

            # Match against description (known params only)
            info = known_params.get(param_name)
            if info:
                desc = info[0]  # (description, type, default, units, options)
                if term in desc.lower():
                    matches.append(param_name)

        if matches:
            result[section_name] = matches

    return result


def validate_str_content(
    content: str, check_files: bool = False, working_dir: Path | None = None
) -> list[str]:
    """Validate STR file content and return list of errors and warnings.

    Args:
        content: Raw .str file text
        check_files: If True, verify that referenced files exist on disk
        working_dir: Working directory for resolving relative file paths
    """
    errors = []
    warnings = []

    try:
        parsed = StrParser.parse(content)
    except Exception as e:
        return [f"Parse error: {e}"]

    # --- Structural checks ---

    lines = content.splitlines()
    section_stack = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip().lower()
        if stripped.startswith("$") and not stripped.startswith("$end"):
            section_name = stripped[1:]
            section_stack.append((section_name, i))
        elif stripped == "$end":
            if not section_stack:
                errors.append(f"Line {i}: Unexpected $end without matching section start")
            else:
                section_stack.pop()

    for section_name, line_num in section_stack:
        errors.append(f"Line {line_num}: Section ${section_name} not closed")

    # --- Required sections ---

    if "para" not in parsed.sections:
        errors.append("Missing required section: $para")
    if "title" not in parsed.sections:
        warnings.append("Warning: Missing $title section (recommended)")

    # --- $para time parameter checks ---

    if "para" in parsed.sections:
        para = parsed.sections["para"]
        params = para.parameters

        # Required timing params
        has_itanf = "itanf" in params or "itanf" in str(para.raw_lines)
        has_itend = "itend" in params or "itend" in str(para.raw_lines)
        has_idt = "idt" in params or "idt" in str(para.raw_lines)

        if not has_itanf:
            errors.append("$para: Missing start time (itanf)")
        if not has_itend:
            errors.append("$para: Missing end time (itend)")
        if not has_idt:
            errors.append("$para: Missing time step (idt)")

        # Time consistency: itanf < itend (when both are numeric)
        itanf = params.get("itanf")
        itend = params.get("itend")
        if isinstance(itanf, (int, float)) and isinstance(itend, (int, float)):
            if itanf >= itend:
                errors.append(f"$para: itanf ({itanf}) must be less than itend ({itend})")

        # Time step positivity
        idt = params.get("idt")
        if isinstance(idt, (int, float)) and idt <= 0:
            errors.append(f"$para: idt ({idt}) must be positive")

        # Depth sanity
        hzmin = params.get("hzmin")
        hzoff = params.get("hzoff")
        if isinstance(hzmin, (int, float)) and isinstance(hzoff, (int, float)):
            if hzmin >= hzoff:
                warnings.append(
                    f"Warning: $para hzmin ({hzmin}) should be less than hzoff ({hzoff})"
                )

        # Value range checks from COMMON_PARAMS
        known_para = COMMON_PARAMS.get("para", {})
        for param_name, value in params.items():
            if param_name.startswith("_"):
                continue
            info = known_para.get(param_name)
            if info:
                _desc, ptype, _default, _units, options = info
                if options and isinstance(value, (int, float)):
                    _check_range(warnings, "para", param_name, value, options)
            else:
                # Unknown parameter — soft warning
                if not any(param_name.startswith(p) for p in ("itm", "idt")):
                    warnings.append(f"Warning: $para unknown parameter '{param_name}'")

    # --- $name file existence checks ---

    if check_files and working_dir and "name" in parsed.sections:
        name_section = parsed.sections["name"]
        for param_name, value in name_section.parameters.items():
            if param_name.startswith("_") or not isinstance(value, str):
                continue
            file_path = Path(value)
            if not file_path.is_absolute():
                file_path = working_dir / file_path
            if not file_path.exists():
                warnings.append(f"Warning: $name {param_name} file not found: {value}")

    # --- Boundary section checks ---

    for section_name, section in parsed.sections.items():
        if section_name.startswith("bound") and section_name != "bound":
            params = section.parameters
            if "ibtyp" not in params and "ibtyp" not in str(section.raw_lines):
                warnings.append(f"Warning: ${section_name} missing boundary type (ibtyp)")

    # Combine errors (first) and warnings (after)
    return errors + warnings


def _check_range(
    warnings: list[str], section: str, param: str, value: float, options_str: str
) -> None:
    """Check if a value is within the range specified in options_str."""
    import re

    # Check [min,max] ranges
    bracket_match = re.match(r"\[([^,]+),\s*([^\]]+)\]", options_str)
    if bracket_match:
        try:
            lo = float(bracket_match.group(1))
            hi = float(bracket_match.group(2))
            if value < lo or value > hi:
                warnings.append(f"Warning: ${section} {param}={value} outside range [{lo},{hi}]")
        except ValueError:
            logger.debug("Could not parse range '%s' for %s.%s", options_str, section, param)
        return

    # Check >0 or >=0 constraints
    if options_str == ">0" and value <= 0:
        warnings.append(f"Warning: ${section} {param}={value} should be >0")
    elif options_str == ">=0" and value < 0:
        warnings.append(f"Warning: ${section} {param}={value} should be >=0")


def generate_section_template(section_name: str) -> str:
    """Generate a template for a section."""
    if section_name == "para":
        return """$para
        itanf = '2020-01-01'    itend = '2020-01-02'
        idt = '300s'
        idtout = '1h'
        date = 20200101
$end"""
    elif section_name == "title":
        return """$title
        Simulation Title
        simulation_name
        GRID/grid_name
$end"""
    elif section_name == "extra":
        return """$extra
        1     'output node 1'
$end"""
    elif section_name == "name":
        return """$name
        wind = 'INPUT/wind.txt'
$end"""
    elif section_name == "bound":
        return """$bound
        1  0  1  0.0
$end"""
    else:
        return f"""${section_name}
        ! Add parameters here
$end"""
