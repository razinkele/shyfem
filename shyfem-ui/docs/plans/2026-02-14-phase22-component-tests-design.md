# Phase 22: Component Test Coverage — Design

**Date:** 2026-02-14
**Scope:** Unit tests for pure functions in job_status, log_viewer, and plot_widget

## Context

4 components had zero unit tests. file_browser now has 9 tests from Phase 19.
The remaining 3 components each have pure, importable functions that can be
tested without Shiny session machinery.

## Test Suites

### 1. job_status (`tests/test_job_status.py`)
Test 4 pure functions:
- `format_duration()` — None, 0s, 30s, 90s, 3600s edge cases
- `format_datetime()` — None and datetime objects
- `get_status_badge()` — all 6 JobStatus enum values
- `job_list_table()` — empty list and multiple jobs

### 2. log_viewer (`tests/test_log_viewer.py`)
Test `format_log_line()`:
- Plain text (HTML-escaped), error/warning/success coloring
- XSS prevention (tags escaped), line truncation at 4096 chars
- Non-string input coercion, `>>>` header highlighting

### 3. plot_widget (`tests/test_plot_widget.py`)
Build synthetic GrdFile (4 nodes, 2 triangles) and test:
- `plot_mesh()`, `plot_depth_contour()`, `plot_boundaries()`, `plot_element_quality()`
- Each returns plt.Figure with expected title text

## Skipped
- 22.2 file_browser — already has 9 tests from Phase 19
- Closures inside server functions — not accessible for unit testing

## Architecture
- Pure function testing — no Shiny, no ASGI mocking
- Synthetic GrdFile for plot tests (using parser_grd types)
- ~25 new tests across 3 files
