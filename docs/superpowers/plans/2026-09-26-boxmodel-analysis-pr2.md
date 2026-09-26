# Box-model analysis, PR 2 (Compare) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship PR 2 of the box-model analysis feature: the **Compare** tab of the "Box model" page — two to four runs from the manifest, a difference map (B − A of the period mean), overlaid series for the selected box, the skill table side by side plus the per-year table, all on the intersection of days (spec §8, "Compare"). Fold in the mechanical follow-ups recorded for PR 2: the build registry moves from the page into the cache service, and the atomic-JSON writer / run-id regex / symlink guard are shared between the CLI and the service through a root-level module.

**Architecture:** Compare is read-only and works only on published caches. A new pure service `shyfem_ui/services/boxmodel_compare.py` computes the shared day intersection, the per-box period-mean difference, the overlaid series and the side-by-side pivot from `CachedRun.state_daily` frames; `skill_table` / `per_year_table` from `boxmodel_skill.py` are reused unchanged. The page gains a second map module (`cmpmap`) with its own layer/legend reactives, a run multi-select, a "B" select, the overlay plot, the side-by-side and per-year tables and a CSV download. The existing "Run comparison" tab **is** the skill half of Compare: it is renamed "Compare" and its render becomes the skill component; nothing is duplicated. The map component gains one diverging palette and a symmetric colour scale so zero sits on white.

**Tech Stack:** Python 3.13 (worker interpreter `/opt/micromamba/envs/shiny/bin/python3`), Shiny for Python 1.8, shinywidgets + Plotly, pandas + pyarrow, numpy, shiny_deckgl, pytest, Playwright (one extended E2E).

**Spec:** `docs/superpowers/specs/2026-09-17-boxmodel-analysis-design.md` (rev 4), §8 "Compare" and §7 (metrics). PR 1 plan: `docs/superpowers/plans/2026-09-17-boxmodel-analysis-pr1.md` (its Global Constraints apply verbatim).

## Global Constraints (in addition to PR 1's)

- **One intersection of days, computed once and shared** by the difference map, the overlay plot and the skill/per-year tables (`common_days`). `skill_table` intersects internally, but the diff map and overlay would otherwise silently use each run's own days.
- Compare reads only `state_daily` (via the page's existing `all_run_states()`, which uses `load_cache_state`); it never touches flux/meteo/hourly frames.
- Every new calc/render hangs off `all_run_states()` / `cache_generation`, **never** `status()` / `status_tick` (`tests/test_boxmodel_page.py::test_expensive_chain_hangs_off_cache_generation_not_the_poll_tick`). A second layers effect has the same write-only, everything-inside-`try` shape as `_layers` (`test_layers_effect_wraps_its_upstream_calls` is extended to cover it).
- Selector choices are updated under `reactive.event` with compare-before-set (a `reactive.Value.set` of a fresh-but-equal object re-triggers; see the self-write-loop rule).
- Fewer than two ready runs → a message, never an empty map.
- Labels, run labels and site names go through `ui.tags` / `_text`; tooltips are escaped at the sink (`build_box_layers`), never twice.
- The CLI (`shyfem_ui/boxmodel_cache_cli.py`) must not import anything under `shyfem_ui/services/` (`services/__init__.py` pulls in the ORM); shared helpers therefore live in a root-level module.
- Run E2E under the worker interpreter, never concurrently with the unit suite (shared DB). Do not add another canvas assertion (the WebGL check is the one local flake).
- Work in the worktree `/tmp/claude-1000/wt-pr2` on branch `feat/boxmodel-pr2`; `~/shyfem` stays on `main` (it is the live app).
- Commit style: conventional commits, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `shyfem_ui/boxmodel_common.py` (new, root-level) | `RUN_ID_RE`, `check_run_id`, `atomic_json`, `no_symlink_components` — shared by CLI and service. |
| `shyfem_ui/boxmodel_cache_cli.py` (modify) | Import the shared helpers instead of its private copies. |
| `shyfem_ui/services/boxmodel_cache.py` (modify) | Import the shared helpers; own the process-wide registry: `get_registry() -> BuildRegistry`. |
| `shyfem_ui/services/boxmodel_compare.py` (new) | `common_days`, `period_mean_diff`, `overlay_series`, `side_by_side`, `METRIC_COLUMNS`. Pure pandas. |
| `shyfem_ui/components/grid_map.py` (modify) | `PALETTE_DIVERGING` (blue–white–red) in `PALETTES`; `value_colors(..., symmetric=False)`; `build_box_layers(..., symmetric=False)`. |
| `shyfem_ui/pages/boxmodel.py` (modify) | "Run comparison" tab → "Compare": run multi-select, B select, `cmpmap`, overlay plot, side-by-side + per-year tables, CSV download; `REGISTRY` → `get_registry()`. |
| `tests/_boxmodel_fixture.py` (modify) | `make_box_run(..., offset=0.0)`, `value_at(..., offset=0.0)`, `make_box_project(..., extra_runs=[...])`. |
| `tests/test_boxmodel_fixture.py`, `tests/test_boxmodel_common.py` (new), `tests/test_boxmodel_compare.py` (new), `tests/test_grid_map_box_layers.py`, `tests/test_boxmodel_page.py`, `tests/test_boxmodel_cache_service.py`, `tests/test_boxmodel_cache_cli.py`, `tests/test_playwright_boxmodel.py` | Tests per task. |
| `shyfem-ui/README.md`, `CHANGELOG.md` | Compare paragraph; `[Unreleased]` entry. |

---

### Task 1: Fixture — a second run with an offset

**Files:** modify `tests/_boxmodel_fixture.py`, `tests/test_boxmodel_fixture.py`.

**Interfaces:**
- `value_at(var, box, stamp, offset: float = 0.0)`: `temp` and `salt` gain `+ offset`; every other variable unchanged.
- `make_box_run(run_dir, *, days=10, boxes=3, with_run_log=True, offset: float = 0.0) -> dict` threads `offset` into the state records (via `_state_record`), not into meteo/flux.
- `make_box_project(project_dir, run_dir, *, run_id="fix", polygons=True, obs_days=10, extra_runs: list[tuple[str, str, Path]] | None = None)`: each `(id, label, dir)` is appended to `manifest["runs"]` after the primary run.

**Steps:**
- [ ] Tests first: a run built with `offset=1.5` has `temp` records exactly `1.5` above `offset=0` for the same (box, hour), `salt` likewise, `cur_speed` identical; `make_box_project(..., extra_runs=[("b", "run B", dir_b)])` writes a manifest with two runs in order `["fix", "b"]`.
- [ ] Implement; run `tests/test_boxmodel_fixture.py`, `tests/test_boxmodel_output.py`, `tests/test_boxmodel_cache_cli.py` (the CLI must still parse an offset run).

### Task 2: Shared root-level helpers + registry ownership

**Files:** create `shyfem_ui/boxmodel_common.py`, `tests/test_boxmodel_common.py`; modify `shyfem_ui/boxmodel_cache_cli.py`, `shyfem_ui/services/boxmodel_cache.py`, `shyfem_ui/pages/boxmodel.py` (registry import only), `tests/test_boxmodel_cache_service.py`, `tests/test_boxmodel_cache_cli.py`, `tests/test_boxmodel_page.py` (if they pin the private names).

**Interfaces:**
- `boxmodel_common.RUN_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")`, `check_run_id(run_id) -> None` (raises `ValueError`), `atomic_json(path, payload) -> None` (mkstemp in `path.parent`, `os.replace`, unlink on failure), `no_symlink_components(p: Path) -> bool`.
- `boxmodel_cache.get_registry() -> BuildRegistry` — one module-level instance created lazily; `BuildRegistry` stays where it is. The page replaces `REGISTRY = BuildRegistry()` with `get_registry()` at each use (`reconcile_tmp_dirs(..., registry=get_registry(), ...)`, `cache_status(..., get_registry())`, build/cancel).
- The CLI keeps importing only stdlib/numpy/pandas/pyarrow + `boxmodel_output` + `boxmodel_common`.

**Steps:**
- [ ] Tests: `atomic_json` leaves no temp file on a failed dump and replaces atomically; `check_run_id` accepts `run9316`, rejects `../x`, `A`, 65 chars; `no_symlink_components` false when any component is a symlink; `get_registry()` returns the same object twice; a grep-style test that `boxmodel_cache_cli.py` imports nothing from `shyfem_ui.services`.
- [ ] Move/rename; keep the old private names as thin aliases only if a test imports them, otherwise update the tests.
- [ ] Run the cache-service, CLI and page test files.

### Task 3: Compare service (pure)

**Files:** create `shyfem_ui/services/boxmodel_compare.py`, `tests/test_boxmodel_compare.py`.

**Interfaces:**
- `common_days(runs: dict[str, CachedRun], start, end) -> pd.DatetimeIndex`: intersection of every run's `state_daily["date"]` (unique, sorted) clamped to `[start, end]`; empty index when any run is missing or the intersection is empty.
- `period_mean_diff(a: CachedRun, b: CachedRun, column: str, days: pd.DatetimeIndex) -> dict[int, float]`: for each box present in both, `mean_b − mean_a` over exactly `days`; boxes with no finite value in either are omitted.
- `overlay_series(runs: dict[str, CachedRun], box: int, column: str, days) -> dict[str, pd.Series]`: one daily series per run restricted to `days` (reuse `boxmodel_skill.model_series` then `.reindex(days)`).
- `side_by_side(skill: pd.DataFrame, run_ids: list[str], labels: dict[str, str]) -> pd.DataFrame`: long `skill_table` rows → index `(site, variable, metric)` for `metric in METRIC_COLUMNS = ("n", "bias", "rmse", "r", "r2", "sd_ratio")`, one column per run label in `run_ids` order; missing cells NaN; deterministic row order (site, variable, metric order as listed).

**Steps:**
- [ ] Tests from the fixture formulas: build runs A (`offset=0`) and B (`offset=1.5`) via the CLI or by constructing `CachedRun` frames directly from `value_at`; assert `period_mean_diff` is `1.5` for `temp` in every box and `0.0` for `cur_speed`; `common_days` of a 10-day and a 40-day run is the 10 days; clamping by `start/end`; `overlay_series` keys and lengths; `side_by_side` shape and a spot value against `compute_metrics`.
- [ ] Implement; ruff/black.

### Task 4: Diverging palette and symmetric scale

**Files:** modify `shyfem_ui/components/grid_map.py`, `tests/test_grid_map_box_layers.py`.

**Interfaces:**
- `PALETTE_DIVERGING` (7 stops, blue → white → red) registered as `"diverging"` in `PALETTES`.
- `value_colors(values, palette="viridis", n_bins=6, *, symmetric=False)`: with `symmetric=True` the bin range is `[-m, +m]` with `m = max(|finite values|)` (or `[-1, 1]` when all are zero), so the middle bin straddles zero.
- `build_box_layers(..., symmetric: bool = False)` forwards it.

**Steps:**
- [ ] Tests: symmetric bins are mirrored around zero for values `[-3, 1, 2]`; all-zero input does not divide by zero; the legend bins returned by `build_box_layers(symmetric=True)` straddle zero.
- [ ] Implement; run the grid-map tests.

### Task 5: The Compare tab (page)

**Files:** modify `shyfem_ui/pages/boxmodel.py`, `tests/test_boxmodel_page.py`.

**Interfaces (ids under the `boxmodel` module):**
- UI (replacing the "Run comparison" nav panel, title **"Compare"**): `ui.output_ui("cmp_controls")` (renders `input_selectize("cmp_runs", "Runs (2–4)", multiple=True, options={"maxItems": 4})` and `input_select("cmp_b", "B (difference is B − A; A = first run)")`); `grid_map_ui("cmpmap", height="440px")` + `ui.output_ui("cmp_legend")`; `output_widget("cmp_plot")`; `ui.output_ui("cmp_skill")` (the existing `run_comparison_table` render, renamed, now filtered to the chosen runs and the common days, rendered side by side); `ui.output_ui("cmp_per_year")`; `ui.download_button("cmp_download", "Download comparison CSV")`.
- Server: `cmp_layers`, `cmp_legend_bins` reactives (write-only for `_cmp_layers`); `@reactive.calc cmp_runs_selected() -> dict[str, CachedRun]` (validated subset of `all_run_states()`, 2–4, A first); `@reactive.calc cmp_days()` (= `common_days(selected, *_period_bounds())` where the bounds are the header period if set else the widest span); `@reactive.calc cmp_diff()` → `(values, label)` using `input.variable()`; `@reactive.calc cmp_overlay()`; `@reactive.calc cmp_skill_frames()` → `(side_by_side_df, per_year_df)`; `@reactive.effect _cmp_layers()` (same shape as `_layers`: everything inside `try`, writes only `cmp_layers`/`cmp_legend_bins`, uses `build_box_layers(..., palette="diverging", symmetric=True, posts=None, selected=selected_box.get())`); `grid_map_server("cmpmap", grd_file, extra_layers=cmp_layers, on_box_click=_on_box)`; `_fill_cmp_runs` effect under `reactive.event(all_run_states)` filling `cmp_runs` (first two preselected) and `cmp_b` with compare-before-set; `cmp_plot` overlay (one line per run, labels via `_text`, observations as markers for the mapped post of `input.box`); `cmp_skill` and `cmp_per_year` tables (per-year: message "Per-year skill needs ≥ 60 matched days per year" when empty); `cmp_download` via the page's non-deprecated download renderer, name `compare_<variable>_<A>_vs_<B>.csv`, built from the validated frames.
- Messages: no project / no observations / fewer than two ready runs / no common days — each a `ui.tags.p(..., class_="text-muted")`, never an empty map or a raised error.

**Steps:**
- [ ] Extend `tests/test_boxmodel_page.py` first: `test_ui_builds_without_a_session` sees the new ids and no "Run comparison" text; the expensive-chain test also asserts `cmp_diff`/`cmp_skill_frames`/`_cmp_layers` bodies contain neither `status_tick` nor `status()`; `test_layers_effect_wraps_its_upstream_calls` is extended to `_cmp_layers`; a source test that `_fill_cmp_runs` is under `reactive.event` and compares before `update_selectize`/`update_select`; the download name is built from validated inputs; `REGISTRY = BuildRegistry()` is gone from the page and `get_registry()` is used.
- [ ] Implement; run `tests/test_boxmodel_page.py`, `tests/test_boxmodel_*.py`, `tests/test_app_wiring.py`.

### Task 6: End-to-end

**Files:** modify `tests/test_playwright_boxmodel.py`.

**Steps:**
- [ ] In the existing test, after the skill row assertion: the fixture now also builds run `b` (`make_box_run(dir_b, days=40, offset=1.5)`, `extra_runs=[("b", "run B", dir_b)]`); select run `b` in `#boxmodel-run`, click build, wait for "ready" (60 s); open the **Compare** tab; `expect(#boxmodel-cmp_legend)` to contain a negative and a positive bound (diverging legend around 1.5); `expect(#boxmodel-cmp_skill table tbody tr).first` visible and the header to contain both run labels; `#boxmodel-cmp_per_year` to contain "60 matched days" (40-day fixture). No new canvas assertion.
- [ ] Run the file alone under the worker interpreter.

### Task 7: Docs, verification, pull request

**Files:** `shyfem-ui/README.md` (Box model paragraph + the "Compare and Setup tabs follow" sentence), `CHANGELOG.md` `[Unreleased]`.

**Steps:**
- [ ] README: one paragraph on Compare (runs 2–4, B − A period mean, common days, side-by-side + per-year, CSV); remove "Compare … follow".
- [ ] `ruff check` + `black --check`; full unit suite; all `tests/test_playwright_*.py` (not concurrently).
- [ ] One correctness review of the branch diff **before** merge; fix findings; PR with summary, deviations from spec, deferred follow-ups (grid parsed once per generation; quota double-count during publish), test plan.

## Self-review against spec §8 "Compare"

| Spec clause | Where |
|---|---|
| two to four runs from the manifest | `cmp_runs` selectize, `maxItems` 4, validated in `cmp_runs_selected` |
| difference map (B − A of the period mean) | `period_mean_diff` + `cmpmap` with diverging symmetric palette |
| overlaid series for the selected box | `overlay_series` + `cmp_plot`, box shared with the Time-series tab via `_on_box` |
| skill side by side plus the per-year table | `side_by_side(skill_table(...))`, `per_year_table` |
| all on the intersection of days | `common_days` computed once in `cmp_days()` and passed to all three |
