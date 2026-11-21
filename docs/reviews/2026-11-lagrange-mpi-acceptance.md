# Lagrangian particles under MPI: acceptance results (#217)

Measured results of the acceptance criteria in section 8 of
`docs/superpowers/specs/2026-11-21-lagrange-mpi-design.md`. The stage that
meets a criterion adds its section here.

## AC1: side fluxes equal serial in every held element

**Criterion.** `flux3d` and `flux2d` in every held element equal the serial
values: the difference is at most 1e-5 of the array's largest serial
magnitude.

**Measured** 2026-11-21 16:16 EET (from `date`). Source: the commit that
adds this section, whose parent is `2d9c839b`. Built with OpenMPI
(`libmpi.so.40`).

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

All six gates print `LGR GATE: PASS`. In every run, coverage is complete:
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

The worst values that remain (at most 1.0e-06) match the all-own class and
come from the order of summation. Serial adds the node contributions in node
order. Under MPI each rank adds those of its own nodes, and the partial sums
are then added.

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
