# UI slice 3: Data Assimilation panel for the `$assimil` framework

**Date:** 2026-07-28
**Status:** approved (user, 2026-07-28)
**Branch:** `feat/ui-assimilation`
**Predecessors:** slice 1 beaching (PR #64), slice 2 imetout (PR #65)

## Problem

The physics page's "Data Assimilation" panel predates the assimilation
framework (PRs #54/#61) and is actively harmful:

- It writes a `$nduge` section (`nvars`/`tramp`/`ttau`/`sigma`/`bmulti`)
  that **no code in the core reads**. `iostr.f90` hard-stops on unknown
  sections (`error stop nlsh2d: no such section`), so opening the panel
  and saving produces an STR that crashes shyfem at startup.
- The zeta-nudging code it was modeled on (`nudge.f90`) is dead:
  `nvars = 0` hardcoded, station filenames hardcoded to a 2013 Venice
  campaign, no STR parameters read at all.
- Its `ibarcl` select offers only 0/4/5 — exactly the modes in which the
  real framework never runs (`assimil_ts` sits under the active-transport
  branch, which requires `ibarcl = 3`).
- The `data_assimilation` **simulation template** in
  `simulation_logic.py` also emits a `$nduge` section and `ibarcl = 4`,
  so simulations created from it crash the core the same way.

The real framework reads numbered `$assimilN` sections (one per
assimilated variable) via `read_assimil` / `assimil_init_section`
(`src/shyfem/assimil_admin.f90`).

## Core contract (source of truth: `assimil_admin.f90`)

Per `$assimilN` section (N ≥ 1, unique; one section per variable):

| Param | Kind | Default | Constraint (when `nobs > 0`) |
|---|---|---|---|
| `nobs` | int, required | −1 | station count; **`nobs = 0` = section ignored** (core logs and deletes it — the sanctioned "disabled" state) |
| `ivar` | int, required | −1 | 12 = temperature, 11 = salinity — the only two wired via `assimil_ts`; must be unique across sections |
| `mode` | int | 0 | 0 = implicit nudging, 1 = direct insertion |
| `tau` | float | 0 | nudging timescale / insertion interval (s) |
| `corlength` | per-station array | 0 | > 0 required |
| `maxlength` | per-station array | 0 | ≥ 0 |
| `sigobs` | per-station array | 0 | > 0 required |
| `sigback` | per-station array | 0 | > 0 required |
| `iuse` | per-station array | 1 | per-station QC on/off |
| `layer` | per-station array | 0 | ≥ 0; **must be uniform** across stations (core aborts otherwise); 0 = uniform column |
| `vcorlength` | per-station array | 0 | **must be uniform**; vertical Gaussian correlation length (m); 0 = uniform column |
| `filecoords` | filename | '' | station x/y file |
| `fileobs` | filename | '' | observation time-series file |

For every per-station array, **a single value broadcasts to all
stations** — both reference STRs (`mm_hyd_assim.str`, `venlag_assim.str`)
use that form exclusively, including with `nobs = 2`.

## Decisions (settled with user)

1. **Granularity: uniform values.** One set of OI parameters per
   variable block, broadcast to all stations. No parser array-write
   support needed. Pre-existing per-station arrays in a loaded STR get
   the slice-1 treatment (read-only note, raw line preserved).
2. **Structure: fixed T + S blocks.** Two sub-blocks (Temperature =
   ivar 12, Salinity = ivar 11), each with an enable toggle. No generic
   section list — only these two ivars are consumed by the model today.
3. **`$nduge` is deleted on save** (user-approved deletion of file
   content): it is guaranteed-fatal to any run and only the old UI ever
   wrote it. A notification reports the removal.
4. **No `ibarcl` control in this panel.** The baroclinic panel already
   owns one with the full 0–5 range; duplicating it is a
   last-writer-wins footgun. The panel shows a static requirement hint
   instead.

## Design

### 1. Registry & metadata

- `PHYSICS_PANELS["assimilation"]`: `"params": {}`, no `"section"` key —
  a composite panel in the imetout mold. Values are read directly from
  the `StrFile` (`str_data.get()`), **never** via `build_panel_params`
  (slice-2 lesson: unregistered params come back empty there).
- Remove `nduge` from `COMMON_SECTIONS` and `COMMON_PARAMS`
  (`parser_str.py`); remove `"ibarcl_assim"` from `_INPUT_ID_REMAP`
  (`physics.py`).
- Rewrite the `data_assimilation` template in `simulation_logic.py`:
  drop `$nduge`, set `ibarcl = 3`, add an `$assimil1` (T) + `$assimil2`
  (S) pair modeled on `mm_hyd_assim.str`, and drop the `$name`
  `tempn`/`saltn` entries (they feed only the dead ibarcl=4 nudging
  path; `wind` stays).

### 2. Panel UI (`panel_assimilation`)

- Top: hint line — "Optimal-interpolation assimilation runs in
  prognostic baroclinic mode (ibarcl = 3, set in the Baroclinic panel)."
- Two blocks, Temperature and Salinity. Each: an enable checkbox
  (`assim_t_on` / `assim_s_on`) above always-rendered fields — the
  checkbox gates only save behavior. (Amended from panel_conditional:
  its JS condition strings are not namespaced inside Shiny modules.)
  Fields per block:
  - `nobs` (int, min 1), `mode` (select: 0 nudging / 1 direct
    insertion), `tau` (s, min 0)
  - `corlength` (m), `maxlength` (m), `sigobs`, `sigback`, `layer`
    (int, min 0), `vcorlength` (m)
  - `filecoords`, `fileobs` (text inputs, `$name`-section convention)
- Input IDs are prefixed `assim_t_` / `assim_s_`.
- `iuse` is not exposed: uniform iuse is either "all on" (default) or
  "section off" (that is the checkbox).
- Per-field array handling: a param renders as a static "per-station
  values set in the STR — edit the file directly" note with **no input
  control created** (so the save loop's read fails and the raw line
  survives verbatim, slice-1 pattern) in either of two cases: the stored
  value exists but is not a clean scalar (`_scalar_or_none` returns
  None — the comma form), or the param's raw STR line carries more than
  one value token (the space form, `corlength = 2000. 3000.`, which
  `PARAM_PATTERN` truncates to a clean first-token scalar that would
  otherwise render editable and be half-rewritten on save; detection
  scans the section's `raw_lines`). String params
  (`filecoords`/`fileobs`) are exempt — they are never arrays.

### 3. Load semantics

- Scan `str_file.sections` for names matching `^assimil\d+$`.
- Adopt **by ivar, not by number**: the section with `ivar = 12` feeds
  the T block, `ivar = 11` the S block — whatever their numbers. The
  adopted section name is remembered for write-back.
- Block enabled ⇔ adopted section exists with `nobs > 0`. A `nobs`
  that is not a clean integer (parse corruption) is treated as 0, i.e.
  disabled — and the disabled-save path then touches nothing but `nobs`.
- Sections with any other ivar are untouched; an info note lists them
  ("other $assimil sections present — edited in the STR").

### 4. Save semantics (composite step in `_collect_panel_values`)

- Panel never rendered (inputs absent) → leave everything untouched
  (try/except around the checkbox reads, imetout pattern).
- Block enabled → write every field (including `ivar`) into the adopted
  section; if none was adopted, create `assimil1` (T) / `assimil2` (S),
  skipping to the first free number if taken. Each field read is
  individually guarded, so a field whose input was never created (the
  array-note case) is skipped and its raw line survives. `set_param`'s
  overlay-on-raw-lines preserves formatting of existing sections.
- Block disabled, adopted section exists → set `nobs = 0` only. The
  core ignores and logs such sections; the user's tuning survives for
  re-enabling. No deletion.
- Block disabled, no section → no-op.
- `$nduge` present in `str_file.sections` → delete it (section dict +
  structure entry handled by `generate()`'s missing-section guard) and
  notify. The purge runs whenever panel values are collected — save and
  STR preview alike — matching the page's existing behavior of mutating
  the in-memory StrFile on preview; the preview then honestly shows what
  save would write.

### 5. Error handling

Light touch, consistent with the page: `min=` constraints on numerics
(`corlength`/`sigobs`/`sigback` min > 0 mirrors core validation); no
hard blocking — the core aborts with clear messages and the STR remains
hand-editable. No existence checks on the two file paths (they are
resolved relative to the run directory at run time).

### 6. Testing

Discriminator tests in the established style (`test_physics_page.py`,
`test_parser_str.py`):

1. Load an `mm_hyd_assim`-shaped STR (two sections, T + S) → both
   blocks reflect stored values.
2. Adoption by ivar: a `$assimil7` with `ivar = 12` feeds the T block
   and is written back under its own name.
3. Untouched load → save round-trips byte-identical (raw-lines path;
   single-section fixture — the generator's inter-section blank-line
   handling precludes multi-section byte-identity, so the guarantee is
   per-section).
4. Array-valued `corlength` → note rendered, no input, raw line
   verbatim after save — in BOTH array forms: comma (parses to a
   non-scalar string) and space-separated (parses to a clean
   first-token scalar; must be caught via raw-line detection).
5. Disable an existing section → only `nobs` changes, to 0.
6. Enable from scratch → well-formed `$assimil1`/`$assimil2` with all
   written fields; numbering skips occupied numbers.
7. `$nduge` in loaded STR → absent from generated output after save.
8. Template: `data_assimilation` output contains `$assimil1`/`$assimil2`
   and `ibarcl = 3`, and no `nduge` anywhere.
9. Parser: `$assimil1`-style numbered sections parse as distinct
   sections and round-trip (add only if not already covered).

## Out of scope

- Per-station arrays / add-remove station rows (would need parser
  array-write support; revisit if a real need appears).
- `iuse` exposure, generic-ivar sections, coords/obs file creation or
  validation, file pickers for `filecoords`/`fileobs`.
- Any core (Fortran) change.

## Reminders for the implementer

- CI Lint gate is `black --check shyfem_ui/` only — never blanket-run
  `black tests/` (slice-2 lesson; it reformats ~65 drifted files).
- Tests: shiny env python, `CONDA_PREFIX=""`.
