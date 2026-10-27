# SHYFEM Results Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Visualize page's broken "NetCDF (.nc)" data type with a shiny-deckgl map of any SHYFEM mesh output, with a time slider and play/pause.

**Architecture:** A data layer opens a UGRID NetCDF (converting a `.shy` once with `shyelab -outformat nc` into a size-bounded cache in the viewer's home) and serves per-record node values. A map component draws the mesh as one indexed `simple_mesh_layer` (one vertex per node, vertex colours); on a time change it patches **only the colour array** of that layer (`MapWidget.patch_layer(..., _meshColors=...)`) from a server timer at 1–4 fps; optional current arrows are a `path_layer` patched the same way.

**Tech Stack:** Python 3.13, Shiny for Python 1.8, shiny-deckgl 1.9.2, xarray + netCDF4, numpy, pyproj; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-27-shyfem-results-map-design.md`

Work in the worktree `/home/razinka/wt-map` (branch `feat/ui-results-map`); laguna serves `~/shyfem` live, never edit there. Run tests with `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python3 -m pytest -q -p no:cacheprovider <paths>`; E2E with `-o addopts="-p no:zarr"`; real-binary tests need `PATH=/home/razinka/shyfem/bin:$PATH`.

## Global Constraints

- Map toolkit: shiny-deckgl (`shiny_deckgl`), as already used in `shyfem_ui/components/grid_map.py`; no other map library.
- It replaces the Visualize "NetCDF (.nc)" data type; no new page. The Data Type select key stays `"netcdf"`, its label becomes `"SHYFEM results (.shy/.nc)"`, its extensions `(".shy", ".nc")`.
- Playback 1, 2 or 4 frames per second (default 2), server-driven. Per frame only `_meshColors` (and the arrows' `data`) are patched; a full `MapWidget.update` (basemap + layers + fit to bounds) happens only on load, variable, layer or projection change; palette or colour-range changes are colour patches too (the user's zoom is never reset by them).
- One view reads one file. Current arrows only when that file has `u_velocity` and `v_velocity`.
- Any SHYFEM UGRID output shyelab can convert is accepted (variables discovered from the file); anything without `Mesh2_face_nodes` + `Mesh2_node_x/y` is refused with: `"Not a SHYFEM mesh file: <name> has no UGRID mesh (Mesh2_face_nodes)."` shyelab's NetCDF has no `long_name`, only `standard_name`: labels come from the variable name.
- Colour range fixed during playback: auto = the variable's nan-min/nan-max over all records (and the chosen layer), or manual. A legend shows palette, vmin, vmax and units.
- Writes only through `Config.user_projects_root(user)` (the viewer's home in server mode, `work_dir` locally): cache folder `.shyfem_viewer_cache` there; never write next to the input `.shy`.
- There is **no per-user storage quota** in the app (only per-project); the cache is bounded instead by a new `Config.viewer_cache_max_mb: int = 2000`, evicting least-recently-used entries but never the entry being returned.
- Every new reactive effect: compare-before-set on `reactive.Value`, catch exceptions inside effects (an escaping exception closes the session), never build an input inside an output that the input re-renders. Effects follow the dependency matrix in Task 4 exactly.
- Sliders always get `step=1` (Shiny's default step is range/100 and `max == min` raises at UI build time); read `int(input.t_index())`.
- shyelab reads at most 80 characters of a file path (`character*80`, `src/tools/shyelab/shy_util2.f:140`): always run it on a short symlink inside its working folder.
- CI has no SHYFEM binaries: tests that need `shyelab` skip when it is absent; CI coverage comes from UGRID files the tests write themselves with xarray (no committed binary fixtures, no CI workflow change). Real-binary tests locate samples via `SHYFEM_SAMPLES_DIR` (default `/home/razinka/shyfem/testcases/examples`; the `.shy` outputs are not in git) and skip with a message saying so; each must be seen **passing** once before the PR.

## Review Focus

1. **A projected mesh whose CRS cannot be resolved** (Mar Menor: UTM metres in `Mesh2_node_x/y` despite the "longitude" label, zone not in the file): show "Choose the mesh projection (EPSG) to place it on the map", never draw it at bogus lon/lat. Tests in Task 3 (`test_utm_without_epsg_needs_projection`) and Task 4.
2. **Missing/dry values and flat fields** (`_FillValue -999` → NaN; a variable constant over the run, e.g. initial salinity 35.0): NaN nodes grey, constant range does not divide by zero. Tests in Task 1 and Task 3.
3. **A `.shy` shyelab cannot convert** — real cases exit **0** and write nothing: `.lgr.shy` ("Error: NetCDF: Not a valid ID"), the sample `.fvl.shy` ("error reading file, ierr = -1"), plus a missing `shyelab` binary: a `ConversionError` naming shyelab's last line, the previous map and layers cleared, playback stopped, no cache entry. Tests in Task 2 and Task 5.
4. **The source file changes after caching / a regenerated `.nc` at the same path**: never served stale. Tests in Task 2 (`test_rerun_invalidates_the_cache`) and Task 5 (reload compares path+size+mtime and closes the old dataset).
5. **Switching file, variable or layer while playing, or a slider beyond the new file's records**: the variable falls back to the file's first one when the current is absent, the index is clamped, playback keeps running without errors. Tests in Task 1, Task 4 and the Task 5 E2E (files with 6 and 3 records).

---

### Task 1: UGRID results data layer

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/results_data.py`, `shyfem-ui/tests/_ugrid_fixture.py`
- Test: `shyfem-ui/tests/test_results_data.py`

**Interfaces:**
- Produces:
  - `class NotUgridError(ValueError)`
  - `@dataclass(frozen=True) class VarInfo: name: str; label: str; units: str; has_level: bool`
  - `@dataclass class ResultsFile: path: Path; stamp: tuple[int, int]  # (st_size, st_mtime_ns); ds: xr.Dataset; node_x: np.ndarray; node_y: np.ndarray; faces: np.ndarray  # (n_face, 3) int, 0-based; times: list[datetime]; n_levels: int; variables: dict[str, VarInfo]; has_currents: bool` with `close() -> None` (closes `ds`)
  - `open_results(nc_path: Path) -> ResultsFile` (raises `NotUgridError` with the Global Constraints message)
  - `frame(rf, var: str, t: int, level: int = 0) -> np.ndarray` — float64 node values, NaN for fill; `t` clamped to `[0, len(times)-1]`, `level` to `[0, n_levels-1]`
  - `velocity(rf, t, level=0) -> tuple[np.ndarray, np.ndarray]`
  - `value_range(rf, var, level=0) -> tuple[float, float]` — nan-min/max over all records, computed in time chunks of 200 records (a 24-year run is ~180 MB per variable), memoised per `(var, level)` on the `ResultsFile`
  - `CURRENT_SPEED = "current_speed"` (derived; label "Current speed", units "m s-1"; present when `has_currents`)
  - `tests/_ugrid_fixture.py`: `write_ugrid(path, *, n_time=4, kind="hydro"|"ts", fill_at=None, const=None) -> Path` writing shyelab's exact layout: dims `nMesh2_node=5, nMesh2_face=3, Three=3, level=1, time`; `Mesh2_face_nodes` int32 with `start_index=1`; `Mesh2_node_x/y` float32 lon/lat; `total_depth`; hydro: `water_level(time,node)`, `u_velocity`/`v_velocity(time,node,level)`; ts: `salinity`, `temperature(time,node,level)`; `_FillValue=-999.0`; units `"m"`, `"m s-1"`, `"1e-3"`, `"degC"`; `standard_name` only, no `long_name`.

- [ ] **Step 1: Write the failing tests:**
  - `test_opens_hydro_and_discovers_variables`: variables == `{"water_level", "u_velocity", "v_velocity", "current_speed"}`, `has_currents`, `faces.min() == 0`, 4 times as `datetime`, labels `"Water level"`, `"U velocity"`.
  - `test_opens_ts_without_currents`: `{"salinity", "temperature"}`, not `has_currents`; salinity units `"psu"` (CF `"1e-3"` → `"psu"`).
  - `test_refuses_a_regular_grid`: ERA5-like file (`lat`, `lon`, `t2m(time,lat,lon)`) → `NotUgridError`, message starts `"Not a SHYFEM mesh file"`.
  - `test_fill_values_are_nan`: node 2 written as -999 → `np.isnan(frame(...)[2])`, `value_range` ignores it.
  - `test_constant_variable_range`: `const=35.0` → `value_range(rf, "salinity") == (35.0, 35.0)`.
  - `test_current_speed_is_the_vector_norm`: u=3, v=4 → speed 5.
  - `test_frame_index_out_of_range_is_clamped`: `frame(rf, "water_level", 99)` equals the last record.
  - `test_close_releases_the_file`: after `rf.close()`, the file can be removed and rewritten and `open_results` reads the new values.
- [ ] **Step 2: Run `tests/test_results_data.py`; expect ImportError.**
- [ ] **Step 3: Implement `results_data.py`.** `xr.open_dataset(path, cache=False)` (mask_and_scale on); labels: the name with `_` → space, first letter upper-cased; drop mesh/coordinate/`total_depth` variables; keep variables with dims `("time", "nMesh2_node"[, "level"])`.
- [ ] **Step 4: Run; expect 8 passed.**
- [ ] **Step 5: Commit** `feat(ui): UGRID results data layer for the results map`.

### Task 2: `.shy` → NetCDF conversion cache

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/results_cache.py`
- Modify: `shyfem-ui/shyfem_ui/config.py` (add `viewer_cache_max_mb: int = Field(default=2000, description="Size cap of each user's results-map NetCDF cache")`)
- Test: `shyfem-ui/tests/test_results_cache.py`

**Interfaces:**
- Consumes: `Config.user_projects_root(user)`; `ShyfemWrapper.run_shyelab(shy_file, working_dir, options)` → `CommandResult(success, return_code, stdout, stderr, ...)`; `ShyfemWrapper.get_executable` raises `FileNotFoundError` when the binary is missing.
- Produces:
  - `class ConversionError(RuntimeError)`
  - `viewer_cache_dir(user: dict | None, config: Config) -> Path` — `config.user_projects_root(user) / ".shyfem_viewer_cache"`, created
  - `async def netcdf_for(path: Path, user: dict | None, config: Config, wrapper) -> Path` — a `.nc` is returned unchanged; a `.shy` returns the cached NetCDF, converting first if needed

- [ ] **Step 1: Write the failing tests** (fake wrapper whose `run_shyelab(shy, wd, opts)` records `shy` and writes `out.nc` with `write_ugrid` into `wd`, or not):
  - `test_nc_is_returned_as_is`
  - `test_shy_is_converted_once_and_cached`: two calls → one conversion; result inside `viewer_cache_dir`; the source folder gains no files.
  - `test_shyelab_gets_a_short_name_in_its_folder`: the recorded `shy` is `<wd>/in.shy`, a symlink to the source, `len(str(...)) < 80` relative form (`"in.shy"` is what `run_shyelab` passes).
  - `test_rerun_invalidates_the_cache`: rewrite the `.shy` (new size/mtime) → converted again; the old entry is gone.
  - `test_failed_conversion_raises_and_leaves_no_entry`, parametrized: (a) `success=False`, stdout ending `"STOP error stop shyelab: file not existing"`; (b) `success=True`, exit 0, stdout ending `"Error: NetCDF: Not a valid ID"`, no `out.nc`; (c) `run_shyelab` raises `FileNotFoundError`. Each → `ConversionError` whose message contains the last non-empty output line (or "shyelab not found"); the cache dir holds no `.nc`, no `.src` and no temp folder.
  - `test_cache_is_bounded`: `viewer_cache_max_mb=1`, three 600 kB conversions → total ≤ 1 MB and the last returned path exists.
  - `test_an_entry_bigger_than_the_cap_is_still_returned`: cap 1 MB, one 2 MB conversion → the returned path exists.
  - `test_cache_is_in_the_viewers_home_in_server_mode` (server-mode `Config` as in `tests/test_clone_into_owner_home.py`).
  - Real binary (`skipif` no `shyelab` / sample): `$SHYFEM_SAMPLES_DIR/mar_menor/mm_hyd_assim.ts.shy` copied to a source folder whose absolute path is **longer than 80 characters** → converts; `open_results` lists salinity and temperature. Second real case: `mm_lgr.lgr.shy` → `ConversionError`.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement.** Key = sha1 of `f"{path.resolve()}|{st_size}|{st_mtime_ns}"`; entry `<key>.nc` + sidecar `<key>.src` (the source path). Convert in `tempfile.mkdtemp(dir=cache_dir)`: `os.symlink(path.resolve(), tmp/"in.shy")`, `await wrapper.run_shyelab(tmp/"in.shy", tmp, ["-outformat", "nc"])`; success means `tmp/"out.nc"` exists and is non-empty (whatever `success` says); then `os.replace` into place (atomic against a concurrent session). Always remove the temp folder (`finally`). On a hit, `os.utime` the entry (LRU). After a conversion: delete other entries whose `.src` names the same source, then evict oldest-mtime entries until the total ≤ cap, never the new one.
- [ ] **Step 4: Run; expect all passed (and the real-binary tests passing with `PATH` set).**
- [ ] **Step 5: Commit** `feat(ui): cached .shy to NetCDF conversion for the results map`.

### Task 3: Mesh geometry, colours, legend and arrows (pure)

**Files:**
- Create: `shyfem-ui/shyfem_ui/components/results_map_layers.py`
- Test: `shyfem-ui/tests/test_results_map_layers.py`

**Interfaces:**
- Consumes: `ResultsFile` (Task 1); `PALETTES` from `components/grid_map.py`; `shiny_deckgl.custom_geometry`, `simple_mesh_layer`, `path_layer`, `encode_binary_attribute`; `pyproj.Transformer`.
- Produces:
  - `class NeedsProjection(ValueError)`
  - `mesh_lonlat(rf, epsg: int | None) -> np.ndarray` — `(n_node, 2)`; values within |x|≤180, |y|≤90 taken as lon/lat; otherwise `epsg` required (`NeedsProjection("Choose the mesh projection (EPSG) to place it on the map")`)
  - `mesh_geometry(lonlat, faces) -> dict` — `{"positions": float32 (n,3) metres from centre, "normals": float32 (n,3) = (0,0,1), "indices": uint32 flat, "center": [lon, lat]}` (one vertex per node; metre-offset convention as `grid_map._build_mesh_geometry`)
  - `node_colors(values, vmin, vmax, palette) -> np.ndarray` — float32 (n,3) in 0–1, NaN → (0.78, 0.78, 0.78); `vmin == vmax` → mid-palette colour
  - `RESULTS_LAYER_ID = "results-mesh"`, `ARROWS_LAYER_ID = "results-arrows"`
  - `mesh_layer(geometry, colors) -> dict` — `simple_mesh_layer(RESULTS_LAYER_ID, **custom_geometry({**geometry, "colors": colors}), pickable=False)` (full layer, for `update`)
  - `color_patch(colors) -> dict` — `{"_meshColors": encode_binary_attribute(colors.astype(np.float32))}` (per-frame `patch_layer` payload; the JS shallow-merges it and keeps the cached positions/indices — deckgl-init.js `deck_partial_update` / `cloneLayersData`)
  - `arrow_paths(lonlat, u, v, *, speed_max: float, max_arrows: int = 400, length_m: float | None = None) -> list[dict]` — nodes thinned by a grid over the mesh bounds (≤ `max_arrows`, the first node per cell); each arrow a 5-point polyline shaft + two barbs (`{"path": [[tail], [tip], [barb1], [tip], [barb2]]}`); length = `length_m * speed / speed_max` (default `length_m` = 3 % of the mesh's extent in metres), converted to degrees per axis (`dlon = dx / (111320 * cos(lat))`, `dlat = dy / 110540`); NaN/zero-speed nodes skipped; `speed_max` fixed by the caller (from `value_range(rf, CURRENT_SPEED, level)`) so the scale does not jump between frames
  - `arrows_layer(paths) -> dict` — `path_layer(ARROWS_LAYER_ID, paths, getPath="@@d.path", getColor=[20, 20, 20, 200], widthMinPixels=1, pickable=False)`
  - `legend_html(palette, vmin, vmax, units, label) -> str` — a small HTML colour bar with min/max and units (escaped)

- [ ] **Step 1: Write the failing tests:** `test_lonlat_mesh_is_used_as_is`; `test_utm_without_epsg_needs_projection` (x 688589–710073 → `NeedsProjection`); `test_utm_with_epsg_is_transformed` (32630 → lon −1…0, lat 37…38.5); `test_geometry_is_indexed_one_vertex_per_node`; `test_nan_nodes_are_grey`; `test_flat_range_does_not_divide_by_zero`; `test_color_patch_is_only_colours` (keys == `{"_meshColors"}`, value is a `@@binary` dict) and `test_mesh_layer_has_the_full_geometry` (`id == RESULTS_LAYER_ID`, `_meshPositions`/`_meshIndices`/`_meshColors` present); `test_arrows_are_thinned` (1000 nodes → ≤ 400 paths); `test_arrow_length_scales_with_speed_under_a_fixed_max` (same node, speed doubled, same `speed_max` → length doubled); `test_arrow_direction_is_true_at_55N` (u = v → the tip's bearing in metres is 45° ± 1°); `test_arrows_have_a_head` (5 points per path); `test_legend_escapes_units`.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement** (palette: linear interpolation over the `PALETTES` stops in `(v - vmin) / (vmax - vmin)` clipped to 0–1).
- [ ] **Step 4: Run; expect all passed.**
- [ ] **Step 5: Commit** `feat(ui): mesh geometry, colours, legend and arrows for the results map`.

### Task 4: Results map component (map, controls, playback)

**Files:**
- Create: `shyfem-ui/shyfem_ui/components/results_map.py`
- Test: `shyfem-ui/tests/test_results_map.py`

**Interfaces:**
- Consumes: Tasks 1 and 3; `MapWidget`, basemap constants and the widget set used in `grid_map.py`.
- Produces:
  - `@module.ui results_map_ui(height: str = "600px")` — the MapWidget (id resolved as in `grid_map_ui`); `output_text("time_label")`; `output_ui("legend")`; `output_ui("map_message")`; buttons `step_back`, `play`, `step_fwd`; `input_slider("t_index", "Record", min=0, max=1, value=0, step=1)`; `input_select("speed", "Speed", {"1": "1 fps", "2": "2 fps", "4": "4 fps"}, selected="2")`; `output_ui("var_controls")` (renders `variable`, `level` when `n_levels > 1`, `arrows` checkbox when `has_currents`); `input_radio_buttons("range_mode", ..., {"auto": "Auto", "manual": "Manual"})`, `input_numeric("vmin")`, `input_numeric("vmax")`; `input_select("palette", ..., PALETTES keys, selected="ocean")`; `input_select("epsg", "Projection", {"": "Auto", "32630": "UTM 30N", "32633": "UTM 33N", "32634": "UTM 34N", "3003": "Gauss-Boaga W", "3004": "Gauss-Boaga E", "4326": "WGS84"})`
  - `@module.server results_map_server(input, output, session, results: reactive.Value)` — `results` holds `ResultsFile | None`
  - Pure helpers (tested): `next_index(t, n) -> int` (wraps to 0 after the last; 0 when `n == 0`), `clamp_index(t, n) -> int`, `format_time(dt) -> str` (`"2001-01-01 06:00"`), `pick_variable(current: str | None, rf) -> str` (current if in `rf.variables`, else the first)

- [ ] **Step 1: Write the failing tests:** `test_next_index_wraps_and_clamps`; `test_format_time`; `test_pick_variable_falls_back`; `test_slider_has_a_step_and_builds` (`results_map_ui("x")` renders without error and the slider has `data-step="1"`); source guards in the style of `tests/test_run_progress_and_log.py`: the slider effect is `@reactive.event(input.t_index)`; the play effect reads `t` only inside `reactive.isolate()` and calls `reactive.invalidate_later(`; the frame effect calls `patch_layer(` with `color_patch(` and never `.update(`; the scene effect reads `t` only under `isolate()`; `var_controls` reads only `results` and reads the current control values under `isolate()`; every effect body is wrapped in `try`/`except Exception` with a logged warning.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement the server with exactly this dependency matrix.** State: `t = reactive.value(0)`, `playing = reactive.value(False)`, `scene = reactive.value(None)` (a dict: `rf`, `var`, `level`, `geometry`, `lonlat`, `vmin`, `vmax`, `speed_max`), `last_pushed: list[int | None] = [None]`.

  | Effect | Reactive dependencies | Reads under `isolate()` | Does |
  |---|---|---|---|
  | (a) scene | `results`, `input.variable`, `input.level`, `input.epsg` | `t`, palette, range inputs | if `results` is None: `playing.set(False)`, full `update` with basemap only, clear message; else `rf.close()` is the caller's job (Task 5); `var = pick_variable(...)`; `mesh_lonlat` (on `NeedsProjection`: clear layers, set `map_message`, `scene.set(None)`, `playing.set(False)`); build geometry; range; full `update` with basemap + `mesh_layer` (+ arrows) and fit bounds; `ui.update_slider("t_index", max=max(n-1, 1), value=clamp, step=1)`; `scene.set(...)` |
  | (b) slider | `@reactive.event(input.t_index)` | `t`, `playing` | `v = int(...)`; while playing ignore the value if it equals `last_pushed[0]` or is older than `t`; else `t.set(clamp_index(v, n))` if different |
  | (c) play button | `@reactive.event(input.play)` | `playing` | toggle `playing`; relabel the button "Pause"/"Play" (`ui.update_action_button`) |
  | (d) ticker | `playing`, `input.speed` | `t`, `scene` | when playing: `reactive.invalidate_later(1 / fps)`, `t.set(next_index(t, n))`; do **not** call `update_slider` while playing |
  | (e) frame | `t`, `scene`, `input.palette`, `input.range_mode`, `input.vmin`, `input.vmax`, `input.arrows` | — | colours from `frame` + `node_colors`; `await _map.patch_layer(session, RESULTS_LAYER_ID, **color_patch(colors))`; arrows: `patch_layer(session, ARROWS_LAYER_ID, data=arrow_paths(...), visible=...)`; skip (log once) if `len(values) != len(geometry positions)`; update `time_label` (`f"{format_time(times[t])} — record {t+1} / {n}"`) and `legend` |
  | (f) step | `@reactive.event(input.step_back)`, `@reactive.event(input.step_fwd)` | `t`, `scene` | `playing.set(False)`; `t.set(clamp_index(t ± 1, n))`; `ui.update_slider("t_index", value=...)` |
  | (g) pause sync | `playing` | `t` | when it turns False: `ui.update_slider("t_index", value=t)`; `last_pushed[0] = t` |

  Range: auto → `value_range(rf, var, level)`; manual → `vmin`/`vmax` when finite and `vmin < vmax`, else auto plus a message.
- [ ] **Step 4: Run; expect all passed.**
- [ ] **Step 5: Commit** `feat(ui): results map component with time slider and playback`.

### Task 5: Visualize page integration (replaces the broken NetCDF type)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/visualize.py`
- Modify/Delete: `shyfem-ui/tests/test_netcdf_explorer.py` (it imports `build_variable_table`, `get_dim_label`, `get_variable_attrs`, `_variable_stats`; delete the tests of removed code, keep any helper still used)
- Modify: `CHANGELOG.md` (repo root), `[Unreleased] / Fixed — shyfem-ui`
- Test: `shyfem-ui/tests/test_visualize_results.py`, `shyfem-ui/tests/test_playwright_results_map.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4; `ShyfemWrapper(config.shyfem_dir)` (create it in `visualize_server`, as `postprocess_server` does); the page's `current_user`, `active_project`, `project_files_rev`.
- Produces: `results_val: reactive.Value[ResultsFile | None]` in `visualize_server`, passed to `results_map_server("results_map", results=results_val)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_netcdf_type_lists_shy_and_nc` (`_DATA_TYPE_EXTS["netcdf"] == (".shy", ".nc")`, label `"SHYFEM results (.shy/.nc)"`).
  - Source guards: `_plotly_netcdf`, `_compare_netcdf`, `netcdf_controls`, `_register_dim_labels`, `nc_var_metadata`, `nc_dim_` gone; the Plot tab holds `results_map_ui("results_map")` inside `ui.panel_conditional("input.data_type === 'netcdf'", ...)` and `output_widget("main_plot")` inside `ui.panel_conditional("input.data_type !== 'netcdf'", ...)`; `_load_data` and `_load_compare` are `async` and `await _do_load(`; the netcdf branch shows a "Converting …" notification before `await netcdf_for(`, then `open_results(`; on any exception it calls `.close()` on the previous file, sets `results_val` to `None` and notifies; reload compares `(path, stamp)` and closes the previous `ResultsFile`.
  - `test_profile_and_comparison_say_not_available_for_results` (they return an element containing "not available for SHYFEM results yet" when `data_type == "netcdf"`); "Load for Comparison" with `netcdf` shows that notice and converts nothing.
  - E2E `test_playwright_results_map.py` (pattern: `tests/test_playwright_partitioning_picker.py` + `window.__test_set_active_project`): a project dir with a 6-record hydro file and a 3-record ts file (`write_ugrid`). Choose "SHYFEM results", pick hydro, Load → `#visualize-results_map-time_label` contains `"record 1 / 6"` and `window.__deckgl_instances['visualize-results_map-deckgl_map'].lastLayers` holds a `results-mesh` layer; record its `_meshColors.value`; step forward → `"record 2 / 6"` and `_meshColors.value` differs; Play, wait 2 s → the record advanced, no visible `.shiny-output-error`; switch to the ts file while playing → no error and the label ends `"/ 3"`; switch Data Type to grid → playback stopped (label unchanged over 1 s after switching back).
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement.** Load (netcdf): confine for read; `nc = await netcdf_for(path, user, config, wrapper)`; `rf = open_results(nc)`; set `results_val` (closing the previous); `data_info_val` from variables, times and mesh size; Statistics shows per-variable `value_range` and units; switching Data Type away from `netcdf` sets `results_val` to `None` (stops playback). CHANGELOG: the NetCDF data type is now "SHYFEM results": opens `.shy` (converted once and cached in your home) or SHYFEM NetCDF, shows the variable on the mesh map with a time slider, play/pause, legend and optional current arrows; replaces the plot that failed with "list index out of range" (V-01).
- [ ] **Step 4: Run the new tests and the full unit suite; run `tests/test_playwright_results_map.py` and `tests/test_playwright_pages.py`.**
- [ ] **Step 5: Commit** `feat(ui): SHYFEM results map replaces the broken NetCDF plot (V-01)`.

### Task 6: Real-run verification

**Files:**
- Test: `shyfem-ui/tests/test_results_map_real_run.py`

- [ ] **Step 1: Write a skip-if-no-`shyelab`/sample test** using `$SHYFEM_SAMPLES_DIR/mar_menor/mm_hyd_assim.ts.shy` in a temp project: `netcdf_for` + `open_results`; `mesh_lonlat(rf, None)` raises `NeedsProjection`; with `32630` lon/lat within −1…0 / 37…38.5; `frame` + `node_colors` for every record without exception; `value_range("salinity")` finite.
- [ ] **Step 2: Run with `PATH=/home/razinka/shyfem/bin:$PATH`; it must pass (not skip).**
- [ ] **Step 3: Manual check on a local server** (the E2E `live_server` fixture or `python -m shyfem_ui.app` in the worktree): load a copy of georg's `curonian29.hydro.shy` (1309 nodes, 1460 records; conversion ~5 s), play at 4 fps for 30 s, confirm ~4 records/s, no flashing, the zoom kept, and a palette change not resetting the view; record the measured rate and the per-frame message size (browser devtools WS frame) in the PR.
- [ ] **Step 4: Commit** `test(ui): real-run check of the results map`.
