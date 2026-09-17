# Box-model analysis in the SHYFEM Workbench — design

**Date:** 2026-09-17 · **Status:** approved in discussion, awaiting spec review · **Path:** architectural

## 1. Purpose

Load a SHYFEM box-model setup (the Curonian Lagoon 29-box, 2-D, 1993–2016 case first) into the
Workbench and analyse both the setup and the results graphically, in a way any project with SHYFEM
box output (`idtbox`) can reuse. Four deliverables, in priority order: box maps with a time
slider; per-box time series with observations and skill; run-vs-run comparison; a setup and
forcing viewer.

Decisions taken with the user: the period is extended to 1993–2016 first (data pipeline in the
Curonian repo, outside this spec); the feature lives in `shyfem-ui` as reusable pages, not a
Curonian-specific page or a separate app; large run outputs stay outside the user sandbox behind
admin-declared read-only analysis roots.

## 2. Non-goals

- No 3-D layers (the box output analysed is 2-D; the parser records `layers` from the stats file
  and refuses `layers > 1` with a clear message).
- No editing of the box definition, no re-running the box aggregation, no AQUABC coupling.
- No new map stack: the existing deck.gl grid-map component is reused.
- No Curonian schema inside the Workbench: observations arrive as a generic CSV.

## 3. Package layout

A self-contained package `shyfem_ui/boxmodel/`:

```
shyfem_ui/boxmodel/
  __init__.py
  manifest.py        # BoxModelManifest: load/validate boxmodel.json, resolve + confine paths
  box_output.py      # streaming parser of boxes_2d.txt / boxes_meteo.txt / boxes_stats.txt / run.log
  cache.py           # build + load the Parquet cache; CLI entry `python -m shyfem_ui.boxmodel.cache`
  skill.py           # observation join + metrics (definitions below)
  polygons.py        # GeoPackage/GeoJSON -> WGS84 GeoJSON features keyed by box number
  setup_view.py      # STR summary, boundary/river nodes, forcing series readers
  page.py            # the "Box model" page: boxmodel_ui / boxmodel_server, four tabs
```

Cross-cutting changes outside the package, each small: the navigation entry and server mount in
`app.py`; a config field `analysis_roots`; the read-only widening in `Config.confine_path`; the
job-queue registration of the cache builder; docs and changelog.

## 4. Manifest (`boxmodel.json` in the project directory)

```json
{
  "schema": 1,
  "title": "Curonian Lagoon 29-box, 2-D",
  "boxes": {"polygons": "b29polys.gpkg", "layer": null, "id_field": "box"},
  "grid": {"grd": "curonian29.grd", "bas": "curonian29.bas", "boxes_txt": "boxes.txt"},
  "str": "curonian29_1993_2016.str",
  "forcing": {"dir": "fem_forcing"},
  "runs": [
    {"id": "run9316", "label": "1993-2016, corrected Minija", "dir": "/home/razinka/curonian/runs/run9316"},
    {"id": "run9314", "label": "1993-2014, pre-fix Minija",   "dir": "/home/razinka/curonian/runs/run9314"}
  ],
  "observations": {"file": "observations.csv", "sites": "sites.csv"}
}
```

Rules:
- Relative paths resolve against the project directory; absolute paths must resolve, after strict
  symlink resolution, under one of `config.analysis_roots` or the project directory. Anything else
  fails validation with the offending key named. Validation never opens the files.
- `boxes.polygons` is optional. When absent, box outlines are derived from `boxes_geom.txt` (element → box) and the `.grd` element triangles, dissolved per box; a polygon file gives cleaner outlines and is preferred.
- `runs[].id` is a slug (`[a-z0-9_-]+`, unique); it names the cache subdirectory.
- `observations.file` is long format, header `date,site,variable,value`, ISO dates, `variable`
  in `{salinity, temperature, level}`, units psu / °C / m. `sites` has header
  `site,lat,lon,box`; `box` is the model box the post represents. Sites without a box are shown
  on the map but excluded from skill.
- `forcing.dir` is optional; when present the setup tab lists `*.txt` river series (SHYFEM
  boundary time-series format, `YYYY-MM-DD::HH:MM:SS value`) found there.
- The manifest is created either by hand, by the project import (bundle), or by a small form on
  the page (title, polygons, sites, runs) that writes the file through the file service.

## 5. Box output formats (as written by SHYFEM 8.4 with `idtbox`)

`boxes_2d.txt`, one record per output step (hourly for `idtbox = '1h'`):

```
# time record
   <seconds since date0>      YYYY-MM-DD::HH:MM:SS
#      boxes       nvars
          29           7
# box      temp      salt cur_speed   act_eta  aver_eta   bstress        volume
   <29 lines: box temp salt cur_speed act_eta aver_eta bstress volume>
#   sections
          56
# section  from    to         total      positive      negative
   <56 lines: section from to total positive negative>
```
`from < 0` marks an open boundary (`-1` Baltic, `-2..-5` rivers in `$bound` order). `total =
positive − negative` (verified). Several interfaces may be split over more than one section.

`boxes_meteo.txt`: same envelope, 8 variables `srad tair rhum wspeed cc rain evap ice`.
`boxes_stats.txt`: `box layers area volume depth` plus start/end of simulation.
`boxes_geom.txt`: `element box area depth` (2027 rows) — used only to draw box outlines when no
polygon file is given (union of element triangles from the `.grd`). `*.box.flx` is a binary
SHYFEM flux file and is not read.

The parser streams line by line, never loads a file into memory, validates the `boxes`/`nvars`
headers on every record, and stops with the record number on any malformed line. It records the
run log's `program stop at time`, `cpu time (total)`, `simulation start` and the `iff_print_info`
forcing table when `run.log` is present.

## 6. Cache

Location: `<project_dir>/.boxmodel_cache/<run_id>/`. Contents:

| file | content |
|---|---|
| `state_daily.parquet` | `date, box, temp, salt, cur_speed, act_eta, aver_eta, bstress, volume` — daily mean, plus `_min`/`_max` columns for `temp`, `salt`, `act_eta` |
| `state_hourly.parquet` | the raw hourly records, float32, zstd — used for zoomed time series and the day slider at hourly resolution; optional (`--no-hourly`) |
| `flux_daily.parquet` | `date, section, from, to, total, positive, negative` daily means |
| `meteo_daily.parquet` | `date, box, srad, tair, rhum, wspeed, cc, rain, evap, ice` daily means |
| `meta.json` | period, record count, step, boxes, sections table (section→from,to), stats table (area/volume/depth), run-log facts, and for each source file its size and mtime |

Build: `python -m shyfem_ui.boxmodel.cache --run <dir> --out <cache_dir>` submitted through the
existing job queue as a job of a new kind `boxmodel-cache`, so it gets progress (records/total
from the file size), cancellation, persistence and the output-file record. The page shows the
cache state per run (missing / stale / building / ready) and a build button; stale means any
source size/mtime differs from `meta.json`. Sizes: for the 22-year Curonian run the daily cache
is ~2 MB, the hourly cache ~40 MB; the build reads 1.15 GB once (~2 min).

Pages read only the cache, through `cache.load(run_id) -> CachedRun` (pandas frames, lazily loaded
and memoised per session).

## 7. Observations and skill (`skill.py`)

Definitions are those of `shyfem_box/compare_runs.py` and `grid_summary.py` in the Curonian repo,
which are the source of truth; the test suite pins them against a shared fixture.

- Join: for a site with box `b` and variable `v`, model daily mean of `v` in box `b` on the
  observation's date. Column map: salinity→`salt`, temperature→`temp`, level→`act_eta`.
- Level is compared as an anomaly: each of the two series minus its own mean over the compared days
  (observations are cm above a local datum, the model is m against its own reference).
- Metrics per (site, variable, period): `n`, `bias`, `RMSE`, `r`, `R²`, `sd_mod/sd_obs`.
- Multi-run rule: every statistic uses the intersection of days all compared runs produced and the
  observations cover.
- Per-year table: the same metrics per calendar year.
- Presentation: amplitude is judged by `sd_mod/sd_obs` (1.00 is right) and phase by `r`; R² is
  shown but never used as a headline, and the table says so in its caption.

## 8. Page: "Box model" (`page.py`)

Header strip: project (implicit), run selector (manifest runs with cache state), variable, period
(date range within the run), cache build button. Tabs:

**Map.** Polygons from `polygons.py` (GeoPackage via fiona or GeoJSON; reprojected to WGS84;
one feature per box number) drawn with the grid-map component's polygon layer; colour by: the
value on the day chosen by a slider (daily cache; hourly when zoomed to ≤31 days and the hourly
cache exists), the period mean, or bias vs observations at the posts (posts as scatter markers,
coloured by bias). Hover: box, value. Legend from the existing legend widget. Clicking a box sets
the selected box for the time-series tab.

**Time series.** Selected box and variable, daily series for the period with min/max band,
observations of the mapped post overlaid, skill table for the period beneath, CSV export via the
existing time-series component's export path.

**Compare.** Choose 2–4 runs from the manifest; difference map (B − A of the period mean) for the
variable; overlaid series for the selected box; skill side by side and per-year table, all on the
intersection of days.

**Setup.** The mesh from `grid.grd` on the map (existing `.grd` parser and layers) with box
outlines; open-boundary nodes and river nodes read from the STR `$bound` blocks (`kbound`);
river series from `forcing.dir` as Plotly lines with the run window shaded; per-box meteo from the
cache; STR summary (period, `idt`, `idtbox`, selected `$para` values) via the existing STR parser.

All plots use `plotly_theme`; server code is a `@module.server` following the repo's page
pattern; reactive effects follow the compare-before-set rule (memory: reactive self-write loop).

## 9. Security and sharing

- `Config.analysis_roots: list[str]` (env `SHYFEM_UI_ANALYSIS_ROOTS`, path-separator list, default
  empty). In `confine_path`, when `for_write=False`, the resolved roots are appended to the allowed
  roots exactly as `testcases_dir` and `bin_dir` are today. Never for writes.
- Symlink resolution stays strict; a manifest path that resolves outside all roots is rejected.
- The cache directory is inside the project directory (user sandbox); the builder job runs under
  the same confinement as other jobs and only writes there.
- Sharing: unchanged. A shared project exposes its manifest; runs under analysis roots are
  readable by anyone who can open the project. Documented in the admin guide.
- Parsers enforce limits: manifest ≤ 64 KB, observations ≤ 50 MB, polygons ≤ 50 MB, box output
  streamed; any header mismatch aborts with the record number.
- The manifest form writes through the file service with the existing validation; no free path
  input reaches the filesystem un-confined.

## 10. Testing

- Fixture: `tests/boxmodel/_fixture.py` generates a synthetic run (3 boxes, 4 sections incl. one
  open boundary, 10 days hourly) plus `boxes_meteo.txt`, `boxes_stats.txt`, a `run.log` excerpt,
  a 3-polygon GeoJSON, `observations.csv` and `sites.csv`.
- Unit: parser (record structure, malformed line → error with record number, `layers > 1`
  refused); cache build → load round trip and staleness; flux aggregation (`total = positive −
  negative`, boundary sections); skill metrics vs hand-computed values (the fixture is small enough to compute by hand);
  the cross-check against `compare_runs.py` is a one-off script in the Curonian repo run on a
  real run and recorded in PR 4 — not a CI test, because that script reads the Curonian
  database schema; manifest validation
  (relative, absolute-under-root, escape, symlink escape); `confine_path` with analysis roots.
- Page wiring: `_test_helpers.get_server_source` assertions for the four tabs' handlers.
- E2E: one Playwright test importing the fixture project, building the cache, and asserting the
  map renders polygons and the skill table has a row.
- No large data in the repository.

## 11. Curonian onboarding (Curonian repo, `shyfem_box/export_ui_bundle.py`)

Writes `ui_bundle/` and zips it for the Workbench project import:
`boxmodel.json`; `observations.csv` from `physical_daily` (salinity, `wtemp_mean`, `wlevel_mean`
per site/date); `sites.csv` with the post→box mapping already used by the scripts (Klaipėda 11,
Juodkrantė 17, Nida 23, Ventė 25; Uostadvaris is exported with an empty box, so it is drawn on the map and excluded from
skill until someone confirms which box it represents); `b29polys.gpkg`;
`curonian29.grd/.bas`, `boxes.txt`; the STR; the four river `.txt`. Runs point at
`/home/razinka/curonian/runs/<run>`; laguna sets
`SHYFEM_UI_ANALYSIS_ROOTS=/home/razinka/curonian`. The 2016 run is added to the manifest when it
finishes.

## 12. Delivery

Four pull requests, each with tests: (1) manifest, parser, cache, config/confinement, Map and
Time-series tabs; (2) Compare; (3) Setup; (4) Curonian bundle script, admin docs, changelog.

## 13. Open points resolved

- Hourly cache is optional and off by default for runs longer than 5 years unless requested.
- Water-level observations in cm are converted to m on import (anomaly comparison makes the datum
  irrelevant, the unit is not).
- Runs with different box counts than the manifest polygons are rejected at cache-load time.
