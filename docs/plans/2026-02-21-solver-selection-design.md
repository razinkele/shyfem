# Solver Selection UI Design

**Date**: 2026-02-21
**Status**: Approved

## Context

SHYFEM has two matrix solvers: SPARSKIT (direct LU, default) and PETSc (iterative GMRES + Block Jacobi). The solver is a compile-time choice — each produces a separate binary. SPARSKIT is ~2x faster on small meshes (<50k nodes) due to lower overhead; PETSc scales better for large meshes (100k+ nodes) where direct methods become memory-bound.

The UI should let users choose which solver to use and recommend one based on mesh size.

## Architecture & Binary Management

Two binaries coexist in `bin/`:
- `bin/shyfem` — SPARSKIT (built by `make fem`)
- `bin/shyfem-petsc` — PETSc (built by `make petsc`)

`ShyfemWrapper` gains `check_solver_available(solver)` to detect if the PETSc binary exists. `run_shyfem()` gets a `solver` parameter — when `solver="petsc"`, it resolves to `shyfem-petsc`.

Config additions: `solver_node_threshold: int = 50000` (recommendation threshold).

No Fortran code changes. Same source built twice with different `SOLVER=` flags and different output binary names.

## Run Page UI & Mesh Recommendation

A "Solver Options" panel appears below MPI options (shyfem tool only):

- **Solver dropdown**: "Direct Solver (SPARSKIT)" and "Iterative Solver (PETSc)". PETSc option disabled with "(not installed)" suffix when binary not found.
- **Mesh hint**: Parses the `.str` file to find the grid file, uses `GrdParser.get_statistics()` for node count:
  - < 50k nodes: "Recommended: Direct Solver — fastest for small/medium meshes"
  - >= 50k nodes: "Recommended: Iterative Solver (PETSc) — scales better for large meshes"
- Hint is informational — users can override.

**Job flow**: Solver stored in `JobSpec.metadata["solver"]`. In `_execute_job`, `solver == "petsc"` routes to `tool_name="shyfem-petsc"`.

## Build System

New top-level Makefile target `make petsc` builds with `SOLVER=PETSC` and installs as `bin/shyfem-petsc`. Existing `make fem` unchanged.

## Testing

- Unit: `get_executable("shyfem-petsc")` resolves or raises `FileNotFoundError`
- Unit: dropdown shows PETSc disabled when binary missing, enabled when present
- Unit: mesh hint returns correct recommendation for node counts above/below threshold
- Unit: `metadata["solver"]` routes to `shyfem-petsc` in `_execute_job`
- Integration: both binaries complete mar_menor (1152 timesteps)

## Not Building

- No auto-rebuild — user builds PETSc binary manually
- No STR file modifications — solver is UI/execution concern only
- No config for PETSc paths — looks for `bin/shyfem-petsc` next to `bin/shyfem`
- No GPU/AmgX — PETSc CPU only

## Summary

| Component | Change |
|-----------|--------|
| Top-level Makefile | New `petsc` target |
| `shyfem_wrapper.py` | `solver` param in `run_shyfem()`, `check_solver_available()` |
| `config.py` | `solver_node_threshold` |
| `run.py` | Solver dropdown + mesh hint panel |
| `job_local.py` | Route `metadata["solver"]` to correct binary |
