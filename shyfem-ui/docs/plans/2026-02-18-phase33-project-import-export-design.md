# Phase 33: Project Import/Export — Design

**Date:** 2026-02-18
**Status:** Design approved

## Scope

Export projects as ZIP archives, import from ZIP, and clone projects.
New service module `services/project_export.py` with three functions.

## Export (33.1)

`export_project(project_id, db) -> BytesIO`

- Zips the entire `work_dir` tree + a `manifest.json` at the root
- Excludes job log files (`*.stdout`, `*.stderr`) — transient and bulky
- Dashboard gets a download button per project

## Import (33.2)

`import_project(zip_bytes, config, db) -> Project`

- Validates manifest.json exists and is well-formed
- Checks referenced files exist in archive
- Rejects path traversal (`..` in filenames)
- Extracts to new directory under `config.work_dir`
- Creates Project, Grid, Simulation DB records from manifest
- Unique project name (appends timestamp on collision)

## Clone (33.3)

`clone_project(project_id, new_name, config, db) -> Project`

- `shutil.copytree()` to new directory
- Creates new DB records (Project, Grid, Simulation)
- Default name: `"Original Name (Copy)"`

## Manifest Format

```json
{
  "version": "1.0",
  "exported_at": "2026-02-18T12:00:00Z",
  "project": {"name": "...", "description": "..."},
  "grids": [
    {"name": "...", "grd_file": "GRID/x.grd", "bas_file": "GRID/x.bas",
     "num_nodes": 1234, "num_elements": 2345, "num_layers": 10,
     "min_depth": 0.5, "max_depth": 50.0}
  ],
  "simulations": [
    {"name": "...", "str_file": "x.str", "grid_name": "...",
     "start_time": "2020-01-01", "end_time": "2020-01-02",
     "time_step": 300.0, "mpi_enabled": false, "mpi_np": 1}
  ]
}
```

## Files

- Create: `shyfem_ui/services/project_export.py`
- Create: `tests/test_project_export.py`
- Modify: `shyfem_ui/pages/home.py` (export/import/clone buttons + handlers)

## Testing

- Export round-trip: export then import produces equivalent project
- Manifest validation: missing manifest, bad JSON, missing files
- Path traversal rejection
- Name collision handling
- Clone produces independent copy
