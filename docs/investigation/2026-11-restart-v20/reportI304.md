## I304 report: why a 3D restart does not reproduce the continuous run (#304)

**Answer.** The first field that differs is **`evapv`**, the evaporation in m/s. It is not in the restart record. Each step's heat flux (`run_scalar` → `heat_admin2.f90:667`) computes it, and the **next** step uses it: `sp111(2)` → `meteo_force` → `rain_evap_set` adds `rqdsv = rqdsv + irain*metrain - ievap*evapv` (`meteo_admin.f90:142`), which is the distributed source of the zeta equation. On a restart, `evap_init` has set `evapv = 0`, so the first step after the read runs with no evaporation.

- The size fits: `evapv` is about 1e-8 m/s, times 300 s gives about 3e-6 m. The dumps show 2.1e-6 m after one step and 3.9e-6 m at 7 h.
- It is the only cause in this case, for `iturb` 0, 1 and 3. Once `evapv` is carried across the restart, every hydro and T/S record has max|d| = 0.
- Nothing is restored in single precision that matters; the model state arrays are `real` in memory too.

### Evidence
Serial, OpenMPI build of fd9bd17c (`libmpi.so.40`). The cases are `mm_hyd_41`: a continuous run 0–12 h against a write run 0–6 h (`idtrst = -1`) and a read run 6–12 h (`itrst = -1`, `ityrst = 1`), with `idtout = 1h`.

**1. Reproducing the issue.** The variant **without the tilt lines and with `idtcon = 1h`** gives the issue's table:

| case | 7 h zeta / S | 12 h zeta / S |
|---|---|---|
| `iturb = 0` | 3.904e-6 / 1.106e-4 | 3.342e-6 / 1.183e-4 |
| `iturb = 1` | 4.154e-6 / 4.620e-3 | 3.438e-6 / **4.912** |

- With the tilt kept, `iturb = 0` gives 3.912e-6 at 7 h, but GOTM reaches only S 0.51 at 12 h. So the issue's runs had the tilt removed.
- My "u" is the layer transport record (ivar 3), not velocity, so it cannot be compared with the issue's u column.

**2. Field-by-field dumps.** A throwaway hook wrote about 90 arrays in double at three points:
- **A**: top of the loop.
- **C**: after `sp111(2)`.
- **B**: end of the step.

Comparing the continuous run's step from 6 h with the first step after the read (no carry):
- At **C**, only the evaporation chain differs among the hydro inputs: `evapv` (restart has 0, continuous up to 1.004e-8), then `rqdsv`/`rqv`/`mfluxv` (4.158e-3 m³/s).
- Also different at C, but inert:
  - `rfricv`, `rcdv`, `bnstressv` and `ddxv`/`ddyv` are recomputed in the step before any read (`chezy.f90:400-403`, `hydrodynamic.f90:1529`, `substress.f90:218`).
  - `qsensv`/`qlatv`/`qlongv` are diagnostics, recomputed before output.
  - `iwetv` differs, but there are no dry elements in this case.
- At **B**, znv differs by 2.094e-6, utlnv by 9.4e-6, S by 1.5e-4.

**3. Confirmations.** Each was checked over all 24 hydro records and all T/S records (4 at 3 h, 12 at 1 h):
- `ievap = 0` in all three runs: max|d| = 0, and the state at the end of each step equals through 7 h.
- `evapv` carried by a side file: max|d| = 0 for `iturb` 0 and 3 (with tilt) and for `iturb` 1 (with and without tilt).
- A throwaway **v20 restart record** (`iwetv` and `evapv` after `vtlnv`, read inside `rst_read_record`): max|d| = 0 for `iturb` 0 and 1 in the issue variant. This shows a real record read is enough.
  - `meteo_init` → `evap_init` runs in `sp111(1)` (`shyfem_subs.f90:414`) **before** `rst_perform_restart` (line 423), so the value read survives.

Two caveats on what was compared: the `.fvl` file matched 0 records in my parser, and `.ext` was not compared (the read run's file holds only 6–12 h).

### GOTM (`iturb = 1`)
- **Saved** (`write_restart_gotm`, double precision, nodes, levels 0:nlv): `numv_gotm`, `nuhv_gotm`, `tken_gotm`, `eps_gotm`, `rls_gotm`.
- **Read by the step:**
  - Those five arrays.
  - `visv`/`difv` in step 1, which `handle_gotm_init` (#283) sets from the restored `numv`/`nuhv`, because the closure runs after hydro and `run_scalar`.
  - `buoyf2`/`shearf2`: 0 after the restart, but `setm2n2` recomputes them in `gotm_shell` before use.
  - `tauxnv`/`tauynv`: forcing, recomputed every step.
  - `uprv`/`vprv`: from the restored transports.
  - `z0` via `turb_wall_roughness`, which is derived (`ireib = 5`).
- **Missing: nothing, for this case and `gotmturb.nml`.** With `evapv` carried the results are identical. The S 4.9 at 12 h is the 4e-6 m evaporation perturbation amplified by GOTM.
- I did not inspect the GOTM library's internal module state. The identical results only show it does not leak in this case.
- k-epsilon was not looked at (N25).

### `iwetv` (#303)
- It belongs in the same record.
- It has two readers:
  - re-wetting, `-iwetv > iwait` (`wetdry.f90:314`);
  - `sedim_admin.f90:4187`, `iwetv > 5`. So #303 is not only about re-wetting.
- **Saving it is not enough on its own.** With v20 the restored value equals the continuous one before the first step (73 = 73). After the first `set_dry`, the restart is +1 everywhere (74 vs 73, still +1 at 7 h).
  - Cause: `setweg` counts a new step when `dtime /= dtime_old`, a `save` local.
  - With `itrst = -1` the reader resets `itanf` after the start-up `setweg(-1)`/`setweg(0)` calls, so `dtime_old` is stale.
  - With an explicit `itanf = itrst = 06:00`, `iwetv` and every dumped array are equal (measured).
  - The fix must set `dtime_old` to the restart time after the read.

### Proposed format: version 20
- **Layout.** v19 plus, in the hydro block right after `vtlnv`: `iwetv` (elements, integer), then `evapv` (nodes, real).
  - Always written; `evapv` is 0 without a heat flux.
  - Read under the hydro flag (`flgrst` id 1, `id_hydro_rst`), with the skip-reads when that id is not wanted. `evapv` is the hydro step's mass source; no new id, `nidmax` stays 10.
- **Reader gates.**
  - The new block needs its own `nvers >= 20` gate; the v18 branch is `.eq. 18`.
  - v18 (upstream: `iwetv`, `zov`, `zeov`) is unchanged; its `evapv` stays 0.
  - v19 and v17 or older are unchanged: `iwetv` comes from `setweg(0)`, `evapv` from `evap_init` (0).
- **Everything that must change:**
  - `nvmax = 20` and the version tables in `mod_restart.f90` and `restart.f90`;
  - `rst_read_record`;
  - `rst_skip_record`;
  - `rstinf.f90`: its range check uses `nvmax`; its diff mode compares `iwetv` only for v18 and needs v20 plus `evapv`;
  - `rst2shy`, which must skip the two new records;
  - the `setweg` `dtime_old` reset.
- **Risks.**
  - Upstream could independently claim 19 or 20, as happened with 18.
  - The new `.rst` files necessarily differ from base, so the round's ".rst byte-identical" rule needs an owner exception for this PR.
  - Results change only for restarted runs with `ievap = 1`, or with wetting and drying, toward the continuous run.
- **Failing-first test.** This fidelity comparison: the 0–12 h run against the 6 h write/read pair with `ievap = 1`, for `iturb` 0 and 1, max|d| = 0. It fails on main at 3.9e-6 m. Add a wet/dry case for `iwetv` (`venlag_smoke`), run serially and on several processes.

### What remains uncertain
- **The same kind of carried state, not exercised here and not in the restart:**
  - `iheat = 6` (COARE): the skin temperature `tws`/`dtw` (a `save` array in `heat_admin2.f90`);
  - `windcd` set by COARE or MFS bulk (`iheat` 6/8) or by waves, read by the next step's wind stress (`windcd_init` resets it to `dragco`).
- **Not run:** other `iheat` formulas, ice, waves, variable time step, MPI, wet/dry.

### Housekeeping
- Scratch (56 KB): `/tmp/claude-1000/-home-razinka-shyfem/6f1c0651-7dd1-449f-9b48-6cb7e179f7a3/scratchpad/i304.OWrv`
  - `results.txt`: all numbers above.
  - `tools/`:
    - `mkcase.sh`, `runcase.sh`, `rundump.sh`, `runevap.sh`: the runs.
    - `shycmp.py`: max|d| per .shy record.
    - `dumpcmp.py`: per-array comparison of the dumps.
    - `i304_throwaway_hooks.patch`: the dump hook, the side file and the v20 record, against fd9bd17c. Apply it and repoint the `/home/razinka/wt-i304` paths in the scripts to reuse them.
- The work tree `/home/razinka/wt-i304` is removed and pruned. Dumps and case outputs (11 GB) are deleted. No background processes are left. The live tree is untouched, and nothing was committed or pushed.

