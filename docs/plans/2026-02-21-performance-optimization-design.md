# Performance Optimization Design — Compiler, Allocation & Vectorization

**Date**: 2026-02-21
**Status**: Proposed
**Approach**: Conservative (B) — compiler flags + allocation caching + SIMD directives

## Context

Phase 3 (2026-02-06) applied algorithmic optimizations: ghost exchange barrier reduction (11→2), getpar caching, METIS weighted partitioning, OpenMP task parallelism. These yielded ~40% MPI speedup.

This proposal targets the next layer: compiler optimization, memory allocation overhead, and vectorization — all low-risk changes with no algorithmic restructuring.

### Current Performance (mar_menor test, 1152 timesteps)

| Config | Wall Time | Speedup |
|--------|-----------|---------|
| Serial | 3.14s | 1.0x |
| 2 MPI | 2.46s | 1.28x |
| 4 MPI | 2.05s | 1.53x |
| 8 MPI | 1.86s | 1.69x |

### Timestep Breakdown (estimated, serial)

| Component | Time | Notes |
|-----------|------|-------|
| `hydro_zeta` (matrix assembly) | ~21% | OpenMP task-parallel |
| `system_solve` (linear solver) | ~16% | Sequential Penta solver |
| Concentration solver | ~16% | OpenMP parallel, multiple MPI syncs |
| Turbulence models | ~13% | Node loops, sequential vertical solves |
| Explicit terms | ~10% | Per-call allocations of large arrays |
| Transport/vertical/misc | ~24% | Various |

## Change 1: Build System — Production Profile Enhancement

**Files**: `Rules.make`

### Current State

```makefile
# NORMAL profile (default): DEBUG=true, OPTIMIZE=MEDIUM
FGNU_OPT = -O                          # Line 707

# SPEED profile: DEBUG=false, OPTIMIZE=HIGH
FGNU_OPT = -O3                         # Line 709

# FPE traps (enabled when DEBUG=true):
FGNU_NOOPT = -g -fbacktrace -ffpe-trap=zero,invalid,overflow  # Line 704

# Link flags:
LFLAGS = $(FGNU_OPT) $(FGNU_PROFILE) $(FGNU_OMP) -fopenmp     # Line 733
```

**Issues**:
- NORMAL uses `-O` (not `-O2`) — leaves easy optimization on the table
- SPEED uses `-O3` but no `-march=native` — misses CPU-specific SIMD (AVX2/AVX-512)
- No `-funroll-loops` — hurts short vertical loops (20-50 iterations)
- FPE traps in NORMAL completely disable auto-vectorization

### Proposed Changes

1. **NORMAL profile**: `-O` → `-O2` (safe, compatible with FPE traps, ~5-10% faster)
2. **SPEED profile**: Add `-march=native -funroll-loops -ftree-vectorize`
3. No change to CHECK profile (stays at `-O0` with bounds checking)

```makefile
# After changes:
FGNU_OPT = -O2                                    # MEDIUM (was -O)
ifeq ($(OPTIMIZE),HIGH)
  FGNU_OPT = -O3 -march=native -funroll-loops -ftree-vectorize
endif
```

**Risk**: None. `-O2` is standard for production Fortran. `-march=native` only affects SPEED profile which already disables debug.

**Expected speedup**: 15-25% (SPEED), 5-10% (NORMAL)

## Change 2: Allocation Caching in `explicit.f90`

**File**: `src/shyfem/explicit.f90`

### Current State

Three subroutines allocate large work arrays on every call (i.e., every timestep):

| Subroutine | Line | Arrays | Size (50 levels, 10k nodes/elements) |
|------------|------|--------|------|
| `set_momentum_flux` | L640 | `saux(nlvdi,nkn)` | ~4MB |
| `set_barocl_new` | L1057-1059 | `bpresxv(nlv,nel)`, `bpresyv(nlv,nel)` | ~8MB |
| `set_barocl_new_interface` | L1324-1326 | `hkko(0:nlvdi,nkn)`, `hkkom(0:nlvdi,nkn)` | ~8MB |

Each array is zeroed at the start of each call, so reuse is safe. Over a 1000-timestep run, this amounts to ~20,000 `malloc`/`free` calls for multi-MB buffers.

### Proposed Changes

Convert from local `allocatable` to module-level `allocatable, save` with lazy initialization:

```fortran
! Before (current):
real, allocatable :: saux(:,:)
allocate(saux(nlvdi,nkn), stat=ierr)
if (ierr /= 0) stop 'error stop: allocation failed'
saux = 0.

! After (proposed):
real, allocatable, save :: saux(:,:)
if (.not. allocated(saux)) then
    allocate(saux(nlvdi,nkn), stat=ierr)
    if (ierr /= 0) stop 'error stop: allocation failed'
end if
saux = 0.
```

Apply the same pattern to all 3 sites (5 arrays total).

**Risk**: Very low. Arrays are zeroed before use. `save` keeps them allocated for the process lifetime — acceptable since these routines run every timestep anyway.

**Expected speedup**: 2-5% (eliminates ~20GB of allocation/deallocation traffic per 1000 timesteps on large meshes)

## Change 3: SIMD Directives on Vertical Level Loops

**Files**: `src/shyfem/hydrodynamic.f90`, `src/shyfem/concentration_omp.f90`, `src/shyfem/turbulence.f90`

### Current State

~30% of inner loops iterate over vertical levels (`l=1,lmax`, trip count 20-50) and have no vectorization barriers (no indirect indexing, no branches, no data dependencies). But gfortran doesn't auto-vectorize them because:

1. FPE traps disable SIMD entirely in NORMAL profile
2. Dynamic trip counts (`lmax` varies per element/node) discourage compiler
3. No explicit vectorization hints

### Target Loops

Only loops that are clearly safe — no function calls, no indirect indexing, no conditionals:

- `hydrodynamic.f90` L669-676: vertical transport summation in `hydro_zeta`
- `hydrodynamic.f90` L1664-1683: vertical velocity computation in `hydro_vertical`
- `concentration_omp.f90`: vertical level loops inside `conz3d_element`
- `turbulence.f90`: vertical diffusivity/viscosity loops

Estimated ~10-15 candidate loops across the 3-4 files.

### Proposed Changes

Add `!$OMP SIMD` directive (OpenMP 4.0+ standard) before safe vertical loops:

```fortran
! Before:
do l = 1, lmax
    flux = utlnv(l,ie) * b(ii) + vtlnv(l,ie) * c(ii)
    hik_local(ii) = hik_local(ii) + flux
end do

! After:
!$OMP SIMD reduction(+:hik_local_ii)
do l = 1, lmax
    flux = utlnv(l,ie) * b(ii) + vtlnv(l,ie) * c(ii)
    hik_local_ii = hik_local_ii + flux
end do
hik_local(ii) = hik_local_ii
```

**Not touching**: Short 3-node loops (`do ii=1,3`) with indirect indexing — inherently non-vectorizable without data layout restructuring (out of scope).

**Risk**: Very low. `!$OMP SIMD` is a hint, not a mandate — compiler ignores it if unsafe. Only applied to loops verified to have no dependencies.

**Expected speedup**: 5-10% in SPEED profile (where SIMD is enabled). Negligible in NORMAL profile (FPE traps still block SIMD).

## Verification Plan

### Correctness

1. **Baseline**: Run mar_menor with current NORMAL profile, save final output (water levels, velocities)
2. **Bit-reproducibility**: NORMAL (`-O2`) and allocation caching must produce bit-identical results vs baseline
3. **SPEED tolerance**: `-O3 -march=native` may reassociate floating-point ops. Verify relative error < 1e-10 vs baseline
4. **SIMD directives**: Must produce bit-identical results vs same optimization level without directives
5. **MPI consistency**: Verify 1P, 2P, 4P, 8P all produce consistent results

### Benchmarking

- **Test case**: mar_menor (1152 timesteps)
- **Metrics**: Total wall time, per-timestep average
- **Matrix**:

| Build | Flags | MPI Ranks |
|-------|-------|-----------|
| Baseline NORMAL | `-O -g -ffpe-trap` | 1, 4 |
| New NORMAL | `-O2 -g -ffpe-trap` + alloc cache | 1, 4 |
| New SPEED | `-O3 -march=native` + alloc cache + SIMD | 1, 2, 4, 8 |

### Rollback

Each change is independent and can be reverted individually:
- Compiler flags: revert `Rules.make` lines
- Allocation caching: revert `explicit.f90` (3 subroutines)
- SIMD directives: remove `!$OMP SIMD` lines

## Summary

| Change | Files | Risk | Expected Speedup |
|--------|-------|------|-----------------|
| SPEED: `-O3 -march=native -funroll-loops` | `Rules.make` | None | 15-25% |
| NORMAL: `-O` → `-O2` | `Rules.make` | None | 5-10% |
| Cache `saux` allocation | `explicit.f90` | Very low | 2-5% |
| Cache `bpresxv/yv` allocation | `explicit.f90` | Very low | 2-5% |
| Cache `hkko/hkkom` allocation | `explicit.f90` | Very low | 1-3% |
| `!$OMP SIMD` on vertical loops | `hydrodynamic.f90`, `concentration_omp.f90`, `turbulence.f90` | Very low | 5-10% (SPEED only) |

**Combined estimated speedup**: 20-35% (SPEED profile), 5-15% (NORMAL profile)
