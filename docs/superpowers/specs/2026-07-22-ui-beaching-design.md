# Beaching UI slice — design spec

**Date:** 2026-07-22
**Status:** approved (design)
**Scope:** first slice of the sequenced UI backlog (beaching → heat-flux `imetout` → assimilation)

## Purpose

Expose the Eulerian tracer-beaching feature from core PR #60 in the SHYFEM
Shiny UI so users can enable it and set its rates from the physics page,
instead of hand-editing the `.str` file.

Core interface (already shipped, `src/shyfem/beaching.f90`, `def_para.f90`):

- `ibeach` (`$para`, integer, default 0) — beaching/burial mode:
  - `0` = off
  - `1` = Curonian lagoon rate preset
  - `2` = Danube delta rate preset
  - `3` = rates taken from the STR arrays `beachrate`/`burryrate`
- `beachrate` / `burryrate` (`$para`, per-area-code arrays, default 0) —
  surface-loss (beaching) and bottom-loss (burial) fractions per timestep.
  Used only when `ibeach = 3`. Documented common usage is a single scalar
  value that the core replicates across every area code
  (`testcases/examples/mar_menor/mm_hyd_beach_str.str`).

Eulerian beaching only does anything when tracers are active (`iconz > 0`);
it accumulates per-node beach/burial stores written at the `conz` output
frequency.

### Not to be confused with `lbeach`

The UI already exposes `lbeach` ("Beaching probability") in the IBM /
Lagrangian section (`physics.py`, near `ldecay`/`ipvert`). That is the
**Lagrangian particle** beaching probability — a different feature. This
slice does **not** touch `lbeach`; the new controls are clearly the
**Eulerian tracer** path and live in the Tracers panel.

## Scope decision: scalar rates (Option A, approved)

`beachrate`/`burryrate` are per-area-code arrays in the core, but this
slice represents each as a **single scalar** `input_numeric`, matching the
documented common usage and every other numeric widget on the page. The
core applies a single supplied value to all area codes.

**Out of scope (documented future extension):** a per-area-code array
editor (repeating add-a-row widget keyed by area code). That is the same
new-widget-pattern complexity as the assimilation station-list, which is
deliberately sequenced last. A user needing true per-area arrays hand-edits
the `.str` (advanced, rare).

## Changes

Three source files plus tests, all following existing patterns.

### 1. `shyfem_ui/services/parser_str.py`

Add three `_p()` metadata entries in the `para` param group, next to
`idecay` (~line 471):

```python
"ibeach": _p("Tracer beaching/burial mode", "int", 0, "",
             "0=off,1=Curonian,2=Danube,3=STR rates"),
"beachrate": _p("Beaching rate (surface loss/step)", "float", 0.0, "",
                "used when ibeach=3"),
"burryrate": _p("Burial rate (bottom loss/step)", "float", 0.0, "",
                "used when ibeach=3"),
```

(Spelling `burryrate` matches the core parameter name exactly — do not
"correct" it to `burialrate`.)

### 2. `shyfem_ui/pages/physics.py`

**(a) Register the params** in the `tracers` entry of `PHYSICS_PANELS`
(~line 152) so the existing save loop reads and writes them (this is what
prevents a dead/unwired control):

```python
"params": {
    "iconz": "para",
    "iage": "para",
    "idecay": "para",
    "conref": "para",
    "chpar": "para",
    "ibeach": "para",
    "beachrate": "para",
    "burryrate": "para",
    ...
},
```

**(b) Render the widgets** in `panel_tracers()` after the `idecay` row:

- `ibeach` → `ui.input_select` with choices
  `{"0": "0 - Off", "1": "1 - Curonian preset", "2": "2 - Danube preset",
    "3": "3 - Rates from STR"}`, `selected` from current params.
- `beachrate` / `burryrate` → `ui.input_numeric`, `min=0`, `step=0.01`,
  `value` from current params. Label text notes they apply only in mode 3;
  presets 1/2 carry their own built-in rates.

Always-visible (no `conditionalPanel` — the page does not use that pattern;
the helper text carries the "mode 3 only" note). Values are auto-typed by
the existing `_read_input_and_set` (int for `ibeach`, float for the rates).

### 3. Tests

- `tests/test_parser_str.py` — assert the three params parse from a `$para`
  block with expected types/defaults (mirror an existing `idecay`/`iconz`
  parse assertion).
- `tests/test_physics_page.py` — assert `panel_tracers()` source renders
  `ibeach`/`beachrate`/`burryrate` inputs, and that a save round-trip
  (`set_param` via the panel registry) writes them back into an `StrFile`.
  Follow the existing physics-page render/round-trip test style.

## Data flow

1. Load: `build_panel_params(str_data, "tracers")` reads current `$para`
   values (or `COMMON_PARAMS` defaults) → widget `value`/`selected`.
2. Edit: user changes `ibeach`/rates in the Tracers panel.
3. Save (`save_btn`): the `PHYSICS_PANELS["tracers"].params` loop calls
   `_read_input_and_set` → `sf.set_param("para", <name>, <value>)` → written
   to the `.str` on serialize.

No new write-back mechanism; the params ride the existing generic path.

## Error handling / edge cases

- Non-numeric or empty rate input: `_read_input_and_set` skips empty and
  falls back to string on parse failure (existing behavior); rates default
  to 0, which is inert.
- `ibeach` out of range (e.g. hand-edited `4`): the UI select only offers
  0–3; the core already aborts cleanly (`shympi_abort_internal`) on unknown
  `ibeach`, so no UI-side validation is added.
- Beaching with `iconz = 0`: harmless — the core beaching path is a no-op
  without tracers. No UI gating added (keeps the slice small); a future
  polish could grey out the controls when `iconz = 0`.

## Testing / validation

- `pytest tests/test_parser_str.py tests/test_physics_page.py`
  (with `CONDA_PREFIX=""` per project convention).
- Full UI suite green (`pytest tests/`).
- `ui-security-reviewer` pass (auth/path/reactive failure modes) before PR,
  though this change is param-metadata + widgets only (no auth/path/DB
  surface).

## Deliverable

One PR (`feat/ui-beaching`) — parser metadata + physics widgets + tests.
UI-only, deploys to laguna via the normal PR → review → deploy path.
