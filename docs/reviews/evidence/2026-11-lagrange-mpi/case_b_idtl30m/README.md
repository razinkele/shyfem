# Case B with a release every 30 minutes: floors (Task 5.2, ruling R2)

A one-off test configuration for the inserted block of the particle file on several processes.
It is not part of the driver's floor table.

## The configuration
`mm_lgr_b.str` is the STR file of the copy. It differs from
`testcases/examples/mar_menor/mm_lgr_b.str` only in `$lagrg`:

| Parameter | Copy | Original |
|---|---|---|
| `idtl` | `'30m'` | `0` |
| `nbdymax` | `100000` | `20000` |

`idtl` belongs in `$lagrg`, where `lagrange` reads it with `convert_time_d('idtl')`. Outside that
block it would be ignored.

The run makes 96 releases of 1,003 particles each, 96,288 in all, with two releases between
outputs (`idtlgr = '1h'`). Releases happen at 00:00, 00:30, 01:00 and so on. The release at the
end time is skipped (`dtrnext == dtend`).

To use it, copy the test folder and replace its `mm_lgr_b.str` with this file. The basin must be
the tracked `GRID/MM_coarse.bas`.

## How the floors were measured
Measured 2026-11-22 09:27 to 09:36 EET (from `date`) by the Task 5.1 implementer, with `g5floors.sh`
(kept here; `bash g5floors.sh SRC_FOLDER mm_lgr_b BIN_DIR`, where SRC_FOLDER is a copy of the test
folder with this `mm_lgr_b.str` in place of the tracked one).

- **Method.** The way of `testcases/examples/mar_menor/measure_lgr_floors.sh` (then kept outside the
  repository as `floors.sh`), on the particle file: one base serial run and six serial runs with
  `dragco` changed by a relative +-1e-5, +-7e-6 and +-4e-6.
- **Binary.** The serial reference build `wt-lgr-ref3` (commit `0fddec90`).
- **Base check.** The base file is byte-identical to the serial file of the stage-5 binary
  (`8113ed74` source).
- **Positions.** Compared with `lgr_compare.py --mode pos --tol 2` and huge floors, which reports
  the beyond count and the largest distance.
- **Times and blocks.** The particles whose `tt` differs, and those in another block (active in
  one run, exited in the other, at some output), were counted from the files as distinct ids.

| Perturbed run | Beyond 2 m at the last output | Largest distance at any output (m) | Particles with a different `tt` | Particles in another block |
|---|---|---|---|---|
| +1e-5 | 1,222 | 6,117.5 | 75 | 4 |
| -1e-5 | 1,258 | 4,543.75 | 64 | 2 |
| +7e-6 | 898 | 1,807.75 | 52 | 1 |
| -7e-6 | 992 | 2,247.5 | 44 | 1 |
| +4e-6 | 577 | 744.75 | 31 | 0 |
| -4e-6 | 636 | 1,593.5 | 26 | 1 |
| **Envelope** | **1,258** | **6,117.5** | **75** | **4** |

## Gate values (envelope rounded up)
`--max-beyond-last 1258 --max-largest 6118 --max-tt-differ 75`

Block membership is not loosened. `pos` still requires the same ids in every block, and `ids`
stays exact (`--same-counts`).

On 4 processes, measured against the serial file:

| Quantity | 4 processes | Gate |
|---|---|---|
| Beyond 2 m at the last output | 202 | 1,258 |
| Largest distance | 499.4 m | 6,118 m |
| Particles with a different `tt` | 4 | 75 |
| Particles in another block | 0 | 0 (exact) |

The commands, in the copy:
```
./check_lgr_mpi.sh mm_lgr_b 4 pos --max-beyond-last 1258 --max-largest 6118 --max-tt-differ 75
./check_lgr_mpi.sh mm_lgr_b 4 ids
```
