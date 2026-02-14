"""File browser component for selecting and uploading files."""

from collections.abc import Callable

from shiny import module, reactive, render, ui
from shiny.types import FileInfo


@module.ui
def file_browser_ui(
    label: str = "Select File",
    accept: list[str] | None = None,
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
    on_file_selected: Callable[[list[FileInfo]], None] | None = None,
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
