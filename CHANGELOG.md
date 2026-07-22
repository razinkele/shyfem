# Changelog

All notable changes to the SHYFEM project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Fixed

- **Temperature surface-boundary sentinel restored — 3D heat-forced runs no longer explode** — a magic-number cleanup (2026-02-11) replaced the `ssurface = -999.` sentinel for temperature with `mkonst`'s `flag` (−9,988,765), which besides the intended "use ambient value" branch (`ssurf ≤ −990`) also trips `make_scal_flux`'s `≤ −5555` "difference" branch, injecting ~10⁷-degree water through the surface flux: the venice_lagoon example blew up to 234 °C within 4 simulated minutes, on every fork version since February. Found by bisect after test-running the example; unnoticed for five months because no mar_menor test exercises temperature transport. A committed 6-hour `venlag_smoke.str` now guards the 3D baroclinic + GOTM + wet/dry + heat path (`concentration.f90`, `testcases/examples/venice_lagoon/venlag_smoke.str`)

### Changed

- **Topbar About/Changelog split per package** — The About and Changelog topbar buttons are now dropdowns with separate SHYFEM (core) and SHYFEM UI entries: About shows the respective README (repo root vs `shyfem-ui/`) with the matching version in the title (core from `VERSION`, UI from package metadata), and Changelog shows only that package's sections of the shared CHANGELOG (`pages/about.py`, `changelog.py` — `filter_changelog`, `core_version`, allowlisted `read_repo_markdown`)

---

## [8.4.0] — 2026-07-22

Feature release for the Fortran core: the shyfemcm upstream port wave — tracer beaching/burial, optimal-interpolation data assimilation, heat fluxes in meteo output, and restart interoperability — plus the restart-v18 collision defusal and two rounds of upstream cherry-picks. Tagged `v8.4.0`.

### Fixed

- **ismar-branch cherry-picks** — from `georgu/shyfemcm-ismar` develop (newer than the pnrr branch): FPE-trap suspension around `MPI_Init` — OpenMPI 5 throws a floating-point exception inside `MPI_Init` when `-ffpe-trap` is armed; halting modes are saved, disabled for the init sequence, and restored (upstream re-enables unconditionally, which would arm trapping in builds that never requested it; our `MPI_INIT_THREAD` call is kept, upstream's switch to plain `MPI_INIT` is not taken). Also: `boxes_matrix.txt` output actually works again (`iu` was never assigned before the `open` — now `newunit=`), a spurious maybe-uninitialized warning silenced in the sediment D50 loop, and a defensive init in the ice model (`mpi_node_internal.f90`, `boxes.f90`, `sedim_admin.f90`, `icemodel.f90`)
- **Restart ssedi extension renumbered to version 19** — the fork's bed-mass restart block (N25) had claimed version 18, which upstream shyfemcm independently uses for old-time-level hydro state; the identical header version with different record layouts meant files from either side would be silently mis-parsed as garbage by the other. The ssedi block is now version 19, and version-18 files are refused with an explanatory error instead of being mis-read; fork-written v18 files (possible only 2026-07-21/22) must be regenerated (`mod_restart.f90`, `restart.f90`)
- **Upstream cherry-picks (shyfemcm pnrr)** — six small fixes ported: `lnkmpi.f90` guards `kantv` entries of 0 before indexing `id_node` (out-of-bounds read for MPI ghost boundary nodes); `baroclinic.f90` calls `ts_nudge` after the observation/relaxation arrays are zeroed (the zeroing silently wiped parameter-given nudging timescales) and confines the parameter reads to first call; shy files accept and write format version 15 (upstream's compatibility bump — no record change, but pre-bump binaries reject v15 files until rebuilt) with clearer version/type error messages; nc2fem reads long WRF-style variable names (15→80 chars), validates NetCDF-3/4 format up front with a conversion hint, tolerates `standard_name == 'unknown'` by falling through to `long_name`, and knows wave variable names (wheight/wper/wdir); parametric wave directions are averaged element→node as vectors via new `aver_wave_dir` (arithmetic averaging was wrong across the 0/360 wrap; `polar2xy`/`xy2polar`/`p2c` added to `geometrical.f90`); `gmsh2grd.pl` reads the `$MeshFormat` version and computes node-column offsets instead of hardcoding them

### Added

- **Restart interoperability with upstream shyfemcm** — restart files written by current upstream (version 18, old-time-level hydro state: `iwetv`, `zov`, `zeov`) are now read by the model (serial and MPI; values consumed for stream sync, `iwetv` restored, `zov`/`zeov` re-derived after restart); the fork keeps writing version 19. Two restart tools ported: `rstinf` (rewritten: record listing, flag display, NaN check option, and a two-file diff mode covering v18/v19 layouts) and the new `rst2shy` (converts restart files to shy format for plotting: water levels, transports, T/S, tracers). The tool ports fix upstream defects (uninitialized tracer count crashing on conz-bearing files, all tracers written as variable 301, gotm diff gate desyncing on k-eps files) and adapt to the fork's validating `rst_get_vertical` (`restart.f90`, `rstinf.f90`, `rst2shy.f90`, `mod_restart.f90`)
- **Heat fluxes in meteo output** — Ported from shyfemcm (pnrr): setting the new 10000 digit of `imetout` writes the computed sensible, latent, and long-wave heat fluxes plus evaporation (ivars 47/48/49/27) into the meteo output file; needs an active heat module (`iheat` > 0) and heat forcing. The port fixes upstream reading `imetout` where it meant `iheat` (neutering the heat-module guard) and keeps meteo output alive for barotropic runs — upstream moved the output call inside `barocl`, which returns early for `ibarcl` ≤ 0; we call it from the main time loop after the heat-flux computation instead (`mod_meteo.f90`, `heat_admin2.f90`, `meteo_forcing.f90`, `meteo_admin.f90`, `shyfem_subs.f90`, `def_para.f90`)
- **Data-assimilation framework (optimal interpolation)** — Ported from the shyfemcm community model (pnrr branch): station observations are assimilated into running simulations via numbered `$assimil` STR sections (one per variable; T = ivar 12, S = ivar 11 wired, generic 2D/3D entry points prepared). Per step, observations are time-interpolated, the background is evaluated at the stations, an optimal-interpolation analysis is computed (Gaussian covariance with per-station correlation lengths and obs/background error weighting, per-station `iuse` on/off), and applied by nudging (`mode=0`, timescale `tau`) or direct insertion (`mode=1`). Currently 2D/surface-only, as upstream. The port fixes six upstream defects in transit: the observation-window check was hidden inside a debug flag (interpolation ran outside the obs window), two or more `$assimil` sections aborted at STR read (`count_sections` whitelist), an empty coords file silently disabled all instances, `get_bobs` wrote out of bounds for fewer than 3 observations, the vertical-correlation Gaussian multiplied instead of divided by the correlation length, and `assimil_2dvars` passed a `(2,nvar)` array to a `(3,nvar)` dummy; plus convention hardening (collective-safe aborts, `newunit=`, checked allocations, opt-in debug file, O(nobs³) self-check off by default). New infra: `para_set_array_value`, `iff_file_has_data`, `has_sigma_levels` (`assimil.f90`, `assimil_admin.f90`, `suboi.f90`, `baroclinic.f90`, `iostr.f90`, `para.f90`, `intp_fem_file.f90`, `sigma.f90`, test case `mm_hyd_assim.str`)
- **WW3 switch-file build glue** — optional `WW3SWITCH` in `Rules.make` names the WW3 switch file whose switches are compiled into the binary as `__WW3_SWITCHES__` (with a fallback list matching the compiled flags), and the WW3 coupling setup guide `docs/modules_wind_wave.tex` is imported from upstream — fixing the manual's previously broken `\input` of that file (`src/shyfem/Makefile`, `Rules.make`)

- **Tracer beaching/burial algorithm** — Ported from the shyfemcm community model (pnrr branch): nodes on material (closed) boundaries lose a fraction of surface-layer tracer per time step into a per-node beach store, and nodes lose a fraction of bottom-layer tracer into a burial store, with rates looked up per element area code from presets; both stores are written as 2D scalar files (`beach`, `burry`) at the conz output frequency and reset per window. Activated by the new STR parameter `ibeach` (1 = Curonian lagoon preset, 2 = Danube delta preset; needs `iconz` ≥ 2) instead of upstream's hardcoded basin sniffing; the port also fixes upstream's out-of-bounds preset writes on grids without the expected area codes and a latent MPI deadlock in the debug path, and verifies serial ≡ MPI bit-identical output (`beaching.f90`, `def_para.f90`, `shyfem_subs.f90`, `geom.f90`, test case `mm_hyd_beach.str`, PR #51)


---

## [8.3.0] — 2026-07-22

Correctness and safety release for the Fortran core: the 2026-07-18 deep-review remediation batches (PRs #40–#47) plus the June fix wave. No new features; every change hardens existing behavior. Tagged `v8.3.0`.

### Fixed

- **OpenMP save-array caching races reverted** — `allocatable, save` work arrays in routines reachable from OMP tasks are thread-shared and raced under parallel sections; reverted to per-call allocation in `conz3d_omp`, `scal_adv`/`scal_adv_nudge`/`scal_adv_fact`, and `conzstab`, and guarded `limit_scalar` initialization (`concentration_omp.f90`, `concentration.f90` — N01, N09, N10, and the conzstab init race)
- **MPI collective-safe aborts** — error paths that previously called bare `stop` from one rank (hanging the other ranks in collectives) now abort collectively, preserving the original message text: conz3d_nodes, SPARSKIT, turbulence, chezy, mercury sediment, mpi_node allocation failures, wetting/drying, plus `flush(6)` inside `shympi_abort_internal` so diagnostics survive the abort (F07, F09, F11, F27, F38, N22, N23)
- **MPI ghost/setup hardening** — allocatable setup arrays, ghost-exchange `ierr` checks, unified buffer sizing, explicit-RHS ownership filter, ghost-node diagnostics, and documented non-deterministic reductions (N28, F32, F33, F34, L01, L05)
- **PETSc solver honesty** — the solve now aborts on KSP divergence instead of silently accepting garbage zeta (N04), and the zeta matrix is no longer double-assembled on the PETSc path (#33)
- **Numerics guards** — Munk-Anderson clamps Ri ≥ 0 to avoid NaN/SIGFPE (#34); `angle()` guarded against division by zero and acos domain errors (#39); COARE/hersbach drag formulas floor wind/friction velocity (N03, N20, F37); `istod` rejects trailing signs and keeps exponent precision (N53, N54)
- **Model-time bookkeeping** — femtime's `it` updates every step and `itend` is set/guarded, fixing stale end-time comparisons (N05, and the Batch-1 `itend` carry-over)
- **Restart correctness** — read/write paths check `iostat`, validate vertical structure, write single records atomically, wire simple-sediment bed mass into restart, and read `ile`/`ilk` exactly once for io_off v3 (N24–N27, N25, N54)
- **Transport correctness** — intent chain repaired, decay no longer double-counted, `ts_shell` counter fixed, clamping is mass-accounted, allocation failures abort (N37–N39, F28, F29); WW3 coupling recognized by `has_waves` (N21)
- **Tools hardening** — nc2fem preserves header `lmax`, errors on oversized records, fixes direction handling, and accepts valid `nz1<nz` input (N36, F43); shyelab/femelab/extelab striding, vorticity records, stats-buffer conventions (N07, N08, N34, N35); shybas bmode-3 and interpolation scratch sizing (N32, N33); mesh/grid tools get bounded filename/coordinate formatting, realloc NULL-checks, and InterpolateDepth guards (F12, F39, F40, N06, N30, N31); femfile EOF handling, grd `nvert` guard, dts integer overflow (L20–L25, L29)

### Changed

- **Documented build flags actually work** — `MPI=`/`OMP=` on the make command line now map onto `PARALLEL_MPI`/`PARALLEL_OMP` as the docs claim (N19, `Rules.make`)
- **CI skips docs-only builds** — The Fortran and UI build workflows ignore markdown-only changes via a trailing `!**/*.md` path-filter negation, so a docs/changelog PR runs only the review check (`.github/workflows/fortran-ci.yml`, `.github/workflows/ui-ci.yml`)

### Documentation

- **OpenMPI build/run requirement** — Documented that a bare `make fem` silently links Intel MPI (first in `PATH` on the dev box) and crashes inside `MPI_Init`; build and run with OpenMPI (`PATH=/usr/bin:$PATH`) and verify with `ldd … | grep mpi` → `libmpi.so.40` (`CLAUDE.md`)

---

## [shyfem-ui 0.4.0] — 2026-07-22

Session-freeze fix and a leaner docs/feedback entry point. Tagged `shyfem-ui-v0.4.0`.

### Fixed

- **Reactive flush loop froze whole sessions** — `run.py`'s `_auto_refresh` poll read `active_jobs_data` (and `selected_job` via the log refresher) and re-wrote them every cycle with freshly-built lists; `reactive.Value.set()` compares by identity, so the effect self-invalidated into an infinite flush loop (~7k iterations/s, worker pinned at 100 % CPU) that starved the first flush — every output in the session stayed blank (most visibly About/Changelog). Writes are now skipped when content is unchanged (dataclass equality, previous values read under `reactive.isolate()`), and the `_refresh_tick` bump isolates its own read (`pages/run.py`, PR #49)
- **"All jobs" toggle read no longer aborts the poll** — the switch renders only once the Run page is shown, so its `SilentException` is treated as the fail-closed default (own jobs) instead of failing the whole refresh cycle (`pages/run.py`)
- **MPI toggle actually reveals the process-count input** — the checkbox and the `input.mpi_enabled()` read lived in the same `@render.ui`, so toggling re-created the checkbox and reset its state; the count input now lives in its own `mpi_np_control` output (`pages/run.py`)

### Changed

- **About / Changelog / Feedback moved to the top bar** — the About sidebar page (tabbed README/Changelog/Feedback) is replaced by three icon buttons left of the theme toggle that open modals; modal content is plain `ui.markdown` built at show-time (`pages/about.py`, `app.py`)

### Testing

- **Browser tests exercise the real `run_server`** — the `_stub_run_server` workaround in `tests/_test_app.py` (which existed only to mask the flush-loop deadlock, tracked as followup Section M.1) is removed, making the whole E2E suite the regression gate; new `test_playwright_topbar_about.py` covers the three topbar modals including an end-to-end feedback submission

Also since 0.3.0 (unreleased in-between work): the 2026-07-18 deep-review remediation batches (PRs #40–#47) landed UI security and robustness fixes — user-owned jobs that survive WebSocket disconnects with orphan reconciliation and per-user listings, path-confinement and username-slug hardening, CSRF-safe logout, proxy-validated `X-Forwarded-For`, feedback content/email validation with retention pruning, restart-continuation (`itrst=-1`) correctness, and job outputs persisted across restarts.

---

## [shyfem-ui 0.3.0] — 2026-06-14

In-app documentation and a feedback channel. Tagged `shyfem-ui-v0.3.0`.

### Added

- **In-app documentation** — New "About" page (nav item) with tabs rendering `README.md` and `CHANGELOG.md` via `ui.markdown`, plus a dismissable "what's new" modal that shows the latest release notes once per browser (`pages/about.py`, `changelog.py`, `app.py`)
- **Feedback system** — Submit bug reports / suggestions (type, title, description, optional severity and contact email, auto-captured page + app version) from the About page. Stored in a new `feedbacks` table; an anonymous, rate-limited `POST /api/feedback` plus an admin-only `GET /api/feedback` for triage (`models/feedback.py`, `services/feedback_service.py`, `middleware/session_auth.py`, Alembic migration `ccde037a5855`)

### Fixed

- **Connect-time input send no longer breaks the session** — Deferred the what's-new version report so `Shiny.setInputValue` is not called synchronously in `shiny:connected`, which tripped a Shiny `ProtocolError` that tore down the WebSocket session before any output rendered (`app.py`)

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
