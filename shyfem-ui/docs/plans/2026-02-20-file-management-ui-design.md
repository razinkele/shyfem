# File Management UI Integration Design

**Date:** 2026-02-20
**Status:** Approved
**Depends on:** Server-side file management (complete — FileService, ProjectFile model, Alembic migration)

## Problem

The SHYFEM-UI backend supports project file management (upload, delete, list, validate, seed) via `FileService`, but the UI has no integration. Browser-only users on a server deployment cannot upload data files, select them in the STR editor, or validate file references before running simulations. All file paths are currently free-text inputs.

## Requirements

- Users interact only through the browser — no SSH or filesystem access
- Upload files to projects with persistent storage and DB tracking
- Browse/download/delete project files from a dedicated page
- Select project files from dropdowns in the STR editor (replacing free-text)
- Validate file references before job submission with actionable warnings
- Storage usage visibility per project

## Approach: Bottom-Up Components

Build reusable components first, then wire into pages. Two new components (`file_picker`, enhanced `file_browser`) are used across three integration points (Files page, STR editor, Run page).

## Component 1: Enhanced File Browser

Extend `components/file_browser.py` to optionally persist uploads via `FileService`.

**Changes to `file_browser_server()`:**

| Parameter | Type | Purpose |
|-----------|------|---------|
| `project_id` | `reactive.Value[int \| None]` | When set, uploads are persisted to this project |
| `file_type` | `str \| None` | Category for FileService (grid, forcing, etc.) |
| `subdir` | `str \| None` | Subdirectory within project work_dir (e.g. "INPUT") |
| `on_file_persisted` | `Callable[[dict], None] \| None` | Fires after DB record created, receives ProjectFile dict |

**Behavior:**
- When `project_id` is None: existing behavior (temp upload + `on_file_selected`)
- When `project_id` is set: reads file bytes, calls `FileService.upload_file()`, fires `on_file_persisted`
- Existing `on_file_selected` still fires in both cases (backward compatible)

## Component 2: File Picker (New)

New `components/file_picker.py` — a reusable Shiny module for selecting project files in forms.

**UI:** A row containing:
- `ui.input_select()` — dropdown populated from `FileService.list_files(project_id, file_type=...)`
- Small "Browse" button — opens a modal with full file list

**Signatures:**

```python
@module.ui
def file_picker_ui(label: str = "Select File") -> ui.div

@module.server
def file_picker_server(
    input, output, session,
    project_id: reactive.Value[int | None],
    file_types: list[str] | None = None,
    on_selected: Callable[[str], None] | None = None,
) -> reactive.Value[str]
```

**Browse modal contents:**
- Searchable file list table (name, type badge, size, date)
- Type filter tabs (All, Grid, Forcing, Boundary, etc.)
- "Upload New" button — triggers enhanced file_browser, then auto-selects new file
- Select button — sets dropdown value and closes modal

**Return value:** `rel_path` of selected file (what goes into STR parameters).

**Reactive refresh:** Dropdown choices update when project files change.

## Page 1: Files Tab (New)

New `pages/files.py` — dedicated tab in main navigation, active when a project is selected.

### Sidebar

- Project name header
- Storage usage: progress bar showing `used / max_project_storage_mb`
- File count summary
- Upload section:
  - Enhanced `file_browser` with `project_id` bound to active project
  - File type selector dropdown (grid, forcing, boundary, initial_condition, restart, config, other)
  - Optional subdir text input (default: auto from type)
- "Seed Tutorial Files" button (shown when project is empty and tutorial data exists on server)

### Main Panel

- Filter row: type filter buttons (All, Grid, Forcing, Boundary, STR, Config, Other)
- Search input for filename filtering
- File table: filename, type (colored badge), size (human-readable), uploaded date, actions
- Actions per row: Download icon, Delete icon (with confirmation)
- Bulk select with "Delete Selected" (confirmation modal)

### Server Logic

- List: `FileService.list_files(project_id, file_type=filter)`
- Upload: enhanced `file_browser` → `FileService.upload_file()`
- Delete: `FileService.delete_file(id)` with confirmation modal
- Download: `FileService.get_file_path(id)` → base64 JS download (existing pattern from project export)
- Seed: `FileService.seed_tutorial_files(project_id)` → refresh file list
- Storage: `FileService.get_project_storage(project_id)` → progress bar

## Page 2: STR Editor Integration

Modify `_build_form_panel()` in `components/str_editor.py` to render `file_picker` for file parameters.

### Detection Logic

Check if parameter name is in known file parameter sets:

```python
# From FileService
_NAME_FILE_PARAMS = {"wind", "rain", "qflux", "ice", "zinit", "tempin", "saltin",
                     "conzin", "restrt", "tempobs", "saltobs", "gotmpa", ...}
_BOUND_FILE_PARAMS = {"boundn", "tempn", "saltn", "conzn", "vel3dn", "bio2dn", "sed2dn"}
```

### Type Mapping

| STR Parameter | file_types filter |
|---|---|
| wind, qflux, rain, ice | `["forcing"]` |
| boundn, tempn, saltn, conzn | `["boundary", "forcing"]` |
| tempin, saltin, zinit, conzin | `["initial_condition", "forcing"]` |
| restrt | `["restart"]` |
| gotmpa | `["config"]` |

### Rendering Logic

In `_build_form_panel()`, for each parameter:
1. If param in file param sets AND project_id is available → render `file_picker_ui()` with mapped filter
2. Else → render `ui.input_text()` as before (fallback for no-project mode)

### Sync

When a file is selected in the picker, the STR parameter value updates to `rel_path`. The existing raw↔form bidirectional sync propagates the change to the text editor.

### Threading Through project_id

`str_editor_server()` needs a new `project_id` parameter, passed from `simulation.py` via the active project reactive value.

## Page 3: Run Page Pre-Flight Validation

Add validation before job submission on `pages/run.py`.

### Trigger

When user clicks "Run" / "Submit Job".

### Flow

1. Read simulation ID from current form state
2. Call `FileService.validate_simulation_files(simulation_id)`
3. If empty warnings → proceed with job submission as normal
4. If warnings exist → show validation modal

### Validation Modal

- Header: "Missing File References"
- List of warnings with STR section/parameter context (e.g. "Missing file for $name/wind: INPUT/wind.fem")
- Three buttons:
  - "Upload Missing Files" → navigate to Files tab
  - "Run Anyway" → proceed with submission despite warnings
  - "Cancel" → close modal, stay on Run page

### Rationale for Non-Blocking

Some file parameters may reference files generated at runtime or may be optional depending on the simulation configuration. Blocking would prevent legitimate runs.

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `components/file_browser.py` | Modify | Add project_id persistence |
| `components/file_picker.py` | Create | New dropdown + browse modal component |
| `pages/files.py` | Create | New Files tab |
| `pages/simulation.py` | Modify | Pass project_id to STR editor |
| `components/str_editor.py` | Modify | File picker for file parameters |
| `pages/run.py` | Modify | Pre-flight validation |
| `app.py` | Modify | Register Files tab in navigation |
| `tests/test_file_picker.py` | Create | File picker component tests |
| `tests/test_files_page.py` | Create | Files page logic tests |
| `tests/test_str_editor_file_picker.py` | Create | STR editor file picker tests |
| `tests/test_run_validation.py` | Create | Run page validation tests |

## Estimated Test Count

~40-50 new tests across:
- File picker component: ~10 (dropdown population, browse modal, upload+select, type filter)
- Enhanced file browser: ~5 (persistence, backward compat, error handling)
- Files page: ~12 (list, upload, delete, download, seed, storage, filters)
- STR editor integration: ~8 (detection, rendering, sync, fallback)
- Run page validation: ~8 (no warnings, with warnings, run anyway, navigate, no simulation)

## Dependency Order

```
1. Enhanced file_browser (no deps)
2. File picker component (uses file_browser for "Upload New")
3. Files page (uses file_browser + file_picker)
4. STR editor integration (uses file_picker)
5. Run page validation (uses FileService.validate_simulation_files)
```

Tasks 1-2 are components (no page changes). Tasks 3-5 are page integrations.
Tasks 3, 4, 5 are independent of each other (can be done in any order after 1-2).
