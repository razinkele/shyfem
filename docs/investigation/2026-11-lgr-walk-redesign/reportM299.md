## M299 report (issue #299): measurement only, base origin/main 3d3cbc21. No commits, no PR, no push.

**Answer.** Vertical advection alone makes the deficit, and most of it comes from how the tracker applies vertical velocity in the bottom layer. `track_xi_get_vertical` gives one layer-mean `w` for the whole layer, so it stays non-zero right down to the bed. Under the steady upwelling at the top of the bottom layers in the 7–20 m slope columns, every bottom-layer particle rises at that speed and the band next to the bed empties. A throwaway variant makes `w` linear in z and zero at the bed. It takes the bottom 5 % at 24 h from **0.46 to 0.89** with K ≈ 0, and from **0.49 to 0.89 with GOTM**. A smaller second effect sits at depth steps, and two residuals remain unexplained.

**Setup**
- Work tree `/home/razinka/wt-m299`, detached at 3d3cbc21, OpenMPI build (`libmpi.so.40`). Serial runs, OMP 1 thread, everything under `nice -n 10`.
- The STR comes from m286 `mkstr.py`: `mm_hyd_41`, tilt removed, one day, both boundaries `ibtyp = 0`, wind/qflux/rain kept, `ilagr = 3`, `nbdy = 2000`, `ipvert = 20` (39,960 particles), output every hour.
- I added a kind `k0`: `iturb = 0`, `diftur = 0.`, `vistur = 1e-3`.

Caveats:
- **"K = 0" is not zero.** `lag_vdiff_ele` adds a hard-coded `difmol = 1e-6`, about 0.4 m rms per day. It can only smooth. Seeds 1 and 2 come out near-identical at K ≈ 0 (0.605 / 0.606), so they are not independent replicates. The pooled particle counts in brackets below overstate n by about 2×; the small classes are thin ("thin bottom layer" 43 particles per output, "full" 5).
- **The flow is not byte-identical to the K controls.** `hydro.shy` of k0 against kc4 agrees to 1e-4 (`shyelab -diffeps 1e-4` passes, 1e-5 fails). This is T/S feedback through evaporation and heat flux; `ibarcl = 3` has no baroclinic term.
- **The base change does not matter.** At 3d3cbc21, kc3, kc4 and the GOTM run `gc_s1` reproduce the issue and m286 numbers exactly (χ² 76 / 134 / 221.1; bottom 5 % at 24 h 0.86 / 0.65 / 0.49).

### 1. Advection alone (closed basin, forced flow)

Release-column weight; 5 % and 15 % are relative-depth bins of each particle's current column.

| run | χ² 12–24 h | bottom 5 % 12–24 h | bottom 15 % 12–24 h | bottom 5 % at 24 h | bottom 15 % at 24 h | χ² at 24 h |
|---|---|---|---|---|---|---|
| K≈0 (`k0`) seed 1 | 302.6 | 0.605 | 0.831 | 0.46 | 0.72 | 575 |
| K≈0 seed 2 | 306.0 | 0.606 | 0.831 | 0.46 | 0.71 | 574 |
| K = 1e-4 | 133.6 | 0.801 | 0.892 | 0.65 | 0.80 | 319 |
| K = 1e-3 | 75.9 | 0.924 | 0.947 | 0.86 | 0.89 | 160 |
| GOTM (`gc_s1`, this base) | 221.1 | 0.638 | 0.856 | 0.49 | 0.75 | 450 |
| K = 1e-2 (m286 seeds 1 / 2) | 32 / 39 | 0.99 / 0.97 | 0.98 / 0.97 | 1.00 / 0.98 | 0.95 | 50 / 47 |

Hourly values for K≈0, hours 1 to 24:
- **Bottom 5 %, seed 1:** 1.00 0.99 0.97 0.93 0.90 0.87 0.83 0.79 0.78 0.77 0.74 0.74 0.73 0.72 0.70 0.68 0.63 0.61 0.57 0.55 0.53 0.49 0.47 0.46. Seed 2 matches to ±0.01.
- **Bottom 15 %, seed 1:** 1.00 1.00 1.00 0.99 0.99 0.97 0.96 0.95 0.94 0.93 0.93 0.92 0.91 0.91 0.90 0.89 0.88 0.85 0.83 0.78 0.76 0.74 0.72 0.72.
- **χ², seed 1:** 0 1 3 9 19 33 49 67 76 82 100 107 117 126 152 182 228 276 328 372 421 510 540 575.

The deficit is largest at K ≈ 0, slightly worse than GOTM, so advection alone makes it and mixing only fills it back.

### 2. Where it sits (K ≈ 0, both seeds pooled)

Measure: particle weight per layer against layer volume (thickness × element area), divided by the column's own mean density.

**It is the bottom layer only.** In the 7–20 m columns (339 elements):

| layer from bottom | 1 h | 3 h | 6 h | 9 h | 12 h | 18 h | 24 h | mean 12–24 h |
|---|---|---|---|---|---|---|---|---|
| bottom layer | 1.03 | 1.00 | 0.93 | 0.81 | 0.79 | 0.54 | 0.35 | 0.556 |
| one above | | | | | | | | 1.19 |
| two above | | | | | | | | 1.18 |
| three above | | | | | | | | 1.12 |
| four above | | | | | | | | 1.10 |

By absolute layer, 15–20 m is worst at 0.58 and 12–15 m is 0.92. The particles move into the 2–3 layers just above.

**Inside the bottom layer** (10 bins from the top of the layer to the bed, 12–24 h):
- **7–20 m:** 2.20 1.89 1.63 1.30 1.00 0.71 0.52 0.33 0.24 0.18. It falls almost linearly to empty at the bed.
- **Same, only elements whose bed `w` is exactly 0** (no node deeper than the element): 3.08 2.59 1.58 1.38 0.88 0.33 0.16 0 0 0. So the nodal `w` at the bed is not needed to produce it.
- **≥ 20 m:** bottom layers are thick (median 6.7 m). The layer as a whole is 0.96, but the bed bin is 0.27: a thin hole at the bed.
- **3–7 m:** declines to 0.46, then 1.01 in the bed bin, a pile at the bed.
- No output particle sits at exactly z = 1, because the walk moves them off.

**Classes** (bottom layer, 7–20 m, 12–24 h). Bathymetry in this grid is per element, so the bed is a staircase.

| class | ratio |
|---|---|
| bottom layer < 0.5 of regular thickness | 0.24 |
| bottom layer 0.5–1 of regular | 0.54 |
| bottom layer merged (`ilytyp = 3`) | 0.72 |
| a neighbour lacks my bottom layer (a wall at a depth step) | 0.37 |
| no such neighbour | 0.71 |
| no node deeper than the element | 0.42 |
| a node deeper | 0.58 |
| largest step down to a neighbour > 1.82 m | 0.50 |
| largest step down ≤ 1.82 m | 0.60 |

**Where it starts.** At 6 h the ratio is 0.67 in the elements with the largest bottom-layer excursion (∫|w| dt / layer thickness over 24 h > 7.6, upper third). It is 0.71 in wall elements with net inflow through the wall sides. Everything else is at 0.93 or above.

**Vertical velocity.** In 336 of 339 elements (7–20 m), the top of the bottom layer has net upward `w`. The median is 13.8 m/day (about 1.6e-4 m/s). The tracker's layer-mean ∫|w| dt is 11.4 m/day against a median bottom-layer thickness of 2.1 m.

**Free surface ruled out by location:** layers 2 and below are static, and ζ agrees within an element to 1e-5 m.

### 3. Hypothesis and tests

**Hypothesis (code reading).** In `lagrange_vertical.f90`, `track_xi_get_vertical` averages the interface velocities into one layer-mean `w`. In the bottom layer that is (w at top + w at bed)/2, which is w_top/2 when no node is deeper. `track_xi` moves every particle in the layer at that speed, right down to the bed. The side fluxes (`flx3d_k`) and the true flow both have w → 0 at the element's bed.
- Under upwelling, the band next to the bed empties and nothing refills it from below.
- A horizontal crossing keeps z, so the empty band is carried into the next bottom layer.
- Constant w_top/2 with uniform side inflow predicts a density of 2 × (height above bed / layer thickness), about 1.9 at the top bin and 0.1 at the bed. The measured 7–20 m profile runs 2.20 to 0.18.
- A second, minor defect: after the layer switch at the start of `track_xi` (old lines 360–367), the old layer's `w` and `hd` are kept for the rest of the call.

**Test (a), uniform 1 m levels, no code change.** The flow differs from the default-level runs. Bottom-layer thickness in metres falls, and the deficit falls with it:

| quantity | default levels | 1 m levels |
|---|---|---|
| χ² 12–24 h | 303 | 185 |
| bottom 5 % 12–24 h | 0.605 | 0.738 |
| bottom 5 % at 24 h | 0.46 | 0.61 |
| bottom 5 %, 7–20 m columns | 0.11 | 0.31 |
| bottom 5 %, ≥ 20 m columns | 0.66 | 0.81 |
| bottom 5 %, 3–7 m columns (same layers in both) | 0.538 | 0.537 |

**Test (b), throwaway variant 1 (never committed, switched on by `SHYFEM_D299_WLIN=1`).** In the bottom layer only, `w` is linear in z, from the element-mean interface `w` at its top to 0 at the bed, integrated exactly. I did not write a numeric prediction before this run, only the expectation that the deficit would go away. The same binary without the variable gives particle output identical to the original binary (999,000 records compared, 0 differ).

| run | χ² 12–24 h | bottom 5 % 12–24 h | bottom 15 % 12–24 h | bottom 5 % at 24 h | bottom 15 % at 24 h | χ² at 24 h |
|---|---|---|---|---|---|---|
| K≈0 seed 1 | 107.1 (was 302.6) | 0.957 | 0.953 | 0.89 (was 0.46) | 0.89 | 239 |
| K≈0 seed 2 | 109.8 | 0.963 | 0.954 | 0.89 | 0.89 | 248 |
| K = 1e-4 | 78.5 (was 133.6) | 0.966 | 0.957 | 0.91 (was 0.65) | 0.90 | 203 |
| GOTM | 60.4 (was 221.1) | 0.963 | 0.960 | 0.89 (was 0.49) | 0.90 | 161 (was 450) |

- **7–20 m columns, bottom 5 %:** 0.78 / 0.82 (was 0.11); GOTM 0.84 (was 0.19).
- **≥ 20 m columns, bottom 5 %:** 0.98 (was 0.66).
- **Profile inside the bottom layer (7–20 m):** 1.06 1.08 1.04 1.07 1.03 0.94 0.90 0.88 0.88 1.11, now flat.
- **Bottom layer, 7–20 m, at 3 / 6 / 9 h:** 0.998 / 0.997 / 0.965 (was 1.001 / 0.930 / 0.809).

The variant bundles three changes: linear `w`, zero `w` at the bed, and `hd` recomputed. The "no deeper node" profile above shows the layer mean alone produces the hole.

**Test (c), throwaway variant 2 (`SHYFEM_D299_WLIN=2`).** It makes `w` linear in every layer, with interface-consistent layer switching. It is no better than variant 1: χ² 101 / 101; bottom 5 % at 24 h 0.82 / 0.84.

### Residuals (outside the main mechanism)

**R1, depth-step walls (measured).** With variant 1, the 7–20 m bottom layer is 1.00 in elements with no wall side and 0.65–0.83 in wall elements. The wall elements order by net wall flux: (out − in) over the wall sides divided by bottom-layer volume, over 24 h:
- below −2.5: 0.65;
- between −2.5 and 0.2: 0.72;
- above 0.2: 0.83.

In 3–7 m, wall elements with net outflow through the walls show an excess (1.05–1.15) and those with net inflow a deficit (0.35–0.55).

Measured with the original tracker:
- In 7–20 m wall elements, `flux3d` over the wall sides carries 9.0e7 m³ in and 6.4e7 m³ out per day. Their bottom-layer volume is 4.75e7 m³.
- `track_xi_side_test` put a particle back at a wall 7,325 times in the bottom layer and 7,233 times above it per day in 7–20 m (two seeds). In 3–7 m it was 64,988 and 32,160.

The cause, from code reading only: `flx3d_k` / `make_fluxes_2d` close the ring of section fluxes around a node per layer as if every sector existed. A sector missing in that layer (a shallower element) passes flux straight through, so a side that is a z-level wall gets a flux. Inflow through a wall brings no particles; outflow through it is blocked by the put-back.

**R2, net-downwelling bottom layers without walls (not explained).**
- In 3–7 m (148 elements) they stay at 0.51 with the original tracker, 0.51 with variant 1 and 0.53 with variant 2.
- In ≥ 20 m (110 elements), 66 of them are on the closed former open boundary (R3).
- A candidate from code reading, untested: the `track_xi_get_flux` special cases for an element with only outflow (`in == 0`: exit through the largest-outflow side, `fact = 1`).

**R3, closing a boundary with `ibtyp = 0` (code reading plus log counts).** The kbound nodes still count as external boundary in `flxtype`. So 92 closed sides get `flux3d ≠ 0`, which `track_xi_get_flux` zeroes while writing 248k "material boundary" lines a day (17 MB of log). These are mostly deep elements (median 38 m); only 5 are in 7–20 m. It is a separate small item.

**R4, χ² that none of this touches.** The mid-depth excess (bins 4–7 at about 1.15–1.20) and the top 5 % (0.90–0.95) look the same in the original, the 1 m-level run and both variants. Variant 1's χ² of about 107 at K ≈ 0, against 14–22 in still water, is mostly this. It is unexplained and lies outside the bottom mechanism.

### 4. What a fix would touch (no PR)

- **Main fix (`lagrange_vertical.f90`):**
  - `track_xi_get_vertical` should return the interface velocities (element mean of nodal old+new at the top and bottom of the layer), with 0 at the element's own bed, as `flx3d_k` already does (`qw_bot = 0` at `l = ilhv(ie)`).
  - `track_xi` should take the time to the interface and the new z from the linear profile. This is the exponential solution: a level where w = 0 inside the layer is approached and never crossed.
  - The surface/bed hold and the layer switch should use the velocity at the particle's z, with `hd` and `w` of the new layer.
  - The bottom layer alone captures most of the gain. Variant 2 shows that interior layers add nothing measurable here, and R2 is not addressed by either.
- **Second fix (walls):** a Lagrangian-only copy of the `flx3d_k` / `make_fluxes_3d` path in `lagrange_flux.f90`. Leave `discharge_flux.f90` alone because flux sections share it. The copy would break the per-layer ring at missing sectors (zero flux on wall sides) and redistribute the node's vertical divergence so each remaining chain closes. This is non-trivial.
- **Impact:** every `ilagr = 3` particle file changes. The wall fix would also change `ilagr = 2`.

### Housekeeping

- Before creating the work tree, I ran `git fetch -q origin` in the live repo `/home/razinka/shyfem`. It touched only the shared `.git` refs, but that is one thing beyond `git worktree add`.
- All particle files were deleted after analysis. My scratch folder `/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/m299.ONMJjW` (115 MB) keeps the numbers (`res/`), the STRs, short logs and `d299.txt` files, and the scripts (`py/`).
- The throwaway diagnostic and variant code is saved as a patch, never committed: `/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/m299.ONMJjW/d299_throwaway.patch`. It covers the held-at-bed / lifted / put-back counters, time integrals of `w`, wall-side flux, and variant modes 1 and 2.
- No background processes are left. The work tree was removed with `git worktree remove --force`; `git worktree list` no longer shows `wt-m299`. I ran no gates, so no `partition.*` files were created.
