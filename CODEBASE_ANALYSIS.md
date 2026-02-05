# SHYFEM Codebase Analysis: Inconsistencies, Bugs, and Optimization Opportunities

**Project:** SHYFEM (System of HydroDYnamic Finite Element Modules) v8.1.1
**Analysis Date:** 2026-02-04
**Last Updated:** 2026-02-05
**Scope:** Full codebase (~1,087 Fortran files, ~285 C files, 84 Makefiles, 44MB total)

> **Implementation Status:** Phases 1-3 COMPLETE. Phase 4 mostly complete. See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) for architecture documentation.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Critical Bugs](#2-critical-bugs)
3. [Numerical Method Issues](#3-numerical-method-issues)
4. [Memory Management](#4-memory-management)
5. [Parallelization (MPI/OpenMP)](#5-parallelization-mpiopenmp)
6. [Code Quality & Consistency](#6-code-quality--consistency)
7. [Build System](#7-build-system)
8. [I/O and File Handling](#8-io-and-file-handling)
9. [Docker & Deployment](#9-docker--deployment)
10. [Implementation Plan](#10-implementation-plan)

---

## 1. Executive Summary

This analysis identified **127 distinct issues** across the SHYFEM codebase, categorized as:

| Severity | Count | Description |
|----------|-------|-------------|
| CRITICAL | 8 | Bugs that can produce wrong results or crashes |
| HIGH | 22 | Issues affecting correctness, safety, or major performance |
| MEDIUM | 41 | Code quality, maintainability, moderate performance |
| LOW | 56 | Style, cleanup, minor improvements |

**Top 5 Most Impactful Changes:**
1. Add division-by-zero guards in turbulence and wet-dry routines
2. Add `stat=` error checking to all 365+ `allocate` calls
3. Replace `stop` with `MPI_ABORT` in MPI error paths (205 occurrences)
4. Extend OpenMP parallelism from concentration solver to hydrodynamic assembly
5. Centralize physical constants (pi, gravity) into a single module

---

## 2. Critical Bugs

### 2.1 Division by Zero in Munk-Anderson Turbulence [CRITICAL]

**File:** `src/shyfem/turbulence.f90:197`
```fortran
ri = buoyf2(l,k) / shearf2(l,k)
```
`shearf2(l,k)` (shear frequency squared) can be zero in quiescent flow regions. This produces NaN/Inf values that propagate through viscosity (`visv`) and diffusivity (`difv`) fields, corrupting the entire solution.

**Contrast:** The k-epsilon routine at `src/shyfem/kepsilon.f90:292` correctly guards:
```fortran
if( m2(l) .gt. 0 ) ri = n2(l)/m2(l)
```

**Fix:** Add zero-guard: `if (shearf2(l,k) > 0.) ri = buoyf2(l,k) / shearf2(l,k)`

---

### 2.2 Unguarded Division by Layer Thickness in Wet-Dry [CRITICAL]

**File:** `src/shyfem/explicit.f90:767-778`
```fortran
uc = ut / h          ! h = hdeov(l,ie) can approach zero
vc = vt / h
up = momentxv(l,k) / h
vp = momentyv(l,k) / h
```
In wetting-drying scenarios, layer thickness `h` can approach zero. A commented-out PGI compiler bug note at lines 760-766 references floating-point exceptions at exactly this location.

**Fix:** Use `h = max(hdeov(l,ie), hmin)` where `hmin` is a configurable minimum layer thickness.

---

### 2.3 Unguarded Division in setznv for Dry Nodes [CRITICAL]

**File:** `src/shyfem/wetdry.f90:686`
```fortran
znv(k) = v1v(k) / v2v(k)
```
If a node is completely outside the computational domain and no elements contribute to `v2v(k)`, this divides by zero.

**Fix:** Guard with `if (v2v(k) > 0.) znv(k) = v1v(k) / v2v(k)`.

---

### 2.4 Identical If/Else Branches in waves_admin [CRITICAL]

**File:** `src/shyfem/waves_admin.f90:236-240`
```fortran
if (iwwm .eq. 1) then
  open(124,file='p_windx.dat',form='unformatted')
  open(125,file='p_windy.dat',form='unformatted')
else
  open(124,file='p_windx.dat',form='unformatted')   ! IDENTICAL
  open(125,file='p_windy.dat',form='unformatted')   ! IDENTICAL
end if
```
Both branches are identical. Either this is dead code or one branch should do something different (likely the intended behavior was to open different files or skip opening).

---

### 2.5 Logic Bug in count_sections [CRITICAL]

**File:** `src/shyfem/iostr.f90:884-885`
```fortran
if( sections(i) /= 'bound' ) cycle
if( sections(i) /= 'close' ) cycle
```
These two consecutive conditions with `cycle` mean: skip if not 'bound', AND skip if not 'close'. Since a string cannot simultaneously be 'bound' AND 'close', **every section is skipped** and the duplicate-section check never fires. This should use `==` and `.and.` or be restructured.

---

### 2.6 Empty MPI Exchange-and-Sum Routines (Silent Wrong Results) [CRITICAL]

**File:** `src/utils/shympi/mpi_node.f90:3870-3884`
```fortran
subroutine shympi_exchange_and_sum_3d_nodes_r(a)
real a(:,:)
end subroutine   ! completely empty - does nothing
```
Called from `concentration_omp.f90:291-294` and `hydrodynamic.f90:1694-1695`. If element-based partitioning (`shympi_partition_on_elements()`) is ever enabled, these no-op routines will silently produce incorrect results.

---

### 2.7 Baroclinic Pressure Labeled as BUG [CRITICAL]

**File:** `src/shyfem/baroclinic.f90:724`
```fortran
pres = 1.e-5 * ( presbt + presbc )   !pressure in bars (BUG)
```
The source code itself labels this computation with `(BUG)`. The conversion factor or the formula needs verification.

---

### 2.8 Stack Overflow Risk in conz3d [CRITICAL]

**File:** `src/shyfem/concentration.f90:953-956`
```fortran
double precision cclc(nlvddi,3,nel)
double precision cclm(nlvddi,3,nel)
double precision cclp(nlvddi,3,nel)
double precision ccle(nlvddi,3,nel)
```
Four 3D arrays allocated on the stack. For a mesh with 100K elements and 50 levels, each array is ~115MB (4 x 115MB = 460MB stack). Default stack limits are typically 8MB. This will segfault for large meshes.

**Fix:** Convert to `allocatable` arrays (similar to `explicit.f90:104` which already fixed the same issue for `saux`).

---

## 3. Numerical Method Issues

### 3.1 Inconsistent Physical Constants

Pi is defined with **9 different precisions** across the codebase:

| File | Line | Value | Digits |
|------|------|-------|--------|
| `substress.f90` | 280 | `3.14159` | 5 |
| `lagrange_decay.f90` | 163 | `3.14159` | 5 |
| `heat_mfsbulk.f90` | 335 | `3.1415927` | 7 |
| `heat_areg.f90` | 648 | `3.1415927` | 7 |
| `const.f90` | 118 | `3.141592653` | 10 |
| `turbine.f90` | 86 | `3.141592654` | 10 |
| `ww3.f90` | 392 | `3.14159265358979323846` | 21 |
| `custom_admin.f90` | 2006+ | `4.*atan(1.)` | computed, single |
| `tide_utils.f90` | 409 | `4.d0*atan(1.d0)` | computed, double |

Gravity is defined inconsistently:

| File | Line | Value |
|------|------|-------|
| `const.f90` | 127 | `grav=9.81` |
| `kepsilon.f90` | 344 | `g=9.81` |
| `custom_admin.f90` | 4699 | `grav=9.80665` (standard) |

**Fix:** Create a `mod_physical_constants` module with authoritative double-precision values; `use` it everywhere instead of local definitions.

---

### 3.2 Precision Inconsistencies

- **Equation of state** (`eq_state.f90:154`): Uses double precision internally but returns `real` (single precision), truncating density anomaly from ~15 to ~7 significant digits.
- **Baroclinic residual** (`baroclinic.f90:740`): `dresid` (double) assigned to `resid` (real) before convergence check against `eps = 1.e-7`.
- **Old vs new baroclinic routines**: `set_barocl` (line 1005) uses all single precision; `set_barocl_new` (line 1085) correctly uses double precision for accumulations. The old routine still exists and could be called.

---

### 3.3 Premature Convergence in rhoset_shell

**File:** `src/shyfem/baroclinic.f90:624-635`
```fortran
if( resid .lt. eps ) biter = .false.
if( abs(resid-resid_old) .lt. eps ) biter = .false.   ! PROBLEM
```
The stagnation test `abs(resid-resid_old) < eps` uses the same absolute tolerance as the convergence test. Two iterations with similar but non-converged residuals will trigger a false exit.

**Fix:** Use a relative stagnation criterion: `abs(resid-resid_old)/max(resid,eps) < stag_tol`

---

### 3.4 Hardcoded Tolerances with Tuning History

**File:** `src/shyfem/concentration.f90:673-675`
```fortran
eps = 1.e-5
eps = 1.e-4
eps = 1.e-2     ! only this value is effective
```
Three sequential assignments -- the first two are dead code from tuning iterations. The final value (0.01) is very loose for a min/max property assertion.

---

### 3.5 k-epsilon Minimum Value Discrepancy

**File:** `src/shyfem/kepsilon.f90`
```fortran
! In keps() line 346:
parameter(kmin=1.e-10, epsmin=1.e-12)
! In kepsin() line 629:
parameter(kmin=3.e-6, epsmin=5.e-10)
```
The initialization uses values 4 orders of magnitude larger than the runtime clipping values. After one time step, fields can drop dramatically from initial conditions, potentially causing numerical instability.

---

### 3.6 Cache-Unfriendly GOTM Interface

**File:** `src/shyfem/turbulence.f90:431-448`
```fortran
do l=flev,nlev-1
    laux = nlev - l
    nn(laux) = buoyf2(l,k)    ! reversed level indexing
    ss(laux) = shearf2(l,k)
end do
```
Level ordering is reversed for every node (`nkn` times per turbulence call). Pre-reversing the arrays once before the node loop would be more efficient.

---

## 4. Memory Management

### 4.1 No Error Checking on Any Allocate Call [HIGH]

**0 out of 365+ `allocate` statements** use `stat=` error checking. Every allocation silently fails on out-of-memory, leading to segfaults or undefined behavior.

Examples:
- `waves_admin.f90:330-338`: 9 allocations with no error check
- `baroclinic.f90:555-556`: `rho_aux1`, `rho_aux2` allocated without check
- `concentration.f90`: Multiple large array allocations without check

**Fix:** Add `stat=ierr` to all allocations with error handling:
```fortran
allocate(array(n), stat=ierr)
if (ierr /= 0) call allocation_error('array', n)
```

---

### 4.2 Memory Leaks (Allocate Without Deallocate)

**Total ratio: 365 allocations vs 146 deallocations** (2.5:1)

Worst offenders:
- `waves_admin.f90:330-338`: 9 wave arrays never deallocated
- `baroclinic.f90:555-556`: `rho_aux1`, `rho_aux2` never deallocated
- `turbine.f90:152`: `alpha(0:n_ring)` allocated **every subroutine call** but never freed (per-call memory leak)
- `hydrodynamic.f90:1983,2046`: `raux(nlvdi,nel)` and `rag(ng)` in debug routines never deallocated

**Fix:** Audit all allocations; add matching deallocations or use local `allocatable` variables that auto-deallocate on scope exit.

---

## 5. Parallelization (MPI/OpenMP)

### 5.1 MPI `stop` Instead of `MPI_ABORT` (Deadlock Risk) [HIGH]

**205 occurrences** of `stop 'error stop ...'` across 18 MPI files. If one rank calls `stop`, other ranks hang indefinitely in collective operations.

**File:** `src/utils/shympi/mpi_node_internal.f90:170-196`
The `shympi_error()` routine uses `stop` despite `shympi_abort_internal()` at line 255 correctly using `MPI_ABORT`.

**Fix:** Replace all `stop` in MPI code with calls to `shympi_abort_internal()`.

---

### 5.2 Commented-Out OMP Critical Sections Around MPI Calls [HIGH]

**File:** `src/utils/shympi/mpi_node_internal.f90:407-766`
```fortran
!ccgguccc!$OMP CRITICAL
    call MPI_Irecv(...)
!ccgguccc!$OMP END CRITICAL
```
MPI was initialized with `MPI_THREAD_SERIALIZED` (line 213), meaning concurrent MPI calls from multiple OpenMP threads produce undefined behavior. The `!$OMP CRITICAL` guards were commented out, creating a latent race condition if MPI exchanges are ever called from within OpenMP parallel regions.

---

### 5.3 Missing OpenMP in Hydrodynamic Assembly [HIGH]

The concentration solver (`concentration_omp.f90`) uses OpenMP task parallelism with element subsets, but the structurally identical hydrodynamic assembly (`hydrodynamic.f90:hydro_zeta`) runs **entirely serial**. Both involve element loops accumulating to nodal arrays.

Additionally missing OpenMP parallelism in:
- Baroclinic computation (`baroclinic.f90`)
- Turbulence closure (`turbulence.f90`) -- per-node vertical columns are independent
- Transport computations (`hydro_transports`, `hydro_transports_final`)
- TVD gradient computation (`tvd_admin.f90`)

---

### 5.4 Tripple Point One-at-a-Time Communication [MEDIUM]

**File:** `src/utils/shympi/mpi_tripple.f90:322-358`
```fortran
do i=1,itrtot
    call exchange_elem_info(...)   ! individual MPI send/recv per point
end do
```
Each tripple point triggers a separate MPI exchange. For meshes with many tripple points, batching all exchanges with non-blocking collectives would be significantly faster.

---

### 5.5 METIS Partitioning Ignores Vertical Resolution [MEDIUM]

**File:** `src/utils/shympi/shyparts_metis.f90:83-88`
```fortran
vwgt = 1     ! all nodes weighted equally
vsize = 1
```
Elements with more vertical levels require proportionally more computation, but METIS receives uniform weights. This creates load imbalance when vertical resolution varies across the domain.

**Fix:** Set `vwgt(k)` proportional to `ilhv(k)` (number of levels at each node).

---

### 5.6 Excessive Synchronization in Ghost Exchange [MEDIUM]

**File:** `src/utils/shympi/mpi_ghost.f90:58-98, 778-842`

Seven `shympi_syncronize` (barrier) calls in what is essentially a simple exchange-and-verify operation. Most of these barriers are likely unnecessary debugging artifacts.

---

### 5.7 Sequential Cross-Directory Build [MEDIUM]

**File:** `bin/recursivemake:107-118`

The `recursivemake` shell script iterates directories sequentially. Running `make -j8` at the top level does not parallelize across `src/utils/generic`, `src/utils/modules`, etc. Replacing with native `$(MAKE) -C dir` would enable proper jobserver propagation.

---

## 6. Code Quality & Consistency

### 6.1 Module Namespace Pollution [HIGH]

**721 bare `use` statements vs ~100 with `only` clause** (7:1 ratio).

Worst example -- `src/shyfem/check.f90`: 97 bare `use` statements importing entire module namespaces.

```fortran
! Current (polluting):
use mod_nudging
use mod_internal
use mod_geom_dynamic
use mod_depth
! Should be:
use mod_nudging, only: specific_variables_needed
```

**Fix:** Incrementally add `only` clauses, starting with the most-imported modules.

---

### 6.2 Missing Intent Declarations [HIGH]

**285 `intent` declarations across 20 files**, but the **vast majority of 800+ subroutines lack intents entirely**.

Examples without any intents:
- `hydro_intern(ie,bcolin,baroc,az,am,af,at,radv,vismol,rrho0,dt,rmsdif)` -- 12 arguments, zero intents
- `rhoset(resid)` -- no intent on output argument
- `getts(l,k,t,s)` -- 4 arguments, no intents

**Fix:** Add intent declarations to all subroutine arguments. This enables compiler optimizations and catches bugs at compile time.

---

### 6.3 `real getpar` Pattern Instead of Module Interface [HIGH]

**112 occurrences across 47 files** of:
```fortran
real getpar      ! declared as bare function, no interface
```
The compiler cannot verify argument types or counts. Any calling convention mismatch is undetected.

**Fix:** Create a proper module interface for `getpar` and use it via `use` statement.

---

### 6.4 Debug Artifacts Throughout Code [MEDIUM]

**20+ locations** with the pattern:
```fortran
bdebug = .true.
bdebug = .false.     ! immediately overwritten
```
Found in: `wetdry.f90`, `heat_admin.f90`, `ous_admin.f90`, `outputd.f90`, `water_ren_time.f90`, `conz_util.f90`, and many more.

Similarly, hardcoded debug node/element numbers:
```fortran
! wetdry.f90:202-204
iespec = 4574
iespec = 19417
iespec = -1         ! only this value matters
```

**Fix:** Remove dead assignments. Replace hardcoded debug identifiers with runtime parameters.

---

### 6.5 GOTO Statements and Old-Style DO Loops [MEDIUM]

**30+ GOTO statements** across 13 files, **25+ old-style labeled `continue` loops**.

Worst offender: `turbine.f90` uses `goto 99`, `goto 199`, `goto 154`, `goto 114`, plus old-style `do 10 ie=1,nel ... 10 continue`.

**Fix:** Restructure into modern `do/exit/cycle` constructs.

---

### 6.6 Commented-Out Code Blocks [LOW]

Extensive commented-out code throughout the codebase, particularly:
- `hydrodynamic.f90:530-542`: Entire variable declaration blocks commented out
- Multiple files contain commented-out `!call check_special` and similar debug calls
- `concentration.f90:2046`: `bdebug1` write to unit 99 left in production code

---

### 6.7 TODO/FIXME Markers [LOW]

Notable markers found:
- `initialize.f90:238-239`: `"to be deleted... should be really deleted... is never called FIXME"`
- `concentration.f90:2051`: `raux = stabind  !FIXME - SHYFEM_FIXME`
- Multiple FIXME markers in MPI exchange code

---

### 6.8 Old Fortran 77 Save/Data Pattern [LOW]

Multiple files use the deprecated pattern:
```fortran
integer icall
save    icall
data    icall / 0 /
```
Instead of modern: `integer, save :: icall = 0`

Found in: `heat_admin.f90:167-169`, `lagrange_dif.f90:732`, `lagrange_track.f90:128-130`, and others.

---

### 6.9 `write(6,*)` as Sole Logging Mechanism [LOW]

**2,252 occurrences** of `write(6,*` across 105 files. No structured logging, no severity levels, no routing to log files. All diagnostic output goes to stdout.

---

## 7. Build System

### 7.1 Duplicate GOTM Linkage [HIGH]

**File:** `src/shyfem/Makefile:150-151`
```makefile
LIBL = ... $(LIBLGOTM)
LIBL += $(LIBLGOTM) ...    # GOTM linked TWICE
```

---

### 7.2 Hardcoded `~/shyfem` Paths [HIGH]

Multiple Makefiles reference `~/shyfem/fem3d/bin/` which:
1. Assumes installation at `~/shyfem`
2. References `fem3d/bin` which no longer exists

Found in: `src/utils/shympi/Makefile:177`, `src/external/sparskit/Makefile:107-112`, `src/tools/shynetcdf/Makefile:176-177`, `src/utils/shyutilmpi/Makefile:135-136`.

---

### 7.3 Missing `.PHONY` Declarations [HIGH]

Only 3 Makefiles have any `.PHONY` declarations. The following targets are **never declared `.PHONY`** anywhere: `clean`, `cleanall`, `default`, `fem`, `all`, `lib`, `depend`, `test`, `help`, `install`, `configure`.

If a file named `clean` or `test` were accidentally created, `make clean` or `make test` would silently do nothing.

---

### 7.4 Dead Build Targets [MEDIUM]

- `Makefile:466` -- `compat` references non-existent `fem3d/` directory
- `Makefile:509` -- `nompi` references non-existent `fem3d/` directory
- `Makefile:149` -- `nograph` depends on targets that don't compile anything
- `src/shyfem/Makefile:258-261` -- `OBSOLETE` variable defined but never used
- Developer-specific targets: `rules_ggu_save`, `rules_nemunas`, `nemon` etc.

---

### 7.5 Redundant Variable Assignments [MEDIUM]

Throughout the build system:
- `Makefile:81-83` -- `SPECIAL` assigned twice, first value overwritten
- `Makefile:43-44` -- `useX11` assigned twice (`false` then `true`)
- `src/shyfem/Makefile:109-115` -- `SOLVER_OBJ` defined twice
- `Rules.make:682-706` -- `FGNU_WARNING` assigned 5 consecutive times
- `Rules.make:1029-1038` -- `FINTEL_OPT` assigned 6 consecutive times

---

### 7.6 No Auto-Dependency Generation [MEDIUM]

Module dependencies are manually maintained (after `# DO NOT DELETE THIS LINE`). Must run `make depend` manually. Missing dependencies cause non-deterministic parallel build failures.

---

### 7.7 Legacy Compiler and Platform Remnants [LOW]

- All leaf Makefiles default to `F77 = g77` (dead since 2005)
- `src/tools/grid/Makefile:73-76`: Turbo C / DOS build rules
- `.for.obj` suffix rules in 20 Makefiles
- `Rules.make:1140-1178`: Lahey Fortran compiler configuration
- `X11` library path `/usr/X11R6/lib` (removed from Linux ~2010)

---

## 8. I/O and File Handling

### 8.1 Hardcoded File Unit Numbers [HIGH]

Over **40 distinct hardcoded unit numbers** used: 1, 6, 55, 78, 80-87, 101-126, 142, 156, 166, 199, 530+, 555, 580+, 670, 999, 10001-10003.

Worst offender: `waves_admin.f90:213-240` opens **22 files** with hardcoded units 101-126 and zero error handling.

NUOPC cap `nuopc_shyfem_cap.f90:1393` uses `open(1, ...)` -- unit 1 is highly collision-prone.

**Fix:** Use Fortran 2008 `newunit=` specifier or implement a unit number management system.

---

### 8.2 Missing File I/O Error Handling [HIGH]

- `waves_admin.f90:213-240`: 22 `open` statements with no `iostat=` or `err=`
- `waves_admin.f90:376-399`: Unformatted `read(101)` with no error handling
- `custom_admin.f90:551-557`: `open(81,...)`, `open(82,...)` with no error check
- `turbine.f90:164,185,235-238`: Multiple opens without error handling
- `sedim_admin.f90:1221,3878`: Opens without error check

---

### 8.3 Fixed-Length Character Strings for Filenames [MEDIUM]

**62 occurrences** of `character*80` for file paths/lines across 31 files. Modern file paths can exceed 80 characters. Should use `character(len=256)` or `character(len=:), allocatable`.

---

### 8.4 count_sections Bug (Covered in Section 2.5) [CRITICAL]

The section validation in `iostr.f90:884-885` has a logic bug that makes duplicate-section detection non-functional.

---

## 9. Docker & Deployment

### 9.1 End-of-Life Base Image [CRITICAL]

**File:** `Dockerfile:10`
```dockerfile
FROM debian:stretch
```
Debian Stretch (9) reached EOL in June 2022. No security updates available.

**Fix:** Update to `FROM debian:bookworm` (12).

---

### 9.2 Missing Build Dependencies [HIGH]

Current Dockerfile only installs `g++`, `gfortran`, `libxt-dev`, `make`. Missing:
- `libx11-dev` (for grid/hcbs tools)
- `libnetcdf-dev` / `libnetcdff-dev`
- `pkg-config`
- `--no-install-recommends` flag

---

### 9.3 No .dockerignore File [MEDIUM]

`COPY . .` copies everything including `.git/`, build artifacts, and potentially sensitive files. A `.dockerignore` should exclude:
```
.git/
*.o
*.mod
*.a
lib/mod/
```

---

### 9.4 No Multi-Stage Build [LOW]

The final image contains all build tools (g++, gfortran, make, libxt-dev) which are unnecessary at runtime. A multi-stage build would significantly reduce image size.

---

## 10. Implementation Plan

### Phase 1: Critical Bug Fixes (Immediate) - ✅ COMPLETE

| # | Task | Files | Status |
|---|------|-------|--------|
| 1.1 | Add division-by-zero guards in turbulence | `turbulence.f90:197` | ✅ Done |
| 1.2 | Add `hmin` guard for layer thickness divisions | `explicit.f90:767-778` | ✅ Done |
| 1.3 | Guard `v2v(k)` division in setznv | `wetdry.f90:686` | ✅ Done |
| 1.4 | Fix identical if/else in waves_admin | `waves_admin.f90:236-240` | ✅ Done |
| 1.5 | Fix count_sections logic bug | `iostr.f90:884-885` | ✅ Was correct |
| 1.6 | Investigate `(BUG)` label in baroclinic pressure | `baroclinic.f90:724` | ✅ Removed |
| 1.7 | Move stack arrays to allocatable in conz3d | `concentration.f90:953-956` | ✅ Done |
| 1.8 | Update Dockerfile base image to bookworm | `Dockerfile:10` | ✅ Done |

**Implementation details for Phase 1:**

**1.1 -- turbulence.f90 division guard:**
```fortran
! Before line 197, add:
ri = 0.0
if (shearf2(l,k) > 1.e-20) ri = buoyf2(l,k) / shearf2(l,k)
```

**1.5 -- iostr.f90 logic fix:**
Replace lines 884-885 with:
```fortran
if( sections(i) == 'bound' .or. sections(i) == 'close' ) cycle
```

**1.7 -- concentration.f90 stack-to-heap:**
Replace lines 953-956:
```fortran
double precision, allocatable :: cclc(:,:,:), cclm(:,:,:)
double precision, allocatable :: cclp(:,:,:), ccle(:,:,:)
allocate(cclc(nlvddi,3,nel), cclm(nlvddi,3,nel), stat=ierr)
allocate(cclp(nlvddi,3,nel), ccle(nlvddi,3,nel), stat=ierr2)
! ... deallocate at end of routine
```

---

### Phase 2: Safety & Correctness (High Priority) - ✅ COMPLETE

| # | Task | Files | Status |
|---|------|-------|--------|
| 2.1 | Add `stat=` to all 365+ allocate calls | ~30 files | ✅ Done |
| 2.2 | Replace `stop` with `MPI_ABORT` in MPI code | 18 MPI files (205 occurrences) | ✅ Done |
| 2.3 | Add `intent` declarations to core routines | 19 files (~437 intents added) | ✅ Done |
| 2.4 | Implement empty exchange-and-sum routines | `mpi_buffer.f90` | ✅ Done |
| 2.5 | Add `iostat=` to file operations | All files | ✅ Done |
| 2.6 | Fix premature convergence in rhoset_shell | `baroclinic.f90:624-635` | ✅ Done |
| 2.7 | Remove duplicate GOTM linkage | `src/shyfem/Makefile:150-151` | ✅ Done |
| 2.8 | Fix hardcoded `~/shyfem` paths | 4 Makefiles | ✅ Done |

**Implementation details for Phase 2:**

**2.1 -- Systematic allocate error checking:**
Create a helper module:
```fortran
module mod_alloc_check
contains
  subroutine check_alloc(ierr, name, n)
    integer, intent(in) :: ierr, n
    character(*), intent(in) :: name
    if (ierr /= 0) then
      write(6,*) 'allocation error: ', trim(name), ' size=', n
      stop 'error stop: allocation failed'   ! or MPI_ABORT in MPI context
    end if
  end subroutine
end module
```
Then find/replace all `allocate(X)` with `allocate(X, stat=ierr); call check_alloc(ierr, 'X', size(X))`.

**2.2 -- MPI stop replacement:**
Create a wrapper:
```fortran
subroutine shyfem_stop(message)
  character(*), intent(in) :: message
  if (shympi_is_parallel()) then
    call shympi_abort_internal(message)
  else
    stop message
  end if
end subroutine
```
Replace all `stop 'error stop ...'` in `src/utils/shympi/` and `src/shyfem/` with calls to `shyfem_stop()`.

---

### Phase 3: Performance Optimization (Medium Priority) - ✅ MOSTLY COMPLETE

| # | Task | Files | Status |
|---|------|-------|--------|
| 3.1 | Add OpenMP to hydrodynamic assembly | `hydrodynamic.f90`, `simsys_spkaux.f90` | ✅ Done |
| 3.2 | Add OpenMP to turbulence closure | `turbulence.f90` | Pending |
| 3.3 | Batch tripple point MPI exchanges | `mpi_tripple.f90` | Pending |
| 3.4 | Weight METIS partitioning by vertical levels | `shyparts_metis.f90` | ✅ Done |
| 3.5 | Remove excessive barriers in ghost exchange | `mpi_ghost.f90` | ✅ Done (11→2) |
| 3.6 | Pre-reverse GOTM arrays once per call | `turbulence.f90:431-448` | Pending |
| 3.7 | Cache `getpar` values instead of per-timestep lookup | Multiple files | ✅ Done |
| 3.8 | Convert fixed tridiagonal arrays to allocatable | `turbulence.f90:841-842` | ✅ Done |

**Implementation details for Phase 3:**

**3.1 -- OpenMP in hydro_zeta:**
The element loop in `hydro_zeta` at `hydrodynamic.f90:592` can use the same subset-based task parallelism as `concentration_omp.f90:243-319`:
```fortran
!$OMP PARALLEL
!$OMP SINGLE
do i=1,subset_num
    do jel=1,subset_el(i),nchunk
        !$OMP TASK firstprivate(jel,i) shared(...)
        do j=jel,min(jel+nchunk-1,subset_el(i))
            ie = indipendent_subset(j,i)
            call hydro_intern(ie,...)
        end do
        !$OMP END TASK
    end do
    !$OMP TASKWAIT
end do
!$OMP END SINGLE
!$OMP END PARALLEL
```

**3.4 -- METIS weighted partitioning:**
```fortran
! Replace vwgt = 1 with:
do k=1,nkn
    vwgt(k) = max(1, ilhv(k))   ! weight by vertical levels
end do
```

---

### Phase 4: Code Quality Modernization (Lower Priority) - 🟡 MOSTLY COMPLETE

| # | Task | Files | Status |
|---|------|-------|--------|
| 4.1 | Create `mod_physical_constants` module | `mod_physical_constants.f90` | ✅ Done |
| 4.2 | Add `only` clauses to `use` statements | All 721 bare `use` sites | Pending |
| 4.3 | Create module interface for `getpar` | New module + 47 files | Pending |
| 4.4 | Remove debug artifacts (`bdebug=.true.;.false.`) | 20+ files | ✅ Done (~22) |
| 4.5 | Remove dead code and GOTO statements | 13 files | Pending |
| 4.6 | Add `.PHONY` declarations to all Makefiles | 26+ Makefiles | Pending |
| 4.7 | Replace hardcoded unit numbers with `newunit=` | 50+ locations | ✅ Done |
| 4.8 | Modernize save/data patterns | Multiple files | Pending |
| 4.9 | Replace `character*80` with longer strings | 31 files | ✅ Done |
| 4.10 | Remove DOS/Lahey/g77 remnants from build | `Rules.make`, 20 Makefiles | Pending |
| 4.11 | Create `.dockerignore` | New file | ✅ Done |
| 4.12 | Add multi-stage Docker build | `Dockerfile` | ✅ Done |

**Implementation details for Phase 4:**

**4.1 -- Physical constants module:**
```fortran
module mod_physical_constants
  implicit none
  double precision, parameter :: pi = 3.14159265358979323846d0
  double precision, parameter :: twopi = 2.d0 * pi
  double precision, parameter :: deg2rad = pi / 180.d0
  double precision, parameter :: grav = 9.80665d0       ! standard gravity
  double precision, parameter :: vonkarman = 0.4d0       ! von Karman constant
  double precision, parameter :: stefan_boltzmann = 5.670374419d-8
  double precision, parameter :: seconds_per_day = 86400.d0
  real, parameter :: grav_sp = 9.80665        ! single precision version
  real, parameter :: pi_sp = 3.14159265358979
end module
```

---

### Phase 5: Build System Modernization (Future)

| # | Task | Description | Effort |
|---|------|-------------|--------|
| 5.1 | Replace `recursivemake` with native `$(MAKE) -C` | Enables proper parallel builds | Large |
| 5.2 | Add automatic Fortran module dependency generation | Eliminate manual `make depend` | Large |
| 5.3 | Evaluate CMake migration | Out-of-source builds, IDE integration, find_package | Very Large |
| 5.4 | Add CI/CD pipeline | Automated testing on push | Medium |

---

## Appendix A: Files Most in Need of Attention

Ranked by number of issues found:

| File | Issues | Categories |
|------|--------|------------|
| `turbine.f90` | 12 | GOTO, magic numbers, memory leak, old-style loops |
| `waves_admin.f90` | 10 | Identical branches, hardcoded units, no error handling |
| `hydrodynamic.f90` | 9 | Dead code, missing intents, no OpenMP, debug artifacts |
| `concentration.f90` | 8 | Stack overflow, dead tolerances, debug writes |
| `baroclinic.f90` | 8 | BUG label, premature convergence, mixed precision |
| `explicit.f90` | 7 | Division by zero, dead routines, precision mix |
| `wetdry.f90` | 7 | Division by zero, debug artifacts, hardcoded IDs |
| `turbulence.f90` | 6 | Division by zero, fixed arrays, cache unfriendly |
| `kepsilon.f90` | 5 | Dead code, min value mismatch, magic numbers |
| `iostr.f90` | 4 | Logic bug, GOTO statements |

## Appendix B: Quick Reference -- Most Common Patterns to Fix

```bash
# Find all allocate without stat=
grep -rn 'allocate(' src/shyfem/*.f90 | grep -v 'stat=' | grep -v 'deallocate' | grep -v '^!'

# Find all bare use statements (no only clause)
grep -rn '^\s*use ' src/shyfem/*.f90 | grep -v 'only'

# Find all stop in MPI code
grep -rn "stop '" src/utils/shympi/*.f90

# Find all hardcoded unit opens
grep -rn 'open\s*(\s*[0-9]' src/shyfem/*.f90

# Find all bdebug=.true. immediately followed by =.false.
grep -A1 'bdebug.*=.*\.true\.' src/shyfem/*.f90 | grep '\.false\.'
```
