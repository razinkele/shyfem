# Lagrangian Particles under MPI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A particle run on 2 or 4 MPI processes gives the serial particle tracks and a `.lgr.shy` file the existing readers accept.

**Architecture:** Each rank adds flux contributions for its own nodes only and the partial sums are added across the ranks that hold an element. A particle lives on exactly one rank and is handed over, with the time left in the step, when it reaches a side with no neighbour there or when a position search fails locally. Ids are numbered as in a serial run and rank 0 writes the unchanged file layout from records the ranks prepare.

**Tech Stack:** Fortran 90 (gfortran), OpenMPI (`include 'mpif.h'`, direct calls in `src/shyfem/lagrange_mpi.f90`), bash and Python 3 standard library for tests.

**Spec:** `docs/superpowers/specs/2026-11-21-lagrange-mpi-design.md` (approved 2026-11-21). Code map with `file:line` for every routine named here: `docs/superpowers/specs/2026-11-21-lagrange-mpi-code-map.md`. Read both before any task.

## Global Constraints

- CLAUDE.md Fortran rules: `implicit none`, `intent` on arguments, `allocate(..., stat=ierr)` with a check, `newunit=`, no GOTO, no bare `stop` in MPI paths (`shympi_abort_internal`).
- Build and run with OpenMPI only: `PATH=/usr/bin:$PATH nice -n 10 make fem`; `ldd src/shyfem/shyfem | grep mpi` must show `libmpi.so.40`. Prefix every run with `nice -n 19`.
- New MPI code goes in `src/shyfem/lagrange_mpi.f90`. `src/utils/shympi` is not changed.
- The `.lgr.shy` layout does not change (code map, section 6).
- A serial run with `rwhpar = 0` is byte-identical before and after every stage (AC6). `mpirun -np 1` is byte-identical to serial (AC7).
- Limits: flux relative difference ≤ 1e-5 of the array's maximum (AC1); position ≤ 1e-5° on a geographic basin, ≤ 2 m on a Cartesian one (AC3). A limit is never relaxed without the owner.
- Work only in worktrees. `~/shyfem` stays on main and is never rebuilt.
- Integration branch `feat/lagrange-mpi` (from main `e35441cc` or later). Every stage is one branch `lgr/sN-<name>` and one pull request **into `feat/lagrange-mpi`**. Merging a stage PR, and the final PR into main, need the owner's word.
- Options outside the core scope stop under MPI with a message; none of them is implemented here (spec, section 6.9).
- Every stage PR adds one line to `CHANGELOG.md` under `[Unreleased]`.

## Review Focus

1. A rank that never holds a particle, or shares no element with some other rank: every exchange and the output must work with zero-length lists. Test in Task 3.6 (case A on 4 ranks, where rank 0 never holds a particle even in the correct solution: the run must end and compare; an empty rank is never a failure of the comparison, a missing dump file is).
2. Several releases between two outputs, or an output interval longer than the release interval: all pending release records must be written once. Test in Task 5.2 (case B variant with `idtl = '30m'`, `idtlgr = '1h'`).
3. More than one OpenMP thread with hand-overs: results must not depend on the order of the hand-over list. Test in Task 3.6 (case A with `nomp = -1`).
4. A run whose first outputs have no particle at all (release later than the first output): nothing is written for those times, as in serial. Test in Task 5.2 (case A variant with `itranf` one hour after `itanf`).
5. The global particle limit: `nbdymax` exceeded by the sum over ranks while every rank is below it must stop with the serial message. Test in Task 4.2 (case B with `nbdymax = 500`, `nbdy = 1000`).

---

## File structure

| File | Responsibility | Stages |
|---|---|---|
| `src/shyfem/lagrange_mpi.f90` | topology lists, flux sum, particle record on the wire, hand-over, ids, output gather, start-up stops, debug dump and check | 1–7 |
| `src/shyfem/lagrange_flux.f90` | own-node loop, call of the flux sum | 2 |
| `src/shyfem/lagrange_main.f90` | call order in `lagrange`, `track_single` split into advect and finish | 3 |
| `src/shyfem/lagrange_vertical.f90`, `lagrange_util.f90`, `lagrange_dif.f90`, `lagrange_stk.f90` | read `lgr_ieltv`; report a failed position search | 3 |
| `src/shyfem/lagrange_init.f90`, `lagrange_inout.f90` | owner filter, global grid origin and spacing, output records | 4, 5 |
| `testcases/examples/mar_menor/mm_lgr_{a,b,c,e}.str` | test cases (case D is the shipped `mm_lgr.str`) | 1 |
| `testcases/examples/mar_menor/lgr_compare.py` | compare two `.lgr.shy` files | 1 |
| `testcases/examples/mar_menor/lgr_dbg_compare.py` | compare debug dumps (fluxes, particles) | 1 |
| `testcases/examples/mar_menor/check_lgr_mpi.sh`, `check_lgr_serial.sh` | test drivers | 1 |
| `docs/reviews/2026-11-lagrange-mpi-acceptance.md` | measured results of every acceptance criterion | 2–7 |

Names used across tasks (all in module `mod_lagrange_mpi` unless noted):

- `lgr_mpi_topology_init()` — builds the lists below once.
- `lgr_ieltv(3,nel)` — integer copy of `ieltv` for the tracker: `> 0` local neighbour, `0` wall, `-1 … -999` open boundary, `<= -1000` cut-off side with destination rank `-lgr_ieltv - 1000`.
- `lgr_mpi_flux_sum_3d(flux)` with `real, intent(inout) :: flux(nlvdi,3,nel)`; `lgr_mpi_flux_sum_2d(flux)` with `real, intent(inout) :: flux(3,nel)`.
- `lgr_mpi_pack_particle(p, buf)`, `lgr_mpi_unpack_particle(buf, p)`, `lgr_mpi_remove_particle(i)`.
- `lgr_mpi_mark_side(i, ie, iside, t_left, n_left)` and `lgr_mpi_mark_position(i, x, y, phase)`.
- `lgr_mpi_handover(dtime)` — the loop of exchanges after `drogue`.
- `lgr_mpi_assign_ids(nbdy_before)`, `lgr_mpi_output(iu, dtime)`, `lgr_mpi_check_supported()`, `lgr_mpi_check_consistency(dtime)`, `lgr_mpi_debug_dump(dtime)`.
- In `lagrange_main.f90`: `track_advect(i, t_left, n_left, dtime)` and `track_finish(i, phase, dtime)`; `track_single` calls both.

---

## Stage 0: branches and reference build

### Task 0.1: Integration branch, work tree, reference binary

**Files:** none in the repo.

- [ ] **Step 1:** Create `feat/lagrange-mpi` from `origin/main` and push it. Create the work tree `/home/razinka/wt-lgr` on a first stage branch `lgr/s1-harness` from it.
- [ ] **Step 2:** Create a detached work tree `/home/razinka/wt-lgr-ref` at the same commit and build it (`PATH=/usr/bin:$PATH nice -n 10 make fem NETCDF=true NETCDFDIR=/usr NETCDFFDIR=/usr/local`). This is the reference binary for AC6. It is never modified.
- [ ] **Step 3:** Verify: `ldd /home/razinka/wt-lgr-ref/src/shyfem/shyfem | grep -c libmpi.so.40` prints `1`, and `readlink -f /home/razinka/wt-lgr-ref/bin/shyfem` ends in `wt-lgr-ref/src/shyfem/shyfem`.

---

## Stage 1: test cases, comparison tools, debug dump, serial guards

### Task 1.1: Test cases A, B, C, E

**Files:**
- Create: `testcases/examples/mar_menor/mm_lgr_a.str`, `mm_lgr_b.str`, `mm_lgr_c.str`, `mm_lgr_e.str`

**Interfaces:**
- Produces: run names `mm_lgr_a`, `mm_lgr_b`, `mm_lgr_c`, `mm_lgr_e` (the second line of `$title`), used by every later test.

- [ ] **Step 1:** Write the four files.

| Case | Start from | Changes |
|---|---|---|
| A `mm_lgr_a` | `mm_lgr.str` | `rwhpar = 0` |
| B `mm_lgr_b` | `mm_hyd_11.str` | remove `ztilt` and `ktilt`; `itend = '2009-01-03'`; add the river boundary `$bound2` of `mm_hyd_41.str` (node 218, `ibtyp = 3`, without its `salt` and `temp` lines) so that a flux boundary and a non-zero `mfluxv` are exercised (serial agrees with 2 and 4 processes to 1.6e-6); add `$lagrg` with `ilagr = 1`, `nbdymax = 20000`, `nbdy = 1000`, `idtl = 0`, `idtlgr = '1h'`, `rwhpar = 0` (no `lgrlin`: whole-basin release) |
| C `mm_lgr_c` | case A (closed geographic basin) | `itend = '2009-01-03'`; add the `$levels` section of `mm_hyd_41.str` (19 levels); `dragco = 1.e-4`; in `$lagrg` `ilagr = 2` and `ipvert = -1` |
| E `mm_lgr_e` | case A | `stkpar = 0.016` |

Amended 2026-11-21 (owner decision): the 3D base with an open boundary differs between serial and MPI in its hydrodynamics (#230), and `ilagr = 3` crashes in a serial run (#231). Case C is therefore a closed 3D basin with layer tracking, and there is no case F. Its wind drag is 25 times weaker than case A's (`dragco = 1.e-4`): with the original drag and no vertical mixing the surface layer reaches 8.9 m/s, and with a turbulence scheme serial and MPI hydrodynamics differ by about 1e-2 m/s (#230). With the weak drag the largest current is 0.6 m/s and serial agrees with 2 and 4 processes to 7e-7 m/s (controller's measurement).

- [ ] **Step 2:** Run each serially with the reference binary. Expected: `simulation end` in each log, and a `.lgr.shy` file with at least one particle (`lgrelab -lgmean` prints records).
- [ ] **Step 3:** Run cases A, B, C, E twice serially and `cmp` the two `.lgr.shy` files. Expected with the reference binary: A and B identical; C and E may differ, because a particle that lands exactly on a vertex picks its next element with an unseeded random number. Record the result for each case; Task 1.5 removes that draw.
- [ ] **Step 4:** Commit: `test(lagrange): deterministic and random test cases for MPI work (#217)`.

### Task 1.2: `lgr_compare.py`

**Files:**
- Create: `testcases/examples/mar_menor/lgr_compare.py`

**Interfaces:**
- Produces: `python3 lgr_compare.py A.lgr.shy B.lgr.shy --mode {pos|ids} [--tol FLOAT] [--same-counts] [--nel N --nlv N]`. Exit 0 on pass, 1 on fail. Prints one line per output time and block: counts in A and B, ids only in A, ids only in B, largest `|dx|`, `|dy|`, and whether `lb` and `z` match.

Record layout to parse (code map, section 6): Fortran sequential unformatted records with 4-byte length markers. After the shy header comes one record `ncust` (int32). Then per output time three blocks, each led by a record `dtime (float64), n (int32), iwhat (int32)` with `iwhat` 0, −1, 1 in that order, followed by `n` particles of three records each: `id, type (int32), tt (float64), s (float32), ie (int32)`; `x, y, z (float32), lb (int32), hl (float32)`; `c (float32 × ncust)`. Find the start of the particle part as the first 4-byte record that is followed by a 16-byte record with `iwhat = 0` and by a consistent first block.

- [ ] **Step 1: Write the failing test.** `testcases/examples/mar_menor/test_lgr_compare.sh`, which builds two small files with Python and asserts:

```bash
python3 lgr_compare.py t1.lgr.shy t1.lgr.shy --mode pos --tol 1e-5        # exit 0
python3 lgr_compare.py t1.lgr.shy t2_shifted.lgr.shy --mode pos --tol 1e-5 # exit 1, prints the id and 2.0e-05
python3 lgr_compare.py t1.lgr.shy t3_missing_id.lgr.shy --mode ids        # exit 1, prints "only in A: 7"
python3 lgr_compare.py t1.lgr.shy t4_reordered.lgr.shy --mode pos --tol 0 # exit 0 (matching is by id)
```

- [ ] **Step 2:** Run it. Expected: fails, `lgr_compare.py` does not exist.
- [ ] **Step 3:** Implement `lgr_compare.py` (standard library only: `struct`, `argparse`). `--mode pos`: same ids per block and position within `--tol`, `lb` equal, `|z|` difference ≤ 1e-5. `--mode ids`: the set of ids over the three blocks is equal; with `--same-counts` the count per block is equal too; with `--nel`/`--nlv`, every active particle has `1 <= ie <= nel` and `1 <= lb <= nlv`.
- [ ] **Step 4:** Run the test. Expected: all four assertions pass. Then run it on two serial runs of case A: exit 0 with difference 0.
- [ ] **Step 5:** Commit: `test(lagrange): lgr_compare.py compares particle files by id (#217)`.

### Task 1.3: Debug dump and its comparison tool

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90` (new routine), `src/shyfem/lagrange_main.f90` (one call at the output point, `lagrange` ~line 367)
- Create: `testcases/examples/mar_menor/lgr_dbg_compare.py`

**Interfaces:**
- Produces: `subroutine lgr_mpi_debug_dump(dtime)` with `double precision, intent(in) :: dtime`. Active only when `levdbg >= 3`. At every particle output it appends to `lgrdbg.part.NN.txt` (NN = rank): one line per array entry, `P|M|G|D time id x y z lb ie_global rank ncross` (`lb` is the particle's layer; P own-node element, M mixed element this rank is main owner of, G mixed element owned elsewhere, D entry with `ie <= 0`; `ncross` is the number of element crossings the particle used in the last time step, kept in an integer array in `mod_lagrange` with one entry per array slot that `track_body_xi` writes when its loop ends). At the first output at or after 10 h it writes three files once. `lgrdbg.flux.NN.txt`: one line per element and side, `ie_global node_global rank main_owner n_ghost_nodes flux3d(1,ii,ie) flux2d(ii,ie)`. `lgrdbg.flux3.NN.txt` (3D runs only): the same with `flux3d` of the element's bottom layer. `lgrdbg.node.NN.txt`: one line per local node, `node_global rank owner wlnv(1,k) mfluxv(1,k) difv(1,k) wxv(k) wyv(k)`.
- Produces: `python3 lgr_dbg_compare.py flux SERIAL_DIR MPI_DIR [--tol 1e-5]` (table per element class as in spec M4, for `flux3d` and `flux2d`; exit 1 if any class exceeds the limit); `python3 lgr_dbg_compare.py node SERIAL_DIR MPI_DIR [--tol 1e-5]` (own and ghost nodes, per array); and `python3 lgr_dbg_compare.py part SERIAL_DIR MPI_DIR --tol FLOAT [--by {id|nearest}] [--first-only] [--ranks-empty-ok]` (counts per time, duplicate ids, largest distance, layer equal and `|z|` difference at most 1e-5 for matched particles, and with `--ncross` the number of matched particles whose crossing count differs; `--first-only` looks at the first output only; exit 1 on a count mismatch, a distance above the limit, or with `--ncross` a differing crossing count).

- [ ] **Step 1: Write the failing test.** Run case A with `levdbg = 3` serially and on 4 ranks (by hand in this task, keeping each run's dump files in its own folder; Task 1.4 wraps this as mode `flux` of `check_lgr_mpi.sh`), then `lgr_dbg_compare.py flux`. Expected today: exit 1, with the classes "mixed" far above 1e-5 and the class "all-own nodes" below it (spec M4).
- [ ] **Step 2:** Implement the dump routine and the tool. The dump only reads model state. The dump files are opened fresh (replacing any old file) at the first call of a run.
- [ ] **Step 2b (amended 2026-11-21):** Two changes so that an MPI run reaches the dump at all (spec M1, M2). (a) In `lagrange` (`lagrange_main.f90` ~367–373), on more than one process do not call `lgr_mpi_gather_output`: MPI runs write no particle records until Stage 5, and the dump is their test output. (b) In `track_single` (~578–591) move the `ie <= 0` return above the `xi2xy` call. Neither changes a serial result. Check on case A with 4 ranks: the run ends.
- [ ] **Step 3:** Run the test. Expected: exit 1 with the M4 pattern. The controller measured this case on 4 ranks before: rows off by more than 1e-6 of scale were 0 of 7,320 (all-own-node elements), 207 of 315 (mixed, this rank is main owner) and 305 of 318 (mixed, owned elsewhere). The tool must reproduce these row counts per class to within a few rows (its limit is 1e-5, so slightly fewer may be off); if the totals per class differ, the dump or the tool is wrong. This is the failing test Stage 2 turns green.
- [ ] **Step 4:** Serial guard: cases A, B, C, E with `levdbg = 0` give `.lgr.shy`, `.hydro.shy` and `.inf` byte-identical to the reference binary.
- [ ] **Step 5:** Commit: `test(lagrange): debug dump of fluxes and particles at levdbg >= 3 (#217)`.

### Task 1.4: Test drivers

**Files:**
- Create: `testcases/examples/mar_menor/check_lgr_mpi.sh`, `testcases/examples/mar_menor/check_lgr_serial.sh`

**Interfaces:**
- Produces: `./check_lgr_mpi.sh CASE NP MODE` with MODE in `flux | part | pos | ids`; runs the case serially and on NP ranks in the folder (renaming the serial outputs to `CASE.serial.*`), calls the matching comparison, prints `LGR GATE: PASS` or `LGR GATE: FAIL`, exits 0 or 1. Limits: geographic cases (A, C, D, E) `--tol 1e-5`; the Cartesian case (B) `--tol 2`. Arguments after MODE are passed on to the comparison tool and replace its defaults. For the dump modes (`flux`, `part`) it sets `levdbg = 3` in a temporary copy of the STR file and moves each run's `lgrdbg.*.txt` files into its own folder (`CASE.serial.dbg/`, `CASE.npN.dbg/`) before the next run.
- Produces: `./check_lgr_serial.sh REF_BIN_DIR` (AC6 and AC7): for cases A, B, C, E compares `.lgr.shy`, `.hydro.shy`, `.inf` from the current binary, from `mpirun -np 1`, and from the reference binary with `cmp`; for `mm_lgr` and `../mar_menor_lagrange/mm_lgr_01` compares `.hydro.shy` and `.inf` only. Prints `SERIAL GUARD: PASS|FAIL`. A second mode, `./check_lgr_serial.sh repro`, runs cases A, B, C, E twice with the current binary and compares the two `.lgr.shy` files of each with `cmp` (`REPRO: PASS|FAIL`).

- [ ] **Step 1:** Write both scripts. `set -u`, no `cd … && rm`, absolute or script-relative paths only.
- [ ] **Step 2:** Run `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin`. Expected: `SERIAL GUARD: PASS`.
- [ ] **Step 3:** Run `./check_lgr_mpi.sh mm_lgr_a 4 flux`. Expected: `LGR GATE: FAIL` (Task 1.3, step 3).
- [ ] **Step 4:** Mutation check of the guard: point `REF_BIN_DIR` at the live v8.5.3 binary (`/home/razinka/shyfem/bin`). Expected (amended 2026-11-21): FAIL on the `.lgr.shy` of cases C and E, because that binary still picks at random at a vertex; cases A and B and every `.hydro.shy` and `.inf` are identical.
- [ ] **Step 5:** Commit: `test(lagrange): MPI and serial test drivers (#217)`.

### Task 1.5: A vertex pick that does not depend on a random stream (added 2026-11-21)

**Files:**
- Modify: `src/shyfem/lagrange_vertical.f90` (`track_xi_next_element`, the `in == 2` branch ~614–635), and whatever passes the needed values down to it (`track_xi`, `track_body_xi` in `lagrange_main.f90`)

Order (amended 2026-11-21): this task runs right after Task 1.2 and before Tasks 1.3 and 1.4, because those compare cases C and E with the reference binary, and the reference is rebuilt from this task's commit.

**Interfaces:**
- Produces: the value `r` used when a particle lands exactly on a vertex is `eps*(u - 0.5)` with `u` a function of three integers only: the particle's id, the number of the time step (a counter of `lagrange` calls kept in `mod_lagrange`), and the number of element crossings the particle has left in this step (the loop counter of `track_body_xi`, starting at 100). `u` lies in (0,1) and is never exactly 0.5. No `random_number` call remains in `track_xi_next_element`. The crossing count reaches `track_xi_next_element` as a subroutine argument, not through a module variable: the tracker runs inside `drogue`'s OpenMP loop. The step number may be a module variable that `lagrange` sets before `drogue`; nothing writes it inside the loop.
- Why these three: the pick must be the same in every run and on any number of processes (the id and the step number are), and it must change from one vertex event to the next within a step so a particle can't cycle (the crossing counter does, and Stage 3 sends it with the particle).

Owner decision 2026-11-21: this draw is replaced, although it changes serial results for particles that land exactly on a vertex. Those results are random today (two serial runs of cases C and E differ; with the draw fixed they are byte-identical).

- [ ] **Step 1: The failing test, by hand.** Run cases A, B, C, E twice with the current build and `cmp` the two `.lgr.shy` files of each. Expected before the change: C and E differ. (Task 1.4 turns this into the mode `repro` of `check_lgr_serial.sh`.)
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Repeat step 1 with the new build. Expected: all four cases identical across two runs, and across three runs for C and E.
- [ ] **Step 4:** Cases A and B: `.lgr.shy`, `.hydro.shy`, `.inf` byte-identical to the reference binary (they never land on a vertex, so nothing may change). Cases C and E: `.hydro.shy` and `.inf` byte-identical to the reference binary.
- [ ] **Step 5:** Commit: `fix(lagrange): the next element at a vertex no longer depends on a random stream (#217)`.

After this task's review is clean the controller builds a second reference binary from this commit in `/home/razinka/wt-lgr-ref2` (the first one, `/home/razinka/wt-lgr-ref`, stays as untouched main). From then on the serial guard compares cases A, B, C, E against `wt-lgr-ref2`.

---

## Stage 2: fluxes that are right in every held element

### Task 2.1: Lists of shared elements

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90`; `src/shyfem/lagrange_main.f90` (call once in the first-call block of `lagrange`, after `lgr_mpi_init`)

**Interfaces:**
- Produces: `subroutine lgr_mpi_topology_init()`. For every other rank `r` it builds the list of local elements this rank shares with `r` (elements with `r` among `id_elem(1:id_elem(0,ie),ie)`), sorted by `ip_int_elem`. Module data: `lgr_nshare(0:nproc-1)`, `lgr_share_ptr(0:nproc)`, `lgr_share_elem(:)`.
- Consumes: `id_elem`, `ip_int_elem`, `my_id`, `n_threads` from `shympi`.

- [ ] **Step 1: Write the failing test.** A check inside `lgr_mpi_topology_init`, active at `levdbg >= 3`: every rank sends its `lgr_nshare` to all, and `lgr_nshare(r)` on rank `q` must equal `lgr_nshare(q)` on rank `r`; a mismatch aborts with `lgr_mpi_topology_init: shared lists differ`. Test command: case A, 4 ranks, `levdbg = 3`, expected line in the log `lgr topology: shared element lists consistent`.
- [ ] **Step 2:** Run before implementing. Expected: no such line.
- [ ] **Step 3:** Implement. In a serial run (`n_threads <= 1`) the routine returns at once.
- [ ] **Step 4:** Run on 2 and 4 ranks. Expected: the line appears once per run; with 4 ranks at least one element has `id_elem(0,ie) = 3` in a list (print the count of such elements; if it is 0, try 3, 5, 6 and 8 ranks and record a count that is not 0 for the triple-point case of spec section 7).
- [ ] **Step 5:** Commit: `feat(lagrange): lists of elements shared between ranks (#217)`.

### Task 2.2: Own-node contributions and the sum across ranks

**Files:**
- Modify: `src/shyfem/lagrange_flux.f90` (`setup_fluxes_3d` ~114–180, `setup_fluxes_2d` ~184–247), `src/shyfem/lagrange_mpi.f90`

**Interfaces:**
- Consumes: the lists of Task 2.1.
- Produces: `lgr_mpi_flux_sum_3d(flux)` and `lgr_mpi_flux_sum_2d(flux)` (signatures in "File structure"). Each sends, to every rank it shares elements with, its own values of the shared elements in list order, and adds what it receives. Returns at once in a serial run.

- [ ] **Step 1:** The failing test exists: `./check_lgr_mpi.sh mm_lgr_a 4 flux` (FAIL).
- [ ] **Step 2:** In both node loops skip a node that is not own (`shympi_is_inner_node(k)`). Call the matching sum after the loop and before `setup_vl_3d` / `setup_vl_2d`.
- [ ] **Step 3:** Run `./check_lgr_mpi.sh mm_lgr_a 4 flux` and `… 2 flux`. Expected: `LGR GATE: PASS`, every class at or below 1e-5.
- [ ] **Step 3b (amended 2026-11-21):** Run `./check_lgr_mpi.sh mm_lgr_b NP flux` for NP 2 and 4, and `lgr_dbg_compare.py node` on the same dumps. Case B is the only case with an open boundary, so it is the one that exercises the boundary node types of `flxtype` and a non-zero `mfluxv`. Expected: PASS.
- [ ] **Step 4:** Run `./check_lgr_mpi.sh mm_lgr_c 4 flux` (closed 3D basin: surface and bottom layer). Expected: PASS. If a class fails, run `lgr_dbg_compare.py node` for `wlnv` and `mfluxv` before changing anything, and report what it shows.
- [ ] **Step 5:** `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin`. Expected: `SERIAL GUARD: PASS`.
- [ ] **Step 6:** Mutation check: comment out the call of `lgr_mpi_flux_sum_3d`; the flux gate must FAIL; restore.
- [ ] **Step 7:** Record the AC1 numbers (2 and 4 ranks, cases A and C) in `docs/reviews/2026-11-lagrange-mpi-acceptance.md`. Commit, push, open the stage PR: `feat(lagrange): side fluxes summed across the ranks that hold an element (#217)`.

### Task 2.3 (added 2026-11-21 by the controller): no division by a zero particle count

**Why.** Found by the controller at the end of stage 2: `./check_lgr_mpi.sh mm_lgr_a 3 flux`, `… mm_lgr_a 8 flux` and `… mm_lgr_c 3 flux` do not end. The run stops with SIGFPE at `src/shyfem/lagrange_main.f90:734`, `perc = (100.*nl)/idbdy`, in the block of `track_body_xi` that prints `loosing particle adv`. `idbdy` is the number of particle ids given out on this process. On 3 and 8 processes one process releases no particle (none of the three release polygons of case A lies in its domain), so its `idbdy` is 0; when a particle it received from a neighbour is then counted as lost in mid-step, the percentage divides by zero (the build traps it: `-ffpe-trap=zero`). In a serial run the line cannot be reached with `idbdy = 0`. The same division stands in the two neighbouring branches (`warning particle adv`, `unknown error adv`).

**Files:**
- Modify: `src/shyfem/lagrange_main.f90` (`track_body_xi`, the three `perc = …/idbdy` lines near 729–739), and any other division by `idbdy` on the tracker path that `grep -n '/ *idbdy' src/shyfem/lagrange_*.f90` shows.

**Interfaces:** none change.

- [ ] **Step 1: The failing test.** From `testcases/examples/mar_menor`: `./check_lgr_mpi.sh mm_lgr_a 3 flux`. Expected today: `LGR GATE FAIL: mm_lgr_a did not end on 3 processes (exit code 136)`, and `mm_lgr_a.np3.log` shows the SIGFPE with `lagrange_main.f90:734` in the backtrace. Run it and paste both.
- [ ] **Step 2: Fix.** Where `idbdy` is 0 the percentage is 0: `perc = 0.` followed by `if( idbdy > 0 ) perc = (100.*n…)/idbdy`, at each of the divisions. Nothing else changes: the messages, the counters and the particle's fate stay as they are. A serial result must not change.
- [ ] **Step 3:** Rebuild. Run `./check_lgr_mpi.sh CASE NP flux` for `mm_lgr_a` on 3, 6 and 8 processes and for `mm_lgr_c` on 3 and 8 processes. Expected: all five runs end and print `LGR GATE: PASS` (every class 0 rows off). If a run does not end for another reason, stop and report the backtrace; do not patch further.
- [ ] **Step 4:** `./check_lgr_mpi.sh mm_lgr_a 4 flux` → `LGR GATE: PASS`; `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin` → `SERIAL GUARD: PASS`.
- [ ] **Step 5:** Add the rows for 3, 6 and 8 processes to the AC1 table of `docs/reviews/2026-11-lagrange-mpi-acceptance.md` (same columns), with one sentence saying that 3 and 8 processes first stopped at this division and pass after the fix. Commit: `fix(lagrange): no division by zero when a process has released no particle (#217)`.

### Task 2.4 (added 2026-11-21 by the controller): no array is read with the element number of a particle that has left the domain

**Why.** Found by the controller at the end of stage 2 (issue #234). In `track_xi` (`src/shyfem/lagrange_vertical.f90`, two calls, near lines 456 and 476) the tracker tests `track_xi_has_layer(iel,lb)`, which is `( ilhv(iel) >= lb )`, right after `call track_xi_next_element(iel,xi,id,ncross)`. When the particle has left the domain, `track_xi_next_element` returns `iel` negative, and `ilhv` is read before its first element. The word found there decides the particle's fate: at least `lb` and the particle leaves; less than `lb` and it is put back on the side of the element it tried to leave (`iel = ieorig; xi = xie`). Measured: valgrind reports `Invalid read of size 4` at both lines for a serial run of case B and for case A on 8 processes; case A on 8 processes gives different particle dumps (`lgrdbg.part.04`–`07`) with `MALLOC_PERTURB_=85` than without, while every flux and node dump is identical. A throwaway build with the guard below gave: serial particle files of cases A, B, C and E byte-identical to the current binary, valgrind 0 errors on serial case B, and identical 8-process dumps with and without the perturbation.

A bounds-checked build (`-fcheck=bounds`) run by the controller found three more places on the same path. With all four corrected in a throwaway build, the serial cases A, B, C and E and the MPI runs (A on 3, 4 and 8 processes, B on 4, C on 4) end with no runtime message:
- `src/shyfem/lagrange_main.f90:747` and `:917`: `if( iel.gt.0 .and. iarv(iel).eq.artype ) iel = -iel` reads `iarv` with a negative `iel` (Fortran does not short-circuit `.and.`). The value cannot change the outcome, but the read is outside the array.
- `src/shyfem/lagrange_flux.f90`, `setup_flux2d` (near line 318): the dummies are declared `real tflux(ne)` and `real flux2d_loc(3,ne)`, but `flux2d_loc` is indexed by the element number (the actual argument is `flux2d(3,nel)`), and at a boundary node `tflux` holds `n = ne+1` side fluxes (`j = i+1` reaches `ne+1`). Wrong declarations, not stray accesses, but they stop every bounds-checked run in the first particle step.
- the same in `setup_flux3d` (near line 286): `real tflux(nlvdi,ne)`.

**Files:**
- Modify: `src/shyfem/lagrange_vertical.f90` (`track_xi_has_layer`, near line 781)
- Modify: `src/shyfem/lagrange_main.f90` (the two lines above)
- Modify: `src/shyfem/lagrange_flux.f90` (the three declarations above)
- Modify: `testcases/examples/mar_menor/check_lgr_mpi.sh` (new mode `perturb`)

**Interfaces:**
- `track_xi_has_layer(iel,lb)`: `.true.` when `iel < 1` (the particle has left the domain; there is no layer to test); otherwise `( ilhv(iel) >= lb )` as before.
- `lagrange_main.f90`, both lines: the test of `iarv(iel)` is nested inside `if( iel > 0 )`, so `iarv` is read only for a real element. Same result as today.
- `lagrange_flux.f90`: `tflux` and `flux2d_loc` (and `tflux` in `setup_flux3d`) are declared so that every index the loops use is inside the declared bounds: assumed-size in the last dimension (`tflux(*)`, `flux2d_loc(3,*)`, `tflux(nlvdi,*)`, which is what the controller's probe build used), or an explicit extent that you can show to be right for every node type. No statement changes.
- `./check_lgr_mpi.sh CASE NP perturb`: runs CASE on NP processes twice with the debug dump on (`levdbg = 3`, as the modes `flux` and `part` do), once plainly and once with the environment variable `MALLOC_PERTURB_=85` exported to the run; keeps the two sets of dump files in `CASE.npNP.dbg/` and `CASE.npNP.perturb.dbg/`; compares every dump file of the first set with the file of the same name in the second, byte for byte (`cmp`); prints the names of files that differ or are missing on either side, the number of `loosing particle adv` lines of each run, and `LGR GATE: PASS` only if both runs ended, both sets hold the same file names, at least one file exists, and no file differs. No serial run in this mode. The variable is passed to the processes explicitly (`mpirun -x MALLOC_PERTURB_ …`), and before the perturbed run the mode prints the value seen by a launched process (`mpirun -np 1 -x MALLOC_PERTURB_ printenv MALLOC_PERTURB_`) and ends in `LGR GATE: FAIL` if that is empty, so a PASS can never be two plain runs. The script header says that a PASS is weak evidence: the perturbation only shows a dependence on memory that `malloc` hands out, and case A on 4 processes passed with the defect present.

- [ ] **Step 1: Write the test.** Add the mode `perturb` to `check_lgr_mpi.sh` (house style of the other modes: same early checks, same clean-up of old dump files and of the temporary STR copy, usage text and header comment updated). Run `./check_lgr_mpi.sh mm_lgr_a 8 perturb` once and paste the output. The controller measured `LGR GATE: FAIL` there (`lgrdbg.part.04.txt` … `lgrdbg.part.07.txt` different, 0 against 6 `loosing particle adv` lines), but what the stray word holds depends on the session: in another session the two runs coincided. If the mode passes before the fix, report the two counts and go on. Do not search for a case or a process count that fails; the binding failing test is step 2.
- [ ] **Step 2: The binding failing test, valgrind.** In a scratch copy of the test folder, a copy of `mm_lgr_b.str` with `itend = '2009-01-01::12:00:00'`, run serially under `valgrind --error-limit=no --num-callers=6 --log-file=…`. Expected today: `Invalid read of size 4` at `track_xi_ (lagrange_vertical.f90:456)` and `(…:476)`. Paste the two reports and the `ERROR SUMMARY` line.
- [ ] **Step 3: Fix** the four places as in Interfaces. Nothing else changes: no statement is added to or removed from the flux routines, and the two `iarv` lines keep their effect.
- [ ] **Step 4:** Rebuild. `./check_lgr_mpi.sh mm_lgr_a 8 perturb` → `LGR GATE: PASS`. Run the mode also for `mm_lgr_a` on 3 and 4, `mm_lgr_b` on 4 and `mm_lgr_c` on 4 and 8 processes. Expected: PASS in all. Report the number of `loosing particle adv` lines of each run.
- [ ] **Step 5:** valgrind again: the serial run of step 2, and case A on 8 processes (`mpirun --oversubscribe -np 8 valgrind -q --error-limit=no --num-callers=12 --log-file=…/vg.%p.log shyfem …` on a copy of `mm_lgr_a.str` with `itend = '2009-01-01::23:00:00'`). Expected: the serial run has `ERROR SUMMARY: 0 errors`; in the 8 logs of the MPI run no report names a frame of the particle code (`grep -c 'lagrange_\|track_\|lgr_\|drogue'` is 0 in every log; reports from inside the MPI library itself are not this task's concern, say how many logs have them).
- [ ] **Step 6:** `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin` → `SERIAL GUARD: PASS`; `./check_lgr_serial.sh repro` → `REPRO: PASS`; `./check_lgr_mpi.sh mm_lgr_a 4 flux` → `LGR GATE: PASS`.
- [ ] **Step 6b:** The controller, not you, then builds your commit with `-fcheck=bounds` in a throwaway work tree and runs the serial and MPI cases there; a runtime message from the particle code comes back to you as a fix round. Do not make a bounds-checked build in the work tree.
- [ ] **Step 7:** Commit: `fix(lagrange): no array is read with the element number of a particle that has left the domain (#234, #217)`.

---

## Stage 3: particle record, one rank per particle, hand-over

### Task 3.1: The full record on the wire, buffers without a fixed size

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90` (`lgr_mpi_init` ~48–71, pack/unpack ~96–168), `src/shyfem/lagrange_main.f90` (move the `lgr_mpi_init` call after `nbdymax` and `ncust` are known, ~193–215)

**Interfaces:**
- Produces: `lgr_mpi_pack_particle(p, buf)` and `lgr_mpi_unpack_particle(buf, p)` carrying, in this order: `actual` (`xi(3)`, `time`, `z`, `l`, `ie_global`), `init` (the same fields), `id`, `type`, `sinking`, `bitmap_in`, `bitmap_out` (each as two 32-bit halves in two doubles), the count of custom values and the values. `lgr_pack_size` is a function of the particle's own custom count. Export lists grow on demand (double when full).
- Produces: `lgr_mpi_remove_particle(i)`: moves the last array entry into slot `i` and reduces `nbdy`.

- [ ] **Step 1: Write the failing test.** A self-test routine `lgr_mpi_selftest_pack()` called once at `levdbg >= 3`: fills a particle with `bitmap_in = 2_8**40 + 5`, `init%time = 123.d0`, `init%ie_global = 77`, three custom values, packs and unpacks it, compares every field, and prints `lgr pack self-test: ok` or aborts naming the field.
- [ ] **Step 2:** Run case A at `levdbg = 3` with the old pack. Expected: abort naming `init%time` (or the bitmap).
- [ ] **Step 3:** Implement the record, the growing lists and the removal.
- [ ] **Step 4:** Run again on 1 and 4 ranks. Expected: `lgr pack self-test: ok`.
- [ ] **Step 5:** Serial guard PASS. Commit: `feat(lagrange): whole particle record on the wire, no fixed export size (#217)`.

### Task 3.2: The tracker's own side table

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90` (`lgr_mpi_topology_init`), and every read of `ieltv` on the live tracker path: `lagrange_vertical.f90` (~657, 672, 722, 927), `lagrange_util.f90` (~176, 179)

**Interfaces:**
- Produces: `lgr_ieltv(3,nel)` (meaning in "File structure"). In a serial run it equals `ieltv`.
- Consumes: `nen3v_global`, `ip_int_node`, `ip_int_elem`, `id_node`. First step of the task: confirm that `nen3v_global` is allocated and filled on every rank (`src/utils/shympi/mpi_node.f90:805`); if it is filled on the master only, broadcast it once inside `lgr_mpi_topology_init`.

Rule: start from `ieltv`. For every local side with `ieltv(ii,ie) <= 0` and not already `<= -1000`, look up in the global mesh whether another element contains the side's two end nodes. If one does, the side is a cut-off side: set `lgr_ieltv(ii,ie) = -1000 - r`, where `r` is the owner of one of the two end nodes and is not this rank. Sides already marked `<= -1000` keep their mark.

- [ ] **Step 1: Write the failing test.** At `levdbg >= 3` the routine prints `lgr side table: N cut-off sides, M added to the marks of set_geom_mpi`, and checks with the neighbours that every cut-off side is seen from both sides (the rank named by a mark must hold an element with that side); a mismatch aborts.
- [ ] **Step 2:** Run before implementing: no such line.
- [ ] **Step 3:** Implement the table and replace the reads. Do not change `ieltv` itself.
- [ ] **Step 4:** Run cases A and B on 2, 3, 4, 5, 6 and 8 ranks. Expected: the line on every rank, no abort. Record `N` and `M` per run in the acceptance document; if some run has `M > 0`, name it as the test for spec section 7, case 3; if none has, record that this mesh does not produce the case.
- [ ] **Step 5:** Serial guard PASS. Commit: `feat(lagrange): tracker side table with all cut-off sides (#217)`.

### Task 3.3: Split `track_single` into advect and finish

**Files:**
- Modify: `src/shyfem/lagrange_main.f90` (`track_single` ~542–637, `track_body_xi` ~641–745)

**Interfaces:**
- Produces: `track_advect(i, t_left, n_left, dtime)` with `integer, intent(in) :: i`, `real, intent(inout) :: t_left` (advection time still to do, in the units `track_body_xi` uses), `integer, intent(inout) :: n_left` (element crossings still allowed; a full step starts with 100), `double precision, intent(in) :: dtime`. It returns when `t_left` is used up, when `n_left` reaches 0, when the particle leaves the basin, or when it stops on a cut-off side.
- Produces: `track_finish(i, phase, dtime)` with `integer, intent(in) :: phase`: `0` runs all steps after advection (vertical and horizontal diffusion, Stokes drift, beaching, storing the state); `1` resumes after the horizontal diffusion step; `2` resumes after the Stokes drift step.
- `track_single(i, dt, dtime)` keeps its signature and calls `track_advect` then `track_finish(i, 0, dtime)`. Its `ie <= 0` return moves above the `xi2xy` call.

- [ ] **Step 1:** The test is the serial guard: this task must not change a serial result.
- [ ] **Step 2:** Refactor. No behaviour change: same operations in the same order for a particle that stays on its rank.
- [ ] **Step 3:** `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin`. Expected: PASS. Also run the shipped `mm_lgr.str` serially and confirm `.hydro.shy` and `.inf` identical to the reference.
- [ ] **Step 4:** Commit: `refactor(lagrange): track_single as advect plus finish, no change in results (#217)`.

### Task 3.4: Hand-over at a cut-off side

**Files:**
- Modify: `src/shyfem/lagrange_main.f90` (`track_body_xi`/`track_advect`, `lagrange` ~337), `src/shyfem/lagrange_mpi.f90` (`lgr_mpi_exchange` is replaced; `lgr_mpi_check_ghost` is removed)

**Interfaces:**
- Consumes: Tasks 3.1–3.3.
- Produces: `lgr_mpi_mark_side(i, ie, iside, t_left, n_left)`: records that particle `i` stopped on side `iside` of local element `ie`, to go to rank `-lgr_ieltv(iside,ie) - 1000`. It is called under the existing `!$OMP CRITICAL (lgr_export)`.
- Produces: `lgr_mpi_handover(dtime)`: repeats (a) send every marked particle with its record plus `ip_int_elem(ie)`, the global numbers of the side's two end nodes with the particle's weight at each, `t_left`, `n_left` and `phase`; (b) remove sent particles; (c) on arrival find the local element that holds both nodes and is not the element left, set `xi` (weights at the two nodes, zero at the third), then `track_advect` and `track_finish(…, 0, …)`; until the global number of marked particles is zero.
- Global-to-local lookup: a sorted copy of `ip_int_node` with its permutation, built in `lgr_mpi_topology_init`, searched by bisection. No scan over all elements per particle.

Detection: in `track_advect`, when the tracker returns a negative element, the side the particle sits on is the one opposite the vertex with `xi = 0`. If `lgr_ieltv` of that side is `<= -1000`, restore the positive element number and call `lgr_mpi_mark_side`; otherwise the particle left the basin, as in serial.

- [ ] **Step 1: Write the failing test.** `./check_lgr_mpi.sh mm_lgr_a 4 part` with `--by nearest --tol 1e-5` (ids still repeat across ranks until Stage 4). Expected today: FAIL (the run crashes at the first hand-over, spec M2).
- [ ] **Step 2:** Implement. Replace the `lgr_mpi_exchange` call in `lagrange` by `lgr_mpi_handover(dtime)`; delete the end-of-step hand-over.
- [ ] **Step 3:** Run the test on 2 and 4 ranks for cases A, B and C. Expected: the runs end; counts equal at every output; no `D` line with `ie = 0`. Positions may still fail where the every-step x,y round trip needs Task 3.5; record the largest distance. The crossing count must also match: run the `part` comparison with `--ncross` on cases A and B; a particle handed over in mid-step must end the step with the same total count as in the serial run (the count travels as `n_left`). (Amended 2026-11-21: in Stage 3 the position limit is a gate for cases A and B only. The vertex pick of Task 1.5 depends on the particle id, and ids repeat across ranks until Stage 4, so cases C and E can differ from serial here; their position gate is Task 4.2 step 4.)
- [ ] **Step 4:** Serial guard PASS. Commit: `feat(lagrange): hand-over at a cut-off side with the time left in the step (#217)`.

### Task 3.5: Hand-over by position

**Files:**
- Modify: `src/shyfem/lagrange_dif.f90` (`lag_diff_hor` ~557–576), `src/shyfem/lagrange_stk.f90` (~127–131), `src/shyfem/lagrange_mpi.f90`

**Interfaces:**
- Produces: `lgr_mpi_mark_position(i, x, y, phase)`: called when `find_elem_from_old` returns 0 on more than one process; `phase` is 1 from the diffusion step and 2 from the Stokes step. The particle keeps its state and skips the rest of `track_finish`.
- `lgr_mpi_handover` gains a second kind of round: every rank offers its marked positions to all; for each one, every rank that is the main owner (`id_elem(1,ie) == my_id`) of an element containing the point answers with that element's global number; the lowest global number wins. The winner receives the particle, sets `xi` with `xy2xi`, and calls `track_finish(i, phase, dtime)`. If nobody answers, the sender continues with the serial path for a failed search (`ienew = ieold`, `particle_on_side`) and `track_finish(i, phase, dtime)`.

- [ ] **Step 1:** The failing test is Task 3.4's, where it still fails on positions; plus `./check_lgr_mpi.sh mm_lgr_e 4 part --by nearest` (Stokes drift, deterministic).
- [ ] **Step 2:** Implement. In a serial run the new branch is never taken.
- [ ] **Step 3:** Run cases A and B on 2 and 4 ranks. Expected: `LGR GATE: PASS` (counts equal, nearest-neighbour distance within the limit). Run case C too: counts must be equal; record its largest distance without gating it. Print and record the number of particles handed over by position at zero displacement (AC11).
- [ ] **Step 4:** Run case E on 2 and 4 ranks. Expected: the runs end and counts are equal at every output; record the largest distance (its position gate is Task 4.2 step 4). If it fails, run `lgr_dbg_compare.py node` for `wxv`/`wyv`; if they differ from serial at ghost nodes, add `call shympi_exchange_2d_node(wxv)` and the same for `wyv` at the start of `lagr_setup_timestep` and repeat.
- [ ] **Step 4b:** If a remaining position mismatch in cases A, B, C or E is traced to the random choice of the next element when a particle lands exactly on a vertex (`track_xi_next_element`, `lagrange_vertical.f90` ~618–621), stop and ask the owner (spec, section 6.10). Do not replace that draw without their word.
- [ ] **Step 5:** Serial guard PASS. Commit: `feat(lagrange): hand-over by position when a local element search fails (#217)`.

### Task 3.6: Built-in check, OpenMP, empty ranks

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90`, `src/shyfem/lagrange_main.f90` (call after `lgr_mpi_handover`). Amended 2026-11-21: the guards for the counters that divide by `idbdy` were brought forward as Task 2.3, because runs on 3 and 8 processes stopped there

**Interfaces:**
- Produces: `lgr_mpi_check_consistency(dtime)`: active at `levdbg >= 2` on more than one process; aborts with a message if the sum of live and exited particles over ranks differs from the number released, or if any particle sits in an element this rank does not hold.

- [ ] **Step 1: Write the failing test.** Case A on 4 ranks with `levdbg = 2` plus a deliberate fault behind an environment variable `LGR_TEST_DROP=1` that skips one arrival in `lgr_mpi_handover`. Expected after implementation: abort with `lgr_mpi_check_consistency: particle count`.
- [ ] **Step 2:** Implement the check; run the fault test (aborts with the message) and the clean run (no abort). Remove nothing: the fault switch stays as a test hook, documented in the routine header.
- [ ] **Step 3:** Review Focus 3: case A with `nomp = -1` in `$para`, 4 ranks, `OMP_NUM_THREADS=4`; confirm the log line `used OMP threads: 4`; `./check_lgr_mpi.sh … part` PASS, and the particle dump equal to the one-thread MPI run within the limit.
- [ ] **Step 4:** Review Focus 1: case A on 4 ranks, where ranks 0 and 1 release nothing; `lgr_dbg_compare.py part … --ranks-empty-ok` PASS, no abort on an empty rank.
- [ ] **Step 5:** Spec section 7, cases 1, 2, 4, 6 and 8. Case 1 (two cut-off sides in one step): print the largest number of hand-overs of one particle in one step; record a run where it is ≥ 2 (case B with `idt` doubled if needed). Case 2 (triple point): print the number of hand-overs that start in an element with `id_elem(0,ie) = 3`; record a run where it is not 0. Case 4: case B has particles leaving through the open boundary; record the count of exited particles on each rank against serial. Case 6: case B with `nbdy = 20000` so that more than 1,024 particles change rank in one step; record the largest number per step. Case 8 (dry element next to a cut-off side): print whether any element is dry (`iwegv /= 0`) during cases B and C; if none is, record that the shipped meshes do not exercise it and name it in the stage PR for the owner.
- [ ] **Step 6:** Serial guard PASS. Record all numbers in the acceptance document. Commit, push, open the stage PR: `feat(lagrange): consistency check, OpenMP and empty ranks under MPI (#217)`.

---

## Stage 4: release and ids

### Task 4.1: Release only on the main owner, with the serial grid

**Files:**
- Modify: `src/shyfem/lagrange_init.f90` (`lagbound_seed_particles` ~415–520, `lgr_init_all` ~524–585, `lgr_init_total` ~89–108), `src/shyfem/lagrange_util.f90` (`compute_total_area` ~119–140, `basin_center` use ~103–115), `src/shyfem/lagrange_mpi.f90`

**Interfaces:**
- Produces in `mod_lagrange_mpi`: `lgr_mpi_global_area(area)` and `lgr_mpi_global_center(x0, y0)`: on more than one process they gather the per-element terms of `compute_total_area` (main-owner elements) and the node coordinates (own nodes) to rank 0, add them in global order with the same variable kinds as the serial loops, and broadcast the result. In a serial run they call the existing routines.
- `lagbound_seed_particles` skips elements whose main owner is another rank (`id_elem(1,ie) /= my_id`), as `lgr_init_all` already does.

- [ ] **Step 1: Write the failing test.** `./check_lgr_mpi.sh mm_lgr_b 4 part --by nearest --tol 0` restricted to the first output (add `--first-only` to `lgr_dbg_compare.py`). Expected today: FAIL (the whole-basin grid of each rank starts from its local centre).
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Run for cases A and B on 2 and 4 ranks. Expected: PASS with distance exactly 0 at the first output and equal counts.
- [ ] **Step 4:** Serial guard PASS. Commit: `feat(lagrange): release on the main owner with the serial grid (#217)`.

### Task 4.2: Ids as in a serial run

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90`, `src/shyfem/lagrange_init.f90` (after each seeding call), `src/shyfem/lagrange_inout.f90` (`insert_particle` ~110–118 for the limit)

**Interfaces:**
- Produces: `lgr_mpi_assign_ids(nbdy_before)`: called on every rank after one seeding call (one polygon, or the whole basin). Particles `nbdy_before+1 … nbdy` of each rank carry a key (global element number, order of creation inside the element). All keys are ordered globally; the particle at position `m` gets id `idbdy + m`; `idbdy` is then advanced by the global count on every rank. In a serial run it returns at once.
- The `nbdymax` test uses the global count and stops every rank with the serial message.

- [ ] **Step 1: Write the failing test.** `./check_lgr_mpi.sh mm_lgr_a 4 part --by id --tol 0 --first-only`. Expected today: FAIL (duplicate ids, spec M7).
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Run for cases A (three polygons) and B (whole basin) on 2 and 4 ranks. Expected: PASS: same ids at the same positions as serial, no duplicate.
- [ ] **Step 4:** Run `./check_lgr_mpi.sh … part --by id` over the whole run for cases A, B, C and E on 2 and 4 ranks. Expected: PASS within the position limits. This is the first position gate for cases C and E (see Task 3.4 step 3).
- [ ] **Step 5:** Review Focus 5: case B with `nbdymax = 500`. Expected: serial and 4 ranks both stop with `Cannot insert more than nbdymax particles`, once.
- [ ] **Step 5b:** Spec section 7, case 7: count the release points the serial run inserts twice (two particles at the same x,y in the first output of cases A and B). The 4-rank run must have the same pairs with the same ids. Record the count; if it is 0 in both cases, record that.
- [ ] **Step 5c:** Extend `lgr_mpi_check_consistency`: no id may occur on two ranks. Test: `LGR_TEST_DUP=1` makes one rank keep a copy of one sent particle; expected abort `lgr_mpi_check_consistency: duplicate id`.
- [ ] **Step 6:** Serial guard PASS. Commit, push, open the stage PR: `feat(lagrange): particle ids as in a serial run (#217)`.

---

## Stage 5: output

### Task 5.1: Records prepared on the ranks, written by rank 0

**Files:**
- Modify: `src/shyfem/lagrange_inout.f90` (`lgr_output` ~691–868), `src/shyfem/lagrange_mpi.f90` (`lgr_mpi_gather_output` is replaced), `src/shyfem/lagrange_main.f90` (~263–267 `ncust` record on the master only; ~367–373)

**Interfaces:**
- Produces in `lagrange_inout.f90`: `lgr_output_record(ip, which, rec)`: fills one output record (the three Fortran records of a particle, code map section 6) for array entry `ip`; `which` is 0 active, −1 inserted, 1 exited. `lgr_output` uses it and keeps its order and its file content.
- Produces: `lgr_mpi_output(iu, dtime)`: every rank builds the records of its active and exited particles and of its pending release records; rank 0 gathers them, orders each block by id and writes the three blocks exactly as `lgr_output` does. The element number written is `ip_int_elem(ie)`. If the global count is 0, nothing is written.
- Release records: a rank keeps, for every particle it released since the last output, what the inserted block needs (id, type, release time, release element, `xi`, `z`, layer, custom values); `lgr_mpi_output` writes and clears them. Particles never carry the "new" flag across ranks.

- [ ] **Step 1: Write the failing test.** `./check_lgr_mpi.sh mm_lgr_a 4 pos`. Expected today: FAIL (the MPI file has all particles in the exited block or the run crashes, spec M1).
- [ ] **Step 2:** Implement.
- [ ] **Step 3:** Run `./check_lgr_mpi.sh CASE NP pos` for cases A, B, C and NP 2, 4. Expected: `LGR GATE: PASS` (AC2 exact ids per block, AC3 positions).
- [ ] **Step 4:** `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin`. Expected: PASS, including `mpirun -np 1` (AC7).
- [ ] **Step 5:** AC8: `lgrelab -lgmean` on the serial and the 4-rank file of case A; the two text outputs agree within 1e-5. Run `lgrelab` in the file's folder with a relative name (it truncates long paths).
- [ ] **Step 6:** Commit: `feat(lagrange): particle output from all ranks in the serial layout (#217)`.

### Task 5.2: Output edge cases

**Files:**
- Modify: test scripts only, unless a case fails.

- [ ] **Step 1:** Review Focus 2: a copy of case B with `idtl = '30m'` (several releases between outputs). `./check_lgr_mpi.sh … pos` on 4 ranks. Expected: PASS, and the inserted block of each output holds all particles released since the previous one.
- [ ] **Step 2:** Review Focus 4: a copy of case A with `itranf` one hour after `itanf`. Expected: PASS; both files have no particle record before the release time.
- [ ] **Step 3:** Record AC2, AC3, AC7, AC8 numbers in the acceptance document. Commit, push, open the stage PR: `test(lagrange): output edge cases under MPI (#217)`.

---

## Stage 6: random cases and Stokes drift through the output path

### Task 6.1: Cases D and E

**Files:**
- Modify: only what a failing audit requires (an exchange of a node array at the start of `lagr_setup_timestep` in `src/shyfem/lagrange_flux.f90`).

- [ ] **Step 1:** `./check_lgr_mpi.sh mm_lgr_e NP pos` for NP 2, 4. Expected: PASS (AC2, AC3 for case E).
- [ ] **Step 2:** `./check_lgr_mpi.sh mm_lgr NP ids` (case D; `--same-counts --nel --nlv` from the basin) for NP 2, 4, with `levdbg = 2`. Expected: PASS (AC4) and no abort of the built-in check.
- [ ] **Step 3:** AC5: for case D print the mean position and the standard deviation of each particle type at the last output, serial against 2 and 4 ranks. Record them; they are not gated.
- [ ] **Step 4:** Serial guard PASS. Commit: `test(lagrange): random walk and Stokes drift under MPI (#217)`.

---

## Stage 7: start-up stops, CI, documentation

### Task 7.1: Options that stop under MPI

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90`, `src/shyfem/lagrange_main.f90` (call in the first-call block, after the parameters are read), `src/shyfem/def_para.f90` (`$lagrg` text ~1466–1597), `MANUAL.md` (CRLF file: edit with `newline=""`), `testcases/examples/mar_menor/check_lgr_mpi.sh` (new mode `stops`)

**Interfaces:**
- Produces: `lgr_mpi_check_supported()`. On more than one process, for each option below that is set, the master prints `Lagrangian option <name> is not supported with MPI` and one line `run on one process, or remove <name>`; after a barrier every rank calls `shympi_abort_internal('error stop lagrange: option not supported with MPI')`.

| Option | Set when |
|---|---|
| `ilagr = 3` | `ilagr == 3` (its serial run crashes, #231) |
| `lbeach` | `> 0` |
| `artype` | `/= -1` |
| `ldecay` | `> 0` |
| `lgrini` | file name not blank |
| `ised` | `> 0` |
| `ilarv` | `> 0` |
| `icnn` (section `connec`) | `> 0` |
| `lgrpps` | `/= 0` on any boundary |
| `lgrtrj` | file name not blank |

- [ ] **Step 1: Write the failing test.** `check_lgr_mpi.sh` mode `stops`: for each row, make a copy of case A with that option set by `sed`, run it on 4 ranks and serially. Expected per option: on 4 ranks a non-zero exit, the message exactly once, no `SIGFPE` or `SIGSEGV`; serially the run starts (it need not end for options that need extra input files: then the serial run must fail with its own message, not with the MPI one).
- [ ] **Step 2:** Run before implementing. Expected: FAIL for every row.
- [ ] **Step 3:** Implement the check and the documentation lines (one sentence per option in `def_para.f90`; one paragraph and the table in `MANUAL.md`).
- [ ] **Step 4:** Run the `stops` mode. Expected: PASS for all ten rows (AC10).
- [ ] **Step 5:** Serial guard PASS. Commit: `feat(lagrange): options without an MPI test stop at start-up (#217)`.

### Task 7.2: CI gate and the full acceptance run

**Files:**
- Modify: `testcases/examples/mar_menor/check_mpi.sh` (a fifth check), `CHANGELOG.md`, `docs/reviews/2026-11-lagrange-mpi-acceptance.md`

- [ ] **Step 1:** Add check 5 to `check_mpi.sh`: `bash check_lgr_mpi.sh mm_lgr_a "$NP" pos`, counted in the gate's result. No workflow file changes.
- [ ] **Step 2:** Mutation check: with the reference binary on `PATH`, `./check_mpi.sh 4` must FAIL in check 5.
- [ ] **Step 3:** Full acceptance on a clean build of the integration branch: every criterion AC1–AC11 on 2 and 4 ranks, plus the cases of spec section 7. Fill the acceptance document with one row per criterion: command, measured value, limit, verdict. A criterion that fails is reported to the owner with its numbers; no limit is changed.
- [ ] **Step 4:** Run the whole 4-rank sweep of 2026-11-21 again (65 cases, memory note `project_mpi_sweep_2026-11-21`): no case may be worse than before, and `mm_lgr` must now end.
- [ ] **Step 5:** `CHANGELOG.md` entry under `[Unreleased]` for the whole feature. List the follow-up issues of spec section 9 in the acceptance document: #223 (`particle_on_side`), #225 (random numbers never seeded), #226 (`lgr_output` with element 0), #227 (`itlin = 1` under MPI), #228 (options that stop under MPI). Commit, push, open the stage PR.
- [ ] **Step 6:** After the owner's word on the last stage PR: open the pull request `feat/lagrange-mpi` → `main` with the acceptance document linked. Merging it is the owner's decision.

---

## Stage PR checklist (every stage)

- [ ] `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin` prints `SERIAL GUARD: PASS`.
- [ ] `testcases/examples/mar_menor/check_mpi.sh 4` prints `MPI GATE: PASS`.
- [ ] The stage's own gate commands and their output are pasted in the PR.
- [ ] `fortran-reviewer` agent run on the diff; findings fixed or answered.
- [ ] One `CHANGELOG.md` line.
- [ ] Fortran CI green on the PR.
