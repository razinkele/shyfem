# Performance Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply compiler flag improvements, allocation caching, and SIMD directives to achieve 20-35% speedup on the SPEED profile.

**Architecture:** Three independent changes: (1) `Rules.make` build flags for NORMAL and SPEED profiles, (2) `save` attribute on 5 allocatable arrays in `explicit.f90` to eliminate per-timestep allocation, (3) `!$OMP SIMD` directives on 9 safe vertical level loops across 3 files.

**Tech Stack:** Fortran 90/95+, GNU Make, gfortran, OpenMP 4.0+, MPI (OpenMPI)

---

### Task 1: Capture baseline benchmark

Establish baseline performance numbers before any changes.

**Files:**
- None modified

**Step 1: Clean build with current flags**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 2: Run serial baseline**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH time shyfem mm_hyd_00.str
```

Record wall time. Expected: ~3.1s serial.

**Step 3: Run MPI baseline (4 ranks)**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH time mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

Record wall time. Expected: ~2.0s.

**Step 4: Save baseline output for correctness comparison**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
cp mm_hyd_00.hydro.shy mm_hyd_00.hydro.shy.baseline 2>/dev/null || true
```

**Step 5: Commit baseline results**

No code changes yet — just record the numbers in a comment for reference.

---

### Task 2: Upgrade NORMAL profile from -O to -O2

**Files:**
- Modify: `Rules.make:707`

**Step 1: Edit Rules.make — change MEDIUM optimization from -O to -O2**

In `Rules.make`, line 707, change:
```makefile
FGNU_OPT   = -O
```
to:
```makefile
FGNU_OPT   = -O2
```

**Step 2: Clean build and verify compilation succeeds**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

Expected: Clean compilation with zero errors.

**Step 3: Run serial test and verify correctness**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH time shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps with no NaN/errors. Wall time should be 5-10% faster than baseline.

**Step 4: Run MPI test (4 ranks)**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH time mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 5: Commit**

```bash
git add Rules.make
git commit -m "perf: upgrade NORMAL profile optimization from -O to -O2"
```

---

### Task 3: Enhance SPEED profile with -march=native and vectorization flags

**Files:**
- Modify: `Rules.make:708-710`

**Step 1: Edit Rules.make — enhance HIGH optimization flags**

In `Rules.make`, lines 708-709, change:
```makefile
ifeq ($(OPTIMIZE),HIGH)
  FGNU_OPT   = -O3
endif
```
to:
```makefile
ifeq ($(OPTIMIZE),HIGH)
  FGNU_OPT   = -O3 -march=native -funroll-loops -ftree-vectorize
endif
```

**Step 2: Clean build with SPEED profile and verify compilation**

```bash
cd /home/razinka/shyfem && make clean && make fem COMPILER_PROFILE=SPEED
```

Expected: Clean compilation with zero errors.

**Step 3: Run serial SPEED test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH time shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps. Should be noticeably faster than -O3 alone.

**Step 4: Run MPI SPEED test (4 ranks)**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH time mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 5: Rebuild with NORMAL profile (restore default for subsequent tasks)**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 6: Commit**

```bash
git add Rules.make
git commit -m "perf: add -march=native -funroll-loops -ftree-vectorize to SPEED profile"
```

---

### Task 4: Cache saux allocation in set_momentum_flux

**Files:**
- Modify: `src/shyfem/explicit.f90:633-641`

**Step 1: Edit explicit.f90 — add save attribute and lazy init for saux**

In `set_momentum_flux` subroutine (around line 633), change:
```fortran
	real, allocatable :: saux(:,:)
	integer ierr
```
to:
```fortran
	real, allocatable, save :: saux(:,:)
	integer ierr
```

Then change the allocation block (around line 640) from:
```fortran
	allocate(saux(nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
```
to:
```fortran
	if (.not. allocated(saux)) then
	  allocate(saux(nlvdi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
```

The existing `saux = 0.` line (643) stays unchanged — it zeroes the array every call.

**Step 2: Build and verify compilation**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

Expected: Clean compilation.

**Step 3: Run serial test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps with no errors.

**Step 4: Commit**

```bash
git add src/shyfem/explicit.f90
git commit -m "perf: cache saux allocation in set_momentum_flux (save attribute)"
```

---

### Task 5: Cache bpresxv/bpresyv allocation in set_barocl

**Files:**
- Modify: `src/shyfem/explicit.f90:1052-1062`

**Step 1: Edit explicit.f90 — add save and lazy init for bpresxv/bpresyv**

In `set_barocl` subroutine (around line 1052), change:
```fortran
	real, allocatable :: bpresxv(:,:), bpresyv(:,:)
	integer ierr
```
to:
```fortran
	real, allocatable, save :: bpresxv(:,:), bpresyv(:,:)
	integer ierr
```

Then change the allocation block (around lines 1057-1060) from:
```fortran
	allocate(bpresxv(nlv,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	allocate(bpresyv(nlv,nel),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
```
to:
```fortran
	if (.not. allocated(bpresxv)) then
	  allocate(bpresxv(nlv,nel),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(bpresyv)) then
	  allocate(bpresyv(nlv,nel),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
```

The existing zeroing `bpresxv = 0.` / `bpresyv = 0.` stays unchanged.

**Step 2: Build and verify**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 3: Run serial test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 4: Commit**

```bash
git add src/shyfem/explicit.f90
git commit -m "perf: cache bpresxv/bpresyv allocation in set_barocl (save attribute)"
```

---

### Task 6: Cache hkko/hkkom allocation in set_barocl_new_interface

**Files:**
- Modify: `src/shyfem/explicit.f90:1275-1327` and `1552-1553`

**Step 1: Edit explicit.f90 — add save and lazy init for hkko/hkkom**

In `set_barocl_new_interface` subroutine (around line 1275), change:
```fortran
	real, allocatable :: hkko(:,:)	!depth of interface at node
	real, allocatable :: hkkom(:,:)	!average depth of layer at node
```
to:
```fortran
	real, allocatable, save :: hkko(:,:)	!depth of interface at node
	real, allocatable, save :: hkkom(:,:)	!average depth of layer at node
```

Then change the allocation block (around lines 1324-1327) from:
```fortran
	allocate(hkko(0:nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	allocate(hkkom(0:nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
```
to:
```fortran
	if (.not. allocated(hkko)) then
	  allocate(hkko(0:nlvdi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(hkkom)) then
	  allocate(hkkom(0:nlvdi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
```

**Step 2: Remove the deallocate calls at end of subroutine**

Remove lines 1552-1553:
```fortran
	deallocate(hkko)
	deallocate(hkkom)
```

These must be removed because `save` arrays persist across calls — deallocating would defeat the purpose.

**Step 3: Build and verify**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 4: Run serial test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 5: Run MPI test (4 ranks) — verify all allocation caching works under MPI**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 6: Commit**

```bash
git add src/shyfem/explicit.f90
git commit -m "perf: cache hkko/hkkom allocation in set_barocl_new_interface (save attribute)"
```

---

### Task 7: Add SIMD directives to hydro_zeta reduction loops

**Files:**
- Modify: `src/shyfem/hydrodynamic.f90:665-692` and `801-816`

These are the 4 reduction loops in `hydro_zeta` (2 in the main path, 2 in the PETSc fallback path). All are pure scalar reductions over vertical levels with no dependencies.

**Step 1: Add !$OMP SIMD to first dbb/dbc/dcb/dcc reduction (line 669)**

Before line 669, add the SIMD directive:
```fortran
            !$OMP SIMD reduction(+:dbb,dbc,dcb,dcc)
            do l=jlevel,ilevel
```

**Step 2: Add !$OMP SIMD to first uold/vold/uhat/vhat reduction (line 687)**

Before line 687, add:
```fortran
            !$OMP SIMD reduction(+:uold,vold,uhat,vhat)
            do l=jlevel,ilevel
```

**Step 3: Add !$OMP SIMD to PETSc fallback dbb/dbc/dcb/dcc reduction (line 802)**

Before line 802, add:
```fortran
            !$OMP SIMD reduction(+:dbb,dbc,dcb,dcc)
            do l=jlevel,ilevel
```

**Step 4: Add !$OMP SIMD to PETSc fallback uold/vold/uhat/vhat reduction (line 811)**

Before line 811, add:
```fortran
            !$OMP SIMD reduction(+:uold,vold,uhat,vhat)
            do l=jlevel,ilevel
```

**Step 5: Build and verify**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 6: Run serial test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps — SIMD directives are hints and must produce identical results.

**Step 7: Commit**

```bash
git add src/shyfem/hydrodynamic.f90
git commit -m "perf: add !$OMP SIMD to hydro_zeta vertical reduction loops"
```

---

### Task 8: Add SIMD directives to hydro_intern and hydro_transports_final loops

**Files:**
- Modify: `src/shyfem/hydrodynamic.f90:1498-1501`, `1509-1512`, `1664-1675`, `1683-1686`

These are 4 loops: 2 in `hydro_intern` (array updates and copies) and 2 in `hydro_transports_final` (barotropic pressure update and transport summation).

**Step 1: Add !$OMP SIMD to utlnv/vtlnv update (line 1498)**

Before line 1498, add:
```fortran
	  !$OMP SIMD
	  do l=jlevel,ilevel
```

**Step 2: Add !$OMP SIMD to ddxv/ddyv copy (line 1509)**

Before line 1509, add:
```fortran
	!$OMP SIMD
	do l=1,ngl						!ASYM_OPSPLT
```

**Step 3: Add !$OMP SIMD to barotropic pressure loop (line 1664)**

Before line 1664, add:
```fortran
	!$OMP SIMD
	do l=jlevel,ilevel
```

**Step 4: Add !$OMP SIMD to transport summation (line 1683)**

Before line 1683, add:
```fortran
	!$OMP SIMD reduction(+:um,vm)
	do l=jlevel,ilevel
```

**Step 5: Build and verify**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 6: Run serial test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 7: Commit**

```bash
git add src/shyfem/hydrodynamic.f90
git commit -m "perf: add !$OMP SIMD to hydro_intern and hydro_transports_final loops"
```

---

### Task 9: Add SIMD directives to turbulence.f90 loops

**Files:**
- Modify: `src/shyfem/turbulence.f90` — lines 431, 596, 797

Three safe loops in `gotm_shell` and `gotm_get`: array scatter/gather operations with formula indexing, no conditionals, no function calls.

**Step 1: Add !$OMP SIMD to buoyf2/shearf2 scatter (line 431)**

Before line 431, add:
```fortran
	!$OMP SIMD
	do l=flev,nlev-1
```

**Step 2: Add !$OMP SIMD to visv/difv assignment (line 596)**

Before line 596, add:
```fortran
	!$OMP SIMD
	do l=flev-1,nlev
```

**Step 3: Add !$OMP SIMD to 5-variable gotm_get copy (line 797)**

Before line 797, add:
```fortran
	!$OMP SIMD
	do l=0,nlev
```

**Step 4: Build and verify**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 5: Run serial test**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```

Expected: Completes all 1152 timesteps.

**Step 6: Commit**

```bash
git add src/shyfem/turbulence.f90
git commit -m "perf: add !$OMP SIMD to turbulence vertical level loops"
```

---

### Task 10: Final verification — full benchmark matrix

Run the complete verification matrix from the design document.

**Files:**
- None modified

**Step 1: Clean build with NORMAL profile, run serial + MPI**

```bash
cd /home/razinka/shyfem && make clean && make fem
cd testcases/examples/mar_menor && make init
PATH=/home/razinka/shyfem/bin:$PATH time shyfem mm_hyd_00.str
make init
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH time mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str
```

Record NORMAL serial and NORMAL 4P times.

**Step 2: Clean build with SPEED profile, run serial + MPI (1, 2, 4, 8)**

```bash
cd /home/razinka/shyfem && make clean && make fem COMPILER_PROFILE=SPEED
cd testcases/examples/mar_menor
for np in 1 2 4 8; do
  make init
  PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH time mpirun --oversubscribe -np $np shyfem mm_hyd_00.str
done
```

Record all SPEED times.

**Step 3: Compare results with baseline**

Verify simulation completes all 1152 timesteps in every configuration. No NaN, no crashes, no error messages.

**Step 4: Rebuild with NORMAL profile (restore default)**

```bash
cd /home/razinka/shyfem && make clean && make fem
```

**Step 5: Report results**

Print a summary table of all benchmark results vs baseline.
