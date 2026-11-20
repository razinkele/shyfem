# k-epsilon flux wall conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SHYFEM k-epsilon's Dirichlet wall values with GOTM-style flux (Neumann) wall conditions, so `iturb=2` reaches GOTM parity in the `channel_turb` benchmark (issue #125).

**Architecture:** `keps` (`src/shyfem/kepsilon.f90`) solves k and eps on the interior interfaces only; the interface next to each wall gets zero k flux and the log-law eps flux at the wall-layer centre with a roughness length, then the wall values are filled for output. `keps_shell` (`src/shyfem/turbulence.f90`) supplies `z0s`/`z0b` through a roughness helper shared with `gotm_shell`.

**Tech Stack:** Fortran 90 (gfortran, OpenMPI build), Python 3 + numpy for the benchmark scripts.

**Spec:** `docs/superpowers/specs/2026-11-20-keps-flux-wall-bc-design.md` (approved 2026-11-20). Read it before any task.

## Global Constraints

- Work in `/home/razinka/wt-keps` (branch `feat/keps-flux-wall-bc`); never edit `/home/razinka/shyfem` (the live tree).
- Build with OpenMPI: `PATH=/usr/bin:$PATH make fem PARTS=METIS METISDIR=/usr`; then `ldd src/shyfem/shyfem | grep mpi` must show `libmpi.so.40`.
- Run models with `PATH=/home/razinka/wt-keps/bin:/usr/bin:$PATH`.
- SHYFEM conventions (`CLAUDE.md`): `implicit none`, `intent` on every argument, `use mod_physical_constants` (kappa is `vonkarman_sp`), no GOTO, no bare `stop`, no new `save`/module state in `keps` (it is called per node).
- Constants stay: `cmu0 = 0.5562`, `cmu03 = cmu0**3`, `sigmae`, `sigmak`, `ceps*` as already in `kepsilon.f90`.
- Pass mark (owner): GOTM parity at 20 and 40 layers — near-bed `nut(zb<0.2H)/ana` in about 0.8-1.1, full-depth `mean/logwake` within about 10% of 1.
- Stop rule (owner): if a `keps_20`/`keps_40` channel run is not steady (`drift` >= 0.02), STOP after Task 3 and report; do not start Tasks 4-5.
- Every non-`iturb=2` run and every GOTM run must be byte-identical to the baseline.
- Scratch directory for baselines: `S=/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/keps`.

## Review Focus

1. **Mixed column depths** (Venice: 1-2 layer nodes beside deep ones) — shallow columns take the unchanged Dirichlet path, deep ones the flux path, no crash. Pinned in Task 4 (shallow-node `visv` unchanged vs baseline).
2. **k at the floor** (start from rest, `k(1)` near `kmin`) — the eps flux is tiny but eps stays positive and finite; no NaN anywhere. Pinned in Task 3 (`finite` check on `visv`).
3. **Strong wind** (Venice, `u*` above the Charnock threshold) — `z0s` from the model's wind stress stays positive and bounded. Pinned in Task 4 (Venice run plus a one-off `z0s` range print removed before commit).
4. **MPI** — the roughness helper and `keps` use node-local values only; a 4-rank run completes and its k-eps/GOTM ratio is close to the 1-rank one. Pinned in Task 4.
5. **Thin wall layer** (shallow, drying cells: small `dh`) — `zi + z0` small makes the flux large; the eps limiter must still hold it. Pinned in Task 4 (Venice smoke completes, no NaN).

---

### Task 1: Baseline (no code change)

**Files:**
- Create: `testcases/examples/venice_lagoon/visv_ratio.py`

**Interfaces:**
- Produces: `visv_ratio.py <keps.dbg> <gotm.dbg>` printing three medians over wet nodes of the last record: `top` (interface 1), `bottom` (the deepest interior interface with nonzero `visv` in both runs), `column` (mean over the node's interior interfaces), each as keps/gotm; plus the same three numbers restricted to nodes with at most 2 layers (`shallow`). Reuse `read_dbg()` by copying it from `testcases/examples/channel_turb/analyse.py` (do not import across directories).

- [ ] **Step 1: Build main's code in the worktree with OpenMPI** and check `ldd ... | grep mpi` -> `libmpi.so.40`.
- [ ] **Step 2: Channel baseline:** `cd testcases/examples/channel_turb && bash run_all.sh > $S/baseline_channel.txt`. Expected: `keps_20` and `keps_40` near-bed about 1.51/1.52, `drift` small (steady).
- [ ] **Step 3: Venice baseline:** in `testcases/examples/venice_lagoon`, run `shyfem -debout venlag_smoke.str` and `shyfem -debout venlag_keps_smoke.str`; copy the two `.dbg` files to `$S/base_gotm.dbg`, `$S/base_keps.dbg`.
- [ ] **Step 4: Write `visv_ratio.py`** and run it on the baseline pair; save to `$S/baseline_venice.txt`. Expected: `column` ratio near 2 (2026-10-18 report).
- [ ] **Step 5: Battery baseline:** run the `fortran-ci.yml` serial battery commands (mar_menor `make init`, the `mm_hyd_00`/beach/assim/restart-cycle loop, `mm_hyd_41_6h`, `venlag_smoke`) plus `mar_menor/mm_rst_keps_write.str`; write `md5sum` of every output file they produce (not the `.out` logs) to `$S/baseline_md5.txt`.
- [ ] **Step 6: Commit** `visv_ratio.py` (`test(keps): Venice k-eps/GOTM visv ratio script (#125)`).

### Task 2: Shared roughness helper (GOTM byte-identical)

**Files:**
- Modify: `src/shyfem/turbulence.f90` (`gotm_shell` z0 block, about lines 488-515)

**Interfaces:**
- Produces: `subroutine turb_wall_roughness(k, u_taus, z0nk, z0s, z0b)` in `turbulence.f90`: `integer, intent(in) :: k`; `double precision, intent(in) :: u_taus` (surface friction velocity from the model's wind stress, `sqrt(sqrt(tauxnv(k)**2 + tauynv(k)**2))`); `real, intent(in) :: z0nk` (nodal bed roughness from `model_bottom_z0`, read only when `ireib == 6`); `double precision, intent(out) :: z0s, z0b`. Body = exactly `gotm_shell`'s current logic (`z0sk`/Charnock with `charnock_val`, `max(z0smin)`; `z0bk`, `ireib == 6` -> `z0nk`, `max(z0bmin)`).

- [ ] **Step 1: Move the z0 block of `gotm_shell` into `turb_wall_roughness`** and call it from `gotm_shell`.
- [ ] **Step 2: Build; rerun the GOTM channel runs and `venlag_smoke`.** Expected: `gotm_*` rows of `analyse.py` identical to `$S/baseline_channel.txt`; `venlag_smoke` outputs' md5 identical to `$S/baseline_md5.txt`.
- [ ] **Step 3: Commit** (`refactor(turb): share the wall roughness lengths between gotm_shell and keps (#125)`).

### Task 3: Flux wall conditions in `keps` (the gate)

**Files:**
- Modify: `src/shyfem/kepsilon.f90` (`keps` boundary rows and solves, about lines 505-575; `keps_compile_test`)
- Modify: `src/shyfem/turbulence.f90` (`keps_shell`: compute `u_taus`, `z0n` once per call when `ireib == 6`, call `turb_wall_roughness` per node, pass `real(z0s)`, `real(z0b)`)

**Interfaces:**
- Consumes: `turb_wall_roughness` (Task 2).
- Produces: `subroutine keps(lmax,dt,rho0,taus,taub,dh,u,v,rho,rkm,rkt,k,eps,z0s,z0b)` with `real, intent(in) :: z0s, z0b` (metres). `keps_compile_test` updated to the new argument list.

- [ ] **Step 1: Write the failing check:** add to `testcases/examples/channel_turb/analyse.py` a final line per `keps_*` run: `GATE keps_NN near=<x> logwake=<y> drift=<d> finite=<True|False>` and exit status 1 unless `0.8 <= near <= 1.1`, `abs(logwake-1) <= 0.10`, `drift < 0.02`, `finite` (all `visv` finite) for both `keps_20` and `keps_40`.
- [ ] **Step 2: Run it on the current code.** Expected: FAIL (`near=1.51`, `near=1.52`).
- [ ] **Step 3: Implement the flux rows** for `lmax >= 3` exactly as spec section 1: unknowns `1..lmax-1`; row 1 drops `aux*rke(1)*dzk(1)` from `bb(1)`, `aa(1)=0`, `rr(1) += aux*F_s`; row `lmax1` drops `aux*rke(lmax)*dzk(lmax)` from `bb(lmax1)`, `cc(lmax1)=0`, `rr(lmax1) += aux*F_b`; `F_s = cmu0**4*k(1)**2/(sigmae*(0.5*dh(1)+z0s))`, `F_b = cmu0**4*k(lmax1)**2/(sigmae*(0.5*dh(lmax)+z0b))` using k **before** the k solve (previous step); k rows: same link drops with `rkk`, no source; solve with `tridagd(aa(1),bb(1),cc(1),rr(1),x(1),gam1(1),gam(1),lmax1)`. Note `dzk` already holds `1/dh` at this point; `F_*` use `dh` (the argument), not `dzk`.
- [ ] **Step 4: Fill the wall values** after the solves (spec section 2): `k(0)=k(1)`, `k(lmax)=k(lmax1)`, `eps(0)=cmu03*k(0)**1.5/(karman*z0s)`, `eps(lmax)=cmu03*k(lmax)**1.5/(karman*z0b)`; the existing limiter loop over `0..lmax` is untouched.
- [ ] **Step 5: Keep `lmax <= 2` on the old path:** wrap today's Dirichlet rows and full `0..lmax` solves in `if( lmax <= 2 )` without changing a character of them.
- [ ] **Step 6: Wire `keps_shell`** (spec section 3) and update `keps_compile_test`.
- [ ] **Step 7: Build and run the gate:** `bash run_all.sh` in `channel_turb`. Expected: exit 0 and both GATE lines pass. **If `drift >= 0.02` for either run: STOP, commit nothing further, report the GATE lines and what was built (owner's stop rule).** If steady but outside the near/logwake bands: STOP and report the numbers.
- [ ] **Step 8: Commit** (`fix(keps): flux (Neumann) wall conditions with roughness lengths (#125)`), with the before/after GATE lines in the message.

### Task 3A: GOTM time treatment (owner-approved bounded retry, spec Amendment A)

**Files:**
- Modify: `src/shyfem/kepsilon.f90` (`keps`: solve order, interior source split, flux k)
- Modify: `testcases/examples/channel_turb/analyse.py` (2-step test in the GATE)

**Interfaces:**
- Consumes: Task 3's `keps(...,z0s,z0b)` and boundary rows (commit 128bcdea), unchanged in signature.

- [ ] **Step 1: Extend the GATE** (spec Amendment A item 4): per `keps_NN` run read `keps_NN.inf`, take the `energy:` lines of the last 120 time steps, and add `flip=<max relative step-to-step change over all numeric fields>`; a run passes only with `flip < 1e-4` in addition to Task 3's conditions. Print `flip` on the GATE line.
- [ ] **Step 2: Run the gate on 128bcdea's build.** Expected: FAIL, keps_20 `flip` about 1.7e-4 (RED), GOTM runs `flip` 0 if you also print them.
- [ ] **Step 3: Implement Amendment A items 1-3** in `keps`, interior rows `1..lmax-1` of both equations, for `lmax >= 3` only (the `lmax <= 2` path stays textually unchanged).
- [ ] **Step 4: Build and run the gate.** Expected: exit 0. **If it fails in any way, STOP for good** (owner): commit WIP only if it builds, report BLOCKED with the GATE lines; the controller then closes #125 as won't-fix.
- [ ] **Step 5: Commit** (`fix(keps): flux wall conditions with GOTM time treatment (#125)`), squash-free, with before/after GATE lines in the message.

### Task 4: Regression gates, MPI/OMP and the Venice comparison

**Files:**
- No code changes expected. A failure here sends the fix back to Task 3.

**Interfaces:**
- Consumes: the Task 3 build; `visv_ratio.py` and the baselines from Task 1.

- [ ] **Step 1: Battery:** rerun Task 1 Step 5. Expected: every md5 in `$S/baseline_md5.txt` identical **except** outputs of `mm_rst_keps_write.str` (k-eps); that run must reach `simulation end`.
- [ ] **Step 2: Venice:** rerun `venlag_keps_smoke.str` with `-debout`; `simulation end` reached; `python3 visv_ratio.py <new keps.dbg> $S/base_gotm.dbg`. Expected: `shallow` ratios identical to `$S/baseline_venice.txt` (Review Focus 1); report `top`/`bottom`/`column` before -> after.
- [ ] **Step 3: Wind/roughness check (Review Focus 3):** add a temporary print of the min/max `z0s` over nodes in `keps_shell`, run `venlag_keps_smoke`, record the range (expected: all `>= z0smin`, finite), then remove the print.
- [ ] **Step 4: MPI:** build the MPI binary (`PATH=/usr/bin:$PATH make clean && PATH=/usr/bin:$PATH make fem OMP=false MPI=true PARTS=METIS METISDIR=/usr`), run `mpirun --oversubscribe -np 4 shyfem -debout venlag_keps_smoke.str`; `simulation end` reached; `visv_ratio.py` `column` ratio within 10% of the 1-rank value (k-eps amplifies round-off across ranks, memory 2026-10-15). Rebuild the default binary afterwards.
- [ ] **Step 5: OpenMP:** run `venlag_keps_smoke.str` with `nomp = -1` in a scratch copy of the STR (`$para`) and `OMP_NUM_THREADS=4`; confirm the log line `used OMP threads: 4` and `simulation end`.
- [ ] **Step 6: Commit** nothing unless a fix was needed; record all numbers for Task 5.

### Task 5: Warning, docs and PR

**Files:**
- Modify: `src/shyfem/turbulence.f90` (`turb_closure` start-up warning, about lines 104-110)
- Modify: `CHANGELOG.md` (`[Unreleased]`, core `### Fixed`)
- Modify: `docs/reviews/2026-10-18-keps-vs-gotm-benchmark.md` (new dated section)

**Interfaces:**
- Consumes: the GATE lines (Task 3) and the Venice/MPI/OMP numbers (Task 4).

- [ ] **Step 1: Reword or remove the `iturb=2` warning** to the new near-bed and full-depth numbers (remove it only if k-eps is at or better than GOTM on both); build; run `keps_20.str` and check the new text in the log.
- [ ] **Step 2: CHANGELOG entry**, core `### Fixed`: "**Model, turbulence (changes results for `iturb=2` runs):** ..." stating the flux wall conditions, roughness lengths from the model's own friction and wind stress, the channel before/after (near-bed 1.51/1.52 -> new; full depth 32-37% high -> new), the Venice k-eps/GOTM ratio before/after, that 1-2 layer columns are unchanged, that `cb`/`cd` no longer affect deeper columns, and "closes #125".
- [ ] **Step 3: Report section** "2026-11-20: flux wall conditions" in the benchmark report: the GATE lines, the Venice table, MPI/OMP notes.
- [ ] **Step 4: Fortran CI-equivalent locally:** `./bin/check_implicit_none.py src/shyfem --max-violations 0` passes.
- [ ] **Step 5: Commit, push, open the PR** (title `fix(keps): flux wall conditions for k-epsilon (#125)`; body: spec link, GATE lines, Venice table, battery result, MPI/OMP, "changes results for iturb=2", "Closes #125"). Stop at green CI; merging is the owner's call.
