# Phase 9 OpenMP Density & Depth Loop Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `!$OMP PARALLEL DO` to the density computation (`rhoset`) and layer depth node loops (`setdepth`).

**Architecture:** Both loops iterate over nodes with no cross-iteration data dependencies. Add OpenMP directives with appropriate PRIVATE/REDUCTION clauses. The density loop uses DYNAMIC scheduling for varying column depths; the depth loop uses STATIC scheduling for uniform work.

**Tech Stack:** Fortran 90/95, OpenMP 4.0+, MPI (OpenMPI), GNU Make

---

### Task 1: Capture Baseline

**Files:**
- None modified

**Step 1: Clean build with hybrid MPI+OMP**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

Expected: Build succeeds.

**Step 2: Run serial benchmark**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record the `Parallel_TIME` value.

**Step 3: Run hybrid benchmark**

```bash
OMP_NUM_THREADS=2 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record the `Parallel_TIME` value.

---

### Task 2: Add OpenMP PARALLEL DO to rhoset Density Loop

**Files:**
- Modify: `src/shyfem/baroclinic.f90:711-745`

**Step 1: Read the loop and its variable declarations**

Read `src/shyfem/baroclinic.f90` lines 660-750 to see the full `rhoset` subroutine. Note all local variables declared at lines 686-695:

```fortran
logical bdebug,debug,bsigma
integer k,l,lmax,lmin
integer nresid,nsigma
real sigma0,rho0,pres,hsigma
real depth,hlayer,hh
real rhop,presbt,presbc,dpresc
real salt
double precision dresid
```

**Step 2: Add the OpenMP directive**

Before line 711 (`do k=1,nkn`), insert:

```fortran
!$OMP PARALLEL DO PRIVATE(k,l,lmin,lmax,depth,presbc,hlayer,hh,rhop, &
!$OMP&   dpresc,presbt,pres,salt,bsigma) &
!$OMP& REDUCTION(+:nresid,dresid) SCHEDULE(DYNAMIC)
```

After line 745 (`end do` — the outer one), insert:

```fortran
!$OMP END PARALLEL DO
```

The PRIVATE list covers all per-iteration scalars. The SHARED arrays (`nkn`, `jlhkv`, `ilhkv`, `hdkov`, `hldv`, `rhov`, `saltv`, `tempv`, `grav`, `rho0`, `sigma0`, `nsigma`) are shared by default — they are either read-only or written at unique `(l,k)` indices. `nresid` and `dresid` are sum reductions.

**Step 3: Build and test**

```bash
cd /home/razinka/shyfem
make clean && PATH=/usr/bin:$PATH make fem OMP=true MPI=true PARTS=METIS METISDIR=/usr
```

Expected: Build succeeds with no warnings about the OpenMP directive.

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=2 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Expected: 1152 timesteps, no errors.

**Step 4: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/baroclinic.f90
git commit -m "perf: add OMP PARALLEL DO to density computation (rhoset)

Parallelizes do k=1,nkn in rhoset. sigma_stp is a pure function,
each node column is independent. SCHEDULE(DYNAMIC) handles varying
column depths. Sum reductions on nresid and dresid.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Add OpenMP PARALLEL DO to setdepth Node Loops

**Files:**
- Modify: `src/shyfem/elems_dealing.f90:1133-1162`

**Step 1: Read the loops**

Read `src/shyfem/elems_dealing.f90` lines 1125-1170. The loops are:

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
              ! error output and stop
            end if
          end do
        end do
```

Variables: `k`, `lmax`, `lmin`, `levmin`, `l`, `areafv`, `h` are local per-iteration.

**Step 2: Add the OpenMP directive**

Before line 1133 (`do k=1,nkn_inner`), insert:

```fortran
!$OMP PARALLEL DO PRIVATE(k,lmax,lmin,levmin,l,areafv,h) SCHEDULE(STATIC)
```

After line 1162 (`end do` — the outer one), insert:

```fortran
!$OMP END PARALLEL DO
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
cd /home/razinka/shyfem
git add src/shyfem/elems_dealing.f90
git commit -m "perf: add OMP PARALLEL DO to setdepth node-to-depth loop

Parallelizes do k=1,nkn_inner in setdepth. Each node accesses
unique hdkn(:,k) and area(:,k) indices. SCHEDULE(STATIC) for
uniform work per node.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Final Benchmark

**Files:**
- None modified

**Step 1: Run benchmark matrix**

Build is already done from Task 3. Run:

**Serial (1P, 1T):**
```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str 2>&1 | tail -5
```

**MPI 4P, 1 thread:**
```bash
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

**MPI 4P, 2 threads:**
```bash
OMP_NUM_THREADS=2 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record all times. Compare against Task 1 baseline.

**Note**: mar_menor is too small to show measurable gains from these changes. The density loop has ~1500 nodes — too few for meaningful thread parallelism on this test case. Production meshes with 100k+ nodes will show the difference.
