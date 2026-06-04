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

## Owner decisions still open (weutro)
- `wsphyt` default velocity (settling is opt-in; give a value to enable by default).
- `eload` loading spec (TR-06); ECO-04 air temp; ECO-05 `IS2` units.
