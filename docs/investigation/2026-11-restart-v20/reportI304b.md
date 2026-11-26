## I304b report: what else a restart must carry to reproduce the continuous run (#303/#304)

**Answer.** Besides `evapv` and `iwetv` and the `setweg` clock reset, a restart must carry six more items to reproduce the continuous run:
- the COARE skin-temperature state `tws` and `dtw` (`iheat = 6`);
- `windcd` (`itdrag = 4`);
- the k-epsilon state `tken`, `eps`, `visv`, `difv` (`iturb = 2`, the known gap N25).

With all of them in a throwaway v20 record, every tested case is **exact**: max|d| = 0 in every hydro, T/S and .ext record, serially and on 2 and 4 processes. Without the carry, each case differs. No tested case is left inexact. One proposed layout covers all of it; it is under "Final proposed layout" below.

### Table: max|d| with the patch, and the same read run with the new records not applied ("main-like")
Each "main-like" read uses the same binary and skips the new records and the clock reset. Its numbers equal the issue's: 3.904e-6 / 1.106e-4 for iturb 0, and 4.154e-6 / 4.620e-3 / 4.912 for iturb 1. The times are the case's first hour and last hour after the restart: 7/12 h for mm_hyd_41, 4/6 h for venlag, 13/18 h for `h6noon`. Columns are zeta / transport / S / T.

| case | with patch, both times | main-like, first hour | main-like, last hour |
|---|---|---|---|
| mm41 iturb0 iheat1 (2, 3, 4, 5 alike) | 0 | 3.9e-6 / 3.6e-5 / 1.1e-4 / 2.7e-5 | 3.3e-6 / 1.2e-5 / 1.2e-4 / 1.9e-5 |
| mm41 iheat 6, itdrag 0 | 0 | 3.0e-6 / 2.6e-5 / 1.1e-4 / 1.8e-4 | 2.6e-6 / 8.6e-6 / 1.1e-4 / 1.3e-4 |
| mm41 iheat 7 (code path only: the qflux columns are misread as fluxes) | 0 | 2.0e-5 / 1.9e-4 / 2.7e-3 / 3.2e-4 | 1.6e-5 / 6.3e-5 / 2.4e-3 / 2.6e-4 |
| mm41 iheat 6, itdrag 4 | 0 | 2.1e-3 / 1.0e-2 / 4.77 / 0.59 | 2.0e-3 / 6.6e-3 / 0.45 / 1.8e-2 |
| mm41 iheat 6, itdrag 4, restart at 12 h (`h6noon`) | 0 | 4.3e-3 / 2.1e-2 / 4.76 / 0.86 | 3.0e-3 / 1.1e-2 / 5.36 / 0.48 |
| mm41 iheat 8 | **did not run** | | |
| mm41 iturb 0, 2 and 4 processes | 0 | 2 proc: 3.904e-6 / 1.106e-4 (zeta / S) | 2 proc: 3.342e-6 / 1.183e-4 |
| mm41 iturb 1, 2 and 4 processes | 0 | 4 proc: 4.154e-6 / 6.8e-4 / 4.6e-3 / 6.8e-4 | 4 proc: 3.4e-6 / 8.6e-2 / 4.91 / 0.85 |
| mm41 iheat 6, itdrag 4, iturb 1, 4 processes | 0 | without windcd/tws/dtw: 2.0e-3 / 2.1e-2 / 4.74 / 0.55 | 2.1e-3 / 5.4e-2 / 5.74 / 0.82 |
| venlag_smoke (COARE, GOTM, wet/dry, itsplt 2), serial, 2 and 4 processes | 0 | 4.17e-3 / 3.9e-3 / 1.7e-3 / 7.0e-2 (identical on 1, 2, 4) | 5.3e-5 / 3.2e-4 / 4.5e-3 / 6.0e-3 |
| venlag k-eps (iturb 2), serial and 4 processes | 0 (with the k-eps carry) | 0.41 / 0.22 / 0.31 / 1.43 | 0.26 / 0.11 / 0.60 / 1.36 |

- **iheat 8:** it stops at the first heat step with `STOP error stop wb2rh: pressure` and exit status 0. `meteo_get_heat_extra` passes `ppv` in Pa to `rh2dp`, which expects mbar. This is a pre-existing bug. The mar_menor grid is also UTM, while MFS needs lon/lat. The "0/0 records" lines for h8 in the raw files are not a pass; they are marked so. The `windcd` evidence comes from iheat 6 only.
- **.ext files:** 0 differing records in every "with patch" case (144 or 288 records each), and every main-like read differs. The record at the restart time itself is equal too. `.fvl` was not compared.

### Each extra state, with its evidence (read runs that skip one field, other fields carried)
1. **`iwetv`** (elements, integer).
   - venlag skipping only `iwetv`: zeta 4.18e-3 and T 7.0e-2 at 4 h. Identical on 1, 2 and 4 processes.
   - At the restart there are 609 dry elements, `min(iwetv)` is -185, and elements re-wet in the following steps (1, then 2).
   - Without the carry, `setweg(0)` sets the dry elements' counter to 0, so re-wetting is held back for more than 5 steps.
2. **`evapv`** (nodes, real). venlag skipping only `evapv`: zeta 1.1e-4, T 1.5e-3. The mm41 cases are the I304 finding again.
3. **`tws`, the skin temperature** (nodes, real; a `save` local of `qflux3d`). COARE takes it as its SST input.
   - mm41 iheat 6, itdrag 0, skipping `tws`: zeta 3.1e-7, T 1.8e-4.
   - venlag skipping `tws`: zeta 3.0e-5, S 2.0e-3.
4. **`dtw`, the warm-layer temperature difference** (nodes, real; a `save` local, intent(inout) in `tw_skin`).
   - It is 0 at night, so it is only exercised by a midday restart.
   - `h6noon`: max|dtw| = 3.3e-3 °C at 12 h. Skipping it gives T 2.0e-5 at 13 h, growing to S 5.3 at 18 h.
5. **`windcd`** (nodes, real). With `itdrag = 4`, COARE sets it each step and the next step's wind stress uses it. On a restart `windcd_init` resets it to `dragco`, which is 2.5e-3, against COARE's 2e-4 to 1.1e-3.
   - Skipping it: zeta 2.0e-3 and S 4.77 at 7 h (h6d4); zeta 4.3e-3 at 13 h (`h6noon`).
   - With `itdrag` 0, 1, 2 or 5 it is recomputed or constant, so it is not state.
6. **k-eps: `tken`, `eps`, `visv`, `difv`** (nodes × levels 0:nlv, real).
   - The A dump at the restart shows `visv`/`difv` and then `tken`/`eps` cold.
   - The carry is exact only with two code changes:
     - `keps_init` must be skipped after a restore, both in `handle_gotm_init` (whose comment predicts this wipe) and on the first call of `keps_shell`;
     - `visv`/`difv` must be re-applied after `init_others`, which runs after the read and sets `visv = vistur`.
   - Without the carry: zeta 0.41 m. With all of the above: 0, serially and on 4 processes.
   - `rls` is not needed: `keps` never reads it, only `keps_init` sets it. `z0bk` is equal at the restart.
   - Verified on venlag only (`ireib = 2`).
7. **`setweg` clock (`dtime_old`).**
   - No tested case changes a result without the reset: venlag on 1, 2 and 4 processes, and mm41.
   - The evidence is the counter only: without the reset, `iwetv` is off by 1 at 7835 of 7842 elements after the first step and by up to 5 two steps later. With the reset it is equal.
   - Cause: `set_dry` runs before `set_timestep`, so at a restart with `itrst = -1` the first call sees `dtime ≠ dtime_old`.

Inert differences (results are still exact):
- `zov`/`zeov`/`utlov`/…: the old time levels, which `copy_uvz` overwrites.
- `dt` at the restart.
- `rfricv`/`rcdv`/`bnstressv`/`fxv`/`fyv`/`momentx/y`/`ddx/y`: recomputed before use.
- `qsensv`/`qlatv`/`qlongv` at dry nodes: output only, not fed back. `qflux3d` skips dry nodes, so they keep stale values in the continuous run and 0 after a restart. A heat-flux output file can differ there.

### Final proposed layout (v20)
- **Hydro block (id 1), after `vtlnv`:**
  - `iwetv` (elements, integer);
  - `evapv` (nodes);
  - `windcd` (nodes);
  - a heat flag (whether `qflux3d` was active), then `tws` and `dtw` (nodes).
  - These could also go under id 3, T/S. Cost: about 4·nkn reals plus nel integers.
- **Turbulence block (id 8), after `iturb`:** if `iturb = 2`, `tken`, `eps`, `visv`, `difv`, written the same way as the GOTM arrays.
  - It needs its own id, or a check of the file's `iturb` on read. Once flag 8 is set by a k-eps file, `handle_gotm_init` skips `gotm_internal_init`, so a file written with iturb 2 and read with iturb 1 would start GOTM from unset arrays.
- **When each field must be applied (the tested reader applied all of them unconditionally):**
  - `windcd` only if the reader has `itdrag = 4` (or 3). With `itdrag = 0`, `windcd` is the drag itself, so a restored value would silently override a changed `dragco`.
  - `tws`/`dtw` only if the writer's heat flag is set; otherwise they are zeros.
  - `evapv` and `iwetv` always.
  - The clock reset only when hydro is restored.
- **Code changes needed:**
  - move `dtw`/`tws` out of the `qflux3d` save locals into a module, and skip their initialisation after a restore;
  - move `dtime_old` to a module, and set it to the restart time (atime − atime0) in `rst_perform_restart`;
  - the k-eps guards and the `visv`/`difv` re-application;
  - `nvmax = 20`, with an `nvers >= 20` gate (the v18 branch is `.eq. 18`);
  - `rst_skip_record`, `rstinf` and `rst2shy` must learn the new records. **None of these was changed**, and only single-record files (`idtrst = -1`) were read.

### Not tested
- Ice model (`icevars`/`icethick` in `ice.f90`; no restart hooks).
- Waves (`itdrag = 3`, `windcd` from waves), sedtrans bed, fluid mud, non-hydrostatic.
- Water renewal time (it has its own `wrtrst` file).
- `itsplt = 1` (`dt_act`), and a restart time off an `idtsyn` multiple.
- `flgrst` subsets and multi-record restart files.
- k-eps on mm_hyd_41; `dtw` under wet/dry.
- Averaged outputs or flux sections that span the restart; `.fvl`.

### Caveats and housekeeping
- **Builds.** The final binary ran end to end only for the k-eps 4-process case and the COARE/GOTM 4-process case. The other cases ran on earlier builds with the same hydro-block layout; later builds changed only reader options, the k-eps hooks and the dumps.
- **Live tree incident.** One mis-scoped command created two empty files, `h6noon.b.txt` and `h6noon.c.txt`, in `/home/razinka/shyfem` at 09:58. I removed them. `git status` shows only the pre-existing `docs/water-10-01178-v2.pdf`, `find -newermt 09:40` finds nothing, and HEAD is fd9bd17c.
- **Other work trees.** `wt-r302` and `wt-r307` left the worktree list during my run. My only worktree commands were add/remove of `wt-i304b` and one `prune`.
- **Cleanup.** The work tree `/home/razinka/wt-i304b` is removed and pruned. All case outputs and dumps (about 0.6 GB at peak) are deleted. No background processes are left. Nothing was committed or pushed.
- **Scratch (300 KB):** `/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/i304b.Wtvn`
  - `results.txt`: every number above, with the iheat 8 rows and one intermediate-build line labelled.
  - `raw/`: per-case summaries.
  - `tools/`:
    - `mkmm.sh`, `mkven.sh`, `run3.sh`, `rr.sh`, `heatcase.sh`, `venmpi.sh`: the runs;
    - `shycmp.py`, `summ.py`, `extcmp.py`, `dumpcmp.py`, `wd.py`: the comparisons;
    - `i304b_throwaway.patch`: against fd9bd17c; the v20 record with per-field `I304_SKIP`, `I304_NORESET`, the k-eps block, and the configurable dump hook.
