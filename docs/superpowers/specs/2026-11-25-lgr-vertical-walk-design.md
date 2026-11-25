# Design: a new vertical random walk for `ilagr = 3` (#286, #287, #283 part 1, #299)

Status: DRAFT, to be checked by a builder and then approved by the owner. The gradient step's constants are the owner's decision of 2026-11-25: setting **B07**, f = 0.07 and a 0.2 s floor, with the walk-only budget **≤ 2.1x** (§2, §5.2). The measurement found no setting that met both the accuracy margin and 2x (reportMwalk2.md).

## 1. Intent

`ilagr = 3` moves particles vertically by advection and by a random walk driven by the vertical diffusivity K. Four open issues show that it puts particles in the wrong place:

- **#287:** the walk spreads particles more slowly than K. K_eff/K is 0.14–0.70 in 0.5–2 m layers, and about 0.76 at the default Mar Menor levels.
- **#286:** where K changes smoothly with depth, an evenly spread release does not stay evenly spread. χ² is 3198 for linear K and 148 for parabolic K; a well-mixed state gives about 19 ± 6.
- **#299:** in a closed basin under a forced flow, the bottom 5 % of the column empties: 0.46 at K ≈ 0 and 0.49 with GOTM after 24 h. The cause is the vertical velocity used for particles in the bottom layer, which is one layer mean, so it stays non-zero right down to the bed.
- **#283, part 1:** the first particle step is made at set-up, before the turbulence closure has set the vertical mixing, so it reads the wrong K.

The owner's decision is to fix all four in **one change**, so that `ilagr = 3` results change only once. Older results stay reproducible from the v8.6.0 tag.

## 2. Goals, non-goals, anti-goals

**Goals.** Each one is gated by a test kept in the repo (section 6).
1. An evenly spread release stays evenly spread for:
   - constant K;
   - linear K;
   - parabolic K;
   - a GOTM profile, with particle advection off.
2. In thin layers the walk spreads at K: K_eff/K ≈ 1 at 0.5, 1 and 2 m.
3. In #299's closed forced case, the bottom 5 % at 24 h comes back toward uniform, comparable to the 0.89 of the bed-velocity fix alone.
4. The set-up particle step reads the closure's mixing.

**Non-goals:**
- the χ² of forced, advected runs as a target;
- #299's residuals R1–R4 (depth-step walls, 3–7 m columns, the mid-depth excess);
- the horizontal walk;
- `ilagr` 1 and 2;
- `ilagr = 3` under MPI, which still stops with a message;
- restarts (#303, #304).

**Anti-goals.** The change fails, even if it works, if:
- the walk's own cost (walk-only) is more than **2.1x** today's walk on either reference case, timed on the production code. The owner said "up to 2x slower is fine" and confirmed that this means the walk's own cost, not the whole run. On 2026-11-25 they accepted up to about 2.1x, because the chosen setting measured 2.06–2.08x on the prototype. The reference cases are the `check_lgr_fixes.sh ilagr3` reproducer and the particle-heavy GOTM case without advection (39,960 particles). The ratio depends on the case: on the #299 forced case it is about 1.5x, and on the parabolic test profile 2.2–3.1x (computed, not timed);
- anything is written or aborted inside the OpenMP particle loop;
- a new gate can pass or fail by seed luck. Seeds are fixed, and limits are set from the measured seed-to-seed spread;
- the old walk is kept as an option (approach B was declined).

## 3. Constraints

- SHYFEM conventions (CLAUDE.md), including:
  - no short-circuit guards;
  - in the particle loop, only counters change (OMP atomic), and events go through `lgr_event`/`lgr_events` (#288, #294).
- Per-particle random streams (#225): every draw goes through `lgr_random(id, lgr_rnd_vdiff, ndraw)`. A step's draws must fit the 2**24 block. The new walk draws one uniform per call, at most ⌈T/floor⌉ calls per step.
- The #261 cap (`lgr_nvdiff_max`, 10,000 calls) and its counters stay as a guard.
- Serial only: `ilagr = 3` stops under MPI.

## 4. Approaches considered

All numbers below are from a build of 97a7ad46 with throwaway debug hooks (reportMwalk.md, reportMwalk2.md), compiled with the live build's flags (`-O2`, NORMAL profile). Its link to main:
- a `cmp` of the reproducer against P8's binary;
- S cells that match M286 on main;
- S on the #299 forced case reproduces M299's main-built run exactly.

| Scheme | Outcome | Why it was dropped |
|---|---|---|
| **S**: today's walk (stops at every layer interface, Milstein) | fails | linear χ² is 65 even with a 5 s step; K_eff 0.14–0.70 |
| **N3**: no stops, Milstein | fails or over budget | fails linear with the gradient rule (30.7 / 33.2 / 36.1); the 2 s cap that rescues it costs 2.84x, because a Milstein call draws about 3.5 random numbers |
| N2 with a fixed 20 s cap | over budget | 2.47x at constant K |
| **N2**: no stops, Visser, gradient step rule with its own floor | **chosen** | passes every no-advection test; K_eff = 1.00–1.02; with the #299 bed fix, bottom 5 % 0.88–0.89 |

How to ship N2 (owner's choice, 2026-11-25):
- **A, replace the walk (chosen).**
- **B, new walk by default with the old walk as a parameter (declined).** It keeps a scheme known to be wrong, plus a parameter, a UI catalog entry and twice the tests.

## 5. The design

### 5.1 The walk: one Visser step across interfaces (`lagrange_dif.f90`)
Each call of `lgr_diff_vert` makes **one** displacement over dt = min(dtvd(ie), time left), with Visser's (1997) scheme:

  z_depth ← z_depth − w·dt,  w = R·√(6·K(z*)/dt) − K′,  z* = z_depth + ½·K′·dt

where:
- R is uniform on [−1, 1], one `lgr_random` draw;
- K(z*) is interpolated between the column's interface values `wde(0:lmax,ie)` (exxpp, as today);
- K′ is the gradient in the layer the particle starts in.

The displacement crosses layer interfaces freely. It is reflected at the surface and at the bed (fold the depth into [0, H] modulo 2H), and then the layer and relative depth are found again. Each call uses exactly dt, so a step takes exactly ⌈T/dtvd⌉ calls.

The same walk runs in every column, including columns with one layer. Today's "z = random(0,1) when a one-layer particle reaches its edge" goes; the measurements ran the no-stop walk that way.

Removed with the stop scheme:
- the stop at an interface (the tv branch);
- the #284 corrections: the thickness of the layer entered, and the stop time tv²/dt;
- the Milstein branch (mode 3) and the mode argument, if nothing else uses them.

The thin-layer bias (#287) came from the stops, so it goes with them.

The prototype is `lgr_diff_vert_last` on `investigate/lgr-vdiff-cap`. It recomputes the layer structure on every call; the production version should take it once per particle step.

### 5.2 The step rule (`lag_vdiff_ele`)
dtvd(ie) = min(T, d_curv, max(g_floor, d_grad)), where:
- **d_curv** = max(2 s, 1/(100·max|K″|)). This is today's rule (#257) with today's 2 s floor, unchanged. A lower curvature floor (0.5 s, setting A2) changed nothing measurable.
- **d_grad** = f·min over layers of K_min,l/K′_l². The condition keeps the drift K′·dt small against the scale K/K′ over which K changes. Visser (1997) states only the curvature condition, so the code comment must not attribute this one to him. It is applied per layer, including in one-layer columns. A layer with K′ = 0 adds no limit, so at constant K the walk takes the model step.
- **f = 0.07 and g_floor = 0.2 s** (setting B07, the owner's choice; see "The constants" below).
- A layer of zero thickness keeps today's rule: the smallest step (2 s).

**At constant K** every candidate setting gives a particle file byte-identical to plain N2 and makes exactly 1 call per step (still water, K = 1e-2, default levels).

**The constants.** Measured on 3 seeds per test (reportMwalk2.md):

| setting | f | g_floor | worst χ² (worst + seed range) linear / parabolic / GOTM | walk-only cost, reproducer / heavy | whole run, reproducer / heavy |
|---|---|---|---|---|---|
| A1 | 0.05 | 0.5 s | 23.4 (24.3) / 20.4 (24.1) / 24.7 (**32.0**) | 1.71x / 1.74x (heavy computed) | 1.47x / — |
| **B07** | 0.07 | 0.2 s | 25.3 (29.0) / 20.6 (22.6) / 21.9 (25.0) | **2.06x / 2.08x** | 1.70x / 2.02x |
| A3 | 0.05 | 0.2 s | 22.4 (24.0) / 20.3 (24.1) / 20.1 (22.8) | 2.45x / 2.50x | 1.95x / — |

- The pick rule was the cheapest setting with every seed < 31, worst + seed range ≤ 31, and walk-only ≤ 2x on both reference cases. No setting meets it.
- B07 passes every test and misses the cost limit by 3–4 %.
- A1 is within cost and misses only the GOTM margin. Its worst seed is 24.7. At 3 seeds the GOTM range runs 2.7–8.1 within a cell, so whether A1 really needs a margin it lacks is unresolved.
- The per-call cost comes from the prototype, which recomputes the column structure on every call (§5.1). The production walk computes it once per particle step, so its cost has to be re-measured in the build.
- **Owner's decision (2026-11-25): B07**, with the walk-only budget raised to about 2.1x if production timing is still over 2x. The walk's own cost is the measure, not the whole run. If production timing exceeds 2.1x on either reference case, the builder stops and reports instead of retuning f or the floor. *(My call.)*

### 5.3 The bed velocity (#299, `lagrange_vertical.f90`)
In the **bottom layer only**, a particle's vertical velocity is linear in z:
- from the element-mean interface velocity at the layer's top;
- to 0 at the bed.

It is integrated exactly over the particle's time in the layer, with `hd` recomputed. This is M299's variant 1, which took the bottom 5 % from 0.46 to 0.89 (K ≈ 0) and from 0.49 to 0.89 (GOTM).

**With the new walk** (B07, the #299 closed forced case, seeds 1 and 2; reportMwalk2.md §D):

| run | bottom 5 % at 24 h | bottom 15 % at 24 h | χ² 12–24 h |
|---|---|---|---|
| today's walk | 0.49 / 0.49 | 0.75 / 0.75 | 221 / 213 |
| today's walk + bed fix | 0.89 / 0.89 | 0.90 / 0.91 | 60.4 / 59.2 |
| new walk alone | 0.48 / 0.49 | 0.76 / 0.75 | 213 / 215 |
| new walk + bed fix | **0.88 / 0.89** | 0.91 / 0.91 | 54.5 / 59.1 |

- The new walk alone does not move the bottom; the bed fix does, with either walk.
- The remaining χ² of 55–59 is #299's residuals R1–R4, a non-goal.
- A1 was not run on this case. Interior layers keep the layer mean: variant 2, linear in every layer, did no better. Also fix the minor defect M299 found: after the layer switch at the start of `track_xi`, the old layer's `w` and `hd` are kept. The prototype is in `d299_throwaway.patch`, written against main 3d3cbc21.

### 5.4 The set-up particle step (#283 part 1, `shyfem_subs.f90`)
Call `lagrange` after `handle_gotm_init`. The prototype is 431c5e8d on `investigate/setup-order`; `tidepar_init` and `submud_init`, which lie in between, touch nothing in the Lagrangian module. With `iturb = 0` nothing changes. With `iturb ≥ 1` the first particle step reads the closure's starting K.

## 6. Tests kept in the repo
Each test must be shown **RED on main** (for the reason the issue gives) and **GREEN on the branch**. Seeds are fixed, and limits come from the measured seed-to-seed spread.

1. **`check_lgr_wellmixed.sh`** (constant K, still water) stays as it is, with limit 31. With no gradient it now takes the model step in one call (min/mean 300 s).
2. **Smooth profiles and GOTM:** new modes of `check_lgr_wellmixed.sh`, through two test hooks read once outside any loop, in the style of `LGR_TEST_VDIFF_END` (#288):
   - `LGR_TEST_KPROF`: 1 for linear K = 1e-3 + 2e-2·s, 2 for parabolic K = 1e-3 + 8e-2·s(1−s), with s = depth/H. These are the formulas the measurements used.
   - `LGR_TEST_NOADV`: particles are not advected.
   - Required: linear and parabolic each below 31 on their fixed seeds. They are RED on main (3198 and 148).
   - **GOTM without advection** is reported and only gated at 31. It is not a RED-on-main test, because today's walk already passes there (17.6 and 20.8). *(My call: it guards against regression; it does not prove the fix.)*
3. **Thin layers (#287):** still water, constant K (`iturb = 0`, `diftur`, kept since #248), uniform 0.5 m levels. K_eff/K from the hourly displacement variance far from the surface and bed must be within **0.1** of 1. The new walk measured 1.00 ± 0.003 (K = 1e-3) and 1.02 ± 0.02 (K = 1e-2) on one seed; main gives 0.14–0.36. At constant K every candidate setting is byte-identical to plain N2, so this test does not depend on the open constants. *(My call: 0.1 is 5x the larger measured ± and far from main.)*
4. **#299 bottom:** the closed forced case (`mm_hyd_41`, both boundaries `ibtyp = 0`, GOTM, 39,960 particles, one day). The bottom 5 % at 24 h must be ≥ **0.80**. The new walk with the bed fix gave 0.88 and 0.89 on 2 seeds; main gives 0.49. *(My call.)*
5. **#283 part 1:** part 1 of the prototype `check_setup_order.sh` (203fc8dc): the first particle step sees the closure's K.
6. **Updated:** `check_lgr_fixes.sh ilagr3`. The calls per step and the cap lines change: there are no stops, so the cap is never reached and the two-zero-time-calls rule cannot fire. The run must still end, write the lines once, and hold valid particles.

**Results that change** (the CHANGELOG line carries a results-change clause): every `ilagr = 3` run. Nothing else may change:
- `ilagr` 1 and 2;
- all hydrodynamics;
- `check_mpi.sh 4`;
- `check_lgr_mpi.sh` (all of whose cases are `ilagr` 1 or 2);
- the repro run.

Show this with both binaries and `cmp`.

**Cost**, reported in the PR:
- calls per step and user CPU on the two reference cases (§2), against main, whole run and walk-only;
- sequential runs, median of 3, at low load;
- the walk-only ratio must be ≤ 2.1x on both reference cases (§2).

The measurement's method is kept in reportMwalk2.md §E: walk-only = (user − fixed part) / (S − fixed part), where the fixed part is the same run at constant K.

**Known residual, recorded and not gated: a surface excess under GOTM.**
- With the new walk, the top of the column holds slightly more particles than uniform on the GOTM case without advection: top 5 % at 1.03–1.06 (top 15 % 1.01–1.05) in every N2 setting.
- Today's walk shows none there (top 15 % 0.98).
- χ² still passes, and the mechanism is not known.
- The PR reports the top 5 % on that case. The excess must not grow beyond 1.06.

*(My call: record and bound it, and do not hold the change for it.)*

## 7. Left to the builder
- Whether to keep the two-zero-time-calls rule (#261) as dead-code protection or drop it. It cannot fire when every call uses exactly dt.
- Whether `rgauss` and the mode argument have other users. Remove them only if not.
- How the production walk gets the column structure once per particle step instead of once per call.
- The exact form of the new log line (the step rule's statistics), in the style of #257.
- The doc comments: replace the #284 explanations in `lgr_diff_vert` with the new scheme and its measured numbers.
