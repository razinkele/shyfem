# Lagrangian particles under MPI: acceptance results (#217)

Measured results of the acceptance criteria in section 8 of
`docs/superpowers/specs/2026-11-21-lagrange-mpi-design.md`. The stage that
meets a criterion adds its section here.

## AC1: side fluxes equal serial in every held element

**Criterion.** `flux3d` and `flux2d` in every held element equal the serial
values: the difference is at most 1e-5 of the array's largest serial
magnitude.

**Measured** 2026-11-21 16:16 EET (from `date`). Source: commit
`ac03c934`. Built with OpenMPI (`libmpi.so.40`).

**Method.** `./check_lgr_mpi.sh CASE NP flux` in
`testcases/examples/mar_menor`. The driver runs the case serially and on NP
processes with `levdbg = 3`, and `lgr_dbg_compare.py flux` compares the debug
dumps written at the first output at or after 10 h. One row is one side
(element, opposite node) on one rank. The rows fall into three classes:

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
| A | 4 | flux3d layer 1 | 7320 / 0 / 9.1e-07 | 315 / 0 / 9.1e-07 | 318 / 0 / 9.1e-07 |
| A | 4 | flux2d | 7320 / 0 / 1.7e-07 | 315 / 0 / 1.3e-07 | 318 / 0 / 1.3e-07 |
| B | 2 | flux3d layer 1 | 7497 / 0 / 8.3e-07 | 138 / 0 / 8.3e-07 | 138 / 0 / 8.3e-07 |
| B | 2 | flux2d | 7497 / 0 / 3.4e-07 | 138 / 0 / 1.7e-07 | 138 / 0 / 1.7e-07 |
| B | 4 | flux3d layer 1 | 7320 / 0 / 9.1e-07 | 315 / 0 / 8.3e-07 | 318 / 0 / 8.3e-07 |
| B | 4 | flux2d | 7320 / 0 / 3.0e-07 | 315 / 0 / 2.3e-07 | 318 / 0 / 2.3e-07 |
| C | 2 | flux3d layer 1 | 7497 / 0 / 8.8e-07 | 138 / 0 / 8.8e-07 | 138 / 0 / 8.8e-07 |
| C | 2 | flux3d bottom layer | 7497 / 0 / 3.8e-07 | 138 / 0 / 2.1e-07 | 138 / 0 / 2.1e-07 |
| C | 2 | flux2d | 7497 / 0 / 2.4e-07 | 138 / 0 / 1.5e-07 | 138 / 0 / 1.5e-07 |
| C | 4 | flux3d layer 1 | 7320 / 0 / 8.8e-07 | 315 / 0 / 8.8e-07 | 318 / 0 / 8.8e-07 |
| C | 4 | flux3d bottom layer | 7320 / 0 / 4.6e-07 | 315 / 0 / 2.5e-07 | 318 / 0 / 2.5e-07 |
| C | 4 | flux2d | 7320 / 0 / 2.3e-07 | 315 / 0 / 2.0e-07 | 318 / 0 / 2.0e-07 |
| A | 3 | flux3d layer 1 | 7452 / 0 / 1.8e-06 | 183 / 0 / 1.8e-06 | 183 / 0 / 1.8e-06 |
| A | 3 | flux2d | 7452 / 0 / 2.2e-07 | 183 / 0 / 8.6e-08 | 183 / 0 / 8.6e-08 |
| A | 6 | flux3d layer 1 | 7143 / 0 / 1.0e-06 | 492 / 0 / 1.0e-06 | 495 / 0 / 1.0e-06 |
| A | 6 | flux2d | 7143 / 0 / 2.2e-07 | 492 / 0 / 1.3e-07 | 495 / 0 / 1.3e-07 |
| A | 8 | flux3d layer 1 | 6996 / 0 / 1.2e-06 | 639 / 0 / 1.3e-06 | 648 / 0 / 1.3e-06 |
| A | 8 | flux2d | 6996 / 0 / 2.2e-07 | 639 / 0 / 1.7e-07 | 648 / 0 / 1.7e-07 |
| C | 3 | flux3d layer 1 | 7452 / 0 / 8.8e-07 | 183 / 0 / 8.8e-07 | 183 / 0 / 8.8e-07 |
| C | 3 | flux3d bottom layer | 7452 / 0 / 3.8e-07 | 183 / 0 / 1.7e-07 | 183 / 0 / 1.7e-07 |
| C | 3 | flux2d | 7452 / 0 / 2.4e-07 | 183 / 0 / 1.8e-07 | 183 / 0 / 1.8e-07 |
| C | 8 | flux3d layer 1 | 6996 / 0 / 9.7e-07 | 639 / 0 / 9.7e-07 | 648 / 0 / 9.7e-07 |
| C | 8 | flux3d bottom layer | 6996 / 0 / 4.2e-07 | 639 / 0 / 4.4e-07 | 648 / 0 / 4.4e-07 |
| C | 8 | flux2d | 6996 / 0 / 2.3e-07 | 639 / 0 / 1.8e-07 | 648 / 0 / 1.8e-07 |

The rows for 3, 6 and 8 processes were added after the fix of task 2.3
(no division by a zero particle count, #217). Case A on 3 and 8 processes and
case C on 3 processes first stopped with SIGFPE at the division by `idbdy` in
`track_body_xi` (a process without a release area); all five of these runs end
and pass after the fix. In these rows the worst mixed value can exceed the
worst all-own value by a little (A on 8 processes: 1.3e-06 against 1.2e-06),
and the largest value is 1.8e-06 (A on 3 processes, flux3d layer 1); all stay
below the 1e-5 limit. The statement below about mixed values not exceeding
all-own values covers the 2 and 4 process runs only.

All six gates of the first table print `LGR GATE: PASS`. In every run, coverage is complete:
every serial row has exactly one main-owner row, and no MPI row is missing
from serial.

Before this stage, the mixed classes were off (rows off out of rows,
flux3d layer 1):

| Case | NP | main owner | elsewhere |
|---|---|---|---|
| A | 2 | 86 / 138 | 129 / 138 |
| A | 4 | 207 / 315 | 305 / 318 |
| B | 2 | 86 / 138 | 130 / 138 |
| B | 4 | 209 / 315 | 308 / 318 |
| C | 4 | 207 / 315 (bottom 205) | 305 / 318 (bottom 297) |

The controller measured these rows on the stage-1 head (`7a819806`) on
2026-11-21.

The differences that remain in the mixed classes are no larger than in the
all-own class. In every run and array of the table, the worst mixed value is
at most the worst all-own value. Over all runs, the worst mixed value is
1.0e-06 and the worst all-own value is 1.0e-06 (both case A on 2 processes,
flux3d layer 1). Their cause was not separated. Two causes are candidates:

- the order of summation: serial adds the node contributions in node order,
  while under MPI each rank adds those of its own nodes and the partial sums
  are then added;
- the small differences of the MPI hydrodynamic solution.

**Other checks**

- **Holders agree bit for bit.** In the 4-process dumps of A, B and C, every
  side held by more than one rank prints the same value on every holder.
  That covers 315 rows; 3 of them are on the element held by three ranks.
- **Case B node arrays.** `lgr_dbg_compare.py node` on 2 and 4 processes:
  `wlnv`, `mfluxv`, `difv`, `wxv` and `wyv` show 0 rows off and a worst
  value of 0, on own and on ghost nodes.
- **Mutation check.** Case A on 4 processes, with the source otherwise
  unchanged:
  - without the call of `lgr_mpi_flux_sum_3d`, flux3d is off in 200 of 315
    main-owner rows and 307 of 318 elsewhere rows (gate FAIL);
  - without the call of `lgr_mpi_flux_sum_2d`, flux2d is off in 200 of 315
    main-owner rows and 307 of 318 elsewhere rows (gate FAIL);
  - with both calls restored, the gate passes.
