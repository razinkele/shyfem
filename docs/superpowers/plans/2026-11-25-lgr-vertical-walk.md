# `ilagr = 3` vertical walk redesign: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One results-changing change to `ilagr = 3`.
- The vertical random walk becomes a no-stop Visser walk with a gradient step rule.
- The bottom layer gets a bed velocity that is linear in z.
- The set-up particle step reads the closure's mixing.

Together these fix #286, #287, #299 and part 1 of #283.

**Architecture:**
- `lagrange_dif.f90` loses the stop-at-interface walk (`lgr_diff_vert`, `diff_get_vert`, Milstein, `rgauss`). In its place:
  - one Visser displacement per call, reflected at the surface and bed;
  - the column structure taken once per particle step;
  - a gradient term in `lag_vdiff_ele`'s step rule.
- `lagrange_vertical.f90` (`track_xi`) gets the bed velocity in the bottom layer.
- `shyfem_subs.f90` moves `call lagrange` after `handle_gotm_init`.
- Two test hooks (`LGR_TEST_KPROF`, `LGR_TEST_NOADV`) and one Python helper make the acceptance runs possible.

**Tech stack:** Fortran 90 (gfortran, OpenMPI build), bash check scripts in `testcases/examples/mar_menor`, Python 3 (standard library only) with the repo's `lgr_compare.py`.

**Spec:** `docs/superpowers/specs/2026-11-25-lgr-vertical-walk-design.md` (approved by the owner on 2026-11-25). Its evidence is in `docs/investigation/2026-11-lgr-walk-redesign/`:
- the reports `reportMwalk.md`, `reportMwalk2.md` and `reportM299.md`;
- the measured hooks `hooks2.diff`;
- the analysis scripts in `py/` and `py299/`;
- the STRs in `str/`;
- the timing scripts in `sh/`;
- every measured number, in `summary_mwalk2.txt`.

## Global Constraints

**Where the work happens:**
- A work tree `/home/razinka/wt-walk`, branch `fix/lgr-vertical-walk`, created from `docs/lgr-walk-design` (it holds the spec, this plan and the evidence) with `git worktree add /home/razinka/wt-walk -b fix/lgr-vertical-walk docs/lgr-walk-design`, run from `/home/razinka/shyfem`.
- Never change `/home/razinka/shyfem`: it is laguna's live production tree.

**SHYFEM conventions (CLAUDE.md):**
- `implicit none` and `intent` on every argument; `allocate(..., stat=ierr)` with a check; `open(newunit=...)`; no GOTO.
- No short-circuit guard: never guard an array read or a division with the other operand of `.and.`/`.or.`; use nested `if`s.
- Nothing may write or abort inside the OpenMP particle loop. Only counters change there (`!$OMP ATOMIC`), and events go through `lgr_event`.

**Build and run:**
- Build: `PATH=/usr/bin:$PATH nice -n 10 make fem NETCDF=true NETCDFDIR=/usr NETCDFFDIR=/usr/local`. Check that `ldd bin/shyfem | grep libmpi.so.40` matches.
- Run with `PATH=/home/razinka/wt-walk/bin:/usr/bin:$PATH`, under `nice -n 10`, after `make init` and `(cd GRID && shypre -noopti MM_geo.grd)` in `testcases/examples/mar_menor`.
- Wait for runs by their exit status, never with a `pgrep`/`sleep` loop.
- Scratch goes only in your own `mktemp -d` under the session scratchpad, with `TMPDIR` set to it.

**Two reference binaries.** Remove both work trees at the end.
- **"main":** origin/main 576abae5, built in a throwaway work tree `/home/razinka/wt-walk-ref`. Used for the RED runs that need no hook and for the unchanged-results battery.
- **"base":** Task 1's commit (the old walk plus the test hooks), built in a throwaway work tree `/home/razinka/wt-walk-base` right after Task 1 is committed. Task 1 step 1 proves it equals main with no hook set. It is the baseline for every run that needs a hook on today's walk, including the cost baseline (Task 7). main ignores the hooks, so it cannot serve there.

**Constants, exactly:**
- the gradient factor f = 0.07 and its floor g_floor = 0.2 s;
- the curvature step and its floor of 2 s, unchanged;
- the #261 cap of `lgr_nvdiff_max` = 10,000 calls, unchanged.

f and g_floor are named parameters in the code, not STR parameters.

**Random draws:** every draw goes through `lgr_random(id, lgr_rnd_vdiff, ndraw)`. The walk draws exactly one uniform per call.

**Commits:** conventional style, with the issue numbers in the subject, files staged by name, and the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Change nothing under `.github/workflows/`. Do not push.

**Results:**
- Only `ilagr = 3` particle results may change.
- These stay byte-identical to main (shown with `cmp` saved to files):
  - `ilagr` 1 and 2;
  - every `.hydro.shy`, `.ts.shy`, `.inf` and `.rst`;
  - `./check_mpi.sh 4`;
  - `./check_lgr_mpi.sh`;
  - `./check_lgr_serial.sh repro`;
  - the serial guard `./check_lgr_serial.sh /home/razinka/wt-walk-ref/bin`.

**Stop and report to the coordinator instead of retuning** if any of these happens:
- the walk-only cost exceeds 2.1x main on either reference case;
- the GOTM top 5 % exceeds 1.06 on any seed;
- a check's χ² does not reproduce the measured values within the tolerance its task states.

## Review Focus

1. **A column with a layer of zero thickness** (a z-level element whose bottom layer has no water). The walk must never divide by `hl(l) = 0`, never place a particle in such a layer, and the step rule must skip it. Pinned by the `vdiff-dt` unit cases (Task 2) and by the walk's layer search (Task 3, step 3).
2. **A one-layer column** (`lmax = 1`, all of `mm_lgr_a`'s elements and the shallow Mar Menor edges). The gradient rule and the reflecting walk apply there too. The old "z = random(0, 1)" rule is gone, so a one-layer column must stay well mixed. Pinned by the `vdiff-dt` lmax = 1 case and by the thin-layer and constant-K modes (Task 3).
3. **A particle that starts exactly on the surface (z = 0, lb = 1) or exactly on the bed (z = 1, lb = lmax).** The fold must give a depth in [0, H], and the layer search must give a layer with z in [0, 1]. Pinned by `walk-fold` (Task 3, step 1).
4. **A particle step longer than 2000 s** (a long `idt`): with the 0.2 s floor binding, it reaches the 10,000-call cap. The cap's existing counting and log line must still apply, without a write in the loop. Pinned in Task 6, step 3: a throwaway build with the cap lowered.
5. **Settling particles at the bed** (`ised = 1`). The bed velocity must not taper the settling speed. Pinned by `check_lgr_bed.sh` part 2 (Task 4) and the `bed-w` unit cases.

---

### Task 1: Test hooks and the RED acceptance runs (#286, #287)

**Files:**
- Modify: `src/shyfem/lagrange_mpi.f90`. Next to `lgr_test_vdiff_end` (about line 269), add the two hook variables. In `lgr_mpi_init` (about lines 441–515, where `LGR_TEST_VDIFF_END` is read), read them.
- Modify: `src/shyfem/lagrange_dif.f90`, `lag_vdiff_ele`: apply `LGR_TEST_KPROF` after `wde(0:lmax,ie)` is computed.
- Modify: `src/shyfem/lagrange_main.f90`, the particle step's `call track_advect(...)` (about line 718): skip it under `LGR_TEST_NOADV`.
- Create: `testcases/examples/mar_menor/lgr_vprof.py`. It holds the relative-depth histogram of a forced run, ported from `docs/investigation/2026-11-lgr-walk-redesign/py299/anaA.py` and `shyhead.py`.
- Modify: `testcases/examples/mar_menor/check_lgr_wellmixed.sh`. It gets a mode argument, `const` (default: today's check, unchanged), `linear`, `parabolic`, `gotm` or `thin`, and its header documents each.

**Interfaces:**
- Produces, in module `mod_lagrange_mpi`:
  - `integer, save :: lgr_test_kprof = 0`: 1 linear, 2 parabolic, 3 constant;
  - `logical, save :: lgr_test_noadv = .false.`
  - Both are read once in `lgr_mpi_init` from `LGR_TEST_KPROF` (integer 1–3; anything else leaves 0) and `LGR_TEST_NOADV` (`1` sets it).
  - When a hook is on, the master writes one line: ` test hook LGR_TEST_KPROF: the vertical diffusivity of the particles is profile N` or ` test hook LGR_TEST_NOADV: particles are not advected`.
- Produces: the KPROF profiles, with s = hle(l)/hle(lmax) over the element's interfaces, applied only when hle(lmax) > 0:
  - 1: `1.e-3 + 2.e-2*s`;
  - 2: `1.e-3 + 8.e-2*s*(1-s)`;
  - 3: `1.e-2`.
- Produces in `lgr_vprof.py`:
  - `read_geom(shy_path) -> dict` with the keys `hlv`, `hev`, `ilhv`;
  - `rel_depths(times, geom) -> list` of per-output lists of `(pid, s, weight_rel)`, with s = depth / column depth in the particle's current column at the output time. Zeta is recovered from the particle records, as in anaA's `zeta_of`;
  - `chi2(values, weights=None, nb=20) -> float`, the effective-count χ² of anaA (unweighted when `weights` is None);
  - `bin_ratio(values, weights, lo, hi) -> float`, the weighted share in [lo, hi) divided by (hi − lo).

- [ ] **Step 1: Check that the hooks are inert.**
  - Build, then run `./check_lgr_fixes.sh ilagr3` and `./check_lgr_serial.sh /home/razinka/wt-walk-ref/bin` with no hook set.
  - Also `cmp` the `lgr_ilagr3` particle file of this build against the reference build's (the same STR, no hook).
  - Expected: both checks PASS and `cmp` exits 0.

- [ ] **Step 2: Write the `linear`, `parabolic` and `gotm` modes.**
  - The case is the full forced `mm_hyd_41`: GOTM, wind, boundaries as in the STR, tilt lines removed, one day.
  - Use the `$lagrg` section `ilagr = 3 nbdymax = 50000 / nbdy = 2000 idtl = 0 idtlgr = '1h' / rwhpar = 0 ipvert = 20 / lgrseed = S`, as `docs/investigation/2026-11-lgr-walk-redesign/str/lgr_wm.str`.
  - Run with `LGR_TEST_NOADV=1`, plus `LGR_TEST_KPROF=1` (linear) or `2` (parabolic), on seeds 1, 2 and 3, with the hydro output hourly so `read_geom` has a header.
  - Each run gets `timeout 7200`, not the 1800 of `const`. B07 on `parabolic` makes about 426 calls per step, about 4.9e9 calls in a day, which is about 1800 s on its own. Run the three seeds in parallel.
  - For each seed, `lgr_vprof.py` computes the unweighted χ² of all active particles at each hourly output from 12:00 to 24:00 and takes the mean.
  - Required: every seed below `CHI2MAX=31`, and 39,960 particles released and active at every output.
  - Print each seed's χ² and the top 5 % ratio `bin_ratio(s, None, 0.0, 0.05)` at 12:00–24:00, mean over the outputs.

- [ ] **Step 3: Write the `thin` mode.**
  - Still water as `const`, with `iturb = 0`, `diftur = 1.e-2` and uniform 0.5 m levels down to at least 74.62 m. Build the `$levels` lines as `py/mkstr.py` does with LEVELS = 0.5.
  - Seed 1. K_eff/K is computed as in `py/anaB.py`:
    - for each pair of hourly outputs, take the particles at least 3σ from the surface and the bed at the start, with σ = √(2KΔt);
    - K_hour = Σdz²/n/(2Δt);
    - K_eff is the mean of the 23 values.
  - Required: |K_eff/K − 1| ≤ 0.1.

- [ ] **Step 4: Show the modes RED on today's walk and reproducing the measurement.**
  - Run all four new modes with this task's build: the old walk plus the hooks.
  - Expected RED:
    - `linear` about 3198 and `parabolic` about 148 (seed 1);
    - `thin` K_eff/K about 0.14 (M286's value for main at 0.5 m and K = 1e-2: 0.142).
  - `gotm` must PASS on main: today's walk measured 17.6 and 20.8 on seeds 1 and 2.
  - Reproduction tolerance: seeds 1 and 2 of `gotm` within 1.0 of 17.6 and 20.8; `thin` within 0.03 of 0.142. Otherwise stop and report: the check does not measure what the measurement measured.
  - Paste the outputs into the task report.

- [ ] **Step 5: Commit**
  ```bash
  git add src/shyfem/lagrange_mpi.f90 src/shyfem/lagrange_dif.f90 src/shyfem/lagrange_main.f90 testcases/examples/mar_menor/lgr_vprof.py testcases/examples/mar_menor/check_lgr_wellmixed.sh
  git commit -m "test(lgr): LGR_TEST_KPROF/NOADV hooks and the smooth-profile, GOTM and thin-layer modes of check_lgr_wellmixed.sh (#286 #287)"
  ```

### Task 2: The gradient step rule (`lag_vdiff_ele`)

**Files:**
- Modify: `src/shyfem/lagrange_data.f90`, module `mod_lagrange`. Add:
  - `real, parameter :: lgr_vdiff_facg = 0.07`;
  - `real, parameter :: lgr_vdiff_dtming = 0.2`;
  - the counters `integer(kind=8), save :: lgr_dtvd_ngrad = 0, lgr_dtvd_nfloor = 0`.
- Modify: `src/shyfem/lagrange_dif.f90`. Add `lgr_vdiff_gradstep` after `lgr_vdiff_curvature`. In `lag_vdiff_ele`, apply it after the curvature step. In `lgr_vdiff_stats`, add one line after the random-walk-time-step line.
- Modify: `testcases/examples/mar_menor/check_lgr_fixes.sh`, mode `vdiff-dt`: part 1 gets the gradient cases; part 2's text names both rules.

**Interfaces:**
- Produces: `subroutine lgr_vdiff_gradstep(lmax,hl,wd,facg,dtg)`.
  - Self-contained (no `use`), like `lgr_vdiff_curvature`, so that `vdiff-dt` can compile it on its own.
  - Arguments: `integer, intent(in) :: lmax`; `real, intent(in) :: hl(lmax)`, `wd(0:lmax)`, `facg`; `real, intent(inout) :: dtg`.
  - For each layer l with hl(l) > 0:
    - dk = (wd(l) − wd(l−1))/hl(l), in double precision;
    - kmin = max(1e-6, min(wd(l−1), wd(l)));
    - if dk ≠ 0, dtg = min(dtg, facg·kmin/dk²).
  - This is exactly `lgr_dbg_dtgrad` bit 1 in `hooks2.diff`.
- Produces in `lag_vdiff_ele`, for every element, including lmax = 1 and an element with a zero-thickness layer:
  - `dtg = time; call lgr_vdiff_gradstep(lmax,hl,wde(0:lmax,ie),lgr_vdiff_facg,dtg)`;
  - then `if( dtg < dtd ) dtd = min(dtd, max(lgr_vdiff_dtming, dtg))`.

  Count `lgr_dtvd_ngrad` when the gradient term lowered dtd, and `lgr_dtvd_nfloor` when it lowered dtd to exactly `lgr_vdiff_dtming`.
- Produces: the log line ` lgr vertical diffusion: random walk time step set by the gradient rule in N element steps, at its floor 0.2 s in M`. It is a new line, so the existing line's format, which the checks grep, is unchanged.

- [ ] **Step 1: Write the failing unit cases in `vdiff-dt` part 1.** Compile `lgr_vdiff_gradstep` cut out of the source, as part 1 does for the curvature routine. Use the same six layers (1, 2, 4, 0.5, 3, 1.5 m), facg = 0.07, starting dtg = 300:
  - **linear K** = 1e-3 + 2e-3·depth: dtg = 0.07·1e-3/(2e-3)² = 17.5 (within 1e-5 relative);
  - **constant K**: dtg stays exactly 300;
  - **a K jump** confined to layer 3 (K = 1e-3 above, 5e-2 below): dtg = 0.07·1e-3/((4.9e-2/4)²) (within 1e-5 relative);
  - **a zero-thickness layer**: layers (1, 2, 0, 3) m with K = 1e-3 + 2e-3·depth at the interfaces (depths 0, 1, 3, 3, 6): dtg = 17.5, with no division by zero (the `-ffpe-trap` build would trap);
  - **lmax = 1**, wd = (1e-3, 2e-3), hl = 2: dtg = 0.07·1e-3/(5e-4)² = 280.

- [ ] **Step 2: Run `./check_lgr_fixes.sh vdiff-dt`.** Expected: FAIL, because the routine does not exist yet (the cut-out step finds nothing).

- [ ] **Step 3: Implement** the routine, its call in `lag_vdiff_ele`, the counters and the log line, as in Interfaces.

- [ ] **Step 4: Run `./check_lgr_fixes.sh vdiff-dt` and `./check_lgr_wellmixed.sh const`.**
  - Expected: both PASS.
  - At constant K the step is still the model step: `min 300.000 mean 300.000 ... below the model step 0`.
  - The new line reports N = 0.

- [ ] **Step 5: Commit**
  ```bash
  git add src/shyfem/lagrange_data.f90 src/shyfem/lagrange_dif.f90 testcases/examples/mar_menor/check_lgr_fixes.sh
  git commit -m "feat(lgr): gradient term in the vertical random walk step, dt <= 0.07 Kmin/K'^2, floor 0.2 s (#286)"
  ```

### Task 3: The no-stop Visser walk (#286, #287)

**Files:**
- Modify: `src/shyfem/lagrange_dif.f90`: `diff_body`, `lgr_diff_vert` (rewritten), `diff_get_vert` (removed, merged into `lgr_diff_vert`), `rgauss` (removed: its only caller is the Milstein branch), and the `lgr_vdiff_stats` comment on draws.
- Modify: `testcases/examples/mar_menor/check_lgr_fixes.sh`: a new mode, `walk-fold`.

**Interfaces:**
- Produces: `subroutine lgr_diff_vert(id,iel,lmax,hl,hle,lb,z,time,ndraw)`.
  - Arguments: `integer, intent(in) :: id, iel, lmax`; `real, intent(in) :: hl(lmax), hle(0:lmax)`; `integer, intent(inout) :: lb, ndraw`; `double precision, intent(inout) :: z`; `real, intent(inout) :: time`.
  - One call makes one displacement over dt = min(dtvd(iel), time) and sets time = time − dt.
- Produces: `subroutine lgr_walk_fold(lmax,hl,hle,d,lb,z)`.
  - Self-contained (no `use`), so that `walk-fold` can compile it alone.
  - Arguments: `integer, intent(in) :: lmax`; `real, intent(in) :: hl(lmax), hle(0:lmax)`; `double precision, intent(in) :: d` (depth after the displacement, any real value); `integer, intent(out) :: lb`; `double precision, intent(out) :: z`.
  - It folds d into [0, H], H = hle(lmax), modulo 2H (d = 0 if H ≤ 0). lb is the first l with d ≤ hle(l) and hl(l) > 0 (lmax if none). z = (d − hle(lb−1))/hl(lb), clamped to [0, 1], or 0.5 when hl(lb) ≤ 0.
  - This is `lgr_diff_vert_last`'s search on `investigate/lgr-vdiff-cap` 97a7ad46.
- Consumes: `dtvd(iel)` from Task 2.

- [ ] **Step 1: Write the failing `walk-fold` unit cases.** Compile `lgr_walk_fold` cut out of the source. Use layers (1, 2, 0, 3) m, so hle = (0, 1, 3, 3, 6), H = 6:
  - d = 2.5 → lb = 2, z = 0.75;
  - d = −0.5 (above the surface) → depth 0.5, lb = 1, z = 0.5;
  - d = 6.5 (below the bed) → depth 5.5, lb = 4, z = 2.5/3;
  - d = 13 → 13 mod 12 = 1, depth 1, lb = 1, z = 1;
  - d = 3 (on the interface above the zero layer) → lb = 2, z = 1, never lb = 3;
  - d = 0 → lb = 1, z = 0; d = 6 → lb = 4, z = 1;
  - H = 0 (every hl = 0) → lb = lmax, z = 0.5, no division.

- [ ] **Step 2: Run `./check_lgr_fixes.sh walk-fold`.** Expected: FAIL (no routine).

- [ ] **Step 3: Implement the walk.**
  - **`diff_body`:** once per particle step, before the loop, call `lagr_layer_thickness(iel,lmax,hl,htot,htotz)` (lmax = nlv on entry) and build hle(0:lmax). Pass both to each `lgr_diff_vert` call. Drop `mode`. Keep the loop, the cap, the counters and the two-zero-time-calls rule with its log line (it cannot fire now, and keeping it keeps the log format the checks read).
  - **`lgr_diff_vert`:**
    - keep the `lb > lmax` guard (`lgr_ev_vd_layer`, `lgr_internal_error`, time = 0);
    - dk = (wde(lb,iel) − wde(lb−1,iel))/hl(lb) if hl(lb) > 0, else 0;
    - dt = min(dtvd(iel), time);
    - zp = hle(lb−1) + z·hl(lb) + 0.5·dk·dt, clamped to [0, hle(lmax)];
    - K = `exxpp(2,lmax+1,hle,wde(0:lmax,iel),zp,iact)`, a negative value counted in `lgr_nvdiff_neg` and set to 0, as today;
    - R = 2·`lgr_random(id,lgr_rnd_vdiff,ndraw)` − 1, then ndraw = ndraw + 1;
    - w = R·√(6K/dt) − dk;
    - d = hle(lb−1) + z·hl(lb) − w·dt;
    - `call lgr_walk_fold(lmax,hl,hle,d,lb,z)`; time = time − dt.
  - **Removed:** the stop at interfaces, the #284 thickness and tv²/dt corrections, the one-layer random z, the Milstein branch, the mode argument, `rgauss`, and `lgr_ev_vd_depth`'s guard in this routine (the fold makes it unreachable).
  - **`lgr_ev_vd_depth`:** keep the event constant in `lagrange_data.f90`, documented as no longer raised.
  - **Comments:** replace the #284 explanations in `diff_body` and `lgr_diff_vert` with the new scheme and its measured numbers, from the spec §4 and §5.2 table. Do not attribute the gradient rule to Visser (1997).

- [ ] **Step 4: Run the walk's checks.**
  - Commands: `./check_lgr_fixes.sh walk-fold`, `./check_lgr_wellmixed.sh const`, `linear`, `parabolic`, `gotm` and `thin`.
  - Expected: all PASS.
  - Reproduction tolerance against B07 in `reportMwalk2.md`: each seed within 1.0 of
    - linear 25.3 / 21.8 / 21.6;
    - parabolic 20.4 / 20.6 / 18.6;
    - GOTM 18.7 / 21.9 / 19.5.
  - If a seed is outside that, stop and report: the production walk does not reproduce the measured one, so the limits do not apply.
  - Report the GOTM top 5 % per seed. If it is above 1.06, stop and report.

- [ ] **Step 5: Commit**
  ```bash
  git add src/shyfem/lagrange_data.f90 src/shyfem/lagrange_dif.f90 testcases/examples/mar_menor/check_lgr_fixes.sh
  git commit -m "fix(lgr): no-stop Visser vertical walk across layer interfaces, reflected at surface and bed (#286 #287)"
  ```

### Task 4: The bed velocity in the bottom layer (#299)

**Files:**
- Modify: `src/shyfem/lagrange_vertical.f90`: `track_xi` (about lines 290–600) and two new self-contained routines.
- Modify: `testcases/examples/mar_menor/check_lgr_fixes.sh`: a new mode, `bed-w`.
- Create: `testcases/examples/mar_menor/check_lgr_bed.sh`.

**Interfaces:**
- Produces two self-contained routines (no `use`):
  - `subroutine lgr_bed_move(wt,sv,hd,z0,t,z1)`, with all arguments `double precision`: the relative depth z1 after time t in the bottom layer of thickness hd, with w(z) = wt·(1 − z) − sv (w > 0 upward, z = 0 at the layer top). Valid while the particle stays inside the layer.
  - `subroutine lgr_bed_exit(wt,sv,hd,z0,texit,bup)`, with `double precision :: wt, sv, hd, z0, texit` and `logical, intent(out) :: bup`: the time to reach the layer top (bup true) or the bed (bup false), and `huge(1.d0)` if neither is ever reached.
  - Closed form, with u = 1 − z: for wt ≠ 0, u(t) = a + (u0 − a)·exp(wt·t/hd) with a = sv/wt; for wt = 0, u(t) = u0 − sv·t/hd.
- Produces in `track_xi`, only when lb = lmax, lmax > 1 and neither `blgrsurf` nor `blgr2d`:
  - wt = the mean over the element's 3 nodes of 0.5·(wlov(lmax−1,k) + wlnv(lmax−1,k)), as in `hooks2.diff`;
  - the particle moves with `lgr_bed_move`/`lgr_bed_exit` in place of the constant w;
  - **sv is not tapered** (spec §5.3);
  - one-layer columns and interior layers keep today's layer-mean w.
- Also in `track_xi`: after the layer switch at its start (`if ( w > 0 .and. z == 0 )` / `if ( w < 0 .and. z == 1 )`), call `track_xi_get_vertical` again for the new lb, so that w and hd belong to the layer the particle is in (M299's minor defect).

- [ ] **Step 1: Write the failing `bed-w` unit cases.** Compile the two routines alone. Compare against an RK4 integration of du/dt = (wt·u − sv)/hd with 10⁵ steps, to 1e-7 absolute:
  - sv = 0, wt = −1e-4, hd = 2, z0 = 0.3, t = 3600 (the measured tapered case);
  - wt = 0, sv = 1e-3: linear; the bed is reached at texit = hd·(1 − z0)/sv exactly;
  - wt = 2e-4, sv = 1e-4: equilibrium at u = 0.5. From z0 = 0.6 (u0 = 0.4 < 0.5) the particle reaches the bed; from z0 = 0.4 it reaches the top;
  - wt = −2e-4, sv = 1e-4: the bed is reached in finite time from any z0;
  - for each exit, `lgr_bed_move(..., texit, z1)` gives z1 = 0 (top) or 1 (bed) within 1e-9.

- [ ] **Step 2: Write `check_lgr_bed.sh` (FAIL on main).**
  - **Part 1, #299:** the closed forced case, `docs/investigation/2026-11-lgr-walk-redesign/str/gc_s1.str` (mm_hyd_41, both boundaries `ibtyp = 0`, wind kept, GOTM, 39,960 particles, one day), seeds 1 and 2.
    - The bottom 5 % at 24:00 is `bin_ratio` over [0.95, 1.0) of `lgr_vprof.rel_depths` with the release-column weight 'rel', anaA's measure.
    - Required: ≥ 0.80 on both seeds.
    - Print it and the χ² 12–24 h.
  - **Part 2, settling (spec §6 test 6, restated as a drift test).**
    - **Why "reach the bed" cannot be tested:** the stock classes settle at 3e-6, 1e-5 and 3e-5 m/s (`lagrange_sedim.f90`). The walk's molecular floor spreads particles by √(2·K_floor·t) with K_floor = 1e-6/3 m²/s, and over the hours a particle needs to reach the bed that spread hides the taper.
    - **The case:** `mm_hyd_41` in still water as `check_lgr_wellmixed.sh const`, but with `diftur = 0.` and `vistur = 1.e-3` (the walk sees only K_floor), plus `ised = 1` (each particle gets a class and its settling speed, field `"s"` of `lgr_compare`). Same uniform release (ipvert = 20), 5 hours, hourly output.
    - **The particles judged:** those of the fastest class (s = 3e-5 m/s) that start in the bottom layer of a column with lmax ≥ 2, and whose distance to the bed, d_b = (1 − z0)·hd, is at least s·t + 4σ at t = 5 h. Here hd is the bottom layer's thickness from `read_geom`, and σ = √(2·K_floor·t).
    - **The statistic:** R = Σ(depth at 5 h − depth at release) / Σ(s·t).
    - **Required:** 0.95 ≤ R ≤ 1.05. Untapered settling gives R ≈ 1.
    - **The script also checks that it can tell the forms apart.** It computes the tapered expectation R_tap = Σ d_b·(1 − exp(−s·t/hd)) / Σ(s·t) and asserts R_tap ≤ 0.85 before judging.
    - It is GREEN on main and RED against the tapered form.
- [ ] **Step 3: Show the checks failing.**
  - Run `./check_lgr_fixes.sh bed-w` (FAIL: no routines yet).
  - Run `./check_lgr_bed.sh` with main. Expected: part 1 FAILS (0.49 / 0.49); part 2 PASSES (main has no taper).
- [ ] **Step 4: Implement the routines and the `track_xi` change.**
- [ ] **Step 5: Show part 2 is RED against the tapered form.** In your build, temporarily taper sv as the prototype did, (wt − sv)·(1 − z). Run part 2: it must FAIL with R near R_tap. Paste that output, then undo the edit by editing the code back (never `git checkout <file>`).

- [ ] **Step 6: Run the checks again.**
  - Commands: `./check_lgr_fixes.sh bed-w`, `./check_lgr_bed.sh`, `./check_lgr_wellmixed.sh const` and `./check_lgr_fixes.sh ilagr3`.
  - Expected: all PASS. Part 1 is near the measured 0.88 / 0.89; it may differ slightly, because the measurement did not have the layer-switch fix.

- [ ] **Step 7: Commit**
  ```bash
  git add src/shyfem/lagrange_vertical.f90 testcases/examples/mar_menor/check_lgr_fixes.sh testcases/examples/mar_menor/check_lgr_bed.sh
  git commit -m "fix(lgr): bottom-layer vertical velocity linear to 0 at the bed, settling not tapered (#299)"
  ```

### Task 5: The set-up particle step after `handle_gotm_init` (#283 part 1)

**Files:**
- Modify: `src/shyfem/shyfem_subs.f90` (about line 491). Move `call lagrange` after `call handle_gotm_init`, with the comment `!after handle_gotm_init: visv/difv final (#283)`, as in 431c5e8d.
- Modify: `testcases/examples/mar_menor/check_setup_order.sh`. Add part 1 from the prototype `203fc8dc:testcases/examples/mar_menor/check_setup_order.sh`:
  - cases p0 and p1: mm_hyd_41 without tilt, `iturb = 1`, one hour, the `$lagrg` section of `check_lgr_fixes.sh ilagr3`;
  - p1 adds `vistur = 1.e-2` and `diftur = 1.e-3`;
  - required: `p0.lgr.shy`, `p0.hydro.shy` and `p0.ts.shy` byte-identical to p1's.

  Today's part 2 stays as it is. Merge the two headers into one.

- [ ] **Step 1: Add part 1** and run `./check_setup_order.sh` with the reference binary. Expected: FAIL in part 1 (the `lgr.shy` files differ, the hydro and ts files do not); part 2 PASSES.
- [ ] **Step 2: Move the call** and confirm by reading that `tidepar_init` and `submud_init` touch nothing in the Lagrangian module.
- [ ] **Step 3: Run `./check_setup_order.sh`.** Expected: PASS for both parts.
- [ ] **Step 4: Commit**
  ```bash
  git add src/shyfem/shyfem_subs.f90 testcases/examples/mar_menor/check_setup_order.sh
  git commit -m "fix(lgr): the set-up particle step runs after handle_gotm_init, with the closure's mixing (#283)"
  ```

### Task 6: Update the existing Lagrangian checks

**Files:**
- Modify: `testcases/examples/mar_menor/check_lgr_fixes.sh`: the header text and limits of the modes `ilagr3`, `vdiff-events` and `vdiff-dt` (part 2).

What changes, by the spec §6 test 7:
- calls per step and the measured numbers in the comments (the reproducer measured 154.8 calls per step);
- the most calls in a step, M: require 100 < M ≤ 1501. The reproducer averages 154.8 calls per step, and ⌈300/0.2⌉ = 1500, plus one call for the single-precision rounding of the time left;
- the cap count N = 0 at T = 300 s;
- E = 0;
- each line is still written exactly once, including in the 12-hour run with `itlend = 06:02:30`.

`vdiff-events` keeps its hook-driven branches. Its comments drop "a call ends ... where the particle reaches an interface".

- [ ] **Step 1: Run the three modes on the branch** before editing. Note which assertions fail, and why each failure is the expected effect of the new walk.
- [ ] **Step 2: Update the assertions and header texts.** Each new limit must come with the measured value it was derived from, in the header.
- [ ] **Step 3: Test the cap path in a throwaway build (not committed).**
  - Build with `lgr_nvdiff_max` = 100 and run the `ilagr3` case: B07 makes up to 1500 calls in a 300 s step, so the cap binds.
  - The run must end. The cap line must report N > 0 steps stopped, with the time not diffused. There must be no `warning particle dif` line, or any other line written from the loop.
  - Paste the output into the task report, then discard the build.
- [ ] **Step 4: Run `./check_lgr_fixes.sh ilagr3`, `vdiff-events`, `vdiff-dt`, `seed`, `sedbeach` and `int-fail`.** Expected: all PASS. `seed`, `sedbeach` and `int-fail` must pass unchanged.
- [ ] **Step 5: Commit**
  ```bash
  git add testcases/examples/mar_menor/check_lgr_fixes.sh
  git commit -m "test(lgr): check_lgr_fixes.sh ilagr3, vdiff-events, vdiff-dt for the no-stop walk (#286 #287)"
  ```

### Task 7: Results battery, cost, CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`: one line under `## [Unreleased]`, Fixed, with a results-change clause: every `ilagr = 3` run changes, older results are reproducible from v8.6.0, and nothing else changes.
- Create: `docs/investigation/2026-11-lgr-walk-redesign/battery.md`, with the `cmp` table and the cost table of this task.

- [ ] **Step 1: Unchanged-results battery** (both binaries, `cmp` saved to files):
  - the serial guard `./check_lgr_serial.sh /home/razinka/wt-walk-ref/bin`;
  - `./check_lgr_serial.sh repro`;
  - `./check_mpi.sh 4`;
  - `./check_lgr_mpi.sh`;
  - the `.hydro.shy`, `.ts.shy` and `.inf` of `lgr_ilagr3` and of the #299 closed case.

  Expected: PASS and `cmp` 0 everywhere. A case with `ilagr = 3` inside these must be named, and is the only allowed difference.

- [ ] **Step 2: Cost** (spec §2 and §6). Sequential runs, median of 3, each at load < 8 (record the load at start and end).
  - **Reproducer:** the `lgr_ilagr3` case of `check_lgr_fixes.sh`.
  - **Heavy case:** `gotm` mode, seed 1 (39,960 particles, no advection).
  - **Runs on each case:**
    - base (today's walk with the hooks; the heavy case needs `LGR_TEST_NOADV`);
    - the branch;
    - the branch with `LGR_TEST_KPROF=3`, the fixed part: one walk call per step.
  - **Walk-only** = (user_branch − user_fixed)/(user_base − user_fixed).
  - Record calls per step from the log for each run.
  - Required: walk-only ≤ 2.1 on both cases. If it is over, stop and report; do not retune.
- [ ] **Step 3: Surface excess:** the GOTM top 5 % on seeds 1–3 from Task 3's run, recorded in `battery.md`. If any is above 1.06, stop and report.
- [ ] **Step 4: Run everything on the final head.** Tasks 4 and 5 change inputs of checks that passed earlier: the set-up move affects `gotm`, and the layer-switch fix affects `const` and `thin`. So run:
  - every acceptance check: `./check_lgr_wellmixed.sh const`, `linear`, `parabolic`, `gotm` and `thin`; `./check_lgr_bed.sh`; `./check_setup_order.sh`;
  - `./check_lgr_fixes.sh ilagr3`, `vdiff-events`, `vdiff-dt`, `walk-fold`, `bed-w`, `seed`, `sedbeach` and `int-fail`;
  - Step 1's battery and Step 2's cost.

  If any code changes after this, run it all again.
- [ ] **Step 5: Commit**
  ```bash
  git add CHANGELOG.md docs/investigation/2026-11-lgr-walk-redesign/battery.md
  git commit -m "docs: CHANGELOG and results/cost record of the ilagr = 3 walk change (#286 #287 #283 #299)"
  ```
