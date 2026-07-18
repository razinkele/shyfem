# Batch 1: Fortran Core Critical/High Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 10 critical/high Fortran-core findings from the 2026-07-18 deep review (N01, N03, N04, N05, N09, N10, N11, N15, N20, N29 in `docs/reviews/2026-07-18-full-codebase-deep-review.md`): the OpenMP save-caching races, the MPI-from-tasks violation, unchecked PETSc convergence, the femtime freeze, two calm-wind singularities, the projection-midpoint bug, and the MPI-debug-unit regression.

**Architecture:** All fixes are surgical reverts or guards in existing files — no new modules. The OMP-race fixes revert the `allocatable, save` "caching" (commits `34ff6dd`/`38469ab`) back to per-call allocatables; the MPI-from-tasks fix undefers OpenMP tasks when MPI is active (`IF` clause on the TASK directives); the rest are point guards/corrections.

**Tech Stack:** Fortran 90 (gfortran), OpenMP tasks, OpenMPI, PETSc (optional solver), GNU Make. No unit-test framework exists for the Fortran core — verification is build + targeted mar_menor runs (see Task 0).

## Global Constraints

- Always build/run with OpenMPI: prefix every make/run with `PATH=/usr/bin:$PATH` (CLAUDE.md Intel-MPI trap). After MPI builds verify `ldd src/shyfem/shyfem | grep mpi` shows `libmpi.so.40`.
- Real build knobs are `PARALLEL_OMP` (`false` default), `PARALLEL_MPI` (`NODE` default), `SOLVER` (`SPARSKIT` default) — Rules.make:110-190. Pass them on the make command line (do not edit Rules.make).
- The Fortran sources use **tab indentation** — match it exactly in edits.
- Keep existing error-stop style per file (bare-stop modernization is Batch 5's job, do not mix it in here).
- Branch: `fix/b1-fortran-core-races` off `fix/codebase-review-remediations`. Conventional commits, one commit per task.
- Working directory: `/home/razinka/shyfem`.

---

### Task 0: Branch + tracer test config + serial baseline

**Files:**
- Create: `testcases/examples/mar_menor/mm_hyd_conz.str` (generated copy, not committed)

**Interfaces:**
- Produces: `mm_hyd_conz.str` — mar_menor config with `iconz = 2` (two tracers), used by Tasks 1–4 to exercise concurrent tracer tasks. Baseline log `base_serial.log` for comparisons.

- [ ] **Step 1: Create the branch**

```bash
cd /home/razinka/shyfem
git checkout -b fix/b1-fortran-core-races
```

- [ ] **Step 2: Build the default (serial/NODE) binary**

```bash
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem
```
Expected: build completes; `src/shyfem/shyfem` exists.

- [ ] **Step 3: Create the tracer config**

`iconz = 2` makes `tracer_compute_multi` spawn two concurrent scalar tasks (the racing configuration). Insert the parameters right after the `$para` section opener:

```bash
cd testcases/examples/mar_menor
make init 2>/dev/null || true
sed "/\$para/a \\\t iconz = 2\n\t conref = 1." mm_hyd_00.str > mm_hyd_conz.str
grep -n "iconz" mm_hyd_conz.str
```
Expected: `iconz = 2` appears once inside `$para`. If `mm_hyd_00.str` already sets `iconz`, edit that line to `= 2` instead of inserting.

- [ ] **Step 4: Serial baseline run**

```bash
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/base_serial.log
```
(Create `/tmp/claude-1000/b1` first: `mkdir -p /tmp/claude-1000/b1`.)
Expected: run completes all timesteps without error stop. Save the log — it is the reference for every later comparison. If the run fails on the STR edit, fix the STR (this task), not the model.

- [ ] **Step 5: Commit (branch only — the .str is generated, do not commit it)**

```bash
git status   # confirm no tracked changes yet
```

---

### Task 1: N01 (critical) — revert `conz3d_omp` save-cached work arrays

**Files:**
- Modify: `src/shyfem/concentration_omp.f90:167-214` (declarations + lazy-init), keep `:353-357` (DEALLOCATE)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: thread-safe `conz3d_omp` — per-call local allocatables `cn/co/cdiag/clow/chigh`.

- [ ] **Step 1: Capture the failing behavior (best-effort — races are probabilistic)**

```bash
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
cd testcases/examples/mar_menor
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/pre_t1_omp4.log
```
Expected (any of): `Attempt to DEALLOCATE unallocated`, segfault, FPE trap, or a clean-looking run whose tracer values differ from `base_serial.log`. Record what happened; a clean pass does NOT invalidate the fix (races are timing-dependent).

- [ ] **Step 2: Remove `save` from the five work arrays**

In `src/shyfem/concentration_omp.f90` replace lines 173–177:

```fortran
	double precision,dimension(:,:),allocatable,save :: cn
	double precision,dimension(:,:),allocatable,save :: co
        double precision,dimension(:,:),allocatable,save :: cdiag
	double precision,dimension(:,:),allocatable,save :: clow
	double precision,dimension(:,:),allocatable,save :: chigh
```

with:

```fortran
	double precision,dimension(:,:),allocatable :: cn
	double precision,dimension(:,:),allocatable :: co
        double precision,dimension(:,:),allocatable :: cdiag
	double precision,dimension(:,:),allocatable :: clow
	double precision,dimension(:,:),allocatable :: chigh
```

Also delete the dead commented block at lines 167–171 (the old automatic-array declarations) — it no longer documents anything true.

- [ ] **Step 3: Make allocation unconditional**

Replace the five lazy-init blocks (lines 195–214, `if (.not. allocated(cn)) then … end if` × 5) with:

```fortran
	allocate(cn(nlvddi,nkn),co(nlvddi,nkn),cdiag(nlvddi,nkn), &
     &		clow(nlvddi,nkn),chigh(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conz3d_omp: allocation failed'
```

Leave the `DEALLOCATE` statements at lines 353–357 in place (now correct: local arrays, freed every call — matching pre-`38469ab` behavior).

- [ ] **Step 4: Build both configs**

```bash
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
```
Expected: compiles cleanly, no new warnings about `cn/co/cdiag/clow/chigh`.

- [ ] **Step 5: Verify OMP 4-thread agreement with serial**

```bash
cd testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/post_t1_omp1.log
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/post_t1_omp4.log
diff <(grep -aiE 'mass|conz' /tmp/claude-1000/b1/post_t1_omp1.log) \
     <(grep -aiE 'mass|conz' /tmp/claude-1000/b1/post_t1_omp4.log)
```
Expected: both runs complete all timesteps; the mass/tracer diagnostic lines agree (empty diff, or only last-digit float noise). NOTE: full agreement also needs Tasks 2–3; if small diffs remain here, re-run this step after Task 3 — it must be clean by then.

- [ ] **Step 6: Commit**

```bash
git add src/shyfem/concentration_omp.f90
git commit -m "fix(omp): revert conz3d_omp save-cached work arrays to per-call (N01)

save locals are shared across concurrent OMP tasks; the lazy-init cache
raced between the barocl and tracer tasks and was deallocated mid-use.
Reverts the caching from 38469ab (which was a no-op anyway - the arrays
were still deallocated every call)."
```

---

### Task 2: N09 (high) — revert `scal_adv` family save-cached BC arrays

**Files:**
- Modify: `src/shyfem/concentration.f90:298-321` (`scal_adv`), `:397-414` (`scal_adv_nudge`), `:486-505` (`scal_adv_fact`)

**Interfaces:**
- Produces: thread-safe `scal_adv`/`scal_adv_nudge`/`scal_adv_fact` with per-call `r3v/load/cobs/rtauv/wsinkv`.

- [ ] **Step 1: `scal_adv` — remove `save`, allocate unconditionally**

Replace lines 298–302:

```fortran
        real, allocatable, save :: r3v(:,:)
        real, allocatable, save :: load(:,:)
        real, allocatable, save :: cobs(:,:)
        real, allocatable, save :: rtauv(:,:)
        real, allocatable, save :: wsinkv(:,:)
```

with:

```fortran
        real, allocatable :: r3v(:,:)
        real, allocatable :: load(:,:)
        real, allocatable :: cobs(:,:)
        real, allocatable :: rtauv(:,:)
        real, allocatable :: wsinkv(:,:)
```

Replace the guard block at lines 310–321 (`if( .not. allocated(r3v) ) then … end if`) with:

```fortran
	allocate(r3v(nlvdi,nkn),load(nlvdi,nkn),cobs(nlvdi,nkn), &
     &		rtauv(nlvdi,nkn),wsinkv(0:nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv: allocation failed'
```

- [ ] **Step 2: `scal_adv_nudge` — same transformation**

Its declarations (`real, allocatable, save :: r3v(:,:)` / `wsinkv` / `load`, around line 397) lose `, save`; its `if( .not. allocated(r3v) ) then … end if` block becomes:

```fortran
	allocate(r3v(nlvdi,nkn),load(nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv_nudge: allocation failed'
	allocate(wsinkv(0:nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv_nudge: allocation failed'
```

- [ ] **Step 3: `scal_adv_fact` — same transformation**

Declarations (`r3v/cobs/rtauv`, around line 486) lose `, save`; the guard block becomes:

```fortran
	allocate(r3v(nlvdi,nkn),cobs(nlvdi,nkn),rtauv(nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv_fact: allocation failed'
```

- [ ] **Step 4: Verify no other save-array caches remain in scalar entry points**

```bash
grep -n 'allocatable, save' src/shyfem/concentration.f90 src/shyfem/concentration_omp.f90
```
Expected after Tasks 1–2: only the `conzstab` block (concentration.f90:1722-1728 — Task 3) remains.

- [ ] **Step 5: Build + run (same as Task 1 Step 5)**

```bash
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
cd testcases/examples/mar_menor
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str
```
Expected: completes all timesteps, no error stop.

- [ ] **Step 6: Commit**

```bash
git add src/shyfem/concentration.f90
git commit -m "fix(omp): revert scal_adv/_nudge/_fact save-cached BC arrays to per-call (N09)

Concurrent tracer tasks shared one r3v/load/cobs/rtauv/wsinkv set, so a
tracer could be advected with another tracer's boundary values. Reverts
the 34ff6dd caching in the three scalar entry points."
```

---

### Task 3: N10 (high) — revert `conzstab` save-cached arrays

**Files:**
- Modify: `src/shyfem/concentration.f90:1719-1731` (declarations), `:1761-1772` (allocation)

- [ ] **Step 1: Remove `save` from declarations (lines 1722–1728)**

```fortran
	double precision, allocatable :: cn(:,:)
	double precision, allocatable :: co(:,:)
	double precision, allocatable :: cdiag(:,:)
	double precision, allocatable :: clow(:,:)
	double precision, allocatable :: chigh(:,:)
        real, allocatable :: cwrite(:,:)
        real, allocatable :: c2write(:)
```

Also update the surrounding comment block (lines 1719–1721 / 1729–1731) from "cached with save to avoid per-timestep allocation" to:

```fortran
!------------------------------------------------------------
! big work arrays (per-call: conzstab runs concurrently from OMP tasks,
! so these must NOT be save/shared - see 2026-07-18 review N10)
!------------------------------------------------------------
```

- [ ] **Step 2: Make allocation unconditional (lines 1765–1772)**

Replace the `if( .not. allocated(cn) ) then … end if` block with:

```fortran
	allocate(cn(nlvddi,nkn),co(nlvddi,nkn),cdiag(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conzstab: allocation failed'
	allocate(clow(nlvddi,nkn),chigh(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conzstab: allocation failed'
	allocate(cwrite(nlvddi,nkn),c2write(nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conzstab: allocation failed'
```

- [ ] **Step 3: Build + full OMP agreement check (closes Task 1 Step 5's loop)**

```bash
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
cd testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/post_t3_omp1.log
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/post_t3_omp4.log
diff <(grep -aiE 'mass|conz' /tmp/claude-1000/b1/post_t3_omp1.log) \
     <(grep -aiE 'mass|conz' /tmp/claude-1000/b1/post_t3_omp4.log)
```
Expected: PASS — diagnostic lines identical (or last-digit noise only). This is the batch's key acceptance check for the race family.

- [ ] **Step 4: Commit**

```bash
git add src/shyfem/concentration.f90
git commit -m "fix(omp): revert conzstab save-cached arrays to per-call (N10)

conzstab is entered concurrently by every scalar task's stability check;
the shared save arrays corrupted the istot accumulation."
```

---

### Task 4: N11 (high) — undefer scalar OMP tasks when MPI is active

**Files:**
- Modify: `src/shyfem/shyfem_subs.f90:1009-1033` (`run_scalar` task region), `src/shyfem/conz_admin.f90:446-475` (`tracer_compute_multi` task loop)

**Interfaces:**
- Consumes: `shympi_is_parallel()` (module `shympi`, already used throughout both files' modules).
- Produces: hybrid MPI+OMP runs execute scalar tasks sequentially (undeferred), so `shympi_exchange_3d_node`/reductions inside `scal3sh` are never issued concurrently — satisfying `MPI_THREAD_FUNNELED` (mpi_node_internal.f90:212). Pure-OMP runs keep full task concurrency.

- [ ] **Step 1: Gate `run_scalar`'s tasks**

In `src/shyfem/shyfem_subs.f90`, inside `run_scalar` (before line 1009's `!$OMP PARALLEL`), declare and set:

```fortran
	logical :: btask
	btask = .not. shympi_is_parallel()	!MPI: undefer tasks, serialize MPI calls
```

(If the routine lacks `use shympi`, add it next to the existing `use` statements — check with `sed -n '/subroutine run_scalar/,/implicit none/p' src/shyfem/shyfem_subs.f90`.)

Then change the three TASK directives (lines 1016, 1020, 1024):

```fortran
!$OMP TASK IF ( btask )
	call barocl(1)
!$OMP END TASK

!$OMP TASK IF ( iconz > 0 .and. btask )
	call tracer_compute
!$OMP END TASK

!$OMP TASK IF ( ibfm > 0 .and. btask )
	call bfm_run
!$OMP END TASK
```

(`IF(.false.)` makes a task *undeferred* — executed immediately, in order, by the encountering thread. Note the `iconz`/`ibfm` clauses keep their original meaning: they only controlled deferral, never whether the call runs — `tracer_compute`/`bfm_run` still guard themselves internally.)

- [ ] **Step 2: Gate `tracer_compute_multi`'s per-tracer tasks**

In `src/shyfem/conz_admin.f90`, in the declarations of the routine containing line 451, add:

```fortran
	logical :: btask
```

set it before the `do i=1,nvar` loop (line 446):

```fortran
	btask = .not. shympi_is_parallel()
```

and extend the TASK directive (lines 451–453), adding the IF clause and `btask` to the data-sharing lists:

```fortran
!$OMP  TASK IF(btask) FIRSTPRIVATE(i,rkpar,wsink,difhv,difv,difmol,     &
!$OMP& idconz,what,dt,nlvdi,idecay,blinfo,bage,btask)                   &
!$OMP&  SHARED(conzv,tauv,massv) DEFAULT(NONE)
```

(Same pattern for the single-tracer sibling routine in the same file if it also spawns tasks — check with `grep -n 'OMP  *TASK' src/shyfem/conz_admin.f90` and apply the IF clause to every hit.)

- [ ] **Step 3: Build serial + OMP + MPI**

```bash
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true    # OMP build
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr   # hybrid build
ldd src/shyfem/shyfem | grep mpi
```
Expected: both compile; `libmpi.so.40` (OpenMPI).

- [ ] **Step 4: Hybrid smoke run (the previously-broken configuration)**

```bash
cd testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH OMP_NUM_THREADS=4 \
  mpirun --oversubscribe -np 4 shyfem mm_hyd_conz.str
```
Expected: completes all timesteps with no deadlock/crash. Compare tracer mass lines against `base_serial.log` (agreement within float noise).

- [ ] **Step 5: Pure-OMP regression (tasks must still parallelize)**

Re-run Task 3 Step 3's OMP-only check — must still pass.

- [ ] **Step 6: Commit**

```bash
git add src/shyfem/shyfem_subs.f90 src/shyfem/conz_admin.f90
git commit -m "fix(mpi+omp): undefer scalar tasks under MPI (N11)

scal3sh issues shympi exchanges/reductions; running it from concurrent
OMP tasks violates the MPI_THREAD_FUNNELED level requested at init.
With MPI active the tasks now run undeferred (sequential per rank);
pure-OMP runs keep full task concurrency."
```

---

### Task 5: N04 (high) — check PETSc/AmgX solver convergence

**Files:**
- Modify: `src/shyfem/mod_petsc_system.f90:581-643` (`solve_PETSc`, `solve_AmgX`)

- [ ] **Step 1: Add the convergence check to `solve_PETSc`**

Add to the routine's declarations (after `class(petsc_system),target :: self`, line 585):

```fortran
          KSPConvergedReason :: reason
```

After the `KSPSolve` + `assert` pair (lines 602–603) insert:

```fortran
              call KSPGetConvergedReason(self%ksp,reason,perr)
              call assert(perr.eq.0,'KSPGetConvergedReason perr ',perr)
              if( reason < 0 ) then
                 if(my_id==0) write(6,*) 'PETSc KSP solve DIVERGED,'// &
     &                ' KSPConvergedReason = ',reason
                 call assert(.false., &
     &                'KSPSolve did not converge, reason ',reason)
              end if
```

(`reason < 0` is PETSc's diverged range; 0 = still iterating, > 0 = converged. If `KSPConvergedReason` is rejected by the compiler with this codebase's PETSc include style, declare `PetscEnum :: reason` instead — functionally identical.)

- [ ] **Step 2: Add a sanity check to `solve_AmgX`**

In `solve_AmgX` (the `iters`/`residual` locals already exist, line 623–625), add after the `CAmgX_Solve` call (line 633):

```fortran
        external :: CAmgX_GetIters
        external :: CAmgX_GetResidual
```
(with the other `external ::` declarations, lines 626–627), and:

```fortran
        call CAmgX_getiters(self%AmgX_Solver,iters,perr)
        if( perr == 0 .and. iters > 0 ) then
          call CAmgX_getresidual(self%AmgX_Solver,iters-1,residual,perr)
          if( perr /= 0 .or. residual /= residual ) then	!NaN check
            write(6,*) 'AmgX solve failed: iters,residual = ',iters,residual
            stop 'error stop solve_AmgX: solver did not converge'
          end if
        end if
```

(AmgX is not built in this environment — this part is compile-verified only when someone builds `SOLVER=PETSC_AmgX`; the PETSc path is the production fix.)

- [ ] **Step 3: Build with PETSc and run mar_menor on the PETSc solver**

```bash
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem SOLVER=PETSC PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr
cd testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 2 shyfem mm_hyd_00.str
```
Expected: compiles (this proves the Fortran binding names/types are right) and the run completes — mar_menor converges, so the new check must NOT fire. If the run aborts with the new message, the check is wired backwards — stop and re-read the reason-code sign convention.

- [ ] **Step 4: Negative test — force a divergence**

Temporarily set an absurd iteration cap to prove the check fires, then revert:

```bash
grep -n 'KSPSetTolerances' src/shyfem/mod_petsc_system.f90
```
Edit the `maxits` argument at that call site to `1`, rebuild, rerun. Expected: run aborts early with `PETSc KSP solve DIVERGED, KSPConvergedReason = -3` (DIVERGED_ITS) instead of silently continuing. **Revert the tolerance edit**, rebuild, confirm clean run again.

- [ ] **Step 5: Restore the default build**

```bash
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem
```

- [ ] **Step 6: Commit**

```bash
git add src/shyfem/mod_petsc_system.f90
git commit -m "fix(petsc): abort on KSP divergence instead of accepting garbage zeta (N04)

KSPSolve returns perr=0 even when the Krylov solve diverges; the wrong
iterate was silently committed as the free surface. Also adds an AmgX
iters/residual sanity check. Restores parity with SPARSKIT's hard stop."
```

---

### Task 6: N05 (high) — unfreeze femtime `it` / set `itend`

**Files:**
- Modify: `src/shyfem/time_admin.f90:359` (init) and `:703` (per-step update)

- [ ] **Step 1: Set `itend` at init**

Line 358–359 currently:

```fortran
	itanf = nint(dtanf)
	!itend = nint(dtend)
```

becomes:

```fortran
	itanf = nint(dtanf)
	itend = nint(dtend)
```

- [ ] **Step 2: Update `it` every step**

Line 703 currently (inside `set_timestep`, after `idt = dt`):

```fortran
	!it = t_act
```

becomes:

```fortran
	if( abs(t_act) < 2.1d9 ) it = nint(t_act)	!legacy femtime clock
```

(The guard prevents integer overflow for simulations beyond ~68 years of model seconds — the pre-existing failure mode that motivated commenting it out; consumers (`lagrange_decay/connect/dif/inout/main`) all operate on second-scale differences well inside the range.)

- [ ] **Step 3: Confirm the consumers see live time**

```bash
grep -rn 'use femtime' src/shyfem/lagrange_decay.f90 src/shyfem/lagrange_connect.f90
grep -n 'age=it-\|dt=it-\|t = it' src/shyfem/lagrange_decay.f90
```
Expected: the `it` consumers are exactly the lagrangian age/decay computations the finding named (lines 107, 152, 179–181, 225).

- [ ] **Step 4: Build + regression**

```bash
PATH=/usr/bin:$PATH make fem
cd testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str
```
Expected: clean run, timings unchanged vs baseline (this config does not use lagrangian — the fix must be behavior-neutral here).

- [ ] **Step 5: Commit**

```bash
git add src/shyfem/time_admin.f90
git commit -m "fix(time): update femtime it each step and set itend (N05)

it was frozen at itanf (update commented out), silently zeroing
lagrangian particle age -> decay, mortality and connectivity never
triggered. Guarded against 2^31 overflow for very long runs."
```

---

### Task 7: N03 (high) — wind-stress input: guard calm points

**Files:**
- Modify: `src/shyfem/meteo_forcing.f90:915-927` (`bstress` branch)

- [ ] **Step 1: Apply the guard**

The branch currently divides by `cd*wspeed` unconditionally (lines 924–925). Replace the loop body:

```fortran
          do k=1,n
	    fice = 1. - aice*cice(k)
            tx(k) = fice * wfact * wx(k)
            ty(k) = fice * wfact * wy(k)
            txy = sqrt( tx(k)**2 + ty(k)**2 )
            wspeed = sqrt(txy/(cd*wfact*roluft))
            wxymax = max(wxymax,wspeed)
            wx(k) = tx(k) / (cd*wspeed)
            wy(k) = ty(k) / (cd*wspeed)
	    ws(k) = wspeed
          end do
```

with:

```fortran
          do k=1,n
	    fice = 1. - aice*cice(k)
            tx(k) = fice * wfact * wx(k)
            ty(k) = fice * wfact * wy(k)
            txy = sqrt( tx(k)**2 + ty(k)**2 )
            wspeed = sqrt(txy/(cd*wfact*roluft))
            wxymax = max(wxymax,wspeed)
            if( wspeed > 1.e-8 ) then
              wx(k) = tx(k) / (cd*wspeed)
              wy(k) = ty(k) / (cd*wspeed)
            else				!calm point: no stress, no wind
              wx(k) = 0.
              wy(k) = 0.
            end if
	    ws(k) = wspeed
          end do
```

- [ ] **Step 2: Build (FPE-trap build catches the old bug class)**

```bash
PATH=/usr/bin:$PATH make fem
```
Expected: compiles. (A calm-point forcing file would previously SIGFPE under the NORMAL profile's `-ffpe-trap`; mar_menor's wind file has no all-zero record, so the regression run only proves no behavior change: run `mm_hyd_00.str`, compare against baseline.)

- [ ] **Step 3: Commit**

```bash
git add src/shyfem/meteo_forcing.f90
git commit -m "fix(meteo): guard zero wind speed in stress-input conversion (N03)

iwtype=2 with a calm point (tx=ty=0) divided by cd*wspeed=0 -> SIGFPE
under FPE traps, Inf/NaN wind otherwise."
```

---

### Task 8: N20 (medium) — hersbach_cd: floor calm wind

**Files:**
- Modify: `src/shyfem/meteo_forcing.f90:1644-1656` (`hersbach_cd`)

- [ ] **Step 1: Apply the floor**

Add to declarations (after line 1645 `double precision :: R,A`):

```fortran
	double precision :: wxy_eff
```

and change lines 1653–1654 from:

```fortran
	R = (z / (am * nu)) * (k * wxy)
	A = (ach / (g_hersbach * z)) * (k * wxy)**2
```

to:

```fortran
	wxy_eff = max(dble(wxy),0.1d0)	!floor: log(R),log(A) diverge as wxy->0
	R = (z / (am * nu)) * (k * wxy_eff)
	A = (ach / (g_hersbach * z)) * (k * wxy_eff)**2
```

(0.1 m/s is far below the ~2 m/s validity threshold of the Hersbach fit; at wxy=0 the old code computed `log(0)` → -Inf and a negative base raised to p=-12.)

- [ ] **Step 2: Build + regression run, commit**

```bash
PATH=/usr/bin:$PATH make fem
git add src/shyfem/meteo_forcing.f90
git commit -m "fix(meteo): floor wind speed in hersbach_cd drag formula (N20)

itdrag=5 with calm wind computed log(0) and a negative fractional
power -> NaN drag coefficient."
```

---

### Task 9: N15 (high) — proj_geo2cart: midpoint, not half-range

**Files:**
- Modify: `src/utils/shyutilmpi/coordinates.f90:191-193`

- [ ] **Step 1: Fix the reference point**

Lines 191–193 currently:

```fortran
        c_phi  = 0.5*(ymax-ymin)
        c_lat0 = 0.5*(ymax-ymin)
        c_lon0 = 0.5*(xmax-xmin)
```

become:

```fortran
        c_phi  = 0.5*(ymax+ymin)
        c_lat0 = 0.5*(ymax+ymin)
        c_lon0 = 0.5*(xmax+xmin)
```

(The CPP projection reference must be the domain *midpoint*. The old code put it at half the *range* — e.g. a Mar Menor basin at lat 37.7° projected around lat ≈ 0.15°, so `cos(lat0)` ≈ 1 instead of ≈ 0.79: every derived cartesian x-distance ~27% too long. Affects everything downstream of `xcartv/ycartv` — notably the wave module fetch/distance computations for spherical basins.)

- [ ] **Step 2: Build + quantify the (intentional) result change**

```bash
PATH=/usr/bin:$PATH make fem
cd testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str | tee /tmp/claude-1000/b1/post_t9.log
```
Expected: clean run. **If mar_menor runs with `iproj`>0 / spherical coords, results legitimately change** — record the delta in the PR description as a wanted correction, not a regression. If mar_menor is already cartesian (no projection), output is bit-identical to baseline.

- [ ] **Step 3: Commit**

```bash
git add src/utils/shyutilmpi/coordinates.f90
git commit -m "fix(proj): use domain midpoint as CPP projection reference (N15)

proj_geo2cart used 0.5*(max-min) (the half-range) instead of
0.5*(max+min) (the midpoint) for lat0/lon0/phi, distorting all derived
cartesian distances (cos(lat0) evaluated near the equator)."
```

---

### Task 10: N29 (medium) — MPI debug guards vs negative `newunit=`

**Files:**
- Modify: `src/utils/shympi/mpi_ghost.f90:138,501`, `src/utils/shympi/mpi_basin.f90:163,180`

- [ ] **Step 1: Flip the four guards**

`newunit=` (mpi_node.f90:693) assigns a *negative* unit, so `my_unit > 0` (initial value 0 = "no debug file") is never true even when the file is open. Change:

- `mpi_ghost.f90:138` and `:501`: `bdebug = ( my_unit > 0 )` → `bdebug = ( my_unit /= 0 )`
- `mpi_basin.f90:163` and `:180`: `if( my_unit > 0 ) then` → `if( my_unit /= 0 ) then`

Confirm completeness:

```bash
grep -rn 'my_unit > 0\|my_unit>0' src/
```
Expected: no hits left (the mpi_ghost.f90:42 comment line may remain; update its text to `only write if my_unit /= 0`).

- [ ] **Step 2: Verify the debug file actually gets content again**

```bash
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr
grep -n 'bmpi_debug_txt' src/utils/shympi/mpi_node.f90 | head -3
```
Flip `bmpi_debug_txt = .false.` to `.true.` **temporarily**, rebuild, run the 2-rank mar_menor case, and check:

```bash
cd testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 2 shyfem mm_hyd_00.str
wc -l mpi_debug_*.txt
```
Expected: the `mpi_debug_*.txt` files now contain the ghost/basin sections (pre-fix they held only the 5 header lines). **Revert the `bmpi_debug_txt` toggle**, rebuild.

- [ ] **Step 3: Commit**

```bash
git add src/utils/shympi/mpi_ghost.f90 src/utils/shympi/mpi_basin.f90
git commit -m "fix(mpi): debug guards must test my_unit /= 0 after newunit= change (N29)

73e03b2 switched the debug file to newunit=, which returns a negative
unit; every my_unit > 0 guard silently disabled the diagnostics that
commit set out to improve."
```

---

### Task 11: Full verification matrix + PR

**Files:** none (verification + PR only)

- [ ] **Step 1: Build matrix**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem                                    # default (NODE serial)
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true                 # OMP
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr   # MPI
ldd src/shyfem/shyfem | grep mpi    # must show libmpi.so.40
```
Expected: all three compile clean.

- [ ] **Step 2: Run matrix (mar_menor)**

| Config | Command | Must show |
|---|---|---|
| serial baseline | `shyfem mm_hyd_00.str` | all 1152 timesteps, mass lines match pre-batch baseline (unless Task 9 legitimately shifted projected runs — documented) |
| serial tracer | `shyfem mm_hyd_conz.str` | clean completion |
| OMP 4T tracer | `OMP_NUM_THREADS=4 shyfem mm_hyd_conz.str` | matches OMP 1T diagnostics (Task 3 Step 3) |
| MPI 4R | `mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str` | clean completion, timings ~2s |
| hybrid MPI 4R × OMP 4T | `OMP_NUM_THREADS=4 mpirun --oversubscribe -np 4 shyfem mm_hyd_conz.str` | clean completion (Task 4 Step 4) |

(All with `PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH` from `testcases/examples/mar_menor`.)

- [ ] **Step 3: Update the roadmap checklist**

Tick Batch 1 in `docs/plans/2026-07-18-remediation-roadmap.md` and mark N01/N03/N04/N05/N09/N10/N11/N15/N20/N29 fixed.

- [ ] **Step 4: Push + PR**

```bash
git push -u origin fix/b1-fortran-core-races
gh pr create --base main --title "fix: Batch 1 - Fortran core critical/high fixes (2026-07-18 review)" --body "$(cat <<'EOF'
## Summary
Fixes the 10 critical/high Fortran-core findings from docs/reviews/2026-07-18-full-codebase-deep-review.md:
- N01/N09/N10: revert the save-cached work arrays (OMP task data races from 34ff6dd/38469ab)
- N11: undefer scalar tasks under MPI (MPI_THREAD_FUNNELED violation)
- N04: abort on PETSc KSP divergence (was silently accepted as zeta)
- N05: unfreeze femtime `it` (lagrangian decay/mortality/connectivity)
- N03/N20: calm-wind guards (stress input div-by-zero, hersbach log(0))
- N15: CPP projection reference = midpoint, not half-range
- N29: MPI debug guards vs negative newunit (73e03b2 regression)

## Test plan
- [ ] serial / OMP / MPI / hybrid builds compile (OpenMPI, libmpi.so.40)
- [ ] mar_menor: serial, iconz=2 tracer, OMP 1T==4T agreement, MPI 4R, hybrid 4Rx4T
- [ ] PETSc: mar_menor converges (check silent); forced maxits=1 divergence aborts loudly
- [ ] MPI debug file populated with bmpi_debug_txt=.true.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes (writing-plans checklist)

- **Coverage:** all 10 Batch-1 findings from the roadmap have a task (N01→T1, N09→T2, N10→T3, N11→T4, N04→T5, N05→T6, N03→T7, N20→T8, N15→T9, N29→T10).
- **No placeholders:** every code step shows the actual before/after code; the two contingencies (KSPConvergedReason type name, STR already containing iconz) specify the exact alternative.
- **Consistency:** `btask` name is used identically in both Task 4 sites; `mm_hyd_conz.str` produced in Task 0 is what Tasks 1–4 and 11 consume; all builds consistently use the real Rules.make knobs (`PARALLEL_OMP`/`PARALLEL_MPI`/`SOLVER`), never the inert `MPI=`/`OMP=` names (that's Batch 2's N19).
- **Known risk:** Task 4's OpenMP data-sharing lists (`FIRSTPRIVATE`) must compile under `DEFAULT(NONE)` — if gfortran complains about `btask`, it belongs in `FIRSTPRIVATE` (already added).
