# Box-model analysis, PR 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship PR 1 of the box-model analysis feature: a project manifest, streaming parsers for SHYFEM `idtbox` output, a child-process Parquet cache builder with registry and publish, admin-declared read-only analysis roots, a box-polygon map extension, and a new "Box model" page with the Map and Time-series tabs including observations and skill.

**Architecture:** Pure parsing lives in a root-level module `shyfem_ui/boxmodel_output.py` and the builder CLI `shyfem_ui/boxmodel_cache_cli.py` (root-level so `python -m` never imports `services/__init__.py`, which pulls in the ORM). Services under `shyfem_ui/services/boxmodel_*.py` handle the manifest, the build registry/publish/load, skill metrics and polygons. The page `shyfem_ui/pages/boxmodel.py` reads only the cache. The map component gains a per-box polygon layer with picking.

**Tech Stack:** Python 3.12/3.13, Shiny for Python (`@module.ui/@module.server`, `reactive`, `render`), shinywidgets + Plotly, pandas + pyarrow (Parquet), numpy, fiona + pyproj + shapely (polygons), shiny_deckgl (deck.gl layers), pytest (`asyncio_mode=auto`), Playwright for one E2E test.

**Spec:** `docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md` (revision 4). Two refinements this plan makes and why: (1) the parser and CLI are root-level modules, not `services/`, because importing anything under `services/` executes `services/__init__.py` (imports the workflow engine, ORM models and config) — the spec's own §6 requirement; (2) the map colours **box polygons** (dissolved from the mesh elements via element→box, or read from the polygon file) with a deck.gl `polygon_layer`, not per-element mesh colouring, because only per-object layers support picking the clicked box; the mesh wireframe stays underneath.

## Global Constraints

- Server-mode path confinement is `Config.confine_path(path, user, must_exist=..., for_write=...)`; analysis roots are appended **only** when `for_write=False`; local mode bypasses confinement (`deployment_mode != "server"`).
- `analysis_roots` is a `list[str]` config field read from env `SHYFEM_UI_ANALYSIS_ROOTS` as a JSON array (pydantic-settings default), default `[]`.
- Every write (manifest form, cache build, cancel) is gated by `editor_denied_reason(project_id, user, min_role="editor")` from `shyfem_ui.services.access_control`; the gate is inside the handler, hiding controls is cosmetic.
- No reactive state is touched off the Shiny event loop; the build child is awaited with `asyncio.create_subprocess_exec` + `start_new_session=True`; cancel = SIGTERM to the process group then SIGKILL (same as `ShyfemWrapper._terminate_process_group`).
- Parser caps: `boxes ≤ 10_000`, `sections ≤ 100_000`, line length ≤ 1024 bytes, `nvars` fixed per file type (state 7, meteo 8, stats 4, geom 3); manifest ≤ 64 KB; observations/polygons files ≤ 50 MB; observations ≤ 2 000 000 rows.
- Cache layout: `<project.work_dir>/.boxmodel_cache/<run_id>/` with `state_daily.parquet`, `flux_daily.parquet`, `meteo_daily.parquet`, optional `state_hourly.parquet`, `meta.json`; builds write to `<run_id>.tmp-<token>/` and are published by a two-step rename; `meta.json` stores relative source names only.
- Metric definitions (spec §7): daily mean = arithmetic mean of hourly records grouped by the stamped date; `bias = mean(m) − mean(o)`; `r` and `sd` with ddof = 0; `R² = 1 − Σ(m−o)²/Σ(o−ō)²`; level compared as an anomaly after obs cm → m; min n 30 (skill), 60 (per-year); a target with < 3 observation days is skipped; `level ≤ 0` rows dropped and counted.
- Text from manifests, labels and site names is rendered through `ui.tags`, never `ui.HTML`.
- Tests are flat under `shyfem-ui/tests/`; page wiring is asserted with `tests/_test_helpers.py::get_server_source`; Playwright tests are named `tests/test_playwright_*.py` and excluded from the default run.
- All commands below run from `/home/razinka/shyfem/shyfem-ui` with `CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest ...`; ruff and black (`shyfem_ui/` scope for CI, but run them on tests too).
- Commit style: conventional commits, one commit per task, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `shyfem_ui/boxmodel_output.py` (new) | Streaming parsers for `boxes_2d.txt`, `boxes_meteo.txt`, `boxes_stats.txt`, `boxes_geom.txt`, `run.log`; dataclasses; caps; `BoxOutputError`. No imports from `shyfem_ui.services`/`db`. |
| `shyfem_ui/boxmodel_cache_cli.py` (new) | `python -m shyfem_ui.boxmodel_cache_cli --run DIR --out DIR --trusted-base DIR [...] [--hourly]`: structural validation, daily aggregation, Parquet + `meta.json` + `progress.json`. Imports only `boxmodel_output`, stdlib, numpy, pandas, pyarrow. |
| `shyfem_ui/services/boxmodel_manifest.py` (new) | `load_manifest(project_dir, config, user)` → `BoxModelManifest`; path resolution through `confine_path`; size/schema checks. |
| `shyfem_ui/services/boxmodel_cache.py` (new) | Cache paths and state, `BuildRegistry`, `start_build`/`cancel_build` (child process), two-step `publish`, `reconcile_tmp_dirs`, `load_cache` → `CachedRun`. |
| `shyfem_ui/services/boxmodel_skill.py` (new) | Observation/sites loading with the import rules, `compute_metrics`, `band_amplitude_ratios`, `skill_table`. |
| `shyfem_ui/services/boxmodel_polygons.py` (new) | Box polygons in WGS84 from a GeoPackage/GeoJSON (driver allowlist, caps) or dissolved from a `.grd` + element→box. |
| `shyfem_ui/components/grid_map.py` (modify) | `build_box_layers(...)`; `grid_map_server` gains `extra_layers`/`on_box_click`; click branch for `box`. |
| `shyfem_ui/pages/boxmodel.py` (new) | `boxmodel_ui`, `boxmodel_server`: header strip, Map tab, Time-series tab, build/cancel, skill table, legend. |
| `shyfem_ui/config.py` (modify) | `analysis_roots` field, validator, `confine_path` widening. |
| `shyfem_ui/services/file_service.py` (modify) | `_sum_project_bytes` counts `.boxmodel_cache/`. |
| `shyfem_ui/app.py`, `shyfem_ui/pages/__init__.py` (modify) | Nav entry, page div, server mount, `__all__`. |
| `pyproject.toml`, `environment.yml` (modify) | `pyarrow>=15` dependency. |
| `tests/_boxmodel_fixture.py` (new) | Synthetic run + project fixture generator used by every test. |
| `tests/test_boxmodel_output.py`, `tests/test_boxmodel_cache_cli.py`, `tests/test_boxmodel_cache_service.py`, `tests/test_boxmodel_manifest.py`, `tests/test_boxmodel_skill.py`, `tests/test_boxmodel_polygons.py`, `tests/test_config_analysis_roots.py`, `tests/test_grid_map_box_layers.py`, `tests/test_boxmodel_page.py`, `tests/test_playwright_boxmodel.py` (new) | One test module per unit plus page wiring and E2E. |
| `docs/` admin note + `CHANGELOG.md` (modify) | Analysis roots documentation, changelog entry. |

---
### Task 1: Synthetic fixture generator

**Files:**
- Create: `shyfem-ui/tests/_boxmodel_fixture.py`
- Test: `shyfem-ui/tests/test_boxmodel_fixture.py`

**Interfaces:**
- Produces: `make_box_run(run_dir: Path, *, days: int = 10, boxes: int = 3, with_run_log: bool = True) -> dict` writing `boxes_2d.txt`, `boxes_meteo.txt`, `boxes_stats.txt`, `boxes_geom.txt`, `run.log` and returning `{"records": int, "sections": [(from, to), ...], "start": datetime, "end": datetime}`; `make_box_project(project_dir: Path, run_dir: Path, *, run_id: str = "fix", polygons: bool = True) -> Path` writing `fixture.grd`, `boxes.txt`, `box_polygons.geojson`, `observations.csv`, `sites.csv`, `boxmodel.json`; `value_at(var: str, box: int, stamp: datetime) -> float` — the deterministic value formula the tests use to compute expectations by hand.
- Grid: 8 nodes on a 2×4 lattice (lon 21.0 + 0.01·i, lat 55.5 + 0.01·j), 6 triangles; elements 1–2 → box 1, 3–4 → box 2, 5–6 → box 3. Sections: 1: 1→2, 2: 1→2 (split interface), 3: 2→3, 4: −1→1 (open boundary). Values: `temp = 10 + box + 0.1*hour`, `salt = 0.5*box + 0.01*hour`, `cur_speed = 0.01*box`, `act_eta = 0.001*(hour − 12)`, `aver_eta = act_eta/2`, `bstress = 0.0001*box`, `volume = 1e8*box`; fluxes for section s at hour h: `positive = 10*s + h`, `negative = s`, `total = positive − negative`. Meteo: `srad = 100 + hour`, `tair = 5 + box`, `rhum = 80`, `wspeed = 3`, `cc = 0.5`, `rain = 1`, `evap = 2`, `ice = 0`.
- Records: hourly from `2009-01-01::01:00:00` to `2009-01-(days+1)::00:00:00` inclusive, i.e. `24*days` records, `seconds = 3600*k` for `k = 1..24*days`.

- [ ] **Step 1: Write the failing test**

```python
# shyfem-ui/tests/test_boxmodel_fixture.py
from datetime import datetime
from pathlib import Path

from _boxmodel_fixture import make_box_project, make_box_run, value_at


def test_make_box_run_writes_all_files_with_real_envelope(tmp_path):
    info = make_box_run(tmp_path / "run")
    names = {p.name for p in (tmp_path / "run").iterdir()}
    assert {"boxes_2d.txt", "boxes_meteo.txt", "boxes_stats.txt", "boxes_geom.txt", "run.log"} <= names
    assert info["records"] == 240
    assert info["sections"] == [(1, 2), (1, 2), (2, 3), (-1, 1)]
    lines = (tmp_path / "run" / "boxes_2d.txt").read_text().splitlines()
    assert lines[0].startswith("#      idbox file_type     nvers")
    assert lines[1].split() == ["#", "473226", "2", "7"]
    assert lines[2] == "# time record"
    assert lines[3].split() == ["3600.0000000000000", "2009-01-01::01:00:00"]
    assert lines[6].startswith("# box      temp      salt cur_speed")
    assert value_at("temp", 2, datetime(2009, 1, 1, 5)) == 10 + 2 + 0.5


def test_make_box_project_writes_manifest_and_observations(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run)
    assert (proj / "boxmodel.json").exists()
    obs = (proj / "observations.csv").read_text().splitlines()
    assert obs[0] == "date,site,variable,value"
    assert any(",A,level,0" in line for line in obs)  # the zero sentinel row
    sites = (proj / "sites.csv").read_text().splitlines()
    assert sites[0] == "site,lat,lon,box"
    assert any(line.endswith(",") for line in sites[1:])  # unmapped site B
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_fixture.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '_boxmodel_fixture'`

- [ ] **Step 3: Write the fixture generator**

```python
# shyfem-ui/tests/_boxmodel_fixture.py
"""Synthetic SHYFEM box-model run + project used by every boxmodel test.

The envelope reproduces what SHYFEM 8.4 writes with ``idtbox`` (two-line
preamble, time record, ``boxes nvars`` header, section block). Values are
deterministic functions of (variable, box, hour) so tests can compute the
expected daily means by hand -- see ``value_at``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

IDBOX = 473226
STATE_VARS = ("temp", "salt", "cur_speed", "act_eta", "aver_eta", "bstress", "volume")
METEO_VARS = ("srad", "tair", "rhum", "wspeed", "cc", "rain", "evap", "ice")
SECTIONS = [(1, 2), (1, 2), (2, 3), (-1, 1)]          # (from, to); -1 = open boundary
ELEMENT_BOX = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}
NODES = {  # id: (lon, lat)
    1: (21.00, 55.50), 2: (21.01, 55.50), 3: (21.02, 55.50), 4: (21.03, 55.50),
    5: (21.00, 55.51), 6: (21.01, 55.51), 7: (21.02, 55.51), 8: (21.03, 55.51),
}
ELEMENTS = {1: (1, 2, 6), 2: (1, 6, 5), 3: (2, 3, 7), 4: (2, 7, 6), 5: (3, 4, 8), 6: (3, 8, 7)}
T0 = datetime(2009, 1, 1)


def value_at(var: str, box: int, stamp: datetime) -> float:
    h = stamp.hour
    return {
        "temp": 10 + box + 0.1 * h, "salt": 0.5 * box + 0.01 * h, "cur_speed": 0.01 * box,
        "act_eta": 0.001 * (h - 12), "aver_eta": 0.0005 * (h - 12), "bstress": 0.0001 * box,
        "volume": 1e8 * box,
        "srad": 100 + h, "tair": 5 + box, "rhum": 80.0, "wspeed": 3.0, "cc": 0.5,
        "rain": 1.0, "evap": 2.0, "ice": 0.0,
    }[var]


def flux_at(section: int, stamp: datetime) -> tuple[float, float, float]:
    positive = 10.0 * section + stamp.hour
    negative = float(section)
    return positive - negative, positive, negative


def _stamp(k: int) -> datetime:
    return T0 + timedelta(hours=k)


def _state_record(k: int, boxes: int) -> str:
    st = _stamp(k)
    out = ["# time record", f"   {3600.0 * k:.13f}      {st:%Y-%m-%d::%H:%M:%S}",
           "#      boxes       nvars", f"          {boxes}           7",
           "# box      temp      salt cur_speed   act_eta  aver_eta   bstress        volume"]
    for b in range(1, boxes + 1):
        v = [value_at(x, b, st) for x in STATE_VARS]
        out.append(f"{b:5d} {v[0]:9.5f} {v[1]:9.5f} {v[2]:9.5f} {v[3]:9.5f} {v[4]:9.5f} {v[5]:9.5f} {v[6]:13.6E}")
    out += ["#   sections", f"          {len(SECTIONS)}",
            "# section  from    to         total      positive      negative"]
    for s, (a, b) in enumerate(SECTIONS, start=1):
        t, p, n = flux_at(s, st)
        out.append(f"{s:9d} {a:5d} {b:5d}  {t:12.6E}  {p:12.6E}  {n:12.6E}")
    return "\n".join(out)


def _meteo_record(k: int, boxes: int) -> str:
    st = _stamp(k)
    out = ["# time record", f"   {3600.0 * k:.13f}      {st:%Y-%m-%d::%H:%M:%S}",
           "#      boxes       nvars", f"          {boxes}           8",
           "# box     srad    tair    rhum  wspeed      cc    rain    evap     ice"]
    for b in range(1, boxes + 1):
        v = [value_at(x, b, st) for x in METEO_VARS]
        out.append(f"{b:5d} " + " ".join(f"{x:7.3f}" for x in v))
    return "\n".join(out)


def _stats(boxes: int, days: int) -> str:
    end = _stamp(24 * days)
    out = ["#      idbox file_type     nvers", f"#     {IDBOX}         8         7",
           "# information on simulation", "    20090101           0", "        3600",
           f" start of simulation = {T0:%Y-%m-%d::%H:%M:%S}", f"   end of simulation = {end:%Y-%m-%d::%H:%M:%S}",
           "#      boxes       nvars", f"          {boxes}           4",
           "#    box  layers          area        volume       depth"]
    for b in range(1, boxes + 1):
        out.append(f"{b:8d}       1  {2e6 * b:12.6E}  {1e8 * b:12.6E}     {5.0 + b:7.4f}")
    out += ["#   sections", f"          {len(SECTIONS)}",
            "#    section        from          to         nls        nlb1        nlb2"]
    for s, (a, b) in enumerate(SECTIONS, start=1):
        out.append(f"{s:12d} {a:11d} {b:11d}           1           1           1")
    out += ["#  section details", f"          {len(SECTIONS)}"]
    for s, (a, b) in enumerate(SECTIONS, start=1):
        out += ["#    section       nodes    from-box      to-box      layers",
                f"{s:12d}           2 {a:11d} {b:11d}           1",
                "#       node node-number            x                y",
                f"           1 {2:11d}   {21.01:.7f}       {55.50:.7f}    ",
                f"           2 {6:11d}   {21.01:.7f}       {55.51:.7f}    "]
    return "\n".join(out) + "\n"


def _geom() -> str:
    out = ["#      idbox file_type     nvers", f"#     {IDBOX}         7         7",
           "#   elements       nvars", f"        {len(ELEMENTS)}           3",
           "#  element       box            area       depth"]
    for e, b in ELEMENT_BOX.items():
        out.append(f"{e:9d} {b:9d}  {1e6:14.8E}     {5.0 + b:7.4f}")
    return "\n".join(out) + "\n"


def _run_log(days: int) -> str:
    end = _stamp(24 * days)
    return "\n".join([
        " simulation start:   2026-09-17::00:40:54",
        " iff_print_info:",
        "   id  ibc unit nvar intp form descript   file",
        "    1    0   20    3    2    1 meteo wind                  fem_forcing/wind.fem",
        "    6    2   26    1    2    3 disch                    fem_forcing/nemunas.txt",
        "   11    2   -1    1    0   -1 temp                                            ",
        "",
        f" program stop at time = {end:%Y-%m-%d::%H:%M:%S}",
        " cpu time (total):             123.456",
        " simulation end:     2026-09-17::00:41:30",
        " simulation runtime: 36 s",
    ]) + "\n"


def make_box_run(run_dir: Path, *, days: int = 10, boxes: int = 3, with_run_log: bool = True) -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    n = 24 * days
    head2 = "#      idbox file_type     nvers\n"
    (run_dir / "boxes_2d.txt").write_text(
        head2 + f"#     {IDBOX}         2         7\n" + "\n".join(_state_record(k, boxes) for k in range(1, n + 1)) + "\n")
    (run_dir / "boxes_meteo.txt").write_text(
        head2 + f"#     {IDBOX}         1         7\n" + "\n".join(_meteo_record(k, boxes) for k in range(1, n + 1)) + "\n")
    (run_dir / "boxes_stats.txt").write_text(_stats(boxes, days))
    (run_dir / "boxes_geom.txt").write_text(_geom())
    if with_run_log:
        (run_dir / "run.log").write_text(_run_log(days))
    return {"records": n, "sections": list(SECTIONS), "start": T0, "end": _stamp(n)}


def _grd() -> str:
    out = ["0 fixture grid"]
    for nid, (x, y) in NODES.items():
        out.append(f"1 {nid} 0 {x:.5f} {y:.5f} {6.0:.2f}")
    for eid, (a, b, c) in ELEMENTS.items():
        out.append(f"2 {eid} 0 3 {a} {b} {c}")
    return "\n".join(out) + "\n"


def _geojson() -> dict:
    def ring(box):
        i = box - 1
        x0, x1 = 21.00 + 0.01 * i, 21.01 + 0.01 * i
        return [[x0, 55.50], [x1, 55.50], [x1, 55.51], [x0, 55.51], [x0, 55.50]]
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"box": b}, "geometry": {"type": "Polygon", "coordinates": [ring(b)]}}
        for b in (1, 2, 3)]}


def make_box_project(project_dir: Path, run_dir: Path, *, run_id: str = "fix", polygons: bool = True) -> Path:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "fixture.grd").write_text(_grd())
    (project_dir / "boxes.txt").write_text(
        f"{IDBOX} 9 3\n{len(ELEMENTS)} 3 3\n" + "\n".join(f"{e} {b}" for e, b in ELEMENT_BOX.items()) + "\n")
    if polygons:
        (project_dir / "box_polygons.geojson").write_text(json.dumps(_geojson()))
    obs = ["date,site,variable,value"]
    for d in range(1, 11):
        day = T0 + timedelta(days=d - 1)
        obs.append(f"{day:%Y-%m-%d},A,salinity,{0.5 + 0.01 * d:.3f}")
        obs.append(f"{day:%Y-%m-%d},A,temperature,{11.0 + 0.1 * d:.3f}")
        obs.append(f"{day:%Y-%m-%d},A,level,{500 + d}")
    obs.append("2009-01-05,A,level,0")           # zero sentinel -> dropped on load
    obs.append("2009-01-03,B,salinity,1.0")       # unmapped site
    (project_dir / "observations.csv").write_text("\n".join(obs) + "\n")
    (project_dir / "sites.csv").write_text("site,lat,lon,box\nA,55.505,21.005,1\nB,55.505,21.025,\n")
    manifest = {
        "schema": 1, "title": "Fixture lagoon",
        "boxes": {"polygons": "box_polygons.geojson" if polygons else None, "layer": None, "id_field": "box"},
        "grid": {"grd": "fixture.grd", "bas": None, "boxes_txt": "boxes.txt"},
        "str": None, "forcing": None,
        "runs": [{"id": run_id, "label": "fixture run", "dir": str(run_dir)}],
        "observations": {"file": "observations.csv", "sites": "sites.csv"},
    }
    (project_dir / "boxmodel.json").write_text(json.dumps(manifest, indent=1))
    return project_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_fixture.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/tests/_boxmodel_fixture.py shyfem-ui/tests/test_boxmodel_fixture.py
git commit -m "test(boxmodel): synthetic idtbox run and project fixture generator"
```

### Task 2: Streaming parsers for the box output files

**Files:**
- Create: `shyfem-ui/shyfem_ui/boxmodel_output.py`
- Test: `shyfem-ui/tests/test_boxmodel_output.py`

**Interfaces:**
- Consumes: the fixture from Task 1 (`make_box_run`, `value_at`, `flux_at`).
- Produces (all in `shyfem_ui.boxmodel_output`):
  - constants `STATE_VARS`, `METEO_VARS`, `FILE_TYPE_STATE = 2`, `FILE_TYPE_METEO = 1`, `FILE_TYPE_STATS = 8`, `FILE_TYPE_GEOM = 7`, `MAX_BOXES = 10_000`, `MAX_SECTIONS = 100_000`, `MAX_LINE_LENGTH = 1024`;
  - `class BoxOutputError(ValueError)`;
  - `@dataclass(frozen=True) class Preamble(idbox: int, file_type: int, nvers: int)`; `read_preamble(path: Path) -> Preamble`;
  - `@dataclass class StateRecord(seconds: float, stamp: datetime, box_ids: np.ndarray, values: np.ndarray, sections: np.ndarray)` — `values` shape `(nbox, 7)` in `STATE_VARS` order; `sections` shape `(nsec, 6)` = `section, from, to, total, positive, negative`;
  - `iter_state_records(path: Path) -> Iterator[StateRecord]`;
  - `@dataclass class MeteoRecord(seconds: float, stamp: datetime, box_ids: np.ndarray, values: np.ndarray)` — `(nbox, 8)` in `METEO_VARS` order; `iter_meteo_records(path: Path) -> Iterator[MeteoRecord]`;
  - `@dataclass class BoxStats(date0: int, time0: int, idtbox_seconds: int, start: datetime, end: datetime, boxes: pd.DataFrame, sections: pd.DataFrame, section_nodes: dict[int, list[tuple[float, float]]])` — `boxes` columns `box, layers, area, volume, depth`; `sections` columns `section, from_box, to_box, nls, nlb1, nlb2`; `read_stats(path: Path) -> BoxStats` (raises `BoxOutputError` when any `layers > 1`);
  - `read_geom(path: Path) -> pd.DataFrame` columns `element, box, area, depth`;
  - `@dataclass class RunLogFacts(simulation_start_wall: str | None, simulation_end_wall: str | None, simulation_runtime: str | None, cpu_total_seconds: float | None, program_stop_time: str | None, forcing: list[dict])`; `read_run_log(path: Path, *, head_bytes: int = 4_000_000, tail_bytes: int = 1_000_000) -> RunLogFacts`.

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_boxmodel_output.py
from datetime import datetime

import numpy as np
import pytest

from _boxmodel_fixture import flux_at, make_box_run, value_at
from shyfem_ui import boxmodel_output as bo


@pytest.fixture
def run(tmp_path):
    make_box_run(tmp_path / "run", days=2)
    return tmp_path / "run"


def test_preamble_and_file_type(run):
    pre = bo.read_preamble(run / "boxes_2d.txt")
    assert (pre.idbox, pre.file_type, pre.nvers) == (473226, bo.FILE_TYPE_STATE, 7)
    assert bo.read_preamble(run / "boxes_meteo.txt").file_type == bo.FILE_TYPE_METEO
    assert bo.read_preamble(run / "boxes_stats.txt").file_type == bo.FILE_TYPE_STATS
    assert bo.read_preamble(run / "boxes_geom.txt").file_type == bo.FILE_TYPE_GEOM


def test_iter_state_records_values_and_sections(run):
    recs = list(bo.iter_state_records(run / "boxes_2d.txt"))
    assert len(recs) == 48
    r = recs[4]                                       # seconds 5*3600 -> 05:00
    assert r.seconds == 5 * 3600 and r.stamp == datetime(2009, 1, 1, 5)
    assert list(r.box_ids) == [1, 2, 3] and r.values.shape == (3, 7)
    assert r.values[1, bo.STATE_VARS.index("temp")] == pytest.approx(value_at("temp", 2, r.stamp))
    assert r.sections.shape == (4, 6)
    t, p, n = flux_at(3, r.stamp)
    assert r.sections[2].tolist() == pytest.approx([3, 2, 3, t, p, n])
    assert r.sections[3, 1] == -1                     # open boundary


def test_state_record_with_wrong_file_type_is_refused(run):
    with pytest.raises(bo.BoxOutputError, match="file_type"):
        list(bo.iter_state_records(run / "boxes_meteo.txt"))


def test_malformed_box_line_reports_record_number(run):
    p = run / "boxes_2d.txt"
    lines = p.read_text().splitlines()
    # record 3 starts at line index 2 + 2*10 (10 lines per record: 5 header + 3 boxes ... ) -> corrupt its second box line
    idx = next(i for i, l in enumerate(lines) if l.startswith("   10800.")) + 4
    lines[idx] = "    2   nan_here"
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(bo.BoxOutputError, match="record 3"):
        list(bo.iter_state_records(p))


def test_duplicate_box_in_record_is_refused(run):
    p = run / "boxes_2d.txt"
    lines = p.read_text().splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("    2 "))
    lines[idx] = "    1" + lines[idx][5:]
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(bo.BoxOutputError, match="duplicate box"):
        list(bo.iter_state_records(p))


def test_iter_meteo_records(run):
    recs = list(bo.iter_meteo_records(run / "boxes_meteo.txt"))
    assert len(recs) == 48 and recs[0].values.shape == (3, 8)
    assert recs[7].values[0, bo.METEO_VARS.index("srad")] == pytest.approx(100 + 8)


def test_read_stats(run):
    st = bo.read_stats(run / "boxes_stats.txt")
    assert (st.date0, st.time0, st.idtbox_seconds) == (20090101, 0, 3600)
    assert st.start == datetime(2009, 1, 1) and st.end == datetime(2009, 1, 3)
    assert st.boxes["box"].tolist() == [1, 2, 3] and st.boxes["layers"].max() == 1
    assert st.sections[["from_box", "to_box"]].values.tolist() == [[1, 2], [1, 2], [2, 3], [-1, 1]]
    assert st.section_nodes[1] == [(21.01, 55.50), (21.01, 55.51)]


def test_read_stats_refuses_3d(run):
    p = run / "boxes_stats.txt"
    p.write_text(p.read_text().replace("       1       1  ", "       1       3  ", 1))
    with pytest.raises(bo.BoxOutputError, match="layers"):
        bo.read_stats(p)


def test_read_geom(run):
    g = bo.read_geom(run / "boxes_geom.txt")
    assert g["element"].tolist() == [1, 2, 3, 4, 5, 6] and g["box"].tolist() == [1, 1, 2, 2, 3, 3]


def test_read_run_log_facts(run):
    f = bo.read_run_log(run / "run.log")
    assert f.simulation_start_wall == "2026-09-17::00:40:54"
    assert f.program_stop_time == "2009-01-03::00:00:00"
    assert f.cpu_total_seconds == pytest.approx(123.456)
    assert f.simulation_runtime == "36 s"
    assert [x["file"] for x in f.forcing] == ["fem_forcing/wind.fem", "fem_forcing/nemunas.txt", ""]
    assert f.forcing[0]["descript"] == "meteo wind" and f.forcing[2]["unit"] == -1


def test_read_run_log_streams_large_file(run, monkeypatch):
    p = run / "run.log"
    body = p.read_text()
    head, tail = body.split(" program stop", 1)
    p.write_text(head + ("*** boxes mass error 2d: 1.0E-03\n" * 200_000) + " program stop" + tail)
    f = bo.read_run_log(p, head_bytes=4096, tail_bytes=4096)
    assert f.program_stop_time == "2009-01-03::00:00:00" and f.simulation_start_wall == "2026-09-17::00:40:54"


def test_caps_are_enforced(run, monkeypatch):
    monkeypatch.setattr(bo, "MAX_BOXES", 2)
    with pytest.raises(bo.BoxOutputError, match="boxes"):
        list(bo.iter_state_records(run / "boxes_2d.txt"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_output.py -v`
Expected: FAIL with `ImportError: cannot import name 'boxmodel_output'`

- [ ] **Step 3: Write the parser module**

```python
# shyfem-ui/shyfem_ui/boxmodel_output.py
"""Streaming readers for SHYFEM box-model (``idtbox``) output.

Formats verified on real 8.4 output (spec §5). Everything streams line by
line; nothing here imports ``shyfem_ui.services`` or ``shyfem_ui.db`` -- the
cache-builder child process imports this module and must stay light.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

STATE_VARS = ("temp", "salt", "cur_speed", "act_eta", "aver_eta", "bstress", "volume")
METEO_VARS = ("srad", "tair", "rhum", "wspeed", "cc", "rain", "evap", "ice")
FILE_TYPE_STATE, FILE_TYPE_METEO, FILE_TYPE_STATS, FILE_TYPE_GEOM = 2, 1, 8, 7
MAX_BOXES = 10_000
MAX_SECTIONS = 100_000
MAX_LINE_LENGTH = 1024
_STAMP = "%Y-%m-%d::%H:%M:%S"


class BoxOutputError(ValueError):
    """Malformed or out-of-policy box output; the message names file and record."""


@dataclass(frozen=True)
class Preamble:
    idbox: int
    file_type: int
    nvers: int


@dataclass
class StateRecord:
    seconds: float
    stamp: datetime
    box_ids: np.ndarray
    values: np.ndarray          # (nbox, 7) in STATE_VARS order
    sections: np.ndarray        # (nsec, 6): section, from, to, total, positive, negative


@dataclass
class MeteoRecord:
    seconds: float
    stamp: datetime
    box_ids: np.ndarray
    values: np.ndarray          # (nbox, 8) in METEO_VARS order


@dataclass
class BoxStats:
    date0: int
    time0: int
    idtbox_seconds: int
    start: datetime
    end: datetime
    boxes: pd.DataFrame
    sections: pd.DataFrame
    section_nodes: dict[int, list[tuple[float, float]]] = field(default_factory=dict)


@dataclass
class RunLogFacts:
    simulation_start_wall: str | None = None
    simulation_end_wall: str | None = None
    simulation_runtime: str | None = None
    cpu_total_seconds: float | None = None
    program_stop_time: str | None = None
    forcing: list[dict] = field(default_factory=list)


def _lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line_number, stripped line) enforcing the line-length cap."""
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        for n, raw in enumerate(fh, start=1):
            if len(raw) > MAX_LINE_LENGTH:
                raise BoxOutputError(f"{path.name}: line {n} exceeds {MAX_LINE_LENGTH} bytes")
            yield n, raw.rstrip("\n")


def read_preamble(path: Path) -> Preamble:
    it = _lines(path)
    try:
        _, l1 = next(it)
        _, l2 = next(it)
    except StopIteration as e:
        raise BoxOutputError(f"{path.name}: truncated preamble") from e
    if not l1.lstrip().startswith("#") or "idbox" not in l1:
        raise BoxOutputError(f"{path.name}: missing idbox preamble")
    g = l2.split()
    if len(g) != 4 or g[0] != "#":
        raise BoxOutputError(f"{path.name}: malformed preamble line 2")
    return Preamble(int(g[1]), int(g[2]), int(g[3]))


def _expect_preamble(path: Path, file_type: int) -> None:
    pre = read_preamble(path)
    if pre.file_type != file_type:
        raise BoxOutputError(f"{path.name}: file_type {pre.file_type}, expected {file_type}")


def _parse_stamp(g: list[str], path: Path, rec: int) -> tuple[float, datetime]:
    if len(g) != 2:
        raise BoxOutputError(f"{path.name}: record {rec}: bad time line")
    try:
        return float(g[0]), datetime.strptime(g[1], _STAMP)
    except ValueError as e:
        raise BoxOutputError(f"{path.name}: record {rec}: bad time stamp") from e


def _read_block(it, path: Path, rec: int, count: int, ncols: int, label: str) -> np.ndarray:
    """Read `count` numeric lines of `ncols` fields; duplicate first-column ids abort."""
    out = np.empty((count, ncols), dtype=float)
    seen: set[int] = set()
    for i in range(count):
        try:
            n, line = next(it)
        except StopIteration as e:
            raise BoxOutputError(f"{path.name}: record {rec}: truncated {label} block") from e
        g = line.split()
        if len(g) != ncols:
            raise BoxOutputError(f"{path.name}: record {rec}: malformed {label} line {n}")
        try:
            row = [float(x) for x in g]
        except ValueError as e:
            raise BoxOutputError(f"{path.name}: record {rec}: malformed {label} line {n}") from e
        key = int(row[0])
        if key in seen:
            raise BoxOutputError(f"{path.name}: record {rec}: duplicate {label} id {key}")
        seen.add(key)
        out[i] = row
    return out


def _iter_records(path: Path, file_type: int, nvars: int, with_sections: bool):
    _expect_preamble(path, file_type)
    it = _lines(path)
    next(it); next(it)                                    # preamble
    rec = 0
    for n, line in it:
        if line.strip() != "# time record":
            if line.strip() == "":
                continue
            raise BoxOutputError(f"{path.name}: record {rec + 1}: expected '# time record' at line {n}")
        rec += 1
        _, tl = next(it)
        seconds, stamp = _parse_stamp(tl.split(), path, rec)
        _, hdr = next(it)
        if "boxes" not in hdr:
            raise BoxOutputError(f"{path.name}: record {rec}: expected boxes header")
        _, cnt = next(it)
        g = cnt.split()
        if len(g) != 2 or int(g[1]) != nvars:
            raise BoxOutputError(f"{path.name}: record {rec}: expected nvars={nvars}, got {cnt.strip()!r}")
        nbox = int(g[0])
        if nbox <= 0 or nbox > MAX_BOXES:
            raise BoxOutputError(f"{path.name}: record {rec}: boxes={nbox} outside 1..{MAX_BOXES}")
        next(it)                                            # '# box ...' column header
        block = _read_block(it, path, rec, nbox, nvars + 1, "box")
        box_ids = block[:, 0].astype(int)
        values = block[:, 1:]
        sections = np.empty((0, 6))
        if with_sections:
            _, sh = next(it)
            if "sections" not in sh:
                raise BoxOutputError(f"{path.name}: record {rec}: expected sections header")
            _, sc = next(it)
            nsec = int(sc.split()[0])
            if nsec < 0 or nsec > MAX_SECTIONS:
                raise BoxOutputError(f"{path.name}: record {rec}: sections={nsec} outside 0..{MAX_SECTIONS}")
            next(it)                                        # '# section from to ...'
            sections = _read_block(it, path, rec, nsec, 6, "section")
        yield seconds, stamp, box_ids, values, sections


def iter_state_records(path: Path) -> Iterator[StateRecord]:
    for seconds, stamp, ids, values, sections in _iter_records(path, FILE_TYPE_STATE, 7, True):
        yield StateRecord(seconds, stamp, ids, values, sections)


def iter_meteo_records(path: Path) -> Iterator[MeteoRecord]:
    for seconds, stamp, ids, values, _ in _iter_records(path, FILE_TYPE_METEO, 8, False):
        yield MeteoRecord(seconds, stamp, ids, values)


def read_stats(path: Path) -> BoxStats:
    _expect_preamble(path, FILE_TYPE_STATS)
    lines = [l for _, l in _lines(path)][2:]
    i = 0
    def take():
        nonlocal i
        i += 1
        return lines[i - 1]
    if "information on simulation" not in take():
        raise BoxOutputError(f"{path.name}: expected simulation information block")
    d0 = take().split(); date0, time0 = int(d0[0]), int(d0[1])
    idtbox = int(float(take().split()[0]))
    start = datetime.strptime(take().split("=")[1].strip(), _STAMP)
    end = datetime.strptime(take().split("=")[1].strip(), _STAMP)
    take()                                                  # '#      boxes       nvars'
    nbox = int(take().split()[0])
    if nbox <= 0 or nbox > MAX_BOXES:
        raise BoxOutputError(f"{path.name}: boxes={nbox} outside 1..{MAX_BOXES}")
    take()                                                  # column header
    rows = [take().split() for _ in range(nbox)]
    boxes = pd.DataFrame(rows, columns=["box", "layers", "area", "volume", "depth"]).astype(
        {"box": int, "layers": int, "area": float, "volume": float, "depth": float})
    if (boxes["layers"] > 1).any():
        raise BoxOutputError(f"{path.name}: layers > 1 (3-D box output is not supported)")
    take()                                                  # '#   sections'
    nsec = int(take().split()[0])
    if nsec > MAX_SECTIONS:
        raise BoxOutputError(f"{path.name}: sections={nsec} exceeds {MAX_SECTIONS}")
    take()
    srows = [take().split() for _ in range(nsec)]
    sections = pd.DataFrame(srows, columns=["section", "from_box", "to_box", "nls", "nlb1", "nlb2"]).astype(int)
    section_nodes: dict[int, list[tuple[float, float]]] = {}
    if i < len(lines) and "section details" in lines[i]:
        take(); take()                                      # header + count
        for _ in range(nsec):
            take()                                          # '#    section nodes from-box to-box layers'
            g = take().split(); sec, nn = int(g[0]), int(g[1])
            take()                                          # '#       node node-number x y'
            pts = []
            for _ in range(nn):
                h = take().split()
                pts.append((float(h[2]), float(h[3])))
            section_nodes[sec] = pts
    return BoxStats(date0, time0, idtbox, start, end, boxes, sections, section_nodes)


def read_geom(path: Path) -> pd.DataFrame:
    _expect_preamble(path, FILE_TYPE_GEOM)
    lines = [l for _, l in _lines(path)][2:]
    nel = int(lines[1].split()[0])
    rows = [l.split() for l in lines[3:3 + nel]]
    if len(rows) != nel or any(len(r) != 4 for r in rows):
        raise BoxOutputError(f"{path.name}: malformed element table")
    return pd.DataFrame(rows, columns=["element", "box", "area", "depth"]).astype(
        {"element": int, "box": int, "area": float, "depth": float})


_IFF_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(-?\d+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)\s+(.*)$")


def read_run_log(path: Path, *, head_bytes: int = 4_000_000, tail_bytes: int = 1_000_000) -> RunLogFacts:
    """Read the head (forcing table, wall-clock start) and the tail (stop, cpu) of a
    possibly huge log without loading it."""
    facts = RunLogFacts()
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read(head_bytes).decode("ascii", errors="replace")
        if size > head_bytes:
            fh.seek(max(size - tail_bytes, head_bytes))
            tail = fh.read().decode("ascii", errors="replace")
        else:
            tail = ""
    in_iff = False
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("simulation start:"):
            facts.simulation_start_wall = s.split(":", 1)[1].strip()
        elif s.startswith("iff_print_info"):
            in_iff = True
            continue
        elif in_iff:
            if s.startswith("id ") or s.startswith("id\t"):
                continue
            m = _IFF_ROW.match(line)
            if not m:
                in_iff = False
                continue
            rest = m.group(7).rstrip()
            parts = rest.split()
            file_ = parts[-1] if parts and ("/" in parts[-1] or "." in parts[-1]) else ""
            descript = rest[: len(rest) - len(file_)].strip() if file_ else rest.strip()
            facts.forcing.append({"id": int(m.group(1)), "ibc": int(m.group(2)), "unit": int(m.group(3)),
                                  "nvar": int(m.group(4)), "intp": int(m.group(5)), "form": int(m.group(6)),
                                  "descript": descript, "file": file_})
    for line in (tail or head).splitlines():
        s = line.strip()
        if s.startswith("program stop at time"):
            facts.program_stop_time = s.split("=", 1)[1].strip()
        elif s.startswith("cpu time (total)"):
            facts.cpu_total_seconds = float(s.split(":", 1)[1])
        elif s.startswith("simulation end:"):
            facts.simulation_end_wall = s.split(":", 1)[1].strip()
        elif s.startswith("simulation runtime:"):
            facts.simulation_runtime = s.split(":", 1)[1].strip()
    return facts
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_output.py -v`
Expected: 11 passed. If `test_malformed_box_line_reports_record_number` fails on the index arithmetic, print the lines around `10800.` and adjust the `+ 4` offset so the corrupted line is a box line of record 3 (the header is five lines: `# time record`, the stamp, `#      boxes       nvars`, the counts, `# box ...`).

- [ ] **Step 5: Lint and commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/boxmodel_output.py tests/test_boxmodel_output.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/boxmodel_output.py tests/test_boxmodel_output.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/boxmodel_output.py shyfem-ui/tests/test_boxmodel_output.py
git commit -m "feat(boxmodel): streaming parsers for SHYFEM idtbox output files"
```

### Task 3: `analysis_roots` config field, validation and read-only confinement

**Files:**
- Modify: `shyfem-ui/shyfem_ui/config.py` (field near `trusted_proxies` ~line 269; validator after `_check_server_mode_passwords` ~line 223; `confine_path` allowed-roots block ~lines 478-480)
- Test: `shyfem-ui/tests/test_config_analysis_roots.py`

**Interfaces:**
- Produces: `Config.analysis_roots: list[str]` (validated, resolved absolute strings); `Config.resolved_analysis_roots() -> list[Path]`; `confine_path(..., for_write=False)` accepts paths under those roots in server mode.

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_config_analysis_roots.py
from pathlib import Path

import pytest

from shyfem_ui.config import Config


def _server_cfg(tmp_path, roots, **kw):
    udr = tmp_path / "users"; wd = tmp_path / "projects"; udr.mkdir(); wd.mkdir()
    return Config(_env_file=None, deployment_mode="server", default_admin_password="x" * 12,
                  user_data_root=udr, work_dir=wd, shyfem_dir=tmp_path / "shyfem",
                  database_url=f"sqlite:///{tmp_path / 'db' / 'ui.db'}", analysis_roots=roots, **kw)


def test_default_is_empty(tmp_path):
    assert _server_cfg(tmp_path, []).analysis_roots == []


def test_roots_are_resolved_and_kept(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    cfg = _server_cfg(tmp_path, [str(root)])
    assert cfg.resolved_analysis_roots() == [root.resolve()]


@pytest.mark.parametrize("bad", ["/", "{tmp}/users", "{tmp}/users/alice", "{tmp}", "{tmp}/projects", "/tmp", "{tmp}/db"])
def test_overlapping_or_forbidden_roots_are_rejected(tmp_path, bad):
    (tmp_path / "users" / "alice").mkdir(parents=True, exist_ok=True)
    (tmp_path / "db").mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="analysis_roots"):
        _server_cfg(tmp_path, [bad.format(tmp=tmp_path)])


def test_missing_root_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="analysis_roots"):
        _server_cfg(tmp_path, [str(tmp_path / "nope")])


def test_local_mode_ignores_roots(tmp_path):
    cfg = Config(_env_file=None, deployment_mode="local", work_dir=tmp_path, analysis_roots=["/definitely/missing"])
    assert cfg.analysis_roots == ["/definitely/missing"]      # not validated, not used


def test_confine_path_reads_under_root_but_never_writes(tmp_path):
    root = tmp_path / "data"; (root / "run").mkdir(parents=True)
    cfg = _server_cfg(tmp_path, [str(root)])
    (cfg.user_data_root / "alice").mkdir()
    user = {"id": 1, "username": "alice", "role": "user"}
    assert cfg.confine_path(root / "run", user, must_exist=True) == (root / "run").resolve()
    with pytest.raises(ValueError):
        cfg.confine_path(root / "run", user, for_write=True)


def test_confine_path_symlink_from_root_into_sandbox_is_rejected(tmp_path):
    root = tmp_path / "data"; root.mkdir()
    cfg = _server_cfg(tmp_path, [str(root)])
    (cfg.user_data_root / "bob").mkdir(); (cfg.user_data_root / "bob" / "secret.txt").write_text("s")
    (root / "link").symlink_to(cfg.user_data_root / "bob" / "secret.txt")
    user = {"id": 1, "username": "alice", "role": "user"}
    (cfg.user_data_root / "alice").mkdir()
    with pytest.raises(ValueError):
        cfg.confine_path(root / "link", user, must_exist=True)


def test_env_var_is_a_json_array(tmp_path, monkeypatch):
    root = tmp_path / "data"; root.mkdir()
    monkeypatch.setenv("SHYFEM_UI_ANALYSIS_ROOTS", f'["{root}"]')
    udr = tmp_path / "users"; wd = tmp_path / "projects"; udr.mkdir(exist_ok=True); wd.mkdir(exist_ok=True)
    cfg = Config(_env_file=None, deployment_mode="server", default_admin_password="x" * 12,
                 user_data_root=udr, work_dir=wd, shyfem_dir=tmp_path / "shyfem",
                 database_url=f"sqlite:///{tmp_path / 'db' / 'ui.db'}")
    assert cfg.resolved_analysis_roots() == [root.resolve()]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config_analysis_roots.py -v`
Expected: FAIL — `ValidationError ... analysis_roots Extra inputs are not permitted` (or `AttributeError: resolved_analysis_roots`)

- [ ] **Step 3: Add the field, the validator and the confinement widening**

Add the field next to `trusted_proxies` in `Config`:

```python
    analysis_roots: list[str] = Field(
        default_factory=list,
        description=(
            "Admin-declared directories readable (never writable) by EVERY authenticated "
            "user in server mode, for box-model run outputs kept outside the sandbox. "
            "JSON array in the environment, e.g. SHYFEM_UI_ANALYSIS_ROOTS='[\"/data/runs\"]'. "
            "Each must exist and must not overlap the user data root, the work dir, the "
            "SHYFEM dir, the database directory or /tmp. Ignored in local mode."
        ),
    )
```

Add a second `model_validator` right after `_check_server_mode_passwords`:

```python
    @model_validator(mode="after")
    def _check_analysis_roots(self):
        """Resolve and vet analysis roots (server mode only; local mode never uses them)."""
        if self.deployment_mode != "server" or not self.analysis_roots:
            return self
        forbidden = [Path("/"), Path("/tmp").resolve(), self.user_data_root.resolve(),
                     Path(self.work_dir).resolve(), Path(self.shyfem_dir).resolve()]
        if self.database_url.startswith("sqlite:///"):
            forbidden.append(Path(self.database_url[len("sqlite:///"):]).resolve().parent)
        resolved: list[str] = []
        for raw in self.analysis_roots:
            try:
                root = Path(raw).expanduser().resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as e:
                raise ValueError(f"analysis_roots: {raw!r} does not resolve to an existing directory") from e
            if not root.is_dir():
                raise ValueError(f"analysis_roots: {raw!r} is not a directory")
            for f in forbidden:
                if root == f or str(root).startswith(str(f) + "/") or str(f).startswith(str(root) + "/"):
                    raise ValueError(f"analysis_roots: {raw!r} overlaps a protected location ({f})")
            resolved.append(str(root))
        self.analysis_roots = resolved
        import logging
        logging.getLogger(__name__).info("analysis_roots accepted: %s", resolved)
        return self

    def resolved_analysis_roots(self) -> list[Path]:
        """The validated roots as Paths (empty outside server mode)."""
        if self.deployment_mode != "server":
            return []
        return [Path(r) for r in self.analysis_roots]
```

In `confine_path`, change the read-only widening block to:

```python
        allowed_roots = [home]
        if not for_write:
            # Read-only bundled assets stay reachable for reads (tutorials/examples),
            # plus the admin-declared analysis roots (box-model run outputs).
            allowed_roots += [self.testcases_dir.resolve(), self.bin_dir.resolve()]
            allowed_roots += self.resolved_analysis_roots()
```

- [ ] **Step 4: Run the new tests and the existing config tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config_analysis_roots.py tests/test_config.py tests/test_path_confinement.py -v`
Expected: all pass (the symlink test passes because `resolve(strict=True)` follows the link to `bob/secret.txt`, which is outside every allowed root).

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/config.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/config.py tests/test_config_analysis_roots.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/config.py shyfem-ui/tests/test_config_analysis_roots.py
git commit -m "feat(config): admin-declared read-only analysis roots for box-model outputs"
```

### Task 4: Manifest service

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/boxmodel_manifest.py`
- Test: `shyfem-ui/tests/test_boxmodel_manifest.py`

**Interfaces:**
- Consumes: `Config.confine_path`, `Config.resolved_analysis_roots()` (Task 3); fixture `make_box_project` (Task 1).
- Produces: `MANIFEST_NAME = "boxmodel.json"`, `MAX_MANIFEST_BYTES = 65_536`, `class ManifestError(ValueError)`, `@dataclass RunEntry(id: str, label: str, dir: Path)`, `@dataclass BoxModelManifest(title: str, polygons: Path | None, polygons_layer: str | None, id_field: str, grd: Path, bas: Path | None, boxes_txt: Path | None, str_path: Path | None, forcing_dir: Path | None, runs: list[RunEntry], observations: Path | None, sites: Path | None)`, `load_manifest(project_dir: Path, config: Config, user: dict | None) -> BoxModelManifest`.

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_boxmodel_manifest.py
import json
from pathlib import Path

import pytest

from _boxmodel_fixture import make_box_project, make_box_run
from shyfem_ui.config import Config
from shyfem_ui.services import boxmodel_manifest as bm


@pytest.fixture
def local_cfg(tmp_path):
    return Config(_env_file=None, deployment_mode="local", work_dir=tmp_path)


@pytest.fixture
def project(tmp_path):
    run = tmp_path / "runs" / "fix"; make_box_run(run, days=1)
    return make_box_project(tmp_path / "proj", run)


def test_loads_relative_and_absolute_paths_local_mode(project, local_cfg):
    m = bm.load_manifest(project, local_cfg, None)
    assert m.title == "Fixture lagoon" and m.grd == (project / "fixture.grd").resolve()
    assert m.runs[0].id == "fix" and m.runs[0].dir.name == "fix"
    assert m.polygons == (project / "box_polygons.geojson").resolve() and m.id_field == "box"


def test_missing_manifest_is_a_clear_error(tmp_path, local_cfg):
    with pytest.raises(bm.ManifestError, match="boxmodel.json"):
        bm.load_manifest(tmp_path, local_cfg, None)


def test_oversized_manifest_rejected(project, local_cfg):
    (project / "boxmodel.json").write_text("{" + " " * bm.MAX_MANIFEST_BYTES + "}")
    with pytest.raises(bm.ManifestError, match="64 KB"):
        bm.load_manifest(project, local_cfg, None)


def test_invalid_json_and_schema(project, local_cfg):
    (project / "boxmodel.json").write_text("{not json")
    with pytest.raises(bm.ManifestError, match="JSON"):
        bm.load_manifest(project, local_cfg, None)
    (project / "boxmodel.json").write_text(json.dumps({"schema": 2, "runs": []}))
    with pytest.raises(bm.ManifestError, match="schema"):
        bm.load_manifest(project, local_cfg, None)


def test_run_id_must_be_a_unique_slug(project, local_cfg):
    d = json.loads((project / "boxmodel.json").read_text())
    d["runs"].append(dict(d["runs"][0])); d["runs"][1]["id"] = "Bad Id!"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="runs\\[1\\].id"):
        bm.load_manifest(project, local_cfg, None)
    d["runs"][1]["id"] = "fix"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="unique"):
        bm.load_manifest(project, local_cfg, None)


def test_server_mode_absolute_run_dir_must_be_under_a_root(tmp_path):
    udr = tmp_path / "users"; (udr / "alice").mkdir(parents=True); wd = tmp_path / "projects"; wd.mkdir()
    root = tmp_path / "data"; run = root / "runs" / "fix"; make_box_run(run, days=1)
    proj = make_box_project(udr / "alice" / "proj", run)
    user = {"id": 1, "username": "alice", "role": "user"}
    ok = Config(_env_file=None, deployment_mode="server", default_admin_password="x" * 12, user_data_root=udr,
                work_dir=wd, shyfem_dir=tmp_path / "shyfem", database_url=f"sqlite:///{tmp_path/'db'/'ui.db'}",
                analysis_roots=[str(root)])
    assert bm.load_manifest(proj, ok, user).runs[0].dir == run.resolve()
    no_root = Config(_env_file=None, deployment_mode="server", default_admin_password="x" * 12, user_data_root=udr,
                     work_dir=wd, shyfem_dir=tmp_path / "shyfem", database_url=f"sqlite:///{tmp_path/'db'/'ui.db'}")
    with pytest.raises(bm.ManifestError, match="runs\\[0\\].dir"):
        bm.load_manifest(proj, no_root, user)


def test_paths_may_not_escape_the_project(project, local_cfg, tmp_path):
    d = json.loads((project / "boxmodel.json").read_text())
    d["grid"]["grd"] = "../../etc/passwd"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="grid.grd"):
        bm.load_manifest(project, local_cfg, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_manifest.py -v`
Expected: FAIL with `ImportError: cannot import name 'boxmodel_manifest'`

- [ ] **Step 3: Write the manifest service**

```python
# shyfem-ui/shyfem_ui/services/boxmodel_manifest.py
"""Load and validate a project's ``boxmodel.json`` (spec §4).

Validation resolves paths through ``Config.confine_path`` (read-only) but
opens nothing; every consumer re-checks at open time. Errors are
``ManifestError`` with the offending key, meant for a page-level message.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from shyfem_ui.config import Config

MANIFEST_NAME = "boxmodel.json"
MAX_MANIFEST_BYTES = 65_536
_SLUG = re.compile(r"^[a-z0-9_-]+$")
_VARIABLES = ("salinity", "temperature", "level")


class ManifestError(ValueError):
    """User-facing manifest problem; the message names the key."""


@dataclass(frozen=True)
class RunEntry:
    id: str
    label: str
    dir: Path


@dataclass
class BoxModelManifest:
    title: str
    polygons: Path | None
    polygons_layer: str | None
    id_field: str
    grd: Path
    bas: Path | None
    boxes_txt: Path | None
    str_path: Path | None
    forcing_dir: Path | None
    runs: list[RunEntry] = field(default_factory=list)
    observations: Path | None = None
    sites: Path | None = None


def _resolve(value, key: str, project_dir: Path, config: Config, user: dict | None, *, required: bool) -> Path | None:
    if value in (None, ""):
        if required:
            raise ManifestError(f"{key}: required")
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ManifestError(f"{key}: must be a path string")
    raw = Path(value)
    candidate = raw if raw.is_absolute() else project_dir / raw
    resolved = candidate.expanduser().resolve()
    proj = project_dir.resolve()
    inside_project = resolved == proj or str(resolved).startswith(str(proj) + "/")
    if config.deployment_mode == "server":
        if not inside_project:
            roots = config.resolved_analysis_roots()
            if not any(resolved == r or str(resolved).startswith(str(r) + "/") for r in roots):
                raise ManifestError(f"{key}: {config.display_path(resolved, user)} is outside the project and every analysis root")
        try:
            return config.confine_path(resolved, user, must_exist=False, for_write=False)
        except ValueError as e:
            raise ManifestError(f"{key}: {e}") from e
    if not inside_project:
        raise ManifestError(f"{key}: must stay inside the project directory in local mode")
    return resolved


def load_manifest(project_dir: Path, config: Config, user: dict | None) -> BoxModelManifest:
    project_dir = Path(project_dir)
    path = project_dir / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"{MANIFEST_NAME} not found in the project")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError(f"{MANIFEST_NAME} exceeds 64 KB")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError(f"{MANIFEST_NAME}: invalid JSON ({e})") from e
    if not isinstance(d, dict) or d.get("schema") != 1:
        raise ManifestError("schema: must be 1")
    title = d.get("title") or "Box model"
    if not isinstance(title, str) or len(title) > 200:
        raise ManifestError("title: must be a string of at most 200 characters")
    boxes = d.get("boxes") or {}
    grid = d.get("grid") or {}
    forcing = d.get("forcing") or {}
    obs = d.get("observations") or {}
    id_field = boxes.get("id_field") or "box"
    if not isinstance(id_field, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", id_field):
        raise ManifestError("boxes.id_field: must be an identifier")
    runs_raw = d.get("runs")
    if not isinstance(runs_raw, list) or not runs_raw:
        raise ManifestError("runs: at least one run is required")
    runs: list[RunEntry] = []
    seen: set[str] = set()
    for i, r in enumerate(runs_raw):
        if not isinstance(r, dict):
            raise ManifestError(f"runs[{i}]: must be an object")
        rid = r.get("id")
        if not isinstance(rid, str) or not _SLUG.match(rid) or len(rid) > 64:
            raise ManifestError(f"runs[{i}].id: must match [a-z0-9_-]+ (max 64)")
        if rid in seen:
            raise ManifestError(f"runs[{i}].id: {rid!r} is not unique")
        seen.add(rid)
        label = r.get("label") or rid
        if not isinstance(label, str) or len(label) > 200:
            raise ManifestError(f"runs[{i}].label: must be a string of at most 200 characters")
        rdir = _resolve(r.get("dir"), f"runs[{i}].dir", project_dir, config, user, required=True)
        runs.append(RunEntry(rid, label, rdir))
    return BoxModelManifest(
        title=title,
        polygons=_resolve(boxes.get("polygons"), "boxes.polygons", project_dir, config, user, required=False),
        polygons_layer=boxes.get("layer") or None,
        id_field=id_field,
        grd=_resolve(grid.get("grd"), "grid.grd", project_dir, config, user, required=True),
        bas=_resolve(grid.get("bas"), "grid.bas", project_dir, config, user, required=False),
        boxes_txt=_resolve(grid.get("boxes_txt"), "grid.boxes_txt", project_dir, config, user, required=False),
        str_path=_resolve(d.get("str"), "str", project_dir, config, user, required=False),
        forcing_dir=_resolve(forcing.get("dir"), "forcing.dir", project_dir, config, user, required=False),
        runs=runs,
        observations=_resolve(obs.get("file"), "observations.file", project_dir, config, user, required=False),
        sites=_resolve(obs.get("sites"), "observations.sites", project_dir, config, user, required=False),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_manifest.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/services/boxmodel_manifest.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/services/boxmodel_manifest.py tests/test_boxmodel_manifest.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/boxmodel_manifest.py shyfem-ui/tests/test_boxmodel_manifest.py
git commit -m "feat(boxmodel): project manifest loader with confined path resolution"
```

### Task 5: Cache builder CLI (the child process)

**Files:**
- Create: `shyfem-ui/shyfem_ui/boxmodel_cache_cli.py`
- Modify: `shyfem-ui/pyproject.toml` (add `"pyarrow>=15",` after `"pandas>=2.0",`), `shyfem-ui/environment.yml` (add `      - pyarrow>=15` after `      - plotly>=5.24`)
- Test: `shyfem-ui/tests/test_boxmodel_cache_cli.py`

**Interfaces:**
- Consumes: `shyfem_ui.boxmodel_output` (Task 2).
- Produces: `python -m shyfem_ui.boxmodel_cache_cli --run DIR --out DIR --trusted-base DIR [--trusted-base DIR ...] [--hourly]`; `main(argv: list[str]) -> int`; `build(run_dir: Path, out_dir: Path, *, hourly: bool, progress_cb=None) -> dict` (the meta dict). Output files in `out_dir`: `state_daily.parquet` (columns `date` (date32), `box` (int32), the seven `STATE_VARS` as daily means, plus `temp_min, temp_max, salt_min, salt_max, act_eta_min, act_eta_max`), `flux_daily.parquet` (`date, section, from_box, to_box, total, positive, negative`), `meteo_daily.parquet` (`date, box` + `METEO_VARS`), optional `state_hourly.parquet` (`stamp` (timestamp), `box`, seven float32 columns), `meta.json`, `progress.json`. `meta.json` keys: `schema` (1), `built_at` (ISO UTC), `hourly` (bool), `period` `{"start","end"}` (from stats), `step_seconds`, `boxes` (list of `{box, area, volume, depth}`), `sections` (list of `{section, from_box, to_box}`), `section_nodes` (`{section: [[lon, lat], ...]}`), `run_log` (RunLogFacts as dict or null), `sources` (`{name: {"size", "mtime_ns"}}` for every file read), `records` (int).
- `progress.json` keys: `phase` (`state|meteo|write|done|error`), `records`, `expected` (int estimate from file size), `error` (str or null), `exit` (int or null), `updated` (ISO UTC). Written atomically (temp + `os.replace`).

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_boxmodel_cache_cli.py
import json
import subprocess
import sys
from datetime import date, datetime

import pandas as pd
import pytest

from _boxmodel_fixture import flux_at, make_box_run, value_at
from shyfem_ui import boxmodel_cache_cli as cli


@pytest.fixture
def run(tmp_path):
    make_box_run(tmp_path / "run", days=3)
    return tmp_path / "run"


def _out(tmp_path):
    base = tmp_path / "users"; proj = base / "alice" / "proj"
    out = proj / ".boxmodel_cache" / "fix.tmp-abc"; out.mkdir(parents=True)
    return base, out


def test_build_daily_means_match_hand_computation(run, tmp_path):
    base, out = _out(tmp_path)
    meta = cli.build(run, out, hourly=False)
    daily = pd.read_parquet(out / "state_daily.parquet")
    # day 1 has records 01:00..23:00 (23 records); day 2 has 00:00 of day 2 + 01:00..23:00 (24)
    d1 = daily[(daily["date"] == date(2009, 1, 1)) & (daily["box"] == 2)].iloc[0]
    hours = range(1, 24)
    assert d1["temp"] == pytest.approx(sum(value_at("temp", 2, datetime(2009, 1, 1, h)) for h in hours) / 23)
    assert d1["salt_max"] == pytest.approx(value_at("salt", 2, datetime(2009, 1, 1, 23)))
    d2 = daily[(daily["date"] == date(2009, 1, 2)) & (daily["box"] == 2)].iloc[0]
    assert d2["temp"] == pytest.approx(sum(value_at("temp", 2, datetime(2009, 1, 2, h)) for h in range(24)) / 24)
    assert set(daily["date"].unique()) == {date(2009, 1, 1), date(2009, 1, 2), date(2009, 1, 3), date(2009, 1, 4)}
    assert meta["records"] == 72 and meta["period"] == {"start": "2009-01-01T00:00:00", "end": "2009-01-04T00:00:00"}


def test_flux_daily_keeps_split_sections_and_boundary(run, tmp_path):
    base, out = _out(tmp_path)
    cli.build(run, out, hourly=False)
    flux = pd.read_parquet(out / "flux_daily.parquet")
    row = flux[(flux["date"] == date(2009, 1, 2)) & (flux["section"] == 3)].iloc[0]
    exp = [flux_at(3, datetime(2009, 1, 2, h)) for h in range(24)]
    assert row["positive"] == pytest.approx(sum(p for _, p, _ in exp) / 24)
    assert row["total"] == pytest.approx(row["positive"] - row["negative"])
    assert (row["from_box"], row["to_box"]) == (2, 3)
    assert sorted(flux[flux["date"] == date(2009, 1, 2)]["section"].tolist()) == [1, 2, 3, 4]
    assert flux[flux["section"] == 4]["from_box"].iloc[0] == -1


def test_meteo_daily_and_meta_sources_are_relative(run, tmp_path):
    base, out = _out(tmp_path)
    meta = cli.build(run, out, hourly=True)
    meteo = pd.read_parquet(out / "meteo_daily.parquet")
    assert meteo[(meteo["date"] == date(2009, 1, 2)) & (meteo["box"] == 1)]["srad"].iloc[0] == pytest.approx(100 + 11.5)
    assert set(meta["sources"]) == {"boxes_2d.txt", "boxes_meteo.txt", "boxes_stats.txt", "boxes_geom.txt", "run.log"}
    assert all("/" not in k for k in meta["sources"]) and meta["hourly"] is True
    hourly = pd.read_parquet(out / "state_hourly.parquet")
    assert len(hourly) == 72 * 3 and str(hourly["temp"].dtype) == "float32"
    assert meta["run_log"]["program_stop_time"] == "2009-01-04::00:00:00"
    assert meta["section_nodes"]["1"] == [[21.01, 55.5], [21.01, 55.51]]
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "done" and prog["exit"] == 0 and prog["records"] == 72


def test_cli_rejects_out_dir_outside_trusted_base(run, tmp_path):
    base, out = _out(tmp_path)
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(tmp_path / "elsewhere")])
    assert rc == 2
    bad = tmp_path / "not_cache" / "x"; bad.mkdir(parents=True)
    assert cli.main(["--run", str(run), "--out", str(bad), "--trusted-base", str(base)]) == 2


def test_cli_rejects_symlinked_run_dir(run, tmp_path):
    base, out = _out(tmp_path)
    link = tmp_path / "link"; link.symlink_to(run)
    assert cli.main(["--run", str(link), "--out", str(out), "--trusted-base", str(base)]) == 2


def test_cli_end_to_end_as_subprocess_and_light_imports(run, tmp_path):
    base, out = _out(tmp_path)
    rc = subprocess.run([sys.executable, "-m", "shyfem_ui.boxmodel_cache_cli", "--run", str(run), "--out", str(out),
                         "--trusted-base", str(base)], capture_output=True, text=True)
    assert rc.returncode == 0, rc.stderr
    assert (out / "meta.json").exists()
    probe = subprocess.run([sys.executable, "-c",
                            "import sys, shyfem_ui.boxmodel_cache_cli; "
                            "bad=[m for m in sys.modules if m.startswith(('shyfem_ui.db','shyfem_ui.services'))]; "
                            "print(bad)"], capture_output=True, text=True)
    assert probe.stdout.strip() == "[]", probe.stdout


def test_error_is_recorded_in_progress(run, tmp_path):
    base, out = _out(tmp_path)
    (run / "boxes_2d.txt").write_text("garbage\n")
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error" and "preamble" in prog["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_cache_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'boxmodel_cache_cli'`

- [ ] **Step 3: Write the CLI module**

```python
# shyfem-ui/shyfem_ui/boxmodel_cache_cli.py
"""Build the Parquet cache of one box-model run (spec §6). Runs as a CHILD
PROCESS: ``python -m shyfem_ui.boxmodel_cache_cli --run DIR --out DIR
--trusted-base DIR ...``. Imports only the parser module, stdlib, numpy,
pandas, pyarrow -- never ``shyfem_ui.services`` (its package init loads the
ORM) -- and re-validates its paths structurally because it has no project
row: ``--out`` must be ``<base>/.../<project>/.boxmodel_cache/<name>``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from shyfem_ui import boxmodel_output as bo

STATE_FILE, METEO_FILE, STATS_FILE, GEOM_FILE, LOG_FILE = (
    "boxes_2d.txt", "boxes_meteo.txt", "boxes_stats.txt", "boxes_geom.txt", "run.log")
MINMAX_VARS = ("temp", "salt", "act_eta")
BYTES_PER_STATE_RECORD_GUESS = 6200   # 29 boxes + 56 sections; only for the progress estimate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, payload: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


class _Progress:
    def __init__(self, out: Path, expected: int):
        self.path = out / "progress.json"; self.expected = expected; self.records = 0
    def write(self, phase: str, *, error: str | None = None, exit_code: int | None = None) -> None:
        _atomic_json(self.path, {"phase": phase, "records": self.records, "expected": self.expected,
                                 "error": error, "exit": exit_code, "updated": _now()})


def _no_symlink_components(p: Path) -> bool:
    cur = Path(p.anchor)
    for part in p.relative_to(p.anchor).parts:
        cur = cur / part
        if cur.is_symlink():
            return False
    return True


def _validate(run_dir: Path, out_dir: Path, bases: list[Path]) -> str | None:
    """Return an error message or None."""
    if not run_dir.is_absolute() or not out_dir.is_absolute():
        return "run and out must be absolute"
    if not run_dir.is_dir() or not _no_symlink_components(run_dir):
        return "run dir must be a real directory without symlink components"
    if not (run_dir / STATE_FILE).is_file() or (run_dir / STATE_FILE).is_symlink():
        return f"run dir has no regular {STATE_FILE}"
    if out_dir.parent.name != ".boxmodel_cache" or not _no_symlink_components(out_dir.parent):
        return "out dir must sit directly under a .boxmodel_cache directory"
    project = out_dir.parent.parent.resolve()
    if not any(str(project).startswith(str(b.resolve()) + "/") for b in bases):
        return "out dir's project is not below a trusted base"
    return None


def _day_accumulate(acc_sum, acc_cnt, acc_min, acc_max, day, ids, values):
    s = acc_sum[day]; c = acc_cnt[day]
    if s is None:
        acc_sum[day] = values.copy(); acc_cnt[day] = 1
        acc_min[day] = values[:, [bo.STATE_VARS.index(v) for v in MINMAX_VARS]].copy()
        acc_max[day] = acc_min[day].copy()
        return
    s += values; acc_cnt[day] = c + 1
    sub = values[:, [bo.STATE_VARS.index(v) for v in MINMAX_VARS]]
    np.minimum(acc_min[day], sub, out=acc_min[day]); np.maximum(acc_max[day], sub, out=acc_max[day])


def build(run_dir: Path, out_dir: Path, *, hourly: bool, progress_cb=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = max(1, os.path.getsize(run_dir / STATE_FILE) // BYTES_PER_STATE_RECORD_GUESS)
    prog = _Progress(out_dir, expected)
    prog.write("state")
    stats = bo.read_stats(run_dir / STATS_FILE)
    geom = bo.read_geom(run_dir / GEOM_FILE) if (run_dir / GEOM_FILE).is_file() else None
    # ---- state (and fluxes) -------------------------------------------------
    box_ids = None
    ssum: dict = defaultdict(lambda: None); scnt: dict = {}; smin: dict = {}; smax: dict = {}
    fsum: dict = defaultdict(lambda: None); fcnt: dict = {}; sec_meta = None
    hourly_rows = []
    n = 0
    for rec in bo.iter_state_records(run_dir / STATE_FILE):
        if box_ids is None:
            box_ids = rec.box_ids.copy()
        elif not np.array_equal(box_ids, rec.box_ids):
            raise bo.BoxOutputError(f"{STATE_FILE}: box ids change at record {n + 1}")
        day = rec.stamp.date()
        _day_accumulate(ssum, scnt, smin, smax, day, rec.box_ids, rec.values)
        if rec.sections.size:
            if sec_meta is None:
                sec_meta = rec.sections[:, :3].astype(int)
            f = fsum[day]
            if f is None:
                fsum[day] = rec.sections[:, 3:].copy(); fcnt[day] = 1
            else:
                f += rec.sections[:, 3:]; fcnt[day] += 1
        if hourly:
            hourly_rows.append((rec.stamp, rec.values.astype(np.float32)))
        n += 1
        if n % 500 == 0:
            prog.records = n; prog.write("state")
            if progress_cb:
                progress_cb(n, expected)
    if n == 0:
        raise bo.BoxOutputError(f"{STATE_FILE}: no records")
    prog.records = n
    # ---- meteo ----------------------------------------------------------------
    prog.write("meteo")
    msum: dict = defaultdict(lambda: None); mcnt: dict = {}
    if (run_dir / METEO_FILE).is_file():
        for rec in bo.iter_meteo_records(run_dir / METEO_FILE):
            day = rec.stamp.date(); m = msum[day]
            if m is None:
                msum[day] = rec.values.copy(); mcnt[day] = 1
            else:
                m += rec.values; mcnt[day] += 1
    # ---- write ---------------------------------------------------------------
    prog.write("write")
    days = sorted(scnt)
    frames = []
    for day in days:
        df = pd.DataFrame(ssum[day] / scnt[day], columns=list(bo.STATE_VARS))
        for j, v in enumerate(MINMAX_VARS):
            df[f"{v}_min"] = smin[day][:, j]; df[f"{v}_max"] = smax[day][:, j]
        df.insert(0, "box", box_ids.astype(np.int32)); df.insert(0, "date", day)
        frames.append(df)
    state_daily = pd.concat(frames, ignore_index=True)
    state_daily.to_parquet(out_dir / "state_daily.parquet", index=False)
    if sec_meta is not None:
        fframes = []
        for day in sorted(fcnt):
            df = pd.DataFrame(fsum[day] / fcnt[day], columns=["total", "positive", "negative"])
            df.insert(0, "to_box", sec_meta[:, 2]); df.insert(0, "from_box", sec_meta[:, 1])
            df.insert(0, "section", sec_meta[:, 0]); df.insert(0, "date", day)
            fframes.append(df)
        pd.concat(fframes, ignore_index=True).to_parquet(out_dir / "flux_daily.parquet", index=False)
    else:
        pd.DataFrame(columns=["date", "section", "from_box", "to_box", "total", "positive", "negative"]).to_parquet(
            out_dir / "flux_daily.parquet", index=False)
    mframes = []
    for day in sorted(mcnt):
        df = pd.DataFrame(msum[day] / mcnt[day], columns=list(bo.METEO_VARS))
        df.insert(0, "box", box_ids.astype(np.int32)); df.insert(0, "date", day)
        mframes.append(df)
    (pd.concat(mframes, ignore_index=True) if mframes else
     pd.DataFrame(columns=["date", "box", *bo.METEO_VARS])).to_parquet(out_dir / "meteo_daily.parquet", index=False)
    if hourly:
        stamps = np.repeat(np.array([s for s, _ in hourly_rows], dtype="datetime64[s]"), len(box_ids))
        vals = np.vstack([v for _, v in hourly_rows])
        hdf = pd.DataFrame(vals, columns=list(bo.STATE_VARS))
        hdf.insert(0, "box", np.tile(box_ids.astype(np.int32), len(hourly_rows))); hdf.insert(0, "stamp", stamps)
        hdf.to_parquet(out_dir / "state_hourly.parquet", index=False, compression="zstd")
    run_log = None
    if (run_dir / LOG_FILE).is_file():
        run_log = bo.read_run_log(run_dir / LOG_FILE).__dict__
    sources = {}
    for name in (STATE_FILE, METEO_FILE, STATS_FILE, GEOM_FILE, LOG_FILE):
        p = run_dir / name
        if p.is_file():
            st = p.stat(); sources[name] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    meta = {
        "schema": 1, "built_at": _now(), "hourly": hourly, "records": n,
        "period": {"start": stats.start.isoformat(), "end": stats.end.isoformat()},
        "step_seconds": stats.idtbox_seconds,
        "boxes": stats.boxes[["box", "area", "volume", "depth"]].to_dict(orient="records"),
        "sections": stats.sections[["section", "from_box", "to_box"]].to_dict(orient="records"),
        "section_nodes": {str(k): [[x, y] for x, y in v] for k, v in stats.section_nodes.items()},
        "element_box": (geom[["element", "box"]].values.tolist() if geom is not None else None),
        "run_log": run_log, "sources": sources,
    }
    _atomic_json(out_dir / "meta.json", meta)
    prog.write("done", exit_code=0)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shyfem_ui.boxmodel_cache_cli")
    ap.add_argument("--run", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--trusted-base", action="append", required=True)
    ap.add_argument("--hourly", action="store_true")
    a = ap.parse_args(argv)
    run_dir, out_dir = Path(a.run), Path(a.out)
    err = _validate(run_dir, out_dir, [Path(b) for b in a.trusted_base])
    if err:
        print(f"refused: {err}", file=sys.stderr)
        return 2
    prog = _Progress(out_dir, 1)
    try:
        build(run_dir, out_dir, hourly=a.hourly)
        return 0
    except (bo.BoxOutputError, OSError, ValueError) as e:
        prog.write("error", error=str(e), exit_code=1)
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

Then add the dependency: in `pyproject.toml` insert `    "pyarrow>=15",` after `    "pandas>=2.0",`; in `environment.yml` insert `      - pyarrow>=15` after `      - plotly>=5.24`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_cache_cli.py -v`
Expected: 7 passed. (`test_cli_end_to_end_as_subprocess_and_light_imports` runs the module in a child interpreter; if `CONDA_PREFIX` isolation makes `shyfem_ui` unimportable there, set `PYTHONPATH=/home/razinka/shyfem/shyfem-ui` in the subprocess env within the test.)

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/boxmodel_cache_cli.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/boxmodel_cache_cli.py tests/test_boxmodel_cache_cli.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/boxmodel_cache_cli.py shyfem-ui/tests/test_boxmodel_cache_cli.py shyfem-ui/pyproject.toml shyfem-ui/environment.yml
git commit -m "feat(boxmodel): Parquet cache builder CLI (child process) and pyarrow dependency"
```

### Task 6: Cache service — paths, state, build registry, publish, load

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/boxmodel_cache.py`
- Test: `shyfem-ui/tests/test_boxmodel_cache_service.py`

**Interfaces:**
- Consumes: `boxmodel_cache_cli.build` (Task 5, via subprocess), `Config.confine_path`, `Config.resolved_analysis_roots`, `Config.command_timeout_seconds`, `editor_denied_reason` from `shyfem_ui.services.access_control`.
- Produces (in `shyfem_ui.services.boxmodel_cache`):
  - `CACHE_DIRNAME = ".boxmodel_cache"`, `MAX_BUILDS_PER_WORKER = 2`, `MAX_BUILDS_PER_USER = 1`, `LIVE_TMP_SECONDS = 90`;
  - `cache_root(project_work_dir: Path) -> Path`, `cache_dir_for(project_work_dir: Path, run_id: str) -> Path`;
  - `CacheState = Literal["missing", "stale", "queued", "building", "ready", "failed"]`; `@dataclass CacheStatus(state: CacheState, progress: dict | None, meta: dict | None, message: str)`; `cache_status(project_work_dir, run_id, run_dir: Path, registry: BuildRegistry | None) -> CacheStatus`;
  - `class BuildRegistry` with `get(key) -> BuildHandle | None`, `active_for_user(user_id) -> int`, `handles() -> list[BuildHandle]`; `@dataclass BuildHandle(key: tuple[int, str], owner_id: int | None, tmp_dir: Path, task: asyncio.Task | None, pid: int | None, started: float, state: str)` where `state` in `queued|building|done|failed|cancelled`;
  - `async def start_build(registry, *, project: dict, run_id: str, run_dir: Path, user: dict | None, config: Config, hourly: bool = False) -> BuildHandle` (raises `PermissionError(reason)` when the editor gate fails, `ValueError` from confinement);
  - `async def cancel_build(registry, key, *, project: dict, user: dict | None) -> bool`;
  - `publish(tmp_dir: Path, run_id: str) -> Path` (two-step rename); `reconcile_tmp_dirs(project_work_dir: Path) -> list[str]` (publishes finished tmp dirs, removes dead `.tmp-*`/`.old-*`, returns messages);
  - `@dataclass CachedRun(run_id: str, meta: dict, state_daily: pd.DataFrame, flux_daily: pd.DataFrame, meteo_daily: pd.DataFrame, state_hourly: pd.DataFrame | None)`; `load_cache(cache_dir: Path, run_id: str) -> CachedRun` (`state_daily["date"]` is `datetime64[ns]`).

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_boxmodel_cache_service.py
import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from _boxmodel_fixture import make_box_project, make_box_run
from shyfem_ui.config import Config
from shyfem_ui.services import boxmodel_cache as bc


@pytest.fixture
def env(tmp_path):
    udr = tmp_path / "users"; wd = tmp_path / "projects"; udr.mkdir(); wd.mkdir()
    root = tmp_path / "data"; run = root / "runs" / "fix"; make_box_run(run, days=2)
    proj = make_box_project(udr / "alice" / "proj", run)
    cfg = Config(_env_file=None, deployment_mode="server", default_admin_password="x" * 12, user_data_root=udr,
                 work_dir=wd, shyfem_dir=tmp_path / "shyfem", database_url=f"sqlite:///{tmp_path/'db'/'ui.db'}",
                 analysis_roots=[str(root)])
    user = {"id": 1, "username": "alice", "role": "user"}
    project = {"id": 7, "name": "proj", "work_dir": str(proj)}
    return cfg, user, project, run


def test_cache_paths(tmp_path):
    assert bc.cache_dir_for(tmp_path, "fix") == tmp_path / ".boxmodel_cache" / "fix"


def test_status_missing_then_ready_then_stale(env, monkeypatch):
    cfg, user, project, run = env
    wd = Path(project["work_dir"])
    assert bc.cache_status(wd, "fix", run, None).state == "missing"
    monkeypatch.setattr("shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None)
    reg = bc.BuildRegistry()
    h = asyncio.run(bc.start_build(reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg))
    asyncio.run(_wait(h))
    st = bc.cache_status(wd, "fix", run, reg)
    assert st.state == "ready" and st.meta["records"] == 48
    (run / "boxes_2d.txt").write_text((run / "boxes_2d.txt").read_text() + "\n")
    assert bc.cache_status(wd, "fix", run, reg).state == "stale"


async def _wait(h, timeout=60):
    if h.task is not None:
        await asyncio.wait_for(h.task, timeout)


def test_editor_gate_blocks_build(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr("shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: "nope")
    with pytest.raises(PermissionError, match="nope"):
        asyncio.run(bc.start_build(bc.BuildRegistry(), project=project, run_id="fix", run_dir=run, user=user, config=cfg))


def test_run_dir_must_be_confined(env, monkeypatch, tmp_path):
    cfg, user, project, run = env
    monkeypatch.setattr("shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None)
    outside = tmp_path / "outside"; make_box_run(outside, days=1)
    with pytest.raises(ValueError):
        asyncio.run(bc.start_build(bc.BuildRegistry(), project=project, run_id="fix", run_dir=outside, user=user, config=cfg))


def test_publish_over_existing_cache_and_old_cleanup(tmp_path):
    root = tmp_path / ".boxmodel_cache"; root.mkdir()
    old = root / "fix"; old.mkdir(); (old / "meta.json").write_text("{}"); (old / "x.parquet").write_text("old")
    tmp = root / "fix.tmp-abc"; tmp.mkdir(); (tmp / "meta.json").write_text('{"schema":1}')
    (tmp / "progress.json").write_text(json.dumps({"phase": "done", "exit": 0}))
    out = bc.publish(tmp, "fix")
    assert out == old and (old / "meta.json").read_text() == '{"schema":1}' and not (old / "x.parquet").exists()
    assert not list(root.glob("fix.old-*")) and not tmp.exists()


def test_reconcile_publishes_finished_and_removes_dead_tmp(tmp_path):
    wd = tmp_path; root = wd / ".boxmodel_cache"; root.mkdir()
    fin = root / "a.tmp-1"; fin.mkdir(); (fin / "meta.json").write_text("{}")
    (fin / "progress.json").write_text(json.dumps({"phase": "done", "exit": 0}))
    dead = root / "b.tmp-2"; dead.mkdir(); (dead / "progress.json").write_text(json.dumps({"phase": "state", "exit": None}))
    old_t = time.time() - 10 * bc.LIVE_TMP_SECONDS; os.utime(dead / "progress.json", (old_t, old_t))
    stray = root / "c.old-3"; stray.mkdir()
    msgs = bc.reconcile_tmp_dirs(wd)
    assert (root / "a").exists() and not dead.exists() and not stray.exists() and len(msgs) == 3


def test_registry_dedupes_and_limits(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr("shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None)
    monkeypatch.setattr(bc, "MAX_BUILDS_PER_USER", 1)
    reg = bc.BuildRegistry()

    async def go():
        h1 = await bc.start_build(reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg)
        h2 = await bc.start_build(reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg)
        assert h1 is h2
        with pytest.raises(RuntimeError, match="one build"):
            await bc.start_build(reg, project=project, run_id="other", run_dir=run, user=user, config=cfg)
        await _wait(h1)
        assert h1.state == "done"
    asyncio.run(go())


def test_cancel_removes_tmp(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr("shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None)
    reg = bc.BuildRegistry()

    async def go():
        h = await bc.start_build(reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg)
        ok = await bc.cancel_build(reg, h.key, project=project, user=user)
        assert ok and h.state in ("cancelled", "done")
        await asyncio.sleep(0.5)
        assert not h.tmp_dir.exists() or h.state == "done"
    asyncio.run(go())


def test_load_cache(env, monkeypatch):
    cfg, user, project, run = env
    monkeypatch.setattr("shyfem_ui.services.access_control.editor_denied_reason", lambda *a, **k: None)
    reg = bc.BuildRegistry()
    h = asyncio.run(bc.start_build(reg, project=project, run_id="fix", run_dir=run, user=user, config=cfg))
    asyncio.run(_wait(h))
    cr = bc.load_cache(bc.cache_dir_for(Path(project["work_dir"]), "fix"), "fix")
    assert cr.run_id == "fix" and str(cr.state_daily["date"].dtype).startswith("datetime64")
    assert set(cr.state_daily["box"]) == {1, 2, 3} and cr.state_hourly is None
    assert cr.meta["period"]["start"] == "2009-01-01T00:00:00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_cache_service.py -v`
Expected: FAIL with `ImportError: cannot import name 'boxmodel_cache'`

- [ ] **Step 3: Write the cache service**

```python
# shyfem-ui/shyfem_ui/services/boxmodel_cache.py
"""Box-model cache: where it lives, what state it is in, how it is built
(child process, registry, two-step publish) and how pages load it (spec §6).
Nothing here touches reactive state; the page polls ``cache_status``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd

from shyfem_ui.config import Config

logger = logging.getLogger(__name__)

CACHE_DIRNAME = ".boxmodel_cache"
MAX_BUILDS_PER_WORKER = 2
MAX_BUILDS_PER_USER = 1
LIVE_TMP_SECONDS = 90          # a tmp dir whose progress.json is older than this is dead
KILL_GRACE_SECONDS = 5.0
CacheState = Literal["missing", "stale", "queued", "building", "ready", "failed"]


def cache_root(project_work_dir: Path) -> Path:
    return Path(project_work_dir) / CACHE_DIRNAME


def cache_dir_for(project_work_dir: Path, run_id: str) -> Path:
    return cache_root(project_work_dir) / run_id


@dataclass
class CacheStatus:
    state: CacheState
    progress: dict | None
    meta: dict | None
    message: str = ""


@dataclass
class BuildHandle:
    key: tuple[int, str]
    owner_id: int | None
    tmp_dir: Path
    task: asyncio.Task | None = None
    pid: int | None = None
    started: float = field(default_factory=time.time)
    state: str = "queued"          # queued | building | done | failed | cancelled
    proc: asyncio.subprocess.Process | None = None


class BuildRegistry:
    """Plain locked state shared by every session on this worker process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handles: dict[tuple[int, str], BuildHandle] = {}
        self._sem: asyncio.Semaphore | None = None

    def semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(MAX_BUILDS_PER_WORKER)
        return self._sem

    def get(self, key: tuple[int, str]) -> BuildHandle | None:
        with self._lock:
            h = self._handles.get(key)
            return h if h and h.state in ("queued", "building") else None

    def put(self, h: BuildHandle) -> None:
        with self._lock:
            self._handles[h.key] = h

    def active_for_user(self, user_id: int | None) -> int:
        with self._lock:
            return sum(1 for h in self._handles.values() if h.owner_id == user_id and h.state in ("queued", "building"))

    def handles(self) -> list[BuildHandle]:
        with self._lock:
            return list(self._handles.values())


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None                     # a half-written file reads as "unknown", callers treat it as building


def _sources_changed(meta: dict, run_dir: Path) -> bool:
    for name, rec in (meta.get("sources") or {}).items():
        p = run_dir / name
        if not p.is_file():
            return True
        st = p.stat()
        if st.st_size != rec.get("size") or st.st_mtime_ns != rec.get("mtime_ns"):
            return True
    return False


def cache_status(project_work_dir: Path, run_id: str, run_dir: Path, registry: BuildRegistry | None) -> CacheStatus:
    root = cache_root(project_work_dir)
    if registry is not None:
        for h in registry.handles():
            if h.key[1] == run_id and Path(h.tmp_dir).parent == root and h.state in ("queued", "building"):
                return CacheStatus(h.state, _read_json(h.tmp_dir / "progress.json"), None, "build in progress")
    for tmp in sorted(root.glob(f"{run_id}.tmp-*")):
        prog = _read_json(tmp / "progress.json")
        age = time.time() - (tmp / "progress.json").stat().st_mtime if (tmp / "progress.json").exists() else 1e9
        if prog and prog.get("phase") == "error":
            return CacheStatus("failed", prog, None, prog.get("error") or "build failed")
        if age < LIVE_TMP_SECONDS:
            return CacheStatus("building", prog, None, "build in progress (another worker)")
    cache_dir = root / run_id
    meta = _read_json(cache_dir / "meta.json") if (cache_dir / "meta.json").is_file() else None
    if meta is None:
        return CacheStatus("missing", None, None, "no cache yet")
    if _sources_changed(meta, run_dir):
        return CacheStatus("stale", None, meta, "run output changed since the cache was built")
    return CacheStatus("ready", None, meta, "ready")


def publish(tmp_dir: Path, run_id: str) -> Path:
    """Two-step publish: target -> .old-<token>, tmp -> target, remove old."""
    target = tmp_dir.parent / run_id
    token = tmp_dir.name.split(".tmp-", 1)[-1] or secrets.token_hex(4)
    old = tmp_dir.parent / f"{run_id}.old-{token}"
    if target.exists():
        os.rename(target, old)
    os.rename(tmp_dir, target)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)
    return target


def reconcile_tmp_dirs(project_work_dir: Path) -> list[str]:
    """Publish finished tmp dirs, remove dead tmp dirs and stray .old dirs. Idempotent."""
    root = cache_root(project_work_dir)
    msgs: list[str] = []
    if not root.is_dir():
        return msgs
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if ".old-" in d.name:
            shutil.rmtree(d, ignore_errors=True); msgs.append(f"removed stray {d.name}"); continue
        if ".tmp-" not in d.name:
            continue
        run_id = d.name.split(".tmp-", 1)[0]
        prog = _read_json(d / "progress.json")
        if prog and prog.get("phase") == "done" and prog.get("exit") == 0 and (d / "meta.json").is_file():
            publish(d, run_id); msgs.append(f"published {run_id}"); continue
        pj = d / "progress.json"
        age = time.time() - pj.stat().st_mtime if pj.exists() else 1e9
        if age >= LIVE_TMP_SECONDS and not (prog and prog.get("phase") == "error"):
            shutil.rmtree(d, ignore_errors=True); msgs.append(f"removed dead {d.name}")
    return msgs


async def start_build(registry: BuildRegistry, *, project: dict, run_id: str, run_dir: Path, user: dict | None,
                      config: Config, hourly: bool = False) -> BuildHandle:
    from shyfem_ui.services.access_control import editor_denied_reason
    denied = editor_denied_reason(project["id"], user, min_role="editor")
    if denied:
        raise PermissionError(denied)
    run_dir = config.confine_path(run_dir, user, must_exist=True, for_write=False)
    key = (int(project["id"]), run_id)
    existing = registry.get(key)
    if existing is not None:
        return existing
    owner_id = user.get("id") if user else None
    if registry.active_for_user(owner_id) >= MAX_BUILDS_PER_USER:
        raise RuntimeError("Only one build at a time per user; wait for the running build to finish.")
    work_dir = Path(project["work_dir"])
    root = cache_root(work_dir); root.mkdir(parents=True, exist_ok=True)
    tmp_dir = root / f"{run_id}.tmp-{secrets.token_hex(4)}"
    tmp_dir.mkdir()
    h = BuildHandle(key=key, owner_id=owner_id, tmp_dir=tmp_dir)
    registry.put(h)
    bases = [str(config.user_data_root.resolve()), str(Path(config.work_dir).resolve())]
    cmd = [sys.executable, "-m", "shyfem_ui.boxmodel_cache_cli", "--run", str(run_dir), "--out", str(tmp_dir)]
    for b in bases:
        cmd += ["--trusted-base", b]
    if hourly:
        cmd.append("--hourly")
    h.task = asyncio.create_task(_run_build(registry, h, cmd, config.command_timeout_seconds))
    return h


async def _run_build(registry: BuildRegistry, h: BuildHandle, cmd: list[str], timeout: int | None) -> None:
    async with registry.semaphore():
        if h.state == "cancelled":
            return
        h.state = "building"
        log = open(h.tmp_dir / "build.log", "wb")
        try:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=log, stderr=asyncio.subprocess.STDOUT,
                                                        cwd=str(h.tmp_dir), start_new_session=True)
            h.proc, h.pid = proc, proc.pid
            try:
                rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                await _terminate(proc); rc = -1
                logger.warning("boxmodel cache build %s timed out", h.key)
        finally:
            log.close()
        if h.state == "cancelled":
            shutil.rmtree(h.tmp_dir, ignore_errors=True)
            return
        if rc == 0 and (h.tmp_dir / "meta.json").is_file():
            publish(h.tmp_dir, h.key[1]); h.state = "done"
        else:
            h.state = "failed"
            if not (h.tmp_dir / "progress.json").exists():
                shutil.rmtree(h.tmp_dir, ignore_errors=True)


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=KILL_GRACE_SECONDS)
    except asyncio.TimeoutError:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()


async def cancel_build(registry: BuildRegistry, key: tuple[int, str], *, project: dict, user: dict | None) -> bool:
    from shyfem_ui.services.access_control import editor_denied_reason
    if editor_denied_reason(project["id"], user, min_role="editor"):
        return False
    h = registry.get(key)
    if h is None:
        return False
    h.state = "cancelled"
    if h.proc is not None:
        await _terminate(h.proc)
    else:
        shutil.rmtree(h.tmp_dir, ignore_errors=True)
    return True


@dataclass
class CachedRun:
    run_id: str
    meta: dict
    state_daily: pd.DataFrame
    flux_daily: pd.DataFrame
    meteo_daily: pd.DataFrame
    state_hourly: pd.DataFrame | None = None


def load_cache(cache_dir: Path, run_id: str) -> CachedRun:
    meta = json.loads((cache_dir / "meta.json").read_text())
    sd = pd.read_parquet(cache_dir / "state_daily.parquet"); sd["date"] = pd.to_datetime(sd["date"])
    fd = pd.read_parquet(cache_dir / "flux_daily.parquet")
    if len(fd):
        fd["date"] = pd.to_datetime(fd["date"])
    md = pd.read_parquet(cache_dir / "meteo_daily.parquet")
    if len(md):
        md["date"] = pd.to_datetime(md["date"])
    hp = cache_dir / "state_hourly.parquet"
    hourly = pd.read_parquet(hp) if hp.is_file() else None
    return CachedRun(run_id, meta, sd, fd, md, hourly)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_cache_service.py -v`
Expected: 9 passed. If the child cannot import `shyfem_ui` in the test environment, pass `env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}` to `create_subprocess_exec` (add an `env` keyword derived from `os.environ` in `_run_build`).

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/services/boxmodel_cache.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/services/boxmodel_cache.py tests/test_boxmodel_cache_service.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/boxmodel_cache.py shyfem-ui/tests/test_boxmodel_cache_service.py
git commit -m "feat(boxmodel): cache service with child-process builds, registry, two-step publish and loader"
```

### Task 7: Observations and skill metrics

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/boxmodel_skill.py`
- Test: `shyfem-ui/tests/test_boxmodel_skill.py`

**Interfaces:**
- Consumes: `CachedRun` (Task 6), fixture observations (Task 1).
- Produces (in `shyfem_ui.services.boxmodel_skill`): `VARIABLE_COLUMNS = {"salinity": "salt", "temperature": "temp", "level": "act_eta"}`, `MIN_N_SKILL = 30`, `MIN_N_YEAR = 60`, `MIN_OBS_DAYS = 3`, `MAX_OBS_ROWS = 2_000_000`, `MAX_OBS_BYTES = 50 * 1024 * 1024`, `BANDS = ((2, 4), (4, 10), (10, 30), (30, 400))`; `class ObservationError(ValueError)`; `@dataclass Metrics(n: int, bias: float, rmse: float, r: float, r2: float, sd_ratio: float | None)`; `compute_metrics(obs: np.ndarray, mod: np.ndarray, *, is_level: bool) -> Metrics`; `load_observations(path: Path) -> tuple[pd.DataFrame, dict]` (frame columns `date` (datetime64), `site`, `variable`, `value` with level in **m**; report dict `{"rows", "dropped_nonfinite", "dropped_level_le0"}`); `load_sites(path: Path) -> pd.DataFrame` (`site, lat, lon, box` with `box` nullable Int64); `model_series(run: CachedRun, box: int, column: str, start, end) -> pd.Series` (daily, indexed by date); `skill_table(runs: dict[str, CachedRun], obs: pd.DataFrame, sites: pd.DataFrame, start, end, *, min_n: int = MIN_N_SKILL) -> pd.DataFrame` (columns `run, site, variable, box, n, bias, rmse, r, r2, sd_ratio`); `per_year_table(...)` same signature with `min_n=MIN_N_YEAR` and an extra `year` column; `band_amplitude_ratios(obs_daily: pd.Series, mod_daily: pd.Series) -> dict[str, float] | None`.

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_boxmodel_skill.py
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from _boxmodel_fixture import make_box_project, make_box_run
from shyfem_ui.services import boxmodel_skill as sk
from shyfem_ui.services.boxmodel_cache import CachedRun


def test_compute_metrics_by_hand():
    o = np.array([1.0, 2.0, 3.0, 4.0]); m = np.array([1.5, 2.0, 2.5, 5.0])
    mt = sk.compute_metrics(o, m, is_level=False)
    assert mt.n == 4 and mt.bias == pytest.approx(0.25)
    assert mt.rmse == pytest.approx(math.sqrt((0.25 + 0 + 0.25 + 1.0) / 4))
    so, sm = o.std(), m.std()                       # ddof = 0
    assert mt.sd_ratio == pytest.approx(sm / so)
    assert mt.r == pytest.approx(np.corrcoef(o, m)[0, 1])
    assert mt.r2 == pytest.approx(1 - ((m - o) ** 2).sum() / ((o - o.mean()) ** 2).sum())


def test_level_is_compared_as_anomaly():
    o = np.array([5.10, 5.20, 5.30]); m = np.array([0.10, 0.20, 0.30])   # same shape, huge offset
    mt = sk.compute_metrics(o, m, is_level=True)
    assert mt.bias == pytest.approx(0.0) and mt.rmse == pytest.approx(0.0) and mt.r == pytest.approx(1.0)


def test_sd_ratio_blank_when_obs_constant():
    mt = sk.compute_metrics(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0]), is_level=False)
    assert mt.sd_ratio is None and math.isnan(mt.r)


def test_load_observations_rules(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    proj = make_box_project(tmp_path / "proj", tmp_path / "run")
    obs, report = sk.load_observations(proj / "observations.csv")
    assert report["dropped_level_le0"] == 1
    lvl = obs[(obs["site"] == "A") & (obs["variable"] == "level")]
    assert len(lvl) == 10 and lvl["value"].max() == pytest.approx(5.10)      # cm -> m
    assert str(obs["date"].dtype).startswith("datetime64")


def test_load_observations_rejects_duplicates_and_bad_variable(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("date,site,variable,value\n2009-01-01,A,salinity,1\n2009-01-01,A,salinity,2\n")
    with pytest.raises(sk.ObservationError, match="duplicate"):
        sk.load_observations(p)
    p.write_text("date,site,variable,value\n2009-01-01,A,oxygen,1\n")
    with pytest.raises(sk.ObservationError, match="variable"):
        sk.load_observations(p)
    p.write_text("date,site,variable,value\n01/02/2009,A,salinity,1\n")
    with pytest.raises(sk.ObservationError, match="date"):
        sk.load_observations(p)


def test_load_sites_nullable_box(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    proj = make_box_project(tmp_path / "proj", tmp_path / "run")
    s = sk.load_sites(proj / "sites.csv")
    assert s.loc[s["site"] == "A", "box"].iloc[0] == 1 and pd.isna(s.loc[s["site"] == "B", "box"].iloc[0])


def _fake_run(run_id, days=40, offset=0.0):
    dates = pd.date_range("2009-01-01", periods=days, freq="D")
    rows = []
    for d in dates:
        for b in (1, 2):
            rows.append({"date": d, "box": b, "salt": 1.0 + 0.1 * d.day + offset, "temp": 5.0, "act_eta": 0.01 * d.day,
                         "cur_speed": 0, "aver_eta": 0, "bstress": 0, "volume": 1})
    sd = pd.DataFrame(rows)
    return CachedRun(run_id, {"period": {"start": str(dates[0]), "end": str(dates[-1])}}, sd,
                     pd.DataFrame(), pd.DataFrame(), None)


def test_skill_table_uses_common_days_and_min_n():
    a, b = _fake_run("a"), _fake_run("b", days=35, offset=0.5)
    dates = pd.date_range("2009-01-01", periods=40, freq="D")
    obs = pd.DataFrame({"date": dates, "site": "A", "variable": "salinity", "value": [1.0 + 0.1 * d.day for d in dates]})
    sites = pd.DataFrame({"site": ["A"], "lat": [0.0], "lon": [0.0], "box": pd.array([1], dtype="Int64")})
    t = sk.skill_table({"a": a, "b": b}, obs, sites, date(2009, 1, 1), date(2009, 2, 9))
    assert set(t["run"]) == {"a", "b"} and (t["n"] == 35).all()            # intersection of days
    assert t.loc[t["run"] == "a", "bias"].iloc[0] == pytest.approx(0.0)
    assert t.loc[t["run"] == "b", "bias"].iloc[0] == pytest.approx(0.5)
    short = sk.skill_table({"a": a}, obs.head(20), sites, date(2009, 1, 1), date(2009, 2, 9))
    assert short.empty                                                       # n < 30 -> no row


def test_band_amplitude_ratios_on_sine():
    t = np.arange(400)
    obs = pd.Series(np.sin(2 * np.pi * t / 7.0), index=pd.date_range("2009-01-01", periods=400, freq="D"))
    mod = 2.0 * obs
    r = sk.band_amplitude_ratios(obs, mod)
    assert r is not None and r["4-10 d"] == pytest.approx(2.0, rel=0.05)
    assert sk.band_amplitude_ratios(obs.head(100), mod.head(100)) is None   # < 120 days
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_skill.py -v`
Expected: FAIL with `ImportError: cannot import name 'boxmodel_skill'`

- [ ] **Step 3: Write the skill service**

```python
# shyfem-ui/shyfem_ui/services/boxmodel_skill.py
"""Observation import rules and skill metrics, transcribed from the Curonian
scripts ``compare_runs.py`` / ``grid_summary.py`` (spec §7). Keep them in
sync by hand; the plan's tests pin every definition.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

VARIABLE_COLUMNS = {"salinity": "salt", "temperature": "temp", "level": "act_eta"}
MIN_N_SKILL = 30
MIN_N_YEAR = 60
MIN_OBS_DAYS = 3
MAX_OBS_ROWS = 2_000_000
MAX_OBS_BYTES = 50 * 1024 * 1024
BANDS = ((2, 4), (4, 10), (10, 30), (30, 400))


class ObservationError(ValueError):
    """User-facing observation-file problem."""


@dataclass(frozen=True)
class Metrics:
    n: int
    bias: float
    rmse: float
    r: float
    r2: float
    sd_ratio: float | None


def compute_metrics(obs: np.ndarray, mod: np.ndarray, *, is_level: bool) -> Metrics:
    o = np.asarray(obs, dtype=float); m = np.asarray(mod, dtype=float)
    if is_level:                                   # anomaly about each series' own mean
        o = o - o.mean(); m = m - m.mean()
    n = len(o)
    bias = float(m.mean() - o.mean())
    rmse = float(math.sqrt(((m - o) ** 2).sum() / n))
    so, sm = float(o.std()), float(m.std())        # ddof = 0 (pstdev)
    r = float(((o - o.mean()) * (m - m.mean())).sum() / n / (so * sm)) if so > 0 and sm > 0 else float("nan")
    denom = ((o - o.mean()) ** 2).sum()
    r2 = float(1 - ((m - o) ** 2).sum() / denom) if denom > 0 else float("nan")
    sd_ratio = (sm / so) if so > 0 else None
    return Metrics(n, bias, rmse, r, r2, sd_ratio)


def load_observations(path: Path) -> tuple[pd.DataFrame, dict]:
    path = Path(path)
    if path.stat().st_size > MAX_OBS_BYTES:
        raise ObservationError("observations file exceeds 50 MB")
    try:
        df = pd.read_csv(path, usecols=["date", "site", "variable", "value"],
                         dtype={"site": "string", "variable": "string", "value": "float64"}, nrows=MAX_OBS_ROWS + 1)
    except (ValueError, KeyError) as e:
        raise ObservationError(f"observations: {e}") from e
    if len(df) > MAX_OBS_ROWS:
        raise ObservationError("observations exceed 2 000 000 rows")
    bad_var = set(df["variable"].dropna()) - set(VARIABLE_COLUMNS)
    if bad_var:
        raise ObservationError(f"observations: unknown variable(s) {sorted(bad_var)}")
    dates = pd.to_datetime(df["date"], format="%Y-%m-%d", errors="coerce")
    if dates.isna().any():
        raise ObservationError("observations: date must be ISO YYYY-MM-DD")
    df["date"] = dates
    report = {"rows": int(len(df)), "dropped_nonfinite": 0, "dropped_level_le0": 0}
    finite = np.isfinite(df["value"].to_numpy(dtype=float, na_value=np.nan))
    report["dropped_nonfinite"] = int((~finite).sum()); df = df[finite]
    is_level = df["variable"] == "level"
    le0 = is_level & (df["value"] <= 0)
    report["dropped_level_le0"] = int(le0.sum()); df = df[~le0].copy()
    df.loc[df["variable"] == "level", "value"] = df.loc[df["variable"] == "level", "value"] / 100.0   # cm -> m
    if df.duplicated(["date", "site", "variable"]).any():
        raise ObservationError("observations: duplicate (date, site, variable) rows")
    return df.reset_index(drop=True), report


def load_sites(path: Path) -> pd.DataFrame:
    try:
        s = pd.read_csv(path, usecols=["site", "lat", "lon", "box"], dtype={"site": "string"})
    except (ValueError, KeyError) as e:
        raise ObservationError(f"sites: {e}") from e
    s["box"] = pd.array(pd.to_numeric(s["box"], errors="coerce").round(), dtype="Int64")
    return s


def model_series(run, box: int, column: str, start, end) -> pd.Series:
    sd = run.state_daily
    sel = sd[(sd["box"] == box) & (sd["date"] >= pd.Timestamp(start)) & (sd["date"] <= pd.Timestamp(end))]
    return pd.Series(sel[column].to_numpy(), index=sel["date"]).sort_index()


def _targets(obs: pd.DataFrame, sites: pd.DataFrame):
    mapped = sites.dropna(subset=["box"])
    for _, srow in mapped.iterrows():
        for var, col in VARIABLE_COLUMNS.items():
            o = obs[(obs["site"] == srow["site"]) & (obs["variable"] == var)]
            if len(o):
                yield srow["site"], var, int(srow["box"]), col, pd.Series(o["value"].to_numpy(), index=o["date"])


def skill_table(runs: dict, obs: pd.DataFrame, sites: pd.DataFrame, start, end, *, min_n: int = MIN_N_SKILL) -> pd.DataFrame:
    rows = []
    common = None
    for r in runs.values():
        d = set(r.state_daily["date"].unique())
        common = d if common is None else common & d
    common = {c for c in (common or set()) if pd.Timestamp(start) <= c <= pd.Timestamp(end)}
    for site, var, box, col, o in _targets(obs, sites):
        days = sorted(set(o.index) & common)
        if len(days) < MIN_OBS_DAYS:
            continue                                       # target skipped, like compare_runs.py
        for run_id, r in runs.items():
            m = model_series(r, box, col, start, end).reindex(days)
            k = m.notna().to_numpy()
            if k.sum() < min_n:
                continue
            mt = compute_metrics(o.reindex(days).to_numpy()[k], m.to_numpy()[k], is_level=(var == "level"))
            rows.append({"run": run_id, "site": site, "variable": var, "box": box, **mt.__dict__})
    return pd.DataFrame(rows, columns=["run", "site", "variable", "box", "n", "bias", "rmse", "r", "r2", "sd_ratio"])


def per_year_table(runs: dict, obs: pd.DataFrame, sites: pd.DataFrame, start, end, *, min_n: int = MIN_N_YEAR) -> pd.DataFrame:
    frames = []
    for y in range(pd.Timestamp(start).year, pd.Timestamp(end).year + 1):
        ys, ye = max(pd.Timestamp(start), pd.Timestamp(y, 1, 1)), min(pd.Timestamp(end), pd.Timestamp(y, 12, 31))
        t = skill_table(runs, obs, sites, ys, ye, min_n=min_n)
        if len(t):
            t.insert(0, "year", y); frames.append(t)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def band_amplitude_ratios(obs_daily: pd.Series, mod_daily: pd.Series) -> dict[str, float] | None:
    """Hann-windowed FFT amplitude ratio model/observed per period band (level only)."""
    idx = obs_daily.index.intersection(mod_daily.index).sort_values()
    if len(idx) < 120 or (np.diff(idx.values).astype("timedelta64[D]").astype(int) != 1).any():
        return None
    o = obs_daily.reindex(idx).to_numpy(dtype=float); m = mod_daily.reindex(idx).to_numpy(dtype=float)
    if np.isnan(o).any() or np.isnan(m).any():
        return None
    w = np.hanning(len(idx))
    fo, fm = np.abs(np.fft.rfft((o - o.mean()) * w)), np.abs(np.fft.rfft((m - m.mean()) * w))
    freqs = np.fft.rfftfreq(len(idx), d=1.0)
    out = {}
    for lo, hi in BANDS:
        sel = (freqs > 0) & (freqs >= 1.0 / hi) & (freqs <= 1.0 / lo)
        if sel.any() and fo[sel].sum() > 0:
            out[f"{lo}-{hi} d"] = float(fm[sel].sum() / fo[sel].sum())
    return out or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_skill.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/services/boxmodel_skill.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/services/boxmodel_skill.py tests/test_boxmodel_skill.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/boxmodel_skill.py shyfem-ui/tests/test_boxmodel_skill.py
git commit -m "feat(boxmodel): observation import rules and skill metrics pinned to the Curonian scripts"
```

### Task 8: Box polygons in WGS84

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/boxmodel_polygons.py`
- Test: `shyfem-ui/tests/test_boxmodel_polygons.py`

**Interfaces:**
- Consumes: `GrdParser.parse_file` (`shyfem_ui.services.parser_grd`), fiona/pyproj/shapely (already used by `services/mesh_builder.py`).
- Produces: `MAX_POLYGON_BYTES = 50 * 1024 * 1024`, `MAX_FEATURES = 1000`, `MAX_VERTICES = 200_000`, `ALLOWED_DRIVERS = ("GPKG", "GeoJSON")`; `class PolygonError(ValueError)`; `load_box_polygons(path: Path, layer: str | None, id_field: str, *, expected_boxes: set[int] | None = None) -> dict[int, list[list[float]]]` (outer ring per box, `[lon, lat]` pairs, closed); `dissolve_boxes_from_grid(grd_path: Path, element_box: list[list[int]]) -> dict[int, list[list[float]]]`.

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_boxmodel_polygons.py
import json

import pytest

from _boxmodel_fixture import ELEMENT_BOX, make_box_project, make_box_run
from shyfem_ui.services import boxmodel_polygons as bp


@pytest.fixture
def proj(tmp_path):
    make_box_run(tmp_path / "run", days=1)
    return make_box_project(tmp_path / "proj", tmp_path / "run")


def test_geojson_polygons_keyed_by_box(proj):
    polys = bp.load_box_polygons(proj / "box_polygons.geojson", None, "box")
    assert set(polys) == {1, 2, 3}
    ring = polys[2]
    assert ring[0] == ring[-1] and ring[0] == [21.01, 55.5]


def test_id_field_must_be_int_and_unique(proj):
    d = json.loads((proj / "box_polygons.geojson").read_text())
    d["features"][1]["properties"]["box"] = 1
    (proj / "dup.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="unique"):
        bp.load_box_polygons(proj / "dup.geojson", None, "box")
    d["features"][1]["properties"]["box"] = "two"
    (proj / "str.geojson").write_text(json.dumps(d))
    with pytest.raises(bp.PolygonError, match="integer"):
        bp.load_box_polygons(proj / "str.geojson", None, "box")


def test_expected_boxes_must_match(proj):
    with pytest.raises(bp.PolygonError, match="expected"):
        bp.load_box_polygons(proj / "box_polygons.geojson", None, "box", expected_boxes={1, 2, 3, 4})


def test_caps_and_driver(proj, monkeypatch):
    monkeypatch.setattr(bp, "MAX_FEATURES", 2)
    with pytest.raises(bp.PolygonError, match="features"):
        bp.load_box_polygons(proj / "box_polygons.geojson", None, "box")
    (proj / "x.csv").write_text("a,b\n1,2\n")
    with pytest.raises(bp.PolygonError):
        bp.load_box_polygons(proj / "x.csv", None, "box")


def test_dissolve_from_grid(proj):
    polys = bp.dissolve_boxes_from_grid(proj / "fixture.grd", [[e, b] for e, b in ELEMENT_BOX.items()])
    assert set(polys) == {1, 2, 3}
    xs = [p[0] for p in polys[1]]; ys = [p[1] for p in polys[1]]
    assert min(xs) == pytest.approx(21.00) and max(xs) == pytest.approx(21.01)
    assert min(ys) == pytest.approx(55.50) and max(ys) == pytest.approx(55.51)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_polygons.py -v`
Expected: FAIL with `ImportError: cannot import name 'boxmodel_polygons'`

- [ ] **Step 3: Write the polygons service**

```python
# shyfem-ui/shyfem_ui/services/boxmodel_polygons.py
"""Box polygons for the map, in WGS84 lon/lat (spec §4, §9)."""
from __future__ import annotations

from pathlib import Path

MAX_POLYGON_BYTES = 50 * 1024 * 1024
MAX_FEATURES = 1000
MAX_VERTICES = 200_000
ALLOWED_DRIVERS = ("GPKG", "GeoJSON")


class PolygonError(ValueError):
    """User-facing polygon-file problem."""


def _to_wgs84(crs) -> callable:
    from pyproj import CRS, Transformer
    src = CRS.from_user_input(crs) if crs else CRS.from_epsg(4326)
    if src.to_epsg() == 4326:
        return lambda x, y: (x, y)
    t = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    return lambda x, y: t.transform(x, y)


def _outer_ring(geom: dict) -> list[list[float]]:
    if geom["type"] == "Polygon":
        return [list(p[:2]) for p in geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":                 # largest part by vertex count
        part = max(geom["coordinates"], key=lambda poly: len(poly[0]))
        return [list(p[:2]) for p in part[0]]
    raise PolygonError(f"unsupported geometry {geom['type']}")


def load_box_polygons(path: Path, layer: str | None, id_field: str, *,
                      expected_boxes: set[int] | None = None) -> dict[int, list[list[float]]]:
    import fiona
    path = Path(path).resolve()
    if not path.is_file() or path.is_symlink():
        raise PolygonError("polygon file must be a regular file")
    if path.stat().st_size > MAX_POLYGON_BYTES:
        raise PolygonError("polygon file exceeds 50 MB")
    try:
        src = fiona.open(str(path), layer=layer) if layer else fiona.open(str(path))
    except Exception as e:                                 # fiona raises driver-specific errors
        raise PolygonError(f"cannot open polygons: {e}") from e
    with src:
        if src.driver not in ALLOWED_DRIVERS:
            raise PolygonError(f"driver {src.driver!r} not allowed (GPKG or GeoJSON)")
        if len(src) > MAX_FEATURES:
            raise PolygonError(f"too many features ({len(src)} > {MAX_FEATURES})")
        try:
            to_wgs = _to_wgs84(src.crs)
        except Exception as e:
            raise PolygonError(f"cannot reproject polygons: {e}") from e
        out: dict[int, list[list[float]]] = {}
        vertices = 0
        for feat in src:
            props = dict(feat["properties"]); raw = props.get(id_field)
            if raw is None or isinstance(raw, bool) or (isinstance(raw, float) and not raw.is_integer()) \
                    or isinstance(raw, str):
                raise PolygonError(f"{id_field} must be an integer on every feature")
            box = int(raw)
            if box in out:
                raise PolygonError(f"{id_field} values must be unique (duplicate {box})")
            ring = _outer_ring(dict(feat["geometry"]))
            vertices += len(ring)
            if vertices > MAX_VERTICES:
                raise PolygonError(f"too many vertices (> {MAX_VERTICES})")
            wgs = [list(to_wgs(x, y)) for x, y in ring]
            if wgs[0] != wgs[-1]:
                wgs.append(wgs[0])
            out[box] = [[round(x, 7), round(y, 7)] for x, y in wgs]
    if expected_boxes is not None and set(out) != set(expected_boxes):
        raise PolygonError(f"polygon boxes {sorted(out)} differ from the expected boxes {sorted(expected_boxes)}")
    return out


def dissolve_boxes_from_grid(grd_path: Path, element_box: list[list[int]]) -> dict[int, list[list[float]]]:
    """Union of each box's element triangles from the .grd (already lon/lat, or reprojected)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from shyfem_ui.services.parser_grd import GrdParser
    grd = GrdParser.parse_file(grd_path)
    to_wgs = _to_wgs84(f"EPSG:{grd.epsg}") if grd.epsg and grd.epsg != 4326 else (lambda x, y: (x, y))
    groups: dict[int, list] = {}
    for elem_id, box in element_box:
        el = grd.elements.get(int(elem_id))
        if el is None:
            continue
        pts = [to_wgs(grd.nodes[n].x, grd.nodes[n].y) for n in el.nodes]
        groups.setdefault(int(box), []).append(Polygon(pts))
    out = {}
    for box, polys in groups.items():
        u = unary_union(polys)
        if u.geom_type == "MultiPolygon":
            u = max(u.geoms, key=lambda g: g.area)
        out[box] = [[round(x, 7), round(y, 7)] for x, y in u.exterior.coords]
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_polygons.py -v`
Expected: 5 passed (fiona reports the GeoJSON driver as `"GeoJSON"`; if `GrdParser` needs an explicit `epsg` for the fixture, the fixture grid is lon/lat so `grd.epsg` is `None` and no reprojection happens).

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/services/boxmodel_polygons.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/services/boxmodel_polygons.py tests/test_boxmodel_polygons.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/boxmodel_polygons.py shyfem-ui/tests/test_boxmodel_polygons.py
git commit -m "feat(boxmodel): box polygons from GeoPackage/GeoJSON or dissolved from the grid"
```

### Task 9: Map component extension — box polygon layer, click → box, legend data

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/grid_map.py` (new function `build_box_layers`; `grid_map_server` gains `extra_layers` and `on_box_click`; `_handle_click` gains the `box` branch; returned dict gains `selected_box`)
- Test: `shyfem-ui/tests/test_grid_map_box_layers.py`

**Interfaces:**
- Consumes: `polygon_layer`, `scatterplot_layer`, `color_bins`, `PALETTES` already imported in `grid_map.py` (guarded by `try/except ImportError`, so the new code must also degrade to `[]` when `shiny_deckgl` is missing); `MapWidget.update(session, layers=...)`.
- Produces:
  - `value_colors(values: list[float], palette: str = "viridis", n_bins: int = 6) -> tuple[list[list[int]], list[tuple[float, float, list[int]]]]` — per-value RGB via `color_bins` plus the legend bins `(lo, hi, rgb)`;
  - `build_box_layers(polygons: dict[int, list[list[float]]], values: dict[int, float] | None, *, palette: str = "viridis", label: str = "", posts: list[dict] | None = None, selected: int | None = None) -> tuple[list[dict], list[tuple[float, float, list[int]]]]` — a `polygon_layer("boxes", ...)` with per-object `color`, `box`, `value`, `tooltip_html`; an optional `scatterplot_layer("posts", ...)` for posts `{"site", "lon", "lat", "value"}`; returns `(layers, legend_bins)`;
  - `grid_map_server(input, output, session, grd_file, partition_map=None, on_node_click=None, *, extra_layers: reactive.Value | None = None, on_box_click=None) -> dict` with keys `selected_node`, `selected_box`.

- [ ] **Step 1: Write the failing tests**

```python
# shyfem-ui/tests/test_grid_map_box_layers.py
import inspect

import pytest

from shyfem_ui.components import grid_map as gm

pytest.importorskip("shiny_deckgl")


def test_value_colors_bins_and_legend():
    colors, bins = gm.value_colors([0.0, 0.5, 1.0], palette="viridis", n_bins=2)
    assert len(colors) == 3 and all(len(c) == 3 for c in colors)
    assert len(bins) == 2 and bins[0][0] == pytest.approx(0.0) and bins[-1][1] == pytest.approx(1.0)
    assert colors[0] != colors[2]


def test_build_box_layers_polygon_and_posts():
    polys = {1: [[21.0, 55.5], [21.01, 55.5], [21.01, 55.51], [21.0, 55.5]], 2: [[21.01, 55.5], [21.02, 55.5], [21.02, 55.51], [21.01, 55.5]]}
    layers, bins = gm.build_box_layers(polys, {1: 0.2, 2: 0.8}, label="salt", posts=[{"site": "A", "lon": 21.005, "lat": 55.505, "value": 0.25}], selected=2)
    ids = [l["id"] for l in layers]
    assert ids == ["boxes", "posts"]
    boxes = layers[0]
    data = boxes["data"]
    assert [d["box"] for d in data] == [1, 2] and data[1]["value"] == 0.8
    assert boxes["getFillColor"] == "@@d.color" and boxes["getPolygon"] == "@@d.polygon" and boxes["pickable"] is True
    assert "salt" in data[0]["tooltip_html"] and data[1]["color"][3] == 255 and data[0]["color"][3] < 255  # selection highlighted
    assert layers[1]["data"][0]["position"] == [21.005, 55.505]
    assert len(bins) == 6


def test_build_box_layers_without_values_is_outline_only():
    layers, bins = gm.build_box_layers({1: [[0, 0], [1, 0], [1, 1], [0, 0]]}, None)
    assert layers[0]["filled"] is False and bins == []


def test_grid_map_server_has_box_click_branch_and_extra_layers():
    src = inspect.getsource(gm.grid_map_server.__closure__[0].cell_contents) if gm.grid_map_server.__closure__ else inspect.getsource(gm.grid_map_server)
    assert '"box" in obj' in src and "selected_box" in src and "extra_layers" in src and "on_box_click" in src
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map_box_layers.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'value_colors'`

- [ ] **Step 3: Extend `grid_map.py`**

Add after `_depth_to_colors` (~line 305):

```python
def value_colors(values, palette: str = "viridis", n_bins: int = 6):
    """Per-value RGB (via color_bins) plus legend bins [(lo, hi, rgb), ...]."""
    if color_bins is None or not values:
        return [[120, 120, 120]] * len(values), []
    pal = PALETTES.get(palette, PALETTE_VIRIDIS)
    colors = [list(c[:3]) for c in color_bins(list(values), n_bins=n_bins, palette=pal)]
    lo, hi = float(min(values)), float(max(values))
    step = (hi - lo) / n_bins if hi > lo else 1.0
    idx = [int(round((i / max(n_bins - 1, 1)) * (len(pal) - 1))) for i in range(n_bins)]
    bins = [(lo + i * step, lo + (i + 1) * step, list(pal[j][:3])) for i, j in enumerate(idx)]
    return colors, bins


def build_box_layers(polygons, values, *, palette: str = "viridis", label: str = "", posts=None, selected=None):
    """Box polygons coloured by value (or outline only) plus optional post markers."""
    if polygon_layer is None:
        return [], []
    boxes = sorted(polygons)
    if values:
        vals = [float(values.get(b, float("nan"))) for b in boxes]
        finite = [v for v in vals if v == v]
        colors, bins = value_colors(finite, palette=palette) if finite else ([], [])
        it = iter(colors)
        data = []
        for b, v in zip(boxes, vals):
            rgb = next(it) if v == v else [200, 200, 200]
            alpha = 255 if (selected is None or b == selected) else 170
            txt = f"{v:.3f}" if v == v else "n/a"
            data.append({"polygon": polygons[b], "box": b, "value": v if v == v else None, "color": [*rgb, alpha],
                         "tooltip_html": f"<b>box {b}</b><br>{label}: {txt}"})
        layer = polygon_layer("boxes", data, getPolygon="@@d.polygon", getFillColor="@@d.color",
                              getLineColor=[40, 40, 40, 200], lineWidthMinPixels=1, filled=True, stroked=True,
                              pickable=True)
    else:
        bins = []
        data = [{"polygon": polygons[b], "box": b, "value": None, "color": [0, 0, 0, 0],
                 "tooltip_html": f"<b>box {b}</b>"} for b in boxes]
        layer = polygon_layer("boxes", data, getPolygon="@@d.polygon", getLineColor=[40, 40, 40, 220],
                              lineWidthMinPixels=1, filled=False, stroked=True, pickable=True)
    layers = [layer]
    if posts:
        pdata = [{"position": [p["lon"], p["lat"]], "site": p["site"], "value": p.get("value"),
                  "tooltip_html": f"<b>{p['site']}</b>" + (f"<br>{p['value']:.3f}" if p.get("value") is not None else "")}
                 for p in posts]
        layers.append(scatterplot_layer("posts", pdata, getPosition="@@d.position", getFillColor=[255, 60, 60, 230],
                                        radiusMinPixels=5, pickable=True))
    return layers, bins
```

In `grid_map_server`: extend the signature to
`def grid_map_server(input, output, session, grd_file: reactive.Value, partition_map: reactive.Value | None = None, on_node_click=None, *, extra_layers: reactive.Value | None = None, on_box_click=None):`;
add `selected_box = reactive.value(None)` next to `selected_node`; in `_update_map`, after `layers = build_layers(...)`, append `if extra_layers is not None: layers = layers + list(extra_layers.get() or [])` (and read `extra_layers.get()` so the effect re-runs when it changes; when `grd_file.get()` is `None` but `extra_layers` holds layers, still call `_map.update` with those layers and fit bounds to the polygons); extend `_handle_click`:

```python
        obj = click_data.get("object") if isinstance(click_data, dict) else None
        if obj and "box" in obj:
            bid = int(obj["box"])
            selected_box.set(bid)
            if on_box_click is not None:
                on_box_click(bid)
            return
        if obj and "node_id" in obj:
            ...existing node branch unchanged...
```

and return `{"selected_node": selected_node, "selected_box": selected_box}`.

- [ ] **Step 4: Run the new tests and the existing map tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_map_box_layers.py tests/test_grid_map.py -v` (use `ls tests | grep -i grid_map` to find the existing file names and include them)
Expected: all pass; existing callers (`grid_prep`, `mesh_builder`, `partitioning`) are unaffected because the new parameters are keyword-only with defaults and the returned dict keeps `selected_node`.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/components/grid_map.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/components/grid_map.py tests/test_grid_map_box_layers.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/components/grid_map.py shyfem-ui/tests/test_grid_map_box_layers.py
git commit -m "feat(grid_map): box polygon layer with value colours, post markers and box click"
```

### Task 10: The "Box model" page — Map and Time-series tabs, wiring

**Files:**
- Create: `shyfem-ui/shyfem_ui/pages/boxmodel.py`
- Modify: `shyfem-ui/shyfem_ui/pages/__init__.py` (add `"boxmodel"` to `__all__`), `shyfem-ui/shyfem_ui/app.py` (import, `SIDEBAR_GROUPS` item after the Compare item, page div after the Compare div, server mount after `compare.compare_server(...)`)
- Test: `shyfem-ui/tests/test_boxmodel_page.py`

**Interfaces:**
- Consumes: Tasks 4–9 (`load_manifest`, `ManifestError`, `cache_status`, `start_build`, `cancel_build`, `reconcile_tmp_dirs`, `load_cache`, `cache_dir_for`, `BuildRegistry`, `CachedRun`, `load_observations`, `load_sites`, `skill_table`, `model_series`, `VARIABLE_COLUMNS`, `load_box_polygons`, `dissolve_boxes_from_grid`, `build_box_layers`, `grid_map_ui`, `grid_map_server`), `editor_denied_reason`, `Config`, `plotly`, `shinywidgets`.
- Produces: `boxmodel_ui()` (module UI) and `boxmodel_server(input, output, session, config: Config, active_project: reactive.Value, tutorial_context=None, current_user=None) -> dict`; nav value `"Box-model"`, page div id `sf-page-Box-model`, module id `"boxmodel"`. Module-level `REGISTRY = BuildRegistry()` (one per worker process).

- [ ] **Step 1: Write the failing wiring tests**

```python
# shyfem-ui/tests/test_boxmodel_page.py
import inspect
import re

from _test_helpers import get_server_source


def test_page_is_registered():
    import shyfem_ui.pages as pages
    assert "boxmodel" in pages.__all__
    from shyfem_ui.pages import boxmodel
    assert callable(boxmodel.boxmodel_ui) and callable(boxmodel.boxmodel_server)


def test_app_wiring():
    import shyfem_ui.app as app
    src = inspect.getsource(app)
    assert '"value": "Box-model"' in src and 'id="sf-page-Box-model"' in src
    assert re.search(r'boxmodel\.boxmodel_server\(\s*"boxmodel",\s*config,', src)
    assert "active_project=active_project" in src.split("boxmodel.boxmodel_server(")[1][:400]


def test_server_wiring_gates_and_polling():
    from shyfem_ui.pages import boxmodel
    src = get_server_source(boxmodel, "boxmodel_server")
    assert src.count("editor_denied_reason(") >= 2            # build + cancel
    assert "start_build(" in src and "cancel_build(" in src and "load_manifest(" in src
    assert "invalidate_later" in src and "reconcile_tmp_dirs(" in src
    assert "ui.HTML(" not in src                                # manifest text via ui.tags only
    assert "grid_map_server(" in src and "on_box_click" in src


def test_download_uses_non_deprecated_renderer():
    from shyfem_ui.pages import boxmodel
    assert boxmodel._render_download is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_page.py -v`
Expected: FAIL with `AssertionError` on `"boxmodel" in pages.__all__`

- [ ] **Step 3: Write the page module**

```python
# shyfem-ui/shyfem_ui/pages/boxmodel.py
"""Box model page (spec §8): Map and Time-series tabs over the Parquet cache."""
from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from shiny import module, reactive, render, ui
from shinywidgets import output_widget, render_widget

from shyfem_ui.components.grid_map import build_box_layers, grid_map_server, grid_map_ui
from shyfem_ui.config import Config
from shyfem_ui.services.access_control import editor_denied_reason
from shyfem_ui.services.boxmodel_cache import (BuildRegistry, cache_dir_for, cache_status, cancel_build,
                                               load_cache, reconcile_tmp_dirs, start_build)
from shyfem_ui.services.boxmodel_manifest import ManifestError, load_manifest
from shyfem_ui.services.boxmodel_polygons import PolygonError, dissolve_boxes_from_grid, load_box_polygons
from shyfem_ui.services.boxmodel_skill import (VARIABLE_COLUMNS, ObservationError, load_observations, load_sites,
                                               model_series)
from shyfem_ui.services.boxmodel_skill import skill_table as compute_skill_table   # the render below is also named skill_table

logger = logging.getLogger(__name__)
REGISTRY = BuildRegistry()
_render_download = getattr(render, "download_button", None) or render.download   # shiny 1.7 renamed it
VARIABLES = {"salt": "Salinity (psu)", "temp": "Temperature (°C)", "act_eta": "Water level (m)"}
COLUMN_TO_VARIABLE = {v: k for k, v in VARIABLE_COLUMNS.items()}
MAP_MODES = {"day": "Value on the selected day", "mean": "Period mean", "bias": "Bias vs observations (posts)"}


@module.ui
def boxmodel_ui() -> ui.Tag:
    return ui.div(
        ui.h3("Box model"),
        ui.output_ui("manifest_error"),
        ui.layout_columns(
            ui.input_select("run", "Run", choices={}),
            ui.input_select("variable", "Variable", choices=VARIABLES),
            ui.input_date_range("period", "Period"),
            ui.div(ui.output_ui("cache_state"),
                   ui.input_action_button("build", "Build cache", class_="btn-primary btn-sm me-1"),
                   ui.input_action_button("cancel", "Cancel", class_="btn-outline-secondary btn-sm")),
            col_widths=(3, 2, 4, 3),
        ),
        ui.navset_card_tab(
            ui.nav_panel("Map", ui.layout_columns(
                ui.div(ui.input_select("map_mode", "Colour by", MAP_MODES), ui.output_ui("day_slider")),
                grid_map_ui("boxmap", height="540px"),
                ui.output_ui("map_legend"),
                col_widths=(3, 7, 2))),
            ui.nav_panel("Time series", ui.layout_columns(
                ui.input_select("box", "Box", choices={}), ui.download_button("download_csv", "Export CSV", class_="btn-outline-primary btn-sm mt-4"),
                col_widths=(3, 3)),
                output_widget("ts_plot"), ui.output_ui("skill_table")),
            id="tabs",
        ),
    )


def _fmt(x, nd=3):
    return "" if x is None or (isinstance(x, float) and x != x) else f"{x:.{nd}f}"


@module.server
def boxmodel_server(input, output, session, config: Config, active_project: reactive.Value,
                    tutorial_context=None, current_user=None) -> dict:
    manifest_err = reactive.value(None)
    cache_version = reactive.value(0)
    status_tick = reactive.value(0)
    last_state = reactive.value(None)
    extra_layers = reactive.value([])
    selected_box = reactive.value(None)

    def _user():
        return current_user() if current_user is not None else None

    def _project():
        return active_project.get() if active_project is not None else None

    @reactive.calc
    def manifest():
        proj = _project()
        if proj is None:
            manifest_err.set("Open a project first.")
            return None
        try:
            m = load_manifest(Path(proj["work_dir"]), config, _user())
        except ManifestError as e:
            manifest_err.set(str(e)); return None
        msgs = reconcile_tmp_dirs(Path(proj["work_dir"]))
        for msg in msgs:
            logger.info("boxmodel cache reconcile (%s): %s", proj["name"], msg)
        if manifest_err.get() is not None:
            manifest_err.set(None)
        return m

    @render.ui
    def manifest_error():
        err = manifest_err.get()
        return ui.div(ui.tags.strong("Box model: "), ui.tags.span(err), class_="alert alert-warning") if err else None

    @reactive.effect
    @reactive.event(manifest)
    def _fill_runs():
        m = manifest()
        choices = {r.id: r.label for r in m.runs} if m else {}
        if choices != getattr(_fill_runs, "_last", None):
            _fill_runs._last = choices
            ui.update_select("run", choices=choices, selected=next(iter(choices), None))

    def _run_entry():
        m = manifest(); rid = input.run()
        return next((r for r in (m.runs if m else []) if r.id == rid), None)

    @reactive.calc
    def status():
        status_tick.get(); cache_version.get()
        m = manifest(); r = _run_entry(); proj = _project()
        if not (m and r and proj):
            return None
        return cache_status(Path(proj["work_dir"]), r.id, r.dir, REGISTRY)

    @reactive.effect
    def _poll():
        st = status()
        state = st.state if st else None
        if state in ("queued", "building"):
            reactive.invalidate_later(2)
            status_tick.set(status_tick.get() + 1)
        prev = last_state.get()
        if prev != state:
            last_state.set(state)
            if prev in ("queued", "building") and state in ("ready", "stale", "failed"):
                cache_version.set(cache_version.get() + 1)

    @render.ui
    def cache_state():
        st = status()
        if st is None:
            return ui.tags.span("no run selected", class_="text-muted")
        badge = {"ready": "success", "stale": "warning", "building": "info", "queued": "info", "failed": "danger",
                 "missing": "secondary"}[st.state]
        txt = st.state
        if st.progress and st.state in ("building", "queued"):
            txt += f" {st.progress.get('records', 0)}/{st.progress.get('expected', '?')}"
        return ui.tags.span(txt, class_=f"badge bg-{badge}", title=st.message)

    @reactive.effect
    @reactive.event(input.build)
    async def _build():
        proj = _project(); r = _run_entry(); usr = _user()
        if not (proj and r):
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6); return
        try:
            await start_build(REGISTRY, project=proj, run_id=r.id, run_dir=r.dir, user=usr, config=config)
        except (PermissionError, ValueError, RuntimeError) as e:
            ui.notification_show(str(e), type="error", duration=8); return
        status_tick.set(status_tick.get() + 1)
        ui.notification_show(f"Building cache for {r.label}", type="message", duration=4)

    @reactive.effect
    @reactive.event(input.cancel)
    async def _cancel():
        proj = _project(); r = _run_entry(); usr = _user()
        if not (proj and r):
            return
        denied = editor_denied_reason(proj["id"], usr, min_role="editor")
        if denied:
            ui.notification_show(denied, type="error", duration=6); return
        ok = await cancel_build(REGISTRY, (int(proj["id"]), r.id), project=proj, user=usr)
        ui.notification_show("Build cancelled" if ok else "No build to cancel", type="message", duration=4)
        status_tick.set(status_tick.get() + 1)

    @reactive.calc
    def cached():
        cache_version.get()
        st = status(); proj = _project(); r = _run_entry()
        if not (st and st.state in ("ready", "stale") and proj and r):
            return None
        try:
            return load_cache(cache_dir_for(Path(proj["work_dir"]), r.id), r.id)
        except (OSError, ValueError) as e:
            logger.warning("boxmodel cache load failed: %s", e); return None

    @reactive.effect
    @reactive.event(cached)
    def _fill_period_and_boxes():
        cr = cached()
        if cr is None:
            return
        start = pd.Timestamp(cr.meta["period"]["start"]).date(); end = pd.Timestamp(cr.meta["period"]["end"]).date()
        ui.update_date_range("period", start=start, end=end, min=start, max=end)
        boxes = {str(b): f"box {b}" for b in sorted(cr.state_daily["box"].unique())}
        if boxes != getattr(_fill_period_and_boxes, "_last", None):
            _fill_period_and_boxes._last = boxes
            ui.update_select("box", choices=boxes, selected=next(iter(boxes)))

    def _period():
        p = input.period()
        if not p or p[0] is None or p[1] is None:
            cr = cached()
            if cr is None:
                return None
            return pd.Timestamp(cr.meta["period"]["start"]).date(), pd.Timestamp(cr.meta["period"]["end"]).date()
        return p[0], p[1]

    @reactive.calc
    def observations():
        m = manifest()
        if not (m and m.observations and m.sites):
            return None, None
        try:
            obs, _report = load_observations(m.observations); sites = load_sites(m.sites)
        except ObservationError as e:
            ui.notification_show(f"Observations: {e}", type="warning", duration=8); return None, None
        return obs, sites

    @reactive.calc
    def polygons():
        m = manifest(); cr = cached()
        if m is None:
            return {}
        expected = set(int(b["box"]) for b in cr.meta["boxes"]) if cr else None
        try:
            if m.polygons:
                return load_box_polygons(m.polygons, m.polygons_layer, m.id_field, expected_boxes=expected)
            if cr and cr.meta.get("element_box"):
                return dissolve_boxes_from_grid(m.grd, cr.meta["element_box"])
        except (PolygonError, OSError, ValueError) as e:
            ui.notification_show(f"Polygons: {e}", type="warning", duration=8)
        return {}

    @render.ui
    def day_slider():
        cr = cached()
        if cr is None or input.map_mode() != "day":
            return None
        p = _period()
        return ui.input_slider("day", "Day", min=p[0], max=p[1], value=p[0], step=timedelta(days=1), width="100%")

    @reactive.calc
    def box_values():
        cr = cached(); col = input.variable(); p = _period()
        if cr is None or p is None:
            return None, ""
        sd = cr.state_daily; mode = input.map_mode()
        if mode == "day":
            d = input.day() if "day" in input else p[0]
            sel = sd[sd["date"] == pd.Timestamp(d)]
            return dict(zip(sel["box"].astype(int), sel[col].astype(float))), f"{VARIABLES[col]} on {d}"
        sel = sd[(sd["date"] >= pd.Timestamp(p[0])) & (sd["date"] <= pd.Timestamp(p[1]))]
        if mode == "mean":
            g = sel.groupby("box")[col].mean()
            return {int(k): float(v) for k, v in g.items()}, f"mean {VARIABLES[col]}"
        obs, sites = observations()
        if obs is None:
            return {}, "bias (no observations)"
        t = compute_skill_table({cr.run_id: cr}, obs, sites, p[0], p[1])
        t = t[t["variable"] == COLUMN_TO_VARIABLE[col]]
        return {int(b): float(v) for b, v in zip(t["box"], t["bias"])}, f"bias of {VARIABLES[col]}"

    @reactive.calc
    def posts():
        obs, sites = observations(); vals, _ = box_values()
        if sites is None:
            return []
        out = []
        for _, s in sites.iterrows():
            v = vals.get(int(s["box"])) if (vals and pd.notna(s["box"])) else None
            out.append({"site": str(s["site"]), "lon": float(s["lon"]), "lat": float(s["lat"]), "value": v})
        return out

    legend_bins = reactive.value([])

    @reactive.effect
    def _layers():
        polys = polygons()
        vals, label = box_values()
        layers, bins = build_box_layers(polys, vals if polys else None, label=label, posts=posts(),
                                        selected=selected_box.get())
        sig = (input.run(), input.variable(), input.map_mode(), label, len(polys), selected_box.get())
        if sig != getattr(_layers, "_sig", None):
            _layers._sig = sig
            extra_layers.set(layers); legend_bins.set(bins)

    @render.ui
    def map_legend():
        bins = legend_bins.get()
        if not bins:
            return None
        rows = [ui.tags.div(ui.tags.span(style=f"display:inline-block;width:14px;height:14px;background:rgb({r},{g},{b});margin-right:6px"),
                            ui.tags.span(f"{lo:.3g} – {hi:.3g}")) for (lo, hi, (r, g, b)) in bins]
        return ui.tags.div(ui.tags.strong("Legend"), *rows, class_="small")

    grd_file = reactive.value(None)

    @reactive.effect
    @reactive.event(manifest)
    def _grd():
        m = manifest()
        val = str(m.grd) if m else None
        if grd_file.get() != val:
            grd_file.set(val)

    def _on_box(b: int):
        if selected_box.get() != b:
            selected_box.set(b)
            ui.update_select("box", selected=str(b))

    grid_map_server("boxmap", grd_file, extra_layers=extra_layers, on_box_click=_on_box)

    @reactive.calc
    def series():
        cr = cached(); p = _period(); col = input.variable(); b = input.box()
        if cr is None or p is None or not b:
            return None
        box = int(b)
        s = model_series(cr, box, col, p[0], p[1])
        lo = model_series(cr, box, f"{col}_min", p[0], p[1]) if f"{col}_min" in cr.state_daily else None
        hi = model_series(cr, box, f"{col}_max", p[0], p[1]) if f"{col}_max" in cr.state_daily else None
        obs, sites = observations(); o = None
        if obs is not None:
            mapped = sites[sites["box"] == box]["site"].tolist()
            oo = obs[(obs["site"].isin(mapped)) & (obs["variable"] == COLUMN_TO_VARIABLE[col])]
            if len(oo):
                o = pd.Series(oo["value"].to_numpy(), index=oo["date"]).sort_index()
        return {"box": box, "model": s, "lo": lo, "hi": hi, "obs": o, "label": VARIABLES[col]}

    @render_widget
    def ts_plot():
        fig = go.Figure(); d = series()
        if d is None:
            fig.add_annotation(text="Select a run with a ready cache", xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False)
            fig.update_layout(height=420); return fig
        if d["lo"] is not None:
            fig.add_trace(go.Scatter(x=d["hi"].index, y=d["hi"].values, line=dict(width=0), showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=d["lo"].index, y=d["lo"].values, fill="tonexty", line=dict(width=0),
                                     name="daily min–max", opacity=0.3))
        fig.add_trace(go.Scatter(x=d["model"].index, y=d["model"].values, name=f"model box {d['box']}", mode="lines"))
        if d["obs"] is not None:
            fig.add_trace(go.Scatter(x=d["obs"].index, y=d["obs"].values, name="observed", mode="markers",
                                     marker=dict(size=5)))
        fig.update_layout(height=420, yaxis_title=d["label"], margin=dict(l=40, r=20, t=30, b=40))
        return fig

    @render.ui
    def skill_table():
        cr = cached(); p = _period(); obs, sites = observations()
        if cr is None or p is None or obs is None:
            return ui.tags.p("No observations configured for this project.", class_="text-muted")
        t = compute_skill_table({cr.run_id: cr}, obs, sites, p[0], p[1])
        if t.empty:
            return ui.tags.p("No target has 30 or more common days in this period.", class_="text-muted")
        head = ui.tags.tr(*[ui.tags.th(c) for c in ("site", "variable", "box", "n", "bias", "RMSE", "r", "R²", "sd_mod/sd_obs")])
        body = [ui.tags.tr(ui.tags.td(str(r.site)), ui.tags.td(str(r.variable)), ui.tags.td(str(r.box)), ui.tags.td(str(r.n)),
                           ui.tags.td(_fmt(r.bias)), ui.tags.td(_fmt(r.rmse)), ui.tags.td(_fmt(r.r, 2)), ui.tags.td(_fmt(r.r2, 2)),
                           ui.tags.td(_fmt(r.sd_ratio, 2))) for r in t.itertuples()]
        return ui.tags.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                           ui.tags.p("Judge amplitude by sd_mod/sd_obs (1.00 is right) and phase by r; R² is shown but is not the headline.",
                                     class_="text-muted small"))

    @_render_download(filename=lambda: f"box{input.box() or 'x'}_{input.variable()}.csv")
    def download_csv():
        d = series()
        if d is None:
            yield ""; return
        df = pd.DataFrame({"date": d["model"].index, "model": d["model"].values})
        if d["obs"] is not None:
            df = df.merge(pd.DataFrame({"date": d["obs"].index, "observed": d["obs"].values}), on="date", how="left")
        buf = io.StringIO(); df.to_csv(buf, index=False); yield buf.getvalue()

    return {"selected_box": selected_box}
```

Wiring: in `pages/__init__.py` add `"boxmodel",` to `__all__`; in `app.py` add `boxmodel` to the `from shyfem_ui.pages import (...)` list, add `{"label": "Box model", "icon": "bi-grid-3x3-gap", "value": "Box-model"},` right after the Compare item in `SIDEBAR_GROUPS`, add `ui.div(boxmodel.boxmodel_ui("boxmodel"), id="sf-page-Box-model", class_="sf-page"),` right after the Compare div, and after the `compare.compare_server(...)` call add:

```python
    boxmodel.boxmodel_server(
        "boxmodel",
        config,
        active_project=active_project,
        tutorial_context=tutorial_context,
        current_user=current_user,
    )
```

- [ ] **Step 4: Run the wiring tests, then the whole suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_page.py -v && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest -q -p no:cacheprovider`
Expected: 4 passed, then the full suite green (the app imports at module level; a syntax or import error surfaces here). Also start the app once locally (`/opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app` per the repo README) and open the Box model page with a project that has the fixture manifest to see the map and the series render.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/pages/boxmodel.py shyfem_ui/app.py && /opt/micromamba/envs/shiny/bin/python -m black shyfem_ui/pages/boxmodel.py shyfem_ui/app.py shyfem_ui/pages/__init__.py tests/test_boxmodel_page.py
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/boxmodel.py shyfem-ui/shyfem_ui/pages/__init__.py shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_boxmodel_page.py
git commit -m "feat(ui): Box model page with Map and Time-series tabs, cache build controls and skill table"
```

### Task 11: Count cache bytes toward the project quota

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/file_service.py` (`_sum_project_bytes`, ~line 457)
- Test: `shyfem-ui/tests/test_boxmodel_quota.py`

**Interfaces:**
- Produces: `_sum_project_bytes(db, project_id: int, work_dir: str | Path | None = None) -> int` — unchanged behaviour when `work_dir` is None; when given, adds the size of every regular file under `<work_dir>/.boxmodel_cache/` (no symlinks followed). Every existing caller keeps working; the upload path passes `project.work_dir`.

- [ ] **Step 1: Write the failing test**

```python
# shyfem-ui/tests/test_boxmodel_quota.py
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project, ProjectFile
from shyfem_ui.services.file_service import _sum_project_bytes


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite:///:memory:"); Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    p = Project(name="p", work_dir=str(tmp_path / "p")); s.add(p); s.commit()
    s.add(ProjectFile(project_id=p.id, filename="a.txt", rel_path="a.txt", file_type="txt", size_bytes=100)); s.commit()
    return s, p


def test_cache_bytes_are_counted_when_work_dir_given(db, tmp_path):
    s, p = db
    cache = tmp_path / "p" / ".boxmodel_cache" / "fix"; cache.mkdir(parents=True)
    (cache / "state_daily.parquet").write_bytes(b"x" * 250)
    (cache / "link").symlink_to(tmp_path)          # never followed
    assert _sum_project_bytes(s, p.id) == 100
    assert _sum_project_bytes(s, p.id, work_dir=p.work_dir) == 350
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_quota.py -v`
Expected: FAIL with `TypeError: _sum_project_bytes() got an unexpected keyword argument 'work_dir'` (if the `ProjectFile` constructor needs other required columns, add them from `shyfem_ui/models/project.py:62`).

- [ ] **Step 3: Extend `_sum_project_bytes`**

```python
def _sum_project_bytes(db, project_id: int, work_dir: str | Path | None = None) -> int:
    """Sum size_bytes for all files in a project, plus the on-disk box-model cache."""
    from sqlalchemy import func as sa_func

    result = (
        db.query(sa_func.coalesce(sa_func.sum(ProjectFile.size_bytes), 0))
        .filter_by(project_id=project_id)
        .scalar()
    )
    total = int(result)
    if work_dir:
        cache = Path(work_dir) / ".boxmodel_cache"
        if cache.is_dir():
            for p in cache.rglob("*"):
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
    return total
```

Then find the upload-quota call site (`grep -n "_sum_project_bytes(" shyfem_ui/services/file_service.py`) and pass `work_dir=project.work_dir` where the `Project` row is in scope.

- [ ] **Step 4: Run the test and the file-service tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_boxmodel_quota.py tests/test_file_service.py -v`
Expected: all pass (use `ls tests | grep file_service` for the exact existing file names).

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/tests/test_boxmodel_quota.py
git commit -m "feat(files): count the box-model cache toward the project quota"
```

### Task 12: Admin documentation and changelog

**Files:**
- Modify: `shyfem-ui/README.md` (a new subsection under the configuration/deployment section; find it with `grep -n "SHYFEM_UI_" README.md | head`), `CHANGELOG.md` (repo root, under `## [Unreleased]` → `### Added`)

- [ ] **Step 1: Add the admin note to `shyfem-ui/README.md`**

```markdown
### Box-model analysis roots (server mode)

The **Box model** page analyses SHYFEM box output (`idtbox`) that usually lives outside the
per-user sandbox (a 22-year run is a gigabyte). Declare the directories that hold such runs:

```bash
SHYFEM_UI_ANALYSIS_ROOTS='["/home/razinka/curonian"]'     # JSON array; default []
```

Rules: server mode only; each root must exist; a root may not be `/`, `/tmp`, or overlap the user
data root, the work dir, the SHYFEM dir or the database directory (startup fails otherwise, and
the accepted list is logged). Roots are **read-only** and **readable by every authenticated user**
who references them from a project manifest — never put per-user or sensitive data under one.

A project opts in with `boxmodel.json` in its directory (schema 1: `boxes`, `grid`, `str`,
`forcing`, `runs`, `observations` — see `docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md`).
The cache is built by a child process into `<project>/.boxmodel_cache/<run_id>/` and counts toward
the project quota.
```

- [ ] **Step 2: Add the changelog entry under `## [Unreleased]` → `### Added`**

```markdown
- **Box model page (PR 1 of 4)** — analyse SHYFEM `idtbox` box output in the Workbench: a project
  `boxmodel.json` manifest, streaming parsers, a Parquet cache built by a child process, admin-declared
  read-only `SHYFEM_UI_ANALYSIS_ROOTS`, box polygons on the map coloured by value/period mean/bias with
  a day slider, per-box time series with observations and the skill table (bias, RMSE, r, R², sd ratio)
  as defined by the Curonian comparison scripts. Compare and Setup tabs follow in later PRs.
```

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/README.md CHANGELOG.md
git commit -m "docs(boxmodel): analysis roots admin note and changelog entry"
```

### Task 13: End-to-end test

**Files:**
- Create: `shyfem-ui/tests/test_playwright_boxmodel.py`

**Interfaces:**
- Consumes: the `live_server`, `pw_page` fixtures and the `window.__test_set_active_project("<id>")` hook from `tests/conftest.py` / `tests/_test_app.py` (project id as a string; `""` clears), the fixture generator (Task 1), the page ids from Task 10 (`boxmodel-run`, `boxmodel-build`, `boxmodel-cache_state`, `boxmodel-skill_table`, tab "Map"). The tests run the app in local mode (`SHYFEM_UI_DEPLOYMENT_MODE=local`, `SHYFEM_UI_WORK_DIR` set by conftest), so the project directory must be created inside `config.work_dir`.

- [ ] **Step 1: Write the test**

```python
# shyfem-ui/tests/test_playwright_boxmodel.py
"""E2E: import the fixture project, build the cache, see the map and the skill table."""
import os
from pathlib import Path

import pytest

from _boxmodel_fixture import make_box_project, make_box_run
from shyfem_ui.config import get_config
from shyfem_ui.db.base import db_session, init_db
from shyfem_ui.models.project import Project

pytestmark = pytest.mark.e2e


@pytest.fixture
def box_project(live_server):
    cfg = get_config(); init_db()
    work = Path(cfg.work_dir) / "e2e_boxmodel"
    run = work / "run"; make_box_run(run, days=40)
    make_box_project(work, run)
    with db_session() as db:
        p = Project(name="e2e_boxmodel", work_dir=str(work)); db.add(p); db.commit(); pid = p.id
    yield pid
    with db_session() as db:
        db.query(Project).filter_by(id=pid).delete(); db.commit()


def test_boxmodel_page_builds_cache_and_renders(pw_page, box_project):
    pw_page.evaluate(f'window.__test_set_active_project("{box_project}")')
    pw_page.evaluate("shyfemNavTo('Box-model')")
    run_select = pw_page.locator("#boxmodel-run")
    run_select.wait_for(state="visible", timeout=15000)
    assert run_select.input_value() == "fix"
    pw_page.locator("#boxmodel-build").click()
    from playwright.sync_api import expect
    expect(pw_page.locator("#boxmodel-cache_state")).to_contain_text("ready", timeout=60000)
    expect(pw_page.locator(".deckgl-map canvas").first).to_be_visible(timeout=15000)
    pw_page.get_by_role("tab", name="Time series").click()
    expect(pw_page.locator("#boxmodel-skill_table table tbody tr").first).to_be_visible(timeout=30000)
    assert "salinity" in pw_page.locator("#boxmodel-skill_table").inner_text()
```

- [ ] **Step 2: Run it against the live server**

Run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_boxmodel.py -v --override-ini="addopts="`
Expected: 1 passed. If `shyfemNavTo` does not switch the page, check the exact `value` string in `SIDEBAR_GROUPS` (`Box-model`) and the `id="sf-page-Box-model"` div; if the deck.gl canvas selector differs, read `grid_map_ui` for the container class and adjust. The fixture uses 40 days so the salinity target has ≥ 30 common days.

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/tests/test_playwright_boxmodel.py
git commit -m "test(boxmodel): end-to-end build, map and skill table"
```

### Task 14: Full verification and pull request

- [ ] **Step 1: Run everything the CI runs**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m ruff check shyfem_ui/ && /opt/micromamba/envs/shiny/bin/python -m black --check shyfem_ui/
mv .env /tmp/claude-1000/.env.bak 2>/dev/null; CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest -q -p no:cacheprovider; mv /tmp/claude-1000/.env.bak .env 2>/dev/null
PYTHONNOUSERSITE=1 CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_db_init_alembic.py --ignore=tests/test_db_fk.py --ignore=tests/test_migrations_env.py 2>&1 | tail -3
```
Expected: lint clean; full suite green with `.env` aside; the worker-env run shows only the known async-plugin failures.

- [ ] **Step 2: Open the PR**

```bash
cd /home/razinka/shyfem && git push -u origin HEAD
gh pr create --title "feat(ui): Box model analysis, PR 1 — manifest, cache, analysis roots, Map and Time-series tabs" --body "Implements PR 1 of docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md (plan: docs/superpowers/plans/2026-09-17-boxmodel-analysis-pr1.md). Tasks 1–13 with tests; E2E runs on the PR."
```

---

## Self-review notes (run by the author before handing off)

- Spec coverage: §3 layout (Tasks 2, 5, 6, 7, 8, 10 — root-level parser/CLI justified in the header); §4 manifest (Task 4); §5 formats and caps (Task 2); §6 cache, child process, registry, publish, quota (Tasks 5, 6, 11); §7 metrics and import rules (Task 7); §8 Map and Time-series tabs, editor gates, polling, box click, legend, download (Tasks 9, 10); §9 roots validation, confinement, parser limits, `ui.tags` only (Tasks 3, 8, 10); §10 fixture and tests (every task); §12 PR 1 (Task 14); README/changelog (Task 12). Not in PR 1 by design: Compare tab, Setup tab and the tolerant STR reader (PR 2–3), export/import cache rules and the Curonian bundle (PR 4).
- Type consistency: `CachedRun` fields and `state_daily` columns are defined in Task 5/6 and used verbatim in Tasks 7 and 10; `build_box_layers` returns `(layers, bins)` in Task 9 and is consumed that way in Task 10; `BuildHandle.key = (project_id, run_id)` in Task 6 matches `cancel_build` in Task 10; `VARIABLE_COLUMNS`/`COLUMN_TO_VARIABLE` names agree.
- Known judgement calls for the implementer: the Playwright selectors in Task 13 and the index arithmetic in Task 2's malformed-line test are the two places most likely to need a one-line adjustment; both steps say how to adjust.
