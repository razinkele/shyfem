# SHYFEM Ecological Models — Hardening Campaign Summary (2026-06-03 → 06-04)

Closing record of the deep review + hardening of SHYFEM's ecological models and
their hydro coupling. All work is merged to `main` and pushed.

## Starting point
- **weutro/EUTRO** did not compile (`ECOLOGICAL=EUTRO`), had **zero test coverage**, and was unvalidated under MPI.
- **mercury** did not run at all (`MERCURY=true`): a missing param + a div-by-zero; its restart silently corrupted the restart stream.
- A 29-agent review of weutro found 20 confirmed defects (5 critical / 8 high / …).

## What shipped

### weutro / EUTRO
- **Compiles** again (fixed fixed-form OPEN continuations).
- **C1** per-layer segment flags (reaeration/SOD/benthic flux were applied to every 3D layer).
- **C2** Beer-Lambert vertical light attenuation (every layer got full surface irradiance) via new `get_weutro_ke()`.
- **C3** ulva DO/nutrient index fix (oxygen written to phyto; rotated nutrient uptake).
- **C4** real restart serialization (was a silent no-op) via the `mod_restart` MPI gather/scatter helpers.
- **C5** explicit-Euler positivity floor + clamp-and-continue; bare `stop` → `shympi_abort_internal`.
- **H1** removed a racy OMP-over-variables loop (4-thread SIGSEGV).
- **H2** depth/denominator floors against drying layers.
- **FC-04** all remaining bare `stop`s → `shympi_abort_internal`.
- **NUTLIM** default switched to Liebig minimum (was multiplicative) — owner decision, literature-backed (Droop 1974).
- **Settling (TR-05)** wired + configurable via new `wsphyt` param (was hardcoded `wsink=0`); default off.

### mercury
- **Runs** now: restored `molhg=12.74` (was 0 → Wilke-Chang div-by-zero SIGFPE); registered the missing `mercsolin` param.
- **Restart** rewritten from a stream-corrupting no-op to full state serialization (`emp/ems/emsolw/emsols` + evolving `dZbed/dZactiv`) with a bmaster-guarded header.

### Test infrastructure (new — there was none)
`testcases/examples/weutro_box/` with **6 gates** (`make check-all`):
eco (positivity/DO/NaN), restart (bit-for-bit), omp (1≡4 threads), light
(vertical gradient), settle (downward redistribution), mercury (runs + restart).

## Validation
- All 6 gates pass on a combined `ECOLOGICAL=EUTRO MERCURY=true` build.
- weutro C4 restart + mercury restart are **bit-for-bit, serial and under `mpirun -np 4`**.
- weutro fixes adversarially reviewed (2 C4 blockers found → fixed → re-verified); mercury hardening adversarially reviewed (MERGE, no blockers).
- Default `ECOLOGICAL=NONE` build + mar_menor regress clean.

## MPI
`PATH=/usr/bin:$PATH mpirun --oversubscribe -np 4 shyfem <str>` (METIS auto-partitions).
Validation surfaced + fixed a pre-existing weutro MPI bug (ulva seeding not decomposition-aware).

## Deliberately NOT done
- **In-tree AQUABC** (`ECOLOGICAL=AQUABC`): does not compile (incomplete 2024 module conversion) and is **superseded** by the standalone `AQUABCv0.2` (`razinkele/ESTAS-AQUABC`), whose sediment diagenesis is a full modular rewrite (`..._sediment_model_1_fast.f90` + `SEDIMENT_LIBRARY`). Hardening the in-tree fork is low-value; integrating AQUABCv0.2 into the tree is a separate major port if AQUABC sediment is a priority.
- **BFM**: not an in-tree model — only `bfm_dummy.f90` (a no-op stub; its restart stubs are empty-and-consistent) lives in the repo. The real BFM is an **external library** (`BFMDIR/lib/libbfm` + NETCDF), marked experimental/unsupported. Nothing to harden in-tree.
- lagrange, hydro core: out of eco scope.

## Eco-model survey — complete
All four ecological models characterized: **weutro** (hardened), **mercury** (hardened), **AQUABC** (in-tree superseded/bit-rotted → port AQUABCv0.2 if needed), **BFM** (external dependency, not in-tree). No further in-tree eco-model hardening remains.

## weutro science — resolved
- **Calibration set now selectable** (`iwcal`): was hardcoded to Venice-lagoon params for every run; now 0=generic / 1=Venice / 2=Taranto / 3=file, with the active set logged. **Owner decision: default stays Venice (`iwcal=1`)** — preserves legacy results.
- **ECO-05 (`IS2` units): not a bug** — the active path (`param_venezia` → `IS2=200`) is W/m²-consistent with `iinst=qrad`; the lux/day value is overridden.
- **NUTLIM** → Liebig minimum (owner-decided, merged).

## weutro decisions — closed 2026-11-20 (delegated by the owner)
All four stay as they are; nothing changes results. They are listed as known limitations in `MANUAL.md` (EUTRO section). Reopen when EUTRO is set up for a real site, which can supply the values.
- `wsphyt` stays 0 (phytoplankton settling opt-in). No calibration backs a default value; same reasoning as keeping `iwcal = 1` to preserve legacy results.
- `eload` (TR-06): no user parameter exists. It is an internal array filled from `elinit`, all zeros, so there is no pelagic loading input. Adding one needs the states, nodes and rates of a real application.
- ECO-04: the air temperature for wind-driven reaeration stays fixed at 22 °C (wind itself comes from the model per node). Passing the real air temperature is the fix when a site needs it.
- Detritus settling stays off: it needs particulate/dissolved partition fractions for ON, OP and CBOD. Note the sediment compartment (`weutro_sedim.f90`: deposition of ON/OP at a fixed 10 m/day x particulate fraction, resuspension) is switched off in the code too (`bsedim = .false.` in `bio3d.f90`, never set), so only the 9 water-column states run; MANUAL.md now says so.
