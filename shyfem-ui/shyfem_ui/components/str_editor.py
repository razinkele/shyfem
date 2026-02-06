"""STR file editor component with syntax highlighting."""

from pathlib import Path
from typing import Optional

from shiny import module, reactive, render, ui

from shyfem_ui.services.parser_str import COMMON_PARAMS, COMMON_SECTIONS, StrFile, StrParser


@module.ui
def str_editor_ui(height: str = "500px"):
    """STR file editor component UI.

    Args:
        height: CSS height for the editor
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
                None,
                choices={"": "Insert Section...", **COMMON_SECTIONS},
                width="200px",
            ),
            class_="d-flex align-items-center mb-2",
        ),
        # Editor area
        ui.div(
            ui.input_text_area(
                "editor_content",
                None,
                height=height,
                resize="vertical",
            ),
            class_="str-editor-area",
        ),
        # Status bar
        ui.div(
            ui.output_ui("status_bar"),
            class_="str-editor-status mt-1",
        ),
        # Validation messages
        ui.output_ui("validation_messages"),
        class_="str-editor-component",
        # Add custom CSS for monospace font
        style="",
    )


@module.server
def str_editor_server(
    input,
    output,
    session,
    file_path: reactive.Value[Optional[Path]],
    on_save: Optional[callable] = None,
):
    """STR file editor component server logic.

    Args:
        file_path: Reactive value containing the file path to edit
        on_save: Callback when file is saved
    """
    content = reactive.value("")
    parsed_file = reactive.value(None)
    validation_errors = reactive.value([])
    is_modified = reactive.value(False)

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
        is_modified.set(True)

    @reactive.effect
    @reactive.event(input.load_btn)
    def _handle_load():
        # Trigger reload
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

        text = input.editor_content()
        try:
            # Validate before saving
            errors = validate_str_content(text)
            if errors:
                validation_errors.set(errors)
                return

            # Save file
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

        # Generate section template
        template = generate_section_template(section)
        current = input.editor_content() or ""

        # Append to end
        new_content = current.rstrip() + "\n\n" + template
        ui.update_text_area("editor_content", value=new_content)

        # Reset dropdown
        ui.update_select("insert_section", selected="")

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

        items = [
            ui.li(error, class_="small")
            for error in errors
        ]

        return ui.div(
            ui.ul(*items, class_="mb-0"),
            class_=f"alert {'alert-success' if is_success else 'alert-warning'} mt-2 py-2",
        )

    return {
        "content": content,
        "parsed_file": parsed_file,
        "is_modified": is_modified,
    }


def validate_str_content(content: str) -> list[str]:
    """Validate STR file content and return list of errors."""
    errors = []

    try:
        parsed = StrParser.parse(content)
    except Exception as e:
        return [f"Parse error: {e}"]

    # Check for unmatched sections
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

    # Check for required sections
    if "para" not in parsed.sections:
        errors.append("Missing required section: $para")

    # Check for common parameter issues
    if "para" in parsed.sections:
        para = parsed.sections["para"]
        if "itanf" not in para.parameters and "itanf" not in str(para.raw_lines):
            errors.append("Section $para: Missing start time (itanf)")
        if "itend" not in para.parameters and "itend" not in str(para.raw_lines):
            errors.append("Section $para: Missing end time (itend)")

    return errors


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


def get_parameter_help(section: str, param: str) -> Optional[str]:
    """Get help text for a parameter."""
    section_params = COMMON_PARAMS.get(section, {})
    param_info = section_params.get(param)

    if param_info:
        description, param_type = param_info
        return f"{description} ({param_type})"

    return None
