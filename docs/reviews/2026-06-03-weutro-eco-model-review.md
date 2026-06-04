# SHYFEM Ecological Model (weutro / EUTRO) + Hydro Coupling — Deep Review

**Date:** 2026-06-03
**Scope:** `src/contrib/ecological/weutro/` (weutro.f90, bio3d.f90, weutro_light/sedim/wdia/seed/ulva/shell.f90, bio3d_util.f90) and the operator-split coupling to the hydro core (`src/shyfem/shyfem_subs.f90`, `concentration.f90`, `restart.f90`).
**Method:** 29-agent multi-dimension workflow (6 lenses: loop-coupling, transport-reaction, numerics/units, ecology-science, bugs/edge-cases, fortran-conventions) → adversarial refute pass on every crit/high → synthesis. 39 raw findings, **20 confirmed**. Cross-checked against the newer **AQUABC-II** model (`/home/razinka/AQUABCv0.2`, git `razinkele/ESTAS-AQUABC`, 2026-02-27) as a reference oracle, and against the WASP/EUTRO literature (scite).
**Status:** REVIEW ONLY — no code modified.

> The 20 confirmed findings collapse to **~7 distinct defects** (several were surfaced redundantly by multiple lenses). They are deduped below. IDs in brackets are the originating lens findings.

---

## Critical

### C1. 3D reactor never sets segment flags per layer — every layer treated as BOTH surface and bottom  `[TR-01 / BIO-02 / ECO-01]`
**`bio3d.f90:509–531` (loop); `weutro.f90:641–643,692,898–899,1431,1504`**
The pelagic column loop calls `eutro0d` for each layer but never calls `settopseg`/`setbotseg`/`setsedseg`. `eutroini` sets `topseg=.true.`/`botseg=.true.` once at init and `source()` never resets them, so **both stay `.true.` for every layer**. Consequences in 3D:
- **Reaeration** (`DISSOXYG`, gated `IF(topseg .AND. xicecvr>0)`) adds `KA*(CS−DO)` to DO in *every* layer, not just the surface → gross over-aeration of subsurface water.
- **Benthic flux** (`BENTFLUX`, gated `if(botseg)`) injects `FNH4`/`FPO4` into *every* layer (latent until benthic fluxes are forced nonzero).
- **SOD** is subtracted in every layer.

Masked entirely in 2D/single-layer runs (l=1 genuinely is both surface and bottom). The sub-models `weutro_sedim/shell/ulva` already call the setters — the pelagic path is the omission.
**Fix:** inside the layer loop, `call settopseg(l==1)`, `call setbotseg(l==lmax)`, `call setsedseg(.false.)` before each `eutro0d`. *(AQUABC-II handles surface/bottom per layer correctly — see oracle below.)*

### C2. Light is not attenuated with depth — every layer receives full surface irradiance  `[ECO-02 / TR-02 / BIO-03]`
**`weutro.f90:639–672,1664–1670,1786–1792`; `bio3d.f90:507–525`**
`iseg`/`ito` are hardwired to 1/0; the self-shading return (`RLGHTS(ITO,2)`, intended to cascade surface→bottom) is written to index 0 and never propagated. Each layer reuses the surface `qrad`, so phytoplankton growth is over-predicted throughout the column in stratified 3D runs. Masked in 2D.
**Fix:** carry each layer's cumulative attenuation forward (`exp(-ke·Σh_above)`), or advance `iseg/ito` and call layers strictly surface→bottom so `RLGHTS` propagates; drop the 2D Steele override. *(AQUABC-II attenuates per layer.)*

### C3. `wulva` reads/writes oxygen via the PHYTO index `c(4)` instead of DO `c(6)`  `[BIO-01]`
**`weutro_ulva.f90:151,211,215,289`**
The macroalgae (ulva) module corrupts the phytoplankton pool and never updates DO. Canonical mapping: `nh3=1,no3=2,opo4=3,phyto=4,cbod=5,do=6,on=7,op=8,zoo=9`.
**Fix:** map ulva oxygen to `c(6)`/`cds(6)`; audit every `c()` index in `wulva`.

### C4. Ecological restart is a silent no-op — bio state lost on every restart  `[LC-1 / BIO-05]`
**`weutro.f90:2593–2614`**
`write_restart_eco` writes only `nstate=0, nkn=0` and **never writes `e(:,:,:)`**; `read_restart_eco` just delegates to `skip_restart_eco` (loops 0 times). `restart.f90:586` sets `ieco=ibio`, so any active eutro run takes this path. Hydro/T/S/turbulence/conz resume correctly, but **all 9 pelagic states (plus sediment `es`, shell `esh`, ulva `eul`) are discarded** and silently re-initialized to `einit` defaults (`bio3d.f90:304,360–363`). Chained/restarted runs produce wrong ecology with no warning.
**Fix:** serialize/restore `e` (and `es/esh/eul`) with real dims (`nstate,nkn,nlvdi`) and validate on read; until then, make `restart.f90` hard-error when `ieco>0`.

### C5. `eutro_check` aborts the whole run on any negative value; positivity clamp is dead code; Euler has no guard  `[NU-2 / TR-04 / ECO-03 / BIO-04 + NU-1 / LC-2]`
**`weutro.f90:475–503` (esp. 499–502), `410–440`**
Explicit forward Euler (`c=(mass+dt·cds)/vol`) with the positivity clip **commented out** (`weutro.f90:435`). Stiff per-day rates × the timestep can overshoot a state negative; the negative then feeds back as a divisor / fractional-power base → NaN. `eutro_check` responds with a **bare `stop`** on any negative, and the intended clamp (`c(i)=0.00001`) sits *after* the stop as **unreachable dead code**. The bare `stop` is also MPI-unsafe (one rank stops, others hang).
**Fix:** clamp-and-continue (move the floor before/instead of the stop), *or* make sinks semi-implicit `c=(mass+dt·sources)/(1+dt·sink_rate)` (unconditionally positive), *or* sub-cycle the reaction. Route any genuine fatal through `shympi_abort_internal`. *(This is the single highest-value robustness fix; AQUABC-II's pattern is below.)*

---

## High

### H1. OpenMP data race: `scal_adv` SAVE work arrays shared across threads in the per-variable bio transport loop  `[TR-03]`
**`src/shyfem/bio3d.f90:592–607` (OMP loop) + `concentration.f90:298–302,325–329,350–351`**
The bio advection parallelizes over the 9 state variables, but the transport work arrays (`r3v`, …) are module-level `SAVE` — shared, not thread-private → corruption / nondeterminism under OMP.
**Fix:** make the work arrays automatic locals or `THREADPRIVATE`/`firstprivate`; or drop the OMP DO over variables for bio advection.

### H2. Multiple divisions by box depth `H` with no zero-guard → Inf/NaN on drying or thin layers  `[NU-3 / NU-4 / BIO-06]`
**`weutro.f90:670,1504,1668–1669,1737,1745,2079`**
`SA=vol/depth`, SOD `/H`, and the DiToro/Smith light terms (`TEMP1=SKE·H`) divide by depth/`H` with no floor. On wetting/drying or very thin top layers this yields Inf/NaN that then propagates through the column.
**Fix:** `H_eff = max(H, eps)` (a single depth floor) before all such divisions.

---

## Medium

| ID | Issue | Location | Fix |
|----|-------|----------|-----|
| TR-05 | `wsink=0` for all bio vars — phyto/detritus **sinking never applied** in transport | `src/shyfem/bio3d.f90:477,595–600` | wire real settling velocities (or document as intentional) |
| TR-06 | Pelagic loadings `eload` are **dead**: init 0, never populated from STR/forcing | `src/shyfem/bio3d.f90:305,362,520` | populate from forcing, or remove the dead path |
| LC-3 | Integer truncation `it=dtime` degrades diurnal light & time-dependent loads | `bio3d.f90:465–487` | keep time in real days |
| NU-5 | Fractional-power extinction → NaN if phyto goes negative before the check | `weutro.f90:1655,1775` | follows from C5 positivity fix |
| ECO-04 | Air temp for wind reaeration **hardcoded 22 °C** (`wmeteo` never called in 3D) | `weutro.f90:285,723–724,1440` | pass real air temp; otherwise only Steele light is usable |
| ECO-05 | Steele optimum irradiance `IS2` units inconsistent with the W/m² light supplied | `weutro.f90:302–305,2244–2246` | reconcile light units (ly/day vs W/m²) |
| BIO-07 | `esh`/`eul` seeded from layer-1 but reaction applied at bottom; 2D-state stored in 3D | `bio3d.f90:550–570` | store/seed per the correct layer |
| BIO-08 | `KAWIND` mutates its input `WS` and bare-`stop`s on unknown `WTYPE` | `weutro.f90:1986–1994` | don't mutate arg; route error via shympi |
| FC-02 | `allocate(...)` without `stat=` across the subsystem | bio3d.f90, bio3d_util.f90, weutro_seed.f90 | add `stat=ierr` + check (CLAUDE.md convention) |
| FC-04 | Bare `stop` in MPI-reachable kernel paths | weutro.f90:499,1994,2222,…; +5 files | `shympi_abort_internal` (prioritize per-timestep ones) |
| FC-05 | Hardcoded `pi=3.14159` instead of `mod_physical_constants` | weutro_light.f90, weutro.f90:159,1820 | `use mod_physical_constants` |

## Low
GOTO clusters (`FC-03`), no `intent()` anywhere in the subsystem (`FC-01`), three-line `save`/`data icall` pattern (`FC-06`), `tsmass` is diagnostic-only with no conservation correction (TR-07/LC-4), `NU-6`/`ECO-07` minor. These are convention/cleanup, not correctness.

---

## Verified NOT a bug
- **NU-7 — per-day vs per-second dt conversion is correct.** `bio3d.f90:484 dtday=dt/86400.` is passed as the `dt` arg to `eutro0d` at `:525` (and `wsedim/wshell/wulva` at 539/555/566); `weutro.f90` `euler/eutro0d` correctly use `[day]` / `[g/day]`. Independently confirmed by reading the code; the review's numerics lens agreed. Do not "fix."

---

## Domain-expert / science notes (judgement calls, not defects)

### NUTLIM = multiplicative vs the documented `Default=0` (Liebig minimum)  `[ECO-06]`
**`weutro.f90:34 (param_init), 182, 1249–1257`** — code runs `NUTLIM=1` (pure multiplicative) although its own comment says the default should be `0 = minimum`. This is consequential: multiplicative **compounds** co-limitation (when N and P are *both* moderately scarce, multiplying two fractions <1 gives a markedly lower growth rate than the minimum rule), biasing phytoplankton growth **downward**.
- **Literature:** Droop (1974) found the Liebig-minimum model fit algal growth data *better* than the multiplicative model; the min-vs-multiplicative choice is a long-standing, real modeling decision, not cosmetic (Tang & Riley, 2021; de Baar, 1994).
- **AQUABC-II oracle:** the newer model uses neither extreme — an **intermediate** combination `LIM_N·LIM_P / max(LIM_N+LIM_P−LIM_N·LIM_P, 1e-20)` (bounded between multiplicative lower-bound and Liebig upper-bound), then `min(LIM_DOXY, LIM_NUTR)·LIM_LIGHT` (`aquabc_II_pelagic_lib_DIATOMS.f90:173–178`).
- **Recommendation:** confirm with the model owner whether multiplicative is intentional; consider matching the documented default or the AQUABC intermediate form. Also `ECO-06`: `NUTLIM` is a `real` compared with `.EQ.` — use an integer flag.

Other science notes: respiration/death routed to organic rather than inorganic N/P (`ECO-07`); possible double-removal of grazing from phyto when `graztype=1`.

---

## Reference oracle: AQUABC-II (`/home/razinka/AQUABCv0.2`, newer/more-correct)

The user's actively-maintained AQUABC-II (36k LOC, double precision, per-functional-group libraries, 2026-02) is the modern successor and a useful template for fixing weutro:

| Concern | weutro (in-tree) | AQUABC-II | Implication |
|---------|------------------|-----------|-------------|
| Integrator | explicit Euler, single precision `real` | explicit Euler **double** (`STATE += DERIVATIVES·TIME_STEP`, days) | **Same scheme** — so the fix for C5 is *positivity protection*, not a new integrator |
| Positivity | clip commented out; bare `stop` on negative | `MIN_CONCENTRATION=1.0D-10` floor + `max(0,min(1,·))` clamp on every limitation factor + negative-CHLA diagnostic-and-stop | adopt a floor + clamp-and-continue (C5) |
| Vertical light | full surface irradiance per layer (C2) | attenuated per layer | C2 is a genuine 3D regression vs AQUABC |
| Segments | flags never set per layer (C1) | surface/bottom handled per layer | C1 genuine vs AQUABC |
| Nutrient limitation | hardcoded multiplicative (against own default) | intermediate harmonic-type, bounded | see NUTLIM note |

**Bottom line:** weutro is serviceable in 2D but has **two critical 3D-only physics regressions (C1, C2)**, a **silent restart data-loss bug (C4)**, an **index bug in the ulva module (C3)**, and a **fragility/abort pattern (C5)** that AQUABC-II already solves with a min-concentration floor. For new 3D ecological work, AQUABC-II is the sounder base.

---

## Not reviewed (out of scope this pass)
aquabc (in-tree), mercury, BFM, sediment diagenesis internals, lagrange, hydro core. TVD transport and BFM paths were not exercised. **Recommend adding a multi-layer stratified test case** — it would have caught C1 and C2, which 2D masks.

## Suggested priority order (if/when fixes are authorized)
1. **C5** (positivity floor + clamp-and-continue + replace bare `stop` with `shympi_abort_internal`) — cheapest, stops crashes, MPI-safe.
2. **C3** (ulva DO index) — one-line correctness bug.
3. **C4** (restart no-op) — at minimum hard-error on `ieco>0`; ideally serialize state.
4. **C1 + C2** (3D segment flags + vertical light) — the real 3D physics; pair with a stratified test.
5. **H1** (OMP race), **H2** (depth floor).
6. Conventions (FC-*) as a sweep.

### References
- de Baar, H. J. W. (1994). von Liebig's law of the minimum and plankton ecology (1899–1991). *Progress in Oceanography, 33*(4), 347–386. https://doi.org/10.1016/0079-6611(94)90022-1
- Tang, J., & Riley, W. J. (2021). Finding Liebig's law of the minimum. *Ecological Applications, 31*(5), e2458. https://doi.org/10.1002/eap.2458
