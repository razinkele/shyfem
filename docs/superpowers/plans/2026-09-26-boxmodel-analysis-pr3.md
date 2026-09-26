# Box-model analysis, PR 3 (Setup) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship PR 3 of the box-model analysis feature: the **Setup** tab of the "Box model" page (spec §8, "Setup") — the mesh with box outlines, section interfaces, open-boundary and river nodes from the STR `$bound*` `kbound` lists, the river series from the files named by `boundn` (with `ibtyp` and `zfact`), per-box meteo from the cache, and an STR summary — built on a **tolerant STR reader** that accepts the real Curonian STR. This also closes the PR 1 deferral "section-interface lines on the map".

**Architecture:** A new pure service `shyfem_ui/services/boxmodel_setup.py` holds the tolerant STR reader, the boundary/summary extraction, the SHYFEM time-series (forcing) reader and the section-interface geometry from the cache meta; it imports nothing from `components/`. The map component gains a public `node_positions(grd, epsg=None)` and a `build_setup_layers(...)` builder (interface path layer + boundary-node scatter layer, tooltips escaped at the sink). The page gains a fourth tab with a third map module (`setupmap`), an STR summary, a boundaries table, a river plot and a per-box meteo plot. Setup is read-only.

**Tech Stack:** as PR 1/2 (Python 3.13 worker interpreter, Shiny 1.8, shinywidgets + Plotly, pandas, shiny_deckgl, pytest, Playwright).

**Spec:** `docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md` §4 (manifest `str`, `forcing.dir` rules), §5 (`boxes_stats.txt` section details), §8 "Setup", §9. PR 1/2 plans' Global Constraints apply.

## Global Constraints (in addition to PR 1/2's)

- **The tolerant reader is defined by the real Curonian STR** (`curonian29_1993_2016.str`, 241 lines). A ~60-line excerpt of it is checked in as a test string and every item of the acceptance list below is a test.
- STR and forcing reads are `reactive.calc`s off `manifest()` returning `(value, error)`; they are never re-read per render. Everything Setup renders hangs off `manifest()` / `cached()` / `cache_generation`, **never** `status()` / `status_tick`; `_setup_layers` has the `_layers` shape (everything inside `try`, writes only its own reactives). Extend `test_expensive_chain_hangs_off_cache_generation_not_the_poll_tick` and `test_layers_effect_wraps_its_upstream_calls` again.
- `boundn` values in the STR are **run-relative** (`fem_forcing/nemunas.txt`); the manifest's `forcing_dir` is the project's `forcing/`. Resolve by **basename** against `forcing_dir`; only `.txt` regular files, no symlinks (`boxmodel_common.no_symlink_components`), re-confined through `config.confine_path` on every open (§9 TOCTOU); caps 50 MB / 2 000 000 rows. A `.fem` `boundn` is shown as "not read (.fem)"; `saltn`/`tempn`/`conzn` are shown as names only.
- Resolved paths are never rendered (spec §4): show `boundn` as written in the STR and `config.display_path(...)` where a path must appear.
- Section ↔ boundary convention (verified on run9316's `meta.json`): an open-boundary section has `from_box = −k` where `k` is the `$bound<k>` number; interior sections have positive `from_box`/`to_box`.
- No editor gate (read-only), but STR text, boundary titles and file names go through `_text`/`ui.tags`; map tooltips are escaped only in the layer builder.
- Worktree `/tmp/claude-1000/wt-pr3`, branch `feat/boxmodel-pr3`; never `git stash`/`checkout --`/`reset` in the shared worktree; worker interpreter for every run; E2E never concurrently with the unit suite.
- Commit style: conventional commits, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Tolerant STR reader — acceptance list (each item is a test)

1. `$name` **and** `&name` open a section; `$end` **and** `&end` close it; names are case-insensitive and reported lower-case; repeated names (`bound1`, `bound2`, …) are distinct sections kept in file order.
2. Trailing text after the section name (`$bound1     ---- Baltic sea ---- raw CMEMS sla, NOT rescaled`) is kept as the section's `title` with leading/trailing dashes and whitespace stripped (`Baltic sea ---- raw CMEMS sla, NOT rescaled`).
3. Several `key = value` pairs on one line, separated by spaces or tabs (`itanf  = '1993-01-01'   itend  = '2016-12-31'	idt = '5m'`); values single- or double-quoted or bare; bare negative numbers (`temp = -999`); no space before the quote (`boundn ='fem_forcing/minija.txt'`); trailing `!` comments stripped; whole lines starting with `!` or `#` skipped (`!gotmpa = ''` inside `$name`).
4. Multi-line integer lists: after `kbound = 1547 1548 …`, following lines that contain only numbers extend the list; a line containing `=` ends the continuation. Only a bare numeric list continues — never a quoted or scalar value.
5. **Everything outside a section is ignored, including `key = value` lines**: the decoy `itanf = 347068800 itend = 536450400 idt = 300 --> 2008-2013` prose lines must not set `itanf`; the STR's period comes from the `&para` section only.
6. Orphan assignments outside any section that *look* like parameters (`nsigma = 12` after `&end`, `dtwave = '5m'` after `$end`) are collected as `orphans: list[(line_no, key, value)]` and reported (SHYFEM ignores them; this is exactly the mistake the forcing-gotchas memory records).
7. Bare-word blocks outside sections (`levels … end`, `flux … end`) are skipped; a bare `end` is never mistaken for a section end.
8. `$title` (three free-text lines) and `$extra` (`1823 'Klaipeda'` rows) contain no `=`: their raw lines are kept in `lines`; the reader never raises on them.
9. `****** SECTION …` banner lines and ` - set …` comment lines are ignored; tabs are whitespace; a file over 1 MB or with a line over 4 KB raises `StrSetupError` naming the file.
10. Duplicate keys inside one section: the last one wins (SHYFEM semantics), with the earlier value kept in `duplicates`.

---

## File structure

| File | Responsibility |
|---|---|
| `shyfem_ui/services/boxmodel_setup.py` (new) | `StrSetupError`, `StrSection`, `StrSetup`, `read_str_tolerant`, `boundaries`, `str_summary`, `read_forcing_series`, `resolve_forcing_file`, `section_interfaces`. No `components/` imports. |
| `shyfem_ui/components/grid_map.py` (modify) | public `node_positions(grd, epsg=None)`; `build_setup_layers(interfaces, boundary_points, *, selected=None)`. |
| `shyfem_ui/pages/boxmodel.py` (modify) | fourth tab "Setup": `setupmap`, `setup_summary`, `setup_boundaries`, `setup_rivers` plot, `setup_meteo` plot + controls. |
| `tests/_boxmodel_fixture.py` (modify) | `make_box_project(..., str_file=True, forcing=True)` writes `fixture.str` + `forcing/river.txt`; manifest `str`/`forcing.dir` set when written. |
| `tests/test_boxmodel_setup.py` (new), `tests/test_boxmodel_fixture.py`, `tests/test_grid_map_box_layers.py`, `tests/test_boxmodel_page.py`, `tests/test_playwright_boxmodel.py`, `tests/test_boxmodel_manifest.py` (if the manifest fixture change touches it) | Tests per task. |
| `shyfem-ui/README.md`, `CHANGELOG.md` | Setup paragraph; `[Unreleased]` entry. |
| GitHub issue | `parser_str` limitations recorded (spec §8): `SECTION_START = ^\s*\$(\w+)\s*$` rejects `&para` and any `$boundN` header with trailing text (on the Curonian file only `title, waves, name, extra` parse); multi-line `kbound` truncated. |

---

### Task 1: Fixture — STR excerpt and a river file

**Files:** modify `tests/_boxmodel_fixture.py`, `tests/test_boxmodel_fixture.py`.

**Interfaces:**
- `make_box_project(project_dir, run_dir, *, run_id="fix", polygons=True, obs_days=10, extra_runs=None, str_file: bool = False, forcing: bool = False)`. With `str_file=True` writes `fixture.str` and sets manifest `"str": "fixture.str"`; with `forcing=True` writes `forcing/river.txt` and sets `"forcing": {"dir": "forcing"}`. Defaults unchanged (the byte-identity test guards this).
- `FIXTURE_STR` constant (module-level string) in the Curonian shape: banner + prose with the decoy `itanf = 347068800 …` line; `&para … &end` with `itanf = '2009-01-01'   itend = '2009-01-<days+1>'	idt = '5m'`, `idtbox = '1h'`, `date = 20090101   time = 000000`, `ireib = 5	czdef = 0.0025`, `nomp = 4`; orphan `nsigma = 12` after `&end`; `$bound1     ---- Baltic sea ---- open boundary` with `kbound = 1 2 3` on one line **and** `4` on a continuation line, `ibtyp = 1`, `boundn = 'fem_forcing/sea_level.fem'`, `saltn = 'fem_forcing/salt.fem'`; `$bound2 ----- Fixture river ---- discharge in m3/s` with `kbound = 5 6`, `zfact = 0.25`, `ibtyp  = 2`, `boundn ='fem_forcing/river.txt'`, `temp = -999`, `salt = 0.1`; `$name` with `!gotmpa = ''` and `wind = 'fem_forcing/wind.fem'`; a bare `levels\n 1 2 3\nend` block; `$extra` with `1 'A'`. Node ids are fixture node ids (1–8).
- `forcing/river.txt`: `YYYY-MM-DD::06:00:00  <value>` daily from `T0 − 2 days` to `T0 + days + 2` (so it overhangs the run period on both sides), `value = 100 + day_index`, no header, one `#` comment line at the top (the reader must tolerate it).

**Steps:**
- [ ] Tests first: files written only when asked; manifest keys set/None accordingly; the STR contains the decoy line and the orphan; the river file has the expected first data value; defaults byte-identical (existing test).
- [ ] Implement; run `tests/test_boxmodel_fixture.py`, `tests/test_boxmodel_manifest.py`, `tests/test_boxmodel_page.py`.

### Task 2: Tolerant STR reader, forcing reader, interfaces (service, pure)

**Files:** create `shyfem_ui/services/boxmodel_setup.py`, `tests/test_boxmodel_setup.py`.

**Interfaces:**
- `class StrSetupError(ValueError)`.
- `@dataclass StrSection: name: str; title: str; params: dict[str, str | list[int]]; lines: list[str]; duplicates: dict[str, list[str]]` (values kept as strings as written, quotes stripped; numeric lists as `list[int]`).
- `@dataclass StrSetup: sections: list[StrSection]; orphans: list[tuple[int, str, str]]; path_name: str` with helpers `get(name) -> StrSection | None` (first match, case-insensitive) and `bounds() -> list[StrSection]` (names matching `^bound(\d+)$`, sorted by number).
- `read_str_tolerant(path: Path, *, max_bytes: int = 1_000_000, max_line: int = 4096) -> StrSetup` — implements the acceptance list; raises `StrSetupError` on size caps, never on content.
- `@dataclass Boundary: number: int; title: str; ibtyp: int | None; zfact: float; kbound: list[int]; boundn: str | None; other_files: dict[str, str]` (`saltn`, `tempn`, `conzn`, `vel3dn`, `bio2dn`, `sed2dn` when present); `boundaries(setup) -> list[Boundary]`; `kind(b) -> "level" | "discharge" | "unknown"` (`ibtyp` 1 → level, 2/3 → discharge).
- `str_summary(setup) -> dict[str, str]` with the keys present among `itanf, itend, idt, idtbox, idtflx, idtext, date, time, ireib, czdef, ibarcl, iheat, ievap, iturb, isalt, itemp, nomp` plus `"title"` (first `$title` line) and `"orphans"` (rendered `"nsigma = 12 (line 60)"`, comma-joined) when any.
- `period_from_summary(summary) -> tuple[pd.Timestamp, pd.Timestamp] | None` — `itanf`/`itend` parsed when they are ISO dates (`'2016-12-31'` or `'2013-12-31::06:00'`); else None.
- `resolve_forcing_file(boundn: str, forcing_dir: Path | None, config, user) -> tuple[Path | None, str | None]`: basename of `boundn`; `None, "not read (.fem)"` for a non-`.txt`; `None, "forcing dir not configured"`; `None, "not found"`; symlink components → `None, "symlink refused"`; else the confined path (`config.confine_path(forcing_dir / name, user, must_exist=True)`, `ValueError` → `None, "outside the allowed roots"`).
- `read_forcing_series(path: Path, *, max_bytes: int = 50_000_000, max_rows: int = 2_000_000) -> pd.Series`: lines `YYYY-MM-DD::HH:MM:SS  v1 [v2 …]` → float64 series of `v1` indexed by timestamp (ns); blank and `#` lines skipped; a malformed line raises `StrSetupError` with the line number; caps raise.
- `section_interfaces(meta: dict) -> list[dict]`: from `meta["sections"]` and `meta["section_nodes"]`: `{"section": int, "from_box": int, "to_box": int, "open_boundary": int | None (=k for from_box −k), "path": [[lon, lat], …]}`; sections without coordinates are omitted.

**Steps:**
- [ ] Write `tests/test_boxmodel_setup.py` first: the Curonian excerpt (`CURONIAN_EXCERPT`, ~60 lines copied from the real file: banner, decoy prose, `&para` head with the multi-pair lines, `nsigma` orphan, `$waves … $end` + `dtwave` orphan, `$bound1` and `$bound2` verbatim, `levels … end`, `$name`, `$extra` head, `flux … end`) and one test per acceptance item; `boundaries()` on the excerpt → bound1 (28 nodes, level, `.fem`), bound2 (4 nodes, zfact 0.25, discharge, `fem_forcing/nemunas.txt`); `str_summary` → `itanf '1993-01-01'`, `idtbox '1h'`, `orphans` mentions `nsigma`; `period_from_summary`; `resolve_forcing_file` branches with a tmp forcing dir and a local-mode `Config`; `read_forcing_series` on the fixture-style file incl. the `#` line and a malformed line; `section_interfaces` on a meta dict with a −2 open section.
- [ ] Implement; ruff/black; run the file plus `tests/test_boxmodel_common.py`.

### Task 3: Map — node positions and setup layers

**Files:** modify `shyfem_ui/components/grid_map.py`, `tests/test_grid_map_box_layers.py`.

**Interfaces:**
- `node_positions(grd: GrdFile, epsg: int | None = None) -> dict[int, list[float]]` — public wrapper of `_get_lonlat`.
- `build_setup_layers(interfaces: list[dict], boundary_points: list[dict], *, selected_boundary: int | None = None) -> list[dict]`: one `path_layer` for interior interfaces (grey), one for open-boundary interfaces (blue, wider), tooltips `section s: box a → box b` / `open boundary k`; one `scatterplot_layer` for boundary nodes `{"node": int, "lon", "lat", "boundary": int, "title": str, "kind": "level"|"discharge"|"unknown", "boundn": str|None}` coloured by kind (level blue, discharge green, unknown grey), the selected boundary's nodes larger; tooltip HTML escaped with `html.escape` at this sink (title and boundn are user text). Empty inputs → `[]`; degrades to `[]` without `shiny_deckgl` like the other builders.

**Steps:**
- [ ] Tests: layer count and ids; open vs interior split; colours by kind; escaping of a `<b>` in a title; empty → []; degrade path.
- [ ] Implement; run the grid-map tests.

### Task 4: The Setup tab (page)

**Files:** modify `shyfem_ui/pages/boxmodel.py`, `tests/test_boxmodel_page.py`.

**Interfaces (ids under `boxmodel`):**
- UI: fourth `ui.nav_panel("Setup", ...)` with `ui.output_ui("setup_message")`, `grid_map_ui("setupmap", height="440px")`, `ui.output_ui("setup_boundaries")` (table: boundary, title, type, nodes, zfact, boundn as written, other files, and a "select" action that sets `setup_selected_boundary`), `ui.output_ui("setup_summary")` (two-column table of `str_summary`, orphans row highlighted), `output_widget("setup_rivers")`, a row with `ui.output_ui("setup_meteo_controls")` (`input_select("setup_meteo_var", ...)` over the meteo columns) and `output_widget("setup_meteo")`.
- Server: `@reactive.calc str_setup_result() -> (StrSetup | None, str | None)` off `manifest()` (`str_path` None → message "Manifest has no STR"); `boundaries_calc()`; `summary_calc()`; `@reactive.calc rivers_result()` → `{boundary number: (series | None, note)}` reading each discharge boundary's `boundn` through `resolve_forcing_file` + `read_forcing_series`, restricted to `period_from_summary(summary)` else the cache period else all; `interfaces_calc()` from `cached().meta`; `boundary_points_calc()` from `node_positions(grd_file.get())` + `boundaries_calc()` (missing node ids collected into the message); `setup_selected_boundary: reactive.Value[int | None]`; `_setup_layers` effect (the `_layers` shape) writing `setup_layers` only, using `build_box_layers(polys, None)` outlines **plus** `build_setup_layers(...)`; `grid_map_server("setupmap", grd_file, extra_layers=setup_layers, on_box_click=_on_box)`; `setup_rivers` widget: one trace per discharge boundary (`_text(title)`), y label "discharge (m³/s)" with `zfact` noted in the trace name when ≠ 1; `setup_meteo` widget: `cached().meteo_daily` for `input.box()` and `input.setup_meteo_var()` over `_period()`.
- Messages: no project; manifest has no STR; STR unreadable (`_err`); forcing notes per boundary in the table; no cache yet (interfaces and meteo need a ready cache — say so, still draw boundaries from the STR).

**Steps:**
- [ ] Extend `tests/test_boxmodel_page.py` first: ids present and the "Setup" tab; the expensive-chain test covers `str_setup_result`, `rivers_result`, `interfaces_calc`, `_setup_layers`; the layers-effect test covers `_setup_layers`; a source test that `rivers_result` goes through `resolve_forcing_file` (never opens `boundn` directly) and that no rendered string contains a resolved path (`str(manifest_obj.forcing_dir` not in any render body); the summary render passes values through `_text`.
- [ ] Implement; run the page tests, `tests/test_boxmodel_*.py`, `tests/test_app_wiring.py`.

### Task 5: End-to-end

**Files:** modify `tests/test_playwright_boxmodel.py`.

**Steps:**
- [ ] Fixture project now `str_file=True, forcing=True`. After the Compare assertions: open the **Setup** tab; `#boxmodel-setup_boundaries table tbody tr` count 2 and text contains "Fixture river" and "0.25"; `#boxmodel-setup_summary` contains `idtbox` and `nsigma` (orphan line); `#boxmodel-setup_rivers` and `#boxmodel-setup_meteo` attached without `shiny-output-error`; no new canvas assertion.
- [ ] Run the file alone under the worker interpreter.

### Task 6: Docs, issue, verification, pull request

**Steps:**
- [ ] README: Setup paragraph (what it shows, the basename rule for `boundn`, `.fem` not read, orphan keys); CHANGELOG `[Unreleased]`.
- [ ] `gh issue create` "parser_str: accept `&name` headers, trailing header text and multi-line `kbound`" with the evidence from the Curonian file (only `title, waves, name, extra` parse today) and a pointer to `boxmodel_setup.read_str_tolerant`; link it from the PR.
- [ ] ruff/black; full unit suite; all Playwright files (not concurrently); correctness review **before** merge; PR with summary, deviations, deferrals (hourly-cache UI still deferred; manifest form still deferred to PR 4), test plan. Merge is the user's call.

## Self-review against spec §8 "Setup"

| Spec clause | Where |
|---|---|
| Mesh with box outlines | `setupmap`: mesh + `build_box_layers(polys, None)` |
| open-boundary nodes and river nodes from the STR `$bound*` `kbound` lists | `boundaries()` + `node_positions` + `build_setup_layers` scatter, coloured by `ibtyp` kind |
| river series from the files named by `boundn` (with `ibtyp` and `zfact` shown) | `rivers_result` + `setup_rivers`; boundaries table shows ibtyp/zfact/boundn |
| per-box meteo from the cache | `setup_meteo` off `cached().meteo_daily` |
| STR summary (`itanf`, `itend`, `idt`, `idtbox`, `date`, selected `$para` values) | `str_summary` + `setup_summary` (plus orphans) |
| tolerant STR reader (`$`/`&`, trailing text, multi-line lists), tested on a Curonian excerpt | `read_str_tolerant` + `CURONIAN_EXCERPT` tests |
| section interfaces as lines (PR 1 deferral) | `section_interfaces` + `build_setup_layers` paths |
| `parser_str` limitation recorded as a follow-up issue | Task 6 |
