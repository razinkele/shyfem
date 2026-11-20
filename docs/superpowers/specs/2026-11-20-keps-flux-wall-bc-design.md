# k-epsilon flux (Neumann) wall conditions — design (2026-11-20)

Closes issue #125. Owner decision 2026-11-20: do it now, with GOTM-style
flux conditions (option 1 below).

## Intent and why

SHYFEM's own k-epsilon closure (`iturb=2`, `keps` in
`src/shyfem/kepsilon.f90`, driven by `keps_shell` in
`src/shyfem/turbulence.f90`) gives **1.5x the log-law eddy viscosity near
the bed**, at 20 and at 40 layers, in the neutral open-channel benchmark
(`testcases/examples/channel_turb`, report
`docs/reviews/2026-10-18-keps-vs-gotm-benchmark.md`, PR #124). Over the full
depth it is 32-37% above the log-wake profile; GOTM is within 6%.

The cause is the wall treatment. `keps` imposes **Dirichlet** values on the
wall interfaces themselves:

- `eps(wall) = u*^3 / (kappa * dh)` (full wall-layer thickness as distance, no
  roughness length),
- `k(wall) = u*^2 / sqrt(cmu)`,

with `u*` from hard-coded drag coefficients (`cb = cd = 2.5e-3` in
`keps_shell`). Earlier attempts that stayed Dirichlet failed: moving the eps
value to `dh/2 + z0` removed the excess (0.88) but made the 20-layer run
unsteady and blew up the 40-layer run; a momentum-consistent `u*` alone left
the excess and destabilised 40 layers (issue #125 and its comment).

GOTM uses **flux (Neumann) conditions with a roughness length** for both k
and epsilon. In the benchmark it is 0.81-0.84 of the log law near the bed
and within 6% of the log-wake profile over the full depth. Its
code is in the repo (`src/external/gotm/dissipationeq.F90`,
`turbulence.F90:epsilon_bc/k_bc`, `diff_face.F90`).

## Goals

1. **GOTM parity** in `channel_turb` at 20 **and** 40 layers (owner decision
   2026-11-20, replacing the issue's 0.9-1.1 band): near-bed ratio
   `nut(zb<0.2H)/ana` (from `analyse.py`) in about 0.8-1.1, and full-depth
   `mean/logwake` within about 10% of 1. Today: 1.51/1.52 near-bed,
   1.32-1.37 overall. A faithful port is expected near GOTM's 0.81-0.84.
2. Both channel runs **steady** at the end of the run. **If the 40-layer run
   (or the 20-layer one) is not steady, stop and report** what was built and
   the numbers; do not hunt for stability inside the closure (owner decision
   2026-11-20).
3. `venlag_keps_smoke` (3D Venice, in `fortran-ci.yml`) completes, as do the
   other `iturb=2` cases (`mar_menor/mm_rst_keps_write.str`).
4. MPI and OpenMP behaviour unchanged (a 4-rank run of a k-eps case works).
5. A CHANGELOG entry under `[Unreleased]` saying results change for every
   `iturb=2` run; issue #125 closed by the PR.

## Non-goals

- Wave-breaking TKE injection at the surface (GOTM's `injection` type),
  viscous sublayers, or new closure constants.
- Changing the GOTM path (`iturb=1`) or Munk-Anderson.
- A core release; that is a separate step on the owner's word.
- Fixing the hard-coded `cb`/`cd` wall stresses as such (report decision 1).
  With flux conditions the interior no longer depends on them; see below.

## Anti-goals (a failure even if the ratio is right)

- Any run that is unsteady or blows up at 40 layers.
- A switch that silently changes results without a CHANGELOG entry, or a
  hidden STR option that keeps the old behaviour as the default.
- Breaking restart files. (Checked: `restart.f90` writes no k-eps state for
  `iturb=2`, so there is nothing to break; keep it that way.)
- New module/`save` state in `keps` (see the allocation-caching OMP hazard;
  `keps` is called per node and must stay re-entrant).

## Constraints

- SHYFEM Fortran conventions (`CLAUDE.md`): `implicit none`, `intent`,
  `use mod_physical_constants` for kappa/g, no GOTO, no bare `stop`
  (`shympi_abort_internal`).
- Build and run with OpenMPI (`PATH=/usr/bin:$PATH make ...`); check
  `ldd src/shyfem/shyfem | grep mpi` -> `libmpi.so.40`.
- `keps` grid: k and eps live on **interfaces 0..lmax** (0 = surface,
  lmax = bottom); level `l` (thickness `dh(l)`) lies between interfaces `l-1`
  and `l`. The current solver (`tridagd`) solves rows 0..lmax with Dirichlet
  rows at both walls.
- SHYFEM's own constants stay: `cmu0 = 0.5562` (neutral `cmu = cmu0^4 =
  0.0957`), `sigmae = 1.08`, `sigmak`, `ceps1/2/3` as in `kepsilon.f90`.

## Approaches considered

1. **GOTM-style flux conditions (chosen).** Solve only the interior
   interfaces; the interface next to each wall gets zero k flux and the
   log-law epsilon flux evaluated at the centre of the wall layer, with a
   roughness length. Proven in GOTM, formulas in the repo, insensitive to the
   wall `u*`. Cost: rework of the boundary rows of both equations.
2. **Dirichlet moved off the wall.** Impose log-law k and eps at the first
   interior interface. Smaller change, but this is the family of variants that
   already went unsteady / blew up (the `dh/2 + z0` diagnostic).
3. **Leave it.** Keep recommending GOTM for 3D and close #125 as won't-fix.

The owner chose 1.

## Design

### 1. Interior-only solve with flux rows (in `keps`)

For `lmax >= 3`, the unknowns of both the eps and the k system are the
interior interfaces `1..lmax-1`. The interior rows are unchanged. The two
rows next to the walls change as in GOTM's `diff_face` (Neumann branch),
in SHYFEM's discretisation (row `l` has `aux = dt*dzr(l)`; its link to
interface `l-1` goes through level `l` with `rke(l)*dzk(l)`, its link to
`l+1` through level `l+1` with `rke(l+1)*dzk(l+1)`):

- **Row 1 (surface side):** drop the diffusive link to interface 0 (remove
  `aux*rke(1)*dzk(1)` from `bb(1)`, `aa(1) = 0`) and add the flux into the
  column: `rr(1) += aux * F_s`.
- **Row lmax-1 (bottom side):** drop the link to interface lmax (remove
  `aux*rke(lmax)*dzk(lmax)` from `bb(lmax-1)`, `cc(lmax-1) = 0`) and add
  `rr(lmax-1) += aux * F_b`.

Fluxes, positive into the water column (GOTM `epsilon_bc`, Neumann,
logarithmic):

- epsilon: `F = cmu0**4 * ki**2 / ( sigmae * (zi + z0) )` with
  `zi = 0.5*dh(wall level)` (centre of the wall layer), `ki` = k at the
  adjacent interior interface (k(1) or k(lmax-1)) **from the previous time
  step** (SHYFEM solves eps before k, GOTM the other way round), and `z0` the
  surface (`z0s`) or bottom (`z0b`) roughness length.
- k: zero flux (`F_k = 0`): only the link is dropped.

The solve is over rows `1..lmax-1` (`tridagd` with offset 1 and
`lmax-1` unknowns). The negative-source handling (`forc < 0` into `bb`)
stays as it is for the interior rows, including rows 1 and lmax-1.

### 2. Wall values after the solve

The wall interfaces are not unknowns any more. Fill them after each solve,
GOTM-style ("for output and the limiter"):

- `k(0) = k(1)`, `k(lmax) = k(lmax-1)` (zero gradient, consistent with zero
  flux),
- `eps(0) = cmu0**3 * k(0)**1.5 / (kappa * z0s)` and
  `eps(lmax) = cmu0**3 * k(lmax)**1.5 / (kappa * z0b)` (log-law value at
  distance z0).

The existing limiter loop (`kmin`, eps limits) then runs over `0..lmax` as
today. The builder checks every consumer of the wall values (`rkm(0)`,
`rkm(lmax)`, `visv/difv` at the wall interfaces, restart output) and states
in the PR that none of them changes behaviour in a way the momentum or scalar
equations see.

### 3. Roughness lengths

`keps` gains two arguments, `z0s` and `z0b` (metres, `intent(in)`).
`keps_shell` computes them per node **the way `gotm_shell` already does**
(same file): `z0s` from `z0sk(k)` or Charnock `charnock_val*u_taus**2/g`,
clamped by `z0smin`, **with `u_taus` from the model's own wind stress**
(`sqrt(sqrt(tauxnv**2 + tauynv**2))`, as `gotm_shell` line ~492), not from
`keps_shell`'s hard-coded `cd` (my call, 2026-11-20: consistent with the
model and with GOTM, and it lets the helper be shared); `z0b` from `model_bottom_z0` under `ireib == 6` (PR
#127), else `z0bk(k)`, clamped by `z0bmin`. Prefer one shared helper over a
copy if it stays simple; otherwise replicate the few lines with a comment
pointing at `gotm_shell`.

### 4. What happens to the wall stresses

With flux conditions the interior solve no longer uses `taus`/`taub`, and
Charnock's `z0s` takes the model's wind stress (section 3). They remain
needed only for the `lmax < 3` fallback (below). The hard-coded `cb`/`cd`
therefore no longer affect `lmax >= 3` columns at all; replacing them in the
fallback is out of scope (non-goal). The PR and CHANGELOG say this.

### 5. Very shallow columns (`lmax < 3`)

With fewer than two interior interfaces the flux rows have nothing to act
on. Keep today's Dirichlet formulation for `lmax <= 2` unchanged (the
builder may choose a cleaner equivalent, but must not change results for
those columns and must say what it did).

## Verification

1. **Benchmark:** `testcases/examples/channel_turb/run_all.sh` then
   `analyse.py`, before and after. Report the table rows for `keps_20` and
   `keps_40` (max, mean, near-bed `nut/ana`, `mean/logwake`) next to GOTM's
   rows. Goal 1 holds at GOTM parity as defined there.
2. **Steadiness:** compare the last two hourly profiles of each `keps` run
   (the method the 2026-10-18 report used: "successive hourly dumps differ by
   N%"). Steady means they differ by less than 2% (builder may tighten).
3. **Regression gates** (OpenMPI build, `CLAUDE.md`): the fortran-ci battery
   (`mm_hyd_00`, beach, assim, restart cycle, `venlag_smoke`,
   `venlag_keps_smoke`), `mm_rst_keps_write.str`, and one 4-rank MPI run of a
   k-eps case. GOTM and non-`iturb=2` cases must be byte-identical to before.
4. **OpenMP:** one k-eps run with `nomp = -1` and the "used OMP threads: N"
   line checked (memory: `nomp` defaults to 1 thread).
5. CI (`fortran-ci.yml`) green.

### 6. The `iturb=2` start-up warning

`turb_closure` (`src/shyfem/turbulence.f90`, about lines 104-110) warns
that `iturb=2` is 1.5x the log law near the bed and recommends GOTM (#126).
Reword it to the new benchmark numbers, or remove it if k-eps now matches
GOTM; say which in the PR.

## Documentation

- `CHANGELOG.md` `[Unreleased]`, core section: "Model, turbulence (changes
  results for `iturb=2` runs): flux wall conditions ..." with the before/after
  benchmark numbers.
- The 2026-10-18 benchmark report gets a dated section with the new results.
- The PR closes #125.

## Left to the builder

- Whether the roughness helper is shared with `gotm_shell` or replicated.
- The exact steadiness threshold, if 2% proves too loose or too strict for
  the channel's own variability (state the choice and why).
- How the `lmax <= 2` fallback is expressed, within section 5's rule.
- Diagnostic output (e.g. a one-off debug print of `F_s`, `F_b`) during
  development; none left in the final code.
