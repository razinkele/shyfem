# k-epsilon vs GOTM: neutral open-channel benchmark (2026-10-18)

## Question

After the k-epsilon fixes (#97, #98), SHYFEM's own k-epsilon (`iturb=2`)
gave about twice GOTM's vertical eddy viscosity on the Venice 3D smoke case.
That "~2x gap" was never explained. This benchmark asks where it comes from
and which closure is closer to a known answer.

## Short answer

1. **The Venice comparison was not k-epsilon against k-epsilon.** The GOTM
   namelist shipped with that case (`venice_lagoon/INPUT/gotmturb.nml`) runs
   a *second-order* model (`turb_method=3`, Cheng–Canuto–Howard 2002
   coefficients, `scnd_coeff=7`) with the *generic length scale*
   (`len_scale_method=10`, GLS "gen"). `stab_method=3` in that file is
   ignored by second-order models. The `mar_menor` namelist is also
   second-order CCH02, but with the k-epsilon dissipation equation
   (`len_scale_method=8`, this benchmark's "GOTM k-eps with CCH02
   stability"). The distribution default (`src/external/gotm/gotmturb.nml`)
   is second-order with Canuto A coefficients and the dissipation
   equation. None is the standard first-order k-epsilon model.
2. **The closure family explains only about a fifth of the gap.** In a
   neutral channel, the three GOTM variants (as shipped; standard
   k-epsilon; k-epsilon with CCH02 stability functions) agree with each
   other within about 7%. On Venice, switching GOTM to standard k-epsilon
   moves the median SHYFEM/GOTM ratio from about 2.0 to about 1.75.
3. **Most of the gap is SHYFEM k-epsilon's own wall treatment.** Near the
   bed, where the log law makes `nu_t = kappa u* z` exact, SHYFEM's
   k-epsilon gives **1.5x** the theoretical value at both 20 and 40 layers.
   GOTM gives about 0.8–0.85x. Over the full depth, against the
   experiment-based log-wake profile, GOTM is within 6% and SHYFEM's
   k-epsilon is 32–37% high. The evidence points at the epsilon wall
   condition, in how and where it is imposed. A second wall-treatment
   inconsistency was also found: wall stresses come from hard-coded drag
   coefficients. It is real, but not what makes the near-bed value 1.5x
   (details below). Correcting either is a results-changing decision for
   the model owner, not part of this benchmark.

## The benchmark

`testcases/examples/channel_turb/` (run `./run_all.sh`, about 2 minutes):

- **Domain:** a flat 10 m deep straight channel, 20 km x 1 km, 250 m
  triangles (`make_grid.py`).
- **Forcing:** a 0.1 m water-level drop between the open ends; no wind,
  no Coriolis, no stratification (`ibarcl=0`).
- **Bottom friction:** roughness length z0 = 5 mm (`ireib=6`).
- **Layers:** 20 and 40 uniform layers. The two counts test whether the
  wall treatment depends on resolution.
- **Runs:** 2 days, which reaches steady state. The last two hourly dumps
  differ by about 1e-6 in every reported run.
- **Output:** the eddy viscosity comes from the `-debout` dump (`*.dbg`),
  read by `analyse.py`.
- **Profile location:** mid-channel, at the centreline node 203 (x = 10 km).

**Reference.** For steady uniform neutral flow, `u*^2 = g H S`, where S is
the measured surface slope. That gives u* = 2.22 cm/s in every run,
independent of either closure. The theory is:

- the log law near the bed, `nu_t = kappa u* z` (z above the bed), exact
  for z/H < 0.2;
- the parabola `nu_t = kappa u* z (1 - z/H)` over the full depth, kappa = 0.4.

The parabola "is valid only in the log layer" (Absi, 2021). Over the full
depth the comparison uses the log-wake-modified profile instead:

`nu_t = kappa u* z (1 - z/H) / (1 + pi PI (z/H) sin(pi z/H))`

with Coles' parameter PI = 0.2, the value found in open-channel flow
experiments (Absi, 2021, comparing against the eddy-viscosity data of
Nezu and Rodi). That profile is everywhere smaller than the parabola,
0.76x at mid-depth, and the two coincide near the bed.

**Consistency checks, all passing.**
- The bottom-layer velocity is the same in every run (0.218 m/s) and equals
  the log law at the bottom-layer centre. The momentum friction is
  consistent.
- In every run, the dumped `visv` equals the viscosity implied by that run's
  own velocity shear, `u*^2 (1 - z/H) / (du/dz)`, to 1.00. The momentum and
  turbulence equations are coupled consistently in all four models.

## Results

Ratios of each run's eddy viscosity to the analytical profile:

| run | layers | depth-mean U (m/s) | max / parabola max | mean / parabola mean | near bed (z/H < 0.2) / log law | mean / log-wake mean |
|---|---|---|---|---|---|---|
| SHYFEM k-eps (`iturb=2`) | 20 | 0.314 | 0.99 | 1.11 | **1.51** | **1.37** |
| SHYFEM k-eps (`iturb=2`) | 40 | 0.297 | 0.95 | 1.07 | **1.52** | **1.32** |
| GOTM as shipped (CCH02 + GLS gen) | 20 | 0.411 | 0.73 | 0.76 | 0.74 | 0.94 |
| GOTM as shipped | 40 | 0.415 | 0.74 | 0.78 | 0.76 | 0.96 |
| GOTM standard k-eps (first order, cmu=0.09) | 20 | 0.393 | 0.78 | 0.80 | 0.81 | 0.99 |
| GOTM standard k-eps | 40 | 0.397 | 0.79 | 0.82 | 0.84 | 1.01 |
| GOTM k-eps with CCH02 stability | 20 | 0.394 | 0.78 | 0.81 | 0.81 | 0.99 |
| GOTM k-eps with CCH02 stability | 40 | 0.397 | 0.79 | 0.83 | 0.83 | 1.02 |

The log-law depth-mean velocity is 0.368 m/s. SHYFEM's k-epsilon is 15%
below it, because its near-wall viscosity is too large. The GOTM runs are
7–12% above it.

Profile at 20 layers, in cm²/s (parabola peak 223 cm²/s):

| z/H | parabola | SHYFEM k-eps | GOTM shipped | GOTM k-eps | GOTM k-eps CCH02 |
|---|---|---|---|---|---|
| 0.95 | 42 | 63 | 38 | 28 | 29 |
| 0.75 | 167 | 173 | 139 | 142 | 144 |
| 0.55 | 221 | 216 | 164 | 173 | 174 |
| 0.35 | 203 | 217 | 145 | 158 | 158 |
| 0.15 | 114 | 164 | 84 | 92 | 92 |
| 0.05 | 42 | **91** | 33 | 36 | 36 |

SHYFEM's k-epsilon profile is skewed toward the bed: 2.1x the log law at
z/H = 0.05.

## Venice, with GOTM switched to standard k-epsilon

The 6-hour `venlag_smoke` (a cold start, so these are early-adjustment
values rather than a spun-up state) was run three ways: GOTM as shipped, SHYFEM
k-epsilon, and GOTM standard k-epsilon. The eddy viscosity was compared at
06:00 over the 2403 nodes with at least 4 layers. Values are medians, with
the interquartile range in brackets.

| ratio | under the surface layer | above the bed |
|---|---|---|
| SHYFEM k-eps / GOTM shipped | 1.96 [1.39–3.60] | 2.09 [1.36–2.83] |
| GOTM standard k-eps / GOTM shipped | 1.30 [1.07–1.51] | 1.21 [1.01–1.39] |
| SHYFEM k-eps / GOTM standard k-eps | 1.70 [1.21–2.49] | 1.80 [1.21–2.39] |

The original "2x" is reproduced. Switching GOTM's closure accounts for
about a fifth of it.

## SHYFEM k-epsilon's wall treatment

Two inconsistencies are in `src/shyfem/turbulence.f90` (`keps_shell`) and
`src/shyfem/kepsilon.f90` (`keps`). They were measured with a diagnostic
build (`channel_turb/keps_diag.patch`, an environment switch). **The
diagnostic build is not merged.**

1. **The wall stresses come from hard-coded drag coefficients.**
   `keps_shell` sets `taub = rho0 * cb * u_bot^2` and
   `taus = 1.225 * cd * |wind|^2` with `cb = cd = 2.5e-3`. This ignores
   the model's bottom friction (`ireib`/`czdef`) and wind drag
   (`iwtype`/`dragco`). In the channel it gives k-epsilon a bottom friction
   velocity of 0.0109 m/s, half the 0.0222 m/s the momentum equation uses.
   Its wall values `k = u*^2/sqrt(cmu)` and `eps = u*^3/(kappa dh)` are
   therefore built on the wrong u*. GOTM's bottom u* is wrong too, 0.70x,
   because of the roughness mismatch under "Other findings". But GOTM's
   Neumann wall conditions make it insensitive to that.
2. **The epsilon wall value is imposed at the wall interface with
   distance dh.** The value `eps = u*^3/(kappa dh)` is set on the bed
   interface itself (Dirichlet), using the full bottom-layer thickness as
   the distance. GOTM instead uses flux (Neumann) conditions with a
   roughness length.

Measured effect on the near-bed ratio (log law = 1), from the diagnostic
build:

| SHYFEM k-eps variant | 20 layers | 40 layers |
|---|---|---|
| as merged | 1.51 (steady) | 1.52 (steady) |
| momentum-consistent u* only | 1.52 (steady) | 1.24, **not steady** (successive hourly dumps differ by 62%) |
| plus wall distance dh/2 + z0 | 0.88, **not steady** (21%) | **blew up** (water level collapsed, "no layer in element") |

What the measurements support:

- **The hard-coded u\* is not what makes the near-bed value 1.5x.**
  Giving k-epsilon the momentum-consistent u* leaves the 20-layer near-bed
  ratio unchanged (1.51 → 1.52, still steady). It is still a real
  inconsistency: it also governs the surface stress, through the
  hard-coded `cd` instead of the model's `iwtype`/`dragco`.
- **The excess sits in the epsilon wall condition.** The near-bed ratio is
  the same at 20 and 40 layers (1.51/1.52). That argues against a simple
  "distance = dh" scaling error, and toward the Dirichlet epsilon value
  imposed on the wall interface itself. Moving that value to dh/2 + z0
  removes the excess (0.88) but makes the run unsteady, and at 40 layers it
  blows up. The data does not pin down the mechanism further than "the
  epsilon wall condition: its placement and value".
- **Stability is fragile at 40 layers.** There, the run with consistent u*
  never settles. A flux-type wall condition, as GOTM uses, is the likely
  route. Either way it is a results-changing redesign.

## Other findings

- **GOTM's bottom roughness ignores `czdef` under `ireib=6`.** `gotm_shell`
  uses `z0bk`, which only `ireib=9` (fluid mud) sets. Otherwise it stays
  at `z0bini = 9e-4 m`. So the momentum equation uses z0 = 5 mm
  while GOTM uses 0.9 mm. Setting GOTM's z0 from `czdef` changed nothing
  measurable here (ratio 0.78 → 0.78), because GOTM's Neumann wall
  conditions are insensitive to it. It remains an inconsistency.
- **SHYFEM's k-epsilon constants are internally consistent.** The neutral
  `cmu = cmu0^4 = 0.0957`, and `sigma_eps = 1.08` satisfies
  `kappa^2 = (c_eps2 - c_eps1) sigma_eps sqrt(cmu)` for kappa = 0.4.
  GOTM's standard set (cmu = 0.09, sigma_eps = 1.3) implies kappa ≈ 0.43
  while its wall conditions use 0.4. That is a known feature of the
  standard constants, and not what drives the gap.
- **GOTM is 15–20% low against the log law near the bed**, improving
  slightly with resolution (0.81 → 0.84 from 20 to 40 layers).

## Decisions for the owner (no code changed)

1. Whether to make `keps_shell` take its wall stresses from the model's
   actual friction and wind stress instead of the hard-coded `cb`/`cd`.
   This needs a different epsilon wall condition to stay stable.
2. Whether to recommend GOTM over `iturb=2` for 3D runs until then. Near
   the bed, GOTM is 0.8–0.85x the log law and SHYFEM k-epsilon is 1.5x.
   Over the full depth, GOTM is within 6% of the log-wake profile and
   SHYFEM k-epsilon is 32–37% high.
3. Whether the test-case namelists should keep their second-order
   configurations, or say in the file what they run, so that "GOTM" is not
   read as "k-epsilon". (Decided 2026-10-18: keep them, and add a header
   to each namelist saying what it configures.)
4. Whether `gotm_shell` should take its bottom z0 from `czdef` under
   `ireib=6`. That is consistent, and negligible in effect here.

## Reproduce

```
cd testcases/examples/channel_turb
./run_all.sh            # builds the grid and STRs, runs 8 cases, prints the table
# diagnostic variants: apply keps_diag.patch to a scratch tree, rebuild, set
# SHYFEM_KEPS_DIAG (1 = momentum u*, 2 = wall distance dh/2+z0, 4 = GOTM z0 from czdef)
```

## References

Absi, R. (2021). Reinvestigating the parabolic-shaped eddy viscosity
profile for free surface flows. *Hydrology*, 8(3), 126.
https://doi.org/10.3390/hydrology8030126
