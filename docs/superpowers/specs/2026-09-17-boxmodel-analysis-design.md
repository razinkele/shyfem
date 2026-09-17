# Box-model analysis in the SHYFEM Workbench — design

**Date:** 2026-09-17 · **Status:** revised after a three-lens review (architecture, security,
domain) and two verification passes (all findings closed); awaiting owner sign-off · **Path:** architectural · **Revision:** 4

## 1. Purpose

Load a SHYFEM box-model setup (the Curonian Lagoon 29-box, 2-D, 1993–2016 case first) into the
Workbench and analyse both the setup and the results graphically, reusable by any project with
SHYFEM box output (`idtbox`). Four deliverables in priority order: box maps with a time slider;
per-box time series with observations and skill; run-vs-run comparison; a setup and forcing
viewer.

Decisions taken with the owner: the period is extended to 1993–2016 first (data pipeline in the
Curonian repo, outside this spec); the feature lives in `shyfem-ui` as reusable pages; large run
outputs stay outside the user sandbox behind admin-declared read-only analysis roots.

## 2. Non-goals

- No 3-D layers: the parser records `layers` from `boxes_stats.txt` and refuses `layers > 1`.
- No editing of the box definition, no re-running the box aggregation, no AQUABC coupling.
- No new map stack: `components/grid_map.py` is extended, not duplicated.
- No Curonian schema inside the Workbench: observations arrive as a generic CSV.
- Not in scope: making the physics/STR editor accept the Curonian STR (see §8, known limitation).

## 3. Layout (follows the repo's `pages/` + `services/` + `components/` convention)

```
shyfem_ui/pages/boxmodel.py              boxmodel_ui / boxmodel_server, four tabs
shyfem_ui/services/boxmodel_manifest.py  manifest load/validate, path resolution + confinement
shyfem_ui/services/boxmodel_output.py    streaming parsers: boxes_2d / boxes_meteo / boxes_stats / boxes_geom / run.log
shyfem_ui/services/boxmodel_cache.py     launch/track/publish builds (registry, reaper) + load of the Parquet cache
shyfem_ui/boxmodel_cache_cli.py          thin CLI (the child process): parsers → Parquet; imports no services/db
shyfem_ui/services/boxmodel_skill.py     observation join + metrics (definitions in §7)
shyfem_ui/services/boxmodel_setup.py     tolerant STR reader, forcing readers, section geometry
shyfem_ui/services/boxmodel_polygons.py  GeoPackage/GeoJSON → WGS84 features keyed by box
shyfem_ui/components/grid_map.py         extended: element colouring by box value, box click, value legend
tests/_boxmodel_fixture.py               synthetic run generator (flat tests/, like _test_helpers.py)
tests/test_boxmodel_*.py                 one file per service + page wiring + one Playwright test
```

Cross-cutting changes, each small: nav entry and server mount in `app.py`; `Config.analysis_roots`
with validation and its read-only widening in `confine_path`; `pyarrow` added to `pyproject.toml`
dependencies and `environment.yml` (it is installed but undeclared); export/import rules for the
cache directory in `services/project_export.py`; docs and changelog.

## 4. Manifest (`boxmodel.json` in the project directory)

```json
{
  "schema": 1,
  "title": "Curonian Lagoon 29-box, 2-D",
  "boxes": {"polygons": "b29polys.gpkg", "layer": "polygons", "id_field": "box"},
  "grid": {"grd": "curonian29.grd", "bas": "curonian29.bas", "boxes_txt": "boxes.txt"},
  "str": "curonian29_1993_2016.str",
  "forcing": {"dir": "fem_forcing"},
  "runs": [
    {"id": "run9314_minijafix", "label": "1993-2014, corrected Minija", "dir": "/home/razinka/curonian/runs/run9314_minijafix"},
    {"id": "run9314",           "label": "1993-2014, pre-fix Minija",   "dir": "/home/razinka/curonian/runs/run9314"}
  ],
  "observations": {"file": "observations.csv", "sites": "sites.csv"}
}
```
(The 1993–2016 run is added to the Curonian manifest when it exists.)

Rules:
- Relative paths resolve against the project directory. Absolute paths must resolve, after strict
  symlink resolution, under one of `config.analysis_roots`. Validation names the offending key.
  Validation resolves paths but does not open files; every open re-checks (§9, TOCTOU).
- The manifest is validated **on every page load for the acting user**, never at import. An
  invalid or oversized (> 64 KB) manifest yields a page-level error message, never an exception
  in module setup.
- `runs[].id` is a slug (`[a-z0-9_-]+`, unique) and names the cache subdirectory.
- `boxes.polygons` is optional. Without it, box outlines are dissolved from the `.grd` triangles
  using the element→box table (`boxes_geom.txt`), which also drives the map colouring (§8).
- `observations.file`: long format, header `date,site,variable,value`, ISO dates, `variable` in
  `{salinity, temperature, level}`, units psu / °C / **cm** for level (converted to m on load).
  `sites`: header `site,lat,lon,box`; `box` may be empty (drawn on the map, excluded from skill).
- `forcing.dir` is optional. The Setup tab reads only the regular `*.txt` files that the STR's
  `$bound*` blocks name in `boundn` (no globbing, no recursion).
- Written by hand, by the project import, or by a form on the page (title, polygons, sites, runs)
  that writes through the file service **after** `editor_denied_reason(project_id, user)` passes.
- The UI shows `runs[].label` and `config.display_path(...)`; raw absolute paths are never
  rendered.

## 5. Box output formats (SHYFEM 8.4, `idtbox`), verified on real runs

Every box file starts with a two-line preamble that the parser validates:
```
#      idbox file_type     nvers
#     473226         2         7          file_type: 2 = boxes_2d, 1 = meteo, 8 = stats, 7 = geom
```

`boxes_2d.txt`, one record per output step (hourly for `idtbox = '1h'`):
```
# time record
   <seconds since date0>      YYYY-MM-DD::HH:MM:SS
#      boxes       nvars
          29           7
# box      temp      salt cur_speed   act_eta  aver_eta   bstress        volume
   <29 lines>
#   sections
          56
# section  from    to         total      positive      negative
   <56 lines>
```
`from < 0` marks an open boundary (`-1` Baltic, `-2..-5` the rivers in `$bound` order, which
equals the `iff_print_info` `ibc` order). `total = positive − negative` (verified). One interface
may be split over several sections (sections 43–49 are all 24→26 in the Curonian setup).

`boxes_meteo.txt`: same envelope, 8 variables `srad tair rhum wspeed cc rain evap ice`, **no
sections block**. `boxes_stats.txt`: `# information on simulation` with `date0 time0` and
`idtbox` in seconds (the step, read from here), `start/end of simulation` (the model period, read
from here), the box table `box layers area volume depth`, the sections table
`section from to nls nlb1 nlb2`, and `# section details` with node lon/lat per section (used to
draw interfaces). `boxes_geom.txt`: `element box area depth` (one row per element). `*.box.flx`
is a binary SHYFEM flux file and is not read.

`run.log` is optional and can exceed 200 MB: it is streamed and only these lines are kept:
`simulation start:` and `simulation end:` (**wall-clock**, reported as such, never used as the
model period), `simulation runtime`, `cpu time (total)`, `program stop at time`, and the
`iff_print_info` table (`descript` is multi-word; rows with unit −1 carry no file).

Parser rules: line-by-line streaming, never a whole file in memory; caps `boxes ≤ 10⁴`,
`sections ≤ 10⁵`, `nvars` fixed per `file_type`, line length ≤ 1 KB; the `boxes`/`nvars` header
is validated on every record; a duplicate box id within a record, a malformed line or a header
mismatch aborts with the record number and file name.

## 6. Cache

Location: `<project.work_dir>/.boxmodel_cache/<run_id>/`, where `project.work_dir` comes from the
project's DB row after the access gate — never from user input and never through a write-widening
of confinement. Contents:

| file | content |
|---|---|
| `state_daily.parquet` | `date, box, temp, salt, cur_speed, act_eta, aver_eta, bstress, volume` daily means; `_min`/`_max` for `temp`, `salt`, `act_eta` |
| `state_hourly.parquet` | raw hourly records, float32, zstd; optional, default **off** for runs longer than 5 years |
| `flux_daily.parquet` | `date, section, from, to, total, positive, negative` daily means |
| `meteo_daily.parquet` | `date, box, srad, tair, rhum, wspeed, cc, rain, evap, ice` daily means |
| `meta.json` | period (from stats), step, boxes, sections table with interface coordinates, box table, run-log facts, and for each source file its **relative name**, size and mtime — no absolute paths |

Daily mean = arithmetic mean of the hourly records whose stamped date is that day (a `00:00:00`
record belongs to its stamped day; first and last days are partial and kept; no minimum count),
exactly as `compare_runs.read()` does.

Sizes for the 22-year Curonian run: ~1.6 GB read (state + meteo), daily cache 10–20 MB, hourly
cache 50–100 MB, build about one minute (two is the cap used for the progress estimate).

**Build model — a child process launched by the service, not a job and not a thread.** The
job queue only launches a closed set of compiled SHYFEM tools and discovers outputs by a flat,
extension-keyed glob, so it cannot represent a Python builder without a generic-exec primitive.
A thread inside the Shiny worker is ruled out too: parsing ~1.6 GB of text in pure Python would
hold the GIL and lag every session on that worker for a minute. So `boxmodel_cache.py` itself
launches `[sys.executable, "-m", "shyfem_ui.services.boxmodel_cache", "--run", <run_dir>,
"--out", <tmp_dir>]` with `start_new_session=True`, bypassing the wrapper's executable lookup
entirely (no change to `ALLOWED_TOOLS`); the CLI's argparse accepts exactly those two arguments
and re-validates both paths at open time (regular directory, no symlink component, run dir under
an accepted root, out dir under the project's cache directory). The CLI lives in a thin top-level module
`shyfem_ui/boxmodel_cache_cli.py` (the command is `-m shyfem_ui.boxmodel_cache_cli`), because
`services/__init__.py` imports the workflow engine, the ORM models and the config; a test asserts
that importing the CLI module does not import `shyfem_ui.db` or `shyfem_ui.services`. The child's
stdout and stderr go to `build.log` inside the tmp directory (never an undrained pipe), and a
wall-clock timeout (`config.command_timeout_seconds`) terminates a hung child so it cannot hold a
slot. A module-level `BuildRegistry` (plain Python state under a lock — never a `reactive.Value`,
which must not be shared across sessions) keyed by `(project_id, run_id)` tracks the child's pid,
start time and owner:
- `start_build(project_id, run_id, run_dir, project_dir, user)` runs only after
  `editor_denied_reason(project_id, user)` passes and `run_dir` has been confined for the acting
  user with `must_exist=True`; a request for a key already building returns the existing handle.
- Concurrency: a global semaphore of 2 builds per worker process and at most one active build per
  user; requests beyond that are queued in the registry and reported as `queued`.
- Cancel: the page's cancel control (editor-gated) sends SIGTERM to the child's process group,
  the same mechanism the job queue uses; the child removes its tmp directory on SIGTERM. Worker
  shutdown terminates children the same way.
- The child re-validates its `--out` structurally, since it has no project row: the parent
  directory must be named `.boxmodel_cache` and its grandparent must lie strictly below
  `user_data_root` or `work_dir`, mirroring `confine_path`'s trusted bases.
- The child writes into `<project_dir>/.boxmodel_cache/<run_id>.tmp-<token>/`, updates
  `progress.json` in that directory via write-to-temp-then-rename (records done / expected from
  the file size, phase, error), writes `meta.json` last, then exits 0. The service awaits the
  child on the worker's event loop (`asyncio.create_subprocess_exec` + `wait()`, as
  `run_command` does), so publishing does not depend on any browser session; on exit 0 it
  performs the **two-step publish**: rename any existing `<run_id>` to `<run_id>.old-<token>`,
  rename the tmp directory to `<run_id>`, then remove the old directory (a plain rename over a
  non-empty directory fails with ENOTEMPTY, so the one-step form is not an option). The token and
  the two-step rename are also the cross-worker safety: Shiny Server may run several worker
  processes with independent registries. Publishing is idempotent: on page load, a `.tmp-*` that
  contains `meta.json` and a `progress.json` reporting exit 0 is published the same way, and a
  stray `.old-*` left by a crash between the two renames is removed like a stale `.tmp-*`.
- Page state per run: `missing`, `stale` (any source name/size/mtime differs from `meta.json`),
  `queued`, `building` (registry entry, or a `.tmp-*` directory whose `progress.json` mtime is
  younger than three poll intervals), `ready`, `failed` (a `progress.json` with an error, or a
  `.tmp-*` older than that — reported and removed by the next build).
- Thread/loop boundary: nothing off the event loop touches reactive state. The page polls
  `progress.json` and the registry with `invalidate_later` only while a build for the shown run is
  queued or active (the precedent is the run page's job polling), and it is the poller that sets
  the completion trigger which invalidates the per-session memo of `cache.load`.
- Cache bytes are counted toward the project quota by extending `_sum_project_bytes` to include
  `.boxmodel_cache/` (or the gap is documented if the owner prefers).

Pages read only the cache: `cache.load(cache_dir) -> CachedRun` (pandas frames, memoised per
session, invalidated by the completion trigger).

## 7. Observations and skill (`boxmodel_skill.py`)

The definitions are those of `shyfem_box/compare_runs.py` and `grid_summary.py` in the Curonian
repo, transcribed here so the two cannot drift:

- Join: site with box `b`, variable `v` → model daily mean of `v` in box `b` on the observation's
  date. Column map: salinity→`salt`, temperature→`temp`, level→`act_eta`.
- Common days: for one run, the days its daily cache contains; for several runs, the intersection
  of their days. Skill uses the days in `obs ∩ model ∩ common`.
- Level as an anomaly: over that day set, subtract each series' own mean; observations are cm and
  are divided by 100 first.
- `n`; `bias = mean(m) − mean(o)`; `RMSE`; `r` with population standard deviations (ddof = 0);
  `R² = 1 − Σ(m−o)² / Σ(o−ō)²` (the Nash–Sutcliffe form the scripts call R²);
  `sd_mod/sd_obs` with ddof = 0. Minimum `n`: 30 for the skill table, 60 for the per-year and
  grid tables; a target with fewer than 3 observation days in the common window is skipped.
- Band amplitude (level only): Hann-windowed FFT amplitude ratio model/observed in the 2–4, 4–10,
  10–30 and 30–400 day bands over a gap-free daily window of at least 120 days; shown beside the
  table because matching total variance can be a compensating error.
- Presentation: amplitude is judged by `sd_mod/sd_obs` (1.00 is right) and phase by `r`; R² is
  shown with a caption that it is not the headline.
- Observation import rules: strict ISO dates; non-finite values dropped; duplicate
  `(date, site, variable)` rejected; **`level ≤ 0` dropped and counted in the import report** (the
  Juodkrantė zero-sentinel lesson, where two `0.0` rows in a 472–555 cm series wrecked r), while
  zeros in salinity and temperature are real and kept; row cap 2 million.

## 8. Page: "Box model" (`pages/boxmodel.py`)

Server signature and mount follow `compare.py` exactly:
`boxmodel_server(input, output, session, config: Config, active_project: reactive.Value,
tutorial_context=None, current_user=None) -> dict`, mounted in `app.py` like the other pages. The
project is read reactively from `active_project.get()`; every `@render.*` is registered
unconditionally with access checks inside the body; selectors are updated under
`reactive.event` on run change with compare-before-set; no `setInputValue` in connect handlers;
each map gets its own module id (`boxmap`, `cmpmap`, `setupmap`). Manifest writes and cache builds
are gated by `editor_denied_reason`; for viewers the controls are hidden **and** the handlers
refuse.

Header strip: run selector with cache state, variable, period (within the run), build button.

**Map.** The `.grd` mesh is drawn with the existing element-coloured mesh layer, each element
coloured by the value of **its box** (element→box from `boxes_geom.txt`), which is the model's own
geometry and needs no polygon file. Quantity: the value on the day chosen by a slider (hourly when
the hourly cache exists and the window is ≤ 31 days), the period mean, or the bias at the posts
(posts as scatter markers coloured by bias). Optional polygon outlines from `boxes.polygons`;
section interfaces as lines from the stats' node coordinates. `grid_map.py` is extended with: a
per-element value array + colour scale (reusing `color_bins`), a value-driven legend via
`legend_control` (the current legend is static per layer), and a click branch that returns the
picked element's `box` (today only `node_id` is extracted). Clicking a box selects it for the
Time-series tab.

**Time series.** Selected box and variable, daily series for the period with the min/max band,
observations of the mapped post overlaid, the skill table beneath, CSV export through the existing
time-series component's export path.

**Compare.** Two to four runs from the manifest; difference map (B − A of the period mean);
overlaid series for the selected box; skill side by side plus the per-year table, all on the
intersection of days.

**Setup.** Mesh with box outlines, open-boundary nodes and river nodes from the STR `$bound*`
`kbound` lists, river series from the files named by `boundn` (with `ibtyp` and `zfact` shown),
per-box meteo from the cache, and an STR summary (`itanf`, `itend`, `idt`, `idtbox`, `date`,
selected `$para` values). This needs a **tolerant STR reader** in `boxmodel_setup.py`: it accepts
`$name` and `&name` headers, trailing text after the section name (`$bound1 ---- Baltic ----`),
and multi-line integer lists; it is tested on an excerpt of the Curonian STR. The existing
`parser_str.py` cannot read this file (headers must match `^\s*\$(\w+)\s*$`, `kbound` is truncated
to its first line); that limitation of the physics/STR editor is recorded as a follow-up issue,
not fixed here.

All plots use `plotly_theme`; text from the manifest, labels and site names is rendered through
`ui.tags`, never `ui.HTML`.

## 9. Security and sharing

- `Config.analysis_roots: list[str]` (env `SHYFEM_UI_ANALYSIS_ROOTS`, **JSON array**, the
  pydantic-settings default for list fields; default `[]`). Applies in **server mode only** (local
  mode bypasses `confine_path`). Validated at config load: each root must strictly resolve to an
  existing directory; `/` is rejected; a root equal to, containing or contained by
  `user_data_root`, `work_dir`, `shyfem_dir`, the database file's directory (sqlite URLs only) or
  `/tmp` is rejected; the accepted list is logged at startup. The `.env` example in the admin
  guide shows the JSON-array form, e.g. `SHYFEM_UI_ANALYSIS_ROOTS='["/home/razinka/curonian"]'`.
- In `confine_path`, when `for_write=False`, the resolved roots are appended to the allowed roots
  exactly as `testcases_dir` and `bin_dir` are today. Roots are never writable and no code path
  writes under them: the builder's working directory is the cache directory, not the run
  directory.
- **Roots are readable by every authenticated user** who can type a path into a manifest, not only
  by those a project is shared with. The admin guide says so and says never to place per-user or
  sensitive data under a root. Directory listing is limited to the STR-named forcing files.
- Symlink resolution stays strict; a manifest path resolving outside all roots is rejected. No app
  path creates symlinks; the test suite keeps the root→sandbox symlink-escape case.
- Parsers: `fiona.open` with the resolved path, `is_file()` true, a driver allowlist
  `{GPKG, GeoJSON}` verified against `src.driver`, ≤ 1000 features and ≤ 200 000 vertices,
  `id_field` integer, unique and matching the stats box table; a CRS failure raises like
  `_wgs84_transformer` does; CSV via `read_csv(dtype=..., usecols=...)` with the rules of §7;
  polygons and observations ≤ 50 MB; box files streamed with the caps of §5.
- Concurrent builds: the registry dedupes within a worker; the `.tmp-<token>` + two-step rename
  makes a race between workers harmless; the semaphore and per-user limit bound the load.
- Export excludes `.boxmodel_cache/`; import **skips** any member under `.boxmodel_cache/` in the
  member loop, so such files never touch disk or the size budget (forcing a rebuild), and
  validates nothing about the manifest (that happens on page load for the acting
  user). Zip-slip is already covered by `_import_project_sync`.
- `confine_path` is applied once per manifest load, not per render.

## 10. Testing

- `tests/_boxmodel_fixture.py` generates a synthetic run: 3 boxes, 4 sections including one open
  boundary and one split interface, 10 days hourly, with the two-line preamble, `boxes_meteo.txt`,
  `boxes_stats.txt` (incl. section details), `boxes_geom.txt`, a run-log excerpt with a wall-clock
  start line, a 3-polygon GeoJSON, `observations.csv` including one `level = 0` sentinel row,
  `sites.csv` with one unmapped site, and an STR excerpt with decorated headers, an `&para`
  section and a multi-line `kbound`.
- Unit: parsers (record structure, preamble/file_type, malformed line → error with record
  number, duplicate box, `layers > 1` refused, run-log streaming); cache build → load round trip,
  staleness, `.tmp` liveness and cleanup, two-step publish over an existing cache, registry
  dedupe, semaphore and per-user limit, cancel (SIGTERM removes the tmp dir), CLI argument and
  path re-validation; flux aggregation (`total = positive − negative`,
  split interface, boundary sections); skill metrics against hand-computed values for every
  definition in §7 including the band ratios and the minimum-`n` rules; manifest validation
  (relative, absolute-under-root, escape, symlink escape, oversized, invalid JSON); config root
  validation cases; tolerant STR reader on the fixture excerpt.
- The cross-check of the package's metrics against `compare_runs.py` on a real run is a one-off
  script in the Curonian repo, recorded in PR 4 — not a CI test, because that script reads the
  Curonian database.
- Page wiring: `_test_helpers.get_server_source` assertions for the tabs' handlers and the
  `editor_denied_reason` gates.
- E2E: one Playwright test importing the fixture project, building the cache, and asserting the
  map renders and the skill table has a row.
- No large data in the repository.

## 11. Curonian onboarding (Curonian repo, `shyfem_box/export_ui_bundle.py`)

Writes `ui_bundle/` and zips it for the Workbench import: `boxmodel.json`; `observations.csv`
from `physical_daily` using `salinity`, `wtemp_mean`, `wlevel_mean` (cm) — noting that Klaipėda
has no `wtemp_mean` rows and one year of `wlevel_mean`, Juodkrantė ends 2011-10-24, Uostadvaris
starts 2010 without salinity, and the record begins 2001-01-01; `sites.csv` with the post→box
mapping the scripts use (Klaipėda 11, Juodkrantė 17, Nida 23, Ventė 25; Uostadvaris with an
empty box); `b29polys.gpkg` (layer `polygons`, EPSG:3346, field `box`); `curonian29.grd/.bas`,
`boxes.txt`; the STR; the river `.txt` files. Runs point at `/home/razinka/curonian/runs/<run>`;
laguna sets `SHYFEM_UI_ANALYSIS_ROOTS='["/home/razinka/curonian"]'`.

## 12. Delivery

Four pull requests, each with tests: (1) manifest, parsers, cache builder and registry, config
roots with validation and confinement, `pyarrow` dependency, map extension, Map and Time-series
tabs; (2) Compare; (3) Setup with the tolerant STR reader; (4) Curonian bundle script, export/
import rules, admin docs, changelog, metric cross-check.

## 13. Resolved points

- Hourly cache off by default for runs longer than 5 years; can be requested.
- Level observations in cm are converted to m on load; the anomaly comparison makes the datum
  irrelevant, the unit is not.
- A run whose box count differs from the manifest's grid/polygons is rejected at cache load.
- The model period always comes from `boxes_stats.txt`, never from `run.log`.
