# F08 — weutro within-layer light averaging: decision brief

**Status: OWNER DECISION REQUIRED (not a code defect — a modeling choice)**
Prepared 2026-07-22. Supersedes the one-line roadmap escalation of 2026-07-21.

## TL;DR

weutro's `weutro_light` subroutine currently evaluates the phytoplankton
light-limitation factor at the **top of each model layer only** — it does not
average the light over the layer thickness. A more accurate depth-averaged
(Di Toro) formula is present in the same routine but commented out. Turning it
on is a **2-line change in isolation**, but those same two lines also re-arm a
vertical light *cascade* that would **double-count** the between-layer
attenuation `bio3d` already applies in 3D runs. There is no flag in weutro to
tell 2D (cascade wanted) from 3D (cascade must stay dead), so a safe fix is a
small coupled `bio3d`↔`weutro` change, not a one-liner. **Nobody should flip
this without deciding which light model is intended and validating against eco
data — hence this brief.**

## The exact code

`src/contrib/ecological/weutro/weutro.f90`, subroutine `weutro_light`
(around line 1830):

```fortran
      temp1 = ske * h                            ! depth-averaged (OFF)
      temp1 = ske                                ! top-of-layer only $WRONG_FORMULA  <-- ACTIVE
      temp2 = iinst / is2
      temp2 = RLGHTS(ISEG,2) * iinst / is2       ! light attenuation $LGA          <-- ACTIVE
      temp3 = exp ( - temp1 )

      RLGHTS (ITO, 2) = RLGHTS (ISEG, 2)*TEMP3   ! vertical cascade to next segment

      RLIGHT = (expon/temp1) * ( exp(-temp2*temp3) - exp(-temp2) )  ! Di Toro depth-avg (OFF)
      RLIGHT = temp2*temp3*exp(1-temp2*temp3)    ! Steele point value $2D_FORMULA   <-- ACTIVE
```

Fortran executes the LAST assignment, so the active model is:
`temp1 = ske` (no depth), Steele's point formula evaluated at the layer top.
`ske` includes algal self-shading `KESHD` + background `KESG`.

## The physics, and why it's entangled

Two distinct vertical light effects:

1. **Between-layer attenuation** (surface → top of layer *l*). In 3D this is
   supplied EXTERNALLY by `bio3d.f90:562`:
   `qrad_l = qrad * exp(-ke_bg*depth_top)` — Beer-Lambert with **background
   extinction only** (no algal self-shading), passed to weutro as the incident
   light. weutro's own `RLGHTS(ITO,2) = RLGHTS(ISEG,2)*temp3` cascade line did
   this in the old 2D box model by chaining boxes; in 3D that cascade is dead
   and **must stay dead** (finding F30, oracle-verified — re-arming it
   double-counts bio3d).

2. **Within-layer averaging** (top of layer → bottom, thickness *h*). This is
   what F08 is about, and it is genuinely MISSING: the active code takes the
   point value at the layer top. The `temp1 = ske*h` + `(expon/temp1)*(...)`
   pair is the Di Toro depth-integrated limitation factor.

The trap: flipping `temp1 = ske` → `ske*h` fixes (2) but also changes `temp3`
(`= exp(-ske*h)`), which feeds the cascade line — so it silently re-arms (1)
and double-counts. That is the coupling the fix must break.

## Options

**A — Do nothing (accept the current model).** The top-of-layer Steele value
with bio3d's between-layer Beer-Lambert is a coherent, documented model
(bio3d.f90:555-560 spells it out). It slightly overestimates growth in thick
layers (uses the brightest light in the layer). Zero risk. This is the honest
default if no eco-validation campaign is planned.

**B — Add within-layer averaging, cascade-safe (recommended if F08 is wanted).**
Compute the Di Toro depth-averaged `RLIGHT` from `ske*h`, but keep the cascade
line off in 3D. Concretely: a `logical, save :: bexternal_vertical` flag in
weutro, set true by bio3d at init (a setter next to `get_weutro_ke`); when
true, use `ske*h` for RLIGHT **and skip** `RLGHTS(ITO,2) = ...`; when false
(pure 2D box), keep today's behavior. ~15 lines across weutro.f90 + bio3d.f90.
**Blocker: needs an eco owner to (a) confirm Di Toro is the intended
within-layer model and (b) sign off after validating against data** — the
`weutro_box` 3D light gate (`check_light.sh`) only checks that deep < surface,
which BOTH models satisfy, so it cannot discriminate. A new gate asserting the
depth-averaged magnitude would be part of this option.

**C — Also fold algal self-shading into the between-layer light.** bio3d uses
`ke_bg` only; a fuller model would attenuate between layers with `ke_bg + KESHD`
too. Larger change, more validation, out of scope for F08 — noted for
completeness.

## Recommendation

Ship **A** as the standing decision unless/until an eco-model owner commits to
a validation campaign, in which case do **B**. Do not attempt B blind: there is
no 3D eco reference dataset in the repo, and a wrong within-layer model changes
every phytoplankton growth rate silently. The code is safe and coherent today.

## Verification of current state (2026-07-22)

- weutro compiles and the `weutro_box` suite is green (2D/3D/light/settle/eco/
  restart/omp/mercury gates) — the current top-of-layer model is the tested one.
- bio3d between-layer path confirmed at `bio3d.f90:562`; weutro cascade confirmed
  dead in 3D (F30).
