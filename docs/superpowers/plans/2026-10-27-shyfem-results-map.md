# SHYFEM Results Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Visualize page's broken "NetCDF (.nc)" data type with a shiny-deckgl map of any SHYFEM mesh output, with a time slider and play/pause.

**Architecture:** A data layer opens a UGRID NetCDF (converting a `.shy` once with `shyelab -outformat nc` into a size-bounded cache in the viewer's home) and serves per-record node values. A map component draws the mesh as one indexed `simple_mesh_layer` (one vertex per node, vertex colours) and, on time changes, patches only that layer (`MapWidget.patch_layer`) from a server timer at 1–4 fps; optional current arrows are a `path_layer` patched the same way.

**Tech Stack:** Python 3.13, Shiny for Python 1.8, shiny-deckgl 1.9.2, xarray + netCDF4, numpy, pyproj; pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-10-27-shyfem-results-map-design.md`

Work in the worktree `/home/razinka/wt-map` (branch `feat/ui-results-map`); laguna serves `~/shyfem` live, never edit there. Run tests with `cd shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python3 -m pytest -q -p no:cacheprovider <paths>`; E2E with `-o addopts="-p no:zarr"`; real-binary tests need `PATH=/home/razinka/shyfem/bin:$PATH`.

## Global Constraints

- Map toolkit: shiny-deckgl (`shiny_deckgl`), as already used in `shyfem_ui/components/grid_map.py`; no other map library.
- It replaces the Visualize "NetCDF (.nc)" data type; no new page. The Data Type select key stays `"netcdf"`, its label becomes `"SHYFEM results (.shy/.nc)"`, its extensions `(".shy", ".nc")`.
- Playback 1, 2 or 4 frames per second (default 2), server-driven; never re-send the full layer stack per frame (full `MapWidget.update` only on load / variable / layer / projection change).
- One view reads one file. Current arrows only when that file has `u_velocity` and `v_velocity`.
- Any SHYFEM UGRID output is accepted (variables discovered from the file); anything without `Mesh2_face_nodes` + `Mesh2_node_x/y` is refused with: `"Not a SHYFEM mesh file: <name> has no UGRID mesh (Mesh2_face_nodes)."`
- Colour range fixed during playback: auto = the variable's nan-min/nan-max over all records (and the chosen layer), or manual.
- Writes only through `Config.user_projects_root(user)` (the viewer's home in server mode, `work_dir` locally): cache folder `.shyfem_viewer_cache` there; never write next to the input `.shy`.
- There is **no per-user storage quota** in the app (only per-project); the cache is bounded instead by a new `Config.viewer_cache_max_mb: int = 2000`, evicting least-recently-used entries.
- Every new reactive effect: compare-before-set on `reactive.Value`, catch exceptions inside effects (an escaping exception closes the session), never build an input inside an output that the input re-renders.
- CI has no SHYFEM binaries: tests that need `shyelab` skip when it is absent; CI coverage comes from UGRID files the tests write themselves with xarray (no committed binary fixtures, no CI workflow change).

## Review Focus

1. **A projected mesh whose CRS cannot be resolved** (Mar Menor: UTM metres in `Mesh2_node_x/y` despite the "longitude" label, zone not in the file): show "Choose the mesh projection (EPSG) to place it on the map", never draw it at bogus lon/lat. Test in Task 3 (`test_utm_without_epsg_needs_projection`) and Task 4 (EPSG select default "auto" + message).
2. **Missing/dry values and flat fields** (`_FillValue -999` → NaN; a variable constant over the run, e.g. initial salinity 35.0 everywhere): NaN nodes grey, constant range does not divide by zero. Tests in Task 1 (`test_fill_values_are_nan`, `test_constant_variable_range`) and Task 3 (`test_nan_nodes_are_grey`, `test_flat_range_does_not_divide_by_zero`).
3. **A `.shy` shyelab cannot convert** (Lagrangian `.lgr.shy`, a build without NetCDF, a truncated file): a clear error naming shyelab's last line, the previous map cleared, no cache entry left behind. Tests in Task 2 (`test_failed_conversion_raises_and_leaves_no_entry`) and Task 5 (load error clears results).
4. **The source file changes after caching** (the run was re-run): the stale cache entry is not reused. Test in Task 2 (`test_rerun_invalidates_the_cache`).
5. **Switching file, variable or layer while playing, or a slider beyond the new file's records**: index clamped, playback keeps running without IndexError. Tests in Task 1 (`test_frame_index_out_of_range_is_clamped`) and Task 4 (`test_next_index_wraps_and_clamps`).

---

### Task 1: UGRID results data layer

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/results_data.py`
- Test: `shyfem-ui/tests/test_results_data.py`

**Interfaces:**
- Produces:
  - `class NotUgridError(ValueError)`
  - `@dataclass(frozen=True) class VarInfo: name: str; label: str; units: str; has_level: bool`
  - `@dataclass class ResultsFile: path: Path; ds: xr.Dataset; node_x: np.ndarray; node_y: np.ndarray; faces: np.ndarray  # (n_face, 3) int, 0-based; times: list[datetime]; n_levels: int; variables: dict[str, VarInfo]; has_currents: bool`
  - `open_results(nc_path: Path) -> ResultsFile` (raises `NotUgridError` with the Global Constraints message)
  - `frame(rf: ResultsFile, var: str, t: int, level: int = 0) -> np.ndarray` — float64 node values, NaN for fill; `t` clamped to `[0, len(times)-1]`, `level` to `[0, n_levels-1]`
  - `velocity(rf, t, level=0) -> tuple[np.ndarray, np.ndarray]`
  - `value_range(rf, var, level=0) -> tuple[float, float]` — nan-min/max over all records, memoised per `(var, level)` on the `ResultsFile`
  - Constant `CURRENT_SPEED = "current_speed"` (derived variable, label "Current speed", units "m s-1", present when `has_currents`)

- [ ] **Step 1: Write the failing tests.** A helper `write_ugrid(path, *, n_time=4, kind="hydro"|"ts", fill_at=None)` in `tests/_ugrid_fixture.py` writes a file shaped exactly like shyelab's: dims `nMesh2_node=5, nMesh2_face=3, Three=3, level=1, time`; `Mesh2_face_nodes` int32 with `start_index=1`; `Mesh2_node_x/y` float32; `total_depth`; hydro: `water_level(time,node)`, `u_velocity`/`v_velocity(time,node,level)`; ts: `salinity`, `temperature(time,node,level)`; encoding `_FillValue=-999.0`; units as shyelab writes them (`"m"`, `"m s-1"`, `"1e-3"`, `"degC"`). Tests:
  - `test_opens_hydro_and_discovers_variables`: variables == `{"water_level", "u_velocity", "v_velocity", "current_speed"}`, `has_currents`, `faces.min() == 0`, 4 times as `datetime`.
  - `test_opens_ts_without_currents`: `{"salinity", "temperature"}`, not `has_currents`; salinity label `"Salinity"`, units `"psu"` (map CF `"1e-3"` → `"psu"`).
  - `test_refuses_a_regular_grid`: an ERA5-like file (`lat`, `lon`, `t2m(time,lat,lon)`) → `NotUgridError` whose message starts `"Not a SHYFEM mesh file"`.
  - `test_fill_values_are_nan`: node 2 written as -999 → `np.isnan(frame(...)[2])`, `value_range` ignores it.
  - `test_constant_variable_range`: salinity 35.0 everywhere → `value_range == (35.0, 35.0)`.
  - `test_current_speed_is_the_vector_norm`: u=3, v=4 → speed 5.
  - `test_frame_index_out_of_range_is_clamped`: `frame(rf, "water_level", 99)` equals the last record.

- [ ] **Step 2: Run `tests/test_results_data.py`; expect ImportError.**
- [ ] **Step 3: Implement `results_data.py`.** Use `xr.open_dataset(path)` (mask_and_scale on); labels from `long_name`, else the variable name title-cased with `_` → space; drop mesh/coordinate/`total_depth` variables from `variables`; keep only variables with dims `("time", "nMesh2_node"[, "level"])`.
- [ ] **Step 4: Run; expect 7 passed.**
- [ ] **Step 5: Commit** `feat(ui): UGRID results data layer for the results map`.

### Task 2: `.shy` → NetCDF conversion cache

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/results_cache.py`
- Modify: `shyfem-ui/shyfem_ui/config.py` (add `viewer_cache_max_mb: int = Field(default=2000, description="Size cap of each user's results-map NetCDF cache")`)
- Test: `shyfem-ui/tests/test_results_cache.py`

**Interfaces:**
- Consumes: `Config.user_projects_root(user)`, `ShyfemWrapper.run_shyelab(shy_file, working_dir, options)` (returns `CommandResult` with `success`, `stdout`, `stderr`, `output_files`).
- Produces:
  - `class ConversionError(RuntimeError)`
  - `viewer_cache_dir(user: dict | None, config: Config) -> Path` — `config.user_projects_root(user) / ".shyfem_viewer_cache"`, created
  - `async def netcdf_for(path: Path, user: dict | None, config: Config, wrapper) -> Path` — a `.nc` is returned unchanged; a `.shy` returns the cached NetCDF, converting first if needed

- [ ] **Step 1: Write the failing tests** (a fake wrapper whose `run_shyelab` writes `out.nc` with `write_ugrid` into its `working_dir`, or fails):
  - `test_nc_is_returned_as_is`
  - `test_shy_is_converted_once_and_cached`: two calls → fake called once; result inside `viewer_cache_dir`; the source folder gains no files.
  - `test_rerun_invalidates_the_cache`: touch the `.shy` with new content/mtime → converted again; old entry removed.
  - `test_failed_conversion_raises_and_leaves_no_entry`: fake returns `success=False`, stdout ending `"STOP error stop shyelab: file not existing"` → `ConversionError` whose message contains that line; cache dir holds no `.nc` and no temp folder.
  - `test_cache_is_bounded`: `viewer_cache_max_mb=1`, three 600 kB conversions → total ≤ 1 MB, the most recent kept.
  - `test_cache_is_in_the_viewers_home_in_server_mode` (server-mode `Config` as in `tests/test_clone_into_owner_home.py`).
  - Real binary, `@pytest.mark.skipif(no shyelab)`: convert `testcases/examples/mar_menor/mm_hyd_assim.ts.shy` (skip if absent) → `open_results` lists salinity and temperature.

- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement.** Key = sha1 of `f"{path.resolve()}|{st_size}|{st_mtime_ns}"`, entry `<key>.nc`; convert in a `tempfile.mkdtemp(dir=cache_dir)` folder (shyelab writes `out.nc` there; `run_shyelab` already passes a short relative path), `os.replace` the result into place (atomic against a concurrent session), always remove the temp folder; on hit, `os.utime` the entry (LRU); after a conversion evict oldest-mtime entries until the total ≤ `viewer_cache_max_mb`; remove other entries for the same source path (keep a `<key>.src` sidecar holding the source path to find them).
- [ ] **Step 4: Run; expect all passed (real-binary test passes with `PATH` set).**
- [ ] **Step 5: Commit** `feat(ui): cached .shy to NetCDF conversion for the results map`.

### Task 3: Mesh geometry, colours and arrows (pure)

**Files:**
- Create: `shyfem-ui/shyfem_ui/components/results_map_layers.py`
- Test: `shyfem-ui/tests/test_results_map_layers.py`

**Interfaces:**
- Consumes: `ResultsFile` (Task 1); `PALETTES` from `components/grid_map.py`; `pyproj.Transformer`.
- Produces:
  - `class NeedsProjection(ValueError)`
  - `mesh_lonlat(rf: ResultsFile, epsg: int | None) -> np.ndarray` — `(n_node, 2)` lon/lat; values within |x|≤180, |y|≤90 are taken as lon/lat; otherwise `epsg` is required (`NeedsProjection("Choose the mesh projection (EPSG) to place it on the map")` when `None`)
  - `mesh_geometry(lonlat, faces) -> dict` — `{"positions": float32 (n,3) metres from centre, "normals": float32 (n,3) of (0,0,1), "indices": uint32 flat, "center": [lon, lat]}` (one vertex per node, same metre-offset convention as `grid_map._build_mesh_geometry`)
  - `node_colors(values: np.ndarray, vmin: float, vmax: float, palette: str) -> np.ndarray` — float32 (n,3) in 0–1, NaN → grey (0.78, 0.78, 0.78)
  - `RESULTS_LAYER_ID = "results-mesh"`, `ARROWS_LAYER_ID = "results-arrows"`
  - `mesh_layer_props(geometry: dict, colors: np.ndarray) -> dict` — the kwargs `custom_geometry({**geometry, "colors": colors})` returns (numpy arrays → binary transport); used both to build the layer and, unchanged, as `patch_layer(session, RESULTS_LAYER_ID, **props)` per frame
  - `mesh_layer(geometry: dict, colors: np.ndarray) -> dict` — `simple_mesh_layer(RESULTS_LAYER_ID, **mesh_layer_props(geometry, colors), pickable=False)`
  - `arrow_paths(lonlat, u, v, *, max_arrows: int = 400, length_deg: float | None = None) -> list[dict]` — one `{"path": [[lon,lat],[lon2,lat2]]}` per kept node; nodes thinned by a grid over the mesh bounds so at most `max_arrows` remain (one per cell, the first node); arrow length proportional to speed, longest = `length_deg` (default 3 % of the mesh's lon span); NaN/zero-speed nodes skipped
  - `arrows_layer(paths) -> dict` — `path_layer(ARROWS_LAYER_ID, paths, getPath="@@d.path", getColor=[20, 20, 20, 200], widthMinPixels=1)`

- [ ] **Step 1: Write the failing tests:** `test_lonlat_mesh_is_used_as_is`; `test_utm_without_epsg_needs_projection` (Mar Menor-range x 688589–710073 → `NeedsProjection`); `test_utm_with_epsg_is_transformed` (32630 → lon ≈ −0.8…−0.6, lat ≈ 37.6…37.9); `test_geometry_is_indexed_one_vertex_per_node` (positions shape `(5,3)`, indices length `3*n_face`); `test_nan_nodes_are_grey`; `test_flat_range_does_not_divide_by_zero` (vmin == vmax → all one finite colour); `test_arrows_are_thinned_and_scaled` (1000 nodes → ≤ 400 paths; double speed → double length); `test_mesh_layer_carries_binary_colours` (`mesh_layer(...)["id"] == RESULTS_LAYER_ID`, and `mesh_layer_props(...)` carries the colours as a `@@binary` dict, i.e. numpy was used, with the same keys `mesh_layer` uses).
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement** (palette interpolation over the chosen `PALETTES` stops, linear in `(v - vmin) / max(vmax - vmin, tiny)` clipped to 0–1).
- [ ] **Step 4: Run; expect 8 passed.**
- [ ] **Step 5: Commit** `feat(ui): mesh geometry, colours and current arrows for the results map`.

### Task 4: Results map component (map, controls, playback)

**Files:**
- Create: `shyfem-ui/shyfem_ui/components/results_map.py`
- Test: `shyfem-ui/tests/test_results_map.py`

**Interfaces:**
- Consumes: Tasks 1 and 3; `MapWidget`, basemap constants and the widget set used in `grid_map.py`.
- Produces:
  - `@module.ui results_map_ui(height: str = "600px")` — MapWidget output (id resolved as in `grid_map_ui`), a time label `output_text("time_label")`, buttons `step_back`, `play`, `step_fwd`, `input_slider("t_index", "Record", 0, 0, 0)`, `input_select("speed", ..., {"1": "1 fps", "2": "2 fps", "4": "4 fps"}, selected="2")`, `output_ui("var_controls")` (variable, layer, arrows), range controls (`range_mode` auto/manual, `vmin`, `vmax`), `palette` (keys of `PALETTES`, default `"ocean"`), `epsg` (`""` = auto, `"32630"`, `"32633"`, `"32634"`, `"3003"`, `"3004"`, `"4326"`), `output_ui("map_message")`
  - `@module.server results_map_server(input, output, session, results: reactive.Value)` — `results` holds `ResultsFile | None`
  - Pure helpers (tested): `next_index(t: int, n: int) -> int` (wraps to 0 after the last record; 0 when `n == 0`), `clamp_index(t: int, n: int) -> int`, `format_time(dt: datetime) -> str` (`"2001-01-01 06:00"`)

- [ ] **Step 1: Write the failing tests:** `test_next_index_wraps_and_clamps`; `test_format_time`; source-level guards in the style of `tests/test_run_progress_and_log.py`: the time-change effect calls `patch_layer(` and not `.update(` (full update only in the load/variable effect); the play effect uses `reactive.invalidate_later(`; the controls that `var_controls` renders are not inputs read by `var_controls` itself (it reads only `results`), and their current value is read under `reactive.isolate()` when rebuilt; every `@reactive.effect` body is wrapped in `try`/`except Exception` with a logged warning.
- [ ] **Step 2: Run; expect ImportError.**
- [ ] **Step 3: Implement the server.** State: `t = reactive.value(0)`, `playing = reactive.value(False)`. Effects: (a) on `results`/variable/layer/epsg/palette/range: full `MapWidget.update` with basemap + `mesh_layer` (+ arrows when on), fit to the mesh bounds, `ui.update_slider("t_index", max=n-1, value=clamp)`; on `NeedsProjection` clear layers and set `map_message`; (b) `t_index` input → `t.set` (compare first); (c) `play` toggles `playing` and relabels the button "Pause"/"Play"; (d) while `playing`: `invalidate_later(1/fps)`, `t.set(next_index(...))`, `ui.update_slider("t_index", value=...)`; (e) on `t`: compute `frame` and `node_colors`, then `await _map.patch_layer(session, RESULTS_LAYER_ID, **mesh_layer_props(geometry, colors))`, and for arrows `await _map.patch_layer(session, ARROWS_LAYER_ID, data=arrow_paths(...))`; the geometry is built once per load (effect a) and kept in a plain variable; `time_label` shows `format_time(times[t])` and `"record t+1 / n"`. Range: auto → `value_range(rf, var, level)`; manual → `vmin`/`vmax` (ignored when not finite or vmin ≥ vmax, with a message).
- [ ] **Step 4: Run; expect all passed.**
- [ ] **Step 5: Commit** `feat(ui): results map component with time slider and playback`.

### Task 5: Visualize page integration (replaces the broken NetCDF type)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/visualize.py` (data type label/extensions, `_do_load` netcdf branch, Plot tab, Profile/Comparison/Statistics/Data Info for `netcdf`, remove `netcdf_controls`, `_register_dim_labels`, `nc_var_metadata`, `_plotly_netcdf`, `_compare_netcdf` and the dimension-slider code — the V-01 paths)
- Modify: `CHANGELOG.md` (repo root), `[Unreleased] / Fixed — shyfem-ui`
- Test: `shyfem-ui/tests/test_visualize_results.py`, `shyfem-ui/tests/test_playwright_results_map.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4; `config.user_projects_root`; the page's `current_user`, `active_project`, `project_files_rev` (already wired).
- Produces: `results_val: reactive.Value[ResultsFile | None]` inside `visualize_server`, passed to `results_map_server("results_map", results=results_val)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_netcdf_type_lists_shy_and_nc` (`_DATA_TYPE_EXTS["netcdf"] == (".shy", ".nc")`, label `"SHYFEM results (.shy/.nc)"`).
  - Source guards: `_plotly_netcdf`, `_compare_netcdf`, `netcdf_controls`, `nc_dim_` no longer in the module; the Plot tab contains `results_map_ui("results_map")` inside `ui.panel_conditional("input.data_type === 'netcdf'"…)` (client-side, so the map is not rebuilt by a re-render); the netcdf load path calls `netcdf_for(` then `open_results(`, inside an `async` handler, and on any exception sets `results_val` to `None` and notifies.
  - `test_profile_and_comparison_say_not_available_for_results` (render functions return a `ui` element containing "not available for SHYFEM results yet" when `data_type == "netcdf"`).
  - E2E `test_playwright_results_map.py` (pattern: `tests/test_playwright_partitioning_picker.py` + `window.__test_set_active_project`): project dir with a `write_ugrid` hydro file of 6 records; choose "SHYFEM results", pick the file, Load → `#visualize-results_map-time_label` contains `"record 1 / 6"`; click step forward → `"record 2 / 6"`; click Play, wait 2 s → the record number changed and no `.shiny-output-error` is visible; switch to the ts file while playing → no error, label restarts within `/ 6`.
- [ ] **Step 2: Run; expect failures.**
- [ ] **Step 3: Implement.** The load handler becomes `async`; for `dtype == "netcdf"`: confine the path (read), `nc = await netcdf_for(path, user, config, wrapper)`, `results_val.set(open_results(nc))` (compare-before-set by path), `data_info_val` from the variables, times and mesh size; `main_plot` returns an empty figure for `netcdf`; Statistics shows per-variable `value_range` and units. CHANGELOG entry: the NetCDF data type is now "SHYFEM results": opens `.shy` (converted once and cached in your home) or SHYFEM NetCDF, shows the variable on the mesh map with a time slider and play/pause and optional current arrows; replaces the plot that failed with "list index out of range" (V-01).
- [ ] **Step 4: Run the new tests and the full unit suite; run `tests/test_playwright_results_map.py` and the existing `tests/test_playwright_pages.py`.**
- [ ] **Step 5: Commit** `feat(ui): SHYFEM results map replaces the broken NetCDF plot (V-01)`.

### Task 6: Real-run verification

**Files:**
- Test: `shyfem-ui/tests/test_results_map_real_run.py`

- [ ] **Step 1: Write a skip-if-no-`shyelab` test** that copies `testcases/examples/mar_menor/mm_hyd_assim.ts.shy` (skip if absent) into a temp project, runs `netcdf_for` + `open_results`, and checks: `mesh_lonlat(rf, None)` raises `NeedsProjection`; with `32630` all lon/lat fall in −1…0 / 37…38.5; `frame` for every record and `node_colors` produce no exception; `value_range("salinity")` is finite.
- [ ] **Step 2: Run with `PATH=/home/razinka/shyfem/bin:$PATH`; expect pass.**
- [ ] **Step 3: Manual check on a local server** (`python -m shyfem_ui.app` in the worktree, or the E2E `live_server` fixture): load georg's `curonian29.hydro.shy` copy (1309 nodes, 1460 records), play at 4 fps for 30 s, confirm the frame counter advances about 4 per second and the map does not flash or reset its view; record the observed rate in the PR.
- [ ] **Step 4: Commit** `test(ui): real-run check of the results map`.
