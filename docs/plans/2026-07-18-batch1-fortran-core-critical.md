# Batch 1: Fortran Core Critical/High Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Rev 2** — corrected after the 2026-07-18 adversarial plan review (workflow `wf_8fb8c9c0-a50`, 28 confirmed findings applied; see PR discussion).

**Goal:** Fix the 10 critical/high Fortran-core findings from the 2026-07-18 deep review (N01, N03, N04, N05, N09, N10, N11, N15, N20, N29 in `docs/reviews/2026-07-18-full-codebase-deep-review.md`): the OpenMP save-caching races, the MPI-from-tasks violation, unchecked PETSc convergence, the femtime freeze, two calm-wind singularities, the projection-midpoint bug, and the MPI-debug-unit regression.

**Architecture:** All fixes are surgical reverts or guards in existing files — no new modules. The OMP-race fixes revert the `allocatable, save` "caching" (commits `34ff6dd`/`38469ab`) back to per-call allocatables (plus a critical-section guard on one remaining lazy-init); the MPI-from-tasks fix undefers OpenMP tasks when MPI is active AND moves the task region from `SINGLE` to `MASTER` so MPI calls run on the MPI main thread; the rest are point guards/corrections.

**Tech Stack:** Fortran 90 (gfortran), OpenMP tasks, OpenMPI, PETSc (optional solver), GNU Make. No unit-test framework exists for the Fortran core — verification is build + targeted mar_menor runs (see Task 0).

## Global Constraints

- Always build/run with OpenMPI: prefix every make/run with `PATH=/usr/bin:$PATH` (CLAUDE.md Intel-MPI trap). After MPI builds verify `ldd src/shyfem/shyfem | grep mpi` shows `libmpi.so.40`.
- Real build knobs are `PARALLEL_OMP` (`false` default), `PARALLEL_MPI` (`NODE` default), `SOLVER` (`SPARSKIT` default) — Rules.make:110-190. Pass them on the make command line (do not edit Rules.make). PETSc builds additionally need `PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real` (README.md:58; without it `make` aborts with "PETSC_DIR directory is empty").
- **cwd discipline:** every build block starts with `cd /home/razinka/shyfem`; every run block starts with `cd /home/razinka/shyfem/testcases/examples/mar_menor`. This is load-bearing: the mar_menor Makefile defines a **do-nothing `fem` target** (`fem: nothing` → `@true`), so a `make fem` issued from the test directory silently builds nothing and you test a stale binary.
- **Line numbers** in this plan refer to HEAD `ed6505f`. They shift as tasks execute (Task 2 removes ~16 lines above Task 3's region in the same file). Always locate edit sites by the quoted code, not by line number alone.
- The Fortran sources use **tab indentation** — match it exactly in edits.
- Keep existing error-stop style per file (bare-stop modernization is Batch 5's job, do not mix it in here).
- Branch: `fix/b1-fortran-core-races` off `fix/codebase-review-remediations`. Conventional commits, one commit per task.

---

### Task 0: Branch + tracer test config + baselines

**Files:**
- Create: `testcases/examples/mar_menor/mm_hyd_conz.str` (generated copy, not committed)

**Interfaces:**
- Produces: `mm_hyd_conz.str` — mar_menor config with two **differentiated** tracers (`iconz = 2`, per-tracer decay rates) and `levdbg = 3` so `scal3sh` writes per-substep per-tracer mass lines (`scal3sh_conz_ 1:` / `scal3sh_conz_ 2:`) into the info file — the observable that all later race checks diff. Baselines: `/tmp/claude-1000/b1/base_00.log` (stock case, pre-edit binary) and `/tmp/claude-1000/b1/base_conz.inf` (tracer case info file).

- [ ] **Step 1: Create the branch and the scratch dir**

```bash
cd /home/razinka/shyfem
git checkout -b fix/b1-fortran-core-races
mkdir -p /tmp/claude-1000/b1
```

- [ ] **Step 2: Build the default (NODE) binary**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem
```
Expected: build completes; `src/shyfem/shyfem` exists.

- [ ] **Step 3: Create the tracer config**

`iconz = 2` makes `tracer_compute_multi` spawn two concurrent scalar tasks. The tracers MUST be differentiated or the N09 race (tracers sharing BC/work arrays) overwrites identical values with identical values and stays invisible: `idecay = 1` with per-tracer `taupar` decay times makes the two fields diverge from step 1 (decay runs inside each task right after `scal_adv` — `conz_admin.f90:461-462`, per-tracer array accepted at `conz_admin.f90:165`). `levdbg = 3` enables the per-substep mass diagnostics (`concentration.f90:800-809`).

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
sed "/\$para/a \\\t iconz = 2\n\t conref = 1.\n\t idecay = 1\n\t taupar = 43200. 86400.\n\t levdbg = 3" mm_hyd_00.str > mm_hyd_conz.str
grep -nE "iconz|idecay|taupar|levdbg" mm_hyd_conz.str
```
Expected: all four parameters appear once, inside `$para`. (`mm_hyd_00.str` sets none of them at HEAD — verified.) If shyfem later rejects a parameter placement, fix the STR here, not the model.

- [ ] **Step 4: Capture BOTH baselines with the pre-edit binary**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str   | tee /tmp/claude-1000/b1/base_00.log
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/base_conz.log
cp mm_hyd_conz.inf /tmp/claude-1000/b1/base_conz.inf
grep -c "scal3sh_conz_" /tmp/claude-1000/b1/base_conz.inf
```
Expected: both runs complete all 1152 timesteps; the grep count is **non-zero** (this proves the oracle has data — if it is 0, stop and fix the config before touching any source). `base_00.log` is the regression reference for Tasks 6/7/8/9/11 — it cannot be recreated once sources change.

- [ ] **Step 5: Confirm nothing is staged**

```bash
cd /home/razinka/shyfem && git status
```
Expected: clean tree (the `.str`, `.inf`, and output files are generated/untracked — do not commit them).

---

### Task 1: N01 (critical) — revert `conz3d_omp` save-cached work arrays

**Files:**
- Modify: `src/shyfem/concentration_omp.f90:167-214` (declarations + lazy-init), keep `:353-357` (DEALLOCATE)

**Interfaces:**
- Produces: thread-safe `conz3d_omp` — per-call local allocatables `cn/co/cdiag/clow/chigh`.

- [ ] **Step 1: Capture the failing behavior (best-effort — races are probabilistic)**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str | tee /tmp/claude-1000/b1/pre_t1_omp4.log
cp mm_hyd_conz.inf /tmp/claude-1000/b1/pre_t1_omp4.inf 2>/dev/null || true
```
Expected (any of): `Attempt to DEALLOCATE unallocated`, `Attempting to allocate already allocated`, segfault, FPE trap, or a run whose `scal3sh_conz_` lines differ from `base_conz.inf`. Record what happened; a clean pass does NOT invalidate the fix (races are timing-dependent).

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

Also delete the dead commented block at lines 167–171 (the old automatic-array declarations).

- [ ] **Step 3: Make allocation unconditional**

Replace the five lazy-init blocks (lines 195–214, `if (.not. allocated(cn)) then … end if` × 5) with:

```fortran
	allocate(cn(nlvddi,nkn),co(nlvddi,nkn),cdiag(nlvddi,nkn), &
     &		clow(nlvddi,nkn),chigh(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conz3d_omp: allocation failed'
```

Leave the `DEALLOCATE` statements at lines 353–357 in place (now correct: local arrays, freed every call — matching pre-`38469ab` behavior).

- [ ] **Step 4: Build**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
```
Expected: compiles cleanly.

- [ ] **Step 5: Interim run (full acceptance comes after Task 3)**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str
```
Expected: completes all timesteps without abort. (The 1T-vs-4T agreement oracle needs Tasks 2–3 too — it is run as the acceptance gate in Task 3 Step 4.)

- [ ] **Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/concentration_omp.f90
git commit -m "fix(omp): revert conz3d_omp save-cached work arrays to per-call (N01)

save locals are shared across concurrent OMP tasks; the lazy-init cache
raced between the barocl and tracer tasks and was deallocated mid-use.
Reverts the caching from 38469ab (which was a no-op anyway - the arrays
were still deallocated every call)."
```

---

### Task 2: N09 (high) — revert `scal_adv` family save arrays + guard `limit_scalar` init

**Files:**
- Modify: `src/shyfem/concentration.f90:298-321` (`scal_adv`), `:397-414` (`scal_adv_nudge`), `:486-505` (`scal_adv_fact`), `:2467-2472` region (`limit_scalar` first-call init)

**Interfaces:**
- Produces: thread-safe `scal_adv`/`scal_adv_nudge`/`scal_adv_fact` with per-call `r3v/load/cobs/rtauv/wsinkv`; race-free `limit_scalar` first-call init (it is called from `scal3sh` at concentration.f90:776 — inside the same concurrent path).

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

The declarations (`real, allocatable, save :: r3v(:,:)` / `wsinkv` / `load`, around line 397 — locate by the `scal_adv_nudge` subroutine header) lose `, save`; its `if( .not. allocated(r3v) ) then … end if` block becomes:

```fortran
	allocate(r3v(nlvdi,nkn),load(nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv_nudge: allocation failed'
	allocate(wsinkv(0:nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv_nudge: allocation failed'
```

- [ ] **Step 3: `scal_adv_fact` — same transformation**

Declarations (`r3v/cobs/rtauv`, around line 486 — locate by the `scal_adv_fact` subroutine header) lose `, save`; the guard block becomes:

```fortran
	allocate(r3v(nlvdi,nkn),cobs(nlvdi,nkn),rtauv(nlvdi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop scal_adv_fact: allocation failed'
```

- [ ] **Step 4: Guard `limit_scalar`'s first-call init**

`limit_scalar` (called from `scal3sh` → inside every concurrent scalar task) keeps a legitimate persistent cache (`mask` + getpar-loaded limits) behind `if( icall == 0 )` (line 2467) — but the guard itself races: two tasks can both see `icall == 0` on the first timestep and double-allocate. Wrap the entire first-call block (from `if( icall == 0 ) then` at line 2467 through its matching `end if`) in a named critical section:

```fortran
!$OMP CRITICAL (limit_scalar_init)
	if( icall == 0 ) then
	  ...existing body unchanged (bwrite/mask allocation/getpar loads)...
	end if
!$OMP END CRITICAL (limit_scalar_init)
```

Move the existing `icall = 1` from the top of the block (line 2468) to the last line before the `end if`, so a second thread entering the critical section after the first finishes sees fully-initialized state.

- [ ] **Step 5: Verify remaining save-array sites are exactly the expected ones**

```bash
cd /home/razinka/shyfem
grep -n 'allocatable, save' src/shyfem/concentration.f90 src/shyfem/concentration_omp.f90
```
Expected after Tasks 1–2: exactly two hits — the `conzstab` block (concentration.f90:~1722, Task 3) and `limit_scalar`'s `logical, allocatable, save :: mask(:,:)` (concentration.f90:~2461, which is CORRECT to keep: it is a genuine one-time cache, now guarded by Step 4's critical section).

- [ ] **Step 6: Build + run**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str
```
Expected: completes all timesteps, no error stop.

- [ ] **Step 7: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/concentration.f90
git commit -m "fix(omp): revert scal_adv/_nudge/_fact save arrays; guard limit_scalar init (N09)

Concurrent tracer tasks shared one r3v/load/cobs/rtauv/wsinkv set, so a
tracer could be advected with another tracer's boundary values. Also
wraps limit_scalar's racy first-call init (mask allocate + getpar cache)
in a named critical section - it is entered from every concurrent task."
```

---

### Task 3: N10 (high) — revert `conzstab` save-cached arrays + acceptance gate

**Files:**
- Modify: `src/shyfem/concentration.f90` — `conzstab` declarations (`:1722-1728` at HEAD; **~16 lines lower after Task 2** — locate by the `big arrays (cached with save` comment) and allocation block (`:1761-1772` at HEAD)

- [ ] **Step 1: Remove `save` from declarations**

Locate the block via `grep -n 'cached with save' src/shyfem/concentration.f90`. Replace the seven declarations:

```fortran
	double precision, allocatable :: cn(:,:)
	double precision, allocatable :: co(:,:)
	double precision, allocatable :: cdiag(:,:)
	double precision, allocatable :: clow(:,:)
	double precision, allocatable :: chigh(:,:)
        real, allocatable :: cwrite(:,:)
        real, allocatable :: c2write(:)
```

and replace BOTH stale comments — the declaration header (`big arrays (cached with save to avoid per-timestep allocation)`) and the allocation-section header (`allocation (cached - allocate once, reuse across calls)`) — with:

```fortran
!------------------------------------------------------------
! big work arrays (per-call: conzstab runs concurrently from OMP tasks,
! so these must NOT be save/shared - see 2026-07-18 review N10)
!------------------------------------------------------------
```

- [ ] **Step 2: Make allocation unconditional**

Replace the `if( .not. allocated(cn) ) then … end if` block (the one allocating cn/co/cdiag/clow/chigh/cwrite/c2write) with:

```fortran
	allocate(cn(nlvddi,nkn),co(nlvddi,nkn),cdiag(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conzstab: allocation failed'
	allocate(clow(nlvddi,nkn),chigh(nlvddi,nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conzstab: allocation failed'
	allocate(cwrite(nlvddi,nkn),c2write(nkn),stat=ierr)
	if( ierr /= 0 ) stop 'error stop conzstab: allocation failed'
```

- [ ] **Step 3: Build**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true
```

- [ ] **Step 4: ACCEPTANCE GATE — OMP 1T vs 4T per-tracer agreement**

The oracle: SHYFEM's colored-subset OMP design is deterministic, so 1-thread and 4-thread runs must produce identical per-tracer diagnostics. Diff **per tracer** (concurrent tasks interleave their write order into the shared info unit, so a whole-file diff would false-fail on line ordering):

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str
cp mm_hyd_conz.inf /tmp/claude-1000/b1/post_t3_omp1.inf
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_conz.str
cp mm_hyd_conz.inf /tmp/claude-1000/b1/post_t3_omp4.inf
for t in 1 2; do
  diff <(grep "scal3sh_conz_ $t:" /tmp/claude-1000/b1/post_t3_omp1.inf) \
       <(grep "scal3sh_conz_ $t:" /tmp/claude-1000/b1/post_t3_omp4.inf) \
    && echo "tracer $t: OK"
done
```
Expected: `tracer 1: OK` and `tracer 2: OK` (empty diffs, or last-digit float noise at most). Also compare tracer 1 against the pre-batch serial baseline: `diff <(grep "scal3sh_conz_ 1:" /tmp/claude-1000/b1/base_conz.inf) <(grep "scal3sh_conz_ 1:" /tmp/claude-1000/b1/post_t3_omp1.inf)` — must match (the reverts must not change serial results). This is the batch's key acceptance check for the race family.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/concentration.f90
git commit -m "fix(omp): revert conzstab save-cached arrays to per-call (N10)

conzstab is entered concurrently by every scalar task's stability check;
the shared save arrays corrupted the istot accumulation."
```

---

### Task 4: N11 (high) — MPI calls from OMP tasks: undefer under MPI + run on master thread

**Files:**
- Modify: `src/shyfem/shyfem_subs.f90:1009-1033` (`run_scalar` task region), `src/shyfem/conz_admin.f90:446-475` (`tracer_compute_multi` task loop), `src/shyfem/sedim_admin.f90:~4298-4390` (`scn_compute` task loop — same violation via `scal_adv_fact`)

**Interfaces:**
- Consumes: `shympi_is_parallel()` — module function of `shympi`. **None of the three routines currently has `use shympi`** (verified) — each edit below adds the needed `use` line.
- Produces: under MPI, scalar/sediment tasks run undeferred (sequential, in program order) on the **master** thread — so all shympi calls inside `scal3sh`/`conz3d`/`conzstab` are issued by the MPI main thread in identical order on every rank (true `MPI_THREAD_FUNNELED` compliance). Pure-OMP runs keep full task concurrency (deferred tasks are stolen by the team at the `END PARALLEL` barrier).

- [ ] **Step 1: `run_scalar` — add use, gate tasks, SINGLE → MASTER**

In `src/shyfem/shyfem_subs.f90`, in `run_scalar`: add to the use statements (next to the existing `use` lines at the routine top):

```fortran
	use shympi, only : shympi_is_parallel
```

Add to the declarations (with the other local declarations, BEFORE any executable statement):

```fortran
	logical :: btask
```

Add as the first executable statement after the getpar calls (before the `!$OMP PARALLEL` at line 1009):

```fortran
	btask = .not. shympi_is_parallel()	!MPI: undefer tasks -> master thread, program order
```

Then change the region so the task-generating construct is `MASTER`, not `SINGLE` (with `SINGLE`, an arbitrary team thread generates — and under `IF(.false.)` *executes* — the tasks, which violates `MPI_THREAD_FUNNELED`'s main-thread-only rule; the master thread IS the thread that called `MPI_Init_thread`):

```fortran
!$OMP PARALLEL

!$OMP MASTER

!$OMP TASK IF ( btask )
	call barocl(1)
!$OMP END TASK

!$OMP TASK IF ( iconz > 0 .and. btask )
	call tracer_compute
!$OMP END TASK

!$OMP TASK IF ( ibfm > 0 .and. btask )
	call bfm_run
!$OMP END TASK

!$OMP TASKWAIT

!$OMP END MASTER

!$OMP END PARALLEL
```

(Also delete the now-orphaned leading `!$OMP TASKWAIT` that sat directly after `!$OMP SINGLE` at line 1013, and the commented `TASKGROUP` lines if in the way. Non-master threads skip the MASTER block and wait at the `END PARALLEL` barrier, where they steal deferred tasks — pure-OMP concurrency is preserved. `iconz`/`ibfm` in the IF clauses only ever controlled deferral, never whether the call runs.)

- [ ] **Step 2: `tracer_compute_multi` — add use, gate the per-tracer tasks**

In `src/shyfem/conz_admin.f90`, in the routine containing the `!$OMP TASK` at line 451: add to its use list (after `use mkonst`, before `implicit none`):

```fortran
	use shympi, only : shympi_is_parallel
```

Declare `logical :: btask` with the locals, set it before the `do i=1,nvar` loop (line 446):

```fortran
	btask = .not. shympi_is_parallel()
```

and extend the TASK directive (lines 451–453) — note `btask` joins FIRSTPRIVATE:

```fortran
!$OMP  TASK IF(btask) FIRSTPRIVATE(i,rkpar,wsink,difhv,difv,difmol,     &
!$OMP& idconz,what,dt,nlvdi,idecay,blinfo,bage,btask)                   &
!$OMP&  SHARED(conzv,tauv,massv) DEFAULT(NONE)
```

- [ ] **Step 3: `scn_compute` (sediments) — same violation, same gate**

`scn_compute` (src/shyfem/sedim_admin.f90:~4298) has its own `PARALLEL/SINGLE` region with a per-sediment-class `!$OMP TASK` (~line 4381) whose body reaches `scal_adv_fact` → `scal3sh` → `shympi_exchange_3d_node`. Apply the identical pattern: add `use shympi, only : shympi_is_parallel` to `scn_compute`, declare/set `btask` before the `do is = 1,nscls` loop, add `IF(btask)` to the TASK directive (and `btask` to its data-sharing clause if it uses `DEFAULT(NONE)`/explicit lists), and convert that region's `SINGLE` to `MASTER` the same way as Step 1. Completeness check — every task-spawning site in the model core is now gated:

```bash
cd /home/razinka/shyfem
grep -rn '\$OMP *TASK\b' src/shyfem/*.f90
```
Expected: hits only in `shyfem_subs.f90`, `conz_admin.f90`, `sedim_admin.f90` (all gated above) and `concentration_omp.f90`/`stability.f90`-style *inner element-loop* tasks — the inner tasks make no MPI calls (they partition element arithmetic) and stay ungated by design; note any other hit and evaluate it the same way before proceeding.

- [ ] **Step 4: Build serial + OMP + hybrid**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true PARTS=METIS METISDIR=/usr
ldd src/shyfem/shyfem | grep mpi
```
Expected: compiles; `libmpi.so.40` (OpenMPI). (`PARALLEL_MPI=NODE` is the default — this single build IS the hybrid build.)

- [ ] **Step 5: Hybrid smoke run (the previously-broken configuration)**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=4 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH \
  mpirun --oversubscribe -np 4 shyfem mm_hyd_conz.str
```
Expected: completes all timesteps with no deadlock/crash.

- [ ] **Step 6: Pure-OMP regression**

Re-run Task 3 Step 4's acceptance gate — must still pass (MASTER instead of SINGLE must not change pure-OMP results).

- [ ] **Step 7: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/shyfem_subs.f90 src/shyfem/conz_admin.f90 src/shyfem/sedim_admin.f90
git commit -m "fix(mpi+omp): run scalar/sediment tasks on master thread, undeferred under MPI (N11)

scal3sh issues shympi exchanges/reductions; running it from concurrent
OMP tasks (spawned from a SINGLE region, i.e. an arbitrary thread)
violated the MPI_THREAD_FUNNELED level requested at init. Tasks are now
generated from the MASTER thread and undeferred when MPI is active, so
all MPI calls run on the MPI main thread in program order per rank.
Pure-OMP runs keep full task concurrency. Covers run_scalar,
tracer_compute_multi and the sediment scn_compute task region."
```

---

### Task 5: N04 (high) — check PETSc/AmgX solver convergence

**Files:**
- Modify: `src/shyfem/mod_petsc_system.f90:581-643` (`solve_PETSc`, `solve_AmgX`)
- Modify: `src/shyfem/amgx_c_wrapper_dummy.f90` (add two missing dummy stubs — every `SOLVER=PETSC` build links this file; without the stubs the new calls fail at link)

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

In `solve_AmgX`'s **declaration section** (with the existing `external :: CAmgX_SetA` / `CAmgX_Solve`, lines 626–627) add:

```fortran
        external :: CAmgX_GetIters
        external :: CAmgX_GetResidual
```

and in the executable section, after the `CAmgX_Solve` call (line 633):

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

- [ ] **Step 3: Add the missing dummy stubs**

`SOLVER=PETSC` builds link `amgx_c_wrapper_dummy.o` (src/shyfem/Makefile:115-118), which defines only SetA/Solve/etc. — NOT GetIters/GetResidual. Append to `src/shyfem/amgx_c_wrapper_dummy.f90`, mirroring the existing stub style:

```fortran
      subroutine CAmgX_GetIters(AmgX_Solver,iters,perr)
       use iso_c_binding
        implicit none
           type(c_ptr) :: AmgX_Solver
           integer(kind=c_int) :: iters
           integer :: perr
           stop "ERROR CAmgX_dummy, AmgX wasn't enabled at compilation"
      end subroutine CAmgX_GetIters

      subroutine CAmgX_GetResidual(AmgX_Solver,iter,residual,perr)
       use iso_c_binding
        implicit none
           type(c_ptr) :: AmgX_Solver
           integer(kind=c_int) :: iter
           real(kind=c_double) :: residual
           integer :: perr
           stop "ERROR CAmgX_dummy, AmgX wasn't enabled at compilation"
      end subroutine CAmgX_GetResidual
```

(Unreachable in dummy builds — `solve_AmgX`'s `CAmgX_Solve` dummy already stops first. A real AmgX build must provide the C implementations; note this in the commit body.)

- [ ] **Step 4: Build with PETSc and run mar_menor on the PETSc solver**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem SOLVER=PETSC \
  PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real \
  PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 2 shyfem mm_hyd_00.str
```
Expected: links (proves the stub/binding names are right) and the run completes — mar_menor converges, so the new check must NOT fire. If it aborts with the new message, the check is wired backwards — stop and re-read the reason-code sign convention.

- [ ] **Step 5: Negative test — force a divergence**

```bash
grep -n 'KSPSetTolerances' src/shyfem/mod_petsc_system.f90
```
Temporarily set the `maxits` argument at that call site to `1`, rebuild (same command as Step 4), rerun. Expected: aborts early with `PETSc KSP solve DIVERGED, KSPConvergedReason = -3` (DIVERGED_ITS) instead of silently continuing. **Revert the tolerance edit**, rebuild, confirm the clean run again.

- [ ] **Step 6: Restore the default build**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem
```

- [ ] **Step 7: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/mod_petsc_system.f90 src/shyfem/amgx_c_wrapper_dummy.f90
git commit -m "fix(petsc): abort on KSP divergence instead of accepting garbage zeta (N04)

KSPSolve returns perr=0 even when the Krylov solve diverges; the wrong
iterate was silently committed as the free surface. Adds an AmgX
iters/residual sanity check (+ the matching dummy-wrapper stubs; a real
AmgX build must provide CAmgX_GetIters/GetResidual). Restores parity
with SPARSKIT's hard stop."
```

---

### Task 6: N05 (high) — unfreeze femtime `it` / set `itend`

**Files:**
- Modify: `src/shyfem/time_admin.f90:359` (init) and `:703` (per-step update)

- [ ] **Step 1: Set `itend` at init**

Line 358–359:

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

Line 703 (inside `set_timestep`, after `idt = dt`): replace `!it = t_act` with:

```fortran
	if( abs(t_act) < 2.1d9 ) it = nint(t_act)	!legacy femtime clock
```

(The guard prevents integer overflow for simulations beyond ~68 years of model seconds — the failure mode that motivated commenting it out; consumers operate on second-scale differences well inside the range.)

- [ ] **Step 3: Confirm the consumers see live time**

```bash
cd /home/razinka/shyfem
grep -rn 'use femtime' src/shyfem/lagrange_decay.f90 src/shyfem/lagrange_connect.f90
grep -nE 'it *- *lgr_ar|t *= *it' src/shyfem/lagrange_decay.f90
```
Expected: `use femtime` present in both; the second grep shows the age/decay computations consuming `it` (lines 107, 152, 181, 225 at HEAD — particle age `it-lgr_ar(...)%init%time`).

- [ ] **Step 4: Build + regression vs captured baseline**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str | tee /tmp/claude-1000/b1/post_t6.log
diff /tmp/claude-1000/b1/post_t6.log /tmp/claude-1000/b1/base_00.log | head -20
```
Expected: clean run; diff empty except timestamp/timing lines (mar_menor has no lagrangian — the fix must be behavior-neutral here).

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem
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

Replace the loop body (lines 917–927):

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

- [ ] **Step 2: Build + neutrality check**

Honest scope note: mar_menor supplies wind *velocity* (not stress), so the changed `bstress` branch never executes in this test — verification here is (a) compile, (b) unchanged regression vs baseline, (c) the code-level guard being self-evidently total. A stress-forcing case with a calm record would previously SIGFPE under the NORMAL profile's traps.

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str | tee /tmp/claude-1000/b1/post_t7.log
diff /tmp/claude-1000/b1/post_t7.log /tmp/claude-1000/b1/base_00.log | head -20
```
Expected: clean run, diff empty except timing lines.

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem
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

(0.1 m/s is far below the ~2 m/s validity threshold of the Hersbach fit; at wxy=0 the old code computed `log(0)` → -Inf and a negative base raised to p=-12. Like Task 7, this branch — `itdrag=5` — is not exercised by mar_menor; verification is compile + unchanged regression.)

- [ ] **Step 2: Build + neutrality run + commit**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str | tee /tmp/claude-1000/b1/post_t8.log
diff /tmp/claude-1000/b1/post_t8.log /tmp/claude-1000/b1/base_00.log | head -20
cd /home/razinka/shyfem
git add src/shyfem/meteo_forcing.f90
git commit -m "fix(meteo): floor wind speed in hersbach_cd drag formula (N20)

itdrag=5 with calm wind computed log(0) and a negative fractional
power -> NaN drag coefficient."
```
Expected: clean run, diff empty except timing lines.

---

### Task 9: N15 (high) — proj_geo2cart: midpoint, not half-range

**Files:**
- Modify: `src/utils/shyutilmpi/coordinates.f90:191-193`

- [ ] **Step 1: Fix the reference point**

Lines 191–193:

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

(The CPP projection reference must be the domain *midpoint*. The old code put it at half the *range* — e.g. a basin at lat 37.7° projected around lat ≈ 0.15°, so `cos(lat0)` ≈ 1 instead of ≈ 0.79: derived cartesian x-distances ~27% too long. Affects everything downstream of `xcartv/ycartv` for lat/lon basins — notably wave-module distances.)

- [ ] **Step 2: Build + classify the result delta**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:$PATH shyfem mm_hyd_00.str | tee /tmp/claude-1000/b1/post_t9.log
diff /tmp/claude-1000/b1/post_t9.log /tmp/claude-1000/b1/base_00.log | head -40
```
Decision rule: **empty diff** (mod timing lines) → mar_menor never calls proj_geo2cart (cartesian basin); record "no regression, fix latent". **Non-empty diff** → the basin is lat/lon and the change is the *intended correction*: paste the diff summary into the PR body under "expected result change (N15)". Either outcome passes; what fails is silence about a non-empty diff.

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem
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

(Leave the dated revision-log comment at mpi_ghost.f90:42 untouched — it records 2024 history.) Confirm completeness:

```bash
cd /home/razinka/shyfem
grep -rn 'my_unit > 0\|my_unit>0' src/ | grep -v '^\S*:[0-9]*:!'
```
Expected: no executable-code hits left.

- [ ] **Step 2: Verify the debug file actually gets content again**

```bash
cd /home/razinka/shyfem
grep -n 'bmpi_debug_txt' src/utils/shympi/mpi_node.f90 | head -3
```
Flip `bmpi_debug_txt = .false.` to `.true.` **temporarily**, then:

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make fem PARTS=METIS METISDIR=/usr
cd /home/razinka/shyfem/testcases/examples/mar_menor
PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 2 shyfem mm_hyd_00.str
wc -l mpi_debug_*.txt
```
Expected: the `mpi_debug_*.txt` files now contain the ghost/basin sections (pre-fix they held only the 5 header lines). **Revert the `bmpi_debug_txt` toggle**, rebuild (`cd /home/razinka/shyfem && PATH=/usr/bin:$PATH make fem`).

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem
git add src/utils/shympi/mpi_ghost.f90 src/utils/shympi/mpi_basin.f90
git commit -m "fix(mpi): debug guards must test my_unit /= 0 after newunit= change (N29)

73e03b2 switched the debug file to newunit=, which returns a negative
unit; every my_unit > 0 guard silently disabled the diagnostics that
commit set out to improve."
```

---

### Task 11: Full verification matrix + PR

**Files:** none (verification + PR only)

- [ ] **Step 1: Build matrix (three genuinely distinct configs)**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem                       # A: default (MPI NODE, no OMP)
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem PARALLEL_OMP=true \
  PARTS=METIS METISDIR=/usr                                                          # B: hybrid (MPI NODE + OMP)
PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem SOLVER=PETSC \
  PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real \
  PARALLEL_MPI=NODE PARTS=METIS METISDIR=/usr                                        # C: PETSc
ldd src/shyfem/shyfem | grep mpi    # must show libmpi.so.40 after each
```
Expected: all three compile clean. Finish on config **B** (rebuild it last) for the run matrix.

- [ ] **Step 2: Run matrix (mar_menor; all from `cd /home/razinka/shyfem/testcases/examples/mar_menor`, `PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH`)**

| Config | Command | Must show |
|---|---|---|
| serial stock | `shyfem mm_hyd_00.str` | all 1152 timesteps; diff vs `/tmp/claude-1000/b1/base_00.log` empty except timing lines — **unless** Task 9 Step 2 classified a legitimate projection delta (then it must match Task 9's recorded diff) |
| serial tracer | `shyfem mm_hyd_conz.str` | clean completion; `scal3sh_conz_` lines present in `.inf` |
| OMP 1T vs 4T tracer | Task 3 Step 4's gate, re-run | per-tracer diffs clean |
| MPI 4R stock | `mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str` | clean completion, ~2s |
| hybrid 4R × 4T tracer | `OMP_NUM_THREADS=4 mpirun --oversubscribe -np 4 shyfem mm_hyd_conz.str` | clean completion (Task 4 Step 5) |

- [ ] **Step 3: Update the roadmap checklist**

Tick Batch 1 in `docs/plans/2026-07-18-remediation-roadmap.md` and mark N01/N03/N04/N05/N09/N10/N11/N15/N20/N29 fixed.

- [ ] **Step 4: Push + PR (stacked on the parent branch)**

The parent `fix/codebase-review-remediations` is not merged to main (open PR #40 with 73e03b2 + the review/plan docs), so a `--base main` PR would smuggle those commits into this diff. Create a **stacked PR**; retarget to main only after PR #40 merges (then rebase onto main first).

```bash
cd /home/razinka/shyfem
git push -u origin fix/b1-fortran-core-races
gh pr create --base fix/codebase-review-remediations \
  --title "fix: Batch 1 - Fortran core critical/high fixes (2026-07-18 review)" --body "$(cat <<'EOF'
## Summary
Fixes the 10 critical/high Fortran-core findings from docs/reviews/2026-07-18-full-codebase-deep-review.md:
- N01/N09/N10: revert the save-cached work arrays (OMP task data races from 34ff6dd/38469ab) + guard limit_scalar's lazy init
- N11: scalar/sediment tasks generated from MASTER and undeferred under MPI (true MPI_THREAD_FUNNELED compliance)
- N04: abort on PETSc KSP divergence (was silently accepted as zeta) + AmgX sanity check + dummy stubs
- N05: unfreeze femtime `it` (lagrangian decay/mortality/connectivity)
- N03/N20: calm-wind guards (stress input div-by-zero, hersbach log(0)) — latent branches, compile+neutrality verified
- N15: CPP projection reference = midpoint, not half-range (result delta, if any, documented below)
- N29: MPI debug guards vs negative newunit (73e03b2 regression)

Stacked on fix/codebase-review-remediations (PR #40); rebase+retarget to main after #40 merges.

## Test plan
- [ ] builds A (default) / B (hybrid OMP+MPI) / C (PETSc, with PETSC_DIR) compile; libmpi.so.40 linked
- [ ] mar_menor: stock serial vs pre-batch baseline; iconz=2 tracer case emits scal3sh_conz_ diagnostics
- [ ] OMP 1T vs 4T per-tracer diff clean; hybrid 4Rx4T clean; MPI 4R clean
- [ ] PETSc: mar_menor converges (check silent); forced maxits=1 divergence aborts loudly
- [ ] MPI debug file populated with bmpi_debug_txt=.true.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes (writing-plans checklist, rev 2)

- **Coverage:** all 10 Batch-1 findings have a task (N01→T1, N09→T2, N10→T3, N11→T4, N04→T5, N05→T6, N03→T7, N20→T8, N15→T9, N29→T10).
- **Review findings applied:** all 28 confirmed findings of plan-review `wf_8fb8c9c0-a50` are incorporated — notably: `use shympi` added explicitly in all three Task 4 routines; SINGLE→MASTER for true FUNNELED compliance; the sediment `scn_compute` task site gated; the acceptance oracle rebuilt on `scal3sh_conz_` info-file lines with `levdbg=3` + per-tracer decay differentiation (the old `mass|conz` stdout grep matched nothing); PETSC_DIR on every PETSc build; AmgX dummy stubs; `limit_scalar` init race guarded; cwd discipline everywhere (mar_menor's do-nothing `fem` target); `base_00.log` baseline captured before any edit; stacked PR base; Task 3 line-drift note; build matrix deduplicated.
- **Known risks:** Task 4's `MASTER` conversion changes which thread generates tasks — pure-OMP re-verified by re-running the Task 3 gate (Step 6). `KSPConvergedReason`/`PetscEnum` contingency stated in place. The refuted review finding (itend overflow guard) was intentionally not applied.
