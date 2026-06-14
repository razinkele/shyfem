# Changelog

All notable changes to the SHYFEM project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Changed

- **CI skips docs-only builds** — The Fortran and UI build workflows ignore markdown-only changes via a trailing `!**/*.md` path-filter negation, so a docs/changelog PR runs only the review check (`.github/workflows/fortran-ci.yml`, `.github/workflows/ui-ci.yml`)

### Documentation

- **OpenMPI build/run requirement** — Documented that a bare `make fem` silently links Intel MPI (first in `PATH` on the dev box) and crashes inside `MPI_Init`; build and run with OpenMPI (`PATH=/usr/bin:$PATH`) and verify with `ldd … | grep mpi` → `libmpi.so.40` (`CLAUDE.md`)

---

## [shyfem-ui 0.2.0] — 2026-06-14

First independently-versioned release of the Python UI package, decoupled from the SHYFEM Fortran core (which stays at 8.2.0). Tagged `shyfem-ui-v0.2.0`.

### Added

- **IBM trips-layer trails respond to the time filter** — Particle trails now animate against the full run's clock, so a time-filtered window plays in its true sub-arc of the loop instead of re-stretching to fill it; closes the last deferred item of the 2026-06-08 unwired-UI audit. Verified against real lagrangian data (`pages/ibm.py` — `_tracks_to_trips` gains a global `extent` anchor via `_tracks_time_extent`/`global_time_extent`)

### Changed

- **shyfem-ui versioned independently of SHYFEM** — Restored `shyfem-ui/pyproject.toml` to its own version line and stopped `bin/bump-version.sh` from rewriting it, so a SHYFEM core release (e.g. 8.2.0) no longer bumps the Python UI package (`shyfem-ui/pyproject.toml`, `bin/bump-version.sh`)
- **shyfem-ui bumped to 0.2.0** — First independent minor of the Python UI package (`shyfem-ui/pyproject.toml`)
- **shyfem-ui `__version__` from package metadata** — `__version__` now derives from `importlib.metadata.version("shyfem-ui")`, making `pyproject.toml` the single source of truth; the `/health` test asserts against it rather than a literal (`shyfem_ui/__init__.py`, `tests/test_health.py`)

---

## [8.2.0] — 2026-06-13

### Added

- **deck.gl widget integration** — Layer legend widget and screenshot widget for grid map and IBM pages (`grid_map.py`, `ibm.py`)
- **Trips animation** — IBM particle tracking uses deck.gl TripsLayer with animated playback, replacing static PathLayer (`ibm.py`, `trips_animation_server.py`)
- **Physics configuration UI** — 13-panel form for STR parameter editing: timing, hydro, wind, turbulence, tracers, ecology, sediment, Lagrangian, boundary conditions, non-hydrostatic, physical constants, advanced hydro, water renewal (`physics.py`)
- **Cross-parameter validation** — Level-based validator with Fortran range checks for iturb, ibarcl, iwave, itdrag; GOTM/T+S dependency checks; timing validation rules (`validation.py`)
- **STR validation on save/submit** — Raw editor validates on save; job submission validates before run; ensemble validates parameter variants (`run.py`, `simulation.py`, `ensemble.py`)
- **Particle statistics panel** — Per-type metrics in IBM page with depth and displacement tooltips (`ibm.py`)
- **Boundary condition enhancements** — Expanded ibtyp choices, scalar boundary file fields, `$sedtr`/`$lagrg`/`$connec`/`$bfmsc`/`$nduge` parser sections (`parser.py`)
- **Workflow templates** — 7 new physics templates (offline tracer, eulerian tracer, etc.) and simulation template preview validation (`templates.py`, `simulation.py`)
- **Restart-from-job** — Dropdown to select a completed job for continuation runs (`run.py`)
- **Flux analysis** — Post-processing with exgrd/shyadj tool integration (`run.py`)
- **MPI Lagrangian tracking** — Particle transport works with domain decomposition (`lagrange_mpi.f90`)
- **Automatic versioning** — `make bump-patch/minor/major` targets with `bin/bump-version.sh` script to update all version files and create git tags
- **README.md** — Modern project README with badges, build matrix, feature list, and quick start guide
- **WS trusted-identity authentication** — Per-session WS-auth token (`WSAuthToken` model + migration) minted by `/api/whoami`, pushed to the client via `setInputValue`, and resolved server-side so WebSocket-scope mutations authorize against a server-validated identity (`auth_service.py`, `app.py`, `services/ws_identity.py`)
- **File picker across pages** — Project-aware file browser/picker wired for grid, bas, str, shy, and lgr inputs on Grid Prep, Partitioning, Physics, Simulation, Run, IBM, and Post-Process (`components/file_picker.py`, `services/file_service.py`)
- **IBM time-range filter** — Restrict the particle view to a time window via `filter_by_time` (`ibm.py`, `services/lgr_service.py`)
- **Project Details modal** — Surface grid/simulation metadata for a project from the dashboard (`home.py`)
- **Job authorization & cancel** — Jobs carry `project_id`/owner; cancel is authorized for owner/admin/editor, including per-job ensemble cancel (`run.py`, `ensemble.py`)
- **Periodic maintenance** — Scheduled pruning of old jobs and expired sessions (`app.py`)
- **Mesh-builder input validation** — Warnings for degenerate bathymetry, bathymetry/mesh extent mismatch, and inert or contradictory triangulation constraints (`mesh_builder.py`)
- **Selectable weutro calibration set** — Calibration parameters are configurable (was hardcoded Venice); the active set is logged and unknown sets guarded (`weutro.f90`)
- **weutro phytoplankton settling** — Settling flux wired (TR-05); `NUTLIM` defaults to the Liebig minimum (`weutro.f90`)

### Security

- **CSRF protection on login form** — Double-submit cookie pattern prevents cross-site request forgery (`session_auth.py`)
- **Secure cookie flag** — Configurable `SHYFEM_UI_USE_SECURE_COOKIES` for HTTPS deployments (`config.py`, `session_auth.py`)
- **Password minimum raised to 8 characters** — Was 4, now enforced in both create and reset flows (`admin.py`)
- **Default credentials removed from login page** — "Try it: user/user" hint no longer displayed
- **Tool name allowlist in ShyfemWrapper** — Only known SHYFEM tools can be invoked through the UI (`shyfem_wrapper.py`)
- **WebSocket auth bypass restricted to localhost** — Shiny Server proxy bypass only accepted from `127.0.0.1` / `::1` (`session_auth.py`)
- **Path traversal prevention** — Username `..` rejected; `User.home_dir()` validates containment; STR file paths checked with `config.validate_path()` (`admin.py`, `user.py`, `file_service.py`)
- **WebSocket auth-bypasses closed** — Write-path pages (home, files, run, physics, simulation, ensemble, grid_prep, partitioning, post-process, mesh_builder) now authorize against the **server-validated** WS identity instead of the unforwarded HTTP-scope user, closing fail-open guards (`app.py`, `pages/*.py`)
- **Fail-closed on unresolved identity** — Project create/import and other mutations deny when the WS identity is unresolved in server mode (`services/access_control.py`, `home.py`)
- **Tutorial read-only enforced centrally** — Tutorial accounts are blocked from every mutation gate via the server-validated role (`services/access_control.py`)
- **Job ownership from WS identity** — Job owner is stamped from the WS identity, not the HTTP-scope user (OWN-1); job-access IDOR closed; share-role escalation prevented (`run.py`, `sharing_service.py`)
- **More path-traversal guards** — `mesh_builder` save and `physics.save_file` validate the target against the project root (`mesh_builder.py`, `physics.py`)
- **Rate-limiter & cookie hardening** — `trusted_proxies` defaults to loopback in server mode (no per-client bucket collapse); secure-cookie flag honored (`middleware/rate_limit.py`, `config.py`)
- **Argon2 rehash on login** — Passwords are re-hashed when argon2 parameters change (`auth_service.py`)

### Fixed

- **Race condition in baroclinic T/S computation** — Removed unsafe concurrent OMP tasks sharing `save` arrays in `scal_adv_nudge` (`baroclinic.f90`)
- **Division-by-zero in hydrodynamic solver** — Added `hhi > 0` guard on implicit advective terms and `va > 0` guard on free-surface divergence (`hydrodynamic.f90`)
- **Division-by-zero in serial concentration solver** — Added zero-pivot guards matching OMP version; uses `cycle`/`exit` to skip degenerate nodes (`concentration.f90`)
- **Stack overflow in Munk-Anderson turbulence** — Converted `shearf2`/`buoyf2` from automatic (stack) to `allocatable, save` (heap); removed dead `richard` array (`turbulence.f90`)
- **Stack overflow in OMP concentration solver** — Converted ~50KB/task automatic arrays to allocatable locals in `conz3d_element` (`concentration_omp.f90`)
- **Undefined behavior: `stop` inside OMP parallel regions** — `hydro_transports` uses `REDUCTION(max:ierr_rms)` error flag; `setdepth` wraps diagnostics in `OMP CRITICAL` and defers `stop` (`hydrodynamic.f90`, `elems_dealing.f90`)
- **Swallowed errors in job queue** — Job persistence failure upgraded from `debug` to `error`; DB load upgraded to `warning`; bare `pass` in progress callbacks and restart file handling replaced with `warning` logging (`job_local.py`, `job_queue.py`, `run.py`)
- **13 pre-existing test failures resolved** — Fixed broken tests across the UI test suite
- **shiny_deckgl API imports** — Updated for v1.9.1 API changes
- **Fortran CI now passes** — It had never been green: moved `mod_physical_constants` to the layer compiled before `src/utils` (clean-build module ordering), built the real MPI-NODE binary in the "serial" job, and stopped a `tee` pipe from masking build failures; mar_menor exit-code expectation corrected to 0 (`src/utils/generic/`, `.github/workflows/fortran-ci.yml`, `util.sh`)
- **IBM particle trails actually animate** — Drive the trips-layer `currentTime` and supply `_tripsAnimation`; normalize epoch timestamps to the animation scale (`ibm.py`)
- **shiny 1.6 compatibility** — E2E tests (re)establish active-project state that 1.6's reliable `priority:'event'` reset clears; lifted the temporary `shiny<1.6` pin (`environment.yml`, `tests/test_playwright_workflows.py`)
- **Server-mode E2E reliability** — Auth/sharing E2E fixed: writable `user_data_root` in fixtures, anchor-only project selector, `dispatch_event` for the card-overlaid share button; 30s timeout + reruns for slow CI (`tests/conftest.py`, `tests/test_playwright_auth.py`)
- **weutro 3D correctness** — Per-layer segment flags + vertical light; removed racy OMP parallelization of bio advection; `stat=` guards on all allocations; bare `stop` → `shympi_abort_internal`; fixed-form `OPEN` continuations so EUTRO compiles (`weutro.f90`, `bio3d.f90`)
- **mercury restart** — Stop restart-stream desync; real bit-for-bit restart (`mercury.f90`)
- **UI data integrity & reliability** — SQLite foreign keys enforced; `mesh_builder` NaN-raster / OOM-cap / temp-dir-leak fixes; SMTP send can't block the event loop; `cleanup_old_jobs` deletes rows; `delete_user` orphans removed; `/health` returns 503 when degraded; reactive handlers dedup-guarded (`pages/*.py`, `services/*.py`)
- **Unwired controls connected** — Preview STR + Equal Aspect wired; `mpi_default_np`/`mpirun_path` honored; `Job.celery_task_id` populated; dead code removed (unwired-UI audit P1–P6) (`pages/*.py`)
- **lgrelab date parsing** — Parse lgrelab's actual `YYYY-MM-DD::HH:MM:SS` timestamp so real `.lgr` files load (`services/lgr_service.py`)

### Changed

- **Build: `.IGNORE: clean` removed** — Individual `rm -` prefix already handles errors; `.IGNORE` masked real failures (`Makefile`)
- **Build: `MPI_TARGET` uses `$(MPI_FILE)` variable** — Second definition at line 133 was hardcoded to `MPI_NODE`, now uses the variable (`src/utils/shympi/Makefile`)
- **Build: `SHYFEMDIR` fallback uses `$(CURDIR)`** — Was `$(HOME)/shyfem`, which fails if the repo is in a different location (`Makefile`)
- **Build: dropped `-std=f95`** — Codebase uses Fortran 2003/2008 features (`newunit=`, `allocatable save`); `-std=f95` was silently overridden anyway (`Rules.make`)
- **Build: removed redundant `FGNU_OMP` redefinition** — Duplicate of lines 740-742 removed (`Rules.make`)
- **Build: Intel `FINTEL_NOOPT` unconditional clear removed** — Preserves `-g -traceback` default (`Rules.make`)
- **Build: Intel HIGH optimization `-O1` → `-O3`** — Matches intent of HIGH profile (`Rules.make`)
- **Build: `lagrange_mpi.o` module dependencies added** — Missing `basin`, `connectivity`, `mod_lagrange`, `shympi` (`src/shyfem/Makefile`)
- **shiny pinned to `>=1.6,<1.7`** — A tested range; an open float silently broke CI on 1.6.3 (`environment.yml`)
- **`actions/checkout` v4 → v5** — Node 20 runtime is being removed from CI runners (`.github/workflows/`)
- **Template reads routed through `WorkflowEngine.list_templates`** — Removed the uncalled `run_shyplot` wrapper (`services/workflow_engine.py`)
- **eco coding-convention sweep** — `intent()` added across weutro/bio3d args (FC-01); GOTOs removed from the reaction kernel and reaeration (FC-03); `pi` from `mod_physical_constants` (FC-05) (`weutro.f90`, `bio3d.f90`)
- **CLAUDE.md** — Documented the `.env`-aside trick to reproduce CI-only UI test failures locally

---

## [8.1.1] — 2025-06-15

### Added

- Profile-Guided Optimization (PGO) build profiles (`SPEED_PGO_GEN`, `SPEED_PGO_USE`)
- Hybrid MPI+OpenMP builds (removed incompatibility guard)
- OpenMP parallelization for density computation (`baroclinic.f90`), depth setup (`elems_dealing.f90`), bottom friction (`chezy.f90`), diffusivity init (`diffusion_admin.f90`), Munk-Anderson turbulence (`turbulence.f90`)
- `!$OMP SIMD` hints on vertical level loops in `hydrodynamic.f90`, `turbulence.f90`
- Compiler optimization: `-O2` default, `-march=native -funroll-loops -ftree-vectorize` for SPEED profile
- Allocation caching in `hydro_vertical` (~4MB/timestep) and `conz3d_omp` (~10MB/timestep)
- Physical constants module (`mod_physical_constants.f90`): `pi`, `grav`, `vonkarman`, etc.
- `getpar`/`dgetpar` moved to `module para` with proper module interface (163 callers updated)
- PETSc solver support (`bin/shyfem-petsc`)
- SHYFEM UI web application (`shyfem-ui/`)

### Fixed

- 365+ `allocate()` calls now have `stat=` error checking
- 205 bare `stop` statements in MPI code paths replaced with `MPI_ABORT`
- All `open()` calls now have `iostat=` error handling
- 87 GOTO statements eliminated from 14 files
- Ghost exchange barriers reduced from 11 to 2
- Division-by-zero guards in `turbulence.f90`, `explicit.f90`, `wetdry.f90`
- Stack overflow in `concentration.f90` (automatic arrays → allocatable)
- Identical if/else branches in `waves_admin.f90`

### Changed

- `.PHONY` targets added to 68 Makefiles
- 246 three-line `save`/`data` patterns modernized to single-line initializers
- DOS/Lahey/g77 build remnants removed from `Rules.make`
- `newunit=` replaces 50+ hardcoded file unit numbers
