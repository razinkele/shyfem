# Phase 7 OpenMP Loop Parallelization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `!$OMP PARALLEL DO` to three independent element/node loops: bottom friction, diffusivity init, and Munk-Anderson turbulence.

**Architecture:** Each loop iterates over elements or nodes with no cross-iteration data dependencies. Add OpenMP directives with appropriate PRIVATE/SHARED/REDUCTION clauses. The bottom friction loop uses an `IF` clause to disable threading for rare friction types (ireib 8-9) that have node-level write conflicts.

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

Record the `Parallel_TIME` value. Expected: ~2.8s.

**Step 3: Run hybrid benchmark**

```bash
OMP_NUM_THREADS=2 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem mm_hyd_00.str 2>&1 | tail -5
```

Record the `Parallel_TIME` value. Expected: ~1.6-1.7s.

---

### Task 2: Add OpenMP PARALLEL DO to Bottom Friction Loop

**Files:**
- Modify: `src/shyfem/chezy.f90:287-395`

**Step 1: Read the loop and its variable declarations**

Read `src/shyfem/chezy.f90` lines 240-395 to see the full `bottom_friction` subroutine. Note all local variables declared at lines 264-271:

```fortran
integer ie,ii,k,lmax
integer ireib
real hzg,alpha
real hzoff
real uso,vso,uv,uuvv
real rfric,rcd,rr,ss,rho0

real cdf
real uvmin
```

**Step 2: Add the OpenMP directive**

Before line 287 (`do ie=1,nel`), insert:

```fortran
!$OMP PARALLEL DO PRIVATE(ie,lmax,uso,vso,uv,hzg,rfric,rr,rcd,ss,uuvv,ii,k,alpha) &
!$OMP& SCHEDULE(STATIC) IF(ireib <= 7)
```

After line 395 (`end do`), insert:

```fortran
!$OMP END PARALLEL DO
```

The `IF(ireib <= 7)` clause disables threading for ireib 8-9 which write to shared node arrays (`z0bk(k)`). For ireib 0-7, all computations use local scalars and write to unique `ie` indices in output arrays.

The SHARED arrays (`nel`, `ilhv`, `utlov`, `vtlov`, `hdeov`, `czv`, `rfricv`, `rcdv`, `bnstressv`, `hzoff`, `ireib`, `grav`, `rho0`, `uvmin`, `z0bk`, `nen3v`, `ilhkv`) are shared by default.

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
git add src/shyfem/chezy.f90
git commit -m "perf: add OMP PARALLEL DO to bottom friction element loop

Parallelizes do ie=1,nel in bottom_friction. IF(ireib<=7) guard
disables threading for friction types 8-9 that write shared node arrays.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Add OpenMP PARALLEL DO to Diffusivity Init Loop

**Files:**
- Modify: `src/shyfem/diffusion_admin.f90:574-585`

**Step 1: Read the loop**

Read `src/shyfem/diffusion_admin.f90` lines 565-595. The loop is:

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

Variables: `ie`, `area`, `ah`, `lmax`, `l` are local per-iteration. `ahmax` is a max reduction.

**Step 2: Add the OpenMP directive**

Before line 575 (`do ie=1,nel`), insert:

```fortran
!$OMP PARALLEL DO PRIVATE(ie,area,ah,lmax,l) REDUCTION(max:ahmax) SCHEDULE(STATIC)
```

After line 585 (`end do` — the outer one), insert:

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
git add src/shyfem/diffusion_admin.f90
git commit -m "perf: add OMP PARALLEL DO to horizontal diffusivity init loop

Parallelizes one-time initialization loop over elements with max reduction.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Add OpenMP PARALLEL DO to Munk-Anderson Turbulence Loop

**Files:**
- Modify: `src/shyfem/turbulence.f90:188-221`

**Step 1: Read the loop and variable declarations**

Read `src/shyfem/turbulence.f90` lines 120-225. The subroutine `munk_anderson_shell` has:

Declarations (lines 137-152):
```fortran
real shearf2(nlvdi,nkn)       ! stack array — each thread gets own copy
real buoyf2(nlvdi,nkn)        ! stack array
real richard(nlvdi,nkn)       ! stack array
real h(nlvdi)                 ! stack array

integer k,l
integer nlev,flev
integer mode
real ri,vis,dif
real a,b,alpha,beta
```

The loop (lines 188-221):
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
  ! boundary assignments ...
end do
```

**Important**: `shearf2`, `buoyf2`, and `richard` are large stack arrays declared locally in the subroutine. They are populated by `call setm2n2(nlvdi,buoyf2,shearf2)` at line 172 BEFORE the loop and read (not written) inside the loop at unique `(l,k)` indices. `richard` is written at unique `(l,k)` indices. These are SHARED.

`h(nlvdi)` is a small stack array filled per-node by `dep3dnod` — must be PRIVATE.

`dep3dnod` is thread-safe: reads shared module arrays, writes only to the local `h` argument passed in.

**Step 2: Add the OpenMP directive**

Before line 188 (`do k=1,nkn`), insert:

```fortran
!$OMP PARALLEL DO PRIVATE(k,l,nlev,flev,h,ri,vis,dif) SCHEDULE(DYNAMIC)
```

After line 221 (`end do`), insert:

```fortran
!$OMP END PARALLEL DO
```

All other variables used in the loop (`nkn`, `nlvdi`, `mode`, `buoyf2`, `shearf2`, `visv`, `difv`, `richard`, `vistur_c`, `diftur_c`, `a`, `b`, `alpha`, `beta`) are shared by default — they are either read-only or written at unique `(l,k)` indices.

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

**Note**: mar_menor uses GOTM turbulence (iturb=1), not Munk-Anderson (iturb=3). The Munk-Anderson code path won't execute in this test. The test verifies that the directive doesn't break compilation or runtime when the code path is NOT taken.

**Step 4: Commit**

```bash
cd /home/razinka/shyfem
git add src/shyfem/turbulence.f90
git commit -m "perf: add OMP PARALLEL DO to Munk-Anderson turbulence node loop

Parallelizes do k=1,nkn in munk_anderson_shell. Each water column is
independent. SCHEDULE(DYNAMIC) handles varying column depths.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Final Benchmark

**Files:**
- None modified

**Step 1: Run benchmark matrix**

Build is already done from Task 4. Run:

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

**Note**: mar_menor is too small to show measurable gains from these changes. The bottom friction loop has ~600 elements — too few to benefit from threading overhead. Production meshes with 100k+ elements will show the difference.
