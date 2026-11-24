# Lagrangian particles under MPI: acceptance results (#217)

Measured results of the acceptance criteria in section 8 of
`docs/superpowers/specs/2026-11-21-lagrange-mpi-design.md`. The stage that
meets a criterion adds its section here.

## Summary: the final acceptance run (Task 7.2)

**Measured** 2026-11-22 13:02 to 13:40 EET (times from `date` and the scripts' stamps) by the
implementer of Task 7.2, on a clean build of the head of `lgr/s7-stops`: `make clean`, then
`PATH=/usr/bin:$PATH make fem NETCDF=true NETCDFDIR=/usr NETCDFFDIR=/usr/local` (12:55 to 13:02),
built at `ddf46f53`, whose Fortran is that of the head `3b460653` (the commit after it changes
`check_mpi.sh` only); OpenMPI `libmpi.so.40`, binary sha256 `68a77b58…`, the tracked basin files.
Every number in the table comes from the logs of this run (scripts and logs: `docs/reviews/evidence/2026-11-lagrange-mpi/t72/`; the
details are in the section "Task 7.2" at the end; the evidence folder's README says what each
file is and how to run it). All gates were run
again; nothing measured on the branch before is reused. What is reused was measured on the serial
reference build `wt-lgr-ref3` (commit `0fddec90`) and does not depend on the branch's code since:
the position and `tt` floors of the driver's table (Tasks 3.7 and 6.1), the six perturbed serial
particle files that make the AC8 envelope (written by
`testcases/examples/mar_menor/measure_lgr_floors.sh`; 61 MB, not kept in the repository, the
script makes them again byte for byte), and the class floor 4 of the
dense copy of case B (serial runs; the serial results of the shipped cases are byte-identical to
`wt-lgr-ref3`, AC6 below). Cases: A `mm_lgr_a`, B `mm_lgr_b`, C `mm_lgr_c`, D `mm_lgr` (random
walk), E `mm_lgr_e` (Stokes drift), W `mm_lgr_w` (case A with one release polygon around the whole
basin). Commands run in `testcases/examples/mar_menor`; NP is 2 and 4.

| # | Criterion, as now defined | Command | 2 processes | 4 processes | Limit | Verdict |
|---|---|---|---|---|---|---|
| AC1 | `flux3d` and `flux2d` in every held element equal serial; A, B, C (C also its bottom layer) | `./check_lgr_mpi.sh CASE NP flux` | rows off 0 (7,635 serial rows each, every one covered by exactly one main-owner row); largest A 1.0e-6, B 8.3e-7, C 8.8e-7 | rows off 0; largest A 9.1e-7, B 9.1e-7, C 8.8e-7 | 1e-5 of the array's largest serial value (spec, unchanged) | PASS. Since #238 (2026-11-22) mode flux passes `--tol 0` (every flux equal to the serial one); the rows above were measured at 1e-5 and are 0 at `--tol 0` only with the ring fix of #238 |
| AC2 | A, B, C, E, W: the same ids in the same blocks at every output, the same count per block (class floor 0: conservation exact), valid elements and layers | `./check_lgr_mpi.sh CASE NP ids` | 5 of 5 PASS | 5 of 5 PASS | exact | PASS |
| AC3 (replaced) | Positions against the floors measured on the serial reference, in the particle file and in the dump; hand-over fidelity by the jump and count tests; in the particle file the inserted block, the layers, z and the element of every pair at distance 0 exact, `tt` within the `tt` floor. Replaces the 1e-5 degrees / 2 m of the spec: spec section 10a ("Positions cannot be gated at 1e-5 degrees or 2 m", "The hand-over check's rule is set by replay") and the plan's amendments after Tasks 3.4, 3.5, 3.7 and 5.2. **Owner decision 2026-11-22, after the final review: "Accept the replacement"** (spec section 10a; plan, amendment after Task 3.4) | `./check_lgr_mpi.sh CASE NP pos` and `... floor` (A, B, C, E, W); `... handover` (A, B, C, W; `--min-changed 1` on 4) | beyond the limit at the last output / largest distance at any output: A 25 / 4.38e-4, B 5 / 103.25 m, C 0 / 2.72e-5, E 18 / 1.09e-3, W 8 / 2.78e-3 degrees (file and dump give the same); `tt` differs for no particle; hand-over check PASS 4 of 4 (largest changed-process distance A 2.4e-7, B 0, C 0, W 0) | A 24 / 4.34e-4, B 5 / 36 m, C 0 / 9.9e-6, E 16 / 1.16e-3, W 8 / 3.26e-4; no `tt` difference; hand-over check PASS 4 of 4 (A 6.0e-8, B 0.25 m, C 6.0e-8, W 6.0e-8) | floors A 78 / 2.98e-3, B 48 / 182 m, C 19 / 7.12e-3, E 33 / 4.3e-3, W 37 / 4.32e-3; `tt` floor B 2, W 1, else 0; jump threshold twice the stayed group's largest distance, at least 10 single-precision steps; count test at the Poisson 99.9 % quantile | PASS |
| AC4 | Case D: ids over the three blocks and the count per block equal serial at every output, every active particle in the basin and in a valid layer; the consistency check (`levdbg = 3`) silent. No case F (spec section 10a, "3D") | `LGR_LEVDBG=3 ./check_lgr_mpi.sh mm_lgr NP ids` | PASS (145 active, none left at the end); 0 went to another process by position | PASS; 73 went to another process by position | exact | PASS |
| AC5 | Case D: mean position and spread of each release group against serial | `docs/reviews/evidence/2026-11-lagrange-mpi/ac5_stats.py` on the files of the AC4 runs and a third serial run | 3 types x 4 values: largest difference 2.07 times the largest difference among three serial runs | largest 1.50 times it | reported, not gated | reported: no MPI value differs from the first serial run by more than three times the spread of three serial runs; 7 of 24 by more than three times the difference of the first two |
| AC6 | Serial runs: A, B, C, E, W `.lgr.shy`, `.hydro.shy`, `.inf`; D and `mar_menor_lagrange/mm_lgr_01` `.hydro.shy`, `.inf`, byte-identical to the reference build | `./check_lgr_serial.sh /home/razinka/wt-lgr-ref3/bin` | 19 of 19 files identical (`SERIAL GUARD: PASS`) | – | byte-identical | PASS |
| AC7 | `mpirun -np 1` byte-identical to serial | the same guard (its `vs np1` comparisons) | 19 of 19 files identical | – | byte-identical | PASS |
| AC8 (limit replaced) | `lgrelab -lgmean` of the MPI file of case A against the serial file: the same particle table; each value within the envelope of the six perturbed serial runs plus one unit of its last printed decimal. Replaces "within the AC3 limit": plan amendment after Task 5.2. **Owner decision 2026-11-22: "Accept the replacement"** (as AC3) | `python3 lgr_lgmean_compare.py SERIAL MPI BASE PERT x6` (the base and the six perturbed particle files of case A from `measure_lgr_floors.sh`, folder `lgr_runs/`) | table equal (96 records); 1,721 of 1,728 values within the envelope, 1,728 within it plus one unit, 0 beyond | 1,723 / 1,728 / 0 | as in the column "Criterion" | PASS |
| AC9 | The cases of spec section 7 | see "Task 7.2", spec section 7 | cases 1 to 9 each shown by a test or a recorded run of this session (case 6 on 8 processes, case 1 on 4 and 8) | | each has a test or a recorded run | PASS |
| AC10 | Each "stops" option on several processes: one message naming the option, non-zero exit, no crash, no particle file. Serially the same STR file starts and the MPI message never appears (the driver's gate; the serial outcome is printed, not gated) | `./check_lgr_mpi.sh mm_lgr_a NP stops` | 10 of 10 rows ok (exit 33, message and advice once each, no signal, no particle file). Serially: 4 end (`lbeach`, `artype`, `ised`, `ilarv`), 6 fail on their own, two of them crashes (`ilagr = 3` SIGFPE, #231; `ldecay` SIGSEGV, #226); no serial log has the MPI message | 10 of 10 rows ok; the same serial outcomes | as in the column "Criterion" | PASS. Final fix round (2026-11-22): 12 of 12 rows on 2 and on 4 processes with `rwhpar < 0` and `ipvert < -1` added (both end serially); the serial `lgrtrj` stop is now an abort, exit 33 (section "Final fix round") |
| AC11 | Particles that went to another process by position at zero displacement (A, B, C have no random walk; W added) | the relocation line of the `handover` runs | A 0, B 0, C 0, W 0 | A 0, B 1, C 2, W 1 | reported; no particle lost or duplicated by one (counts equal at every output, the consistency check silent) | reported; PASS |
| Focus 5 | The global particle limit (plan, Review Focus 5): `nbdymax` exceeded by the sum over the processes, or by one process, stops every process with the serial message, once, and no process hangs | `bash docs/reviews/evidence/2026-11-lagrange-mpi/focus5_nbdymax.sh NP` (case B, 1,003 particles released at the start, with `nbdymax` 500 and 200, on NP processes and serially; timeout 300 s) | 500: exit 33, `Cannot insert more than nbdymax particles` once, the abort line on both processes, not ended, no signal; 200: the same | 500: exit 33, message once, abort line on all 4 processes, not ended, no signal (the release puts 251, 252, 246, 254 particles on the processes: only the global sum passes 500); 200: the same (every process passes 200 by itself) | one message, non-zero exit on several processes, no hang; serially (both values) the message once, `STOP` with exit 0, as before | PASS |

Also on this build: the tool self-tests (`test_lgr_compare.sh`, `test_lgr_dbg_compare.sh`,
`lgr_lgmean_compare.py --selftest`) PASS; `./check_lgr_serial.sh repro` `REPRO: PASS`; the MPI gate
of CI with its new fifth check, `./check_mpi.sh 2` and `./check_mpi.sh 4`, `MPI GATE: PASS`;
perturbed twins of A, B, C, E, W on 4 processes PASS (every dump file byte-identical); the release
gate with ids (`part --by key --tol 0 --first-only --elem --ranks-empty-ok --ids`) of W on 2 and 4
PASS; the two fault runs of the consistency check abort with exit 33 and their messages; plain
runs of D on 2 and 4 and E on 4 at `levdbg = 2` end with the check silent. The 4-process sweep of
all shipped cases is in the section "Task 7.2" at the end: no case is worse than on 2026-11-21,
and `mm_lgr` now ends on 4 processes.

**Finding, outside the criteria, fixed in Task 7.3.** The sweep showed that the `.inf` file of a
particle run on several processes was wrong at its start: the particle module wrote its
`lagrange_nbdy:` line (`drogue` in `src/shyfem/lagrange_main.f90`, on main since the initial commit)
on every process with that process's own count, and the first hours of the file were missing (case
A: 1,080 energy lines on 4 processes against 1,152 serially, none before 06:05; `lagrange_nbdy` 145
on every serial line, per-process values 0, 96, 122, ... on 2,233 lines of the 4-process file). It
had the symptom of #220 and the mechanism (every process opening the `.inf` through `getinfo`) is
confirmed by the fix: on several processes only rank 0 now calls `getinfo` and writes the line, with
the global particle count. After the fix the `.inf` of every particle case on 4 processes has the
serial number of energy lines at the same times and the serial `lagrange_nbdy` value at every step.
The detail is in the section "Task 7.2" (the finding) and "Task 7.3" in its report; the check is
`lgr_inf_compare.py`, run by `check_lgr_mpi.sh CASE NP ids`.

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
differed in 138 bytes and give slightly different runs of case B (since
#251 the tracked file is the one `make init` builds).

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
final commit against the previous reference build `wt-lgr-ref2`
(main plus the deterministic vertex pick, `84f07ac6`), 03:58 EET: the only
file that differs is `mm_lgr_e.lgr.shy`, by this correction (`SERIAL GUARD:
FAIL` by design); the closed basin (A), the open-boundary case (B) and the
closed 3D basin (C) are byte-identical, and so are the hydrodynamic files of
every case. Against the new reference build `wt-lgr-ref3` (`0fddec90`),
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

**Position floors on the new reference** (superseded for case B by the re-measurement on the
rebuilt basin below, #251) (`testcases/examples/mar_menor/measure_lgr_floors.sh`,
then `floors.sh` in the plan's working folder; log `docs/reviews/evidence/2026-11-lagrange-mpi/floors_ref3.log`:
a serial run against six serial runs whose wind drag is changed by
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
base run in one perturbed run, counted on the particle files of the floor runs (`lgr_runs/` of
`measure_lgr_floors.sh`) with
`lgr_compare.py --mode pos`: in case B two particles leave the basin one time step apart in
three of the six runs (`+1e-5`, `+7e-6`, `+4e-6`). Until Task 5.1 the driver held A 2.97e-3
and C 7.1e-3 (rounded down, below the measurement); the gates of stage 3 quoted below ran
against those values and stay as recorded.

Case C's largest distance appears in the three runs with a smaller drag: from 22 h on the run leaves the serial track, the largest distance grows to 7.1e-3 degrees at 26 h and then does not change to the end (a particle that comes to rest away from its serial position); the three others reach at most 2.0e-4 degrees. Before the correction a single run per change gave A 74 / 6.7e-4, B 44 / 147 m, C 19 / 7.2e-5 (at the last output only) and E 0 (the old fallback pinned E's particles); those numbers are superseded. Measured 2026-11-22 04:04 EET on the reference build `wt-lgr-ref3`, 28 runs, all ended; the script is `testcases/examples/mar_menor/measure_lgr_floors.sh` and its log `docs/reviews/evidence/2026-11-lagrange-mpi/floors_ref3.log` (the particle files of the runs are made again by the script: for case A the seven files of a rerun on 2026-11-22 are byte-identical to the ones used here, log `floors_a_rerun.log` of the same folder).

### Position floors re-measured on the rebuilt basin (#251), 2026-11-24

**Why.** The tracked `testcases/examples/mar_menor/GRID/MM_coarse.bas` was written by `shypre`
before the exact decimal parsing of `istod` (`9abe01a4`, 2026-10-16); since then `shypre MM_coarse.grd`
writes 46 of its 2,545 element depths one unit in the last place lower (sha256 `ed71feb3…`, the tracked
file `1cb7ef14…`). Until #251 `make init` rebuilt the file, so CI and every tree that ran it used the
rebuilt basin while the floors above were measured on the tracked one. The owner decided to replace the
tracked basin with today's output (commit `5ebf495b`) and to measure the floors again on it.

**How.** `measure_lgr_floors.sh <bin> 5ebf495b key 3 "mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr_w"`
with an OpenMPI build of `9147b517` (the Fortran of `37f08788`, release 8.6.0), 13:23 to 13:25 EET,
35 runs, all ended; the `tt` counts with `lgr_compare.py --mode pos` on the particle files of the runs.
A control with the same build on the old tracked basin (inputs of `9147b517`) followed at 13:25. Log:
`docs/reviews/evidence/2026-11-lagrange-mpi/floors_basin251.log`.

| Case | Beyond the limit at the last output (six runs) | Largest distance at any output (six runs) | Particles with another `tt` | Floor before (`0fddec90`, old basin) | Floor now (8.6.0, rebuilt basin) |
|---|---|---|---|---|---|
| A | 51 to 78 | 7.2e-4 to 2.9734e-3 degrees | 0 | 78 / 2.98e-3 / 0 | 78 / 2.98e-3 / 0 (unchanged) |
| B | 11 to 44 (was 13 to 48) | 89.3 to 181.75 m (was 59 to 181.75) | 0 to 2 | 48 / 182 m / 2 | **44** / 182 m (measured 181.75) / 2 |
| C | 12 to 19 | 7.3e-5 to 7.1106e-3 degrees | 0 | 19 / 7.12e-3 / 0 | 19 / 7.12e-3 / 0 (unchanged) |
| E | 25 to 33 | 1.1e-3 to 4.2915e-3 degrees | 0 | 33 / 4.3e-3 / 0 | 33 / 4.3e-3 / 0 (unchanged) |
| W | 23 to 37 | 1.1e-3 to 4.3113e-3 degrees | 1 | 37 / 4.32e-3 / 1 | 37 / 4.32e-3 / 1 (unchanged) |
| D (`mm_lgr`) | not measured | | | 0 / 0 / 0 (owner) | 0 / 0 / 0 (owner; unchanged) |

Counts as measured, distances rounded up as before. **What moved them: the basin alone, and only in
case B.** With the same build on the old basin every row of the control equals `floors_ref3.log` and
`floors_w.log`, and its 35 particle files equal those of the reference runs (`lgr_compare.py --mode pos
--tol 0`; the files differ only in the version string of the header), so 8.6.0's serial changes since
`0fddec90` change none of these runs. Cases A, C, E, W and D read `GRID/MM_geo.bas` (built from
`MM_geo.grd`, not tracked, not touched by #251): the particle and hydrodynamic files of the 28 runs of
A, C, E and W are byte-identical on both basins (D was not run here). Case B reads `MM_coarse.bas`; in its base run 33 of the 408 particles are elsewhere at the last
output (2 of them by more than 2 m), the largest distance at any output is 14.75 m (at 45 h), and the
hydrodynamic values differ by less than 1e-4; its six perturbed runs give
+1e-5 44 (was 48), -1e-5 36 (33), +7e-6 30 (28), -7e-6 21 (23; largest 102.31 m, was 129.44),
+4e-6 20 (21), -4e-6 11 (13; largest 89.31 m, was 59.0); the largest of the six stays 181.75 m and the
`tt` count stays 2 in the same three runs. On the particle file (what the `pos` mode compares) B gives
10 to 43 particles beyond 2 m and the same largest distances, within the floor.

### Position floor of case C re-measured for #248, 2026-11-24

**Why.** Case C (`mm_lgr_c`) is the one 3D particle case, and it runs without turbulence closure
(`iturb = 0`). Until #248 `handle_gotm_init`, called at set-up whatever `iturb`, replaced the constant
`vistur`/`diftur` that `set_eddy` puts into `visv`/`difv` by GOTM's initial 1e-6; with #248 they stay
(0 by default, so the run has the molecular viscosity only). The currents of case C change (by up to
3.5e-2 m/s, the water level by 1.1e-4 m), and so do its particles, so its floor was measured again.
Cases A, B, E, W and D are 2D and byte-identical before and after #248.

**How.** `measure_lgr_floors.sh <bin> 7564a360 key 3 mm_lgr_c` with an OpenMPI build of #248 (the
Fortran of `7564a360`), 15:35 to 15:36 EET, 7 runs, all ended; the `tt` counts with `lgr_compare.py
--mode pos` on the particle files of the runs. A control with an OpenMPI build of origin/main `c917d27e`
(before #248) on the same inputs followed at 15:37. Log:
`docs/reviews/evidence/2026-11-lagrange-mpi/floors_vistur248.log`.

| Case | Beyond the limit at the last output (six runs) | Largest distance at any output (six runs) | Particles with another `tt` | Floor before (8.6.0 and origin/main) | Floor now (#248) |
|---|---|---|---|---|---|
| C | 14 to 25 (was 12 to 19) | 1.37e-4 to 3.9029e-4 degrees (was 7.3e-5 to 7.1106e-3) | 0 | 19 / 7.12e-3 / 0 | **25** / **3.91e-4** (measured 3.9029e-4) / 0 |

Count as measured, distance rounded up as before. **What moved it: #248 alone.** The control's rows equal
those of case C in `floors_basin251.log` row for row (19 / 7.1106e-3). With #248 the base run is another
run: 632 of its 648 particles are elsewhere at the last output, by up to 3.73e-2 degrees. Its six perturbed
runs give +1e-5 25, -1e-5 22, +7e-6 23, -7e-6 21, +4e-6 14, -4e-6 15 particles beyond 1e-5 degrees at the
last output, the largest distance 3.9029e-4 degrees (run -1e-5, at 45 h); the particle that came to rest
7.1e-3 degrees from its serial position in three runs before #248 does not do so now, hence the much smaller
distance floor. On the particle file (what the `pos` mode compares) C gives the same counts and distances.
`./check_lgr_mpi.sh mm_lgr_c 4 floor` and `... pos` pass with the new floor (0 particles beyond the limit,
largest distance 0: the 4-process run equals the serial one).

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
(their particle files, `lgr_runs/` of `measure_lgr_floors.sh`) against its base run with `lgr_compare.py --mode pos` (`--tol 1e-5`,
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
file of case A; the serial file is byte-identical to the base run of the floor runs; the
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
position). The copy's own floors measured the same way on the reference build `wt-lgr-ref3` (base
against six perturbed serial runs, particle file): 577 to 1,258 beyond 2 m at the last output,
745 to 6,118 m largest distance, `tt` differing for 26 to 75 particles, 0 to 4 particles in
another block (active in one run, exited in the other) at some output; the 4-process run is
within all of them (202, 499 m, 4, 0); with `tt` compared exactly the copy fails, as the
perturbed serial runs do. Ruling (controller): the copy is a one-off configuration gated against its own
floors (`docs/reviews/evidence/2026-11-lagrange-mpi/case_b_idtl30m/`: the STR file, the measured envelope and the script
that measured it), `lgr_compare.py --max-tt-differ N` counts the particles whose `tt` differs against a
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

## Task 6.1: cases D and E (AC4, AC5), a release polygon across all domains, spec section 7 case 4

**Measured** 2026-11-22 11:09 to 11:44 EET (from `date` and the runs' `simulation start` lines)
by the implementer, on the stage-6 branch (`lgr/s6-random`, from `b2f438fd`): the binary of the
work tree with this task's statistic line (`lagrange_mpi.f90`, committed as `e5357166` with the
first form of this section; OpenMPI `libmpi.so.40`); the
floors of the new case on the reference build `wt-lgr-ref3` (`0fddec90`) with the inputs of commit
`6b514083`. The floor log is `docs/reviews/evidence/2026-11-lagrange-mpi/floors_w.log`; the scripts of spec section 7,
case 4 are in `docs/reviews/evidence/2026-11-lagrange-mpi/d5/`.

**What was added.** (1) Case `mm_lgr_w.str` (commit `6b514083`): case A with its three release
polygons replaced by one rectangle around the whole geographic basin,
`INPUT/release_area_whole.txt` (in `INPUT/` so that the floors script and the stage-end gates,
which copy `GRID/` and `INPUT/`, pick it up); the release is the polygon path
(`lagbound_seed_particles`; all 2,545 elements inside), 80 particles of type 1 (the spacing comes
from the polygon's area, larger than the basin). It is in the driver's case list with floors, and
in the serial guard and `repro`. (2) The driver's `LGR_LEVDBG=2|3` (modes `pos` and `ids` only,
off by default): both runs at that `levdbg`, at 3 with the dump, the side self-test and the
re-location self-checks; whenever the driver sets `levdbg`, a run on several processes must hold
no line of `lgr_mpi_check_consistency` (it writes only when a check fails or is not active).
(3) A fourth line of the hand-over statistic at `levdbg >= 3` on several processes: `lgr left
the basin: particles N, from an element whose main owner is another process: M`, counted on the
particle array at the end of the particle run (a particle that has left keeps `ie = -(local
element it left)` on the process that carried it). With it the dumps of A, B, C and E on 4
processes are byte-identical to those of the start binary (52 of 52 files); the logs differ only
in the new line (sorted, clock and timing fields left out), serial logs not at all.

**Case E (AC2, AC3)**, `./check_lgr_mpi.sh mm_lgr_e NP ids` and `... pos`: all six PASS; 145
particles, none left, the inserted block exact, no `tt` difference:

| Processes | ids | pos | Beyond 1e-5 degrees at the last output / floor | Largest distance at any output / floor |
|---|---|---|---|---|
| 2 | PASS | PASS | 18 / 33 | 1.09e-3 / 4.3e-3 degrees |
| 4 | PASS | PASS | 16 / 33 | 1.16e-3 / 4.3e-3 degrees |
| 8 | PASS | PASS | 18 / 33 | 1.09e-3 / 4.3e-3 degrees |

**Case D, AC4** (`mm_lgr.str`, random walk `rwhpar = 0.5`, never seeded, #225), `LGR_LEVDBG=3
./check_lgr_mpi.sh mm_lgr NP ids` (`--same-counts --nel 2545 --nlv 1` from the model header of the
serial file): PASS on 2, 4 and 8 processes. At each of the 96 outputs the ids of the three blocks
equal serial, every active particle is in a valid element and layer, and the count per block
equals serial (145 active, none left); the consistency check (active at `levdbg = 3`) is silent;
the serial self-check of the search: 14,227 / 14,652 / 14,640 compared, 0 differing. The
hand-over by position under a nonzero displacement (the MPI run's line `lgr relocation by
position`; "nobody answered" = the point is outside the basin, treated as serially):

| Processes | Parked | Stayed | Kept for lack of a layer | Went to another process | Nobody answered | Within the margin and nobody answered | Handed over at a cut-off side |
|---|---|---|---|---|---|---|---|
| 2 | 407 | 172 | 0 | 2 | 233 | 0 | 2 |
| 4 | 425 | 174 | 0 | 62 | 189 | 0 | 220 |
| 8 | 540 | 157 | 0 | 148 | 235 | 0 | 394 |

**Case D, AC5** (not gated): per particle type at the last output (345,600 s; 49, 49 and 47
particles, none left in any run), mean position and standard deviation in degrees, from two serial
runs (S1, S2: the serial runs of the 2- and 4-process calls above) and the MPI runs; each MPI run
as its difference from S1, next to S2 − S1, the spread of two runs of an unseeded random walk:

| Type | Value | S1 | S2 − S1 | 2 processes − S1 | 4 processes − S1 | 8 processes − S1 |
|---|---|---|---|---|---|---|
| 1 | mean x | -0.773107 | +1.33e-3 | +1.39e-3 | -4.23e-3 (>3x) | +4.9e-5 |
| 1 | mean y | 37.689160 | -3.56e-3 | +3.99e-3 | +1.6e-4 | -6.7e-4 |
| 1 | sd x | 0.019991 | +8.60e-3 | +1.10e-2 | +7.90e-3 | +6.85e-3 |
| 1 | sd y | 0.034156 | +7.7e-4 | +7.58e-3 (>3x) | +1.3e-4 | -6.8e-4 |
| 2 | mean x | -0.798904 | +5.94e-3 | +7.9e-4 | +7.40e-3 | +3.08e-3 |
| 2 | mean y | 37.699912 | -7.4e-4 | +1.82e-3 | -2.95e-3 (>3x) | +1.03e-3 |
| 2 | sd x | 0.013537 | +6.2e-4 | +3.32e-3 (>3x) | +1.4e-4 | +3.37e-3 (>3x) |
| 2 | sd y | 0.018030 | +3.12e-3 | +4.71e-3 | +5.75e-3 | +5.33e-3 |
| 3 | mean x | -0.771329 | +2.11e-3 | -9.01e-3 (>3x) | -7.82e-3 (>3x) | -4.80e-3 |
| 3 | mean y | 37.754691 | -8.66e-3 | -1.82e-2 | -6.62e-3 | -4.78e-3 |
| 3 | sd x | 0.030718 | -4.43e-3 | +3.89e-3 | +1.45e-3 | -1.17e-3 |
| 3 | sd y | 0.041406 | -3.65e-3 | +9.0e-4 | -6.29e-3 | -9.21e-3 |

Seven of the 36 MPI differences are more than three times S2 − S1 for that value (marked). One
serial pair is one sample of the spread: with the third serial run (that of the 8-process call,
S3) the largest serial difference of each value (over S1, S2, S3) is 1.15e-3 to 1.39e-2 degrees,
and none of the 36 MPI differences is more than three times it (type 3, mean x: S3 − S1 =
-9.76e-3 against the 2-process run's -9.01e-3).

**A release polygon across all domains** (`mm_lgr_w`; on this machine a release polygon of the
shipped cases reaches two processes only on 6 of them, and another partitioner may cut
differently). Particles of the polygon per process in the dump's release block (t = 0), and the
release gate `./check_lgr_mpi.sh mm_lgr_w NP part --by key --tol 0 --first-only --elem
--ranks-empty-ok --ids`:

| Processes | Particles per process (rank 0, 1, ...) | Release gate |
|---|---|---|
| 2 | 40, 40 | PASS |
| 3 | 29, 27, 24 | PASS |
| 4 | 20, 21, 19, 20 | PASS |
| 6 | 12, 12, 16, 13, 13, 14 | PASS |
| 8 | 11, 11, 10, 9, 11, 8, 10, 10 | PASS |

Floors of `mm_lgr_w` (`measure_lgr_floors.sh <wt-lgr-ref3>/bin 6b514083 key 3 mm_lgr_w`, then
`floors.sh` in the plan's working folder, 11:20:56 EET, seven runs, all ended; log
`docs/reviews/evidence/2026-11-lagrange-mpi/floors_w.log`; the particle files are written again by the script): beyond 1e-5 degrees at the last output 23 to 37, largest distance at any
output 1.1124e-3 to 4.3113e-3 degrees; `tt` differs for 1 particle in each of the six runs
(particle 46 comes to rest in the permanently dry element 870 in every run, at a time between
327,900 and 329,100 s); class floor 0 (no particle unmatched at any output in the six dump
comparisons; the same particle rests in the dry element in all seven runs; none leaves the closed
basin). Driver table: 37 / 4.32e-3 degrees (measured 4.3113e-3) / `tt` 1. Self-check: each of the
six perturbed runs against the base run passes `lgr_compare.py --mode pos` with the table's three
floors and `lgr_dbg_compare.py part` with its two.

| Processes | ids | pos: beyond / largest | floor: beyond / largest | handover: changed-process pairs, largest changed distance / threshold |
|---|---|---|---|---|
| 2 | PASS | PASS: 8 / 2.78e-3 | PASS: 8 / 2.78e-3 | PASS: 46, 0 / 6e-7 |
| 4 | PASS | PASS: 8 / 3.3e-4 | PASS: 8 / 3.3e-4 | PASS: 113, 5.96e-8 / 6e-7 |
| 8 | PASS | PASS: 8 / 2.78e-3 | PASS: 8 / 2.78e-3 | PASS: 214, 5.96e-8 / 6e-7 |

(`handover` with `--min-changed 1` on 4 and 8 processes, as at the stage ends; no `tt` and no
inserted-block difference in `pos`; the relocation lines: parked 519 to 520, nobody answered 479
in each, as many as the serial run's failed searches, 479; went to another process 0, 1, 0.)

**Spec section 7, case 4** (a particle leaving through the open boundary from a mixed element held
by a process that is not its main owner). How a run takes a given partition: neither a build
option nor an STR parameter. `shypre -partition FILE.grd BASIN.grd` (the node type of FILE.grd is
the domain) writes the partition into the basin file; on NP processes `handle_partition`
(`src/utils/shympi/mpi_basin.f90`) uses a partition contained in the basin when it has NP domains
("partitiones contained in basin: 4 / using these partitiones..."), partitions with METIS when the
basin holds none, and stops when the counts differ; a serial run ignores it (a serial run of case
B with the partitioned basin is byte-identical to one with the same basin made without the
partition). `check_part_basin` (`src/utils/shympi/mpi_node.f90`) has no caller, and the tracked
`GRID/partition.2.txt`, `GRID/partition.4.txt` are statistics tables of a partition (domain,
nodes, elements, ghosts), not assignments. The partition files (`docs/reviews/evidence/2026-11-lagrange-mpi/d5/part_first.grd`, `part_second.grd`) are made from the
tracked `GRID/MM_coarse.4.node.grd` (the METIS partition of this mesh on 4 processes) by
`d5/d5_partition.py` of the same folder, and the runs are in a scratch copy of the test folder whose
`GRID/MM_coarse.bas` is rebuilt by `shypre -partition` (this basin differed from the tracked one
of that time in the 138 bytes `make init` changed, so the serial reference is the serial run of
the same folder; since #251 the tracked basin is today's `shypre` output). Where particles leave: in the serial run all 595 leave through open sides between
consecutive boundary nodes, 568 of them between nodes 163 and 177, whose elements are inner
elements of rank 2 with METIS (so no leaving is case 4 there: METIS on 4 processes, 0 of 595).

- First partition (open-boundary nodes 158..177 moved from rank 2 to rank 1, so that the 21
  elements with an open side between them have their main owner on rank 1 and are held by rank
  2): the run stops at start-up, before any particle exists, on two processes with `error stop
  setnod: open boundary node` for external node 158 ("the node is an inner node"). Cause, in the
  MPI layer of the hydrodynamics, not in the particle code: `setnod`
  (`src/utils/shyutilmpi/topo_update.f90`) sums the angles of every local element at its nodes
  on every process and then adds the ghost copies to the owner with
  `shympi_exchange_and_sum_2d_nodes`, although with a node partition the owner already holds
  every element around its own node; the angle of a shared node is counted once per holder, and
  a node whose sum passes 359.99 degrees is classified inner. A replay of that sum from the
  coordinates (`docs/reviews/evidence/2026-11-lagrange-mpi/d5/winkv.py`) names node 158 first for this partition, and 18 boundary
  nodes in all (14 open-boundary nodes and the four below); for METIS on 4 processes it
  predicts four material-boundary nodes classified inner (10, 16, 25, 32), which stops nothing
  and so is not shown by a run (code present since the initial commit; a finding outside #217
  for the owner).
- Second partition (the first, with every interior node next to 158..177 also on rank 1, then
  the interior nodes of the exit elements handed back to rank 2 one at a time, each kept only if
  the replay leaves the classification as with METIS): 8 elements with an open side on rank 1
  and the interior node on rank 2 (main owner rank 1, held by rank 2). It starts ("using these
  partitiones", partition quality 2.85). Case B on 4 processes with it:
  `LGR_LEVDBG=3 ./check_lgr_mpi.sh mm_lgr_b 4 ids` PASS (408 active and 595 left at the end, the
  counts per block equal serial at all 48 outputs, 595 lines of particles leaving in both logs,
  the consistency check silent); `floor` PASS (6 / 48 beyond 2 m, 36 / 182 m); `handover
  --min-changed 1` PASS (1,194 changed-process pairs, largest 0.25 m against 2.5 m). The new
  line: `lgr left the basin: particles 595, from an element whose main owner is another process:
  274`; the dump gives the same 274 (`d5/d5_count.py` of the evidence folder: particles of class D on each process
  against the main owner in the flux dump): rank 2 carried them out of elements 62 (104), 369
  (40), 512 (47), 526 (45), 537 (37) and 168 (1), all with main owner rank 1. The dump reads the
  same particle state as the line, so it checks the counting and the main-owner lookup; the
  premise of both (a particle that has left stays with the process that carried it out) holds in
  the dump: each of the 595 keeps one process and one element over all its 18,904 rows of class
  D. With METIS the same line reads 595 / 0. The whole D5 run from a commit, with the steps
  above, is `docs/reviews/evidence/2026-11-lagrange-mpi/d5/run_d5.sh` (rerun at 11:44 on `e5357166`: PASS, 274); the first partition's
  start-up stop is in `d5/setnod_first.txt`.

**Gates after the change** (same binary): `./check_lgr_mpi.sh CASE 4 ids` and `pos` for A, B, C
and E PASS (A 24 / 78, 4.34e-4; B 5 / 48, 36 m; C 0 / 19, 9.9e-6; no `tt` difference);
`perturb` A, B, C, E on 4 PASS (the consistency check silent in both runs of each);
`./check_lgr_serial.sh /home/razinka/wt-lgr-ref3/bin`: `SERIAL GUARD: PASS`, every file identical
(38 comparisons, with `mm_lgr_w`'s lgr.shy, hydro.shy and inf against the reference build and
`mpirun -np 1`; nothing skipped); `./check_lgr_serial.sh repro`: `REPRO: PASS` (A, B, C, E, W).
The driver's new paths: `LGR_LEVDBG=2 ./check_lgr_mpi.sh mm_lgr_a 4 ids` PASS with the check
silent; with `LGR_TEST_DROP=2` as well the run aborts with exit 33 and the driver prints the
check's particle-count lines and fails.

## End of stage 6: the final gates

**Measured** 2026-11-22 11:56 to 12:24 EET (from `date`) by the controller, on a clean build of
`e750fba3`: everything of the stage-5 final gates (tool self-tests, serial guard against
`wt-lgr-ref3` with case W, repro, MPI hydrodynamics, flux, hand-over check, positions in the dump
against the floors, perturbed twins, release gate with ids on 6 and 10 processes, AC8, fault
runs, plain runs) PASS, plus the particle file (ids exact, positions against the floors) for A,
B, C, E and W on 2, 4 and 8 processes, case D's ids (AC4) on 2, 4 and 8, and case W's floor,
hand-over check and release gate with ids on 2, 3, 4, 6 and 8: 94 gate runs PASS, none FAIL.
Builds with `-fcheck=bounds` (19 runs) and `COMPILER_PROFILE=CHECK` (A, B, C, E, W serially and on
4 processes) of `e750fba3` run without a runtime message or a trap.

## Task 7.1: options that stop under MPI (AC10)

**Measured** 2026-11-22 12:34 to 12:40 EET (from `date`) on a build of the working tree on top of
`0a21dc85` (committed as the commit of this task). `./check_lgr_mpi.sh mm_lgr_a 4 stops`: a scratch
STR copy of case A with the option set (by `sed`; `lgrini` and `lgrtrj` name a file that does not
exist; `icnn` adds a `$connec` section, `lgrpps` a boundary at node 218 with `lgrpps = 1`), run
on 4 processes and serially. Before the change the mode failed for all ten rows (`ilagr = 3` and
`icnn` stopped, but with the older wording: the message count was 0; `lbeach`, `artype`, `ised`,
`ilarv` ran to the end and wrote the particle file; `ldecay` died with SIGSEGV, `lgrini` with
SIGFPE/SIGSEGV on 4 processes; `lgrpps` and `lgrtrj` wrote the particle file before they failed).
After the change: `LGR GATE: PASS`.

| Option | Message (rank 0, once) | 4 processes: exit | Serial run |
|---|---|---|---|
| `ilagr = 3` | `Lagrangian option ilagr = 3 is not supported with MPI` | 33 | SIGFPE in the first release (#231), not the MPI message |
| `lbeach` (0.5) | `... option lbeach ...` | 33 | ends |
| `artype` (1) | `... option artype ...` | 33 | ends |
| `ldecay` (3600) | `... option ldecay ...` | 33 | SIGSEGV (a serial defect of its own, not part of this task) |
| `lgrini` | `... option lgrini ...` | 33 | stops: the file does not exist (own message) |
| `ised` (1) | `... option ised ...` | 33 | ends |
| `ilarv` (1) | `... option ilarv ...` | 33 | ends |
| `icnn` (1) | `... option icnn ...` | 33 | `connectivity: stations defined but no release` |
| `lgrpps` (1) | `... option lgrpps ...` | 33 | `Please change nbdymax in STR file` (the river releases more than 5000) |
| `lgrtrj` | `... option lgrtrj ...` | 33 | `lgrlin and lgrtrj not allowed` (case A has `lgrlin`); since the final fix round the serial stop is an abort, exit 33 |
| `rwhpar < 0` (-1, added in the final fix round) | `... option rwhpar < 0 ...` | 33 | ends |
| `ipvert < -1` (-2, added in the final fix round) | `... option ipvert < -1 ...` | 33 | ends (case A is 2D: nothing is drawn) |

Every row also prints `run on one process, or remove NAME` once, and no row has a SIGFPE, SIGSEGV
or `Fortran runtime` line or a particle file on 4 processes; no serial log holds the MPI message.
Other gates on the same build: `./check_lgr_serial.sh /home/razinka/wt-lgr-ref3/bin`
`SERIAL GUARD: PASS`; `./check_lgr_serial.sh repro` `REPRO: PASS`; `./check_lgr_mpi.sh CASE 4 ids`
and `pos` PASS for A, B, C, E, W; `LGR_LEVDBG=3 ./check_lgr_mpi.sh mm_lgr 4 ids` PASS (the
consistency check silent). None of these cases sets an option of the table.

## Task 7.2: the CI gate, the full acceptance run, the sweep, the follow-up issues

**Measured** 2026-11-22 12:55 to 13:40 EET (from `date`) by the implementer, on the clean build
described in the summary at the top. Scripts and logs are in `docs/reviews/evidence/2026-11-lagrange-mpi/t72/` (made in the plan's
working folder and moved there in the final fix round; the paths the logs print are those of the
run): `t72_ci.sh` (CI's conditions and the mutation check), `t72_acc.sh` (the criteria),
`t72_acc2.sh`, `t72_acc3.sh`, `t72_c7run.sh` (spec section 7, cases 4, 6, 7, and the third serial
run of AC5), `t72_sweep.sh` (the sweep), with their logs and the tools they call
(`t72_extract.py`, `t72_c7find.py`, `t72_c7check.py`, `t72_sweepjoin.py`).

### The particle check in the CI gate (C1, C2)

**What CI runs.** `.github/workflows/fortran-ci.yml` (not changed), job `mpi-build` on
`ubuntu-latest`: installs `gfortran openmpi-bin libopenmpi-dev libmetis-dev libnetcdf-dev
libnetcdff-dev libx11-dev libxt-dev`; builds with `make clean && make fem OMP=false MPI=true
PARTS=METIS METISDIR=/usr`; step "MPI run smoke" runs `make init` in
`testcases/examples/mar_menor` and `mm_hyd_00` on 2 processes; step "MPI gate (4 processes)" runs
`bash check_mpi.sh 4` there with `PATH=/usr/bin:$GITHUB_WORKSPACE/bin:$PATH`. The workflow runs on
pushes to `main` and on pull requests that touch `testcases/**` (among others), so the new check
runs on the stage PR itself. The step's comment in the workflow still names four checks.

**Check 5** (`check_mpi.sh`, commit `3b460653`; since the final fix round it also runs `ids` with the consistency check on and `handover --min-changed 1`, section "Final fix round" at the end): `bash check_lgr_mpi.sh mm_lgr_w "$NP" pos`, then
`... ids`, each counted in the gate's result through the gate's `fail` like checks 1 to 4 (exit
1 and `MPI GATE: FAIL` if either fails; the driver's last 25 lines are printed then). Case W
releases its particles from one polygon around the whole basin, so the release is split between
processes on any partition, also on one that another METIS version makes. `pos` holds the
positions against the floors measured on the serial reference (37 beyond 1e-5 degrees at the last
output, 4.32e-3 degrees at any output, 1 particle with another `tt`) and compares ids, layers,
types, the inserted block and the element of every pair at distance 0 exactly; `ids` requires the
same ids in the same blocks at every output, the same counts per block and valid elements and
layers.

**What the check needs, and whether CI has it.** `shyfem` and `shypre` from the build's `bin/`,
`mpirun` (`openmpi-bin`), `python3` (in the runner image; `lgr_compare.py` imports only `argparse`,
`math`, `struct` and `sys`, so the `python3-numpy` the serial job installs is not needed), and
tracked files only: `mm_lgr_w.str`, `GRID/MM_geo.grd`, `INPUT/release_area_whole.txt`,
`INPUT/wind_scir.txt`. One gap was closed: the driver stops when `GRID/MM_geo.bas` is missing, and
CI's `make init` builds only `MM_coarse` and `MM_coarse_smooth`; check 5 therefore runs
`(cd GRID && shypre -noopti MM_geo.grd)` when the file is missing (the precondition the driver
names). No file of the check names a path under `/home/razinka` or a scratch folder (`grep` of
`check_mpi.sh`, `check_lgr_mpi.sh`, `lgr_compare.py`, `mm_lgr_w.str`: nothing); the driver's modes
`pos` and `ids` make no temporary folder.

**Proof in CI's conditions** (`t72_ci.sh build`, 13:03 to 13:06 EET): a `git archive` of
`3b460653` (tracked files only; no `MM_geo.bas`), CI's own build command (`OMP=false MPI=true
PARTS=METIS METISDIR=/usr`, no NetCDF; 103 s; `libmpi.so.40`), `PATH=/usr/bin:<export>/bin:$PATH`
as in the step, `make init`, `bash check_mpi.sh 4`: check 5 built `GRID/MM_geo.bas` and printed

```
=== 5. mm_lgr_w (particles): particle file of 4 processes vs serial
mm_lgr_w pos: floor: particles beyond --tol 1e-05 at the last output both files share (t=345600.0): 8 <= 37: ok
mm_lgr_w pos: floor: largest distance at any output (t=327600.0): 0.000325978 <= 0.00432: ok
mm_lgr_w pos: tt: particles whose tt differs (any output, any block): 0 <= 1: ok
mm_lgr_w pos: LGR COMPARE: PASS (96 output times in A, 96 in B)
mm_lgr_w ids: LGR COMPARE: PASS (96 output times in A, 96 in B)
MPI GATE: PASS
```

**Run time.** The whole gate took 26 s, check 5 17 s of it (the work tree's build, 13:02 EET:
the same 26 s and 17 s, and the same numbers). In the last CI run of a stage branch (run
45012370458, `lgr/s6-random`) the gate's step took 7 s against 9 s here, so check 5 should add
about 15 to 20 s to the job, which took 2 min 24 s. The workflow sets no `timeout-minutes`, so the
job runs under GitHub's default limit of 360 minutes; the gate fits with a wide margin.

**Mutation check** (`t72_ci.sh <wt-lgr-ref3>/bin`, 13:02 EET; an export of the test
folders with the reference build `wt-lgr-ref3`, commit `0fddec90`, first on `PATH`; that build
predates the particle output on several processes): checks 1 to 4 pass (energy lines 5.42e-06;
the tilt stop; the restart; the 6-node stop), check 5 fails in both modes because the 4-process
file holds no particle record, not for a reason of setup (`GRID/MM_geo.bas` was built by the check):

```
  MPI file:
    cannot read file: no particle section found (ncust record + iwhat=0 block)
LGR GATE FAIL: pos comparison could not be made (tool exit code 2: ...)
MPI GATE FAIL: mm_lgr_w: mode pos of check_lgr_mpi.sh failed on 4 processes (log: mm_lgr_w.pos.gate.log)
...
MPI GATE FAIL: mm_lgr_w: mode ids of check_lgr_mpi.sh failed on 4 processes (log: mm_lgr_w.ids.gate.log)
MPI GATE: FAIL
```

With the work tree's binary the same gate prints `MPI GATE: PASS` (above, and in the work tree).

### The criteria (C3): what the table at the top rests on

The run (`t72_acc.sh`, 13:06:54 to 13:27:15) printed `LGR GATE: PASS` 57 times and `LGR GATE: FAIL`
never: flux A, B, C on 2 and 4 (6); ids and pos A, B, C, E, W on 2 and 4 (20); floor A, B, C, E, W
on 2 and 4 (10); handover A, B, C, W on 2 and 4 and B on 8 (9); case D ids on 2 and 4 (2); stops on
2 and 4 (2); the release gates (3); perturbed twins (5). Details that the table condenses:

- **AC1.** In every run every class (all own nodes, mixed with this process as main owner, mixed
  owned elsewhere) has 0 rows off; the largest values per class are equal in the three classes
  except B on 4 (all own 9.1e-7, mixed 8.3e-7); coverage complete (no MPI row missing from
  serial, every serial row with exactly one main-owner row). Elements held by three processes: 0
  on 2, 1 on 4 (`lgr topology` line), and its fluxes are in the comparison.
- **AC3.** Pairs at distance 0 with another element: 0 in every `pos` run; inserted blocks: 0
  differing; in the dump no unmatched particle and no layer or z difference at any output. The
  hand-over groups (pairs, beyond one step): changed process A 1 / 1, 192 / 0; B 121 / 0, 1,119 /
  1; C 0 / 0, 171 / 0; W 46 / 0, 113 / 0 on 2 / 4 processes; B on 8 1,803 / 0.
- **AC4.** The serial self-check of the search: 14,655 and 14,370 searches compared, 0 differing.
  Relocation by position on 4: parked 463, stayed 142, went to another process 73, nobody
  answered 248 (outside the basin, treated as serially), within the margin and unanswered 0; on
  2: 315, 161, 0, 154, 0. The numbers differ from those of Task 6.1 (the random walk is not
  seeded, #225).
- **AC5** (`t72_acc3.sh`, 13:31). Per type at the last output (345,600 s; 49, 49, 47 particles,
  none left), each run as its difference from the first serial run S1 (S2: the serial run of the
  4-process call; S3: a third serial run):

  | Type | Value | S1 | S2 − S1 | S3 − S1 | 2 processes − S1 | 4 processes − S1 |
  |---|---|---|---|---|---|---|
  | 1 | mean x | -0.773895 | +9.3e-5 | -1.82e-3 | +2.68e-3 | -1.88e-3 |
  | 1 | mean y | 37.690939 | -7.21e-3 | -3.48e-3 | -1.17e-2 | -3.48e-3 |
  | 1 | sd x | 0.025559 | +2.27e-3 | -1.27e-3 | -1.92e-3 | +1.94e-3 |
  | 1 | sd y | 0.038248 | -9.16e-3 | -4.95e-3 | -1.73e-2 | -2.87e-3 |
  | 2 | mean x | -0.799679 | +2.9e-4 | -2.52e-3 | +5.40e-3 | +3.71e-3 |
  | 2 | mean y | 37.701615 | -5.4e-5 | -1.08e-3 | +5.8e-5 | -1.62e-3 |
  | 2 | sd x | 0.017041 | +1.89e-3 | -1.49e-3 | -9.5e-4 | -1.22e-3 |
  | 2 | sd y | 0.023179 | -1.06e-3 | -3.62e-3 | +4.5e-4 | -2.39e-3 |
  | 3 | mean x | -0.782193 | +3.06e-3 | +4.63e-3 | +9.56e-3 | +4.25e-3 |
  | 3 | mean y | 37.747496 | -5.4e-4 | +4.28e-3 | +3.04e-3 | -1.7e-4 |
  | 3 | sd x | 0.031215 | +1.60e-3 | +2.25e-3 | -1.77e-3 | -3.30e-3 |
  | 3 | sd y | 0.035495 | +3.05e-3 | +6.09e-3 | +2.79e-3 | +3.50e-3 |

  Against the largest difference among the three serial runs of each value, the MPI differences
  are at most 2.07 times it (type 3, mean x, 2 processes), 8 of 24 are above 1 time and none above
  3 times; against S2 − S1 alone 7 of 24 are above 3 times (one serial pair is one sample of the
  spread).
- **AC6, AC7.** The guard compares 19 files against the reference build and the same 19 against
  `mpirun -np 1`: 38 identical, nothing skipped.
- **AC10.** On 2 and on 4 processes every row: exit 33, the message and the advice once each, no
  SIGFPE, SIGSEGV or `Fortran runtime` line, no particle file; serially `lbeach`, `artype`,
  `ised`, `ilarv` end; `ilagr = 3` SIGFPE (#231), `ldecay` SIGSEGV (#226), `lgrini` exit 2 (the
  last line of its log an `alloc_lagr` line; the driver removes the logs when every row passes), `icnn` "connectivity: stations defined but no release", `lgrpps` "Please change
  nbdymax in STR file", `lgrtrj` "lgrlin and lgrtrj not allowed"; no serial log has the MPI
  message (the same as Task 7.1).
- **AC11.** From the line `lgr relocation by position` of the `handover` runs ("went to another
  process"): the table's numbers; the same as at the end of stage 3 for A, B and C.

### Spec section 7 (AC9)

| Case | Shown by | Result |
|---|---|---|
| 1. A particle crosses two or more cut-off sides in one step | `handover` of B on 4 and 8 (`lgr hand-over` line) | most hand-overs at a side of one particle in one step: 2 on 4 and on 8 processes (1 on 2); both runs PASS |
| 2. An element held by three processes: fluxes summed over three holders, a particle crossing there | `flux` A, B, C on 4; `handover` B on 4 and 8, W on 4 | one element held by three processes on 4 (three on 8), in the flux comparison with 0 rows off; hand-overs at a side that start in such an element: B 14 on 4, 56 on 8, W 1 on 4 (the dense copy of case 6: 10,672 at a side and 8 by position on 8) |
| 3. A cut-off side whose two end nodes are basin boundary nodes | the side table at `levdbg = 3`, every dump run | `added between two basin boundary nodes`: 2 on 2 processes, 4 on 4, 1 on 8 (all cases; the same mesh and partition) |
| 4. A particle leaving through the open boundary from a mixed element held by a process that is not its main owner | `docs/reviews/evidence/2026-11-lagrange-mpi/d5/run_d5.sh HEAD` (case B with a partition written into the basin, 13:28) | `LGR_LEVDBG=3 ./check_lgr_mpi.sh mm_lgr_b 4 ids` PASS; `lgr left the basin: particles 595, from an element whose main owner is another process: 274`; the dump count gives 274 (all on rank 2); with METIS 0 of 595 |
| 5. A process without particles at release and at output | `part --by key --tol 0 --first-only --elem --ranks-empty-ok` A on 4 | release block per process 0, 0, 49, 96; PASS; the ids, pos, floor and handover runs of A on 4 with these two empty processes PASS |
| 6. More than 1,024 particles changing process in one step | the dense copy of case B (`docs/reviews/evidence/2026-11-lagrange-mpi/case6/`, 200,001 particles) on 8 processes, `part --by key` (13:28 to 13:30) | at most 1,236 particles change process in one step (the step ending at 36,900 s); 377,552 hand-overs at a side and 262 by position; the consistency check silent at every step; in the domain plus left = 200,001 at every output. The part mode prints FAIL on COUNT at 129,600, 151,200 and 172,800 s: one particle (key 1295, the same as at the end of stage 3) rests in the dry element in the serial run and has left in the MPI run: 1 against the class floor 4 of this copy, so the criterion as now defined holds. The hand-over check on these dumps: jump 17.25 m <= 112.5 m, count 855 <= 886, both ok (rates 2.77e-3 changed, 2.58e-3 stayed, as at stage 3). On 4 processes this copy peaks at 837 (stage 3), below 1,024, so it was not rerun there |
| 7. A release point on a side between elements of two processes: the serial run inserts it in both elements, the MPI run must give the same particles and ids | a constructed release (no shipped case has such a point, Task 4.2): case A with two square polygons, each centred exactly, in single precision, on the midpoint of a side between elements of two main owners (`t72_c7find.py`: side 515-1083, elements 1336 and 2512, main owners 0 and 1 on 2 processes; side 120-943, elements 446 and 451, main owners 0 and 1 on 4 processes); the polygon release puts its grid point (0, 0) at the centre, and the point lies on the side in `intri`'s arithmetic | serial run: each midpoint inserted twice, ids 13 (element 1336) and 73 (2512), ids 86 (446) and 94 (451); on 2 processes ids 13 and 73 in the same elements on processes 0 and 1; on 4 processes ids 86 and 94 in the same elements on processes 0 and 1; the release gate with ids (`part --by key --tol 0 --first-only --elem --ranks-empty-ok --ids`) and `ids` over the whole run (134 particles, every output) PASS on 2 and 4 (13:32 to 13:33). The first two checks (13:27 with squares of half-size 4e-3 degrees, 13:30 with these) reported one copy per point: the checker matched the dump's x, y exactly, but those come back from each copy's internal coordinates in its own element and differ in the last bits; matched within 1e-5 degrees (the release spacing is 1.4e-3 degrees) the run of record finds both copies |
| 8. A dry element next to a cut-off side | the `lgr dry elements` line of the dump runs | the permanently dry elements 365 and 870 have cut-off sides on 2 processes: dry element-steps with a cut-off side A 2,306 of 2,306, B 1,154 of 1,258, C 1,154 of 1,154, W 2,306 of 2,306; on 8 (B) 1,258 of 1,258; on 4 none (both lie inside one process); all these runs PASS |
| 9. More than one OpenMP thread with hand-overs | copies of A, C, E with `nomp = -1` and `levdbg = 3` on 4 processes, `OMP_NUM_THREADS=4` (two runs) and one thread | every log `used OMP threads: 4` (the one-thread run: 1); run 1 = run 2 = the one-thread run, every dump file byte-identical (A 12, C 16, E 12 files); hand-overs A 283 at a side, C 190 and 2 by position, E 10 and 39 |

### The 4-process sweep of all shipped cases (C4)

**How** (`t72_sweep.sh`, 13:05:55 to 13:39:51): the recipe of the sweep of 2026-11-21 (memory
note `project_mpi_sweep_2026-11-21`; its scripts `mpisweep.sh` and `eutrosweep.sh`): every
tracked `testcases/examples/*/*.str` except the `apn*` tool files, serially and on 4 processes,
niced, timeout 75 s (the restart writers, run first, 600 s; the EUTRO cases 1,800 s), classified
by exit code, `simulation end` and the count of progress lines (ended; still stepping at the
timeout; stop; crash). Differences from the recipe, all for the record's sake: the binary is the
clean build of the head (the recipe built `origin/main`); the EUTRO and mercury build
(`ECOLOGICAL=EUTRO MERCURY=true`, with the NetCDF flags; `libmpi.so.40`) is made in a `git
archive` export of the head, and the folder's own serial gates pass with it (`check_eco.sh` ECO
GATE: PASS, `check_mercury.sh` MERCURY GATE: PASS, `check_restart.sh` RESTART GATE: PASS); the
test folders are `git archive` exports (no outputs of earlier runs); the init also builds
`GRID/MM_geo.bas` (the particle cases need it; `make init` does not build it); the serial and the
4-process run of a case run one after the other (the recipe ran them at once; the machine rule
allows two model runs, and the acceptance run ran beside the sweep); `mm_lgr` and the new particle
cases get 600 s, so that load cannot turn an end into "still stepping"; and for every case that
ends in both modes the per-step `energy:` lines of the `.inf` are compared (`infcmp.py` of the
result comparison of 2026-11-21: agree <= 1e-5, drift <= 1e-2 of each column's largest value).
"Then" is the log of 2026-11-21 (main `43ff9c30`).

**Result: no case is worse than on 2026-11-21** (70 cases now: the 65 of then and the five new
particle cases; the 10 EUTRO cases with their build). `mm_lgr` (case D) now ends on 4 processes
(then: SIGFPE at the first particle output, #217). The two `restart_strip` cases now stop on 4
processes with "too many MPI processes for this mesh" (then: `make_domain: no nodes` and a SIGFPE;
#218, fixed on main by PR #219). Every other case has the class of then; the five new particle
cases end in both modes. The known results that are not regressions: the 16 tilt cases stop on 4
processes with the tilt message (#215, PR #216: as intended); `mm_hyd_22` stops serially in
`setnod` (the tutorial's deliberately unstable case; 22a and 22b are its fixes); the 10
`weutro_box` cases stop in both modes in the default build (no EUTRO or mercury linked; the two
`part2` restarts then abort) and end in both modes with the EUTRO build; `mm_rst_ssedi_write` and
`_read` have 504 energy lines on 4 processes against 576 serially (#220). #222 (`shyelab
-outformat nc` for EUTRO output) and #230 (3D with an open boundary) are not touched by the sweep's
classification. In the 13 cases where the result comparison of 2026-11-21 and this sweep both compare energy
lines, the numbers are the same (`agree`, 0 or 5.42e-6, or the #220 shape). "Stepping" against "ended" is load
(the 75 s timeout), not a change: `mm_hyd_assim`, `_beach`, `_beach_str` and three Venice cases
stepped then and end now.

**A finding: the `.inf` file of a particle run on several processes.** The particle cases have
fewer energy lines on 4 processes than serially: 1,080 against 1,152 for `mm_lgr`, `mm_lgr_a`,
`mm_lgr_e`, `mm_lgr_w` (the first 6 hours, 00:05 to 06:00, are missing) and 540 against 576 for
`mm_lgr_b` and `mm_lgr_c` (the first 3 hours); the lines both files have agree to 2.0e-5 (B 7.2e-6,
C 1.7e-5). The `lagrange_nbdy:` line, 145 on every one of the 1,153 lines of the serial `.inf` of
case A (1,152 time steps plus one call of `drogue` at the start time, before the first step, which
has no energy line), appears 2,233 times in the 4-process file with per-process values (0 on 1,097 lines, 96 on
147, 122 on 57, 55 on 33, 56 on 31, ...). It is written at `src/shyfem/lagrange_main.f90:566`
(`write(iuinfo,*) 'lagrange_nbdy: ',nbdy`, the process's own count) on every process, with no
master guard, and has been on main since the initial commit; on main a particle run on several
processes crashed before, so it never showed. Likely mechanism, not proven: `getinfo`
(`src/shyfem/iostr.f90`) opens the `.inf` on every process that calls it, so the other processes
write over the start of rank 0's file; the same symptom as #220 (the simple sediment module).
It changes no criterion above (none reads the `.inf` of a multi-process run; the serial `.inf` is
byte-identical to the reference, AC6) and no Fortran was changed for it in this task. The two
`mm_lgr_a.inf` files (532 KB each) are not kept in the repository: a build before `309226f6` writes
them again with `./check_lgr_mpi.sh mm_lgr_a 4 ids`; the draft issue text was not needed, the
defect was fixed in Task 7.3.

**Fixed in Task 7.3** (`drogue`): on several processes only rank 0 calls `getinfo` and writes the
`lagrange_nbdy:` line, and the value is the sum of the counts of all processes (one `MPI_Allreduce`
per call, every process takes part); on one process the call and the line are unchanged, and the
serial `.inf` files are still byte-identical (`SERIAL GUARD: PASS`). Nothing else in the particle
module calls `getinfo` or writes to the info file. Before and after, on 4 processes (energy lines,
`lagrange_nbdy` lines and values; serial: 1,152 or 576 energy lines, 1,153 or 577 count lines):

| Case | Energy lines before | Energy lines after | `lagrange_nbdy` after |
|---|---|---|---|
| A (`mm_lgr_a`) | 1,080 (count lines 2,233, values 0, 96, 122, ...) | 1,152 | 1,153 lines, all 145 |
| B (`mm_lgr_b`) | 540 | 576 | 577 lines, all 1003 |
| C (`mm_lgr_c`) | 540 | 576 | 577 lines, all 648 |
| D (`mm_lgr`) | 1,080 | 1,152 | 1,153 lines, all 145 |
| E (`mm_lgr_e`) | 1,080 | 1,152 | 1,153 lines, all 145 |
| W (`mm_lgr_w`) | 1,080 | 1,152 | 1,153 lines, all 80 |

| Build | Case | Serial then | Serial now | 4 processes then | 4 processes now | Energy lines now, serial vs 4 | Verdict |
|---|---|---|---|---|---|---|---|
| default | channel_turb/gotm_gen_20 | ended | ended | ended | ended | drift (5.62e-05) | same |
| default | channel_turb/gotm_gen_40 | ended | ended | ended | ended | drift (5.53e-05) | same |
| default | channel_turb/gotm_ke1_20 | ended | ended | ended | ended | drift (8.41e-05) | same |
| default | channel_turb/gotm_ke1_40 | ended | ended | ended | ended | drift (6.07e-05) | same |
| default | channel_turb/gotm_ke2_20 | ended | ended | ended | ended | drift (6.12e-05) | same |
| default | channel_turb/gotm_ke2_40 | ended | ended | ended | ended | drift (6.05e-05) | same |
| default | channel_turb/keps_20 | ended | ended | ended | ended | drift (1.02e-05) | same |
| default | channel_turb/keps_40 | ended | ended | ended | ended | drift (1.53e-05) | same |
| default | mar_menor/mm_hyd_00 | ended | ended | ended | ended | agree (5.42e-06) | same |
| default | mar_menor/mm_hyd_01 | ended | ended | ended | ended | agree (5.42e-06) | same |
| default | mar_menor/mm_hyd_02 | ended | ended | ended | ended | drift (2.03e-05) | same |
| default | mar_menor/mm_hyd_03 | ended | ended | ended | ended | drift (1.78e-05) | same |
| default | mar_menor/mm_hyd_11 | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_12a | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_12b | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_13 | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_21 | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_22 | stop: setnod: open boundary node (exit 0) | stop: setnod: open boundary node (exit 0) | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_22a | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_22b | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_23 | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_31 | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_32a | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_32b | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_41 | stepping (1223 steps) | stepping (1317 steps) | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_42 | stepping (808 steps) | stepping (849 steps) | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_43 | stepping (1727 steps) | stepping (2549 steps) | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | mar_menor/mm_hyd_assim | stepping (87 steps) | ended | stepping (69 steps) | ended | agree (0) | same |
| default | mar_menor/mm_hyd_beach | stepping (91 steps) | ended | stepping (63 steps) | ended | agree (0) | same |
| default | mar_menor/mm_hyd_beach_str | stepping (93 steps) | ended | stepping (66 steps) | ended | agree (0) | same |
| default | mar_menor/mm_hyd_conz | stepping (97 steps) | stepping (1057 steps) | stepping (68 steps) | stepping (291 steps) | – | same |
| default | mar_menor/mm_hyd_long | ended | ended | ended | ended | drift (4.43e-05) | same |
| default | mar_menor/mm_lgr | ended | ended | crash: SIGFPE at the first particle output (exit 136) | ended | serial 1152 lines, 4 processes 1080 | better on 4 |
| default | mar_menor/mm_lgr_a | – | ended | – | ended | serial 1152 lines, 4 processes 1080 | new case |
| default | mar_menor/mm_lgr_b | – | ended | – | ended | serial 576 lines, 4 processes 540 | new case |
| default | mar_menor/mm_lgr_c | – | ended | – | ended | serial 576 lines, 4 processes 540 | new case |
| default | mar_menor/mm_lgr_e | – | ended | – | ended | serial 1152 lines, 4 processes 1080 | new case |
| default | mar_menor/mm_lgr_w | – | ended | – | ended | serial 1152 lines, 4 processes 1080 | new case |
| default | mar_menor/mm_rst_conflict | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor/mm_rst_cycle_read | ended | ended | ended | ended | agree (5.42e-06) | same |
| default | mar_menor/mm_rst_cycle_write | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor/mm_rst_keps_write | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor/mm_rst_periodic | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor/mm_rst_read | ended | ended | ended | ended | agree (5.42e-06) | same |
| default | mar_menor/mm_rst_read_mpi | ended | ended | ended | ended | – | same |
| default | mar_menor/mm_rst_read_periodic | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor/mm_rst_read_repeat | ended | ended | ended | ended | agree (5.42e-06) | same |
| default | mar_menor/mm_rst_read_trunc | ended | ended | ended | ended | – | same |
| default | mar_menor/mm_rst_read_trunc72 | ended | ended | ended | ended | – | same |
| default | mar_menor/mm_rst_repeat | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor/mm_rst_ssedi_read | ended | ended | ended | ended | serial 576 lines, 4 processes 504 | same |
| default | mar_menor/mm_rst_ssedi_write | ended | ended | ended | ended | serial 576 lines, 4 processes 504 | same |
| default | mar_menor/mm_rst_write | ended | ended | ended | ended | agree (0) | same |
| default | mar_menor_lagrange/mm_lgr_01 | ended | ended | tilt stop (exit 33) | tilt stop (exit 33) | – | same |
| default | restart_strip/strip_rst | ended | ended | crash: make_domain: no nodes, SIGFPE (exit 33) | stop: too many MPI processes for this mesh (exit 33) | – | better on 4 |
| default | restart_strip/strip_warm | ended | ended | crash: make_domain: no nodes, SIGFPE (exit 33) | stop: too many MPI processes for this mesh (exit 33) | – | better on 4 |
| default | venice_lagoon/venlag | stepping (219 steps) | stepping (549 steps) | stepping (564 steps) | stepping (2237 steps) | – | same |
| default | venice_lagoon/venlag_assim | stepping (249 steps) | ended | ended | ended | drift (0.000125) | same |
| default | venice_lagoon/venlag_keps_smoke | stepping (264 steps) | ended | ended | ended | drift (0.000391) | same |
| default | venice_lagoon/venlag_smoke | stepping (230 steps) | ended | ended | ended | drift (0.000701) | same |
| default | weutro_box/eco_2d | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 1) | stop: no EUTRO in this build (exit 1) | – | same |
| default | weutro_box/eco_2d_mt | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 1) | stop: no EUTRO in this build (exit 1) | – | same |
| default | weutro_box/eco_3d | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 1) | stop: no EUTRO in this build (exit 1) | – | same |
| default | weutro_box/eco_3d_light | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 1) | stop: no EUTRO in this build (exit 1) | – | same |
| default | weutro_box/eco_3d_settle | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 1) | stop: no EUTRO in this build (exit 1) | – | same |
| default | weutro_box/eco_rst_part1 | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 0) | stop: no EUTRO in this build (exit 1) | stop: no EUTRO in this build (exit 1) | – | same |
| default | weutro_box/eco_rst_part2 | MPI_ABORT (exit 33) | MPI_ABORT (exit 33) | MPI_ABORT (exit 33) | MPI_ABORT (exit 33) | – | same |
| default | weutro_box/merc_2d | stop: no mercury in this build (exit 0) | stop: no mercury in this build (exit 0) | stop: no mercury in this build (exit 1) | stop: no mercury in this build (exit 1) | – | same |
| default | weutro_box/merc_rst_part1 | stop: no mercury in this build (exit 0) | stop: no mercury in this build (exit 0) | stop: no mercury in this build (exit 1) | stop: no mercury in this build (exit 1) | – | same |
| default | weutro_box/merc_rst_part2 | MPI_ABORT (exit 33) | MPI_ABORT (exit 33) | MPI_ABORT (exit 33) | MPI_ABORT (exit 33) | – | same |
| eutro | weutro_box/eco_2d | ended | ended | ended | ended | agree (0) | same |
| eutro | weutro_box/eco_2d_mt | ended | ended | ended | ended | agree (0) | same |
| eutro | weutro_box/eco_3d | ended | ended | ended | ended | drift (2.14e-05) | same |
| eutro | weutro_box/eco_3d_light | ended | ended | ended | ended | agree (5.35e-06) | same |
| eutro | weutro_box/eco_3d_settle | ended | ended | ended | ended | drift (2.14e-05) | same |
| eutro | weutro_box/eco_rst_part1 | ended | ended | ended | ended | agree (0) | same |
| eutro | weutro_box/eco_rst_part2 | ended | ended | ended | ended | agree (0) | same |
| eutro | weutro_box/merc_2d | ended | ended | ended | ended | agree (0) | same |
| eutro | weutro_box/merc_rst_part1 | ended | ended | ended | ended | agree (0) | same |
| eutro | weutro_box/merc_rst_part2 | ended | ended | ended | ended | agree (0) | same |

### Follow-up issues (spec section 9, and those found during the work)

States as of 2026-11-22 (`gh issue view`); every issue in the table is open unless stated (#218, named below the table, is fixed on main in PR #219).

| Issue | What | Where it stands after this work |
|---|---|---|
| #223 | `particle_on_side` intersected a particle's move with the triangle of mesh nodes 1 to 3 instead of its own element (spec section 9) | **Fixed on the branch in stage 3** (Task 3.7, two owner decisions), for serial and MPI runs alike: serial results of the Stokes-drift and random-walk runs change, the closed-basin and open-boundary cases stay byte-identical; the serial guard's reference `wt-lgr-ref3` is built from that commit. Main still has the old routine until `feat/lagrange-mpi` is merged. |
| #225 | the random numbers are never seeded, so a run with the random walk is not reproducible (spec section 9) | Not addressed. Case D (the random walk) is therefore gated on what does not depend on the stream (AC4: ids and counts per block exact, every particle in the basin and in a valid layer), and its mean and spread are reported, not gated (AC5); it has no position floor. |
| #226 | `lgr_output` looks up the coordinates of element 0 for deleted and decayed particles (spec section 9) | Not addressed. Decay (`ldecay > 0`) crashes in a serial run too (SIGSEGV in `xi_abc` ← `xi2xy` ← `lgr_output_fill`, reproduced in Task 7.1 and recorded on the issue); since stage 5 the serial and the MPI output share the record routine, so one fix covers both; on several processes `ldecay` stops at start-up (AC10). |
| #227 | `itlin = 1` (semi-Lagrangian momentum advection) is unverified on several processes (spec section 9) | Outside this project; not addressed. |
| #228 | the options that stop under MPI (spec section 9; tracking issue) | **The stops are in** (Task 7.1, AC10 above): `ilagr = 3`, `lbeach`, `artype`, `ldecay`, `lgrini`, `ised`, `ilarv`, `icnn` (any value other than 0 since the final fix round), `lgrpps`, `lgrtrj`, and since the final fix round `rwhpar < 0` and `ipvert < -1`, stop at start-up on several processes with one message naming the option. What remains is the issue's purpose: each option needs its own test case and acceptance criterion before it moves to "works", and the issue's table should gain `ilagr = 3` (it stops too; its serial crash is #231). The last item of spec section 9 belongs here: `lgr_mpi_reduce_connect` sums the connectivity matrices in place every step (the connectivity row of the table). |
| #230 | a 3D run with an open boundary differs between serial and MPI in its hydrodynamics (found in stage 1) | Not addressed (outside the particle module). Because of it case C is a closed 3D basin and there is no case F (spec section 10a). |
| #231 | `ilagr = 3` crashes in a serial run (found in stage 1) | Not addressed; `ilagr = 3` stops on several processes (AC10), and serially it still crashes in the first release (the stops gate prints it as the serial row's own failure). |
| #234 | the tracker read `ilhv` with a negative element number when a particle left the domain (found in stage 2) | **Fixed on the branch in stage 2** (Task 2.4, with two more reads of that kind and three declarations); serial files of A, B, C, E byte-identical with the fix. Main still has the defect until the merge. |
| #238 | `setnod` counts the angles of shared nodes more than once, so a boundary node can be classified inner on several processes (found in Task 6.1) | Outside this project (MPI hydrodynamics), not addressed. Found with a hand-written partition (spec section 7, case 4); a replay predicts that METIS on 4 processes misclassifies four material-boundary nodes of the Mar Menor mesh without stopping. |

Known issues of the 4-process sweep (C4 below), outside the particle module: #216 (the tilt
stop, by design), #218 (fixed on main in PR #219, a clear stop), #220 (simple sediment info lines
from every rank), #222 (`shyelab -outformat nc` for EUTRO and mercury output).

## Final fix round (2026-11-22, after the final review of the branch)

**Measured** 2026-11-22 14:39 to 15:16 EET (from `date`) by the implementer of the fix round, on
builds of the work tree of `lgr/s7-stops` (the Fortran of the round is commit `4145db7c`; OpenMPI
`libmpi.so.40`; the tracked basin files). Commands in `testcases/examples/mar_menor`.

**An abort instead of a bare `stop` on paths several processes run.** 41 bare `stop` statements
(the start-up checks and allocations of `mod_lagrange_init`, the growth of the particle array, the
tracker in `lagrange_vertical.f90`, the polygon release in `lagrange_init.f90`, `insert_particle`
and the release helpers in `lagrange_inout.f90`, `lagrange` and `drogue`, and `lagr_vel` of the
semi-Lagrangian advection) call `shympi_abort_internal` with the same message; on several processes
every process now ends instead of one stopping and the others waiting. The `MPI_Allreduce` of
`drogue` moved into the module (`lgr_mpi_global_count`). Neither changes a track: the debug dumps
of A, B, C and E, serially and on 4 processes (`./check_lgr_mpi.sh CASE 4 part`), are
byte-identical to those of `309226f6` (65 files of 65), `./check_lgr_serial.sh <wt-lgr-ref3>/bin`
prints `SERIAL GUARD: PASS` (38 comparisons, all identical) and `./check_lgr_serial.sh repro`
`REPRO: PASS`. A serial run that reaches one of these lines ends with exit 33 instead of 0 (the
`lgrtrj` row of the stops below).

**Two more options stop on several processes, and `icnn` on any value.** `rwhpar < 0` (the
diffusivity taken from the local diffusivity of the element) and `ipvert < -1` (the random
vertical release: `insert_particle_3d` draws a random depth with `random_number` for each of the
`|ipvert|` particles of a release point in a basin with more than one layer and `ilagr = 2`;
`ilagr = 3` stops anyway, and in a 2D basin or with `ilagr = 1` nothing is drawn, but the value
stops the run there too) ran on several processes untested; no shipped test case sets either. The
module switches connectivity on for any `icnn` other than 0, so the stop tests `/= 0`.
`./check_lgr_mpi.sh mm_lgr_a NP stops`, NP 2 and 4: `LGR GATE: PASS`, 12 of 12 rows (exit 33, the
message and the advice once each, no signal, no particle file); serially `rwhpar` (-1) and
`ipvert` (-2) end, the other rows as in Task 7.1 except `lgrtrj`, which still prints `lgrlin and
lgrtrj not allowed` but now ends through the abort, exit 33.

**Review Focus 5, the global particle limit** (row "Focus 5" of the summary table;
`docs/reviews/evidence/2026-11-lagrange-mpi/focus5_nbdymax.sh`, log `focus5_nbdymax.log` there).

| `nbdymax` | 4 processes | 2 processes | Serial |
|---|---|---|---|
| 500 | exit 33, message once, abort line on 4 processes, not ended | exit 33, message once, abort line on 2 processes, not ended | message once, `STOP`, exit 0 |
| 200 | the same | the same | the same |

No run hung (timeout 300 s, every run ended at the first release) and no run printed a signal.
On 4 processes the release puts 251, 252, 246 and 254 particles on the processes, so with 500 only
the sum over the processes passes the limit (the global test of `lgr_mpi_assign_ids`), and with
200 every process passes it by itself (the flag of `insert_particle`).

**The CI gate's check 5 sees a hand-over regression.** Check 5 runs `mm_lgr_w` in mode `pos`, in
mode `ids` with `LGR_LEVDBG=2` (the consistency check active at every step, silent in both runs),
and in mode `handover --min-changed 1`. `./check_mpi.sh 2`: `MPI GATE: PASS` in 37 s (28 s with
the version of `309226f6`); `./check_mpi.sh 4`: `MPI GATE: PASS` in 36 s (25 s): the round adds
9 s on 2 and 11 s on 4 processes. Hand-over check of check 5: 46 changed-process pairs on 2 (all
at distance 0), 113 on 4 (largest 5.96e-8 degrees against a threshold of 6e-7). The driver's mode
`handover` now passes `--min-changed 1` itself on several processes (a `--min-changed` among the
caller's arguments replaces it):

| Case | 2 processes | 4 processes | 8 processes |
|---|---|---|---|
| A | PASS (1 changed-process pair) | PASS (192) | PASS (374) |
| B | PASS (121) | PASS (1,119) | PASS (1,803) |
| C | **FAIL with the default**: 0 changed-process pairs; no particle changes process at all on this partition (0 hand-overs at a side, 0 by position); PASS with `--min-changed 0` | PASS (171) | PASS (269) |
| W | PASS (46) | PASS (113) | PASS (214) |

Case C on 2 processes: the controller's ruling (2026-11-22) keeps the driver's default, so that a
hand-over check in which no particle changes process cannot pass silently, and runs that one cell
with an explicit `--min-changed 0` (no hand-over can occur on this partition); every other run
passes, with the same groups as in the acceptance run. The end-of-stage gate on the head ran it so.

**`lgr_compare.py`: nothing compared is a failure.** A file without any output time cannot be read
(exit 2, as before); two files whose output times hold no particle passed in both modes and now
fail with `nothing compared: N output times in both files, no particle in them` (new lines of
`test_lgr_compare.sh`; RED before the change, `LGR COMPARE TEST: PASS` after).

**Other gates on the same build.** `./check_lgr_mpi.sh CASE 4 ids` and `pos` for A, B, C, E, W:
PASS (10 of 10). Tool self-tests: `LGR COMPARE TEST: PASS`, `LGR DBG COMPARE TEST: PASS`,
`LGMEAN SELFTEST: PASS`.

**The evidence is in the repository.** The inputs, logs and one-off scripts that this file, the
plan's amendments and the driver's floor table cite are in `docs/reviews/evidence/2026-11-lagrange-mpi/`
(its README lists each file, who cites it and how to run it); the floor script is
`testcases/examples/mar_menor/measure_lgr_floors.sh` and the bounds gate
`testcases/examples/mar_menor/check_lgr_bounds.sh`. The floor script, run from the repository
against the reference build for case A, gives the floor of the table again (78 / 2.9734e-3
degrees, the same seven runs) and writes particle files byte-identical to the ones AC8 used
(`floors_a_rerun.log`). The other moved scripts were run from the repository on the head
`e4da5233` (15:23 to 15:32): `t72/t72_ci.sh build` (a tracked-files-only export, CI's own build
command without NetCDF, `make init`, `bash check_mpi.sh 4`): check 5 with its new modes passes in
CI's conditions (`pos` 8 / 37 and 3.26e-4 / 4.32e-3; `ids` with the consistency check silent; the
hand-over check 113 changed-process pairs, largest 5.96e-8 degrees), `MPI GATE: PASS`, 41 s;
`d5/run_d5.sh`: `ids` PASS, `lgr left the basin: particles 595, from an element whose main owner
is another process: 274`, the dump count 274, and `part_second.grd` byte-identical to the kept
one; `t72/t72_c7run.sh`: the release gate with ids and `ids` on 2 and 4 PASS, `CASE 7 CHECK:
PASS` with the ids of the acceptance run (13 and 73, 86 and 94);
`testcases/examples/mar_menor/check_lgr_bounds.sh` (no NetCDF flags): `BOUNDS GATE: PASS`, 19 runs
without a runtime message, 413 compile lines with `-fcheck=bounds`. `t72_acc.sh`, `t72_acc2.sh`,
`t72_acc3.sh` and `t72_sweep.sh` (20 to 35 minutes each) were checked for syntax and paths only;
`t72_acc2.sh` and `t72_acc3.sh` share the copy and release-file code of `t72_c7run.sh`.

## End of stage 7 and of the final fix round: the final gates on the head

**Measured** 2026-11-22 15:39 to 16:08 EET (from `date`) by the controller, on the head of the
branch after the final review's fix round (`86834ad5`): a build with `-fcheck=bounds` (19 serial
and MPI runs) and one with `COMPILER_PROFILE=CHECK` (A, B, C, E, W serially and on 4 processes)
without a runtime message or a trap; on a clean build: tool self-tests PASS; serial guard against
`wt-lgr-ref3` (commit `0fddec90`) PASS with no file differing, including the `mpirun -np 1`
comparisons; repro PASS; MPI hydrodynamics gate PASS; flux A, B, C on 2, 3, 4, 6, 8 processes
(15), hand-over check (13; case C on 2 processes with an explicit `--min-changed 0`), positions in
the dump against the floors (12), perturbed twins (6), release gate with ids on 6 and 10
processes, the particle file (ids and positions) for A, B, C, E and W on 2, 4 and 8 processes,
case D's ids on 2, 4 and 8, case W's floor, hand-over check and release gate, the `stops` mode
(12 rows): 95 gate runs PASS, none FAIL; AC8 PASS; `check_mpi.sh` on 2 and 4 processes (with
check 5) `MPI GATE: PASS`; both fault runs of the consistency check abort with exit 33; plain
runs of D, E on 4 and B on 8 processes at `levdbg = 2` end with the check silent. The acceptance
table above was measured on `ddf46f53`; these gates repeat every criterion it can repeat on the
head.
