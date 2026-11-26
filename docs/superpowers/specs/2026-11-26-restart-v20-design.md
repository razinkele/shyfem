# Design: restart file version 20, so a restarted run reproduces the continuous run (#303, #304)

Status: a short design, for the owner's approval. The owner chose on 2026-11-26: one new restart version that carries all the missing state (the "core fields only" and "hold" options were declined), short design doc first, then one PR.

Evidence: two investigations in round 6.
- `reportI304.md` found the first differing field.
- `reportI304b.md` audited every other heat, drag, wet/dry, MPI and closure case.

Both are kept under `docs/investigation/2026-11-restart-v20/` with their scripts and the throwaway patch (copied there by the build PR).

## Intent
Today a run restarted from a restart file does not continue as the uninterrupted run would.
- `mm_hyd_41`: the water level is off by about 4e-6 m at the first output after the read, and GOTM amplifies that to S 4.9 by 12 h.
- Wet/dry cases re-wet at different steps.
- COARE with its own drag, and k-epsilon, are off by up to 0.4 m.

A restart that changes the answer defeats its purpose: chained runs, cold-start avoidance, and comparing scenarios from a common state. Goal: write and read everything the next step needs.

## Goals
- A continuous 0–12 h run and a write-at-6 h / read-from-6 h pair give byte-identical hydro, T/S and `.ext` records, in every case the audit made exact:
  - `iheat` 1–6;
  - `iheat = 6` with `itdrag = 4`, including a midday restart;
  - GOTM and k-epsilon;
  - wet/dry `venlag_smoke`, serially and on 2 and 4 processes.
- Old restart files (v17–v19) are still read exactly as now.

## Non-goals
These were not tested and are not promised to become exact:
- the ice model, waves (`itdrag = 3`), sedtrans bed state, fluid mud, non-hydrostatic;
- `itsplt = 1`;
- `flgrst` subsets, multi-record restart files;
- the water-renewal file (`wrtrst`);
- `iheat = 8` (it cannot run today: #319);
- `.fvl` files, and averaged outputs that span the restart.

## Anti-goals
The change fails, even if it works, if:
- any non-restarted run changes;
- an old restart file reads differently;
- the restart silently overrides a user's changed parameter, for example `dragco` when `itdrag = 0`.

## Constraints
- **Repo conventions** (CLAUDE.md): MPI-safe aborts, no bare `stop`.
- **The format and its readers stay one family.** `rstinf` and `rst2shy` must read v20.
- **Upstream** (`shyfemcm`/`ismar` active branches) is at v18. This fork already writes v19, so v20 stays this fork's number. A clash with a future upstream v19/v20 already exists for v19 and is accepted.

## Approaches (decided)
- **A. One v20 record with all the missing state.** *Chosen.* The format changes once, and every audited case becomes exact.
- B. v20 with only `evapv`, `iwetv` and the clock reset; the rest later. *Declined*: the format would change twice.
- C. Per-module side files, like `wrtrst`. *Not taken*: it breaks the single-file restart users rely on.

## The design
### What the v20 record adds
**In the hydro block (id 1), after `vtlnv`:**

| Field | Shape | Applied when |
|---|---|---|
| `iwetv` | elements, integer | always |
| `evapv` | nodes, real | always |
| `windcd` | nodes, real | only if the reader has `itdrag = 4` (or 3) |
| a heat flag: `qflux3d` was active in the writer | | |
| `tws`, `dtw` | nodes, real (COARE skin temperature and warm-layer difference) | only if the heat flag is set |

`windcd` is skipped otherwise because with `itdrag = 0` it *is* the user's drag. *(My call: the hydro block holds them because they feed the next hydro step. The audit tested that placement.)*

**In the turbulence block (id 8):** if the writer's `iturb = 2`, the k-epsilon `tken`, `eps`, `visv` and `difv` (nodes × levels 0:nlv), written like the GOTM arrays.
- The reader applies them only if its own `iturb = 2`.
- A k-epsilon file read with GOTM must not leave GOTM uninitialised: `handle_gotm_init` checks which closure wrote the block.

### Code changes
- **`dtime_old`** (`setweg`'s new-step clock, today a `save` local in `wetdry.f90`): moves to a module and is set to the restart time in `rst_perform_restart`. Without it the restored `iwetv` is off by one after the first step.
- **`tws` and `dtw`:** move from `save` locals of `qflux3d` (`heat_admin2.f90:229-230`) to a module, and their start-up initialisation is skipped after a restore.
- **k-epsilon:**
  - `keps_init` is skipped after a restore, in `handle_gotm_init` and on the first call of `keps_shell`;
  - `visv`/`difv` are re-applied after `init_others` (`initialize.f90:236`), which sets `visv = vistur` after the read.
- **The reader:**
  - `rst_read_record` and `rst_skip_record` get an `nvers >= 20` gate (the v18 branch is `.eq. 18` and stays);
  - `nvmax = 20` (`mod_restart.f90:88`) and the version tables;
  - `rstinf` (range check; its diff mode compares the new fields) and `rst2shy` (skips the new records).
- **`evap_init` and `windcd_init`** run in `sp111(1)` before `rst_perform_restart`, so read values survive. The audit verified this.

### Results that change
- Only restarted runs, toward the continuous run.
- New `.rst` files are v20, so every gate that compares `.rst` files with the base gets this PR's exception. The PR names those gates.
- No non-restarted file changes: shown with `cmp` for the usual battery.

## Tests kept in the repo
1. **`check_restart_fidelity.sh`, new, from the audit's scripts:**
   - continuous against write/read pairs: `mm_hyd_41` with `iturb` 0 and 1 and `ievap = 1`, `iheat = 6` with `itdrag = 4` including the midday restart, and `venlag_smoke` serially and on 2 and 4 processes;
   - required: max|d| = 0 in every hydro, T/S and `.ext` record;
   - RED on main (3.9e-6 m and up).

   The k-epsilon case runs on `venlag` (serially and on 4 processes). *(My call: it was only verified there.)*
2. **Old files:** a v19 restart file written by main is read by the branch exactly as main reads it (`cmp` of the continued run).
3. **Tools:** `rstinf` and `rst2shy` on a v20 file.

## Left to the builder
- The exact record order and names within the blocks.
- How `handle_gotm_init` learns the writer's closure: a stored `iturb`, or a sub-flag.
- Whether the heat flag is a separate integer or derived from `iheat`.
- The CHANGELOG wording. It must say restarted runs change, toward the continuous run, and that the format is now v20.
