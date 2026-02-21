"""File browser component for selecting and uploading files."""

import logging
from collections.abc import Callable
from pathlib import Path

from shiny import module, reactive, render, ui
from shiny.types import FileInfo

logger = logging.getLogger(__name__)


def validate_upload(
    file_info: dict,
    accept: list[str] | None,
    max_size_bytes: int,
) -> list[str]:
    """Validate an uploaded file's size and extension.

    Args:
        file_info: Shiny FileInfo dict with 'name' and 'size' keys.
        accept: List of accepted extensions (e.g., [".grd"]). None allows all.
        max_size_bytes: Maximum file size in bytes.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors = []

    size = file_info.get("size", 0)
    if size > max_size_bytes:
        size_mb = size / (1024 * 1024)
        max_mb = max_size_bytes / (1024 * 1024)
        errors.append(f"File too large: {size_mb:.1f} MB (max {max_mb:.0f} MB)")

    if accept:
        suffix = Path(file_info.get("name", "")).suffix.lower()
        allowed = [ext.lower() for ext in accept]
        if suffix not in allowed:
            errors.append(f"Invalid file type: {suffix}. Expected: {', '.join(accept)}")

    return errors


def infer_file_type(filename: str) -> str:
    """Infer file_type category from filename/path.

    Args:
        filename: Filename or relative path (e.g. "mesh.grd", "INPUT/wind.fem").

    Returns:
        One of: grid, basin, str, restart, config, output, forcing, other.
    """
    from pathlib import PurePosixPath

    p = PurePosixPath(filename)
    ext = p.suffix.lower()
    if ext == ".grd":
        return "grid"
    if ext == ".bas":
        return "basin"
    if ext == ".str":
        return "str"
    if ext == ".rst":
        return "restart"
    if ext == ".nml":
        return "config"
    if ext in (".shy", ".nc"):
        return "output"
    # Subdirectory hint
    if len(p.parts) > 1 and p.parts[0].upper() == "INPUT":
        return "forcing"
    return "other"


def persist_upload(
    temp_path: Path,
    filename: str,
    project_id: int | None,
    file_type: str | None = None,
    subdir: str | None = None,
) -> dict | None:
    """Persist an uploaded file to a project via FileService.

    Args:
        temp_path: Path to the temporary uploaded file.
        filename: Original filename.
        project_id: Target project ID. If None, returns None (no persistence).
        file_type: File category. If None, inferred from filename.
        subdir: Optional subdirectory within project work_dir.

    Returns:
        ProjectFile dict on success, None if project_id is None or on error.
    """
    if project_id is None:
        return None

    if file_type is None:
        file_type = infer_file_type(filename)

    try:
        from shyfem_ui.services.file_service import FileService

        file_data = temp_path.read_bytes()
        return FileService.upload_file(
            project_id=project_id,
            file_data=file_data,
            filename=filename,
            file_type=file_type,
            subdir=subdir,
        )
    except Exception:
        logger.warning(
            "Failed to persist upload %s to project %s",
            filename,
            project_id,
            exc_info=True,
        )
        return None


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
    accept: list[str] | None = None,
):
    """File browser component server logic.

    Args:
        on_file_selected: Callback when files are selected
        accept: List of accepted file extensions (e.g., [".grd"]). None allows all.
    """
    selected_files = reactive.value([])

    @reactive.effect
    @reactive.event(input.file_input)
    def _handle_file_selection():
        from shyfem_ui.config import get_config

        files = input.file_input()
        if not files:
            return

        config = get_config()
        max_size_bytes = config.max_upload_size_mb * 1024 * 1024

        valid_files = []
        for f in files:
            errors = validate_upload(f, accept=accept, max_size_bytes=max_size_bytes)
            if errors:
                for err in errors:
                    ui.notification_show(err, type="error", duration=8)
                    logger.warning("Upload rejected: %s — %s", f.get("name", "?"), err)
            else:
                valid_files.append(f)

        if valid_files:
            selected_files.set(valid_files)
            if on_file_selected:
                on_file_selected(valid_files)

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
