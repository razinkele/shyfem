# SHYFEM Deep Codebase Review

**Date:** 2026-04-15
**Scope:** Full codebase — Fortran core, MPI layer, utilities, build system, Web UI, testing, documentation
**Version:** 8.1.1

---

## Executive Summary

SHYFEM is a mature finite element hydrodynamic simulation system comprising **710,592 lines of source code** across **1,252 files** (938 Fortran 90, 29 legacy Fortran, 120 C, 165 headers), plus a **28,781-line Python web UI** with **19,114 lines of tests**. The project has 435 git commits, primarily from a single contributor.

The codebase is **actively modernizing** — recent work (2026) has centralized physical constants, added allocation error checking, improved MPI safety, and built a comprehensive web UI. However, significant legacy debt remains: **5,363 GOTO statements**, **~150 subroutines missing `implicit none`**, and **~35% of allocations lacking error checking**.

### Overall Health Scorecard

| Area | Score | Key Issue |
|------|-------|-----------|
| **Architecture** | ★★★★☆ | Clean module structure, but heavy coupling via 139 uses of mod_hydro |
| **Fortran Core** | ★★★☆☆ | Missing implicit none, intent, GOTO prevalence |
| **MPI Layer** | ★★★☆☆ | Weak error handling, bare stops, scalability limits |
| **Build System** | ★★★☆☆ | Functional but fragile parallel make, no Fortran CI |
| **Web UI** | ★★★★★ | Excellent architecture, security, type hints, testing |
| **Testing** | ★★★☆☆ | Good UI coverage, minimal Fortran CI, regression framework inactive |
| **Documentation** | ★★★★☆ | Excellent README/CHANGELOG, sparse testing docs |
| **Security** | ★★★★☆ | Strong UI security, weak default password in .env |

---

## 1. Codebase Statistics

### 1.1 Size and Composition

| Component | Files | Lines of Code | Language |
|-----------|-------|---------------|----------|
| src/shyfem/ (core) | 134 | ~140,000 | Fortran 90 |
| src/utils/ | 113 | ~60,000 | Fortran 90 |
| src/tools/ | 200+ | ~80,000 | Fortran 90/C |
| src/contrib/ | 25 | ~25,000 | Fortran 90 |
| src/external/ | 20 | ~48,000 | Fortran 90 |
| src/obsolete/ | 300+ | 320,214 | Fortran (legacy) |
| shyfem-ui/ | 8,966 | 359,240 (incl. venv) | Python/JS |
| shyfem-ui/ (app only) | ~200 | ~28,781 | Python |
| bin/ | 106 | ~15,000 | Shell/Perl |
| **Active Total** | ~800 | **~397,000** | Mixed |

### 1.2 Module Dependency Hotspots

The most depended-upon modules (by `use` count in src/shyfem/):

| Module | Use Count | Risk |
|--------|-----------|------|
| `mod_hydro` | 139 | Very high coupling — changes ripple everywhere |
| `mod_layer_thickness` | 74 | Medium coupling |
| `mod_ts` | 69 | Medium coupling |
| `mod_hydro_vel` | 69 | Medium coupling |
| `mod_lagrange` | 65 | Medium coupling |
| `mod_depth` | 62 | Medium coupling |
| `mod_diff_visc_fric` | 53 | Medium coupling |

### 1.3 Largest Files (complexity hotspots)

| File | Lines | Notes |
|------|-------|-------|
| spk_itpack.f90 | 8,656 | External SPARSKIT solver (3 copies!) |
| aquabc_II_pelagic_model.f90 | 5,635 | Ecological contrib |
| sedim_admin.f90 | 4,740 | Sediment transport |
| sedim_util.f90 | 4,730 | Sediment utilities — **worst code quality** |
| custom_admin.f90 | 4,711 | Custom channel admin |
| mpi_node.f90 | 4,477 | MPI node management |

---

## 2. Fortran Core Quality

### 2.1 Convention Violations Summary

| Issue | Count | Severity | Files Affected |
|-------|-------|----------|----------------|
| GOTO statements | 5,363 total (110 in src/shyfem/) | HIGH | 50+ active files |
| Missing `implicit none` | ~150 subroutines | CRITICAL | sedim_util, nuopc_shyfem_cap, meteo_forcing, matrix_inv |
| Missing `intent` declarations | ~100+ parameters | CRITICAL | arrays.f90, shyfem_subs.f90, hydrodynamic.f90 |
| `allocate` without `stat=` | 238/804 (30%) in core | HIGH | Multiple files |
| Three-line save/data patterns | 2 files | LOW | stability.f90, ous_admin.f90 |
| Hardcoded magic numbers | 100+ instances | HIGH | bnd_routines, bcvel, boxes, concentration |
| TODO/FIXME/HACK comments | 147 | MEDIUM | Scattered across codebase |

### 2.2 Most Problematic Files

**`sedim_util.f90`** (4,730 lines) — Worst quality in the codebase:
- 0/72 subroutines have `implicit none` (0% compliance)
- No intent declarations
- Multiple GOTO patterns

**`nuopc_shyfem_cap.f90`** — NUOPC/ESMF coupling:
- 1/35 subroutines have `implicit none` (3% compliance)

**`meteo_forcing.f90`** — Meteorological forcing:
- 17/61 subroutines have `implicit none` (28% compliance)

**`matrix_inv.f90`** — Matrix inversion:
- 7/22 subroutines have `implicit none` (32% compliance)

### 2.3 Numerical Stability Concerns

- **`hydrodynamic.f90:1312`**: `rhm = 2.0 * alev(l-1) / (hhi + hhim)` — potential division by zero in dry cells
- **`lagrange_dif.f90:608`**: `rnd = (rnd-0.5)/0.5` — safe but fragile constant division

### 2.4 OpenMP Analysis

312 OMP directives across 28 files (excluding obsolete). Key findings:
- **`concentration_omp.f90`**: Conditional `!$ use omp_lib` — preparatory but not fully active
- **`hydrodynamic.f90`**: OMP task regions for parallel hydro computations
- **No race conditions detected** in current implementation
- Code is largely thread-safe but sequential in practice

### 2.5 Memory Management

- **Good**: Allocation-deallocation balance is well maintained
- **Good**: Static caching patterns are intentional (allocate once, reuse)
- **No obvious memory leaks** detected
- **Risk**: 30% of allocations lack `stat=` error checking — silent allocation failures possible

---

## 3. MPI Layer Analysis

### 3.1 Architecture

The MPI layer in `src/utils/shympi/` (20 files) implements **node-based domain decomposition** using METIS graph partitioning. Ghost/halo exchange uses point-to-point non-blocking MPI with OpenMP critical sections.

**Domain classification:**
- `nkn_inner`: Owned nodes (interior)
- `nkn_unique`: Owned + ghost copies
- `nkn_local`: All local nodes (inner + ghost)

### 3.2 Correctness Issues

| Issue | Location | Severity |
|-------|----------|----------|
| **Weak MPI error handling** — write(6,*) instead of abort | mpi_node_internal.f90:466,474,478 | CRITICAL |
| **16 bare `stop` statements** in MPI code | mpi_dummy.f90, mpi_node.f90, shyparts_util.f90, mpi_tvd.f90 | CRITICAL |
| **MPI tag collision risk** — only 8 tags (121-144) for all exchanges | mpi_node_internal.f90:520,615,724 | HIGH |
| **Message reordering assumption** — assumes MPI_WaitAll completion order | mpi_node_internal.f90:548-577 | HIGH |
| **Balanced partition requirement** — aborts if any rank has different array size | mpi_node_internal.f90:1465-1489 | HIGH |

### 3.3 Performance Issues

| Issue | Location | Impact |
|-------|----------|--------|
| **OMP CRITICAL serializes MPI posting** — 200+ sequential MPI calls | mpi_node_internal.f90:546-570 | HIGH |
| **Global arrays replicated on every rank** — O(N) per rank memory | mpi_node.f90:207-218 | HIGH for large meshes |
| **Unnecessary MPI_Barrier** calls during init | mpi_node_internal.f90:219,225 | LOW |
| **MPI_ALLGATHER instead of MPI_GATHER** | mpi_node_internal.f90:1478,1519,1560 | MEDIUM |
| **No computation-communication overlap** | Pattern: Post→Wait→Compute | MEDIUM |
| **Small messages not batched** — each ghost area gets separate Isend/Irecv | mpi_node_internal.f90:548-568 | HIGH |

### 3.4 Scalability Limits

- `ni == no` constraint requires balanced partitions — fails with non-uniform workloads
- All operations on MPI_COMM_WORLD — inactive processes still participate
- Global numbering arrays replicated — memory scales as O(N_global × P)

---

## 4. Utilities and Supporting Libraries

### 4.1 Module Architecture

94% of `src/utils/` uses modern Fortran 90+ modules. Legacy COMMON blocks are confined to `src/contrib/ecological/` (external contributions).

**Key modules analyzed:**
- **`para.f90`** (1,412 lines): Parameter management. Proper module but only 2 intent declarations across entire file
- **`mod_physical_constants.f90`**: Well-designed, centralized constants (pi, gravity, von Karman, Stefan-Boltzmann). No issues
- **`version.f90`** (585 lines): Clean version tracking since 1998

### 4.2 Error Handling Patterns

Four inconsistent error handling patterns found:
1. **Direct `stop`** — most common: `if(ierr /= 0) stop 'error stop: allocation failed'`
2. **`mod_error_stop`** module — structured but underutilized
3. **`stop` with varying message formats** — no standardization
4. **Custom error subroutines** — per-module (e.g., `clo_error`)

### 4.3 GOTO Usage in Utilities

9 files contain GOTO statements. Most are acceptable error-exit patterns (`goto 99 ... 99 continue`):
- `evgeom.f90`: 5 GOTO labels
- `heat_util.f90`: 21+ GOTO statements (most problematic)
- `dts.f90`, `nls.f90`, `iso8601.f90`, `femfile.f90`, `utility.f90`, `mat_util.f90`

### 4.4 C Interoperability

Minimal and properly handled:
- `file.f90:440-445`: `fsync()` binding with proper `ISO_C_BINDING`
- PETSc/AMGX integration: Proper `iso_c_binding` usage
- No unsafe C interop patterns detected

---

## 5. Build System

### 5.1 Architecture

Recursive Makefiles orchestrated from root `Makefile`, configured via `Rules.make` (1,119 lines). Supports 5 Fortran compilers (gfortran, ifort, pgf90, xlf, nvfortran) and 4 parallelization modes (serial, OpenMP, MPI, hybrid).

### 5.2 Critical Build Issues

| Issue | Location | Severity |
|-------|----------|----------|
| **Parallel make race condition** — lib/mod directory creation | Makefile:175-177 | HIGH |
| **-fopenmp unconditionally linked** — even when OMP=false | Rules.make:758 | MEDIUM |
| **NETCDF path inconsistency** — line 140 vs 200 use different dirs | src/shyfem/Makefile:140,200 | MEDIUM |
| **No Fortran CI/CD** — only UI has GitHub Actions | .github/workflows/ | HIGH |
| **Version sync gap** — pyproject.toml not updated by bump-version.sh | shyfem-ui/pyproject.toml | MEDIUM |
| **Shell-based eco-builds** — `$(shell cd...; make)` fragile | src/shyfem/Makefile:179,183,192 | MEDIUM |
| **Backtick usage** — `ACTFEMDIR = \`pwd\`` legacy pattern | Makefile:60 | LOW |

### 5.3 Dependency Tracking

**Strengths:**
- 41 explicit `.mod` dependencies in src/shyfem/Makefile
- `makdp.pl` for automatic dependency generation

**Weaknesses:**
- Library files (LIBF) not treated as true dependencies — may be stale
- No guarantee of Fortran module compilation order in parallel make
- No `depend` target in root Makefile

### 5.4 CI/CD Pipeline

Only the Web UI has CI (`.github/workflows/ui-ci.yml`):
- Ruff linting, Black formatting
- Pytest unit tests (excluding Playwright)
- Playwright E2E tests (PR-only)
- Docker build validation

**Missing:**
- No Fortran compilation testing in CI
- No compiler matrix testing (gfortran, intel)
- No MPI/OpenMP configuration testing
- No regression test automation

---

## 6. Web UI (shyfem-ui/)

### 6.1 Architecture — Excellent

**Stack:** Python 3.13, Shiny for Python, SQLAlchemy 2.0, Alembic, deck.gl, Plotly

**Structure:**
- 14 Shiny page modules (home, admin, mesh_builder, simulation, run, ibm, visualize, etc.)
- 21 service modules (auth, access_control, file, job queues, parsers, etc.)
- 6 middleware modules (session auth, rate limiting, cache headers, health check, request ID)
- 5 Alembic database migrations
- 79+ test files (unit + E2E)

### 6.2 Code Quality — Excellent

| Aspect | Status | Details |
|--------|--------|---------|
| **Type hints** | ★★★★☆ | 306/842 functions (36%) have return type hints; SQLAlchemy models fully typed |
| **Error handling** | ★★★★★ | Comprehensive try/except, graceful degradation, logging |
| **SQL injection** | ★★★★★ | SQLAlchemy ORM exclusively, no raw SQL in critical paths |
| **Input validation** | ★★★★★ | Path traversal protection, null byte checks, filename sanitization |
| **Authentication** | ★★★★★ | Argon2 password hashing, HMAC timing-safe comparison, session DB |

### 6.3 Security

**Strengths:**
- Argon2-cffi for password hashing (auth_service.py)
- HMAC timing-safe comparison for basic auth
- Path traversal prevention with symlink resolution
- Per-client rate limiting with X-Forwarded-For spoofing protection
- Session tokens stored in DB with expiry
- Role-based access control

**Issues Found:**

| Issue | Severity | Location |
|-------|----------|----------|
| **Weak default admin password** (`niekas`) in .env | HIGH | .env:2 |
| **Auth disabled by default** in server mode | HIGH | config.py, docker-compose.yml |
| **No HTTPS built-in** — requires reverse proxy | MEDIUM | Dockerfile |
| **Bare `except Exception:` in auth_service** — 10 instances | LOW | auth_service.py |

### 6.4 Testing — Comprehensive

- 79+ test files, ~19,114 lines of test code
- Unit tests: auth, config, file_service, access control, parsers, validators
- Integration tests: job execution, database, middleware
- E2E: 10+ Playwright browser tests (login flows, UI interactions)
- CI: Ruff + Black linting, pytest with coverage

---

## 7. Testing Infrastructure

### 7.1 Fortran Testing

| Component | Status | Notes |
|-----------|--------|-------|
| Mar Menor test suite | ✅ 23 test cases | Exit code validation, sequential execution |
| Lagrangian tests | ✅ 3 test cases | Particle tracking validation |
| Regression framework | ⚠️ Exists but disabled | `femregress/` directory optional |
| MPI verification routines | ✅ Available | `shympi_check_*` in check_shympi_*.f90 |
| Runtime consistency | ✅ Available | `check_fem()`, `check_special()` |
| CI/CD automation | ❌ Missing | No GitHub Actions for Fortran |

### 7.2 Test Execution

```
testcases/examples/mar_menor/
├── make_all_sims.sh    → orchestrator (23 tests, exit code validation)
├── mm_hyd_*.sh          → individual test scripts
├── util.sh              → shared functions (Run, CheckFiles, CheckStatus)
└── Makefile             → grid initialization (shypre on .grd files)
```

### 7.3 Gaps

1. No automated Fortran build testing in CI
2. Regression testing framework inactive
3. No MPI test automation
4. Only 27 lines of testing documentation in DEVELOPER_GUIDE.md
5. 94 Playwright E2E tests skipped in CI

---

## 8. Documentation

### 8.1 Quality Assessment

| Document | Quality | Lines | Current |
|----------|---------|-------|---------|
| README.md | ★★★★★ | 184 | 2026-04 |
| CHANGELOG.md | ★★★★★ | 100+ sections | 2026-04 |
| DEVELOPER_GUIDE.md | ★★★★☆ | 28.2 KB | 2026-04 |
| CODEBASE_ANALYSIS.md | ★★★★★ | 56.7 KB | 2026-02 |
| MANUAL.md | ★★★★☆ | Full manual | Varies |
| docs/shyfem_manual.pdf | ★★★★☆ | 4.3 MB | 2025-12 |

### 8.2 Gaps

- Testing documentation sparse (27 lines in DEVELOPER_GUIDE)
- No "Adding New Tests" guide
- No CI/CD workflow documentation
- PDF manual may be out of sync with Markdown version

---

## 9. Obsolete Code

**320,214 lines** of obsolete code exist in `src/obsolete/` — nearly equal to the active codebase (352,575 lines). This includes:
- Duplicate SPARSKIT files (3 copies of spk_itpack.f90 at 8,656 lines each)
- Old versions of active files (sedim_admin, custom_admin, coordinates, etc.)
- Legacy `real getpar` external declaration patterns

**Recommendation:** Remove `src/obsolete/` from the repository. If historical reference is needed, it's preserved in git history.

---

## 10. Recommendations

### 10.1 Critical (address immediately)

1. **Add Fortran CI/CD** — GitHub Actions job: `make clean && make fem && cd testcases/examples/mar_menor && make init && ./make_all_sims.sh`
2. **Fix MPI error handling** — Replace `write(6,*)` with `call shympi_abort_internal()` in mpi_node_internal.f90:466,474,478
3. **Replace bare `stop` in MPI code** — 16 instances across 4 files need `shympi_abort_internal`
4. **Remove weak default password from .env** — `SHYFEM_UI_DEFAULT_ADMIN_PASSWORD=niekas` should not be in repository
5. **Enable auth by default in server mode** — `auth_enabled` should default to `True` when `deployment_mode=server`

### 10.2 High Priority (next release cycle)

6. **Add `implicit none`** to ~150 subroutines — priority: sedim_util.f90, nuopc_shyfem_cap.f90, meteo_forcing.f90
7. **Add `intent` declarations** to all subroutine arguments — priority: arrays.f90, shyfem_subs.f90
8. **Fix remaining 238 allocations** without `stat=` error checking
9. **Batch MPI ghost exchanges** — pack all ghosts into fewer large messages
10. **Fix parallel make race condition** — convert lib/mod to order-only prerequisite
11. **Sync version across all files** — update bump-version.sh to include pyproject.toml
12. **Enable Playwright tests in CI** — 94 tests currently skipped

### 10.3 Medium Priority (ongoing improvement)

13. **Reduce GOTO usage** — priority: heat_util.f90 (21 instances), evgeom.f90 (5 instances)
14. **Standardize error handling** — adopt `mod_error_stop` pattern consistently
15. **Remove obsolete code** — 320K lines in src/obsolete/
16. **Add MPI subcommunicators** — reduce overhead of all-process collectives
17. **Document testing workflow** — expand DEVELOPER_GUIDE.md testing section
18. **Fix NETCDF path inconsistency** — src/shyfem/Makefile line 140 vs 200
19. **Improve type hint coverage** — from 36% to 80%+ in Python UI

### 10.4 Long-term

20. **Migrate to CMake** — replace recursive Makefiles for better dependency tracking
21. **Implement computation-communication overlap** — in MPI ghost exchange
22. **Replace replicated global arrays** — distributed numbering for O(N/P) memory per rank
23. **Add static analysis** — Fortran linter in CI (e.g., fortran-linter, flint)

---

## Appendix A: File-Level Issue Index

### Files with Most Issues

| File | Issues |
|------|--------|
| `src/shyfem/sedim_util.f90` | 0% implicit none, no intents, GOTO |
| `src/shyfem/nuopc_shyfem_cap.f90` | 3% implicit none |
| `src/shyfem/meteo_forcing.f90` | 28% implicit none |
| `src/utils/shympi/mpi_node_internal.f90` | Weak error handling, OMP CRITICAL bottleneck, tag collisions |
| `src/utils/shympi/mpi_dummy.f90` | 12 bare stop statements |
| `src/utils/shympi/mpi_node.f90` | Replicated global arrays, bare stop |
| `src/utils/generic/heat_util.f90` | 21+ GOTO statements |
| `src/utils/shyutil/evgeom.f90` | 5 GOTO labels, no intent declarations |
| `src/shyfem/arrays.f90` | 15 subroutines without intent declarations |

### Files with Best Quality

| File | Quality |
|------|---------|
| `src/shyfem/mod_physical_constants.f90` | ★★★★★ Clean, well-documented, centralized |
| `src/shyfem/concentration.f90` | ★★★★☆ 100% allocation checking, proper intents |
| `bin/bump-version.sh` | ★★★★★ `set -euo pipefail`, validation, dry-run |
| `shyfem-ui/shyfem_ui/config.py` | ★★★★★ Pydantic validation, path security |
| `shyfem-ui/shyfem_ui/services/auth_service.py` | ★★★★☆ Argon2, timing-safe, session management |

---

*Report generated by automated deep codebase analysis using 6 parallel investigation agents covering all project areas.*
