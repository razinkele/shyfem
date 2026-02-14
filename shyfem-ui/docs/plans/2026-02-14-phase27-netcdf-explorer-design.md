# Phase 27: NetCDF Variable Explorer — Design

**Date:** 2026-02-14

## Scope

Enhance existing NetCDF support with metadata visibility. Variable selection
dropdown and dimension sliders already work. We add:

1. **Variable info table** — pure function `build_variable_table(ds)` returns
   list of dicts (name, dims, dtype, units, long_name, min/max). Displayed in
   Data Info tab when dtype is netcdf.

2. **Coordinate labels** — pure function `get_dim_label(ds, dim_name, index)`
   converts integer index to human-readable label (timestamps, depth values).
   Displayed as reactive text below each dimension slider.

3. **Variable metadata panel** — pure function `get_variable_attrs(ds, var_name)`
   extracts key attrs (long_name, standard_name, units, valid_range, _FillValue).
   Displayed below variable selector.

## Architecture

- All three are pure functions taking xarray objects, returning plain data
- No changes to existing sliders, plots, or variable dropdown
- UI additions are minimal: one table, one text output per slider, one info div
- Testable with synthetic xarray.Dataset fixtures

## Skipped

- Separate variable list panel (dropdown already works)
- New slicing controls (existing sliders adequate)
- Search/filter/grouping (YAGNI for current user base)
- Label-based indexing via `sel()` (keep `isel()` — simpler)
