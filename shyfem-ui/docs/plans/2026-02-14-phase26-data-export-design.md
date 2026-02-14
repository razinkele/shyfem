# Phase 26: Data Export — Design

**Date:** 2026-02-14

## Scope

Scoped to genuinely missing features. Existing exports (Plotly PNG modebar,
timeseries CSV, job reports) are already functional.

## What We Build

### 1. Grid statistics JSON export — `grid_prep.py`

Add "Export Stats JSON" button to Grid Prep page. Serializes
`GrdParser.get_statistics()` output as formatted JSON and triggers browser
download via the established base64 data URI pattern (from log_viewer.py).

### 2. Enhanced Plotly modebar — `visualize.py`

Add a shared config dict applied to all Plotly figures: SVG export option,
meaningful filenames, no Plotly logo. Declarative config, not behavioral code.

## What We Skip (already exists)

- **26.1 Plot PNG export**: Plotly modebar camera icon already works
- **26.2 CSV export**: `timeseries.py` has full CSV export (lines 376-422)
- **26.3 Report download**: `run.py` has "Generate Report" with ReportBuilder

## Architecture

- Reuse base64 data URI pattern from `log_viewer.py` (lines 163-179)
- Pure function `grid_stats_to_json(stats_dict)` for testability
- Plotly config as a module-level dict constant, applied via `fig.show(config=...)`

## Testing

- Unit test for `grid_stats_to_json()`: valid dict, empty dict, nested values
- No tests for Plotly config (declarative, no logic)
