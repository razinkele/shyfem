# Phase 7 Optimization Design — OpenMP Parallelization of Element/Node Loops

**Date**: 2026-02-21
**Status**: Proposed
**Approach**: Add `!$OMP PARALLEL DO` to three independent loops

## Context

Phases 3, 5, and 6 applied algorithmic optimizations, compiler flags, allocation caching, SIMD directives, and enabled hybrid MPI+OpenMP. Phase 6 confirmed that GOTM turbulence cannot be parallelized (module-level scratch arrays).

This proposal targets three remaining sequential loops that iterate over elements or nodes with no data dependencies.

## Change 1: Bottom Friction Loop in chezy.f90

**File**: `src/shyfem/chezy.f90:287-395`

### Current State

The `bottom_friction` subroutine iterates over all elements:

```fortran
do ie=1,nel
  lmax = ilhv(ie)
  uso = utlov(lmax,ie)
  vso = vtlov(lmax,ie)
  uv = sqrt(uso*uso+vso*vso)
  hzg = hdeov(lmax,ie)
  rfric = czv(ie)
  ! ... select case on ireib (friction type) ...
  rfricv(ie) = rr
  rcdv(ie) = rcd
  bnstressv(ie) = rcd * uuvv * uuvv
end do
```

Each element is independent. Output arrays are written at unique `ie` indices.

### Safety Analysis

- `ireib` 0-7: All local scalar computations, `cdf()` is a pure function. Thread-safe.
- `ireib` 8-9: Access node arrays via `nen3v(ii,ie)`, write to `z0bk(k)` — potential race condition. `ireib==9` calls `set_mud_roughness` with possible side effects.

### Proposed Change

Add `!$OMP PARALLEL DO` guarded by `ireib <= 7`:

```fortran
!$OMP PARALLEL DO PRIVATE(ie,lmax,uso,vso,uv,hzg,rfric,rr,rcd,ss,uuvv,ii,k,alpha) &
!$OMP& SHARED(nel,ilhv,utlov,vtlov,hdeov,czv,rfricv,rcdv,bnstressv, &
!$OMP&  hzoff,ireib,grav,drittl,rho0,uvmin,z0bk,nen3v,ilhkv) &
!$OMP& SCHEDULE(STATIC) IF(ireib <= 7)
do ie=1,nel
  ...
end do
!$OMP END PARALLEL DO
```

The `IF(ireib <= 7)` clause disables threading for `ireib` 8-9 where node-level writes create races.

**Risk**: Very low. >95% of simulations use `ireib` 1-7.

## Change 2: Horizontal Diffusivity Initialization in diffusion_admin.f90

**File**: `src/shyfem/diffusion_admin.f90:574-585`

### Current State

One-time initialization loop computing diffusion coefficients:

```fortran
ahmax = 0.
do ie=1,nel
  area = 12. * ev(10,ie)
  ah = 1.
  if( alpha .gt. 0. ) ah = alpha * area**(2./3.)
  ahmax = max(ahmax,ah)
  lmax = ilhv(ie)
  do l=1,lmax
    difhv(l,ie) = ah
  end do
end do
```

### Proposed Change

```fortran
!$OMP PARALLEL DO PRIVATE(ie,area,ah,lmax,l) REDUCTION(max:ahmax) SCHEDULE(STATIC)
do ie=1,nel
  ...
end do
!$OMP END PARALLEL DO
```

Textbook parallel loop with one max reduction.

**Risk**: Very low. Runs once at initialization.

## Change 3: Munk-Anderson Turbulence Loop in turbulence.f90

**File**: `src/shyfem/turbulence.f90:188-221`

### Current State

Per-timestep loop computing Richardson number and viscosity/diffusivity per water column:

```fortran
do k=1,nkn
  nlev = nlvdi
  call dep3dnod(k,mode,flev,nlev,h)
  do l=flev,nlev-1
    ri = buoyf2(l,k) / shearf2(l,k)
    vis = vistur_c*(1.+a*ri)**alpha
    dif = diftur_c*(1.+b*ri)**beta
    visv(l,k) = vis
    difv(l,k) = dif
    richard(l,k) = ri
  end do
  ! boundary layer assignments at flev-1, flev, nlev
end do
```

Each node is independent. `dep3dnod` reads shared arrays, writes only to the local `h` argument. `visv`, `difv`, `richard` are written at unique `(l,k)` indices.

### Proposed Change

```fortran
!$OMP PARALLEL DO PRIVATE(k,l,nlev,flev,h,ri,vis,dif) &
!$OMP& SHARED(nkn,nlvdi,mode,buoyf2,shearf2,visv,difv,richard, &
!$OMP&  vistur_c,diftur_c,a,b,alpha,beta) &
!$OMP& SCHEDULE(DYNAMIC)
do k=1,nkn
  ...
end do
!$OMP END PARALLEL DO
```

`SCHEDULE(DYNAMIC)` handles varying column depths (coastal vs deep-water nodes).

**Note**: Only active when `iturb==3` (Munk-Anderson closure). GOTM (`iturb==1`) remains sequential due to module-level state in `do_gotm_turb`.

**Risk**: Very low. Node columns are independent.

## Verification Plan

1. Build: `PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr`
2. Serial test: `shyfem mm_hyd_00.str` — 1152 timesteps, no errors
3. Hybrid test: `OMP_NUM_THREADS=2 mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str`
4. Results must be bit-identical to Phase 6 baseline

## Summary

| Change | File | Risk | Frequency |
|--------|------|------|-----------|
| Bottom friction `!$OMP PARALLEL DO` | `chezy.f90` | Very low | Every timestep |
| Diffusivity init `!$OMP PARALLEL DO` | `diffusion_admin.f90` | Very low | Once at startup |
| Munk-Anderson `!$OMP PARALLEL DO` | `turbulence.f90` | Very low | Every timestep (if `iturb==3`) |

**Combined estimated speedup**: 2-4% on production meshes with 4+ threads.
