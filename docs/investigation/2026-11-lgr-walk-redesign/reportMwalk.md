# Report M-walk: measurements for the redesign of the ilagr = 3 vertical walk (#286, #287)

Everything ran on a debug build of 97a7ad46 in my throwaway work tree `/home/razinka/wt-mwalk`. I added a small throwaway change that was never committed: step-criterion hooks (below). Build: OpenMPI, `ldd` shows `libmpi.so.40`. All runs were serial (one process, one thread) under `nice -n 10`. Nothing was committed, pushed or opened as a PR.

## Short answer
- **Yes, one change can pass every test inside the owner's 2x budget:** NOSTOP with Visser's scheme (N2), plus a gradient step criterion **dt ≤ f·K_min/K'²** (per layer, applied to one-layer columns too), plus a **0.5 s floor** in place of 2 s.
  - With f = 0.03 (N2-C) it passes with a margin at **1.88x** S's user CPU on the reproducer.
  - With f = 0.1 (N2-A) it passes at **1.12x**, but the linear test is marginal (24.4 / 28.0 / 30.1; the limit is 31).
- **Thin layers (#287):** NOSTOP spreads at K, whatever the layer thickness. K_eff/K is 1.00 ± 0.003 at K = 1e-3 and 1.02 ± 0.02 at 1e-2, against S's 0.14–0.70.
- **No N3 variant and no S variant passes within 2x.**
  - N3 (Milstein) fails linear with the same criterion (30.7 / 33.2 / 36.1). The cap that rescues it (2 s) costs 2.84x, because each N3 call costs about twice an N2 call.
  - S still fails linear (65) and parabolic (32) at a 5 s step.

## Main table
- K_eff/K: still water, uniform layers, KCONST, P8's method (`anaB.py` from M286), one seed.
- χ²: mean over hours 12–24, all columns, no advection; "/" separates seeds.
- Calls and CPU: the `check_lgr_fixes.sh ilagr3` reproducer (GOTM, with advection, 2914 particles). User CPU is the median of 3 sequential runs at load 2–5; each ratio is against S in the same session.
- "Curvature" is today's 1/(100·max|K''|) criterion with its 2 s floor.

| variant (step criterion) | K_eff/K 0.5 / 1 / 2 m, K = 1e-2 | same, K = 1e-3 | χ² linear | χ² parabolic | χ² GOTM, no advection | χ² constant K (still water, 1e-2) | calls per step | user CPU (ratio to S) |
|---|---|---|---|---|---|---|---|---|
| **S** (HDFIX + TFIX, Milstein, curvature, cap 10,000) | 0.142 / **0.259** / 0.406 | **0.360** / 0.533 / 0.699 | 3198 | 148 | 17.6 / 20.8 | 20.3 | 42.4 | 34.6 s (1.00) |
| **N3** (curvature) | 1.022 ± 0.017 (all three) | 0.999 ± 0.002 | 169 | 56.0 | 24.2 / 28.2 | 19.5 | 41.0 | 36.2 s (1.05) |
| **N2** (curvature) | 1.016 ± 0.026 (all three) | 1.000 ± 0.003 | 239 | 21.1 | 29.6 / 39.8 | 19.9 | 40.9 | 24.1 s (0.70) |
| **N2-A**: N2 + f 0.1 + floor 0.5 s | = N2 (identical run at constant K) | = N2 | 24.4 / 28.0 / 30.1 | 19.0 | 18.6 / 25.6 / 22.1 | 19.9 | 90.4 | 38.8 s (1.12) |
| **N2-B**: N2-A + cap 20 s | 0.996 ± 0.014 (0.5 m, 2 m and default levels identical) | 0.999 ± 0.004 (0.5 m) | 21.2 / 20.3 / 22.4 | 18.9 | 17.9 / 26.1 / 22.1 | 20.0 | 91.0 | 38.6 s (1.15), but 2.47x at constant K |
| **N2-C**: N2 + f 0.03 + floor 0.5 s | = N2 | = N2 | 16.6 / 17.3 / 20.3 | 20.8 | 17.8 / 24.8 / 24.8 | 19.9 | 176.9 | 63.3 s (1.88) |
| N2 + f 0.1 + floor 0.2 s | = N2 | = N2 | 23.0 / 27.6 / 29.2 | 21.0 | 15.7 / 22.1 | 19.9 | 131.2 | 50.7 s (1.47) |
| N2 + cap 5 s | not run | not run | 26.9 | 19.9 | 24.4 / **33.2** | — | 66.8 | 31.8 s (0.92) |
| N2 + cap 2 s | 1.007 ± 0.023 (0.5 m) | not run | 20.1 | 19.7 | 26.2 / **31.6** | 18.0 (0.5 m) | 150 | 55.9 s (1.63) |
| N3 + f 0.1 + floor 0.5 s | = N3 | = N3 | **30.7 / 33.2 / 36.1** | 25.8 | 18.8 / 23.3 | 19.5 | 91.6 | 65.5 s (1.90) |
| N3 + cap 2 s | not run | not run | 24.2 | 30.7 (at 5 s) | — | — | 150 | 98.3 s (**2.84**) |

Notes on the table:
- **S's K_eff:** the bold cells were re-measured on this build and equal M286 (main): 0.259 ± 0.006 and 0.360 ± 0.001. The other four are M286's numbers. S at default levels gives 0.762 and χ² 20.3; M286 gave 0.761 and 20.4.
- **NOSTOP at constant K ignores the layers.** Every thickness gives the same numbers, and the hourly K estimates are identical too.
- **The gradient criterion does not bind at constant K (K' = 0).** The N2-A and N2-C constant-K runs log `min 300 mean 300` and 1 call per step, and they are identical to N2.
- **Constant K at 1e-3:** N2 19.8, N3 18.5.

**Calls per step in each test, the candidates against S:**
- linear: S 2.55; N2-A 64.5; N2-B 70.9; N2-C 127.8.
- parabolic: S 76.8; N2-A 243.7; N2-B 245.2; N2-C 324.5.
- GOTM without advection: S 43.5; N2-A 97.0; N2-B 97.7; N2-C 183.9.
- still water at constant K: S 2.46; N2-A and N2-C 1.00; N2-B 15.0.

**Constant-K cost** (still water, default levels, 39,960 particles, user CPU at load 2–5): S 32.5 s; N2-A 17.0 s (0.52x); N2-B 80.3 s (**2.47x**). N2-C makes exactly N2-A's calls there, so it costs about the same (inferred, not timed).

## 1. Thin layers (#287)
- **NOSTOP spreads at K wherever S does not.** Every N2 and N3 cell at 0.5, 1 and 2 m, and at default levels, gives K_eff/K = 1.00–1.02. S gives 0.14–0.70.
- χ² is 18.5–19.9 in every N cell.
- Each N run makes exactly 1 call per step. S makes 1.3–5.0 (M286), and S's thin-layer runs took about 2–3x the user CPU of the N runs (60–78 s against 20–40 s, under load).

## 2. Smooth profiles (no advection; χ² for all columns, with lmax ≥ 5 in brackets; one seed)

| walk step | S linear | N3 linear | N2 linear | S parabolic | N3 parabolic | N2 parabolic |
|---|---|---|---|---|---|---|
| default | 3198 (2067) | 169 (251) | 239 (225) | 148 (193) | 56.0 (40.4) | 21.1 (19.6) |
| at most 60 s | 556 (483) | 118 (115) | 71.0 (39.4) | 112 (145) | 53.5 (37.0) | 19.7 (18.6) |
| at most 20 s | 191 (184) | 54.2 (31.4) | 39.3 (21.9) | 62.6 (83.4) | 48.5 (35.5) | 22.6 (22.3) |
| at most 5 s | 65.1 (65.9) | 36.6 (21.2) | 26.9 (21.8) | 32.0 (38.7) | 30.7 (21.0) | 19.9 (19.8) |
| at most 2 s | — | 24.2 (22.7) | 20.1 (19.2) | — | — | 19.7 (20.5) |

- **P7 confirmed exactly.** My `lgr_dbg_vprof` lines and counts are byte-identical to P7's logs for N3 linear default (169 / 251) and S parabolic default (148 / 193). These two runs also prove my hooks are inert when unset. Other cells equal P7's numbers: N3 linear at 20 and 5 s, N2 linear default, N2 and N3 parabolic default, S linear at 5 s, S on GOTM.
- **How χ² − 19 falls with the step on linear:**
  - S: about 9 per second of step; it would pass only near 1.5 s (extrapolated).
  - N3: about 2.5–3.5 per second; passes at about 3 s.
  - N2: about 1–2 per second; passes below about 8 s.
- **On parabolic:** N2 passes at every step. N3 passes at about 5 s. S needs about 4–5 s (extrapolated).
- **Where the linear residual of N2-A sits** (seed 3, from the particle file; all columns 30.3 against 30.1 in the model):
  - columns 20–50 m deep, 35 % of the particles: χ² 29.9, top 15 % at 1.045;
  - columns over 50 m: top 15 % at 1.077;
  - columns 1.25–4 m: top 5 % at 1.05–1.07.
  - f = 0.1 lets the walk take 0.25·H² s, which is 100–300 s in the 20–50 m columns. f = 0.03 or the 20 s cap removes the residual.

## 3. GOTM without advection (seed 1 / seed 2)
- N3: 24.2 / 28.2 at the default step; 26.4 / 33.4 at most 20 s.
- N2: 29.6 / 39.8 at the default step; 28.2 / 37.2 at most 20 s.
- **N2's GOTM excess is not a step cap problem.** It persists at a 5 s cap (24.4 / 33.2) and a 2 s cap (26.2 / 31.6). It moves only when the floor goes below 2 s:
  - floor 0.5 s alone: 22.3 / 30.9;
  - with the gradient criterion: 18.6 / 25.6 / 22.1;
  - floor 0.2 s: 15.7 / 22.1.
- A surface excess remains in every N2 variant: the top 5 % bin is 1.07–1.09 with the 2 s floor and 1.04–1.06 with the 0.5 s floor.

## 4. Constant K
In still water at K = 1e-2: N2 19.9, N3 19.5, S 20.3; P7 had about 19–22.

## 5. Step criteria (throwaway hook in `lag_vdiff_ele`, per element, applied after the curvature step, including lmax = 1)
- **Visser drift, dt ≤ f·K_min/K'² (bit 1):** the only criterion that makes N2 pass linear, parabolic and GOTM. It needs the floor lowered to 0.5 s for GOTM.
  - On linear: f 0.1 gives N2 26.2, N3 36.7; f 1 gives N2 82.4, N3 308. With f 1, intermediate steps in shallow columns are worse than 300 s, which folds those columns to uniform.
- **√(2·K·dt) ≤ 0.5·h (bit 2):** passes N2 linear at 23.3 (56 calls per step). It adds no calls on the reproducer (41.9 against 41.7 sub-steps), because those elements already sit at the floor.
  - Not run on parabolic or GOTM: untested there, not rejected.
  - In 0.5 m layers at K = 1e-2 it would force about 3.1 s, i.e. about 97 calls per step. That figure is computed, not measured, and NOSTOP needs no such step at constant K.
- **K'·dt ≤ 0.1·h (bit 4):** fails linear (32.8) at 15 calls per step.
- **One hook sets both floors.** The 0.5 s floor applies to the curvature step and the gradient step alike, so their costs are not separated. Most of the parabolic test's extra calls (244 against 77) come from the curvature floor, which that test never needed.

## 6. Cost
Per-call fits on the reproducer:
- N2 ≈ 0.37 µs per call on top of 12.3 s fixed (hydrodynamics and the rest), with a near-linear fit over 8 runs; S ≈ 0.69 µs per call; N3 ≈ 0.75 µs.
- So the 2x budget is about 150 M N2 calls, about 195 per particle step. For N3 it is only about 97 per step.
- **N2 is cheaper per call than S and N3**: it draws one uniform per call, where Milstein draws about 3.5 random numbers.

## Which variant passes everything, and what it costs
- **N2-C** (N2 + K'²·dt ≤ 0.03·K_min + floor 0.5 s): passes all tests with a margin. It costs 1.88x on the reproducer, about 0.5x at constant K, and 4.2x S's calls on parabolic.
- **N2-A** (f 0.1): also passes every cell, but linear is marginal (24.4 / 28.0 / 30.1). It costs 1.12x on the reproducer and 0.52x at constant K.
- **N2-B** (N2-A + 20 s cap): passes with a margin and costs 1.15x on the reproducer, but **2.47x** on constant-K and weak-gradient runs (15 calls against 2.5). It breaks the budget there.

## What remains uncertain
- **GOTM seeds 2 and 3 sit at 22–26 in every N2 variant with the 0.5 s floor.** The surface excess persists (top 5 % 1.04–1.06), and only the 0.2 s floor reaches 22.1. I did not identify the mechanism.
- **Seed scatter:** the smooth-profile grid is one seed per cell, except the candidates on linear (3 seeds). GOTM cells have 2–3 seeds, which scatter by 3–10.
- **Link to main:** checked once against P8's binary `bin/C` (the #261 + #284 code), not against a build of main.
  - With HDFIX TFIX VCAP=10000 the reproducer particle file is identical (`cmp`), and so are the counts: 777,212 steps, 32,976,828 calls, 1 capped step (141.822 s).
  - P8 showed that its later commits change only log lines. Main's later lagrange commits (#288) declare no result change.
- **Costs are from a debug-hook build.**
  - The NOSTOP prototype (`lgr_diff_vert_last`) recomputes the layer structure on every call; a production version may cost a different amount per call.
  - Only two cases were timed, the reproducer and still water at constant K. The parabolic cost is a call count, not timed.
  - Timing round 3 started while one of my other runs was still going (S read 33.7 s against 34.4–34.6 elsewhere).
  - Two of the three constant-K rounds ran at load 40–56 and were discarded; I repeated them at load 2–3.
- **S's thin-layer cells:** four of the six are M286's. S with a step cap in thin layers was not measured.
- **S equals main** only where main's rule of two no-progress calls never fires; the debug build does not have that rule.
- **No advected χ² for any NOSTOP variant.** M286's forced bottom deficit is a separate issue.
- **NOSTOP's K_eff** was measured only at constant K, where it is 1 by construction; K_eff with a K gradient in thin layers was not measured.

## Clean-up and kept data
- `/home/razinka/wt-mwalk` is removed and pruned. `git status` in the live tree shows only the untracked `docs/water-10-01178-v2.pdf`.
- No particle or `.shy` file is left, no background process is left, and I made no `partition.*` files.
- Kept in `/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/mwalk.FIRs9L` (32 MB):
  - `res/summary.txt`: every χ², count, K_eff and timing;
  - `res/*.anaB.txt` and `res/*.json`, `res/timing*.txt`, `res/bydepth_p1_N2_V01f05_s3.txt`;
  - `criterion_hooks.diff`: the throwaway hooks `LGR_DBG_DTCRIT` (bit flags), `FACV`, `FACS`, `FACD` and `DTMIN`;
  - scripts: `run.sh`, `job.sh`, `b*.sh` with their `jobs_*.txt`, `timing*.sh`, and in `py/` `vsum.py`, `vbins.py`, `bydepth.py`, `anaB.py`, `shyhead.py`, `mkstr.py`, `vprof.py`;
  - `str/`, the frozen binary `bin/shyfem`, and the `runs/*` logs, `.vdbg.txt` and timing files. `run.sh` points to the removed work tree for GRID and INPUT, so re-running needs the tree rebuilt from 97a7ad46 plus the diff.
