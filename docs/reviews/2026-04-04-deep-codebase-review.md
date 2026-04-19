# SHYFEM Deep Codebase Review — 2026-04-04

7 parallel review agents analyzed the entire SHYFEM codebase (~1,081 Fortran files, ~9K Python files). This report synthesizes all findings, prioritized by severity.

---

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| Concurrency (MPI/OpenMP) | 1 | 0 | 3 | 4 | 8 |
| Security (Python UI) | 2 | 4 | 7 | 4 | 17 |
| Fortran Code Quality | 0 | 3 | 3 | 4 | 10 |
| Error Handling | 0 | 2 | 5 | 4 | 11 |
| Build System | 0 | 4 | 8 | 8 | 20 |
| Test Coverage | 0 | 3 | 2 | 0 | 5 |
| Dead Code | 0 | 0 | 1 | 3 | 4 |
| **Total** | **3** | **16** | **29** | **27** | **75** |

---

## CRITICAL Findings (Fix Immediately)

### C1. Race Condition on `save` Arrays in `scal_adv_nudge` (Concurrency)
- **File**: `src/shyfem/concentration.f90:397-413`, called from `src/shyfem/baroclinic.f90:469-503`
- **Bug**: `scal_adv_nudge` has `allocatable, save` local arrays (`r3v`, `wsinkv`, `load`). In `baroclinic.f90`, two OMP TASKs call this subroutine concurrently (temperature at line 476, salinity at line 495). Since `save` variables are shared across invocations, both tasks corrupt each other's data.
- **Impact**: Silent data corruption of temperature and salinity fields. Wrong simulation results.
- **Fix**: Make the arrays non-`save` and allocate per-call, or serialize the tasks with `!$OMP TASKWAIT` between them.

### C2. Command Execution via Arbitrary Tool Name (Security)
- **File**: `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:54-67`
- **Bug**: `get_executable()` accepts any `tool_name` string, checks `bin_dir`, `shyfem_dir`, then falls back to `shutil.which()`. No allowlist validation before `create_subprocess_exec`. A crafted `JobSpec` could execute any binary on the system PATH.
- **Impact**: Remote code execution if an attacker can influence `tool_name`.
- **Fix**: Validate `tool_name` against a fixed allowlist (shyfem, shypre, shybas, shyparts, shyelab, shyplot, exgrd, shyadj).

### C3. WebSocket Authentication Bypass Behind Reverse Proxy (Security)
- **File**: `shyfem-ui/shyfem_ui/middleware/session_auth.py:588-594`
- **Bug**: When `root_path` is set (reverse proxy), WebSocket auth is completely skipped. Anyone who reaches the ASGI server directly (bypassing nginx) gets unauthenticated access.
- **Impact**: Full application access without authentication.
- **Fix**: Require WebSocket connections from localhost/trusted proxy rather than skipping auth entirely.

---

## HIGH Findings (Fix Soon)

### H1. Division by Zero in `hydrodynamic.f90` (Fortran)
- **Lines 1355-1361**: `uc = uui/hhi` — layer thickness `hhi` can be 0 for dry elements. The `if(aux > 0.)` guard does NOT check `hhi`.
- **Line 1873**: `dz = dt * wlnv(lmin-1,k) / va(lmin,k)` — node area can be 0 during extreme drying.
- **Impact**: NaN/Inf propagation in SPEED mode (no FPE traps), crash in NORMAL mode.

### H2. Stack Overflow Risk in `turbulence.f90` (Fortran)
- **Lines 137-139**: Three automatic arrays `shearf2(nlvdi,nkn)`, `buoyf2(nlvdi,nkn)`, `richard(nlvdi,nkn)` total ~60 MB on the stack for production meshes (100K nodes, 50 levels). Default 8 MB stack limit causes segfault.
- **Note**: `richard` is never read anywhere — dead code wasting memory.

### H3. No CSRF Protection on Login Form (Security)
- **File**: `session_auth.py:464-478`
- Plain HTML form with no CSRF token. `SameSite=Lax` provides partial mitigation.

### H4. Session Cookie Missing `Secure` Flag (Security)
- **File**: `session_auth.py:666`
- Cookie sent over plain HTTP, allowing session hijacking via network sniffing.

### H5. Weak Password Policy — 4-Character Minimum (Security)
- **File**: `admin.py:64-65`
- No complexity requirements, no brute-force protection beyond global 120 rpm rate limit.

### H6. Login Page Reveals Default Credentials (Security)
- **File**: `session_auth.py:459`
- "Try it: log in with user / user" shown to all visitors.

### H7. Build: `.IGNORE: clean` Suppresses All Errors (Build)
- **File**: `Makefile:109`
- Masks real problems (permission errors, stuck mounts). Individual `-` prefixes on `rm` already handle expected failures.

### H8. Build: `MPI_TARGET` Defined Twice with Different Values (Build)
- **File**: `src/utils/shympi/Makefile:50,133`
- Second assignment overwrites first, breaking serial build reset logic.

### H9. Build: No Automatic Fortran Dependency Tracking (Build)
- Manual `makedepend` sections require regeneration. Incremental/parallel builds can fail with missing `.mod` files.

### H10. Build: `shyfem` Target Not Safe for Parallel Make (Build)
- **File**: `src/shyfem/Makefile:284`
- Library dependencies rely on sequential `recursivemake` script. Direct `make -j` fails.

### H11. Job Persistence Failure Swallowed (Error Handling)
- **File**: `shyfem-ui/services/job_local.py:137`
- `except Exception: logger.debug(...)` — completed simulation disappears from UI.

### H12. No Fortran CI Pipeline (Testing)
- No automated build or test for Fortran code. Compilation-breaking changes go undetected.

### H13. Zero Automated Fortran Tests (Testing)
- No unit test framework, no regression baselines, no serial-vs-MPI comparison.

### H14. 5 UI Pages Have No Test Coverage (Testing)
- `grid_prep.py`, `partitioning.py`, `simulation.py`, `home.py`, `postprocess.py` — zero tests.

---

## MEDIUM Findings

### Concurrency
- **M1**: Missing OMP CRITICAL in `exchange_and_sum/min/max` phase 1 MPI calls (`mpi_node_internal.f90:858-886`). Latent — currently called from serial context.
- **M2**: `stop` inside OMP parallel regions (`hydrodynamic.f90:996`, `concentration_omp.f90:436`, `elems_dealing.f90:1186`). Undefined behavior on error paths.
- **M3**: Double-precision exchange uses `n_ghost_max` not `n_ghost_max_global` (`mpi_node_internal.f90`). Potential buffer mismatch between domains.

### Security
- **M4**: Admin access control relies on client-side JavaScript role (`app.py:417-463`). Server-side fallback exists but reactive path is client-controllable.
- **M5**: Path traversal via username `..` in `home_dir()` (`models/user.py:60`). Regex allows `..` since `.` is permitted.
- **M6**: No per-endpoint rate limiting on `/login` (`session_auth.py`). 120 attempts/minute via global limit.
- **M7**: Expired session cleanup is unbounded (`auth_service.py:368-387`). Loads ALL expired sessions into memory.
- **M8**: Race condition in job queue `_running_count` (`job_local.py:259-262`).
- **M9**: Jinja2 templates without autoescaping (`notification_service.py:21`). Risk if templates evolve to HTML.
- **M10**: File download encodes entire file as base64 JavaScript data URI (`files.py:352-366`). DoS for large files (up to 500 MB).

### Fortran
- **M11**: ~599 `stop` statements in `src/shyfem/` that should use `shympi_abort_internal` for clean MPI termination.
- **M12**: Interactive `READ(*,*)` in `sedim_util.f90:4356` — hangs in batch/MPI mode.
- **M13**: Infinite loop risk in `check.f90:1443,1464` — `do i=1,nelg,nelg/netot` yields step=0 when `netot > nelg`.

### Build
- **M14**: Double assignment patterns in `Rules.make` (dead code, confusing).
- **M15**: `FGNU_OMP` redefined in PGI section (`Rules.make:811-813`).
- **M16**: `FGNU_GENERAL` drops `-std=f95` when `MODDIR` is defined (always).
- **M17**: Library archives rebuilt entirely on any change (should use `$?`).
- **M18**: `recursivemake` is inherently sequential — prevents parallel builds.
- **M19**: Hardcoded fallback `SHYFEMDIR := $(HOME)/shyfem` (`Makefile:48`).
- **M20**: Intel HIGH optimization uses `-O1` instead of `-O3` (`Rules.make:1017`).
- **M21**: FPE traps in NORMAL profile conflict with SIMD directives.

### Error Handling
- **M22**: Progress callback errors silently swallowed (`job_queue.py:146` — `except: pass`).
- **M23**: Restart file selection silently dropped (`run.py:691`).
- **M24**: DB history load failure swallowed at startup (`job_local.py:78`).
- **M25**: Email send failure swallowed (`notification_service.py:134`).
- **M26**: Tutorial file copy failure swallowed (`app.py:165`).

### Dead Code
- **M27**: `bndo_admin.f90` (710 lines) — exact duplicate of `bndo.f90`, never linked.

---

## LOW Findings (27 items, abbreviated)

### Build (8): GOTM `*.o` glob, missing .PHONY in tool Makefiles, PGO gfortran-only without guard, GNU Make-only (informational), Docker hardcoded path, `-march=native` portability, `DIR=util` naming confusion, dead SAVEFILES variable.

### Security (4): SQLite `check_same_thread=False`, global mutable config singleton, no job name validation, fragile email template parsing.

### Concurrency (4): `save` array deallocation defeats caching in `conz3d_omp`, ghost elements in PARALLEL DO (unnecessary work), MPI_COMM_WORLD only (coupling limitation), verified-safe turbulence PARALLEL DO.

### Fortran (4): `open()` with `find_unit()` instead of `newunit=` (~13 sites), hardcoded debug unit numbers (2 sites), `allocate` without `stat=` (1 site in `lagrange_mpi.f90`), 2 bare `STOP` without message in `sedim_util.f90`.

### Error Handling (4): Overly broad `except (ValueError, Exception)`, ~50 `except Exception: logger.debug()` in Shiny reactives (intentional pattern), file cleanup errors swallowed, base file access during preview swallowed.

### Dead Code (3): `src/obsolete/` (~100K lines, already marked), never-called test subroutines (~350 lines in `shyfem_subs.f90`, `custom_admin.f90`), `if (.false.)` blocks (~47 lines).

---

## Test Coverage Gaps

| Module | Has Tests? | Type | Coverage | Key Gaps |
|---|---|---|---|---|
| Fortran Solver | No | — | None | No unit tests, no regression baselines |
| MPI Layer | Smoke only | mpi_test.f90 | Negligible | No exchange correctness tests |
| Serial vs MPI | No | — | None | Most important integration test missing |
| Python Services | Yes | Unit | Good | 38+ tests for auth, 54 for parser, etc. |
| Python Pages | Partial | Unit | Mixed | 5 pages with zero tests |
| Python Middleware | Yes | Unit | Excellent | 26 tests for session_auth |
| E2E (Playwright) | Yes | Browser | Good | Only runs on PRs, not on push to main |
| CI/CD | Partial | — | — | No Fortran CI, no coverage threshold, no type checking |

---

## Dead Code Summary

| Category | Lines | Risk to Remove |
|---|---|---|
| `src/obsolete/` tree | ~100,000 | Safe |
| `bndo_admin.f90` duplicate | 710 | Safe |
| Never-called subroutines | ~350 | Low risk |
| `if (.false.)` blocks | ~47 | Safe |
| Unbuilt `femutil` subdirs | ~5,000 | Low risk (may have research value) |
| **Total removable** | **~106,000** | |

---

## Recommended Priority Order

1. **Fix C1** (race condition) — active data corruption bug
2. **Fix C2** (tool name allowlist) — remote code execution risk
3. **Fix C3** (WebSocket auth bypass) — unauthenticated access
4. **Fix H1** (division by zero guards) — solver correctness
5. **Fix H2** (stack arrays to allocatable) — production crash
6. **Fix H4+H5** (cookie Secure flag, password policy) — security hardening
7. **Add Fortran CI** (H12) — prevent silent regressions
8. **Fix M2** (stop in OMP regions) — undefined behavior on error paths
9. **Fix M5** (path traversal via username) — directory escape
10. **Remove dead code** (M27, obsolete/) — reduce maintenance burden
