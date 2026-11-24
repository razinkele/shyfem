# Evidence of the Lagrangian MPI work (#217)

The inputs, logs and one-off scripts that the acceptance file
(`docs/reviews/2026-11-lagrange-mpi-acceptance.md`), the plan's amendments
(`docs/superpowers/plans/2026-11-21-lagrange-mpi.md`) and the floor table of
`testcases/examples/mar_menor/check_lgr_mpi.sh` rest on. They were made in the
plan's working folder outside the repository and moved here in the final fix
round of the branch (2026-11-22). The two reusable tools went to the test
folder instead:

| Tool | What it does |
|---|---|
| `testcases/examples/mar_menor/measure_lgr_floors.sh BIN_DIR [COMMIT] [BY] [JOBS] [CASES]` | the position floors of the driver's table: a serial run against six serial runs with the wind drag changed by a relative +-1e-5, +-7e-6, +-4e-6 (was `floors.sh`) |
| `testcases/examples/mar_menor/check_lgr_bounds.sh [COMMIT]` | a build with `-fcheck=bounds` in a throwaway work tree and the particle cases run with it, serially and on several processes (the gate for reads outside an array, issue #234; was `bounds_gate.sh`) |

Every script here runs from a checkout: it finds the repository with
`git rev-parse --show-toplevel` (or relative to its own folder), makes its
scratch folders with `mktemp -d` under `${TMPDIR:-/tmp}`, takes the reference
build as an argument, and puts the build of the checkout (`bin/`) first on
`PATH`. Where a script needs the untracked `GRID/MM_geo.bas` it builds it with
`shypre -noopti MM_geo.grd` (the same bytes as the file built by hand). The
logs are kept as they were written: the paths they print are those of the
machine and the session that made them.

## What each file is, and who cites it

| File | What it is | Cited by |
|---|---|---|
| `floors_ref3.log` | the floors of cases A, B, C, E on the serial reference build `wt-lgr-ref3` (commit `0fddec90`), 28 runs, 2026-11-22 04:04 | plan, amendment after Task 3.7; acceptance, "Task 3.7" (position floors); the driver's floor table |
| `floors_w.log` | the floors of case W on the same build (inputs of commit `6b514083`), 2026-11-22 11:20 | acceptance, "Task 6.1"; the driver's floor table |
| `floors_a_rerun.log` | case A again with the moved script, from this repository, 2026-11-22 14:59 (`measure_lgr_floors.sh <wt-lgr-ref3>/bin HEAD key 1 mm_lgr_a`): the same seven runs and numbers as `floors_ref3.log`, and its seven particle files byte-identical to the ones the acceptance used | this README; the final fix report |
| `floors_basin251.log` | the floors of cases A, B, C, E, W measured again for the rebuilt basin (#251), 2026-11-24 13:23: the build of `37f08788` (release 8.6.0) on the inputs of commit `5ebf495b` (35 runs), the `tt` counts of every perturbed run, and a control with the same build on the old tracked basin (inputs of `9147b517`), whose particle files equal those of `floors_ref3.log` and `floors_w.log` | acceptance, "Task 3.7" (re-measured on the rebuilt basin); the driver's floor table |
| `case6/mm_lgr_b_dense200k.str` | the dense copy of case B for spec section 7, case 6 (200,001 particles, `nbdymax = 400000`, `idtlgr = '6h'`) | plan, amendment after Task 3.6; acceptance, "End of stage 3" and "Spec section 7" (case 6) |
| `case_b_idtl30m/` | case B with a release every 30 minutes (Review Focus 2): the STR file, its floors, the floor script `g5floors.sh` and a README | plan, amendment after stage 5; acceptance, "Task 5.1 and 5.2" |
| `d5/` | spec section 7, case 4 (a particle leaving through the open boundary from an element whose main owner is another process): `run_d5.sh` (the whole run from a checkout), `d5_partition.py` (the hand-written partition), `d5_count.py` (the count from the dump), `part_first.grd` and `part_second.grd` (the two partitions as made), `winkv.py` (the replay of `setnod`'s angle sum) and `setnod_first.txt` (the start-up stop of the first partition, the evidence of issue #238) | plan, amendment after stage 6; acceptance, "Task 6.1" and "Spec section 7" (case 4) |
| `t72/` | the final acceptance run (Task 7.2): `t72_ci.sh` (CI's conditions and the mutation check), `t72_acc.sh` (the criteria; arguments: the reference build, the folder of floor particle files), `t72_acc2.sh` (spec section 7, cases 7, 4 and 6), `t72_acc3.sh` (case 7 again and the third serial run of AC5; argument: the folder `t72_acc.sh` printed), `t72_c7run.sh` (case 7, the run of record), `t72_sweep.sh` (the 4-process sweep of all shipped cases), the helpers `t72_extract.py`, `t72_c7find.py`, `t72_c7check.py`, `t72_sweepjoin.py`, `infcmp.py`, case 7's release files `release_case7.txt` and `release_case7b.txt`, the logs of each script (`*.log`), and the sweep's tables (`sweep/`) | acceptance, summary table and "Task 7.2" |
| `ac5_stats.py` | AC5: mean position and spread per release group of case D | acceptance, AC5 row |
| `release_owners.py` | the owners of the release block in a dump (Task 6.1, the split release of case W; called by `t72_acc.sh`) | acceptance, "Task 6.1" |
| `focus5_nbdymax.sh`, `focus5_nbdymax.log` | Review Focus 5 (the global `nbdymax` limit): case B with `nbdymax` 500 and 200 on 4 and 2 processes and serially, and its log | acceptance, row "Focus 5" of the summary table |

## Not kept here, and how to make them again

- The particle files of the floor runs (61 MB, `floors_runs/` of the working
  folder; the six perturbed files and the base file of case A are the envelope
  of AC8): `measure_lgr_floors.sh` writes them again into `lgr_runs/` of its
  scratch folder (file names `CASE.TAG.lgr.shy`). For case A this was checked:
  the seven files of the rerun are byte-identical to the kept ones.
- The run folders of `t72/` (`acc/`, `acc2/`, `acc3/`, `c7run/`: driver and
  model logs, 16 MB in all), the build log of Task 7.2 (256 KB) and the two
  `mm_lgr_a.inf` files of the info-file finding (532 KB each): the scripts
  write them again; the `.inf` files of a build before commit `309226f6`
  (Task 7.3) come from `./check_lgr_mpi.sh mm_lgr_a 4 ids` with that build.

## How to run

From the test folder, with an OpenMPI build of the checkout and
`make init` plus `(cd GRID && shypre -noopti MM_geo.grd)` done (the scripts
that copy the folder build `MM_geo.bas` themselves):

```
cd testcases/examples/mar_menor
./measure_lgr_floors.sh /path/to/reference/bin            # all four cases
./measure_lgr_floors.sh /path/to/reference/bin HEAD key 1 mm_lgr_w
./check_lgr_bounds.sh                                     # bounds-checked build of HEAD
E=../../../docs/reviews/evidence/2026-11-lagrange-mpi
bash $E/focus5_nbdymax.sh 4
bash $E/d5/run_d5.sh
bash $E/t72/t72_acc.sh /path/to/reference/bin /path/to/lgr_runs
```

The other scripts of `t72/` take no arguments unless stated; they use the build of this
checkout (`bin/`) and print the temporary folder they work in:

```
bash $E/t72/t72_ci.sh build          # export of HEAD, CI's build and steps (check_mpi.sh 4)
bash $E/t72/t72_ci.sh /path/to/bin   # the same with a given build, no build step
bash $E/t72/t72_acc2.sh              # spec section 7 cases 7, 4 and 6
bash $E/t72/t72_c7run.sh             # case 7, the run of record
bash $E/t72/t72_sweep.sh             # the 4-process sweep of every shipped STR file (long)
python3 $E/t72/t72_extract.py LOGDIR # the acceptance table's values from t72_acc.sh's logs
python3 $E/d5/winkv.py GRD PARTGRD   # replay of setnod's angle sum for a partition (#238)
```

`t72_acc.sh` runs every gate of the acceptance table (about 20 minutes on the
development machine); `t72_sweep.sh` runs all shipped test cases serially and
on 4 processes and builds a second binary with EUTRO and mercury (about 35
minutes); `t72_sweepjoin.py` compares its tables with the logs of the sweep of
2026-11-21, which are not in the repository.
