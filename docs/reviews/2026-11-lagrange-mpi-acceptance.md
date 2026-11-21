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
