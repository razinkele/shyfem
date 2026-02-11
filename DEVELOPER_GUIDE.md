# SHYFEM Developer Guide

**Project:** SHYFEM (System of HydroDYnamic Finite Element Modules) v8.1.1
**Last Updated:** 2026-02-11

This guide provides a comprehensive overview of the SHYFEM codebase for developers who want to understand, maintain, or extend the model.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Architecture Overview](#3-architecture-overview)
4. [Core Modules Reference](#4-core-modules-reference)
5. [Data Structures](#5-data-structures)
6. [Build System](#6-build-system)
7. [Parallelization](#7-parallelization)
8. [Extending SHYFEM](#8-extending-shyfem)
9. [Testing](#9-testing)
10. [Code Style Guidelines](#10-code-style-guidelines)
11. [Recent Improvements](#11-recent-improvements)

---

## 1. Project Overview

SHYFEM is a finite element hydrodynamic model for lagoons, coastal seas, estuaries, and lakes. Key characteristics:

- **Numerical Method:** Unstructured triangular finite elements
- **Time Integration:** Semi-implicit scheme (explicit for advection, implicit for barotropic terms)
- **Coordinate System:** Z-layers for vertical discretization
- **Primary Languages:** Fortran 90/95+ (~1,087 files), C (~285 files)
- **Build System:** GNU Make with recursive Makefiles
- **Parallelization:** MPI (domain decomposition) + OpenMP (task-based)

### Capabilities

| Feature | Module | Status |
|---------|--------|--------|
| 2D/3D Hydrodynamics | `hydrodynamic.f90` | Production |
| Baroclinic dynamics | `baroclinic.f90` | Production |
| Turbulence closure | `turbulence.f90`, `kepsilon.f90` | Production |
| Wet-dry processes | `wetdry.f90` | Production |
| Scalar transport | `concentration.f90` | Production |
| Lagrangian particles | `lagrange_*.f90` | Serial only |
| Sediment transport | `sedim_admin.f90` | Experimental |
| Waves (WWMIII) | `ww3.f90`, `waves_*.f90` | Production |
| Ecological models | `src/contrib/ecological/` | BFM, EUTRO |
| MPI parallelization | `src/utils/shympi/` | Production |
| OpenMP parallelization | `concentration_omp.f90` | Production |

---

## 2. Directory Structure

```
shyfem/
├── bin/                    # Executables and helper scripts
│   ├── shyfem             # Main executable (after build)
│   └── fem3d/             # Additional binary tools
├── docs/                   # LaTeX documentation source
│   └── shyfem_manual.pdf  # User manual
├── include/               # Fortran include files (.h)
├── lib/                   # Compiled libraries
│   ├── mod/              # Compiled Fortran modules (.mod)
│   └── *.a               # Static libraries
├── src/                   # Source code
│   ├── shyfem/           # Main model (135 files) [CORE]
│   ├── utils/            # Utility libraries
│   │   ├── generic/      # Self-sufficient utilities
│   │   ├── modules/      # Module definitions
│   │   ├── shympi/       # MPI implementation (18 files)
│   │   ├── shyutil/      # Basic functionality (basin, levels)
│   │   └── shyutilmpi/   # MPI-dependent utilities
│   ├── tools/            # Preprocessing/postprocessing tools
│   │   ├── shybas/       # Basin file utilities
│   │   ├── shyelab/      # Output elaboration
│   │   ├── shynetcdf/    # NetCDF interface
│   │   ├── shyparts/     # MPI partitioning
│   │   ├── shyplot/      # Plotting routines
│   │   ├── shypre/       # Preprocessor (.grd -> .bas)
│   │   ├── mesh/         # Mesh generator
│   │   └── grid/         # Grid visualization
│   ├── contrib/          # Contributed components
│   │   └── ecological/   # BFM, EUTRO models
│   └── external/         # Third-party code
│       ├── gotm/         # GOTM turbulence library
│       └── sparskit/     # Sparse matrix solvers
├── testcases/            # Test cases and validation
├── Rules.make            # Compiler configuration
├── Makefile              # Top-level build
├── CODEBASE_ANALYSIS.md  # Bug/issue analysis
└── DEVELOPER_GUIDE.md    # This file
```

---

## 3. Architecture Overview

### 3.1 Main Program Flow

```
shyfem.f90 (main)
    │
    ├── shyfem_init()          [shyfem_subs.f90]
    │   ├── nlsh2d()           Read STR file parameters
    │   ├── sp136()            Setup mesh/basin
    │   ├── sp111()            Allocate arrays
    │   └── shympi_init()      Initialize MPI
    │
    ├── shyfem_run()           [shyfem_subs.f90] -- MAIN TIME LOOP
    │   │
    │   └── do while (not finished)
    │       ├── timestep()     Advance time
    │       ├── cstsetup()     Stability check
    │       │
    │       ├── meteo_forcing() Wind/pressure forcing
    │       │
    │       ├── hydro()        [hydrodynamic.f90]
    │       │   ├── hydro_zeta()        Solve water levels
    │       │   │   └── hydro_intern()  Element assembly
    │       │   ├── hydro_3d()          3D velocities
    │       │   └── hydro_transports()  Volume fluxes
    │       │
    │       ├── barocl()       [baroclinic.f90]
    │       │   └── rhoset_shell()  Density iterations
    │       │
    │       ├── turb_closure() [turbulence.f90]
    │       │   ├── munk_anderson_shell()  M-A closure
    │       │   └── gotm_shell()           GOTM closure
    │       │
    │       ├── conzstep()     [concentration.f90]
    │       │   └── conz3d()   Solve scalar transport
    │       │
    │       ├── lagrange_step() [lagrange_main.f90]
    │       │
    │       └── output/check routines
    │
    └── shyfem_finalize()
```

### 3.2 Key Computational Kernels

| Kernel | File | Description | Parallelization |
|--------|------|-------------|-----------------|
| `hydro_zeta` | hydrodynamic.f90:~550 | Water level solver | OpenMP tasks |
| `hydro_intern` | hydrodynamic.f90:~800 | Element matrix assembly | Called per-element |
| `conz3d` | concentration.f90:~900 | Scalar transport | OpenMP tasks |
| `rhoset_shell` | baroclinic.f90:~580 | Density-pressure coupling | Serial |
| `munk_anderson` | turbulence.f90:~180 | Vertical mixing | Serial (per-column) |
| `keps` | kepsilon.f90:~270 | k-epsilon closure | Serial (per-column) |

### 3.3 Module Dependencies

```
                    ┌─────────────────────────────────────┐
                    │          mod_shympi                 │
                    │     (MPI communication layer)       │
                    └──────────────┬──────────────────────┘
                                   │
           ┌───────────────────────┼───────────────────────┐
           │                       │                       │
    ┌──────▼──────┐         ┌──────▼──────┐         ┌──────▼──────┐
    │  mod_basin  │         │ mod_levels  │         │ mod_geom    │
    │ (mesh data) │         │ (vertical)  │         │ (geometry)  │
    └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
           │                       │                       │
           └───────────────────────┼───────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         mod_hydro                   │
                    │    (hydrodynamic variables)         │
                    │   znv, zenv, utlnv, vtlnv, etc.    │
                    └──────────────┬──────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
 ┌──────▼──────┐           ┌───────▼───────┐          ┌───────▼───────┐
 │ mod_ts      │           │ mod_conz      │          │ mod_layer     │
 │ (T, S)      │           │ (tracers)     │          │ (interfaces)  │
 └─────────────┘           └───────────────┘          └───────────────┘
```

---

## 4. Core Modules Reference

### 4.1 Main Model Files (`src/shyfem/`)

| File | Purpose | Key Routines |
|------|---------|--------------|
| `shyfem.f90` | Program entry point | `shyfem` |
| `shyfem_subs.f90` | Main time loop | `shyfem_init`, `shyfem_run`, `shyfem_finalize` |
| `hydrodynamic.f90` | Momentum/continuity | `hydro`, `hydro_zeta`, `hydro_intern` |
| `explicit.f90` | Explicit advection | `set_advective`, `uvadv` |
| `concentration.f90` | Scalar transport | `conz3d`, `scal3sh` |
| `concentration_omp.f90` | OpenMP transport | `conz3d_omp` |
| `baroclinic.f90` | Density effects | `barocl`, `rhoset_shell`, `set_barocl_new` |
| `turbulence.f90` | Vertical mixing | `turb_closure`, `munk_anderson_shell` |
| `kepsilon.f90` | k-epsilon closure | `keps`, `kepsin` |
| `wetdry.f90` | Wetting/drying | `setweg`, `setznv`, `setuvd` |
| `stability.f90` | CFL conditions | `hydro_internal_stability`, `scalar_compute_stability` |
| `timestep.f90` | Time stepping | `set_timestep`, `get_timestep` |
| `mod_hydro.f90` | State variables | Module with `znv`, `utlnv`, `vtlnv`, etc. |
| `mod_ts.f90` | T/S fields | Module with `tempv`, `saltv` |
| `mod_conz.f90` | Tracer fields | Module with `cnv` |

### 4.2 MPI Layer (`src/utils/shympi/`)

| File | Purpose | Key Routines |
|------|---------|--------------|
| `mpi_node.f90` | Main MPI interface | `shympi_init`, `shympi_finalize` |
| `mpi_node_internal.f90` | Internal exchange | `shympi_exchange_internal` |
| `mpi_ghost.f90` | Ghost zone updates | `ghost_exchange`, `ghost_handle` |
| `mpi_buffer.f90` | Buffer operations | `sum_from_buffer`, `min/max_from_buffer` |
| `mpi_tripple.f90` | Triple-point handling | `tripple_points_exchange` |
| `shyparts_metis.f90` | METIS partitioning | `shyparts_metis_partition` |

### 4.3 Physical Constants (`src/shyfem/mod_physical_constants.f90`)

```fortran
module mod_physical_constants
  implicit none

  ! Mathematical constants
  double precision, parameter :: pi_dp = 3.14159265358979323846d0
  real, parameter :: pi_sp = 3.14159265358979
  double precision, parameter :: twopi = 6.28318530717958647692d0
  double precision, parameter :: halfpi = 1.57079632679489661923d0
  double precision, parameter :: deg2rad = 0.01745329251994329577d0
  double precision, parameter :: rad2deg = 57.29577951308232087680d0

  ! Physical constants
  double precision, parameter :: grav_dp = 9.81d0
  real, parameter :: grav_sp = 9.81
  double precision, parameter :: vonkarman = 0.4d0
  double precision, parameter :: stefan_boltzmann = 5.670374419d-8

  ! Time constants
  double precision, parameter :: seconds_per_day = 86400.d0
  double precision, parameter :: seconds_per_hour = 3600.d0

  ! Density references
  double precision, parameter :: rho_seawater = 1025.d0
  double precision, parameter :: rho_freshwater = 1000.d0
  double precision, parameter :: rho_air = 1.225d0
end module
```

---

## 5. Data Structures

### 5.1 Mesh Data (`mod_basin`)

```fortran
! Nodes
integer :: nkn                    ! Number of nodes
real :: xgv(nkn), ygv(nkn)       ! Node coordinates
real :: hkv(nkn)                  ! Depth at nodes

! Elements
integer :: nel                    ! Number of elements
integer :: nen3v(3,nel)          ! Element-node connectivity
integer :: ipev(nel)             ! Element external number
real :: hm3v(3,nel)              ! Depth at element vertices

! Levels
integer :: nlv                    ! Number of vertical levels
integer :: ilhkv(nkn)            ! Levels at each node
integer :: ilhv(nel)             ! Levels at each element
real :: hlv(nlv)                 ! Layer thicknesses
```

### 5.2 Hydrodynamic Variables (`mod_hydro`)

```fortran
! 2D fields (per node)
real :: znv(nkn)                  ! Water level
real :: zenv(3,nel)               ! Water level at element vertices

! 3D fields (per layer, per node/element)
real :: utlnv(nlv,nel)            ! Transport velocity U
real :: vtlnv(nlv,nel)            ! Transport velocity V
real :: wlnv(0:nlv,nkn)           ! Vertical velocity W

! Layer geometry
real :: hdknv(nlv,nkn)            ! Layer thickness at nodes
real :: hdeov(nlv,nel)            ! Layer thickness at elements
```

### 5.3 Scalar Fields (`mod_ts`, `mod_conz`)

```fortran
! Temperature and salinity
real :: tempv(nlv,nkn)            ! Temperature
real :: saltv(nlv,nkn)            ! Salinity
real :: rhov(nlv,nkn)             ! Density anomaly

! Generic tracers
real :: cnv(nlv,nkn,ntr)          ! Tracer concentrations
```

### 5.4 MPI Domain Decomposition

```fortran
! Partition information (mod_shympi)
integer :: n_threads              ! Number of MPI ranks
integer :: my_id                  ! This rank's ID (0-based)
integer :: nkn_local              ! Local nodes (owned + ghost)
integer :: nkn_inner              ! Local nodes (owned only)
integer :: nel_local              ! Local elements
integer :: nel_inner              ! Local elements (no ghost)

! Ghost zones
integer :: nghost                 ! Number of ghost nodes
integer :: ghost_nodes(nghost)    ! Ghost node indices
integer :: ghost_source(nghost)   ! Source rank for each ghost
```

---

## 6. Build System

### 6.1 Quick Start

```bash
# Full build
make fem

# Build with MPI
make fem PARALLEL=MPI

# Build with OpenMP
make fem PARALLEL=OMP

# Clean build
make cleanall && make fem

# Build specific tool
cd src/tools/shyelab && make
```

### 6.2 Key Makefiles

| File | Purpose |
|------|---------|
| `Makefile` | Top-level orchestration |
| `Rules.make` | Compiler flags, library paths |
| `src/shyfem/Makefile` | Main model build |
| `src/utils/*/Makefile` | Utility library builds |

### 6.3 Compiler Configuration (`Rules.make`)

Key variables:
```makefile
# Fortran compiler
FORTRAN_COMPILER = GFORTRAN   # or INTEL

# Parallelization
PARALLEL = NONE               # NONE, OMP, MPI, or MPI_OMP

# External libraries
NETCDF = true                 # Enable NetCDF support
GOTM = true                   # Enable GOTM turbulence
PETSC = false                 # PETSc solver (optional)

# METIS for partitioning (required for MPI)
PARTS = METIS                 # or PARMETIS
METISDIR = /usr               # System METIS location
```

### 6.4 Build Dependencies

```
libgeneric.a
    │
    ├── libmodules.a
    │       │
    │       ├── libshyutil.a
    │       │       │
    │       │       ├── libshympi.a
    │       │       │       │
    │       │       │       └── libshyutilmpi.a
    │       │       │               │
    │       │       │               └── shyfem executable
```

### 6.5 Adding New Source Files

1. Add `.f90` file to appropriate `src/` subdirectory
2. Add to `SRCS` variable in that directory's `Makefile`
3. Run `make depend` to update module dependencies
4. Run `make` to build

---

## 7. Parallelization

### 7.1 MPI Domain Decomposition

SHYFEM uses domain decomposition via METIS or ParMETIS:

1. **Partitioning:** `shyparts` utility partitions mesh into subdomains
2. **Initialization:** Each rank reads its subdomain from partitioned files
3. **Ghost zones:** Overlapping layer of nodes shared between ranks
4. **Communication:** `shympi_exchange_*` routines update ghost values

```fortran
! Example MPI exchange pattern
call shympi_exchange_3d_node(tempv)   ! Exchange temperature
call shympi_barrier()                 ! Synchronize
```

**Running MPI:**
```bash
# Partition mesh (once)
shyparts -n 4 basin.bas

# Run with 4 ranks
mpirun -np 4 shyfem simulation.str
```

### 7.2 OpenMP Task Parallelism

The concentration solver uses subset-based task parallelism:

```fortran
! Pattern from concentration_omp.f90
!$OMP PARALLEL
!$OMP SINGLE
do i = 1, subset_num
    do jel = 1, subset_el(i), nchunk
        !$OMP TASK firstprivate(jel,i) shared(...)
        do j = jel, min(jel+nchunk-1, subset_el(i))
            ie = indipendent_subset(j,i)
            call element_computation(ie, ...)
        end do
        !$OMP END TASK
    end do
    !$OMP TASKWAIT    ! Barrier between subsets
end do
!$OMP END SINGLE
!$OMP END PARALLEL
```

**Element subsets:** Elements are grouped into "independent subsets" where no two elements share a node, allowing parallel assembly without race conditions.

### 7.3 Hybrid MPI+OpenMP

Not recommended due to `MPI_THREAD_SERIALIZED` initialization. Use either MPI or OpenMP, not both simultaneously.

---

## 8. Extending SHYFEM

### 8.1 Adding a New Tracer

1. **Define tracer index** in `mod_conz`:
```fortran
integer, parameter :: itr_mytracer = 10  ! New tracer index
```

2. **Add source term** in `concentration.f90`:
```fortran
subroutine conz_source_mytracer(k, l, source)
    ! Compute source/sink for your tracer
    source = ...
end subroutine
```

3. **Call from main loop** in `shyfem_subs.f90`:
```fortran
call conzstep(itr_mytracer)
```

### 8.2 Adding a New Physical Process

1. **Create module file** in `src/shyfem/`:
```fortran
module mod_myprocess
    implicit none
    real, allocatable :: myvar(:,:)
contains
    subroutine myprocess_init()
        ! Allocate arrays
    end subroutine

    subroutine myprocess_run(dt)
        ! Your physics here
    end subroutine
end module
```

2. **Update Makefile** in `src/shyfem/`:
```makefile
SRCS += mod_myprocess.f90
```

3. **Call from time loop** in `shyfem_subs.f90`:
```fortran
use mod_myprocess
...
call myprocess_init()  ! In shyfem_init
...
call myprocess_run(dt) ! In time loop
```

### 8.3 Adding Runtime Parameters

Parameters are read via `getpar()` from the STR file. `getpar` and `dgetpar` are module functions in `module para`:

```fortran
use para

real :: myparam
myparam = getpar('myparam')  ! Read from STR section
```

STR file:
```
$para
  myparam = 0.5
$end
```

**Performance note:** Cache `getpar()` values in saved variables for parameters called frequently (per-timestep).

---

## 9. Testing

### 9.1 Test Cases

Test cases are in `testcases/`:

```bash
cd testcases/examples/mar_menor
./run.sh
```

### 9.2 Verification Checks

```fortran
! Runtime consistency checks (src/shyfem/check.f90)
call check_fem()           ! Full state verification
call check_special(k,val)  ! Check specific node
```

### 9.3 MPI Verification

```fortran
! MPI array consistency (src/utils/shympi/check_shympi_*.f90)
call shympi_check_2d_node_r(array, 'array_name')
call shympi_check_3d_elem_r(array, 'array_name')
```

---

## 10. Code Style Guidelines

### 10.1 Fortran Style

- **Free-form source** (`.f90` extension)
- **Implicit none** in all program units
- **Intent declarations** on all arguments:
  ```fortran
  subroutine mysub(a, b, result)
      real, intent(in) :: a, b
      real, intent(out) :: result
  ```
- **Modern variable initialization** (not separate `save`/`data` statements):
  ```fortran
  integer, save :: icall = 0
  real, save :: cached_param = 0.0
  ```
- **Module functions** for `getpar`/`dgetpar` (use `use para`, not `real getpar`):
  ```fortran
  use para
  value = getpar('param_name')
  ```
- **Error checking** on allocations:
  ```fortran
  allocate(array(n), stat=ierr)
  if (ierr /= 0) stop 'allocation error'
  ```
- **File I/O** with `newunit=` and `iostat=`:
  ```fortran
  integer :: iu, ierr
  open(newunit=iu, file='data.txt', iostat=ierr, status='old')
  if (ierr /= 0) then
      write(6,*) 'Cannot open file'
      return
  end if
  ```
- **No GOTO statements** -- use `do/exit/cycle`, `if/then/else`, or `select case`
- **`.PHONY` declarations** in all Makefiles for non-file targets

### 10.2 Naming Conventions

| Pattern | Meaning |
|---------|---------|
| `*v` | Per-node variable (e.g., `znv`, `tempv`) |
| `*e` | Per-element variable (e.g., `zenv`) |
| `*nv` | 3D per-node (e.g., `utlnv`) |
| `mod_*` | Module name |
| `*_init` | Initialization routine |
| `*_shell` | Wrapper/driver routine |
| `i*` | Integer parameter/flag |
| `n*` | Count/dimension |

### 10.3 MPI Code

- **Never use bare `stop`** - use `shympi_abort_internal()`
- **Exchange after modification** of shared arrays
- **Check partition type** before element/node loops:
  ```fortran
  if (shympi_partition_on_elements()) then
      ! Element-based loop
  else
      ! Node-based loop
  end if
  ```

---

## 11. Recent Improvements

### 11.1 Bug Fixes (Phase 1)

| Issue | File | Fix |
|-------|------|-----|
| Division by zero in turbulence | `turbulence.f90:197` | Guard `shearf2 > 0` |
| Division by zero in wet-dry | `explicit.f90:757` | `hmin` guard |
| Division by zero in `setznv` | `wetdry.f90:686` | Guard `v2v > 0` |
| Identical if/else branches | `waves_admin.f90` | Removed duplicate |
| Stack overflow in `conz3d` | `concentration.f90:961` | Allocatable arrays |

### 11.2 Safety Improvements (Phase 2)

- **`stat=` on all allocations:** 365+ allocate calls now have error checking
- **`stop` → `MPI_ABORT`:** 205 occurrences in MPI code paths
- **`iostat=` on file I/O:** All `open()` calls have error handling
- **Intent declarations:** ~437 new intent declarations across 19 files

### 11.3 Performance Optimizations (Phase 3)

- **Ghost exchange barriers:** Reduced from 11 to 2 synchronization points
- **`getpar()` caching:** Critical parameters cached in `hydro_zeta`, `setweg`, etc.
- **METIS weighting:** Node weights proportional to vertical levels
- **Automatic arrays:** Tridiagonal solver arrays sized to actual `Nmx`

### 11.4 Code Quality (Phase 4)

- **Physical constants module:** Centralized `pi`, `grav`, etc.
- **`newunit=` for file I/O:** 50+ hardcoded unit numbers replaced
- **Debug artifact cleanup:** ~22 dead `bdebug` assignments removed
- **OpenMP in hydrodynamics:** `hydro_zeta` now parallelized
- **`getpar`/`dgetpar` module interface:** Moved into `module para`; 163 caller files updated to use module instead of external declarations
- **GOTO removal:** 87 GOTOs eliminated from 14 files using structured control flow (`do/exit`, `if/else`, `select case`)
- **`.PHONY` in Makefiles:** Added to 68 Makefiles across the project
- **Save/data modernization:** 246 three-line `save`/`data` patterns converted to single-line initializers across 36 files
- **Build cleanup:** Removed DOS/Lahey/g77 compiler remnants from `Rules.make` and obsolete Makefiles

---

## Appendix A: Quick Reference

### Common Operations

```fortran
! Get runtime parameter
use para
value = getpar('param_name')

! Loop over local elements (MPI-safe)
do ie = 1, nel
    if (.not. shympi_is_inner_elem(ie)) cycle
    ! ... process element
end do

! Exchange 3D nodal array
call shympi_exchange_3d_node(array)

! Check array consistency (debug)
call shympi_check_3d_node_r(array, 'array_name')

! Get node coordinates
call get_coords_node(k, x, y)

! Get element depth
call depele(ie, dep)

! Get layer thickness
h = hdknv(l, k)
```

### Key Include Files

| File | Contents |
|------|----------|
| `param.h` | Array dimension parameters |
| `pkonst.h` | Physical constants (legacy) |

### Useful Debugging

```fortran
! Print at specific node
if (k == 12345) write(6,*) 'debug:', var

! Enable per-routine debugging
logical, save :: bdebug = .false.
if (bdebug) write(6,*) 'routine_name: entering'
```

---

## Appendix B: File Quick Lookup

### By Functionality

| Need | Look In |
|------|---------|
| Main time loop | `src/shyfem/shyfem_subs.f90` |
| Water level solver | `src/shyfem/hydrodynamic.f90:hydro_zeta` |
| 3D velocity | `src/shyfem/hydrodynamic.f90:hydro_3d` |
| Scalar transport | `src/shyfem/concentration.f90:conz3d` |
| Density calculation | `src/shyfem/baroclinic.f90:rhoset_shell` |
| Turbulence mixing | `src/shyfem/turbulence.f90` |
| Wet-dry logic | `src/shyfem/wetdry.f90` |
| MPI communication | `src/utils/shympi/mpi_node.f90` |
| Ghost exchange | `src/utils/shympi/mpi_ghost.f90` |
| Mesh partitioning | `src/utils/shympi/shyparts_metis.f90` |
| Physical constants | `src/shyfem/mod_physical_constants.f90` |
| Runtime parameters | `src/utils/generic/para.f90` (module `para`: `getpar`, `dgetpar`) |

### By Variable

| Variable | Declared In |
|----------|-------------|
| `znv` (water level) | `mod_hydro.f90` |
| `tempv`, `saltv` | `mod_ts.f90` |
| `utlnv`, `vtlnv` | `mod_hydro.f90` |
| `nkn`, `nel` | `mod_basin.f90` |
| `hlv`, `nlv` | `mod_levels.f90` |
| `n_threads`, `my_id` | `mod_shympi.f90` |

---

*For bug reports and detailed issue tracking, see [CODEBASE_ANALYSIS.md](CODEBASE_ANALYSIS.md).*
