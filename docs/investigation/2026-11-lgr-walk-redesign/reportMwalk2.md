## Report M-walk2: constants for the new ilagr = 3 walk (N2 + gradient step), with the #299 bed fix

Everything ran on a debug build of 97a7ad46 plus a throwaway diff, `hooks2.diff`. Build: OpenMPI, `ldd` shows `libmpi.so.40`, NETCDF=true. All runs were serial (1 thread) under `nice -n 10`. Nothing was committed, pushed or opened as a PR.

**Answer: no setting meets both conditions.**
- **B07 comes closest:** f = 0.07, curvature floor 2 s, gradient floor 0.2 s. It passes every test on all 3 seeds. It fails only the cost limit, by 3–6 %: walk-only cost is 2.06x S on the reproducer and 2.08x on the particle-heavy case.
- **The other near miss is A1:** f = 0.05, floors 2 s and 0.5 s. Its cost is 1.71x and 1.74x. It fails only the GOTM margin, by 1.0 χ², and no A1 seed is above 24.7.

### Setup checks
- **Hooks inert:** I ran the reproducer (`check_lgr_fixes.sh ilagr3`, HDFIX=1 TFIX=1 VCAP=10000, none of the new variables set) with my binary and with the frozen `mwalk.FIRs9L/bin/shyfem`.
  - `cmp` of the two particle files exits 0. Both md5s are 9798c1b2a7ff6730a443b9ae186ea025, the value the previous report recorded.
  - The counts are identical: 777,212 steps and 32,976,828 calls.
- **The floor line I edited is also inert:** with N2 + DTCRIT=1 FACV=0.1 DTMIN=0.5 and DTMING unset, my binary matches the frozen one (`cmp` 0), and so does DTMING=0.5. All three runs make 90.44 calls per step, N2-A's number from the previous report.
- **Floor split:** DTMIN is now the curvature floor only. It still sets the zero-thickness-layer step (`bzero`), as today. DTMING is the gradient floor; the rule is `dtd = min(dtd, max(dtming, dtg))`.
- **Variant 1 reproduces M299:** S + variant 1 (`SHYFEM_D299_WLIN=1`, read once in `lgr_dbg_read_env`) gives χ² 60.4, bottom 5 % at 24 h **0.89**, χ² at 24 h 161 on seed 1. These are M299's numbers exactly, and its depth-class split matches line for line. S alone gives 221.1 / 0.49, M299's main-built `gc_s1` exactly.

### Pass rule (written before any χ²; `res/pass_rule.txt`)
- **χ²:** the in-model vprof χ², all columns, mean over hours 12–24. The limit is 31.
- **A cell passes** when every seed is below 31 and worst + spread ≤ 31.
- **Spread used:** max − min of that cell's 3 seeds.
- **Sensitivity only (not used for verdicts):** worst + the pooled seed SD of the test. The pooled SDs are linear 1.17, parabolic 1.77, GOTM 3.13.

### Candidates × tests × seeds (no advection, 39,960 particles)

| setting | f | curvature / gradient floor | linear s1 / s2 / s3 (worst + spread) | parabolic | GOTM, no advection | GOTM top 5 % | calls per step: linear / parabolic / GOTM / reproducer |
|---|---|---|---|---|---|---|---|
| S (carried over from reportMwalk, not re-run) | — | — | 3198 (1 seed) | 148 (1 seed) | 17.6 / 20.8 | — | 2.55 / 76.8 / 43.46* / 42.43* |
| A1 | 0.05 | 2 s / 0.5 s | 22.6 / 22.6 / 23.4 (24.3) pass | 20.4 / 17.6 / 16.6 (24.1) pass | 17.3 / 23.4 / 24.7 (**32.0 FAIL**) | 1.030 / 1.050 / 1.058 | 95.4 / 300.4 / 135.8 / 129.3 |
| A2 | 0.05 | 0.5 s / 0.5 s | same as A1 | same as A1 | 17.4 / 24.5 / 25.5 (**33.5 FAIL**) | 1.029 / 1.051 / 1.060 | 95.4 / 300.4 / 136.9 / 129.8 |
| A3 | 0.05 | 2 s / 0.2 s | 20.8 / 22.4 / 21.4 (24.0) pass | 18.6 / 20.3 / 16.5 (24.1) pass | 17.4 / 19.3 / 20.1 (22.8) pass | 1.018 / 1.040 / 1.038 | 140.6 / 532.6 / 195.5 / 185.5 |
| **B07** | 0.07 | 2 s / 0.2 s | 25.3 / 21.8 / 21.6 (29.0) pass | 20.4 / 20.6 / 18.6 (22.6) pass | 18.7 / 21.9 / 19.5 (25.0) pass | 1.036 / 1.052 / 1.034 | 112.6 / 426.5 / 162.8 / 154.8 |

\* re-measured here. Plain N2 makes 40.93 calls per step on the reproducer and 42.02 on GOTM.

How the grid was run:
- **A3 was triggered** because A1 fails GOTM under the rule.
- **B used A3's floors,** the only passing floor setting from A.
- **f = 0.04 was not run.** I read the trigger as "f = 0.05 at the better floor fails a test", and A3 passed every test. Under the other reading (A1 and A2 fail), f = 0.04 at A3's floors would cost more than A3's 2.45x, so it could not be the pick.
- **Under the pooled-SD reading every cell passes.** That makes A1 a passing setting at about 1.7x. The cheaper f = 0.07 at A1's floors (2 s / 0.5 s) was never run.

What the runs show:
- **A1 and A2 give identical χ² and calls on linear and parabolic.** I did not `cmp` their particle files. This follows from `min(dtd, max(dtming, dtg))`: wherever the curvature step falls below 2 s, the gradient step is already at its floor. On GOTM, 135.76 against 136.93 calls shows DTMIN is still live.
- **This corrects the previous report.** It said most of parabolic's extra calls come from the curvature floor. With the gradient step on, they come from the gradient step and its floor.
- **The lower gradient floor is what fixes GOTM.** A1 → A3, same seeds, gradient floor 0.5 s → 0.2 s: seed 2 23.4 → 19.3, seed 3 24.7 → 20.1.

**C (constant K 1e-2, still water, default levels, seed 1):**
- A1, A2, A3 and B07 each give a particle file byte-identical to N2 (`cmp` 0).
- Each makes 1.0000 calls per step (11,548,440 calls in 11,548,440 steps), with χ² 19.9 / 22.0, the same as N2.

### D: closed forced case (mm_hyd_41, both `ibtyp = 0`, wind kept, GOTM, 39,960 particles, 1 day; anaA release-column weight, as M299)

| run | χ² 12–24 h | χ² at 24 h | bottom 5 % at 24 h | bottom 15 % at 24 h | top 5 % at 24 h | top 5 % 12–24 h | calls per step |
|---|---|---|---|---|---|---|---|
| S s1 / s2 | 221.1 / 213.0 | 450 / 425 | 0.49 / 0.49 | 0.75 / 0.75 | 1.00 / 1.03 | 1.015 / 1.037 | 37.2 |
| S + variant 1 | 60.4 / 59.2 | 161 / 154 | **0.89 / 0.89** | 0.90 / 0.91 | 0.98 / 1.02 | 1.011 / 1.033 | 37.2 |
| B07 alone | 212.7 / 215.1 | 444 / 440 | 0.48 / 0.49 | 0.76 / 0.75 | 1.05 / 1.03 | 1.019 / 1.030 | 101.0 |
| B07 + variant 1 | 54.5 / 59.1 | 156 / 155 | **0.88 / 0.89** | 0.91 / 0.91 | 1.04 / 1.01 | 1.015 / 1.025 | 101.0 |

- **Acceptance is met:** B07 + variant 1 brings the bottom 5 % back to 0.88–0.89, the same as S + variant 1.
- **N2 alone does not move it:** B07 without variant 1 stays at 0.48–0.49, like S.
- **7–20 m columns, bottom 5 % (12–24 h):** B07 0.19 → 0.80 with variant 1; S 0.19 → 0.84.
- **Coverage:** D was run for B07 only. A1 has no D row.

### E: cost (sequential runs, nothing else of mine running, load 0.8–3.2 at every start and end, none discarded)

**Reproducer, median user s of 3:**

| run | S | N2 | A1 | B07 | A3 | S capped 5 s | S capped 2 s | fixed part (N2 at constant K) |
|---|---|---|---|---|---|---|---|---|
| user s | 33.23 | 23.22 | 48.72 | 56.38 | 64.94 | 46.70 | 89.97 | 11.39 |

**Per-call fits from this session:**
- **Joint fit, 21 runs:** fixed 11.58 s, N2 0.3733 µs, S 0.6627 µs per call; rms residual 0.47 s.
- **Fixed-part method:** N2 0.3745 µs, S 0.6623 µs per call.

**Reproducer ratios to S:**

| setting | whole run | walk-only, primary (user − fixed) / (S − fixed) | walk-only by round | walk-only, joint fit |
|---|---|---|---|---|
| A1 | 1.47 | 1.71 | — | 1.72 |
| **B07** | 1.70 | **2.06** | 2.06 / 2.09 / 2.00 | 2.06 |
| A3 | 1.95 | 2.45 | — | 2.46 |

Removing the constant-K run's own walk calls from the fixed part changes these by less than 0.02: A1 1.70, B07 2.05, A3 2.43.

**Particle-heavy (GOTM without advection, 39,960 particles, seed 1, median of 3):**
- **Median user s:** S 348.31 (43.46 calls per step), N2 197.56 (42.02), B07 702.78 (162.79), fixed part 21.00.
- **Whole run:** B07/S 2.02; N2/S 0.57.
- **B07 walk-only:** primary **2.08**, by round 2.12 / 2.06 / 2.09. With the self-call correction it is 2.07. With the N2 and S costs fitted on this case it is 2.09 (N2 0.362 µs, S 0.651 µs per call). With the reproducer costs it is 2.11.
- **Computed from calls × in-situ costs, not timed:** A1 1.74, A3 2.50.

**The 2x line is about 150 N2 calls per step on the reproducer and 156 on the heavy case.** B07 makes 154.8 and 162.8. All methods put B07 over 2.0 on both cases, so the cost condition is not unresolved.

Computed costs outside the pick rule (calls × in-situ costs, not timed):
- **Parabolic:** B07 3.1x, A1 2.2x.
- **D's forced case:** B07 about 1.5x (101 against 37 calls).

### The pick, with the rule applied
- **Condition 1 (every test, every seed, with margin):** only A3 and B07 meet it.
- **Condition 2 (walk-only ≤ 2x on both cases):** only A1 (and A2) meet it.
- **No setting meets both.**
- **Closest, as smallest relative miss among the settings that pass every test:** **B07**. It fails only cost, by 3 % on the reproducer and 4 % on the heavy case.
- **Beside it, A1** fails only the GOTM margin (32.0 against 31, a 3 % miss), at 1.71x / 1.74x.
- A3, B and D exist only because of the margin rule; A1 has no seed above 31.

### What remains uncertain
- **B07's cost miss is small, and the per-call cost comes from the debug prototype.** The prototype (`lgr_diff_vert_last`) recomputes the layer structure on every call. A production N2 call 2–4 % cheaper would bring B07 under 2x. Per-round ratios already reach 2.00 once on the reproducer.
- **The verdicts depend on the margin rule and on 3 seeds.** GOTM seeds scatter by 2.7–8.0 within a cell, and A1's verdict hinges on seed 3. Under the pooled SD, A1 passes, and f = 0.07 at 2 s / 0.5 s is the first unmeasured cell.
- **Parabolic would break 2x** if it were a cost case: B07 3.1x, A1 2.2x, computed.
- **D's χ² of 55–59 with variant 1** is M299's R1–R4 residual. The walk change does not touch it.
- **Comparison base:** S is the debug build's HDFIX + TFIX walk. It equals main where main's no-progress rule never fires; D's S row reproduces M299's main-built run exactly.

**GOTM surface excess and the gradient floor.** At f = 0.05 the top 5 % falls by 0.01–0.02 on every seed when the gradient floor drops from 0.5 s to 0.2 s (A1 1.030–1.058 → A3 1.018–1.040); the curvature floor changes nothing (A1 against A2). In the candidate B07, at the same 0.2 s floor, it is back at 1.034–1.052, so f moves it as much as the floor does and the excess persists.

### Clean-up and kept data
- **Clean-up:**
  - `/home/razinka/wt-mwalk2` is removed and pruned.
  - Live tree `git status --short` shows only `?? docs/water-10-01178-v2.pdf`.
  - No shyfem or batch process of mine is left.
  - No particle, `.shy`, `.ext` or `.inf` file is left, and I made no `partition.*` files.
  - `wt-walkdoc` appeared in `git worktree list` during the session; it is not mine and I did not touch it.
- **Commands I ran in the live tree, beyond `git worktree add/remove/prune`:** read-only `git worktree list`, `git log --oneline`, `git merge-base` and `git diff --stat` between commits.
- **Waiting:** one bounded wait, `timeout 590 tail --pid=<PID of the batch script>`. The harness moved it to the background and it ended at its timeout. Otherwise I waited on notifications.
- **Kept in `/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/mwalk2.VMQJdX` (45 MB):**
  - `hooks2.diff`, 221 lines across 3 files: the criterion hooks, the DTMIN/DTMING split, and variant 1. I checked it equals the tree's `git diff` before removing the tree.
  - `res/summary.txt` (every number above), `res/pass_rule.txt`, `res/tfit.txt`, `res/timing_r.txt`, `res/timing_h.txt`, `res/C_cmp.txt`, `res/inert_cmp.txt`, `res/inert2_cmp.txt`, `res/vbins_gotm.txt`, and D's `res/D_*.json`, `*.anaA.txt` and `split_*.txt`.
  - Scripts: `run.sh`, `job.sh`, `mkjobs.sh`, `b0.sh`–`b4.sh` with their `jobs_b*.txt`, `timing.sh`, `timing2.sh`, `py/` (`cells.py`, `dtab.py`, `tfit.py` and copies of `vsum.py`, `vbins.py`, `vprof.py`), and `py299/` (`anaA.py`, `splitA.py`, `shyhead.py`).
  - `str/` (with `gc_s1.str` and `gc_s2.str`), the frozen binary `bin/shyfem`, and the run logs (large ones gzipped) with their `.vdbg.txt` files.
  - `run.sh` and `job.sh` point at the removed tree for GRID and INPUT, so a re-run needs it rebuilt from 97a7ad46 plus `hooks2.diff`.
