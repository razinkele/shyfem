# Phase 9 Optimization Design — OpenMP Parallelization of Density & Depth Loops

**Date**: 2026-02-21
**Status**: Proposed
**Approach**: Add `!$OMP PARALLEL DO` to density computation and layer depth node loops

## Context

Phases 3-8 optimized compiler flags, allocation caching, SIMD directives, hybrid MPI+OpenMP, element/node loop parallelization (chezy, diffusion_admin, turbulence), and PGO build profiles. The remaining per-timestep sequential work includes the equation-of-state density computation and the volume-to-depth node conversion.

## Change 1: Density Computation in baroclinic.f90

**File**: `src/shyfem/baroclinic.f90:711-745`

### Current State

The `rhoset` subroutine iterates over all nodes computing the UNESCO equation of state:

```fortran
nresid = 0
dresid = 0.
do k=1,nkn
  depth = 0.
  presbc = 0.
  lmin = jlhkv(k)
  lmax = ilhkv(k)
  do l=lmin,lmax
    ! compute pressure, call sigma_stp(), update rhov(l,k)
    nresid = nresid + 1
    dresid = dresid + (rhov(l,k)-rhop)**2
    rhov(l,k) = rhop
  end do
end do
resid = dresid/nresid
```

Called every timestep via `rhoset_shell` → `rhoset`.

### Safety Analysis

- `sigma_stp(s,t,p)`: Pure function — uses only local `parameter` constants and scalar arguments. No module state. Thread-safe.
- `set_rhomud(k,l,rhop)`: Empty stub (no-op). Thread-safe.
- Array reads: `rhov(l,k)`, `saltv(l,k)`, `tempv(l,k)`, `hdkov(l,k)`, `hldv(l)` — each `(l,k)` index is unique per outer iteration.
- Array writes: `rhov(l,k)` — unique `(l,k)` per outer iteration.
- Reductions: `nresid` (integer sum), `dresid` (double precision sum).
- All other loop variables are local scalars.

### Proposed Change

```fortran
!$OMP PARALLEL DO PRIVATE(k,l,lmin,lmax,depth,presbc,hlayer,hh,rhop, &
!$OMP&   dpresc,presbt,pres,salt,bsigma) &
!$OMP& REDUCTION(+:nresid,dresid) SCHEDULE(DYNAMIC)
do k=1,nkn
  ...
end do
!$OMP END PARALLEL DO
```

`SCHEDULE(DYNAMIC)` handles varying column depths (coastal vs deep-water nodes).

**Risk**: Very low. Pure computation with standard reductions.

## Change 2: Layer Depth Node Loops in elems_dealing.f90

**File**: `src/shyfem/elems_dealing.f90:1133-1162`

### Current State

After the element loop accumulates volumes into `hdkn`, two node loops convert volumes to depths:

```fortran
do k=1,nkn_inner
  lmax = ilhkv(k)
  lmin = jlhkv(k)
  levmin = nsigma + lmin
  do l=levmin,lmax
    areafv = area(l,k)
    if( areafv .gt. 0. ) then
      hdkn(l,k) = hdkn(l,k) / areafv
    else
      exit
    end if
  end do
  do l=lmin,lmax
    h = hdkn(l,k)
    if( h <= hmin ) then
      ! error output and stop (never reached in normal operation)
    end if
  end do
end do
```

Called every timestep via `make_new_depth` → `setdepth`.

### Safety Analysis

- Each node `k` reads/writes only `hdkn(:,k)` and `area(:,k)` — unique indices, no cross-node dependencies.
- Error check path (`h <= hmin`) contains `write` + `stop`. Only triggers on fatal mesh defects. `stop` in OMP region is implementation-defined but gfortran handles it correctly.
- All loop variables are local scalars.

### Proposed Change

```fortran
!$OMP PARALLEL DO PRIVATE(k,lmax,lmin,levmin,l,areafv,h) SCHEDULE(STATIC)
do k=1,nkn_inner
  ...
end do
!$OMP END PARALLEL DO
```

`SCHEDULE(STATIC)` because work per node is uniform (simple division).

**Risk**: Low. Each node accesses unique array indices. Error path never reached in normal operation.

## Verification Plan

1. Build: `PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr`
2. Serial test: `OMP_NUM_THREADS=1 shyfem mm_hyd_00.str` — 1152 timesteps, no errors
3. Hybrid test: `OMP_NUM_THREADS=2 mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str`
4. Results must be identical to Phase 8 baseline

## Summary

| Change | File | Risk | Frequency |
|--------|------|------|-----------|
| Density `!$OMP PARALLEL DO` | `baroclinic.f90` | Very low | Every timestep |
| Layer depth node `!$OMP PARALLEL DO` | `elems_dealing.f90` | Low | Every timestep |

**Combined estimated speedup**: 2-4% on production meshes with 4+ threads.
