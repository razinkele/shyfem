# Lagrangian particles under MPI: acceptance results (#217)

Measured results of the acceptance criteria in section 8 of
`docs/superpowers/specs/2026-11-21-lagrange-mpi-design.md`. The stage that
meets a criterion adds its section here.

## AC1: side fluxes equal serial in every held element

**Criterion.** `flux3d` and `flux2d` in every held element equal the serial
values: the difference is at most 1e-5 of the array's largest serial
magnitude.

**Measured** 2026-11-21 18:15 EET (from `date`) by the controller, on a clean build of
`fb8c31b2` with OpenMPI (`libmpi.so.40`) and the tracked basin files. The table
and every number in the "Result" paragraph are generated from the logs of
that run.

**Method.** `./check_lgr_mpi.sh CASE NP flux` in
`testcases/examples/mar_menor`, for cases A, B and C on 2, 3, 4, 6 and 8
processes (15 runs). The driver runs the case serially and on NP processes
with `levdbg = 3`, and `lgr_dbg_compare.py flux` compares the debug dumps
written at the first output at or after 10 h. One row is one side (element,
opposite node) on one rank. The rows fall into three classes:

- all-own: every vertex is owned by this rank;
- mixed, main owner: this rank is the element's main owner;
- mixed, elsewhere: the element is owned by another rank.

"worst" is the largest |MPI - serial| divided by the scale (the largest
|serial| of that array). Case C is the closed 3D basin (19 layers), and the
tool reports its surface layer and its bottom layer (`ilhv(ie)`).

| Case | NP | Array | all-own rows / off / worst | mixed, main owner | mixed, elsewhere |
|---|---|---|---|---|---|
| A | 2 | flux3d layer 1 | 7497 / 0 / 1.0e-06 | 138 / 0 / 1.0e-06 | 138 / 0 / 1.0e-06 |
| A | 2 | flux2d | 7497 / 0 / 2.2e-07 | 138 / 0 / 1.7e-07 | 138 / 0 / 1.7e-07 |
| A | 3 | flux3d layer 1 | 7452 / 0 / 1.8e-06 | 183 / 0 / 1.8e-06 | 183 / 0 / 1.8e-06 |
| A | 3 | flux2d | 7452 / 0 / 2.2e-07 | 183 / 0 / 8.6e-08 | 183 / 0 / 8.6e-08 |
| A | 4 | flux3d layer 1 | 7320 / 0 / 9.1e-07 | 315 / 0 / 9.1e-07 | 318 / 0 / 9.1e-07 |
| A | 4 | flux2d | 7320 / 0 / 1.7e-07 | 315 / 0 / 1.3e-07 | 318 / 0 / 1.3e-07 |
| A | 6 | flux3d layer 1 | 7143 / 0 / 1.0e-06 | 492 / 0 / 1.0e-06 | 495 / 0 / 1.0e-06 |
| A | 6 | flux2d | 7143 / 0 / 2.2e-07 | 492 / 0 / 1.3e-07 | 495 / 0 / 1.3e-07 |
| A | 8 | flux3d layer 1 | 6996 / 0 / 1.2e-06 | 639 / 0 / 1.3e-06 | 648 / 0 / 1.3e-06 |
| A | 8 | flux2d | 6996 / 0 / 2.2e-07 | 639 / 0 / 1.7e-07 | 648 / 0 / 1.7e-07 |
| B | 2 | flux3d layer 1 | 7497 / 0 / 8.3e-07 | 138 / 0 / 8.3e-07 | 138 / 0 / 8.3e-07 |
| B | 2 | flux2d | 7497 / 0 / 3.4e-07 | 138 / 0 / 1.7e-07 | 138 / 0 / 1.7e-07 |
| B | 3 | flux3d layer 1 | 7452 / 0 / 7.5e-07 | 183 / 0 / 3.0e-07 | 183 / 0 / 3.0e-07 |
| B | 3 | flux2d | 7452 / 0 / 3.4e-07 | 183 / 0 / 1.5e-07 | 183 / 0 / 1.5e-07 |
| B | 4 | flux3d layer 1 | 7320 / 0 / 9.1e-07 | 315 / 0 / 8.3e-07 | 318 / 0 / 8.3e-07 |
| B | 4 | flux2d | 7320 / 0 / 3.0e-07 | 315 / 0 / 2.3e-07 | 318 / 0 / 2.3e-07 |
| B | 6 | flux3d layer 1 | 7143 / 0 / 7.5e-07 | 492 / 0 / 6.8e-07 | 495 / 0 / 6.8e-07 |
| B | 6 | flux2d | 7143 / 0 / 3.4e-07 | 492 / 0 / 1.9e-07 | 495 / 0 / 1.9e-07 |
| B | 8 | flux3d layer 1 | 6996 / 0 / 9.8e-07 | 639 / 0 / 9.8e-07 | 648 / 0 / 9.8e-07 |
| B | 8 | flux2d | 6996 / 0 / 3.4e-07 | 639 / 0 / 1.7e-07 | 648 / 0 / 1.7e-07 |
| C | 2 | flux3d layer 1 | 7497 / 0 / 8.8e-07 | 138 / 0 / 8.8e-07 | 138 / 0 / 8.8e-07 |
| C | 2 | flux2d | 7497 / 0 / 2.4e-07 | 138 / 0 / 1.5e-07 | 138 / 0 / 1.5e-07 |
| C | 2 | flux3d bottom layer | 7497 / 0 / 3.8e-07 | 138 / 0 / 2.1e-07 | 138 / 0 / 2.1e-07 |
| C | 3 | flux3d layer 1 | 7452 / 0 / 8.8e-07 | 183 / 0 / 8.8e-07 | 183 / 0 / 8.8e-07 |
| C | 3 | flux2d | 7452 / 0 / 2.4e-07 | 183 / 0 / 1.8e-07 | 183 / 0 / 1.8e-07 |
| C | 3 | flux3d bottom layer | 7452 / 0 / 3.8e-07 | 183 / 0 / 1.7e-07 | 183 / 0 / 1.7e-07 |
| C | 4 | flux3d layer 1 | 7320 / 0 / 8.8e-07 | 315 / 0 / 8.8e-07 | 318 / 0 / 8.8e-07 |
| C | 4 | flux2d | 7320 / 0 / 2.3e-07 | 315 / 0 / 2.0e-07 | 318 / 0 / 2.0e-07 |
| C | 4 | flux3d bottom layer | 7320 / 0 / 4.6e-07 | 315 / 0 / 2.5e-07 | 318 / 0 / 2.5e-07 |
| C | 6 | flux3d layer 1 | 7143 / 0 / 1.0e-06 | 492 / 0 / 9.5e-07 | 495 / 0 / 9.5e-07 |
| C | 6 | flux2d | 7143 / 0 / 2.3e-07 | 492 / 0 / 2.4e-07 | 495 / 0 / 2.4e-07 |
| C | 6 | flux3d bottom layer | 7143 / 0 / 6.3e-07 | 492 / 0 / 5.9e-07 | 495 / 0 / 5.9e-07 |
| C | 8 | flux3d layer 1 | 6996 / 0 / 9.7e-07 | 639 / 0 / 9.7e-07 | 648 / 0 / 9.7e-07 |
| C | 8 | flux2d | 6996 / 0 / 2.3e-07 | 639 / 0 / 1.8e-07 | 648 / 0 / 1.8e-07 |
| C | 8 | flux3d bottom layer | 6996 / 0 / 4.2e-07 | 639 / 0 / 4.4e-07 | 648 / 0 / 4.4e-07 |

**Result.** All 15 of 15 runs print `LGR GATE: PASS`. No row is off in
any of the 35 tables. The largest difference is 1.8e-06 of the scale
(case A on 3 processes, flux3d layer 1); the largest in the all-own class is 1.8e-06
(case A on 3 processes, flux3d layer 1) and in the mixed classes 1.8e-06 (case A on 3 processes, flux3d layer 1).
In 3 of the 35 tables the worst mixed value is larger than the worst
all-own value:

- case A on 8 processes, flux3d layer 1: 1.3e-06 against 1.2e-06
- case C on 6 processes, flux2d: 2.4e-07 against 2.3e-07
- case C on 8 processes, flux3d bottom layer: 4.4e-07 against 4.2e-07

The cause of the differences that remain was not separated. Two causes are
candidates: the order of summation (serial adds the node contributions in
node order; under MPI each rank adds those of its own nodes and the partial
sums are then added), and the small differences of the MPI hydrodynamic
solution itself.

Coverage is complete in every run: every serial row has exactly one
main-owner row, and no MPI row is missing from serial. `lgr_dbg_compare.py
node` passes in all 15 runs (`wlnv`, `mfluxv`, `difv`, `wxv`, `wyv`, on own and
on ghost nodes). On the same build the serial guard against the reference
binary passes (32 files identical, 0 different), as do the
reproducibility check and the MPI gate of CI.

**Before this stage** the mixed classes were off (rows off out of rows,
flux3d layer 1):

| Case | NP | main owner | elsewhere |
|---|---|---|---|
| A | 2 | 86 / 138 | 129 / 138 |
| A | 4 | 207 / 315 | 305 / 318 |
| B | 2 | 86 / 138 | 130 / 138 |
| B | 4 | 209 / 315 | 308 / 318 |
| C | 4 | 207 / 315 (bottom 205) | 305 / 318 (bottom 297) |

The controller measured these rows on the stage-1 head (`7a819806`) on
2026-11-21. The rows of case B were measured with the basin file that
`make init` builds, the table above with the tracked file; the two files
differ in 138 bytes and give slightly different runs of case B.

**Other checks**

- **Holders agree bit for bit** (task 2.2, commit `ac03c934`). In the
  4-process dumps of A, B and C, every side held by more than one rank
  prints the same value on every holder. That covers 315 rows; 3 of them are
  on the element held by three ranks.
- **Mutation check** (task 2.2, commit `ac03c934`). Case A on 4 processes,
  with the source otherwise unchanged: without the call of
  `lgr_mpi_flux_sum_3d`, flux3d is off in 200 of 315 main-owner rows and 307
  of 318 elsewhere rows; without the call of `lgr_mpi_flux_sum_2d`, flux2d is
  off in the same numbers of rows; with both calls restored the gate passes.
- **Process counts 3 and 8** (task 2.3). Before that task, case A on 3 and on
  8 processes and case C on 3 processes stopped with SIGFPE at a division by
  `idbdy`, the number of particles released on a process, which is 0 on a
  process without a release area. The percentage is now 0 in that case.
- **No dependence on memory** (task 2.4, issue #234). `./check_lgr_mpi.sh
  CASE NP perturb` runs a case twice, plainly and with `MALLOC_PERTURB_=85`,
  and compares every dump file byte for byte. A launched process saw no value
  in the plain run and `85` in the perturbed run in every row:

  | Case | Processes | Dump files compared | Differing | Lost-particle lines, plain / perturbed |
  |---|---|---|---|---|
  | A | 4 | 12 | 0 | 6 / 6 |
  | A | 8 | 24 | 0 | 13 / 13 |
  | B | 4 | 12 | 0 | 2344 / 2344 |
  | C | 4 | 16 | 0 | 4 / 4 |
  | C | 8 | 32 | 0 | 8 / 8 |

  Before task 2.4 the same check failed for case A on 8 processes (the
  particle dumps of four ranks differed). A pass is weak evidence on its own
  (the perturbation only reaches memory that `malloc` hands out), so two
  stronger checks back it: valgrind reports no error in the particle code
  for a serial run of case B and for case A on 8 processes, and a build with
  `-fcheck=bounds` (commit `58411503`, the same Fortran sources) runs 19
  serial and MPI runs of cases A to E, with and without the debug dump, to
  the end with no runtime message.
- **Particles lost at the edge of a process's domain.** Until the hand-over
  of the next stage exists, a particle that crosses the edge of a process's
  domain is counted as lost, like a particle that leaves through an open
  boundary. The numbers of `loosing particle adv` lines in the MPI logs of
  the 15 runs above:

  | Case | 2 processes | 3 processes | 4 processes | 6 processes | 8 processes |
  |---|---|---|---|---|---|
  | A | 0 | 4 | 6 | 9 | 13 |
  | B | 1168 | 1813 | 2344 | 3479 | 4614 |
  | C | 0 | 4 | 4 | 10 | 8 |

  For case B the lines include particles that leave through the open
  boundary, and every process still releases its own set of particles there
  (corrected in the release stage). In the five runs of the perturbation
  check these numbers are the same in the plain and in the perturbed run;
  before task 2.4 they depended on memory.

## Task 3.2: the tracker's side table (cut-off sides)

**Measured** 2026-11-21 19:34 to 19:36 EET (from `date`) by the
implementer, on the source of the commit that adds this section (built on
its parent `08ce9c8c`, OpenMPI `libmpi.so.40`, the tracked basin files).

**Method.** Each case run on NP processes with `levdbg = 3` (the same
temporary STR file as `check_lgr_mpi.sh` makes). At start-up rank 0 writes
the global totals of the side table: N cut-off sides and M of them added
to the marks of `set_geom_mpi` (a side counted once per process that has
it), and the smallest and largest layer count of the element across a
cut-off side (`lgr_side_lmax`) with the number of cut-off sides whose
neighbour has fewer layers than the element on this side. Every cut-off
side is confirmed by the process its mark names (the element across, the
one the global mesh has there); no run aborted.

| Case | Processes | N | M | `lgr_side_lmax` min / max | Sides with a shallower neighbour |
|---|---|---|---|---|---|
| A | 2 | 46 | 2 | 1 / 1 | 0 |
| A | 3 | 61 | 2 | 1 / 1 | 0 |
| A | 4 | 107 | 4 | 1 / 1 | 0 |
| A | 5 | 111 | 4 | 1 / 1 | 0 |
| A | 6 | 165 | 5 | 1 / 1 | 0 |
| A | 8 | 219 | 1 | 1 / 1 | 0 |
| B | 2 | 46 | 2 | 1 / 1 | 0 |
| B | 3 | 61 | 2 | 1 / 1 | 0 |
| B | 4 | 107 | 4 | 1 / 1 | 0 |
| B | 5 | 111 | 4 | 1 / 1 | 0 |
| B | 6 | 165 | 5 | 1 / 1 | 0 |
| B | 8 | 219 | 1 | 1 / 1 | 0 |
| C | 4 | 107 | 4 | 1 / 16 | 12 |
| C | 8 | 219 | 1 | 1 / 17 | 26 |

**Result.** Every run has M > 0, and every added side lies between two
basin boundary nodes (the side `set_geom_mpi` does not mark). So every
run above is a test of spec section 7, case 3; the smallest is case A or B
on 8 processes (one such side). Cases A and B have the same mesh
topology and the same partition, so they have the same sides. No open
boundary side has an element across that another process holds, so the
open boundary marks (-1, kept as in a serial run) never hide a cut-off
side on this mesh.

The added sides now read as cut-off sides instead of walls: their flux is
no longer set to zero and a particle can cross them (counted as lost until
the hand-over of task 3.4). Particle dumps differ where particles reach
those sides (case A on 2 to 6 processes, case B on 2 to 6 processes); the
flux and node dumps are unchanged, and so are all dumps of case C and of
cases A and B on 8 processes. Lost-particle lines before / after:

| Case | 2 processes | 3 processes | 4 processes | 5 processes | 6 processes | 8 processes |
|---|---|---|---|---|---|---|
| A | 0 / 0 | 4 / 4 | 6 / 6 | 5 / 5 | 9 / 9 | 13 / 13 |
| B | 596 / 596 | 608 / 607 | 607 / 605 | 606 / 606 | 618 / 618 | 627 / 627 |
| C | | | 4 / 4 | | | 8 / 8 |

A control build that does everything except give the added marks to the
tracker reproduces every dump file of the 14 runs byte for byte (216
files), so the added sides are the only change.

Start-up cost on this mesh (1,402 nodes, 2,545 elements): 313 to 499 sides
looked up in the global mesh (summed over the processes), at most 0.0002 s
on the slowest process.

With the same binary (19:37 to 19:41 EET): `./check_lgr_mpi.sh CASE 4
perturb` passes for A, B and C (lost-particle lines plain / perturbed 6 / 6,
605 / 605, 4 / 4); `./check_lgr_serial.sh /home/razinka/wt-lgr-ref2/bin`
prints `SERIAL GUARD: PASS` and `./check_lgr_serial.sh repro` prints
`REPRO: PASS`.

## Task 3.7: the fallback for a failed element search (#223), and the new serial reference

**Measured** 2026-11-22 by the controller (times from `date`), on commit
`0fddec90` built with OpenMPI (`libmpi.so.40`), and on the reference builds
named below.

**What changed.** `particle_on_side` (`src/shyfem/lagrange_util.f90`) uses
the particle's own element instead of mesh nodes 1 to 3, changes nothing for
a move of zero length, puts the particle where its move leaves the element,
and lets it leave only through an open boundary it crosses outward. A side
cut off by the partition is treated like a side with a neighbour. The plan's
amendment after Task 3.7 has the full statement.

**Evidence that ties the test cases back to `main`.** The serial guard of the
final commit against the previous reference `/home/razinka/wt-lgr-ref2`
(main plus the deterministic vertex pick, `84f07ac6`), 03:58 EET: the only
file that differs is `mm_lgr_e.lgr.shy`, by this correction (`SERIAL GUARD:
FAIL` by design); the closed basin (A), the open-boundary case (B) and the
closed 3D basin (C) are byte-identical, and so are the hydrodynamic files of
every case. Against the new reference `/home/razinka/wt-lgr-ref3` (`0fddec90`),
04:01 EET: `SERIAL GUARD: PASS`. From here on the guard's reference is
`wt-lgr-ref3`.

**Serial effect on the Stokes-drift case E** (the ref2 binary against a
build with the routine's final code, measured at 02:5x EET; E's particle file
is byte-identical between `0bd9f268`, `b723c8e2` and `0fddec90` by the
implementer's comparisons of the fix rounds; `lgr_compare.py --mode pos --tol
1e-5`): 140 of its 145 particles are more than 1e-5 degrees from where the old routine put them at the end of the four-day run, the largest distance at any output is 1.17e-2 degrees (about 1 km), the first difference appears at the third output (3 h), and the counts are unchanged (145 in the basin, none left).

**On 4 processes** (the implementer's runs at `0bd9f268`, whose executable
code of the routine is the final one; the later commits change only the
self-test and comments, `./check_lgr_mpi.sh CASE 4 part`): every case keeps
the serial count at the end: A 145 / 145, B 408 / 408 with 595 / 595 lines of
particles leaving through the open boundary, C 648 / 648, E 145 / 145;
`perturb` passes for A, B, C and E (again at `b723c8e2` with the driver's new
self-test requirements in force).

**Built-in check.** At `levdbg >= 3` the side self-test writes one line with
the checks it ran and skipped per side kind. In a build with
`COMPILER_PROFILE=CHECK` (no optimisation, floating-point traps on), cases A
and B run to the end serially and on 4 processes; on 4 processes case B runs
24 checks at open sides and 28 at cut-off sides, none fails. A build with
`-fcheck=bounds` runs the 19 serial and MPI runs of the bounds gate without a
runtime message.

**Position floors on the new reference** (`gates/floors.sh` in the plan's
workspace: a serial run against six serial runs whose wind drag is changed by
a relative +-1e-5, +-7e-6 and +-4e-6; the floor is the envelope of the six;
compared with `lgr_dbg_compare.py part --by key`, limit 1e-5 degrees, case B
2 m):

| Case | Limit | Particles | Beyond the limit at the last output (six runs) | Largest distance at any output (six runs) | Particles with another `tt` (six runs, particle file) | Floor: beyond / largest / `tt` (table of the driver; measured envelope) |
|---|---|---|---|---|---|---|
| A | 1e-5 degrees | 145 | 51 to 78 | 7.2e-4 to 2.9734e-3 degrees | 0 | 78 / 2.98e-3 degrees (measured 2.9734e-3) / 0 (measured 0) |
| B | 2 m | 408 | 13 to 48 | 59 to 181.75 m | 0 to 2 | 48 / 182 m (measured 181.75) / 2 (measured 2) |
| C | 1e-5 degrees | 648 | 12 to 19 | 7.3e-5 to 7.1106e-3 degrees | 0 | 19 / 7.12e-3 degrees (measured 7.1106e-3) / 0 (measured 0) |
| E | 1e-5 degrees | 145 | 25 to 33 | 1.1e-3 to 4.2915e-3 degrees | 0 | 33 / 4.3e-3 degrees (measured 4.2915e-3) / 0 (measured 0) |

The table values are the measured envelopes rounded up. The `tt` floor (added in Task 5.1, used
by the `pos` mode as `--max-tt-differ`) is the most particles whose time `tt` differs from the
base run in one perturbed run, counted on the particle files of `gates/floors_runs/` with
`lgr_compare.py --mode pos`: in case B two particles leave the basin one time step apart in
three of the six runs (`+1e-5`, `+7e-6`, `+4e-6`). Until Task 5.1 the driver held A 2.97e-3
and C 7.1e-3 (rounded down, below the measurement); the gates of stage 3 quoted below ran
against those values and stay as recorded.

Case C's largest distance appears in the three runs with a smaller drag: from 22 h on the run leaves the serial track, the largest distance grows to 7.1e-3 degrees at 26 h and then does not change to the end (a particle that comes to rest away from its serial position); the three others reach at most 2.0e-4 degrees. Before the correction a single run per change gave A 74 / 6.7e-4, B 44 / 147 m, C 19 / 7.2e-5 (at the last output only) and E 0 (the old fallback pinned E's particles); those numbers are superseded. Measured 2026-11-22 04:04 EET on `/home/razinka/wt-lgr-ref3`, 28 runs, all ended; the gate script and its log are in the plan's workspace (`gates/floors.sh`, `gates/floors_ref3.log`).

## Task 3.5: the hand-over by position (AC11) and the hand-over check

**Measured** 2026-11-22 05:00 to 06:45 EET (from `date`) by the implementer and the controller,
on commits `14124b92`, `ee3ad4bb` and `7080cfef` (the last two change no particle's track),
MPI runs with OpenMPI `libmpi.so.40`.

**Conservation.** Counts and particles that left equal the serial run at every output in all
runs: A and C on 2, 3, 4, 6 and 8 processes (no particle lost), B on 2, 4 and 8 (595 left
through the open boundary in serial and MPI, no unmatched particle), E on 2, 4 and 8, D on 4.

**AC11: particles that went to another process by position** (A, B and C have no random walk:
every one is at zero displacement):

| Case | 2 processes | 3 | 4 | 6 | 8 |
|---|---|---|---|---|---|
| A | 0 | 0 | 0 | 2 | 1 |
| B | 0 | – | 1 | – | 2 |
| C | 0 | 1 | 2 | 0 | 2 |

Case E parks about 146,000 particle-steps, nearly all failed searches that no process can
answer; 39 went to another process on 4 and on 8 processes; the resolution costs 0.70 s of a
5.4 s run on 4 processes and 0.26 s on 8.

**Positions against the floors** (4 processes; beyond 1e-5 degrees, case B 2 m, at the last
output / largest distance at any output): A 24 / 4.3e-4 degrees (floor 78 / 2.97e-3 then,
measured 2.9734e-3, 2.98e-3 since Task 5.1); B 5 / 36 m (floor 48 / 182 m, measured 181.75 m);
C 0 / 9.9e-6 degrees (floor 19 / 7.1e-3 then, measured 7.1106e-3, 7.12e-3 since Task 5.1);
E 16 / 1.2e-3 degrees (floor 33 / 4.3e-3, measured 4.2915e-3); on 2 and 8 processes E reaches
1.09e-3 degrees. No pair at distance 0 has a
different crossing count.

**The hand-over check, by replay** (`./check_lgr_mpi.sh CASE NP handover`; jump test: twice the
stayed group's largest distance, floor 10 steps; count test: Poisson 99.9 % quantile):

| Run | Largest changed-process distance | Jump threshold | Verdict |
|---|---|---|---|
| C, 4 processes, before (`41b114ad`) | 1.13e-4 degrees | 6e-7 | FAIL (jump) |
| C, 8 processes, before | 1.13e-4 degrees | 6e-7 | FAIL (jump) |
| A, 8 processes, before | 1.45e-4 degrees | 5.96e-5 | FAIL (jump) |
| B, 8 processes, before | 80.75 m | 2.5 m | FAIL (jump) |
| A, C on 2, 3, 4, 6, 8 and B on 2, 4, 8, after (`ee3ad4bb`) | at most 2.98e-7 degrees (A), 0.25 m (B), 5.96e-8 degrees (C) | 6e-7 or more | PASS (both tests, 13 runs) |

Blind spot: in case A a single lag smaller than about 6e-5 degrees passes (the particles that
stay on their process differ by up to 2.98e-5 degrees, eight spacings of latitude).

**Built-in checks.** The serial walk check found 0 differences in A, B, C, D and E (the key's
order is tested walk by walk; no point of these meshes lies in two elements); on several
processes no particle was parked with a local hit that no owner answered. Bounds-checked and
`COMPILER_PROFILE=CHECK` builds of `7080cfef` run A, B, C and E serially and on 4 processes
without a runtime message or a trap. With 4 OpenMP threads on 4 processes two runs are
byte-identical to each other and to the one-thread run.

## Task 3.6: consistency check, OpenMP, empty ranks, and the cases of spec section 7

**Measured** 2026-11-22 06:52 to 07:34 EET (from `date`) by the implementer, on the binaries of
the two commits of Task 3.6 on top of `185321dd` (`cd980bcd`, and the follow-up that counts
the ids of check (c) over the ids given out; every run below was repeated on the follow-up's
binary with the same results), OpenMPI `libmpi.so.40`; the head binary of `185321dd` was kept
aside for the baseline dumps.

**What was added.** `lgr_mpi_check_consistency` (`src/shyfem/lagrange_mpi.f90`), called by
`lagrange` once per step right after the hand-over, at `levdbg >= 2` on more than one process
(a no-op serially). It checks (a) that the particles of all processes, in the domain
(`ie > 0`), left (`ie < 0`) and without an element (`ie = 0`), add up to the ids given out
(`idbdy`); (b) that every particle in the domain sits in a held element, every slot holds a
record, and no hand-over mark is left; (c) that no id occurs twice, on one process or on two
(exact: per-id counts summed over the processes). It aborts on every process after rank 0
has written every failing message. It is not active, with one line at start-up, when
`lgrini`, `lgrtrj` or `lgrpps` is set. The test hooks `LGR_TEST_DROP=R` / `LGR_TEST_DUP=R`
make process R lose its first arrival at a side, or keep a copy of the first particle it sends
at a side (passed with `mpirun -x NAME`).

**Fault tests** (case A, 4 processes, `levdbg = 2`, R = 2):

| Run | Before the check (hooks only) | With the check |
|---|---|---|
| `LGR_TEST_DROP=2` | ends normally, exit 0 (the hook's line: id 63 dropped at 49,500 s) | exit 33 at 49,500 s: `particle count: ... released (ids given out) 145, held 144`; all four processes stop |
| `LGR_TEST_DUP=2` | ends normally, exit 0 (id 8 kept at 78,900 s) | exit 33 at 78,900 s: `particle count: ... held 146` and `duplicate id 8 on processes 2 3`; all four stop |

A repeat gives the same messages; the same faults in cases B and C (R = 1 and 2) abort
likewise. The clean runs at `levdbg = 2` end without a message: A, B, C, D, E on 4
processes, A, B, C on 2 and 8. With `lgrpps` or `lgrtrj` set, the start-up line
`lgr_mpi_check_consistency: not active (release lgrpps ...)` (or `lgrtrj`) appears once.

**Tracks unchanged.** The dumps of A, B, C and E on 4 processes are byte-identical to those of
the head binary (52 of 52 files); `./check_lgr_serial.sh /home/razinka/wt-lgr-ref3/bin`
prints `SERIAL GUARD: PASS` (32 files identical, none skipped), `repro` prints `REPRO: PASS`,
`perturb` passes for A, B, C and E, and the hand-over check passes for A, B and C on 4 and 8
processes.

**OpenMP** (spec section 7, case 9; copies of A, C, E with `nomp = -1`, 4 processes,
`OMP_NUM_THREADS=4`, `levdbg = 3`): every log has `used OMP threads: 4`; two runs are
byte-identical to each other and to the one-thread run (A 12, C 16, E 12 files).

**Empty ranks** (case 5): in case A on 4 processes ranks 0 and 1 release nothing (rank 2: 49,
rank 3: 96 particles; rank 0 holds none in the whole run, rank 1 receives some later);
`./check_lgr_mpi.sh mm_lgr_a 4 part --by key --tol 0 --first-only --elem --ranks-empty-ok`
passes, and no process aborts or hangs.

**Positions against the floors** (`./check_lgr_mpi.sh CASE NP floor`; beyond 1e-5 degrees,
case B 2 m, at the last output / largest distance at any output; all twelve pass, no
unmatched particle, no layer or z difference):

| Case | 2 processes | 4 processes | 8 processes | Floor (then; measured envelope) |
|---|---|---|---|---|
| A | 25 / 4.38e-4 | 24 / 4.34e-4 | 27 / 4.35e-4 | 78 / 2.97e-3 degrees (measured 2.9734e-3; 2.98e-3 since Task 5.1) |
| B | 5 / 103.25 m | 5 / 36 m | 4 / 103.25 m | 48 / 182 m (measured 181.75) |
| C | 0 / 2.72e-5 | 0 / 9.89e-6 | 0 / 2.72e-5 | 19 / 7.1e-3 degrees (measured 7.1106e-3; 7.12e-3 since Task 5.1) |
| E | 18 / 1.09e-3 | 16 / 1.16e-3 | 18 / 1.09e-3 | 33 / 4.3e-3 degrees (measured 4.2915e-3) |

**Spec section 7** (the statistic lines at `levdbg >= 3`):
- Case 1: most hand-overs at a side of one particle in one step: 2 in case B on 4, 8 and 16
  processes (the shipped time step).
- Case 2: hand-overs that start in an element held by three processes: case B, at a side 14 on
  4 processes, 25 on 6, 56 on 8, 221 on 16; case A on 6: 2; by position only in the dense copy
  of case 6 (8 on 8 processes).
- Case 4: particles that left through the open boundary at the end of case B: serial 595; on 4
  processes 1, 12, 582, 0 (595); on 8 processes 13, 0, 0, 582, 0, 0, 0, 0 (595), the same ids.
  None of them left from an element whose main owner is another process (on 2, 3, 4, 6, 8 and
  16 processes and in the dense copy): the spec's form of case 4 does not occur in these runs.
- Case 6: a copy of case B with `nbdy = 200000`, `nbdymax = 400000` (a ten times smaller
  release spacing) and `idtlgr = '6h'` releases 200,001 particles; on 8 processes at most
  1,236 particles change process in one step (the step ending at 36,900 s). No particle is
  lost or duplicated (the check is active and silent; in the domain plus left = 200,001 at
  every output). The counts per class do not equal serial at the last three outputs: one
  particle that comes to rest in the permanently dry element 870 in the serial run is 0.0625 m
  (one single-precision step) away at 24 h, after a hand-over between 18 and 24 h, misses the
  element and has left at the open boundary by 36 h, so the part mode prints FAIL (COUNT at
  129,600, 151,200 and 172,800 s; positions up to 11.5 km apart). Serial runs whose wind drag
  is changed by a relative +-1e-5 change the class of 1 to 4 particles at the same outputs and
  reach 18.6 km; 688 of the 711 particles resting in the dry elements at the end are at the
  same place on 8 processes, against 536 and 561 in the two changed serial runs (708, 709 and
  713 rest there in all); the hand-over check passes on these dumps (rate of the changed group
  2.77e-3, of the stayed group 2.58e-3). This is consistent with the divergence the serial
  floor shows, but "counts equal serial at every output" is not met in this run. The same
  copy on 4 processes, where the two dry elements lie inside one process (no cut-off side),
  has the counts per class equal to serial at every output (no unmatched particle; at most 837
  particles change process in one step), and 707 particles rest in the dry elements at the
  end (684 at the serial place): both MPI runs have 3 or 4 fewer resting there than serial
  (711), the changed serial runs 2 fewer and 2 more, so the cut-off side at the dry element is
  not what makes the difference.
- Case 8: elements 365 and 870 are dry (`iwegv = 3`) for the whole run in both meshes (case B:
  1,258 dry element-steps, 1,154 of them these two; case C: 1,154). On 2 processes each of them
  has a cut-off side (shown by a temporary print); on 3, 6 and 8 processes (and 16 in case B)
  the count of dry element-steps with a cut-off side is not 0 either; on 4 processes it is 0
  (both lie inside one process).

## End of stage 3: the class floor, case 6, and the final gates

**Measured** 2026-11-22 08:00 to 08:29 EET (from `date`) by the controller; the dense runs on
the build of `a4335dfc`'s source (the final gates on a clean build of `a4335dfc`).

**Class floor** (the class of a particle: in the domain, left, resting; paired by key; the base
serial run against six serial runs with the wind drag changed by a relative +-1e-5, +-7e-6,
+-4e-6): A, B, C and E: no particle changes class at any output in any of the 24 comparisons
(class floor 0; the gate stays "counts equal at every output"). The dense copy of case B used
for case 6 above (200,001 particles): at most 4, 2, 3, 2, 1, 1 particles per output (envelope
4). The run on 8 processes differs by 1 particle at three outputs, within it; the run on 4
processes by none. The section above recorded case 6 as not met against "counts equal at every
output"; with the class floor as the gate it is met.

**The cause, traced** (the implementer, temporary instrumentation in a throwaway work tree):
for each particle that rests in a permanently dry element in one run and not in the other, the
first quantity that differs between the serial run and 4 processes is a flux or velocity of the
particle's own element, 1e-7 to 5e-7 relative, while its position, element and time are still
bit-identical and it has not been parked or handed over. Whether a particle stopped on the
side of the dry element comes to rest in it depends on where along the side it arrives.
Particles resting in the dry elements at the end: serial 711; 4 processes 707 (5 missing, 1
extra); 8 processes 708 (3 missing, 0 extra); serial with drag +-1e-7: 709 and 710 (2 and 1
missing, 0 extra); serial with drag +-1e-5: 709 and 713 (17 / 15 and 13 / 15). A very small
disturbance loses such entries one way, in a serial run as on several processes.

**Final gates of stage 3** (clean build of `a4335dfc`, 08:15 to 08:29): tool self-tests PASS;
serial guard against `wt-lgr-ref3` PASS; repro PASS; MPI hydrodynamics gate PASS; flux A, B, C
on 2, 3, 4, 6, 8 processes PASS (15); hand-over check A, C on 2, 3, 4, 6, 8 and B on 2, 4, 8
PASS (13); positions against the floors A, B, C, E on 2, 4, 8 PASS (12); perturbed twins A 4,
A 8, B 4, C 4, C 8, E 4 PASS; release gate with ids A, C on 6 and 10 processes PASS; the two
fault runs abort with exit 33 and the particle-count and duplicate-id messages; plain runs of
D and E on 4 and B on 8 processes at `levdbg = 2` end with the check silent. A build with
`-fcheck=bounds` (19 runs) and one with `COMPILER_PROFILE=CHECK` (A, B, C, E serially and on 4
processes) of `a4335dfc` run without a runtime message or a trap.

## Task 5.1 and 5.2: the particle file on several processes (AC2, AC3, AC7, AC8)

**Measured** 2026-11-22 09:17 to 09:34 EET (from `date`) by the implementer, on the stage-5
branch (`lgr/s5-output`): the gates on a build of the working tree that became commit
`8113ed74` (the commit changes one comment line against it; its own build was checked at the
end: case A on 4 processes writes the same particle file byte for byte, serial A is
unchanged, `ids` B on 4 passes), OpenMPI `libmpi.so.40`. After the controller's rulings
(09:50 to 09:56, tools only, same binary): AC8 within one printed digit of the envelope, `tt`
counted against a floor for the one-off copy of case B, and the floor table rounded up; the
numbers below are those of the reruns.

**What changed.** On several processes `lagrange` calls `lgr_mpi_output` at every output time
on every process; rank 0 gathers the records of the three blocks (active, inserted, exited),
orders each by id and writes them as `lgr_output` does; the inserted block comes from release
records kept by the process that released the particles. Before, no particle record was written
on several processes (`check_lgr_mpi.sh mm_lgr_a 4 pos` and `ids`: `no particle section found`,
`LGR GATE: FAIL`). The driver's `pos` mode now holds the positions against the case's floors
(`lgr_compare.py --max-beyond-last --max-largest`, the table of the `floor` mode; `hl` compared
for pairs in the same element only), and `ids` runs with `--same-counts --nel --nlv` from the
model header of the serial file (nel 2545; nlv 1, case C 19).

**AC2 (ids exact) and AC3 (positions against the floors)**, `./check_lgr_mpi.sh CASE NP ids`
and `... pos`; every inserted block equals serial exactly (largest |dx|, |dy| 0, no element
differs) in all 12 runs, and in the active and exited blocks every pair at distance 0 has the
same (global) element (A on 4: 9,933 pairs; B on 4: 46,690; the case-B copy below: 2,349,585):

| Case | Processes | ids | pos | Beyond the limit at the last output / floor | Largest distance at any output / floor (measured envelope) |
|---|---|---|---|---|---|
| A | 2 | PASS | PASS | 25 / 78 | 4.38e-4 / 2.98e-3 degrees (2.9734e-3) |
| A | 4 | PASS | PASS | 24 / 78 | 4.34e-4 / 2.98e-3 degrees (2.9734e-3) |
| A | 8 | PASS | PASS | 27 / 78 | 4.35e-4 / 2.98e-3 degrees (2.9734e-3) |
| B | 2 | PASS | PASS | 5 / 48 | 103 / 182 m (181.75) |
| B | 4 | PASS | PASS | 5 / 48 | 36 / 182 m (181.75) |
| B | 8 | PASS | PASS | 4 / 48 | 103 / 182 m (181.75) |
| C | 2 | PASS | PASS | 0 / 19 | 2.7e-5 / 7.12e-3 degrees (7.1106e-3) |
| C | 4 | PASS | PASS | 0 / 19 | 9.9e-6 / 7.12e-3 degrees (7.1106e-3) |
| C | 8 | PASS | PASS | 0 / 19 | 2.7e-5 / 7.12e-3 degrees (7.1106e-3) |
| E | 2 | PASS | PASS | 18 / 33 | 1.09e-3 / 4.3e-3 degrees (4.2915e-3) |
| E | 4 | PASS | PASS | 16 / 33 | 1.16e-3 / 4.3e-3 degrees (4.2915e-3) |
| E | 8 | PASS | PASS | 18 / 33 | 1.09e-3 / 4.3e-3 degrees (4.2915e-3) |

`tt` is compared exactly in all 24 runs (no `tt` difference). `./check_lgr_mpi.sh mm_lgr_a 4
floor` and `mm_lgr_c 4 floor` with the new table: PASS (24 / 78, 4.34e-4 / 2.98e-3; 0 / 19,
9.9e-6 / 7.12e-3).

Self-check of the table: each of the 24 perturbed serial runs of Task 3.7
(`gates/floors_runs/`) against its base run with `lgr_compare.py --mode pos` (`--tol 1e-5`,
case B `--tol 2`) and the table's three floors (`--max-beyond-last`, `--max-largest`,
`--max-tt-differ`): all 24 PASS (largest distances up to 2.97344e-3 in A, 181.75 m in B,
7.1106e-3 in C, 4.29153e-3 in E, the dump's values; `tt` differing for 2 particles in B
`+1e-5`, `+7e-6`, `+4e-6`, for none elsewhere). With the old table (A 2.97e-3, C 7.1e-3, rounded
down, `tt` exact) seven of them failed. The `pos` runs above were rerun with the `tt` floor in
the driver (B 2, A, C, E 0): all PASS, no `tt` differs in any of them.

**AC7.** `./check_lgr_serial.sh /home/razinka/wt-lgr-ref3/bin`: `SERIAL GUARD: PASS`, every
file identical (lgr.shy, hydro.shy, inf of A, B, C, E; hydro.shy, inf of D and of
`mar_menor_lagrange/mm_lgr_01`), also every `mpirun -np 1` file; `./check_lgr_serial.sh repro`:
`REPRO: PASS`.

**AC8** (`lgr_lgmean_compare.py`: `lgrelab -lgmean` of the serial file and of the 4-process
file of case A; the serial file is byte-identical to the base run of `gates/floors_runs/`; the
allowed difference of each value is the envelope of the base against the six perturbed runs,
value by value). The particle table (per record: active, new, exited, beached, types) is equal
in all 96 records, the three type files have the same times. Values beyond the envelope:

| Type | x | y | hl | age | sinking | c1 |
|---|---|---|---|---|---|---|
| 1 | 0 (max 1e-5 / envelope max 7e-5) | 1 (2e-5 / 7e-5) | 0 (0.025 / 0.030) | 0 | 0 | 0 |
| 2 | 2 (1e-5 / 2e-5) | 0 (1e-5 / 1e-5) | 1 (0.001 / 0.004) | 0 | 0 | 0 |
| 3 | 1 (1e-5 / 2e-5) | 0 (2e-5 / 3e-5) | 0 (0.030 / 0.032) | 0 | 0 | 0 |

Five of the 1,728 values are beyond their envelope, each by one unit of the last printed
decimal (1e-5 degrees, 1e-3 m), at times where all six perturbed runs print the same digits as
the base (envelope 0). Ruling (controller): a value passes if it is within the envelope plus one
unit of its last printed decimal (the printed means are rounded; an envelope of 0 there is a
rounding, not physics). With that rule (`lgr_lgmean_compare.py`, rerun 09:48): 1,728 values
compared, 1,723 within the envelope, 1,728 within the envelope plus one unit, 0 beyond:
`LGMEAN COMPARE: PASS`.

**Edge cases (Task 5.2).** Case B with `idtl = '30m'` in `$lagrg` (and `nbdymax = 100000`; 96
releases of 1,003 particles, 96,288 in all, two releases between outputs): every one of the 48
inserted blocks holds exactly the ids released since the previous output, equal as sets in the
serial and the 4-process file; `ids` on 4 PASS. Against case B's floors `pos` on 4 fails (202 >
48 beyond 2 m at the last output, 499 m > 182 m), which were measured on one release of 1,003
particles, and on the time `tt` of 4 particles (one whose serial time stays while the MPI time
advances, consistent with a particle resting in a dry element in one run only; two whose times
stay fixed in both runs at different values; one that leaves the basin one step later at the same
position). The copy's own floors measured the same way on `/home/razinka/wt-lgr-ref3` (base
against six perturbed serial runs, particle file): 577 to 1,258 beyond 2 m at the last output,
745 to 6,118 m largest distance, `tt` differing for 26 to 75 particles, 0 to 4 particles in
another block (active in one run, exited in the other) at some output; the 4-process run is
within all of them (202, 499 m, 4, 0); with `tt` compared exactly the copy fails, as the
perturbed serial runs do. Ruling (controller): the copy is a one-off configuration gated against its own
floors (`gates/case_b_idtl30m/` in the plan's workspace: the STR file and the measured
envelope), `lgr_compare.py --max-tt-differ N` counts the particles whose `tt` differs against a
floor (without it `tt` stays exact; the shipped cases keep it exact). Rerun 09:50 to 09:54:
`./check_lgr_mpi.sh mm_lgr_b 4 pos --max-beyond-last 1258 --max-largest 6118 --max-tt-differ
75`: PASS (202, 499 m, 4); `ids` on 4: PASS; the 48 inserted blocks again exactly the ids
released since the previous output, equal in both files (largest |dx|, |dy| 0, no element
differs). Case A with `itranf` one hour after `itanf` (release at the first output time):
`pos` and `ids` on 4 PASS, no output time before the release in either file; with `itranf` at
01:30 (release between outputs) both files skip the 01:00 output (nothing written while no
particle exists) and both PASS.

**Unchanged.** The debug dumps of A, B, C and E on 4 processes are byte-identical to those of
the stage-3 head `65064328`; `perturb` A, B, C, E on 4 PASS; `handover` B on 8 with
`--min-changed 1` PASS (1,803 changed-process pairs). A 4-process run of case B with a
continuous release (`lgrpps` on the river boundary; not supported on several processes) stops
at the first output with exit 33 and the message "particles 1047, release records taken 1003";
its file holds no particle record. No run on several processes leaves a `fort.NN` file.

## End of stage 5: the final gates

**Measured** 2026-11-22 10:33 to 10:52 EET (from `date`) by the controller, on a clean build of
`fbc65b4b` (OpenMPI `libmpi.so.40`): tool self-tests PASS; serial guard against `wt-lgr-ref3`
PASS, including the `mpirun -np 1` comparisons (AC7); repro PASS; MPI hydrodynamics gate PASS;
flux A, B, C on 2, 3, 4, 6, 8 processes PASS (15); hand-over check PASS (13); positions in the
debug dump against the floors A, B, C, E on 2, 4, 8 PASS (12); perturbed twins PASS (6); release
gate with ids on 6 and 10 processes PASS; **the particle file: ids exact (AC2) and positions
against the floors (AC3) for A, B, C and E on 2, 4 and 8 processes PASS (24)**; AC8
(`lgrelab -lgmean`, case A on 4 processes against the six perturbed serial runs) PASS; both fault
runs of the consistency check abort with exit 33; plain runs of D, E on 4 and B on 8 processes
at `levdbg = 2` end with the check silent. Builds with `-fcheck=bounds` and
`COMPILER_PROFILE=CHECK` of `7d3ca548` (the Fortran of `fbc65b4b`) run without a runtime message
or a trap.
