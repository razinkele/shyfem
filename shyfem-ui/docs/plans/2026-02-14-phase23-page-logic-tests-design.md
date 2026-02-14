# Phase 23: Page Logic Tests — Design

**Date:** 2026-02-14
**Scope:** Unit tests for module-level pure functions in compare, ensemble, and visualize pages

## Context

3 pages contain complex pure logic at module level (outside closures). These
functions accept plain data structures and return results with no Shiny
reactive dependencies.

## Importable Pure Functions (11 total)

### compare.py (2 functions)
- `_compute_param_diff(str_a, str_b, name_a, name_b)` — STR file diff
- `_load_ts(path)` — time series file loading

### ensemble.py (5 functions)
- `_try_convert(value)` — string to int/float coercion
- `_combo_label(combo, index)` — directory name generation
- `_load_ts(path)` — time series loading (with path-exists guard)
- `_build_duration_chart(jobs)` — Plotly bar chart from JobInfo list
- `_build_ensemble_ts_plot(run_data)` — overlaid time series with envelope

### visualize.py (4 functions)
- `_load_timeseries(path)` — CSV/TSV loading with pandas fallback
- `_plotly_timeseries(data, plot_type, show_grid)` — Plotly figure
- `_compare_grids(grd1, grd2, colormap)` — side-by-side grid comparison
- `_compare_timeseries(ts1, ts2)` — overlaid time series comparison

## Skipped
- `_build_combinations` — closure inside ensemble_server, not importable
- `_apply_param_combo` — depends on StrParser internals
- `_plotly_netcdf`, `_build_vertical_profile`, `_build_transect`, `_compare_netcdf` — accept Shiny `input` param
- `_netcdf_statistics`, `_timeseries_statistics` — return ui.Tag (brittle assertions)

## Architecture
- Pure function testing — no Shiny, no ASGI mocking
- Mock StrFile objects (SimpleNamespace with sections/parameters)
- Reuse GrdFile fixture pattern from Phase 22
- `tmp_path` fixture for file I/O tests
- Plotly `go.Figure` type assertions + trace count checks
- ~30 new tests across 3 files
