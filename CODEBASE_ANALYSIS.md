# SHYFEM Codebase Analysis

**Project:** SHYFEM (System of HydroDYnamic Finite Element Modules) v8.1.1
**Analysis Date:** 2026-02-13
**Scope:** Full codebase — Fortran engine, C tools, Python web UI, build system, tests

> **Previous Work:** Phases 1-4 (PRs #1-5) addressed all critical bugs, safety issues, performance optimizations, and code quality improvements. Phases 5-8 (PRs #6-8) implemented the web UI. This document supersedes the prior analysis with a fresh, comprehensive view of the current state.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Repository Structure](#2-repository-structure)
3. [Core Architecture](#3-core-architecture)
4. [Module Inventory](#4-module-inventory)
5. [Parallelization](#5-parallelization)
6. [Code Quality Status](#6-code-quality-status)
7. [Performance Characteristics](#7-performance-characteristics)
8. [Build System](#8-build-system)
9. [Tools & Utilities](#9-tools--utilities)
10. [Test Infrastructure](#10-test-infrastructure)
11. [Web UI (shyfem-ui)](#11-web-ui-shyfem-ui)
12. [External Dependencies](#12-external-dependencies)
13. [Remaining Issues & Recommendations](#13-remaining-issues--recommendations)
14. [Implementation History](#14-implementation-history)

---

## 1. Project Overview

SHYFEM is a finite element hydrodynamic model for simulating flow, transport, and ecological processes in shallow water bodies (lagoons, coastal seas, estuaries). It solves the 3D shallow water equations on unstructured triangular grids using a semi-implicit finite element method.

### Key Capabilities
- 2D/3D baroclinic hydrodynamics (semi-implicit time stepping)
- Scalar transport (temperature, salinity, tracers) with TVD advection
- Multiple turbulence closures (Munk-Anderson, k-epsilon, GOTM)
- Sediment transport (SEDTRANS05), fluid mud, mercury
- Wave models (parametric, WaveWatch III coupling)
- Lagrangian particle tracking
- Ecological models (AQUABC, BFM/ERSEM, eutrophication)
- Sea ice model
- NUOPC/ESMF coupler interface

### Scale

| Metric | Count |
|--------|-------|
| Fortran 90+ files (.f90) | 998 |
| Fixed-format Fortran (.f) | 61 |
| C source files (.c) | 136 |
| C headers (.h) | 223 |
| Python files (UI + venv) | ~8,900 |
| Makefiles | 81 |
| Fortran LOC | ~515,000 |
| C LOC | ~215,000 |
| Python LOC (app code) | ~13,200 |

---

## 2. Repository Structure

```
shyfem/
├── src/
│   ├── shyfem/          # Core hydrodynamic engine (133 .f90, 111K LOC)
│   ├── utils/
│   │   ├── generic/     # General utilities, parameters (43 files, 30K LOC)
│   │   ├── modules/     # Data structure modules (21 files)
│   │   ├── shympi/      # MPI domain decomposition (21 files, 21K LOC)
│   │   ├── shyutil/     # Core utilities: grid, basin, I/O (36 files)
│   │   └── shyutilmpi/  # MPI-aware utilities (11 files)
│   ├── tools/
│   │   ├── mesh/        # Mesh generator (C, 45 files)
│   │   ├── grid/        # Grid viewer (C/X11, 60 files)
│   │   ├── shypre/      # Grid preprocessor (6 files)
│   │   ├── shybas/      # Basin elaboration (13 files)
│   │   ├── shyadj/      # Grid regularization (8 files)
│   │   ├── shyelab/     # Output elaboration (30+ files)
│   │   ├── shyplot/     # Plotting (40+ files)
│   │   ├── shynetcdf/   # NetCDF interface (8 files)
│   │   ├── shyparts/    # MPI partitioning (1 file)
│   │   ├── femutil/     # Misc utilities (mixed subdirs)
│   │   ├── postscript/  # PS output library (6 files)
│   │   └── hcbs/        # X11 graphics library (2 files)
│   ├── external/
│   │   ├── gotm/        # GOTM turbulence library (39 F90 files)
│   │   └── sparskit/    # Sparse matrix solvers (9 files)
│   ├── contrib/
│   │   └── ecological/  # AQUABC, BFM, eutrophication, mercury
│   └── obsolete/        # Legacy code (not built)
├── shyfem-ui/           # Python Shiny web interface
│   ├── shyfem_ui/       # Application code (35 .py files, 13K LOC)
│   └── tests/           # Unit + Playwright E2E tests (16 files)
├── testcases/           # Example simulations
│   └── examples/        # Mar Menor, Venice Lagoon
├── docs/                # LaTeX manual + PDF (8.9 MB)
├── bin/                 # 332+ executables and scripts
├── lib/                 # Compiled libraries + Perl/Python modules
├── var/                 # Configuration and utility scripts
├── Makefile             # Root build entry point
├── Rules.make           # Compiler/platform configuration
├── Dockerfile           # Multi-stage build (debian:bookworm)
├── CLAUDE.md            # Project instructions
└── DEVELOPER_GUIDE.md   # Architecture & coding conventions
```

### Library Products

| Library | Purpose |
|---------|---------|
| `libshympi.a` | MPI domain decomposition layer |
| `libshyutil.a` | Core utility functions |
| `libshyutilmpi.a` | MPI-enabled utilities |
| `libshynetcdf.a` | NetCDF I/O bindings |
| `libutil.a` | Generic utilities |
| `libpost.a` | PostScript output |
| `libcalp.a` | CALCOMP plotting |
| `libgrappa.a` | Graphics/color handling |
| `libsparskit.a` | Sparse matrix library |

---

## 3. Core Architecture

### 3.1 Main Program Flow

**Entry point:** `src/shyfem/shyfem.f90` → calls `shyfem_main()`

**Execution sequence** (in `src/shyfem/shyfem_subs.f90`):

```
shyfem_main()
  ├── shyfem_initialize()    # MPI init, read grid/params, allocate arrays
  ├── shyfem_run()           # Main time loop (below)
  └── shyfem_finalize()      # Close files, MPI finalize, timing summary

shyfem_run():
  do while (dtime < dtmax)
    set_timestep()           # Adaptive dt
    do_befor()               # Pre-hydro setup
    copy_uvz()               # Copy to old time level
    sp111()                  # Boundary conditions
    hydro()                  # Solve hydrodynamics (zeta, u, v, w)
    run_scalar()             # Concentration/temp/salinity transport
    turb_closure()           # Turbulence model
    parwaves()               # Parametric waves
    sedi() / submud()        # Sediment transport / fluid mud
    bstress()                # Bottom stress
    renewal_time()           # Residence time
    ecological_module()      # Ecology (BFM/ERSEM)
    lagrange()               # Particle tracking
    handle_offline()         # Offline I/O
    do_after()               # Post-timestep output, checks
  end do
```

### 3.2 Key Computational Routines

| Routine | File | Purpose |
|---------|------|---------|
| `hydro()` | `hydrodynamic.f90:284` | Top-level hydrodynamics driver |
| `hydro_zeta()` | `hydrodynamic.f90:496` | Water level equation assembly (OpenMP) |
| `hydro_vertical()` | `hydrodynamic.f90:1700` | Vertical velocity computation |
| `scal3sh()` | `concentration.f90:576` | Scalar transport shell |
| `conz3d_omp()` | `concentration_omp.f90:65` | OpenMP concentration solver |
| `turb_closure()` | `turbulence.f90` | Turbulence model dispatch |
| `sedi()` | `sedim_admin.f90:160` | Sediment transport driver |
| `lagrange()` | `lagrange_main.f90` | Particle tracking main |

### 3.3 Data Structures

All state data is held in Fortran modules (zero common blocks remain after Phase 4):

**Basin/Grid** (module `basin`):
- `nen3v(3,nel)` — element-to-node connectivity
- `xgv(nkn)`, `ygv(nkn)` — node coordinates
- `hm3v(nkn)` — depth at nodes
- `ipv(nkn)`, `ipev(nel)` — external node/element IDs

**Vertical Structure** (module `levels`):
- `nlv` — number of vertical layers
- `ilhv(nel)`, `ilhkv(nkn)` — max level per element/node
- `hlv(nlv)` — layer depths

**Hydrodynamic State** (module `mod_hydro`):
- `znv(nkn)` — water level
- `ulnv`, `vlnv`, `wlnv` — velocity components by layer
- `difhv`, `difv` — horizontal/vertical diffusivity

**Physics** (module `mod_physical_constants`):
- `pi_dp`, `grav_dp`, `vonkarman`, `stefan_boltzmann`
- `rho_seawater`, `rho_freshwater`, `rho_air`
- `seconds_per_day`, `deg2rad`, `rad2deg`

**Parameters** (module `para`):
- `getpar(name)` / `dgetpar(name)` — runtime parameter access
- `putpar(name, value)` — parameter modification

### 3.4 Defined Modules (46 in src/shyfem/)

Core physics: `mod_shyfem`, `mod_physical_constants`, `semi_implicit`, `stab`, `chezy`
Concentration: `mod_conz`, `mod_subset`
Turbulence: `mod_keps`, `mod_gotm_aux`
Waves: `mod_parwaves`, `mod_ww3`
Sediment: `simple_sediments`, `lgr_sedim_module`
Lagrangian: `mod_lagrange`, `connectivity`
Ice: `ice_global`, `ice_params`, `ice_variables`, `shyice_model`
Solvers: `mod_petsc_global`, `mod_petsc_system`, `mod_zeta_system`, `poisson`
Coupling: `ocean_shyfem` (NUOPC interface)
Admin: `arrays`, `befor_after`, `box`, `box_arrays`, `close`, `extra`, `lines`
OpenMP: `omp_admin`, `mod_subset`
Forcing: `meteo_forcing_module`, `tide`
Other: `mod_bndo`, `mod_bstress`, `mod_nudge`, `mod_renewal_time`, `subqfx`

### 3.5 Utility Modules (60+ in src/utils/)

**MPI**: `shympi`, `shympi_internal`, `shympi_tripple`, `shympi_time`, `shympi_tvd`, `shympi_debug`, `mod_shympi_check`
**Core**: `basin`, `levels`, `grd`, `mod_geom`, `evgeom`, `mod_depth`, `mod_bnd`
**I/O**: `shyfile` (SHY format), `extfile` (EXT), `flxfile` (FLX), `fem_file`, `fem_util`
**Generic**: `para`, `stack`, `queue`, `list`, `mod_connect`, `mod_histo`, `mod_reallocate`
**Time**: `femtime`, `custom_dates`, `iso8601`, `dts`
**Math**: `projection`, `mod_sort`, `nls`, `mod_random`
**Data modules**: `mod_hydro`, `mod_hydro_vel`, `mod_hydro_baro`, `mod_diffusion`, `mod_meteo`, `mod_waves`, `mod_sedim`, `mod_roughness`, `mod_fluidmud`, `mod_nudging`, `mod_layer_thickness`, `mod_area`, `mod_flux`, `mod_system`

---

## 4. Module Inventory

### 4.1 MPI Layer (`src/utils/shympi/`, 21 files)

Domain decomposition based on METIS graph partitioning:

| File | Purpose |
|------|---------|
| `mpi_node.f90` | Main `shympi` module — init, exchange, gather, reduce, global↔local |
| `mpi_node_internal.f90` | Internal collective helpers |
| `mpi_ghost.f90` | Ghost node/element exchange between domains |
| `mpi_tripple.f90` | Triple-point handling (3+ domain boundaries) |
| `mpi_buffer.f90` | Pack/unpack buffers for variable-depth data |
| `mpi_basin.f90` | Basin distribution to partitions |
| `mpi_general.f90` | Sorting, index management |
| `mpi_time.f90` | Time synchronization |
| `mpi_tvd.f90` | TVD scheme for MPI |
| `mpi_debug.f90` | Debug output utilities |
| `mpi_check.f90` | Partition consistency validation |
| `mpi_custom.f90` | Custom partitioning options |
| `mpi_dummy.f90` | Single-processor fallback |
| `shyparts_metis.f90` | METIS interface (weighted by vertical levels) |
| `shyparts_custom.f90` | User-defined partitioning |
| `shyparts_util.f90` | Partition quality checks |
| `shyparts_basutil.f90` | Basin partition utilities |
| `shyparts_dummy.f90` | Single-partition fallback |

**Partition model**: Node-based. Each partition has `nkn_local` (own + ghost), `nkn_unique` (no duplicates), `nkn_inner` (no communication needed). Ghost areas tracked per neighboring domain.

### 4.2 I/O Formats

| Format | Module | Description |
|--------|--------|-------------|
| SHY | `shyfile` | Native binary — header + timestep records (version 13) |
| EXT | `extfile` | Node-based ASCII output (version 8) |
| FLX | `flxfile` | Flux output |
| LGR | `io_lgr` | Lagrangian particle output |
| GRD | `grd` | Grid definition (text) |
| BAS | `basin` | Basin geometry (binary FEM) |
| STR | (custom) | Parameter/configuration (ASCII key=value sections) |
| NetCDF | `shynetcdf` | Optional, via netcdf/netcdff libraries |
| NML | (namelist) | Fortran namelist (GOTM turbulence config) |

### 4.3 Ecological Models (`src/contrib/ecological/`)

| Model | Files | Description |
|-------|-------|-------------|
| AQUABC | 13 | Water quality model (AQUABC II) |
| BFM | 1 stub | Biogeochemical Flux Model (external library) |
| WEUTRO | 11 | Eutrophication module |
| Mercury | 7 | Mercury transport model |

---

## 5. Parallelization

### 5.1 OpenMP

**Pattern**: Subset-based task parallelism (avoids race conditions via independent element coloring):

```fortran
!$OMP PARALLEL
!$OMP SINGLE
do i = 1, subset_num
    do jel = 1, subset_el(i), nchunk
        !$OMP TASK firstprivate(jel,i) shared(...)
        do j = jel, min(jel+nchunk-1, subset_el(i))
            ie = indipendent_subset(j,i)
            ! element computation
        end do
        !$OMP END TASK
    end do
    !$OMP TASKWAIT
end do
!$OMP END SINGLE
!$OMP END PARALLEL
```

**Files with OpenMP directives** (81 directives across 17 files):
- `hydrodynamic.f90` — hydro_zeta element assembly
- `concentration_omp.f90` — scalar transport (elements + nodes)
- `tidef.f90`, `tvd_admin.f90`, `baroclinic.f90` — physics
- `waves_admin.f90`, `sedim_admin.f90` — forcing
- `openmp_admin.f90` — OMP thread management

### 5.2 MPI

**692 MPI-related calls across 51 files.** Key communication points:

| Location | Operation | Frequency |
|----------|-----------|-----------|
| `hydrodynamic.f90:411` | `shympi_exchange_2d_node(znv)` | Per timestep |
| `hydrodynamic.f90:424-427` | Element exchanges (conditional) | Per timestep |
| `concentration.f90:779-781` | Double `shympi_exchange_3d_node` | Per internal step |
| `concentration_omp.f90:297-300` | Quad `shympi_exchange_and_sum_3d_nodes` | Per OMP assembly |

**Scaling** (Mar Menor test, 1152 timesteps):

| Processes | Time | Speedup |
|-----------|------|---------|
| 1 (serial) | 3.17s | 1.0x |
| 2 | 2.46s | 1.3x |
| 4 | 2.15s | 1.5x |
| 8 | 1.86s | 1.7x |

---

## 6. Code Quality Status

### 6.1 Completed Improvements (Phases 1-4)

| Category | Before | After | Phase |
|----------|--------|-------|-------|
| Division-by-zero guards | 3 unguarded | All guarded (hydro, concentration, turbulence) | 1, Safety |
| Stack overflow risk | 3 files | All fixed (allocatable/save or allocatable locals) | 1, Safety |
| `allocate` with `stat=` | Inconsistent | 365+ checked (100%) | 2 |
| `open` with `iostat=` | Inconsistent | All checked (100%) | 2 |
| `open` with `newunit=` | Hardcoded units | All modernized | 2,4 |
| `stop` → `MPI_ABORT` | 205 bare stops | All replaced | 2 |
| GOTO statements | 87 across 14 files | 0 remaining | 4 |
| Physical constants | Hardcoded everywhere | `mod_physical_constants` | 4 |
| `getpar`/`dgetpar` | External declarations | `module para` (163 callers) | 4 |
| Save/data patterns | 246 three-line patterns | Single-line initializers | 4 |
| `implicit none` | 97.7% compliance | 100% (all checked) | Design |
| Common blocks in core | Multiple | 0 in src/shyfem/ | 4 |
| Makefile `.PHONY` | Missing | Added to 68 Makefiles | 4 |
| Legacy build remnants | DOS/Lahey/g77 | Removed | 4 |

### 6.2 Current Quality Metrics

| Metric | Status | Notes |
|--------|--------|-------|
| `implicit none` | 100% | All program units |
| GOTO statements | 0 | Fully eliminated |
| Common blocks (core) | 0 | All in modules; 14 files in tools/obsolete retain legacy blocks |
| Equivalence statements | 2 | Only in PostScript tools (acceptable) |
| Fixed-format files | 61 (5.8%) | Tools/obsolete only; core is 100% free-format |
| Intent declarations | 1,206+ | Good coverage across 50+ files |
| Error handling | Comprehensive | All allocations, I/O operations checked |

### 6.3 Residual Issues

**Common blocks (14 files, tools/legacy only)**:
- `src/tools/femutil/var/femtime.f90` — time management
- `src/contrib/ecological/weutro/weutro_light.f90` — ecological
- `src/tools/shyplot/taylor/taylor.f90` — plotting
- `src/external/sparskit/spk_itaux.f90` — sparse matrix
- 7+ files in `src/obsolete/`

**Hardcoded constants (tools only)**:
- ~10 files in `src/tools/` still define local pi/gravity values
- Core simulation uses `mod_physical_constants` consistently

**Magic numbers**:
- ~50+ physics-related constants in sediment, heat, turbulence routines
- Physics parameters are appropriately hardcoded (documented in comments)
- Numerical tolerances could be consolidated

**Unused variables** (estimated 50-100):
- Not systematically audited; would require `gfortran -Wall -Wunused`
- Known patterns: sequential `eps` reassignments, disabled debug flags

**Large files** (well-structured but complex):
- `sedim_util.f90` (5,400 lines, 72 subroutines)
- `sedim_admin.f90` (5,100 lines, 47 subroutines)
- `icemodel.f90` (3,500 lines)
- `custom_admin.f90` (3,200 lines)
- These contain many small routines; average 80-150 lines/routine

**Dead code**:
- `lagrange_main.f90:823` — `if(.false.) then` block (particle recycling)
- `discharge_flux.f90` — similar disabled code block

---

## 7. Performance Characteristics

### 7.1 Hot Path Analysis

**Tier 1 — Per timestep, per element** (highest impact):
1. `hydro_zeta()` element assembly (hydrodynamic.f90:634-760) — OpenMP parallelized
2. `conz3d_element()` per scalar (concentration_omp.f90) — OpenMP parallelized
3. Turbulence Richardson number (turbulence.f90:188-200) — **SERIAL**

**Tier 2 — Per timestep, per node**:
1. `conz3d_nodes()` vertical solve
2. Vertical velocity computation (hydrodynamic.f90:1756-1889)

**Tier 3 — Per timestep**:
1. MPI ghost exchanges
2. System solve (zeta equation)
3. TVD gradient computation

### 7.2 Optimization Opportunities

| Category | Issue | Location | Impact | Effort |
|----------|-------|----------|--------|--------|
| **MPI** | Double exchange around BC update | concentration.f90:779-781 | Medium (3-5%) | Low |
| **MPI** | Quad exchange could be batched | concentration_omp.f90:297-300 | Low-Med | Medium |
| **OpenMP** | Turbulence loop is serial | turbulence.f90:188-198 | Medium (2-3%) | Low |
| **OpenMP** | PETSc solver path is serial | hydrodynamic.f90:778-813 | Medium | High |
| **Memory** | Large arrays allocated in tasks | concentration_omp.f90:195-204 | Low-Med (1-2%) | Low |
| **Memory** | Strided element access via indirection | concentration_omp.f90:274 | Low-Med | N/A |
| **Redundant** | Uncached getpar() calls | concentration.f90:654-657, explicit.f90:144-147 | Low (1%) | Low |
| **Algorithm** | Redundant vertical loops in hydro_zeta | hydrodynamic.f90:669-676,687-692 | Medium | Medium |
| **Vectorization** | No `pure`/`elemental` annotations | Entire codebase | Low-Med | Medium |
| **Vectorization** | No `!$OMP SIMD` directives | Entire codebase | Low | Low |

### 7.3 Quick Wins

1. **Parallelize turbulence loops** — Add `!$OMP PARALLEL DO` to `do k=1,nkn` in turbulence.f90:188. Risk: LOW.
2. **Cache getpar() in concentration.f90** — Apply `integer, save :: icall = 0` pattern for `adpar`, `aapar`, `itvd`, `itvdv`. Risk: LOW.
3. **Investigate double MPI exchange** — Check if second `shympi_exchange_3d_node(cnv)` in concentration.f90:781 is redundant after BC update. Risk: LOW.
4. **Pre-allocate OMP work arrays** — Move `cn`, `co`, `cdiag`, `clow`, `chigh` allocations out of task region in concentration_omp.f90. Risk: LOW.

---

## 8. Build System

### 8.1 Structure

Recursive GNU Make with 81 Makefiles:

```
Root Makefile → src/Makefile
  ├── src/shyfem/Makefile        # Core engine → shyfem executable
  ├── src/utils/Makefile         # → 5 subdirectory Makefiles
  ├── src/tools/Makefile         # → 11 subdirectory Makefiles
  ├── src/external/Makefile      # → GOTM, sparskit
  └── src/contrib/Makefile       # → ecological models
lib/Makefile                     # Library archives
bin/Makefile                     # Utility compilation
docs/Makefile                    # LaTeX documentation
testcases/Makefile               # Test case setup
```

### 8.2 Configuration (`Rules.make`)

Key build flags:

| Variable | Purpose | Default |
|----------|---------|---------|
| `COMPILER` | Fortran compiler | gfortran |
| `MPI` | Enable MPI build | false |
| `OMP` | Enable OpenMP | true |
| `PARTS` | Partitioner | NONE |
| `NETCDF` | NetCDF support | false |
| `METISDIR` | METIS library path | /usr |

### 8.3 Build Commands

```bash
# Serial build
make fem

# MPI build (must use OpenMPI, not Intel MPI)
PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr

# Clean + rebuild
make clean && make fem
```

### 8.4 Build Issues

| Issue | Severity | Notes |
|-------|----------|-------|
| Sequential recursive make | Low | `recursivemake` script iterates directories sequentially |
| Manual `make depend` | Low | Module dependencies not auto-generated |
| No CI/CD pipeline | Medium | No GitHub Actions or GitLab CI configured |
| Intel MPI incompatible | Known | `mpi.mod` from Intel MPI doesn't work with gfortran |

---

## 9. Tools & Utilities

### 9.1 Tool Suite

| Tool | Language | Executables | Purpose |
|------|----------|-------------|---------|
| **mesh** | C | `mesh`, `exgrd`, `elips` | Unstructured mesh generation |
| **grid** | C | `grid` | X11 interactive grid viewer |
| **shypre** | F90 | `shypre` | Grid → basin preprocessing |
| **shybas** | F90 | `shybas` | Basin elaboration, bathymetry |
| **shyadj** | F90 | `shyadj` | Grid regularization |
| **shyparts** | F90 | `shyparts` | MPI domain partitioning |
| **shyelab** | F90 | `shyelab`, `extelab`, `flxelab`, `lgrelab`, `tselab`, `femelab`, + 8 more | Output file elaboration |
| **shyplot** | F90 | `shyplot` | PostScript plot generation |
| **shynetcdf** | F90 | `nc2fem`, `ts2nc` | NetCDF conversion |
| **postscript** | F77 | (library) | CALCOMP-compatible PS generation |
| **hcbs** | F77 | (library) | X11 graphics routines |
| **femutil** | Mixed | Various | Interpolation, splines, conversion |

### 9.2 Utility Scripts (`bin/`, 332+ files)

- **Data processing**: `gp` (Gnuplot wrapper), `splitcol.pl`, `extractcol.pl`, `average.pl`, `minmax.pl`, `rms.pl`
- **Simulation management**: `femrun`, `fembat`, `fembatch`, `strparse.pl`, `strcheck.pl`
- **File conversion**: `2nc`, `nc_elab`, `unf_*.c` (32/64-bit binary)
- **Grid tools**: `regularize`, `reduce`, `make_regular.pl`, `scal_intp`
- **Development**: `recursivemake`, `mkdp.pl`, `diffs`
- **Installation**: `shyfem_install*.sh`, `shyfem_version.sh`, `check_compiler.sh`

---

## 10. Test Infrastructure

### 10.1 Fortran Test Cases

| Test Case | Location | Grid | Scenarios |
|-----------|----------|------|-----------|
| **Mar Menor** | `testcases/examples/mar_menor/` | Coarse triangular | 43 .str configs |
| **Mar Menor Lagrange** | `testcases/examples/mar_menor_lagrange/` | Same grid | 3 particle tracking configs |
| **Venice Lagoon** | `testcases/examples/venice_lagoon/` | 62-element grid | 2 configs |

**Mar Menor tutorial progression**:
- 00-03: Basic hydrodynamics
- 11-13: Lateral boundary conditions
- 21-23: Coriolis, advection, diffusion
- 31-32: Salinity transport
- 41-43: 3D simulations

**Test execution**: Shell scripts + Makefiles (`make init`, `make run_all`). No automated test framework for core Fortran code.

**Runtime benchmarks** (verified 2026-02-11):
- Serial: 3.14s / 1152 timesteps (Mar Menor)
- MPI 4P: 2.05s / 1152 timesteps — no errors, no NaN

### 10.2 Web UI Tests

| Category | Files | Tests | Framework |
|----------|-------|-------|-----------|
| Unit: services | 7 files | ~80 | pytest + pytest-asyncio |
| Unit: config | 1 file | ~10 | pytest |
| Unit: components | 1 file | ~5 | pytest |
| E2E: browser | 4 files | 94 | Playwright |
| **Total** | **16 files** | **~200** | |

Key test patterns:
- Session-scoped Playwright page (Shiny can't reconnect WebSocket after disconnect)
- Live server fixture (subprocess Shiny server on free port)
- Modal backdrop removal (`.remove()`, not `display:none`)
- `force=True` on clicks (modal backdrops intercept pointer events)

---

## 11. Web UI (shyfem-ui)

### 11.1 Technology Stack

| Layer | Technology |
|-------|-----------|
| Framework | Shiny for Python 1.2+ |
| Themes | Shinyswatch (Bootstrap) |
| Visualization | Plotly 5.24+ (primary), Matplotlib 3.7+ (fallback) |
| Database | SQLAlchemy 2.0+ / SQLite (default) or PostgreSQL |
| Job queue | asyncio (local) or Celery 5.3+ / Redis (server) |
| Config | Pydantic Settings 2.0+ |
| Auth | HTTP Basic (SHA256 hash, timing-safe comparison) |

### 11.2 Pages

| Page | Module | Description |
|------|--------|-------------|
| Dashboard | `home.py` | Project list, quick actions, system status, tutorials |
| Grid Prep | `grid_prep.py` | Convert .grd → .bas via shypre/shybas |
| Partitioning | `partitioning.py` | MPI mesh partitioning via shyparts |
| Simulation | `simulation.py` | STR editor (split/raw/form views), templates, boundary editor |
| Run | `run.py` | Job submission, progress dashboard, timeline, log viewer |
| Post-Process | `postprocess.py` | shyelab interface (10 operation modes) |
| Visualize | `visualize.py` | Interactive Plotly (grid, time series, NetCDF, profiles, transects) |
| Compare | `compare.py` | Side-by-side job comparison, parameter diff |
| Ensemble | `ensemble.py` | Parameter sweep (grid/zip modes), envelope plots |

### 11.3 Components

| Component | Purpose |
|-----------|---------|
| `boundary_editor.py` | Boundary condition cards, CSV import |
| `file_browser.py` | File picker widget |
| `grid_map.py` | deck.gl interactive mesh with depth coloring, layer legend, screenshot |
| `job_status.py` | Job status badges, duration formatting |
| `log_viewer.py` | Real-time log streaming with search |
| `plot_widget.py` | Matplotlib embedding with colorbar |
| `str_editor.py` | STR file editor (split/raw/form views, validation) |
| `timeseries.py` | Time series plotting with statistics |

### 11.4 Job Management

Two implementations of abstract `JobQueue`:
- **LocalJobQueue** — asyncio-based, semaphore concurrency control, in-process
- **CeleryJobQueue** — Redis-backed, distributed workers

Job lifecycle: `PENDING → QUEUED → RUNNING → COMPLETED/FAILED`

Features: progress callbacks, output streaming, database persistence, session isolation, workflow chaining (multi-step automation).

### 11.5 Security

- HTTP Basic Auth (optional, SHA256 + `hmac.compare_digest`)
- Path validation (symlink resolution, null-byte rejection, allowed roots)
- Subprocess execution via explicit args list (no `shell=True`)
- HTML escaping with `quote=True`; log line truncation at 4096 chars
- SQLAlchemy ORM (prevents SQL injection)
- Rate limiting (configurable RPM)

### 11.6 Deployment

**Docker**: Multi-stage build (python:3.12-slim), non-root user, health check
**Compose profiles**: Default (local) vs `server` (adds Redis + Celery worker)
**Configuration**: 20+ environment variables prefixed `SHYFEM_UI_`

---

## 12. External Dependencies

### 12.1 Bundled Libraries

| Library | Location | Purpose | License |
|---------|----------|---------|---------|
| GOTM v4.0.0 | `src/external/gotm/` | Turbulence closure (k-ε, k-ω, etc.) | GPL |
| SPARSKIT | `src/external/sparskit/` | Sparse matrix iterative solvers | Public domain |
| Triangle | `src/tools/mesh/` | Delaunay triangulation (C) | Custom |

### 12.2 Optional External Libraries

| Library | Purpose | Build Flag |
|---------|---------|-----------|
| METIS (libmetis-dev) | Graph partitioning for MPI | `PARTS=METIS` |
| NetCDF (libnetcdf-dev) | NetCDF I/O | `NETCDF=true` |
| PETSc | Parallel sparse solver | `SOLVER=PETSC` |
| Paralution | GPU linear solver | Custom integration |
| BFM | Biogeochemical ecology | External |
| X11 (libx11-dev, libxt-dev) | Grid viewer | Always linked |

### 12.3 Obsolete Code (`src/obsolete/`)

| Directory | Contents | Recommendation |
|-----------|----------|----------------|
| `fem3d/` | Old 3D code | Archive/remove |
| `femersem/` | Old BFM coupling (bfm-2.5e) | Archive/remove |
| `femgotm/` | Old GOTM coupling | Archive/remove (replaced by src/external/gotm/) |
| `femdummy/` | Placeholder stubs | Archive/remove |
| `old_util/` | Previous MPI/utility versions | Archive/remove |
| `old_var/` | Old variable definitions | Archive/remove |

Estimated 500+ files that are no longer built or referenced.

---

## 13. Remaining Issues & Recommendations

### 13.1 High Priority

| # | Issue | Category | Effort | Impact |
|---|-------|----------|--------|--------|
| 1 | **Add CI/CD pipeline** — GitHub Actions for automated build/test on each commit | Infrastructure | Medium | High |
| 2 | **Parallelize turbulence loops** — `!$OMP PARALLEL DO` for Richardson number calculation | Performance | Low | Medium |
| 3 | **Investigate double MPI exchange** in concentration.f90:779-781 | Performance | Low | Medium |
| 4 | **Enable Playwright tests in CI** — 94 browser tests currently skipped | Testing | Low | Medium |
| 5 | **Fix Dockerfile** — references deleted `requirements.txt` | Deployment | Low | Low |

### 13.2 Medium Priority

| # | Issue | Category | Effort | Impact |
|---|-------|----------|--------|--------|
| 6 | Remove obsolete code (`src/obsolete/`, 500+ files) | Cleanup | Low | Low |
| 7 | Cache remaining uncached getpar() calls | Performance | Low | Low |
| 8 | Audit unused variables (`gfortran -Wall -Wunused`) | Quality | Medium | Low |
| 9 | Add unit tests for UI page logic (0% coverage) | Testing | High | Medium |
| 10 | Fix 77 ruff linting issues in shyfem-ui | Quality | Low | Low |
| 11 | Remove dead code blocks (`if(.false.)`) | Cleanup | Low | Low |
| 12 | Pre-allocate OMP working arrays in concentration_omp.f90 | Performance | Low | Low |

### 13.3 Long-Term

| # | Issue | Category | Effort | Impact |
|---|-------|----------|--------|--------|
| 13 | Migrate build to CMake for cross-platform support | Build | Very High | Medium |
| 14 | Add Alembic database migrations for UI | UI | Medium | Low |
| 15 | Batch triple-point MPI exchanges | Performance | High | Low |
| 16 | Add `pure`/`elemental`/`contiguous` annotations for vectorization | Performance | High | Low-Med |
| 17 | Add `only` clauses to bare `use` statements (721 occurrences) | Quality | Very High | Low |
| 18 | Convert remaining 61 fixed-format .f files to .f90 | Quality | Medium | Low |

---

## 14. Implementation History

### Phase 1: Critical Bugs (PR #1, 2026-02-04)
- Division-by-zero guards: turbulence.f90, explicit.f90, wetdry.f90
- waves_admin.f90: identical if/else branch fixed + iostat added
- concentration.f90: stack arrays → allocatable
- Dockerfile: debian:bookworm + multi-stage build

### Phase 2: Safety & Correctness (PRs #2-3, 2026-02-05)
- `stat=` on all allocations (365+ calls)
- `stop` → `MPI_ABORT` (205 occurrences)
- `iostat=` on all open() calls
- MPI min/max routines in mpi_buffer.f90

### Phase 3: Performance (PR #4, 2026-02-06)
- Ghost exchange barriers: 11 → 2
- getpar caching in hot paths (hydro_zeta, setweg, setuvd, stability)
- METIS weighted partitioning by vertical levels
- Tridiagonal arrays: dynamic sizing (removed MaxNmx=500 limit)
- OpenMP task parallelism in hydro_zeta (subset-based)

### Phase 4: Code Quality (PR #5, 254 files, 2026-02-11)
- Physical constants module (`mod_physical_constants`)
- `newunit=` for all file I/O
- Intent declarations on subroutine arguments
- Debug cleanup (hardcoded flags removed)
- Removed 87 GOTOs from 14 files (structured control flow)
- Moved getpar/dgetpar into `module para` (163 caller files updated)
- Modernized 246 save/data statements to single-line initializers (36 files)
- Added .PHONY to 68 Makefiles
- Removed DOS/Lahey/g77 build remnants

### Phases 5-8: Web UI (PRs #6-8, 2026-02-11 to 2026-02-13)
- Shiny for Python web application (9 pages, 8 components)
- Job queue (local asyncio + Celery/Redis)
- Interactive visualization (Plotly)
- Authentication, configuration, database persistence
- 94 Playwright browser tests + unit tests

### Phases 9-10: Optimization (2026-02-21)
- Compiler flags: `-O2` default, SPEED profile with `-march=native -funroll-loops -ftree-vectorize`
- `!$OMP SIMD` on vertical loops in hydrodynamic.f90, turbulence.f90
- OpenMP `PARALLEL DO` on density, depth, friction, diffusivity, turbulence loops
- Profile-Guided Optimization (PGO) build profiles
- Hybrid MPI+OpenMP support (removed incompatibility guard)
- Allocation caching in hydro_vertical (~4MB/timestep) and conz3d_omp (~10MB/timestep)
- PETSc solver support (`bin/shyfem-petsc`)

### Safety & Security Audit (PR #7, 2026-04-05)
Deep codebase review (75 findings from 7 parallel agents), 12 fix tasks:
- **Fortran:** Race condition in baroclinic OMP tasks, division-by-zero guards (hydro + concentration), stack overflow fixes (turbulence.f90, concentration_omp.f90), `stop` inside OMP regions replaced with error flags
- **Python UI:** CSRF protection, Secure cookie flag, password min 8, default creds removed, tool allowlist, WS auth bypass restricted, path traversal prevention, swallowed error logging
- **Build system:** `.IGNORE` removal, `MPI_TARGET` fix, `SHYFEMDIR` fallback, `-std=f95` dropped, Intel flag fixes, Makefile dependency additions

### Runtime Verification (2026-04-05)
- Mar Menor test: serial 2.78s, MPI 4P 1.67s
- All timesteps complete, no errors, no NaN
- Python tests: 58/58 auth tests pass, 37/37 admin tests pass
