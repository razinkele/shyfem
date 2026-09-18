"""File picker component for selecting project files in forms."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from shiny import module, reactive, ui

if TYPE_CHECKING:
    from shyfem_ui.services.project_context import ProjectContext

logger = logging.getLogger(__name__)

# STR parameters that reference files -- from FileService
_NAME_FILE_PARAMS = frozenset(
    {
        "wind",
        "rain",
        "qflux",
        "ice",
        "zinit",
        "tempin",
        "saltin",
        "conzin",
        "restrt",
        "tempobs",
        "saltobs",
        "gotmpa",
        "basnam",
        "offlin",
        "surfvel",
        "temptau",
        "salttau",
    }
)

_BOUND_FILE_PARAMS = frozenset(
    {
        "boundn",
        "tempn",
        "saltn",
        "conzn",
        "vel3dn",
        "bio2dn",
        "sed2dn",
    }
)


def is_file_param(param_name: str) -> bool:
    """Check if an STR parameter name references a file."""
    return param_name in _NAME_FILE_PARAMS or param_name in _BOUND_FILE_PARAMS


#: File-type category -> filename extensions, for listing project files that
#: were placed on disk outside the upload flow (which never got a DB row and so
#: were invisible to the picker). Only categories with an *unambiguous*
#: extension are listed from disk: forcing/boundary/etc. share ``.fem``/``.txt``
#: /``.dat``, so a disk scan can't honour their DB category and would leak
#: cross-category files -- those keep relying on DB uploads.
_TYPE_EXTS: dict[str, tuple[str, ...]] = {
    "grid": (".grd",),
    "basin": (".bas",),
    "str": (".str",),
    "output": (".shy", ".nc"),
    "lagrangian": (".lgr",),
}


def _disk_file_rels(project_id: int, file_types: list[str] | None) -> list[str]:
    """Project-relative paths of on-disk files matching ``file_types``.

    Looks up the project's ``work_dir`` and scans it (recursively, hidden
    trees skipped) so projects populated outside the upload flow still list
    their files. Returns [] on any lookup/scan problem -- never raises.
    """
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project
    from shyfem_ui.services.project_files import list_project_files

    if file_types:
        exts: tuple[str, ...] = tuple(e for ft in file_types for e in _TYPE_EXTS.get(ft, ()))
    else:
        exts = tuple({e for v in _TYPE_EXTS.values() for e in v})
    if not exts:
        return []
    try:
        with db_session() as db:
            proj = db.query(Project).filter_by(id=project_id).first()
            work_dir = proj.work_dir if proj else None
    except Exception:
        logger.warning("build_file_choices: project %s work_dir lookup failed", project_id)
        return []
    if not work_dir:
        return []
    return list_project_files(Path(work_dir), exts)


def build_file_choices(
    project_id: int | None,
    file_types: list[str] | None = None,
) -> dict:
    """Build {display_label: rel_path} choices from project files.

    Includes both DB-registered uploads and files found on disk in the
    project directory (so a project populated outside the upload flow -- e.g.
    an imported analysis project -- still lists its files).

    Args:
        project_id: Project to list files from. None returns empty dict.
        file_types: Optional filter by file type categories.

    Returns:
        Dict mapping display labels to rel_path values.
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

    # Merge in on-disk files not already registered in the DB (dedup by
    # rel_path, which is the picker's option value).
    known = set(choices.values())
    for rel in _disk_file_rels(project_id, file_types):
        if rel not in known:
            choices[rel] = rel
            known.add(rel)
    return choices


def resolve_picker_path(
    active_project: "ProjectContext | None",
    rel_path: str | None,
) -> str | None:
    """Resolve a project-relative path to an absolute path.

    Returns None if the project is unknown, rel_path is empty, or the
    resolved path would escape the project work_dir (path traversal
    guard — Path(work_dir) / "/etc/passwd" silently yields /etc/passwd,
    and Path(work_dir) / "../../etc" escapes the root).

    Returns None on five distinct conditions: None project, empty
    rel_path, missing work_dir key, empty work_dir, traversal guard.
    Callers needing branch info must consume the WARNING log records
    — the return value alone does not differentiate. The
    security-relevant branches (missing/empty work_dir, traversal)
    emit logger.warning so containment failures don't disappear
    silently across the 6 follow-up pages that will reuse this helper.
    """
    if active_project is None or not rel_path:
        return None
    work_dir = active_project.get("work_dir")
    if not work_dir:
        logger.warning(
            "Picker resolution failed: project %r has no work_dir " "(legacy/corrupt row?)",
            active_project.get("id"),
        )
        return None
    root = Path(work_dir).resolve()
    resolved = (root / rel_path).resolve()
    if not resolved.is_relative_to(root):
        logger.warning(
            "Picker rel_path %r escapes work_dir %r — " "dropdown/project state mismatch",
            rel_path,
            work_dir,
        )
        return None
    return str(resolved)


# Set of input ids that the file picker can target. Literal-typed so
# typos at call sites (e.g. fill_picker_input("bad_path", ...)) surface
# at type-check time rather than as silent ui.update_text("bad_path",
# ...) no-ops.
PickerTargetId = Literal[
    "bas_path",
    "grd_path",
    "shy_path",
    "str_path",
    "input_file",
    "lgr_path",
]


def fill_picker_input(
    target_id: PickerTargetId,
    project: "ProjectContext | None",
    rel_path: str,
) -> None:
    """Resolve a picker selection and write it to a Shiny text input.

    Bridges resolve_picker_path's pure logic to the session-bound
    ui.update_text + ui.notification_show calls. Silent on the benign
    empty-state (no project / empty rel_path); logs a WARNING naming
    target_id and shows a warning toast when a non-empty selection
    fails to resolve. See resolve_picker_path's docstring for the
    containment / traversal contract.

    Args:
        target_id: Shiny text input id (no namespace prefix).
        project: unwrapped ProjectContext, or None for benign empty-state.
            Callers pass `active_project.get() if active_project else None`.
        rel_path: project-relative path from the picker, "" for the
            empty-placeholder selection.
    """
    absolute = resolve_picker_path(project, rel_path)
    if absolute is None:
        if project is not None and rel_path:
            logger.warning(
                "Picker selection %r could not be resolved for "
                "project %r (target=%s, work_dir missing or "
                "traversal guard rejected)",
                rel_path,
                project.get("id"),
                target_id,
            )
            ui.notification_show(
                "Could not resolve selected file. Try re-selecting "
                "after the project finishes loading.",
                type="warning",
                duration=5,
            )
        return
    ui.update_text(target_id, value=absolute)


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

    # Per-file pick handlers are registered when the browse modal opens. A
    # reactive.effect registered inside another effect is NOT destroyed when
    # the outer effect re-runs, so reopening the modal would stack a fresh
    # handler on the same pick_<id> button each time, firing _pick (and
    # on_selected / modal_remove) N times. Register each button id at most once.
    _registered_pick_btns: set[str] = set()

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
        if btn_id in _registered_pick_btns:
            return  # handler already live for this button — don't stack another
        _registered_pick_btns.add(btn_id)

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
