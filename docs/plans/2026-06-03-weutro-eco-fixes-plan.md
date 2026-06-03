# weutro / EUTRO Ecological Model — Fix Implementation Plan

**Created:** 2026-06-03
**Source review:** `docs/reviews/2026-06-03-weutro-eco-model-review.md`
**Reference oracle:** AQUABC-II at `/home/razinka/AQUABCv0.2` (git `razinkele/ESTAS-AQUABC`)
**Decisions (confirmed with owner):** full scope (crit+high+med+conventions); fix 3D physics (C1/C2) now; build a real EUTRO test case for verification; C5 = MIN_CONCENTRATION floor + clamp-and-continue (AQUABC pattern).

## Context / constraints
- **weutro is NOT in the default build** (`Rules.make:304 ECOLOGICAL = NONE` → `ecological_dummy.f90`). Bugs affect only `ECOLOGICAL = EUTRO` builds. ⇒ no shipped-binary regression risk, but also **zero existing test coverage**.
- **No Fortran unit harness** (no pFUnit). Verification = build with EUTRO + run testcases + scripted output checks (NaN/mass/profile). Phase 0 must create this first.
- **No testcase enables `ibio`**; no `bioin` IC files exist. Must author one.
- Must keep `ECOLOGICAL = NONE` building cleanly and **mar_menor (non-eco) regression intact** at every phase.
- Git: feature branch `fix/weutro-eco`, one commit per phase, **multi-agent review before merge** (owner's standing preference), PR to main. (This is Fortran core, not the UI — merging does not deploy laguna UI, but follow the usual review gate.)

## Workflow per phase
1. Implement the phase's edits.
2. `make clean && make fem` with `ECOLOGICAL=EUTRO` → must compile (and a `ECOLOGICAL=NONE` build sanity check).
3. Run the Phase-0 eco testcases (1-layer + stratified) → run the check script (no NaN, mass deltas within tol, profiles sane).
4. Run mar_menor (non-eco) → unchanged results.
5. Commit. At end, adversarial multi-agent review → fix blockers → merge.

---

## Phase 0 — Verification infrastructure (PREREQUISITE) ✅ DONE
Nothing downstream can be validated without this. **Status: complete** (branch `fix/weutro-eco`).
- Commit 1 — fixed 2 pre-existing fixed-form OPEN continuations (`weutro.f90:2218`, `weutro_light.f90:252`); weutro was **uncompilable** with `ECOLOGICAL=EUTRO`. Now builds + links shyfem/rstinf.
- Commit 2 — `testcases/examples/weutro_box/` with `eco_2d.str` (2D smoke), `eco_3d.str` (12-layer), `check_eco.sh` gate (no-NaN / positivity / DO-range, validator proven to bite), Makefile/README/.gitignore.
- Baseline: both cases run clean; DO 7.8→~7.65 mg/L (respiration); all states positive.
- Deferred to Phase 3: constant light forcing so C1/C2 become observable (currently latent: `qrad=0`, well-mixed).

- **0.1 EUTRO build recipe.** Confirm `make fem ECOLOGICAL=EUTRO` links weutro. Document the exact command; add to the test script. Verify `ECOLOGICAL=NONE` still builds (dummy path).
- **0.2 Minimal eco testcase (2D / 1-layer smoke).** Small grid + `.str` with `ibio>0`, EUTRO section params, short run (a few days). Establishes a baseline and a fast smoke gate. Place under `testcases/examples/weutro_box/` (new).
- **0.3 Stratified multi-layer testcase.** Same chemistry, several vertical layers + stratification (T/S profile or `nlv>1` with a thermocline). **This is the case that exposes C1 and C2** (2D masks them). Capture baseline DO/nutrient profiles and column mass.
- **0.4 Check script** (`testcases/examples/weutro_box/check.sh` or Python): asserts (a) no NaN/Inf in outputs, (b) total N/P/DO mass change over a closed run within tolerance (mass conservation), (c) DO/nutrient vertical profiles are physically ordered (e.g. surface DO ≥ deep DO under the fixed model). Used as the "test" gate for all later phases.

> Note: 0.3 will initially show the **wrong** stratified behavior (uniform light, over-aerated deep layers) — that is the pre-fix baseline that Phase 3 must correct.

---

## Phase 1 — Robustness / anti-crash (lowest risk, do first) ✅ DONE
Goal: a stiff/over-large step can never crash or NaN the run. **Status: complete** (commit on `fix/weutro-eco`).
- C5: `euler()` cmin=1e-5 positivity floor (re-enabled the disabled clip); `eutro_check()` split fatal (neg vol/depth → `shympi_abort_internal`) from recoverable (neg state → clamp-and-continue); bare `stop` removed.
- H2/NU-3/NU-4/BIO-06: `max(.,1e-10)` floors on `SA=vol0/depth0`, `SOD/H`, and both `TEMP1=SKE*H` light denominators.
- Gate tightened to strict positivity (TOL=0); 2D+3D pass, values identical to baseline (no regression).

- **C5 — positivity + safe abort.** `weutro.f90`
  - Add `MIN_CONCENTRATION = 1.0e-5` (match existing intended floor; AQUABC uses 1e-10 in double — pick a single-precision-safe floor) as a named constant.
  - In `euler` (`~410–440`): after the update, `c(i) = max(c(i), MIN_CONCENTRATION)` (re-enable the commented-out clip as a real floor).
  - In `eutro_check` (`475–503`): remove the **bare `stop`**; clamp-and-continue (the dead clamp at 499–502 becomes the live path). Reserve a hard error for clearly unphysical magnitudes only, routed through `shympi_abort_internal` (never bare `stop`).
- **H2 / NU-3 / NU-4 / BIO-06 — depth-division guard.** `weutro.f90:670,1504,1668–1669,1737,1745,2079`
  - Introduce `H_eff = max(H, H_MIN)` (single depth floor constant) and use it in `SA=vol/depth`, SOD `/H`, and the DiToro/Smith `TEMP1=SKE·H` terms.
- **NU-5** resolves automatically once C5 floors concentrations before the fractional-power extinction term.

**Verify:** force a tiny `dt`-stress / low-nutrient run; confirm no NaN, no stop, states stay ≥ floor.

---

## Phase 2 — Correctness bugs (non-3D)  🚧 C3 + C4 DONE, H1 remaining
- ✅ **C3** (ulva DO + nutrient indices) — committed. Inspection-verified + no-regression; **not** gate-exercised (ulva unseeded). Also fixed rotated nutrient `cds`; noted (unfixed) the min-quota cds-not-zeroed kinetics call.
- ✅ **C4** (real restart serialization) — committed. **TDD-validated**: `check_restart.sh` round-trip RED→GREEN (bit-for-bit, 0 diff). Touches weutro.f90 (serialize) + bio3d.f90 (alloc guard + skip einit when `brst_loaded`).
- ⏳ **H1** (OMP race on `scal_adv` SAVE arrays) — pending; needs a multi-thread gate run + care (touches core `concentration.f90`).

- **C3 — ulva oxygen index.** `weutro_ulva.f90:151,211,215,289`
  - Replace phyto `c(4)` with DO `c(6)` for oxygen read/build/write (`oxy=c(6)`, `cds(6)`, `c(6)=ca(6)`).
  - Audit **every** `c()` index in `wulva` against canonical map (nh3=1,no3=2,opo4=3,phyto=4,cbod=5,do=6,on=7,op=8,zoo=9).
- **C4 — real ecological restart.** `weutro.f90:2593–2614` (+ `restart.f90` wiring)
  - Implement `write_restart_eco`: `use eutro`, write `nstate,nkn,nlvdi` then each `e(:,:,i)` (and `es/esh/eul` when `bsedim/bshell/bulva`).
  - Implement `read_restart_eco`: read back, **validate** array sizes / variable count+order against running config; error clearly on mismatch.
  - Add a guard: if restart record is the legacy `nstate=0` stub, refuse with a clear message (don't silently cold-start).
- **H1 — OMP data race.** `src/shyfem/bio3d.f90:592–607` + `concentration.f90:298–302,325–329,350–351`
  - Make `scal_adv` work arrays (`r3v`, …) thread-private (automatic locals or `THREADPRIVATE`/`firstprivate`), **or** remove the OMP DO over the 9 variables for bio advection. Confirm no other consumer relies on the SAVE state.

**Verify:** restart round-trip test (run N steps → checkpoint → restart → continue == single run); ulva-enabled run shows DO responding and phyto not corrupted; OMP vs serial bio run agree bit-for-bit (or within tol).

---

## Phase 3 — 3D physics regressions (validate against the stratified case)
This is where scientific output changes; gate hard on the Phase-0.3 stratified baseline.

- **C1 — per-layer segment flags.** `bio3d.f90:509–531`
  - Inside the layer loop, before each `eutro0d`: `call settopseg(l==1)`, `call setbotseg(l==lmax)`, `call setsedseg(.false.)` (pelagic).
  - Confirm `source()` doesn't unconditionally reset these (`weutro.f90:641–643`); ensure the sub-models (`weutro_sedim/shell/ulva`) restore the shared globals rather than leaving them flipped.
  - Result: reaeration only at surface layer; SOD/benthic flux only at bottom layer.
- **C2 — vertical light attenuation.** `weutro.f90:639–672,1664–1670,1786–1792`; `bio3d.f90:507–525`
  - Drive per-layer attenuation: carry each layer's bottom-of-layer light fraction forward as the next layer's surface fraction (`exp(-ke·Σh_above)`), via the `RLGHTS`/`rlux` cascade the comments describe, OR reduce `qrad` layer-by-layer in `bio3d` ordering layers surface→bottom.
  - Remove/guard the 2D Steele override and the hardwired `iseg=1/ito=0`.

**Verify against Phase-0.3 stratified baseline:** surface DO > deep DO; phyto growth decreases with depth; deep layers no longer over-aerated; column mass still conserved. Sanity-compare qualitative behavior to AQUABC-II on a similar profile.

---

## Phase 4 — Remaining mediums

- **TR-05** `src/shyfem/bio3d.f90:477,595–600` — `wsink=0`: wire real settling velocities for phyto/detritus (from STR), or explicitly document as intentional-off.
- **TR-06** `bio3d.f90:305,362,520` — dead `eload`: populate pelagic loadings from STR/forcing, or remove the dead path.
- **LC-3** `bio3d.f90:465–487` — keep model time in real days (avoid `it=dtime` integer truncation degrading diurnal light/loads).
- **ECO-04** `weutro.f90:285,723–724,1440` — pass real air temperature to wind reaeration instead of hardcoded 22 °C (wire `wmeteo` into the 3D path).
- **ECO-05** `weutro.f90:302–305,2244–2246` — reconcile Steele `IS2` optimum-irradiance units with the W/m² light actually supplied.
- **BIO-07** `bio3d.f90:550–570` — store/seed `esh`/`eul` at the correct layer (currently layer-1 seed but bottom-layer reaction).
- **BIO-08** `weutro.f90:1986–1994` — `KAWIND` must not mutate its input `WS`; replace bare `stop` on unknown `WTYPE`.

---

## Phase 5 — Conventions sweep (last; mechanical)
Align with CLAUDE.md Fortran conventions. Low correctness risk but large surface.

- **FC-02** add `stat=ierr` + check to all eco allocations (bio3d.f90, bio3d_util.f90, weutro_seed.f90).
- **FC-04** replace bare `stop` in MPI-reachable kernels with `shympi_abort_internal` (prioritize per-timestep ones already handled in P1/P2).
- **FC-05** `weutro_light.f90`, `weutro.f90:159,1820` — use `mod_physical_constants` instead of hardcoded `pi=3.14159`.
- **FC-01** add `intent(in/out/inout)` across the subsystem (start with kernel signatures `eutro0d/source/wsedim/wshell/wulva` + light functions).
- **FC-03** convert GOTO clusters (`weutro.f90` reaeration/sediment kernels) to `select case` / `do…exit`.
- **FC-06** modernize three-line `save`/`data icall` to single-line init.
- **ECO-06** make `NUTLIM` an **integer** flag (currently `real` compared with `.EQ.`).

---

## Science decision checkpoint (owner call — NOT auto-applied)
- **NUTLIM default = multiplicative vs documented `Default=0` (Liebig minimum).** Multiplicative compounds co-limitation and biases phyto growth down; Droop (1974) favored minimum for algae; AQUABC-II uses an intermediate harmonic form. **Do not silently flip the default.** Options to decide before/after Phase 5: (a) keep multiplicative (document why), (b) switch default to minimum (matches the code comment + literature), (c) adopt AQUABC-II's intermediate `a·b/max(a+b−a·b,ε)`. Recommend (c) for 3D realism, but it changes results — owner picks.
- **ECO-07** (respiration routed to organic vs inorganic N/P) — flag for owner; behavioral, not a clear bug.

---

## Sequencing & risk summary
| Phase | Risk | Why ordered here |
|-------|------|------------------|
| 0 Test infra | none | required to validate anything |
| 1 Robustness | low | stops crashes; pure safety floors |
| 2 Correctness | low–med | localized bug fixes; restart is the biggest |
| 3 3D physics | **med–high** | changes scientific output; needs 0.3 baseline |
| 4 Mediums | low–med | feature gaps / wiring |
| 5 Conventions | low | mechanical, large surface |

**Estimated commits:** ~6 (one per phase) on `fix/weutro-eco`, multi-agent review before PR merge.

**Definition of done:** all phases merged; `ECOLOGICAL=EUTRO` builds; eco testcases pass the check script (no NaN, mass conserved, stratified profiles physical); `ECOLOGICAL=NONE` + mar_menor regress clean; NUTLIM/science decisions resolved by owner.
