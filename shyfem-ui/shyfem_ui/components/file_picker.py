"""File picker component for selecting project files in forms."""

import logging
from collections.abc import Callable

from shiny import module, reactive, ui

logger = logging.getLogger(__name__)

# STR parameters that reference files -- from FileService
_NAME_FILE_PARAMS = frozenset({
    "wind", "rain", "qflux", "ice", "zinit", "tempin", "saltin",
    "conzin", "restrt", "tempobs", "saltobs", "gotmpa", "basnam",
    "offlin", "surfvel", "temptau", "salttau",
})

_BOUND_FILE_PARAMS = frozenset({
    "boundn", "tempn", "saltn", "conzn", "vel3dn", "bio2dn", "sed2dn",
})

# Parameter -> file_types filter mapping
_PARAM_TYPE_MAP = {
    # Forcing files
    "wind": ["forcing"], "rain": ["forcing"], "qflux": ["forcing"],
    "ice": ["forcing"], "surfvel": ["forcing"],
    # Boundary + forcing
    "boundn": ["boundary", "forcing"], "tempn": ["boundary", "forcing"],
    "saltn": ["boundary", "forcing"], "conzn": ["boundary", "forcing"],
    "vel3dn": ["boundary", "forcing"], "bio2dn": ["boundary", "forcing"],
    "sed2dn": ["boundary", "forcing"],
    # Initial conditions
    "zinit": ["initial_condition", "forcing"],
    "tempin": ["initial_condition", "forcing"],
    "saltin": ["initial_condition", "forcing"],
    "conzin": ["initial_condition", "forcing"],
    # Restart
    "restrt": ["restart"],
    # Config
    "gotmpa": ["config"],
    # Observations
    "tempobs": ["forcing"], "saltobs": ["forcing"],
    "temptau": ["forcing"], "salttau": ["forcing"],
    # Other
    "basnam": ["basin"], "offlin": ["forcing"],
}


def is_file_param(param_name: str) -> bool:
    """Check if an STR parameter name references a file."""
    return param_name in _NAME_FILE_PARAMS or param_name in _BOUND_FILE_PARAMS


def param_to_file_types(param_name: str) -> list[str] | None:
    """Map an STR parameter name to file_types filter for the picker.

    Returns None if the parameter is not a file parameter.
    """
    return _PARAM_TYPE_MAP.get(param_name)


def build_file_choices(
    project_id: int | None,
    file_types: list[str] | None = None,
) -> dict:
    """Build {display_label: rel_path} choices from project files.

    Args:
        project_id: Project to list files from. None returns empty dict.
        file_types: Optional filter by file type categories.

    Returns:
        Dict mapping "filename (type)" display labels to rel_path values.
    """
    if project_id is None:
        return {}

    from shyfem_ui.services.file_service import FileService

    if file_types:
        files = []
        for ft in file_types:
            files.extend(FileService.list_files(project_id, file_type=ft))
        # Deduplicate by id
        seen: set[int] = set()
        unique = []
        for f in files:
            if f["id"] not in seen:
                seen.add(f["id"])
                unique.append(f)
        files = unique
    else:
        files = FileService.list_files(project_id)

    choices = {}
    for f in sorted(files, key=lambda x: x["rel_path"]):
        label = f"{f['rel_path']} ({f['file_type']})"
        choices[label] = f["rel_path"]
    return choices


@module.ui
def file_picker_ui(label: str = "Select File"):
    """File picker UI -- dropdown with browse button."""
    return ui.div(
        ui.div(
            ui.div(
                ui.input_select(
                    "file_select",
                    label,
                    choices={"": "No files available"},
                    width="100%",
                ),
                class_="flex-grow-1",
            ),
            ui.div(
                ui.input_action_button(
                    "browse_btn",
                    "Browse...",
                    class_="btn-sm btn-outline-secondary mt-4",
                ),
                class_="ms-2",
            ),
            class_="d-flex align-items-start",
        ),
        class_="file-picker-component",
    )


@module.server
def file_picker_server(
    input,
    output,
    session,
    project_id: reactive.Value | None = None,
    file_types: list[str] | None = None,
    on_selected: Callable[[str], None] | None = None,
):
    """File picker server logic.

    Args:
        project_id: Reactive value with current project ID.
        file_types: Filter file list by these types.
        on_selected: Callback fired with rel_path when selection changes.

    Returns:
        reactive.Value[str] -- current selected rel_path.
    """
    selected_path = reactive.value("")

    @reactive.effect
    def _update_choices():
        pid = project_id.get() if project_id else None
        choices = build_file_choices(pid, file_types=file_types)
        if choices:
            ui.update_select(
                "file_select",
                choices={"": "-- Select file --", **choices},
            )
        else:
            ui.update_select(
                "file_select",
                choices={"": "No files available"},
            )

    @reactive.effect
    @reactive.event(input.file_select)
    def _on_selection():
        val = input.file_select()
        if val:
            selected_path.set(val)
            if on_selected:
                on_selected(val)

    @reactive.effect
    @reactive.event(input.browse_btn)
    def _show_browse_modal():
        pid = project_id.get() if project_id else None
        if pid is None:
            ui.notification_show(
                "No active project. Select a project first.",
                type="warning",
            )
            return

        from shyfem_ui.services.file_service import FileService
        files = FileService.list_files(pid)

        rows = []
        for f in files:
            size_str = _format_size(f["size_bytes"])
            type_badge = ui.span(f["file_type"], class_="badge bg-secondary")
            select_btn = ui.input_action_button(
                f"pick_{f['id']}",
                "Select",
                class_="btn-sm btn-outline-primary",
            )
            rows.append(
                ui.tags.tr(
                    ui.tags.td(f["filename"]),
                    ui.tags.td(type_badge),
                    ui.tags.td(f["rel_path"]),
                    ui.tags.td(size_str),
                    ui.tags.td(select_btn),
                )
            )

        table = (
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Name"),
                        ui.tags.th("Type"),
                        ui.tags.th("Path"),
                        ui.tags.th("Size"),
                        ui.tags.th(""),
                    )
                ),
                ui.tags.tbody(*rows),
                class_="table table-sm table-hover",
            )
            if rows
            else ui.p(
                "No files in project. Upload files first.",
                class_="text-muted",
            )
        )

        m = ui.modal(
            table,
            title="Browse Project Files",
            size="l",
            easy_close=True,
        )
        ui.modal_show(m)

        # Register click handlers for each file's select button
        for f in files:
            _register_pick_handler(f["id"], f["rel_path"])

    def _register_pick_handler(file_id: int, rel_path: str):
        btn_id = f"pick_{file_id}"

        @reactive.effect
        @reactive.event(getattr(input, btn_id))
        def _pick():
            selected_path.set(rel_path)
            # Update dropdown to match
            choices = build_file_choices(
                project_id.get() if project_id else None,
                file_types=file_types,
            )
            ui.update_select(
                "file_select",
                choices={"": "-- Select file --", **choices},
                selected=rel_path,
            )
            if on_selected:
                on_selected(rel_path)
            ui.modal_remove()

    return selected_path


def _format_size(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"
