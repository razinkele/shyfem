## Results, cost and surface excess of the `ilagr = 3` walk change (#286, #287, #283 part 1, #299)

This is the record of the plan's Task 7, made on 2026-11-26 on the final head of `fix/lgr-vertical-walk`. It holds the unchanged-results battery (with `cmp`), the cost against the owner's budget, the GOTM surface excess and the final-head verdict of every check. Nothing here is gated by a script; the gates are the checks of section 4.

**Binaries.** All three come from the same `Rules.make` (`COMPILER_PROFILE = NORMAL`, gfortran), with OpenMPI (`ldd` shows `libmpi.so.40`) and `NETCDF=true`:

| name | commit | what it is | md5 of `src/shyfem/shyfem` |
|---|---|---|---|
| main | 576abae5 (origin/main) | the reference for unchanged results | d21672df2c46697211e012010f70c824 |
| base | 945dd856 (Task 1) | the walk before, plus the test hooks: the cost baseline | 2057ba877f1340f010bc5286c460391a |
| head | 1b47eadf | the final head of the branch | b3df61c558ef81e3484f641a8ccf2f67 |

Runs are serial unless stated, with 1 OpenMP thread, under `nice -n 10`.

### 1. Unchanged results: main against the final head, `cmp`

**Method.** Each in-folder check ran once with each binary, from the scripts and STR files of the final head:
- I made two detached work trees of the final head in scratch (`make init`, `shypre -noopti MM_geo.grd`): one ran main, the other the head.
- After each check, every file it had left under `testcases/examples` was moved aside, so the next check started clean.
- Then I ran `cmp` on each file against the other binary's copy. Logs were left out, since they hold dates and paths.

| check | main | head | files compared | `cmp` |
|---|---|---|---|---|
| serial guard `check_lgr_serial.sh /home/razinka/wt-walk-ref/bin` | — (it compares the head with main itself) | `SERIAL GUARD: PASS` | its own `cmp`, each against main and against the head under `mpirun -np 1`: the `.lgr.shy`, `.hydro.shy` and `.inf` of `mm_lgr_a`, `_b`, `_c`, `_e`, `_w` (30); for `mm_lgr`, `.hydro.shy` and `.inf`, and `.lgr.shy` against `mpirun -np 1` only (5); for `mm_lgr_01`, `.hydro.shy` and `.inf` (4) | 39 of 39 "identical" |
| `check_lgr_serial.sh repro` | `REPRO: PASS` | `REPRO: PASS` | 19: the `.lgr.shy`, `.hydro.shy` and `.inf` of a, b, c, e, w and `mm_lgr`, plus `mm_lgr_b.ext` | 19 × 0 |
| `check_mpi.sh 4` | `MPI GATE: PASS` | `MPI GATE: PASS` | 34: `mm_hyd_01` (`.hydro.shy`, `.ext`, `.inf` of the run the check leaves, and `mm_hyd_01.serial.inf`); `mm_lgr_w` serial and on 4 processes (`.lgr.shy`, `.hydro.shy`, `.inf`, 15 debug dumps); `mm_rst_write.rst`; `mm_rst_write.inf`; `mm_rst_read.inf`; the partitions and `restart_strip/strip.bas` | 34 × 0 |
| `check_lgr_mpi.sh CASE 4 pos`, with CASE = `mm_lgr_a`, `_b`, `_c`, `_e`, `_w`, `mm_lgr` | 6 × `LGR GATE: PASS` | 6 × `LGR GATE: PASS` | 55: serial and 4-process particle, hydro and info files | 55 × 0 |
| `check_lgr_mpi.sh CASE 4 floor`, same 6 cases | 6 × `LGR GATE: PASS` | 6 × `LGR GATE: PASS` | 150: the serial and 4-process debug dumps and the partitions | 150 × 0 |
| `check_lgr_mpi.sh mm_lgr_a 4 stops` | `LGR GATE: PASS` | `LGR GATE: PASS` | 3 (partitions) | 3 × 0 |

In all, the in-folder checks left 261 files, and all 261 give `cmp` 0. Among them are 65 `.shy`, 36 `.inf`, 4 `.ext`, 1 `.rst` and 124 debug dumps.

**My own runs of the `ilagr = 3` cases** (the checks delete their scratch on PASS):

| case | files | `cmp` main vs head |
|---|---|---|
| `lgr_ilagr3` (the STR of `check_lgr_fixes.sh ilagr3`) | `.hydro.shy`, `.ts.shy`, `.inf`, `.ext`, `.fvl.shy` | 0 (all five) |
| | `.lgr.shy` | **differs** (main md5 9798c1b2a7ff6730a443b9ae186ea025, the value of every earlier report; head d33501bb9ef5c4a140ac14f3c34e4a0b) |
| `c_s1`, the #299 closed case (the STR of `check_lgr_bed.sh` part 1, `lgrseed = 1`) | `.hydro.shy`, `.ts.shy`, `.inf`, `.ext`, `.fvl.shy` | 0 (all five) |
| | `.lgr.shy` | **differs** (main 11b1d8f3ea269f70a1e69f0b5dba51bf, head 1f34182afd3b2999e18bf3f83a79c067) |
| `mm_lgr_a` with `ilagr = 3` (2D, one layer; the STR edit of the `ilagr3` row of `stops`), serial | `.hydro.shy`, `.inf` | 0 |
| | `.lgr.shy` | **differs**, only in `z` and `hl` (13920 records); x, y, element, layer, type and time are identical in every record |

**The `ilagr = 3` cases inside the battery.** Only one exists: the `ilagr3` row of `check_lgr_mpi.sh mm_lgr_a 4 stops`.
- On both binaries its 4-process run exits with 33 and the message `Lagrangian option ilagr = 3 is not supported with MPI`, and its serial run ends with exit code 0.
- The row leaves no particle file. My own 2D run above compares that serial case.
- Every other battery case has `ilagr` 1 (`mm_lgr_a`, `_b`, `_e`, `_w`, `mm_lgr`, `mm_lgr_01`) or 2 (`mm_lgr_c`).

In a mesh of one layer, `ilagr = 3` runs the walk as well (`blgr2d` means `ilagr = 2`, not a 2D mesh). There the walk before put a particle that reached the surface or the bed at a random depth, and the walk of #286 reflects it. So a 2D `ilagr = 3` run changes only the particles' depth in the column.

The particle files of `ilagr = 3` runs are the only files that change.

### 2. Cost (spec §2 and §6; the method of reportMwalk2.md §E)

**How the runs were made.**
- Runs were sequential, with nothing else of mine running.
- Each run had its own folder, linked to `GRID` and `INPUT`, and ran with `OMP_NUM_THREADS=1`, `nice -n 10` and stdin from `/dev/null`.
- Each run set or unset the hooks explicitly, and every log was checked for the hook acknowledgements: none for the reproducer on base and head, 1 for the reproducer fixed run and for base and head on the heavy case, and 2 for the heavy fixed run.
- The user time was measured with `/usr/bin/time`. The 1-minute load was recorded at the start and the end of each run: all were between 0.40 and 1.20, so no run was discarded.
- The variants were interleaved within each round: base, head, fixed.

**Variants and cases.**
- **base:** the walk before, with the hooks.
- **head:** the walk of #286.
- **fixed:** the head with `LGR_TEST_KPROF=3`, a constant K = 1e-2, so one walk call per particle step. It is the part of the run that is not the walk.
- **Reproducer:** the `lgr_ilagr3` STR of `check_lgr_fixes.sh ilagr3`, identical to `str/lgr_ilagr3.str` of this folder.
- **Heavy case:** the `gotm` mode's STR of `check_lgr_wellmixed.sh`, seed 1, with 39,960 particles. It differs from `str/lgr_wm.str` only in its run name, `idtout = '1h'` and its `lgrseed = 1` line. All three variants ran it with `LGR_TEST_NOADV=1`.

**How the ratios are computed.**
- walk-only = (user_head − user_fixed) / (user_base − user_fixed)
- whole run = user_head / user_base

The verdict uses the medians.

| case | variant | user s, rounds 1 / 2 / 3 | median | load start–end per round | calls per particle step (calls / steps) |
|---|---|---|---|---|---|
| reproducer | base | 32.18 / 32.25 / 32.27 | **32.25** | 0.40–0.73; 1.04–1.02; 1.01–1.00 | 42.43 (32,976,828 / 777,212) |
| | head | 30.99 / 31.10 / 31.15 | **31.10** | 0.73–0.95; 1.02–1.01; 1.00–1.08 | 154.89 (119,714,348 / 772,898) |
| | fixed | 11.31 / 11.37 / 11.37 | **11.37** | 0.95–1.04; 1.01–1.01; 1.08–1.07 | 1.00 (809,171 / 809,171) |
| heavy | base | 332.91 / 334.09 / 333.40 | **333.40** | 1.07–1.11; 1.15–1.17; 1.03–1.09 | 43.46 (501,843,135 / 11,548,440) |
| | head | 327.49 / 327.91 / 326.84 | **327.49** | 1.11–1.20; 1.17–1.04; 1.09–1.00 | 162.79 (1,879,989,260 / 11,548,440) |
| | fixed | 19.23 / 19.25 / 19.14 | **19.23** | 1.20–1.15; 1.04–1.03; 1.00–1.00 | 1.00 (11,548,440 / 11,548,440) |

| case | **walk-only** (medians) | walk-only by round | whole run (medians) | whole run by round | required |
|---|---|---|---|---|---|
| reproducer | **0.945** | 0.943 / 0.945 / 0.946 | 0.964 | 0.963 / 0.964 / 0.965 | walk-only ≤ 2.1 |
| heavy | **0.981** | 0.983 / 0.980 / 0.979 | 0.982 | 0.984 / 0.982 / 0.980 | walk-only ≤ 2.1 |

**Verdict: walk-only 0.94x and 0.98x, within the 2.1x budget on both reference cases.**

**Why the cost is lower than the prototype's.** The walk makes 3.6x (reproducer) and 3.7x (heavy) the calls of the walk before, but a call costs about a quarter as much:
- head: 0.165 µs per call above the fixed part on the reproducer, 0.164 µs on the heavy case;
- base: 0.633 µs and 0.626 µs.

This is far below the prototype, which measured walk-only 2.06x and 2.08x at the same calls per step (154.8 and 162.8) on a debug build of 97a7ad46. There:
- the walk before cost 0.66 µs per call (here 0.63);
- the prototype's no-stop walk cost 0.37 µs, because it recomputed the layer structure at every call.

The production walk takes the layers of the element once per particle step (`diff_body`) and draws one uniform number per call. The Milstein walk before drew a gaussian, about 3.5 uniform draws per call, and took the layers at every call.

The calls per step equal the prototype's (B07: 154.8 and 162.8), and the base counts equal the walk before (777,212 steps and 32,976,828 calls on the reproducer, as reportMwalk2.md records). So the same work is timed.

### 3. Surface excess under GOTM (spec §6; not a test in the repo)

The source is the final-head `./check_lgr_wellmixed.sh gotm` run of section 4: forced `mm_hyd_41`, particles not advected, 39,960 particles. The quantity is the top 5 % of the column against uniform, mean over 12:00 … 24:00:

| seed | top 5 % | χ² (12–24 h mean) | one-layer χ² (1400 particles, not gated) |
|---|---|---|---|
| 1 | **1.036** | 18.5 | 18.2 |
| 2 | **1.052** | 21.8 | 21.0 |
| 3 | **1.034** | 19.4 | 19.4 |

All three seeds are at or below the stop at 1.06. The prototype (B07) measured 1.036 / 1.052 / 1.034 and the walk before 0.981 (seed 1).

The χ² values differ from the check header's 18.8 / 22.0 / 19.6 (Task 3) by 0.3 / 0.2 / 0.2. They remain within 0.2 of the prototype's 18.7 / 21.9 / 19.5, inside the tolerance of 1.0. The header predates Task 5's move of the set-up particle step after `handle_gotm_init` (f66edaab), which changes a GOTM run's first particle step. `linear`, `parabolic` and `const`, whose diffusivity the step does not read from the closure, reproduce their header values exactly. The top 5 % did not move.

### 4. Final-head checks (verdict lines, verbatim)

The checks ran from `/home/razinka/wt-walk` on the head binary, with `TMPDIR` in scratch:

| check | verdict line | numbers on the final head |
|---|---|---|
| `./check_lgr_wellmixed.sh const` | `WELLMIXED: PASS` | χ² 19.9 / 19.5; one call per step |
| `./check_lgr_wellmixed.sh linear` | `WELLMIXED linear: PASS` | χ² 25.4 / 22.0 / 21.7; 112.6 calls per step; step rule N 650603, floor 23575 |
| `./check_lgr_wellmixed.sh parabolic` | `WELLMIXED parabolic: PASS` | χ² 20.3 / 20.5 / 18.6; 426.5 calls per step; N 700536, floor 65889 |
| `./check_lgr_wellmixed.sh gotm` | `WELLMIXED gotm: PASS` | χ² 18.5 / 21.8 / 19.4; top 5 % 1.036 / 1.052 / 1.034; 162.8 calls per step; N 528007, floor 35052 |
| `./check_lgr_wellmixed.sh thin` | `WELLMIXED thin: PASS` | K_eff/K 1.016 ± 0.026; 149 levels |
| `./check_lgr_bed.sh` | `BED: PASS` | part 1: bottom 5 % at 24:00 0.884 / 0.882 (limit 0.80), χ² 54.0 / 59.7; part 2: R = 0.988, R_tap 0.586, 1067 judged; part 3: 0 exited, 0 lost |
| `./check_setup_order.sh` | `SETUP ORDER: PASS` | parts 1 and 2 |
| `./check_lgr_fixes.sh ilagr3` | `ilagr3: PASS` | 119,714,348 calls in 772,898 particle steps (154.9 per step), most 1501, 0 at the cap, 0 ended by two zero-time calls, 0 negative diffusivities, 0 lines `warning particle dif`; walk step min 0.2 s, mean 14.11 s |
| `./check_lgr_fixes.sh vdiff-events` | `vdiff-events: PASS` | summary lines and particle file of 4 threads identical to 1 thread |
| `./check_lgr_fixes.sh vdiff-dt` | `vdiff-dt: PASS` | |
| `./check_lgr_fixes.sh walk-fold` | `walk-fold: PASS` | failed checks 0; sweep of 2001 depths, wrong 0 |
| `./check_lgr_fixes.sh bed-w` | `bed-w: PASS` | |
| `./check_lgr_fixes.sh seed` | `seed: PASS` | |
| `./check_lgr_fixes.sh sedbeach` | `sedbeach: PASS` | |
| `./check_lgr_fixes.sh int-fail` | `int-fail: PASS` | |

The 15 checks above ran after the cost runs, on the same binary (md5 b3df61c5…). No code changed after them. The χ² of every seed of `linear`, `parabolic` and `gotm` is within 0.2 of the prototype's measured value; the reproduction tolerance is 1.0.

Part 1 of `check_lgr_bed.sh` gives 0.884 / 0.882 for the bottom 5 % and χ² 54.0 / 59.7. Its header was measured before Task 5's set-up move (f66edaab) and gives 0.881 / 0.885 and 54.5 / 59.1. The case uses GOTM, which that move affects.
