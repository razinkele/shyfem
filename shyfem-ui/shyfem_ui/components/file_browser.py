"""File browser component for selecting and uploading files."""

from pathlib import Path
from typing import Callable, Optional

from shiny import module, reactive, render, ui
from shiny.types import FileInfo


@module.ui
def file_browser_ui(
    label: str = "Select File",
    accept: Optional[list[str]] = None,
    multiple: bool = False,
    placeholder: str = "No file selected",
):
    """File browser component UI.

    Args:
        label: Label for the file input
        accept: List of accepted file extensions (e.g., [".grd", ".bas"])
        multiple: Allow multiple file selection
        placeholder: Placeholder text when no file is selected
    """
    accept_str = ",".join(accept) if accept else None

    return ui.div(
        ui.input_file(
            "file_input",
            label,
            accept=accept_str,
            multiple=multiple,
            placeholder=placeholder,
        ),
        ui.output_ui("file_info"),
        class_="file-browser-component",
    )


@module.server
def file_browser_server(
    input,
    output,
    session,
    on_file_selected: Optional[Callable[[list[FileInfo]], None]] = None,
):
    """File browser component server logic.

    Args:
        on_file_selected: Callback when files are selected
    """
    selected_files = reactive.value([])

    @reactive.effect
    @reactive.event(input.file_input)
    def _handle_file_selection():
        files = input.file_input()
        if files:
            selected_files.set(files)
            if on_file_selected:
                on_file_selected(files)

    @render.ui
    def file_info():
        files = selected_files.get()
        if not files:
            return ui.p("No file selected", class_="text-muted")

        items = []
        for f in files:
            size_kb = f["size"] / 1024
            items.append(
                ui.div(
                    ui.span(f["name"], class_="fw-bold"),
                    ui.span(f" ({size_kb:.1f} KB)", class_="text-muted"),
                    class_="file-info-item",
                )
            )
        return ui.div(*items)

    return selected_files


def create_directory_browser(
    id: str,
    label: str = "Select Directory",
    initial_path: Optional[Path] = None,
) -> ui.Tag:
    """Create a directory browser component.

    Note: True directory selection is not supported in web browsers.
    This provides a text input for path entry with path validation.
    """
    initial_value = str(initial_path) if initial_path else ""

    return ui.div(
        ui.input_text(
            f"{id}_path",
            label,
            value=initial_value,
            placeholder="/path/to/directory",
        ),
        ui.output_ui(f"{id}_validation"),
        class_="directory-browser-component",
    )


def validate_path(path_str: str, must_exist: bool = True) -> tuple[bool, str]:
    """Validate a file/directory path.

    Returns:
        Tuple of (is_valid, message)
    """
    if not path_str:
        return False, "Path is empty"

    path = Path(path_str)

    if must_exist and not path.exists():
        return False, f"Path does not exist: {path_str}"

    if must_exist and not (path.is_file() or path.is_dir()):
        return False, f"Path is not a file or directory: {path_str}"

    return True, "Valid path"


def get_file_icon(filename: str) -> str:
    """Get an appropriate icon for a file type."""
    ext = Path(filename).suffix.lower()

    icons = {
        ".grd": "📐",
        ".bas": "🗄️",
        ".str": "📝",
        ".shy": "💧",
        ".ext": "📊",
        ".nc": "🌐",
        ".png": "🖼️",
        ".pdf": "📄",
        ".txt": "📃",
        ".log": "📋",
    }

    return icons.get(ext, "📁")
