# Phase 6 Optimization Design — Hybrid MPI+OpenMP, Allocation Caching & MPI Fusion

**Date**: 2026-02-21
**Status**: Proposed
**Approach**: Quick wins + MPI investigation + hybrid parallelism

## Context

Phase 3 (2026-02-06) applied algorithmic optimizations (ghost barrier reduction, getpar caching, METIS weighting, OpenMP tasks). Phase 5 (2026-02-21) applied compiler flags (`-O2`/`-O3 -march=native`), allocation caching in `explicit.f90`, and `!$OMP SIMD` directives.

This proposal targets the next layer: enabling hybrid MPI+OpenMP, caching remaining per-timestep allocations, investigating duplicate MPI exchanges, and adding thread parallelism to the turbulence solver.

### Current Timestep Breakdown (serial)

| Component | Time | Status |
|-----------|------|--------|
| `hydro_zeta` (matrix assembly) | ~21% | OpenMP task-parallel |
| `system_solve` (linear solver) | ~16% | Sequential Penta solver |
| Concentration solver | ~16% | OpenMP parallel, 2 MPI exchanges/substep |
| Turbulence models | ~13% | Sequential node loop |
| Explicit terms | ~10% | Allocation cached (Phase 5) |
| Transport/vertical/misc | ~24% | Various |

## Change 1: Enable Hybrid MPI+OpenMP

**Files**: `Rules.make`, `src/utils/shympi/mpi_node_internal.f90`

### Current State

The build system blocks hybrid mode at `Rules.make:479-483`:
```makefile
ifeq ($(PARALLEL_MPI),NODE)
  ifeq ($(PARALLEL_OMP),true)
    RULES_MAKE_PARAMETERS = RULES_MAKE_PARAMETER_ERROR
    RULES_MAKE_MESSAGE = "OMP and MPI parallelization are incompatible"
  endif
```

MPI is initialized with `MPI_THREAD_SERIALIZED` at `mpi_node_internal.f90:213`. The MPI layer has 7 pairs of `!$OMP CRITICAL` guards that are commented out (`!ccgguccc` prefix).

### Safety Analysis

Investigation confirms the codebase already follows the `MPI_THREAD_FUNNELED` pattern:
- **All MPI calls are outside `!$OMP PARALLEL` regions** — verified in `hydrodynamic.f90`, `concentration_omp.f90`, and all other OpenMP-using files
- **Ghost exchanges happen after `!$OMP TASKWAIT` barriers** — the independent subset pattern ensures synchronization before MPI access
- **No MPI calls exist inside `!$OMP TASK` blocks**
- Only the master thread calls MPI functions

### Proposed Changes

1. **`mpi_node_internal.f90:213`**: Change `MPI_THREAD_SERIALIZED` → `MPI_THREAD_FUNNELED`
2. **`Rules.make:479-483`**: Remove the incompatibility check (allow `PARALLEL_OMP=true` with `PARALLEL_MPI=NODE`)
3. **`mpi_node_internal.f90`**: Restore `!$OMP CRITICAL` guards at 7 locations (defensive — prevents issues if MPI is ever called near OpenMP regions in future code)

**Risk**: Low. The code already follows the funneled pattern. `MPI_THREAD_FUNNELED` is less restrictive than `SERIALIZED`.

**Expected benefit**: Unlocks OpenMP parallelism for turbulence, concentration, and hydro_zeta within each MPI rank.

## Change 2: Cache Remaining Per-Timestep Allocations

**Files**: `src/shyfem/hydrodynamic.f90`, `src/shyfem/concentration_omp.f90`

### Current State

Two subroutines allocate large work arrays on every call:

| Subroutine | File | Arrays | Size (50 levels, 10k nodes) |
|------------|------|--------|----|
| `hydro_vertical` | hydrodynamic.f90:1787 | `vf(nlvdi,nkn)`, `va(nlvdi,nkn)` | ~4MB |
| `conz3d_omp` | concentration_omp.f90:195-203 | `cn`, `co`, `cdiag`, `clow`, `chigh` (all `nlvddi,nkn`) | ~10MB |

### Proposed Changes

Convert from local `allocatable` to `allocatable, save` with lazy initialization (identical pattern to Phase 5):

```fortran
! Before:
real, allocatable :: vf(:,:)
allocate(vf(nlvdi,nkn), stat=ierr)
...
deallocate(vf)

! After:
real, allocatable, save :: vf(:,:)
if (.not. allocated(vf)) then
    allocate(vf(nlvdi,nkn), stat=ierr)
    if (ierr /= 0) stop 'error stop: allocation failed'
end if
```

Remove corresponding `deallocate` calls.

**Risk**: Very low. Arrays are zeroed before use. Identical pattern to 5 arrays already cached in Phase 5.

**Expected speedup**: 2-5% on large meshes (eliminates ~14MB of allocation/deallocation traffic per timestep).

## Change 3: Investigate Duplicate MPI Exchanges in Concentration

**File**: `src/shyfem/concentration.f90`

### Current State

Inside the concentration substep loop (`istot` iterations, typically 2-5):

```fortran
do isact=1,istot
  call conz3d_omp(...)
  call shympi_exchange_3d_node(cnv)    ! Exchange #1: after solver
  call bndo_setbc(...)                  ! Set boundary conditions
  call shympi_exchange_3d_node(cnv)    ! Exchange #2: after BC
end do
```

Two MPI exchanges per substep. The second propagates boundary condition values into ghost nodes.

### Proposed Investigation

1. Read `bndo_setbc` to determine whether it modifies ghost-region nodes
2. If boundary nodes don't overlap ghost regions (typical in well-partitioned domains), the second exchange is redundant
3. If redundant: remove it. If needed for edge cases: keep both with explanatory comment.

### Verification

Run MPI tests at 1, 2, 4, and 8 ranks comparing output with and without the second exchange. Results must be bit-identical.

**Risk**: Medium. Requires understanding boundary-ghost interaction.

**Expected speedup**: 0-7% of concentration solver time (if one exchange is removable, saves `istot` MPI synchronizations per timestep per scalar).

## Change 4: Add OpenMP PARALLEL DO to Turbulence Node Loop

**File**: `src/shyfem/turbulence.f90`

### Current State

The main turbulence dispatch loops iterate over all nodes sequentially:

```fortran
do k=1,nkn
  lmax = ilhkv(k)
  ... compute turbulent closure per water column ...
  do l=flev,nlev-1
    ... vertical solve (independent per node) ...
  end do
end do
```

Each node's vertical column is completely independent — no data dependencies between nodes.

### Proposed Changes

Add `!$OMP PARALLEL DO` with appropriate private/shared clauses to the `do k=1,nkn` loops in:
- `munk_anderson_shell` (Munk-Anderson closure)
- `gotm_shell` (GOTM turbulence model)
- k-epsilon solver routines

```fortran
!$OMP PARALLEL DO PRIVATE(k,lmax,flev,nlev,...) SCHEDULE(DYNAMIC)
do k=1,nkn
  ... independent vertical column computation ...
end do
!$OMP END PARALLEL DO
```

`SCHEDULE(DYNAMIC)` handles varying column heights (coastal nodes have fewer levels than deep-water nodes).

**Prerequisite**: Change 1 (hybrid mode enabled). Without it, OpenMP threads won't spawn in MPI builds.

**Risk**: Low. Node columns are independent. Private variables are local scalars and small vertical arrays. Shared arrays (`visv`, `difv`, `buoyf2`, `shearf2`) are written at unique `(l,k)` indices with no write conflicts.

**Expected speedup**: 3-4% overall (turbulence is 13% of timestep; 2-4x speedup with threading yields ~9% of that 13%).

## Verification Plan

### Correctness

1. **Baseline**: Run mar_menor with current build, save output
2. **Hybrid build**: `make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr`
3. **Allocation caching**: Must produce bit-identical results vs baseline
4. **MPI exchange investigation**: Compare 1P, 2P, 4P, 8P results with and without second exchange
5. **Turbulence OpenMP**: Verify results match serial within floating-point tolerance

### Benchmarking

- **Test case**: mar_menor (1152 timesteps)
- **Matrix**:

| Build | Config | MPI Ranks | OMP Threads |
|-------|--------|-----------|-------------|
| Baseline | NORMAL, MPI only | 1, 4 | 1 |
| Hybrid | NORMAL, MPI+OMP | 4 | 1, 2, 4 |
| Hybrid SPEED | SPEED, MPI+OMP | 4 | 1, 2, 4 |

### Rollback

Each change is independent:
- Hybrid mode: revert `Rules.make` + `mpi_node_internal.f90`
- Allocation caching: revert `hydrodynamic.f90` + `concentration_omp.f90`
- MPI exchange: revert `concentration.f90`
- Turbulence OpenMP: remove `!$OMP PARALLEL DO` directives

## Summary

| Change | Files | Risk | Expected Speedup |
|--------|-------|------|-----------------|
| Enable hybrid MPI+OpenMP | `Rules.make`, `mpi_node_internal.f90` | Low | Enables threading |
| Cache `vf`/`va` in hydro_vertical | `hydrodynamic.f90` | Very low | 1-2% |
| Cache 5 arrays in conz3d_omp | `concentration_omp.f90` | Very low | 1-3% |
| Remove duplicate MPI exchange | `concentration.f90` | Medium | 0-7% |
| Turbulence `!$OMP PARALLEL DO` | `turbulence.f90` | Low | 3-4% |

**Combined estimated speedup**: 5-15% depending on mesh size and core count.
