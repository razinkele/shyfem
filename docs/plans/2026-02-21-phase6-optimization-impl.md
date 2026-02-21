# Phase 6 Optimization Implementation Plan — Hybrid MPI+OpenMP, Allocation Caching & Turbulence Threading

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable hybrid MPI+OpenMP builds, cache 7 remaining per-timestep allocations, document MPI exchange pattern, and add OpenMP threading to the turbulence solver.

**Architecture:** Four independent changes applied sequentially. Change 1 (hybrid mode) unlocks Change 4 (turbulence threading). Changes 2-3 are independent. All changes are individually revertible.

**Tech Stack:** Fortran 90/95, OpenMP 4.0+, MPI (OpenMPI), GNU Make

---

### Task 1: Capture Baseline Benchmarks

**Files:**
- None modified

**Step 1: Clean build with current code (MPI-only)**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr
```

Expected: Build succeeds with no errors.

**Step 2: Run baseline serial benchmark**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record the wall time. Expected: ~3.1-3.3s, 1152 timesteps, no errors.

**Step 3: Run baseline MPI 4P benchmark**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record the wall time. Expected: ~2.0-2.2s.

**Step 4: Commit (no code changes — just record baseline in commit message)**

No commit needed for this task. Just record the numbers.

---

### Task 2: Enable Hybrid MPI+OpenMP — Remove Build Guard

**Files:**
- Modify: `Rules.make:479-483`

**Step 1: Read the current incompatibility check**

Read `Rules.make` lines 479-483:
```makefile
ifeq ($(PARALLEL_MPI),NODE)
  ifeq ($(PARALLEL_OMP),true)
    RULES_MAKE_PARAMETERS = RULES_MAKE_PARAMETER_ERROR
    RULES_MAKE_MESSAGE = "OMP and MPI parallelization are incompatible"
  endif
```

**Step 2: Remove the OMP+MPI incompatibility check**

Delete lines 479-483 (the `ifeq ($(PARALLEL_OMP),true)` block inside `ifeq ($(PARALLEL_MPI),NODE)`). Keep the surrounding MPI-METIS check intact.

After edit, lines 479+ should look like:
```makefile
ifeq ($(PARALLEL_MPI),NODE)
  ifeq ($(PARTS),NONE)
    RULES_MAKE_PARAMETERS = RULES_MAKE_PARAMETER_ERROR
    RULES_MAKE_MESSAGE = "MPI parallelization PARTS = METIS"
  endif
endif
```

**Step 3: Verify hybrid build compiles**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

Expected: Build succeeds. Previously this would fail with "OMP and MPI parallelization are incompatible".

**Step 4: Commit**

```bash
git add Rules.make
git commit -m "perf: remove OMP+MPI incompatibility guard in Rules.make

The codebase already follows MPI_THREAD_FUNNELED pattern — all MPI calls
are outside OMP PARALLEL regions. Safe to allow hybrid builds.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Enable Hybrid MPI+OpenMP — MPI Thread Level + Critical Guards

**Files:**
- Modify: `src/utils/shympi/mpi_node_internal.f90:212-213` (thread level)
- Modify: `src/utils/shympi/mpi_node_internal.f90` at 7 locations (restore `!$OMP CRITICAL` guards)

**Step 1: Change MPI thread level from SERIALIZED to FUNNELED**

In `mpi_node_internal.f90`, lines 212-213 currently read:
```fortran
	required = MPI_THREAD_MULTIPLE
	required = MPI_THREAD_SERIALIZED
```

Change to:
```fortran
	required = MPI_THREAD_FUNNELED
```

Remove the first line (MULTIPLE) — it's dead code overwritten by SERIALIZED anyway. Replace SERIALIZED with FUNNELED.

**Step 2: Restore `!$OMP CRITICAL` guards at 7 locations**

At each of these 14 lines, change the comment prefix `!ccgguccc` to nothing (uncomment the directive):

| Line | Current | Change to |
|------|---------|-----------|
| 410 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 428 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |
| 459 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 482 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |
| 547 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 571 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |
| 657 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 684 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |
| 751 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 775 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |
| 2053 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 2076 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |
| 2119 | `!ccgguccc!$OMP CRITICAL` | `!$OMP CRITICAL` |
| 2142 | `!ccgguccc!$OMP END CRITICAL` | `!$OMP END CRITICAL` |

Use `replace_all` to change `!ccgguccc!$OMP CRITICAL` → `!$OMP CRITICAL` and `!ccgguccc!$OMP END CRITICAL` → `!$OMP END CRITICAL`.

**Step 3: Build and test**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

Expected: Build succeeds.

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: 1152 timesteps complete, no errors.

**Step 4: Commit**

```bash
git add src/utils/shympi/mpi_node_internal.f90
git commit -m "perf: enable MPI_THREAD_FUNNELED and restore OMP CRITICAL guards

Change MPI init from SERIALIZED to FUNNELED. Restore 7 OMP CRITICAL
guard pairs as defensive measure for future code changes.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Cache vf/va Allocations in hydro_vertical

**Files:**
- Modify: `src/shyfem/hydrodynamic.f90:1787-1790` (allocation site)
- Modify: `src/shyfem/hydrodynamic.f90:1897` (deallocate site)

**Step 1: Convert vf/va to allocatable save with lazy init**

At line 1787-1790, the current code is:
```fortran
	allocate(vf(nlvdi,nkn),va(nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	vf = 0.
	va = 0.
```

Change to:
```fortran
	if (.not. allocated(vf)) then
	  allocate(vf(nlvdi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(va)) then
	  allocate(va(nlvdi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	vf = 0.
	va = 0.
```

Also find the declaration of `vf` and `va` near the top of `hydro_vertical`. They should currently be:
```fortran
	real, allocatable :: vf(:,:), va(:,:)
```

Change to:
```fortran
	real, allocatable, save :: vf(:,:), va(:,:)
```

The declaration is near line 1750-1770 — read that section to find the exact line.

**Step 2: Remove the deallocate at line 1897**

Line 1897: `deallocate(vf,va)` — delete this line entirely.

**Step 3: Build and test**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Build succeeds, 1152 timesteps, no errors. Results should be bit-identical to baseline (arrays are zeroed before use).

**Step 4: Commit**

```bash
git add src/shyfem/hydrodynamic.f90
git commit -m "perf: cache vf/va allocations in hydro_vertical (~4MB/timestep saved)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Cache 5 Arrays in conz3d_omp

**Files:**
- Modify: `src/shyfem/concentration_omp.f90:173-177` (declarations)
- Modify: `src/shyfem/concentration_omp.f90:195-204` (allocation site)

**Step 1: Add `save` to the array declarations**

At lines 173-177, the current declarations are:
```fortran
	double precision,dimension(:,:),allocatable :: cn
	double precision,dimension(:,:),allocatable :: co
        double precision,dimension(:,:),allocatable :: cdiag
	double precision,dimension(:,:),allocatable :: clow
	double precision,dimension(:,:),allocatable :: chigh
```

Change to:
```fortran
	double precision,dimension(:,:),allocatable,save :: cn
	double precision,dimension(:,:),allocatable,save :: co
        double precision,dimension(:,:),allocatable,save :: cdiag
	double precision,dimension(:,:),allocatable,save :: clow
	double precision,dimension(:,:),allocatable,save :: chigh
```

**Step 2: Wrap allocations in lazy init guards**

At lines 195-204, the current code is:
```fortran
	ALLOCATE(cn(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	ALLOCATE(co(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	ALLOCATE(cdiag(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	ALLOCATE(clow(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
	ALLOCATE(chigh(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop: allocation failed'
```

Change to:
```fortran
	if (.not. allocated(cn)) then
	  allocate(cn(nlvddi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(co)) then
	  allocate(co(nlvddi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(cdiag)) then
	  allocate(cdiag(nlvddi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(clow)) then
	  allocate(clow(nlvddi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
	if (.not. allocated(chigh)) then
	  allocate(chigh(nlvddi,nkn),stat=ierr)
	  if( ierr /= 0 ) stop 'error stop: allocation failed'
	end if
```

There are no `deallocate` calls for these arrays (already verified).

**Step 3: Build and test**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Build succeeds, 1152 timesteps, no errors. Arrays are zeroed inside `conz3d_element` before use.

**Step 4: Commit**

```bash
git add src/shyfem/concentration_omp.f90
git commit -m "perf: cache 5 work arrays in conz3d_omp (~10MB/timestep saved)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Document Duplicate MPI Exchange in Concentration

**Files:**
- Modify: `src/shyfem/concentration.f90:779-781`

**Investigation result**: `bndo_setbc` applies boundary conditions to ALL boundary nodes, including outer ghost nodes. When a boundary node is an outer ghost (owned by a neighboring MPI domain), the BC modification must be propagated back via exchange. **The second exchange is NOT redundant — it is necessary for correctness in edge cases where boundary nodes span partition boundaries.**

**Step 1: Add explanatory comment**

At lines 779-781, the current code is:
```fortran
          call shympi_exchange_3d_node(cnv)
          call bndo_setbc(what,nlvddi,cnv,rcv,uprv,vprv)
          call shympi_exchange_3d_node(cnv)
```

Add a comment explaining why both exchanges are needed:
```fortran
          call shympi_exchange_3d_node(cnv)
          call bndo_setbc(what,nlvddi,cnv,rcv,uprv,vprv)
          ! Second exchange needed: bndo_setbc modifies all boundary nodes
          ! including outer ghost nodes. Must propagate BC values back to
          ! owning domains when boundary nodes span partition boundaries.
          call shympi_exchange_3d_node(cnv)
```

**Step 2: Build and test**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Build succeeds, 1152 timesteps, identical to previous runs.

**Step 3: Commit**

```bash
git add src/shyfem/concentration.f90
git commit -m "docs: document why both MPI exchanges are needed in concentration substep

Investigation confirmed bndo_setbc modifies outer ghost boundary nodes,
so the second exchange is necessary for cross-partition consistency.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Add OpenMP PARALLEL DO to Turbulence gotm_shell

**Files:**
- Modify: `src/shyfem/turbulence.f90:413` (main `do k=1,nkn` loop)

**Prerequisites:** Tasks 2-3 (hybrid mode enabled). Without hybrid mode, OpenMP directives are no-ops in MPI builds.

**Step 1: Understand the loop structure**

The `gotm_shell` subroutine has a `do k=1,nkn` loop at line 413 that iterates over all water column nodes. Each iteration is completely independent: it reads shared arrays at index `k`, calls `do_gotm_turb` with local stack arrays, and writes results back to shared arrays at unique `(l,k)` indices.

**Variables to classify:**
- **PRIVATE** (each thread needs its own copy):
  - Loop index: `k`
  - Scalars computed per-node: `nlev`, `flev`, `numOfLev`, `depth`, `z0s`, `z0b`, `u_taus`, `u_taub`, `ubot`, `vbot`, `rr`, `dz0`, `laux`, `l`, `bwrite`, `bdeb`
  - Small stack arrays: `h(nlvdi)`, `hh(0:nlvdi)`, `nn(0:nlvdi)`, `ss(0:nlvdi)`, `num(0:nlvdi)`, `nuh(0:nlvdi)`, `ken(0:nlvdi)`, `dis(0:nlvdi)`, `len(0:nlvdi)`, `num_old(0:nlvdi)`, `nuh_old(0:nlvdi)`, `ken_old(0:nlvdi)`, `dis_old(0:nlvdi)`, `len_old(0:nlvdi)`
- **SHARED** (read-only or written at unique k indices):
  - `ilhkv`, `jlhkv`, `tauxnv`, `tauynv`, `taub`, `uprv`, `vprv`, `z0bk`, `z0sk`
  - `buoyf2`, `shearf2` (read)
  - `numv_gotm`, `nuhv_gotm`, `tken_gotm`, `eps_gotm`, `rls_gotm` (read+write at unique k)
  - `visv`, `difv` (write at unique (l,k))
  - `wlnv` (not touched in this loop)
- **REDUCTION**: `rlmax` (max), `nltot` (+)

**Important**: The debug write blocks (`bdeb`, `iudeb`, `iwhat`, `bwrite`) and `goto` statements are NOT thread-safe. The debug code must be disabled for threaded execution. Since `kdebug` is hardcoded to `-1` at line 320, `bdeb` is always `.false.` and `iudeb` is always `0`. The debug blocks are dead code. However, `goto 96` and `goto 97` are used for error handling — these are safe because they stop the program.

**Step 2: Add OpenMP PARALLEL DO directive**

Before line 413 (`do k=1,nkn`), add:

```fortran
!$OMP PARALLEL DO PRIVATE(k,bdeb,nlev,flev,numOfLev,h,hh,depth, &
!$OMP&  z0s,z0b,u_taus,u_taub,ubot,vbot,rr,dz0,laux,l,bwrite, &
!$OMP&  nn,ss,num,nuh,ken,dis,len,num_old,nuh_old,ken_old, &
!$OMP&  dis_old,len_old) &
!$OMP& SHARED(nkn,nlvdi,ilhkv,jlhkv,tauxnv,tauynv,taub,uprv, &
!$OMP&  vprv,z0bk,z0sk,buoyf2,shearf2,numv_gotm,nuhv_gotm, &
!$OMP&  tken_gotm,eps_gotm,rls_gotm,visv,difv,g,dt, &
!$OMP&  z0bmin,z0smin,charnock_val,dz0min,ipext) &
!$OMP& REDUCTION(max:rlmax) REDUCTION(+:nltot) &
!$OMP& SCHEDULE(DYNAMIC)
	do k=1,nkn
```

After line 605 (`end do` closing the `k` loop), add:
```fortran
!$OMP END PARALLEL DO
```

**Important**: Remove `call save_gotm_set_debug(bdeb)` at line 416 from the parallel region — this likely modifies module-level state. Since `bdeb` is always `.false.` (kdebug=-1), remove these debug-related lines from inside the loop, or guard them with `if (.false.)`. The safest approach: wrap the `save_gotm_set_debug` call and all `iudeb`-dependent blocks in `!$OMP SINGLE` or simply skip them since `kdebug = -1`.

Actually, the simplest safe approach: since `kdebug` is hardcoded to -1, `bdeb` is always false and `iudeb` is always 0. The debug code paths are never taken. Just leave them — they're dead code. But `save_gotm_set_debug` at line 416 IS called every iteration. Check if it modifies shared state:
- If it just sets a module variable, it's a race condition even if the value is always `.false.`
- Move the call outside the loop or guard it

**Safe approach**: Set `bdeb = .false.` in the PRIVATE list and remove the `call save_gotm_set_debug(bdeb)` from inside the loop. Add a single call before the loop:
```fortran
	call save_gotm_set_debug(.false.)
```

**Step 3: Build and test**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=2 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: Build succeeds, 1152 timesteps, no errors.

**Step 4: Commit**

```bash
git add src/shyfem/turbulence.f90
git commit -m "perf: add OMP PARALLEL DO to gotm_shell turbulence node loop

Each node's vertical column is independent. SCHEDULE(DYNAMIC) handles
varying column depths. ~13% of timestep now parallelized across threads.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Final Benchmark

**Files:**
- None modified

**Step 1: Run hybrid MPI+OMP benchmark matrix**

Build is already done from Task 7. Run the following benchmarks:

**Serial (1P, OMP_NUM_THREADS=1):**
```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

**MPI 4P, 1 thread per rank:**
```bash
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

**MPI 4P, 2 threads per rank:**
```bash
OMP_NUM_THREADS=2 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

**MPI 2P, 4 threads per rank:**
```bash
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 2 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record all times. Compare against Task 1 baseline.

**Note:** mar_menor is a small test case. Measurable gains require production meshes with 50+ vertical levels and 100k+ elements. The primary goal here is correctness verification.

**Step 2: Verify correctness**

All runs must complete 1152 timesteps with no errors, no NaN values.
