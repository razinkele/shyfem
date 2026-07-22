# Heat-flux `imetout` UI slice — design spec

**Date:** 2026-07-23
**Status:** approved (design; Option B)
**Scope:** slice 2 of 3 in the sequenced UI backlog (beaching ✓ → **heat-flux `imetout`** → assimilation)

## Purpose

Expose the meteo-output selector `imetout` in the SHYFEM Shiny UI so users
can toggle which meteo-forcing streams get written to the meteo output file,
including the heat-flux stream added by core PR #55.

Core interface (`def_para.f90:478` `addpar('imetout',0.)`;
`meteo_forcing.f90:628-644`; digit extraction `bit10.f90`):

`imetout` is a **5-digit decimal**; each digit position (a value >0) enables
one meteo-output stream, verified against `bit10_extract_value(imetout,pos)`:

| position | place  | stream       | vars written |
|----------|--------|--------------|--------------|
| 1        | 1s     | wind         | 4            |
| 2        | 10s    | heat         | 4            |
| 3        | 100s   | rain         | 1            |
| 4        | 1000s  | ice          | 1            |
| 5        | 10000s | heat-fluxes  | 4 (qsens/qlat/qlong) — PR #55 |

Positions 1–5 are the complete set the core reads, so five booleans fully
describe `imetout` — there are no higher digits to preserve. "On" is encoded
by the core as digit value 1 (`bit10_set_pos`); reads test digit `> 0`.

## Approach: Option B (approved) — five checkboxes ↔ one integer

Represent `imetout` as five `input_checkbox`es (wind / heat / rain / ice /
heat-fluxes) that decode from and encode back into the single `imetout`
integer. Chosen over a raw numeric input (Option A) because the digit
encoding is not user-guessable, and over a single heat-fluxes checkbox
(Option C) because composing even one digit needs the same encode/decode
plumbing.

## Changes

### 1. `shyfem_ui/services/parser_str.py`

One `_p()` entry in the `"para"` group (near the heat params):

```python
"imetout": _p("Meteo output streams (bitmask)", "int", 0, "",
              "digits: 1s=wind,10s=heat,100s=rain,1000s=ice,10000s=heat-fluxes"),
```

### 2. `shyfem_ui/pages/physics.py`

**Two pure module-level helpers (unit-tested):**

```python
_IMETOUT_FIELDS = ("wind", "heat", "rain", "ice", "hflx")  # positions 1..5

def _imetout_decode(value) -> dict[str, bool]:
    """Split the imetout integer into the 5 stream flags (digit > 0)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    return {f: (v // 10**i) % 10 > 0 for i, f in enumerate(_IMETOUT_FIELDS)}

def _imetout_encode(flags: dict[str, bool]) -> int:
    """Compose the 5 stream flags back into the imetout integer."""
    return sum(int(bool(flags.get(f))) * 10**i
               for i, f in enumerate(_IMETOUT_FIELDS))
```

**Widgets** in `panel_heat()` (the "Heat Flux" panel), a row of five
`ui.input_checkbox`es under a "Meteo output (imetout)" label, initial state
from `_imetout_decode(params.get("imetout", 0))`. Input IDs:
`imetout_wind`, `imetout_heat`, `imetout_rain`, `imetout_ice`,
`imetout_hflx`.

**Save (composite param).** `imetout` is NOT added to
`PHYSICS_PANELS["heat"]["params"]` (there is no `input.imetout`). Instead a
dedicated step in `_collect_panel_values`, after the panel loop and the
`_INPUT_ID_REMAP` block:

```python
# --- composite param: imetout <- 5 meteo-output checkboxes ---
try:
    flags = {f: bool(input[f"imetout_{f}"]()) for f in _IMETOUT_FIELDS}
except Exception:
    flags = None            # heat panel not rendered -> leave imetout as-is
if flags is not None:
    sf.set_param("para", "imetout", _imetout_encode(flags))
```

If the Heat panel was never rendered, the reads raise and `imetout` is left
untouched (same preservation pattern as beaching).

### 3. Tests

- `tests/test_parser_str.py` — `imetout` present in `COMMON_PARAMS["para"]`
  (int) and parses from a `$para` block.
- `tests/test_physics_page.py`:
  - `_imetout_decode` / `_imetout_encode` round-trip and digit mapping
    (e.g. `10010` → heat+hflx on, others off; encode back to `10010`).
  - decode of `0` → all False; encode of all-False → `0`.
  - normalization: `_imetout_encode(_imetout_decode(30))` == `10`
    (digit >1 → 1; documented benign).
  - `panel_heat()` source renders the five `imetout_*` checkboxes.

## Data flow

1. Load: `build_panel_params(str_data, "heat")` returns current `imetout`
   (int, or default 0) → `_imetout_decode` → five checkbox `value=`.
2. Edit: user toggles checkboxes.
3. Save: `_collect_panel_values` composite step reads the five inputs →
   `_imetout_encode` → `set_param("para","imetout",value)`.

## Edge cases / known limitation

- Heat panel never opened → checkboxes unrendered → reads raise → `imetout`
  preserved (not overwritten to 0).
- **Normalization (documented, benign):** a loaded digit >1 (e.g. `imetout`
  heat place = 3) round-trips to 1. The core treats any digit >0 as "on", so
  it is semantically identical though not byte-identical. Mirrors slice 1's
  documented space-separated-array limitation.
- Non-integer/garbage `imetout` value → `_imetout_decode` treats as 0 (all
  streams off) rather than raising.

## Testing / validation

- `pytest tests/test_parser_str.py tests/test_physics_page.py` and full UI
  suite (`CONDA_PREFIX=""`, `/opt/micromamba/envs/shiny/bin/python`).
- `black --check shyfem_ui/` + `ruff check` before push (CI Lint gate).
- `ui-security-reviewer` pass before PR (composite-param wiring, no dead
  control, no reactive self-write).

## Deliverable

One PR (`feat/ui-heatflux-imetout`). UI-only; deploys to laguna via the
normal PR → review → deploy path.
