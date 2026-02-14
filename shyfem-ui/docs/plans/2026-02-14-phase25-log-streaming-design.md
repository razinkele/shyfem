# Phase 25: Real-Time Log Streaming — Design

**Date:** 2026-02-14

## Problem

Users see no log output during long-running SHYFEM simulations. Three root causes:

1. `job_local.py` accumulates stdout in memory and writes the file only at job
   completion — nothing to read during execution.
2. `run.py` passes `on_refresh=lambda: None` to the log viewer — the auto-refresh
   checkbox is a no-op.
3. `log_viewer.py` hardcodes `reactive.invalidate_later(2)` instead of using the
   existing `log_refresh_interval` config option.

## Fix: Pipeline Approach (no new services)

### 1. Incremental file writing — `job_local.py`

Change `output_callback` in `_execute_job()` to open stdout file in append mode
and write+flush each line as it arrives. Remove the post-completion
`Path(job.stdout_file).write_text(result.stdout)` since the file already has
content. Stderr stays as-is (small, written once at end).

### 2. Wire auto-refresh — `run.py`

- Pass `on_refresh=_refresh_log` instead of `lambda: None`
- Call `await _refresh_log()` inside the existing `_auto_refresh` effect

### 3. Honor config — `log_viewer.py`

Replace hardcoded `reactive.invalidate_later(2)` with `log_refresh_interval`
from config. Pass config value into `log_viewer_server()` as a parameter.

### 4. Efficient tail — `job_local.py` + `job_celery.py`

Replace `path.read_text()` (loads entire file) with seek-from-end: read last
~64KB, split lines, return last N. Safe for multi-GB log files.

### 5. Same approach for `job_celery.py`

Apply the same efficient tail to `CeleryJobQueue.get_output()`. Incremental
file writing is not needed there (Celery workers handle output differently).

## Skipped

- `LogBroadcaster` service — YAGNI. 2s polling is adequate for simulation logs.
- `SHYFEM_UI_LOG_STREAM_INTERVAL_MS` config — unnecessary with polling approach.
- Ensemble page auto-refresh — out of scope, works independently.

## Testing

- Unit test for seek-based tail function (empty, small, large, boundary)
- Unit test for incremental output_callback (mock file, verify flush per line)
- Unit test that log_viewer_server uses configurable interval
