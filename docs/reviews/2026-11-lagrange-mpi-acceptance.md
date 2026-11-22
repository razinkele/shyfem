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

| Case | Limit | Particles | Beyond the limit at the last output (six runs) | Largest distance at any output (six runs) | Floor: beyond / largest |
|---|---|---|---|---|---|
| A | 1e-5 degrees | 145 | 51 to 78 | 7.2e-4 to 2.97e-3 degrees | 78 / 2.97e-3 degrees |
| B | 2 m | 408 | 13 to 48 | 59 to 182 m | 48 / 182 m |
| C | 1e-5 degrees | 648 | 12 to 19 | 7.3e-5 to 7.1e-3 degrees | 19 / 7.1e-3 degrees |
| E | 1e-5 degrees | 145 | 25 to 33 | 1.1e-3 to 4.3e-3 degrees | 33 / 4.3e-3 degrees |

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
output / largest distance at any output): A 24 / 4.3e-4 degrees (floor 78 / 2.97e-3); B 5 / 36 m
(floor 48 / 182 m); C 0 / 9.9e-6 degrees (floor 19 / 7.1e-3); E 16 / 1.2e-3 degrees (floor
33 / 4.3e-3); on 2 and 8 processes E reaches 1.09e-3 degrees. No pair at distance 0 has a
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
