"""Project file management page -- upload, browse, download, delete."""

import asyncio
import logging
from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.components.project_select import project_rel_dir_choices, str_file_selectize
from shyfem_ui.config import Config, get_config
from shyfem_ui.services.downloads import SessionDownloads
from shyfem_ui.services.file_service import FileService

logger = logging.getLogger(__name__)

# File type badge colors
_TYPE_COLORS = {
    "grid": "bg-primary",
    "basin": "bg-info",
    "str": "bg-success",
    "forcing": "bg-warning text-dark",
    "boundary": "bg-danger",
    "initial_condition": "bg-secondary",
    "restart": "bg-dark",
    "config": "bg-light text-dark",
    "output": "bg-primary",
    "other": "bg-secondary",
}


def _format_size(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def _build_file_table_data(
    project_id: int,
    file_type: str | None = None,
) -> list[dict]:
    """Build file table rows from FileService."""
    files = FileService.list_files(project_id, file_type=file_type)
    return [
        {
            "id": f["id"],
            "filename": f["filename"],
            "file_type": f["file_type"],
            "rel_path": f["rel_path"],
            "size_str": _format_size(f["size_bytes"]),
            "size_bytes": f["size_bytes"],
            "uploaded_at": f.get("uploaded_at", ""),
        }
        for f in files
    ]


def _storage_summary(project_id: int) -> dict:
    """Get storage usage summary for a project."""
    config = get_config()
    storage = FileService.get_project_storage(project_id)
    limit_bytes = config.max_project_storage_mb * 1024 * 1024
    used = storage["used_bytes"]
    pct = round(used / limit_bytes * 100, 1) if limit_bytes > 0 else 0
    return {
        "used_bytes": used,
        "used_str": _format_size(used),
        "limit_bytes": limit_bytes,
        "limit_str": _format_size(limit_bytes),
        "file_count": storage["file_count"],
        "usage_pct": min(pct, 100),
    }


def _has_tutorial_data() -> bool:
    """Check if Mar Menor tutorial data exists on the server."""
    config = get_config()
    tutorial_dir = config.shyfem_dir / "testcases" / "examples" / "mar_menor"
    return tutorial_dir.exists()


@module.ui
def files_ui() -> ui.Tag:
    """Project files page UI."""
    return ui.div(
        ui.h3("Project Files"),
        ui.p(
            "Upload, browse, and manage data files for the active project.",
            class_="text-muted",
        ),
        ui.output_ui("files_content"),
    )


@module.server
def files_server(
    input,
    output,
    session,
    config: Config,
    active_project=None,
    tutorial_context=None,
    current_user=None,
) -> None:
    """Project files page server logic."""
    refresh_trigger = reactive.value(0)
    current_filter = reactive.value(None)

    # Dedup sets — handlers are registered once per file_id and persist for
    # the session. Without this, every re-render of files_content() (and
    # every click on a delete button) would stack additional listeners,
    # causing one user action to fire N times.
    _dl_registered: set[int] = set()
    _rm_registered: set[int] = set()
    downloads = SessionDownloads(session)

    @render.ui
    def files_content():
        _ = refresh_trigger.get()
        if active_project is None:
            return ui.div(
                ui.p(
                    "No project selected. Go to Dashboard and select or create a project.",
                    class_="text-muted text-center p-5",
                ),
            )
        proj = active_project.get()
        if proj is None:
            return ui.div(
                ui.p(
                    "No project selected. Go to Dashboard and select or create a project.",
                    class_="text-muted text-center p-5",
                ),
            )

        pid = proj["id"]
        ft = current_filter.get()

        # Storage summary
        summary = _storage_summary(pid)
        storage_bar = ui.div(
            ui.div(
                ui.span(
                    f"Storage: {summary['used_str']} / {summary['limit_str']}",
                    class_="small fw-bold",
                ),
                ui.span(
                    f" ({summary['file_count']} files)",
                    class_="small text-muted",
                ),
            ),
            ui.div(
                ui.div(
                    ui.div(
                        class_="progress-bar",
                        style=f"width: {summary['usage_pct']}%",
                        role="progressbar",
                    ),
                    class_="progress",
                    style="height: 8px;",
                ),
                class_="mt-1",
            ),
            class_="mb-3",
        )

        # Type filter buttons
        type_buttons = []
        for label, type_val in [
            ("All", None),
            ("Grid", "grid"),
            ("Forcing", "forcing"),
            ("Boundary", "boundary"),
            ("STR", "str"),
            ("Config", "config"),
            ("Other", "other"),
        ]:
            active = "btn-primary" if ft == type_val else "btn-outline-secondary"
            type_buttons.append(
                ui.input_action_button(
                    f"filter_{label.lower()}",
                    label,
                    class_=f"btn-sm {active} me-1",
                ),
            )

        # File table
        rows_data = _build_file_table_data(pid, file_type=ft)
        if rows_data:
            table_rows = []
            for row in rows_data:
                badge_class = _TYPE_COLORS.get(row["file_type"], "bg-secondary")
                table_rows.append(
                    ui.tags.tr(
                        ui.tags.td(row["filename"]),
                        ui.tags.td(ui.span(row["file_type"], class_=f"badge {badge_class}")),
                        ui.tags.td(ui.code(row["rel_path"], class_="small")),
                        ui.tags.td(row["size_str"]),
                        ui.tags.td(
                            ui.input_action_button(
                                f"dl_{row['id']}",
                                ui.tags.i(class_="bi bi-download"),
                                class_="btn-sm btn-outline-primary me-1",
                            ),
                            ui.input_action_button(
                                f"rm_{row['id']}",
                                ui.tags.i(class_="bi bi-trash"),
                                class_="btn-sm btn-outline-danger",
                            ),
                        ),
                    )
                )

            file_table = ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Name"),
                        ui.tags.th("Type"),
                        ui.tags.th("Path"),
                        ui.tags.th("Size"),
                        ui.tags.th("Actions"),
                    )
                ),
                ui.tags.tbody(*table_rows),
                class_="table table-sm table-hover",
            )

            for row in rows_data:
                _register_download_handler(row["id"])
                _register_delete_handler(row["id"], row["filename"])
        else:
            file_table = ui.p("No files found.", class_="text-muted text-center p-4")

        # Upload section
        from shyfem_ui.components.file_browser import file_browser_ui

        upload_section = ui.div(
            ui.h5("Upload File"),
            ui.input_select(
                "upload_type",
                "File Type",
                choices={
                    "": "Auto-detect",
                    "grid": "Grid (.grd)",
                    "basin": "Basin (.bas)",
                    "str": "STR (.str)",
                    "forcing": "Forcing",
                    "boundary": "Boundary",
                    "initial_condition": "Initial Condition",
                    "restart": "Restart",
                    "config": "Config (.nml)",
                    "other": "Other",
                },
            ),
            str_file_selectize(
                "upload_subdir",
                "Subdirectory (optional)",
                "",
                project_rel_dir_choices(
                    proj, current_user() if current_user is not None else None, config
                ),
                placeholder="project root; pick a folder or type a new one",
            ),
            file_browser_ui("file_upload"),
            class_="card p-3 mb-3",
        )

        # Seed tutorial button
        seed_btn = None
        # Seeding refuses a project with files (F-01); the button follows that rule.
        if _has_tutorial_data() and not FileService.has_project_files(proj["id"]):
            seed_btn = ui.div(
                ui.input_action_button(
                    "seed_tutorial_btn",
                    "Seed Tutorial Files (Mar Menor)",
                    class_="btn-outline-info btn-sm w-100",
                ),
                class_="mb-3",
            )

        return ui.layout_sidebar(
            ui.sidebar(
                storage_bar,
                upload_section,
                seed_btn,
                width=350,
            ),
            ui.div(
                ui.div(*type_buttons, class_="mb-3"),
                file_table,
            ),
        )

    # File upload handler
    from shyfem_ui.components.file_browser import file_browser_server, persist_upload

    async def _handle_upload(files):
        if not files or active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return

        # Access check: require editor role to upload (fail-closed in server mode)
        from shyfem_ui.services.access_control import editor_denied_reason

        user = current_user() if current_user is not None else None
        _denied = editor_denied_reason(proj["id"], user, min_role="editor")
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return

        for f in files:
            file_type = input.upload_type() or None
            subdir = input.upload_subdir() or None
            # Read, checksum and write in a thread: an upload may be 500 MB.
            result = await asyncio.to_thread(
                persist_upload,
                temp_path=Path(f["datapath"]),
                filename=f["name"],
                project_id=proj["id"],
                file_type=file_type,
                subdir=subdir,
            )
            if result:
                ui.notification_show(f"Uploaded: {result['filename']}", type="message", duration=4)
            else:
                ui.notification_show(f"Failed to upload: {f['name']}", type="error", duration=6)

        refresh_trigger.set(refresh_trigger.get() + 1)

    file_browser_server("file_upload", on_file_selected=_handle_upload)

    # Type filter handlers
    for label, type_val in [
        ("all", None),
        ("grid", "grid"),
        ("forcing", "forcing"),
        ("boundary", "boundary"),
        ("str", "str"),
        ("config", "config"),
        ("other", "other"),
    ]:
        _register_filter_handler(label, type_val, current_filter, refresh_trigger, input)

    # Seed tutorial handler
    @reactive.effect
    @reactive.event(input.seed_tutorial_btn)
    def _seed_tutorial():
        proj = active_project.get() if active_project else None
        if proj is None:
            return
        # Access check: seeding mutates the active project — require editor.
        from shyfem_ui.services.access_control import editor_denied_reason

        _denied = editor_denied_reason(
            proj["id"],
            current_user() if current_user is not None else None,
            min_role="editor",
        )
        if _denied:
            ui.notification_show(_denied, type="error", duration=6)
            return
        try:
            FileService.seed_tutorial_files(proj["id"])
            ui.notification_show("Tutorial files seeded successfully!", type="message", duration=4)
            refresh_trigger.set(refresh_trigger.get() + 1)
        except Exception as e:
            ui.notification_show(f"Error seeding tutorial files: {e}", type="error", duration=6)

    def _register_download_handler(file_id: int):
        if file_id in _dl_registered:
            return
        _dl_registered.add(file_id)
        btn_id = f"dl_{file_id}"

        @reactive.effect
        @reactive.event(getattr(input, btn_id))
        async def _download():
            # Access check: viewer role on the file's *actual* project (not
            # active_project — defense-in-depth against crafted file_ids).
            from shyfem_ui.services.access_control import editor_denied_reason

            file_project_id = FileService.get_file_project_id(file_id)
            if file_project_id is None:
                ui.notification_show("File not found", type="error", duration=4)
                return
            user = current_user() if current_user is not None else None
            _denied = editor_denied_reason(file_project_id, user, min_role="viewer")
            if _denied:
                ui.notification_show(_denied, type="error", duration=6)
                return
            try:
                path = FileService.get_file_path(file_id)
                if not path.is_file():
                    ui.notification_show("File not found on disk", type="error", duration=6)
                    return
                # The browser fetches the file over HTTP: nothing is read here.
                await session.send_custom_message(
                    "download_file",
                    {"href": downloads.offer_file(path, path.name), "filename": path.name},
                )
            except Exception as e:
                ui.notification_show(f"Download error: {e}", type="error", duration=6)

    def _register_delete_handler(file_id: int, filename: str):
        if file_id in _rm_registered:
            return
        _rm_registered.add(file_id)
        rm_btn = f"rm_{file_id}"
        confirm_btn = f"confirm_rm_{file_id}"

        @reactive.effect
        @reactive.event(getattr(input, rm_btn))
        def _confirm_delete():
            m = ui.modal(
                ui.p(f"Delete '{filename}'? This cannot be undone."),
                title="Confirm Delete",
                easy_close=True,
                footer=ui.div(
                    ui.input_action_button(
                        confirm_btn,
                        "Delete",
                        class_="btn-danger",
                    ),
                    ui.modal_button("Cancel"),
                ),
            )
            ui.modal_show(m)

        @reactive.effect
        @reactive.event(getattr(input, confirm_btn))
        def _do_delete():
            # Access check: require editor role on the file's *actual* project
            # (not active_project — defense-in-depth against crafted file_ids,
            # and so the guard still runs when no project is active). Fail-closed
            # in server mode.
            from shyfem_ui.services.access_control import editor_denied_reason

            user = current_user() if current_user is not None else None
            file_project_id = FileService.get_file_project_id(file_id)
            if file_project_id is None:
                ui.notification_show("File not found", type="error", duration=4)
                ui.modal_remove()
                return
            _denied = editor_denied_reason(file_project_id, user, min_role="editor")
            if _denied:
                ui.notification_show(_denied, type="error", duration=6)
                ui.modal_remove()
                return
            try:
                FileService.delete_file(file_id)
                ui.notification_show(f"Deleted: {filename}", type="message", duration=4)
                refresh_trigger.set(refresh_trigger.get() + 1)
            except Exception as e:
                ui.notification_show(f"Delete error: {e}", type="error", duration=6)
            ui.modal_remove()


def _register_filter_handler(label, type_val, current_filter, refresh_trigger, input) -> None:
    btn_id = f"filter_{label}"

    @reactive.effect
    @reactive.event(getattr(input, btn_id))
    def _set_filter():
        current_filter.set(type_val)
        refresh_trigger.set(refresh_trigger.get() + 1)
