# Server-Side File Management for SHYFEM-UI

**Date:** 2026-02-20
**Status:** Approved

## Problem

The project database lives on the server, but all data files (grid, basin, STR, forcing, boundary, initial conditions) are expected on the local filesystem. Users with no server access (browser-only) cannot place files where the model expects them. Tutorial data should be available from the server without upload.

## Requirements

- Users interact only through the browser — no SSH or filesystem access
- All data files uploaded/downloaded through the UI
- Tutorial data (Mar Menor) pre-loaded on server, available without upload
- STR editor file references link to uploaded files via a picker
- Individual file download AND full project ZIP export
- Storage limits: per-file (existing max_upload_size_mb) and per-project (new max_project_storage_mb)

## Approach: File Inventory in Existing DB

Add a `ProjectFile` model to track every file in a project. Files stored in the existing `{work_dir}/` filesystem structure. The DB adds an inventory layer for file pickers, validation, and quota enforcement.

## Data Model

### New: `ProjectFile`

```python
class ProjectFile(Base):
    __tablename__ = "project_files"

    id: int                     # PK, autoincrement
    project_id: int             # FK -> projects.id
    filename: str               # Original name ("wind.fem")
    rel_path: str               # Relative to work_dir ("INPUT/wind.fem")
    file_type: str              # Category (see below)
    size_bytes: int             # File size
    uploaded_at: datetime       # When uploaded/created
    checksum: str | None        # Optional SHA256
```

File type categories: `grid`, `basin`, `str`, `forcing`, `boundary`, `initial_condition`, `restart`, `config`, `output`, `other`.

### Modified: `Project`

Add relationship: `files: list[ProjectFile]` with cascade delete-orphan.

### Unchanged

`Grid.grd_file`, `Simulation.str_file` continue storing relative paths that now resolve to `ProjectFile` records.

## File Service

New `shyfem_ui/services/file_service.py`:

```python
class FileService:
    upload_file(project_id, file_data, filename, file_type, subdir=None) -> ProjectFile
    delete_file(file_id) -> None
    list_files(project_id, file_type=None) -> list[ProjectFile]
    get_file_path(file_id) -> Path
    validate_simulation_files(simulation_id) -> list[str]
    get_project_storage(project_id) -> dict
    seed_tutorial_files(project_id) -> None
```

### upload_file
- Validates: per-file size limit, total project quota, path traversal
- Stores at `{work_dir}/{subdir}/{filename}` (subdir defaults to root)
- Computes SHA256 checksum
- Creates ProjectFile record

### delete_file
- Removes from disk and DB
- Recalculates project storage

### validate_simulation_files
- Parses STR with existing parser
- Extracts file refs from `$name` and `$bound` sections
- Checks each resolves to existing file in work_dir
- Returns list of missing file warnings

### seed_tutorial_files
- Copies from `{shyfem_dir}/testcases/examples/mar_menor/`
- Copies: GRID/ (.grd, .bas), INPUT/ (forcing), .str files
- Creates ProjectFile records with appropriate file_type
- Skips shell scripts, Makefile, output files

## Configuration

New config field:
```python
max_project_storage_mb: int = Field(default=5000, description="Max storage per project in MB")
```

## STR Editor File Picker

File path parameters in `$name` and `$bound` sections show a dropdown picker:

| STR Parameter | Picker Filter |
|---------------|---------------|
| wind, qflux, rain | forcing |
| boundn, tempn, saltn, conzn | boundary, forcing |
| tempin, saltin, zinit, conzin | initial_condition |
| restrt | restart |
| gotmpa | config |
| Basin in $title | basin |

Selecting a file sets the STR parameter to its `rel_path`.

## Upload/Download Flows

### Upload
1. User selects file in browser (Shiny input_file widget)
2. Page handler calls file_service.upload_file() with temp file
3. File stored in work_dir, DB record created
4. File appears in file list and STR editor pickers

### Download (individual)
1. User clicks download icon next to file
2. Handler streams file from ProjectFile.rel_path

### Download (ZIP)
- Existing export_project() unchanged

## Pre-Flight Validation

Before job submission on the Run page:
1. Call validate_simulation_files(simulation_id)
2. Display warnings for missing files
3. Block submission if critical files missing

## Tutorial Data

When creating a tutorial project:
1. seed_tutorial_files() copies Mar Menor files from testcases/
2. Creates ProjectFile records for each file
3. Grid + Simulation records created as before
4. Tutorial projects behave identically to user projects

## Migration

- Alembic migration adds project_files table
- Existing projects: a one-time scan of work_dir populates ProjectFile records for files already on disk
- Export/import: manifest.json extended with file inventory; import creates ProjectFile records

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `models/project.py` | Modify | Add ProjectFile model, Project.files relationship |
| `services/file_service.py` | Create | FileService class |
| `config.py` | Modify | Add max_project_storage_mb |
| `pages/home.py` | Modify | File upload UI, file list, download buttons |
| `pages/simulation.py` | Modify | File picker in STR editor |
| `pages/run.py` | Modify | Pre-flight validation before job submit |
| `services/project_export.py` | Modify | Include file inventory in manifest |
| `services/project_context.py` | Modify | Include files in project context |
| `alembic/versions/xxx_add_project_files.py` | Create | DB migration |
| `tests/test_file_service.py` | Create | FileService tests |
