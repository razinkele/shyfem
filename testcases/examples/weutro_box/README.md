# weutro / EUTRO ecological test case

Minimal, self-contained test case for the EUTRO (weutro) ecological reactor and
its hydro coupling. Created as **Phase 0** (verification infrastructure) of
`docs/plans/2026-06-03-weutro-eco-fixes-plan.md` so the eco fixes have something
to validate against — previously the model had no test coverage and did not even
compile with `ECOLOGICAL=EUTRO`.

## Cases
- **`eco_2d.str`** — 2D closed basin, `ibio=1`, 2-day run. Fast smoke gate.
- **`eco_3d.str`** — same chemistry on a 12-layer column (`$levels`). Exercises the
  per-layer reactor loop; this is the case that will expose the 3D-only defects
  (C1 segment flags, C2 vertical light) once light forcing is added in Phase 3.

Both run **closed** (no open boundaries, no forcing). Initial conditions come from
the hardcoded `einit` defaults in `bio3d.f90` (NH3 NO3 OPO4 PHYT CBOD DO ON OP ZOO).

## Build (required first)
```
cd /home/razinka/shyfem && make fem ECOLOGICAL=EUTRO
```

## Run / gate
```
make init      # build GRID/MM_coarse.bas
make check     # run both cases + validate (no-NaN, positivity, DO in [0,25])
```
`check_eco.sh` is the gate: it fails on NaN/Inf, any pelagic state < -1e-6, or DO
out of physical range, and prints a baseline min/aver/max summary per variable.

## Baseline (pre-fix, this branch)
Both cases complete cleanly; DO declines from 7.8→~7.65 mg/L (respiration/BOD),
all states stay positive. NOTE: with no light (`qrad=0`) and a well-mixed closed
basin, layers are near-identical, so C1/C2 are **latent** here — Phase 3 will add a
constant solar-radiation forcing to make the per-layer differences observable.
