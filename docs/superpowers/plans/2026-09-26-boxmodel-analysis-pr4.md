# Box-model analysis, PR 4 (Curonian bundle, import rules, docs, metric cross-check) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the box-model analysis feature (spec §12 item 4): the Curonian onboarding bundle script, the import side of the export cache rules, the admin onboarding documentation, and the metric cross-check against the Curonian reference scripts as a committed script with its output.

**Two repositories.** The **shyfem** repo gets the only code change (import skips `.boxmodel_cache/`), a defensive fix carried over from the PR 3 review, docs and the changelog — on branch `feat/boxmodel-pr4` in the worktree `/tmp/claude-1000/wt-pr4`, as a PR with CI and a review. The **Curonian** repo (`~/curonian`, remote `git@github.com:razinkele/curonian.git`, no CI) gets two scripts under `shyfem_box/` as plain commits on `main`. Order: write and **run** the Curonian scripts first, then the shyfem PR records their results. No Curonian commit may reference an unmerged shyfem SHA.

**Spec:** `docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md` §9 (export/import rules), §10 (the cross-check is a script in the Curonian repo, recorded in PR 4), §11 (Curonian onboarding), §12.

## Global Constraints

- `~/curonian` is **shared state**: another session or process edits `curonian_db.gpkg`. The scripts open the database **read-only** (`file:…?mode=ro`, uri=True) and never write to it. Nothing in this PR writes under `~/curonian` except the new files under `shyfem_box/` and the bundle output directory.
- The bundle is written to a fresh `ui_bundle/` plus a zip; the live admin project (`~/.shyfem-ui/users/admin/Curonian 29-box/`) is **never** written to by a script.
- Bundle assets are **copies**, never symlinks: the manifest loader resolves strictly and refuses symlinked paths.
- Run directories in the generated manifest are `/home/razinka/curonian/published_runs/<run>` — **not** `runs/<run>` as spec §11 says. `runs/<run>` are symlinks into `published_runs/`, and `confine_path` resolves symlinks strictly, so a root of `curonian/runs` would resolve outside itself. The deployed `.env` root is already `["/home/razinka/curonian/published_runs"]`. Spec §11's sentence is corrected in this PR, and the correction is called out in the PR body.
- Worker interpreter for every test and script run; E2E never concurrently with the unit suite; never `git stash`/`checkout --`/`reset` in a shared worktree.
- Commit style: conventional commits, trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File structure

| File | Repo | Responsibility |
|---|---|---|
| `shyfem_box/export_ui_bundle.py` (new) | curonian | Build `ui_bundle/` + `ui_bundle.zip` for the Workbench import: manifest, observations, sites, polygons, grid, boxes, STR, river files. |
| `shyfem_box/cross_check_metrics.py` (new) | curonian | Compare `shyfem_ui.services.boxmodel_skill` against `compare_runs.stats`/`bandamp` and `grid_summary.skill` on a real run; non-zero exit on breach. |
| `shyfem_box/cross_check_2026-09-26.txt` (new) | curonian | Committed output of the above. |
| `shyfem_ui/services/project_export.py` (modify) | shyfem | Import skips `.boxmodel_cache/` members **and** excludes them from the archive size budget. |
| `shyfem_ui/services/boxmodel_setup.py` (modify) | shyfem | Defensive `ValueError` guard in `resolve_forcing_file` (PR 3 review, sub-threshold). |
| `tests/test_project_export.py` (modify) | shyfem | Import-skip and budget tests. |
| `tests/test_boxmodel_setup.py` (modify) | shyfem | NUL-byte `boundn` returns a note instead of raising. |
| `shyfem-ui/README.md`, `CHANGELOG.md`, spec §11 | shyfem | Onboarding paragraph, changelog line, run-dir correction. |
| `~/laguna-admin/2026-09-18/README.md` | — | Mark `curonian-boxmodel-deploy-commands.txt` superseded by the script. |

---

### Task 1 (curonian): `export_ui_bundle.py`

**Interfaces:** `python3 shyfem_box/export_ui_bundle.py [--out ui_bundle] [--zip]`, run from `~/curonian`. Writes into `--out` (created, refuses to overwrite a non-empty dir without `--force`):

- `boxmodel.json` — schema 1; `title` "Curonian Lagoon 29-box, 2-D (1993–2016)"; `boxes` = `{"polygons": "b29polys.gpkg", "layer": "polygons", "id_field": "box"}`; `grid` = `{"grd": "curonian29.grd", "bas": "curonian29.bas", "boxes_txt": "boxes.txt"}`; `str` = the STR basename; `forcing` = `{"dir": "forcing"}`; `runs` = the three published runs (`run9316` "1993-2016, corrected Minija + extended Nemunas", `run9314_minijafix` "1993-2014, corrected Minija", `run9314` "1993-2014, pre-fix Minija") with **absolute** `dir` under `/home/razinka/curonian/published_runs/`, only those that exist; `observations` = `{"file": "observations.csv", "sites": "sites.csv"}`.
- `observations.csv` — long format `date,site,variable,value` from `physical_daily`, **read-only** connection. Rule, documented in the module docstring: for each of the mapped sites, one row per non-null value of `salinity` → `salinity`, `wtemp_mean` → `temperature`, `wlevel_mean` → `level` (**cm**, as stored; the UI converts to m on load). Rows are emitted sorted by `(site, variable, date)`. Coverage facts to state in the docstring (verified against the DB): the record starts 2001-01-01; Klaipėda has **no** `wtemp_mean` rows and only 365 `wlevel_mean` rows; Juodkrantė ends 2011-10-24; Uostadvaris starts 2010 and has no salinity. With the four mapped sites this rule yields **47 631** rows (the hand-built 2026-09-18 file has 47 601 — 30 fewer Klaipėda salinity rows; that file was assembled ad hoc and the script's rule is authoritative from now on, which the verification step reports rather than reproduces).
- `sites.csv` — `site,lat,lon,box`: Klaipeda 11, Juodkrante 17, Nida 23, Vente 25 (coordinates as in the existing bundle), plus **Uostadvaris with an empty box** (spec §11: drawn on the map, excluded from skill).
- Assets copied (never linked) from the repo: `b29polys.gpkg`, `curonian29.grd`, `curonian29.bas`, `boxes.txt`, the STR, and `forcing/{nemunas,minija,matrosovka,deima}.txt`. Every source path is resolved and its absence is a clear error naming the key.
- `--zip` writes `ui_bundle.zip` with the directory's contents at the archive root (importable by the Workbench).
- Prints a summary: row counts per site and variable, the files written with sizes, and the runs included.

**Steps:**
- [ ] Implement; run `python3 shyfem_box/export_ui_bundle.py --out /tmp/claude-1000/ui_bundle --zip` and paste the summary.
- [ ] Verification: per-file `sha256` / `diff` against `~/.shyfem-ui/users/admin/Curonian 29-box/`; report every difference and classify each as expected (sites.csv gains Uostadvaris; observations.csv +30 rows; README/cache absent from the bundle) or unexpected (must be fixed).
- [ ] Confirm the generated manifest loads: `load_manifest(Path(bundle), Config(deployment_mode="local", work_dir=…), None)` under the worker interpreter with `PYTHONPATH=~/shyfem/shyfem-ui`.
- [ ] Remove the stale hand-built `observations.csv` / `sites.csv` from the Curonian repo root (untracked intermediates, superseded by the script). Do not commit them.

### Task 2 (curonian): `cross_check_metrics.py` + committed output

**Interfaces:** `python3 shyfem_box/cross_check_metrics.py [--run run9316] [--tol 1e-12]`, run with `PYTHONPATH=~/shyfem/shyfem-ui` under the worker interpreter. For the chosen run:

- Load the package's view: `boxmodel_cache.load_cache_state(cache_dir_for(<admin project>, run), run)`, `boxmodel_skill.load_observations`/`load_sites` on the bundle's CSVs, `skill_table` and `band_amplitude_ratios`.
- Load the reference view: `compare_runs.read(<run>/boxes_2d.txt, box, idx)` daily means and `compare_runs.stats`, `compare_runs.bandamp`, `grid_summary.skill(..., anomaly=…)` on the same days from the same database (read-only).
- Print, per site × variable, `max |Δ|` for bias, RMSE, r, R², sd ratio and each band amplitude; exit non-zero if any exceeds `--tol`.
- Semantic difference to verify, not assume: `grid_summary.skill(anomaly=True)` de-means level and converts cm → m, while the package converts on load and compares anomalies — r and the sd ratio must match; level bias is "—" by construction in the UI and is compared as ~0.

**Steps:**
- [ ] Implement; run it on `run9316`; commit the output as `shyfem_box/cross_check_2026-09-26.txt`.
- [ ] If a metric disagrees beyond the tolerance, **stop and report** — that is a finding about the package, not something to paper over.

### Task 3 (shyfem): import skips the cache, and the review's defensive guard

**Files:** `shyfem_ui/services/project_export.py`, `tests/test_project_export.py`, `shyfem_ui/services/boxmodel_setup.py`, `tests/test_boxmodel_setup.py`.

**Steps:**
- [ ] Tests first: (a) a zip containing `.boxmodel_cache/<run>/state_daily.parquet` imports without that file on disk; (b) the same members are excluded from `_validate_archive_limits`' size budget, so an archive whose payload is under the limit only because the cache is excluded still imports (and one over the limit without the cache still raises); (c) export → import round trip leaves no `.boxmodel_cache` directory.
- [ ] Implement: filter cache members out **before** the budget and skip them in the extraction loop; keep the literal `_EXCLUDE_DIRNAMES` (importing the cache service would pull pandas into the export path).
- [ ] Test + implement the PR 3 review's sub-threshold guard: a `boundn` whose basename contains a NUL byte must return `(None, note)` from `resolve_forcing_file` rather than raise `ValueError` out of `pathlib`.

### Task 4 (shyfem): docs, spec correction, verification, PR

**Steps:**
- [ ] `shyfem-ui/README.md`, "Box-model analysis roots (server mode)": an onboarding paragraph — generate the bundle with `shyfem_box/export_ui_bundle.py`, import the zip on the Projects page, set `SHYFEM_UI_ANALYSIS_ROOTS='["/home/razinka/curonian/published_runs"]'`, remember the roots are readable by every authenticated user, and that the cache is excluded from both export and import so the first page load rebuilds it.
- [ ] Spec §11: correct the run-directory sentence to `published_runs` and note why (strict symlink resolution).
- [ ] `CHANGELOG.md` `[Unreleased]`: PR 4 line (bundle script, import rule, cross-check, docs).
- [ ] `~/laguna-admin/2026-09-18/README.md`: mark `curonian-boxmodel-deploy-commands.txt` superseded.
- [ ] ruff/black; full unit suite; all Playwright files (not concurrently); correctness review **before** merge; PR body: what landed, the two Curonian commits with their SHAs, the cross-check summary, the three expected bundle differences, the spec correction, deferrals (hourly-cache UI, manifest-editing form) and issue #86. Merge is the user's call.

## Self-review against spec §12 item 4

| Spec clause | Where |
|---|---|
| Curonian bundle script | Task 1, `shyfem_box/export_ui_bundle.py` (spec §11's file list, plus Uostadvaris) |
| export/import rules | Export landed in PR 1; **import** skip + budget exclusion in Task 3 (spec §9) |
| admin docs | Task 4, README onboarding paragraph |
| changelog | Task 4 |
| metric cross-check | Task 2, script + committed output (spec §10: a Curonian-repo script, recorded in this PR) |
