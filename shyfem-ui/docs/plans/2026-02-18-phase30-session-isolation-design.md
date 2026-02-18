# Phase 30: Session Isolation — Design

**Date:** 2026-02-18
**Status:** Design approved

## Scope

In server mode, each browser session sees only its own jobs by default.
Projects remain shared (visible to all users). A toggle lets users switch
between "My Jobs" and "All Jobs" views.

## What Already Exists

- `Job.session_id` column (String(255), nullable) in DB model
- `JobQueue.list_jobs(session_id=...)` filter on both Local and Celery queues
- `run.py` already computes `_session_id = str(id(session))` and filters
  job listing in server mode

## What Needs to Change

### 1. Dashboard recent jobs filter (`pages/home.py`)

`_refresh_jobs()` calls `list_jobs(limit=5)` with no session filter.
In server mode, pass `session_id` so the Dashboard only shows the current
session's jobs by default.

Compute `_session_id = str(id(session))` in `home_server()`, same pattern
as `run.py`.

### 2. Fix `session.on_ended` multi-user bug (`app.py`)

The cleanup callback cancels ALL active jobs when any session disconnects.
In server mode with multiple users, this kills other users' jobs.

Fix: pass `session_id` to the cleanup, call
`list_jobs(session_id=sid)` to only cancel the disconnecting session's jobs.

### 3. "My Jobs" / "All Jobs" toggle

Add a checkbox on the **Run page** and **Dashboard** (server mode only,
hidden in local mode). Default: "My Jobs". When toggled to "All Jobs",
`list_jobs()` is called without `session_id`.

### 4. No DB migration

`Job.session_id` column already exists. Project model unchanged.

## Testing

- Dashboard job filtering: mock job_queue, verify session_id passed in server mode
- `session.on_ended` filtering: verify only matching session's jobs cancelled
- Toggle reactive state: verify filter changes on toggle

## Skipped

- Project-level session isolation (projects remain shared resources)
- Auth-gated admin toggle (single-credential Basic Auth doesn't differentiate users)
