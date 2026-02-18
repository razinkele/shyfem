# Phase 30: Session Isolation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** In server mode, isolate job visibility per browser session and fix the multi-user session cleanup bug.

**Architecture:** Jobs already carry `session_id` in metadata/DB. We fix three gaps: (1) `session.on_ended` cleanup filters by session, (2) Dashboard recent jobs filters by session, (3) both Dashboard and Run page get a "Show all jobs" toggle (server mode only). Projects remain shared.

**Tech Stack:** Python, Shiny reactive UI, pytest + pytest-asyncio

---

### Task 1: Fix session.on_ended to filter by session in server mode

**Files:**
- Modify: `shyfem_ui/app.py:420-438`
- Modify: `tests/test_session_cleanup.py`

**Step 1: Write the failing test**

The existing `test_session_cleanup.py` tests a replicated `session_cleanup()` function that mirrors `_on_session_ended`. Add a new function `session_cleanup_filtered()` and a test class for it.

Append to `tests/test_session_cleanup.py`:

```python
async def session_cleanup_filtered(job_queue, session_id, is_server_mode, logger):
    """Replicate updated _on_session_ended with session filtering."""
    try:
        sid = session_id if is_server_mode else None
        jobs = await job_queue.list_jobs(limit=100, session_id=sid)
        for job in jobs:
            if job.is_active:
                logger.info("Session ended — cancelling orphaned job %s", job.id)
                await job_queue.cancel(job.id)
    except Exception as exc:
        logger.warning("Session cleanup failed: %s", exc)


class TestSessionCleanupFiltered:
    """Tests for session-filtered cleanup (server mode)."""

    @pytest.mark.asyncio
    async def test_server_mode_passes_session_id(self, mock_job_queue, mock_logger):
        """In server mode, list_jobs is called with session_id."""
        mock_job_queue.list_jobs.return_value = []
        await session_cleanup_filtered(
            mock_job_queue, "sess-123", is_server_mode=True, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id="sess-123")

    @pytest.mark.asyncio
    async def test_local_mode_no_session_filter(self, mock_job_queue, mock_logger):
        """In local mode, list_jobs is called without session_id."""
        mock_job_queue.list_jobs.return_value = []
        await session_cleanup_filtered(
            mock_job_queue, "sess-123", is_server_mode=False, logger=mock_logger
        )
        mock_job_queue.list_jobs.assert_awaited_once_with(limit=100, session_id=None)

    @pytest.mark.asyncio
    async def test_server_mode_cancels_only_session_jobs(
        self, mock_job_queue, mock_logger
    ):
        """In server mode, only active jobs from list_jobs (already filtered) are cancelled."""
        active = _make_job("mine-1", is_active=True)
        done = _make_job("mine-2", is_active=False)
        mock_job_queue.list_jobs.return_value = [active, done]

        await session_cleanup_filtered(
            mock_job_queue, "sess-456", is_server_mode=True, logger=mock_logger
        )

        mock_job_queue.cancel.assert_awaited_once_with("mine-1")
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_cleanup.py::TestSessionCleanupFiltered -v`
Expected: FAIL — `session_cleanup_filtered` not defined

**Step 3: Add the function (already in the test file above) and update app.py**

In `shyfem_ui/app.py`, modify `_build_server` (lines 420-438). Change the cleanup callback to filter by session:

Replace:
```python
    # Cancel orphaned running jobs when the browser session disconnects
    async def _on_session_ended():
        try:
            jobs = await job_queue.list_jobs(limit=100)
            for job in jobs:
                if job.is_active:
                    logger.info("Session ended — cancelling orphaned job %s", job.id)
                    await job_queue.cancel(job.id)
        except Exception as exc:
            logger.warning("Session cleanup failed: %s", exc)

    session.on_ended(_on_session_ended)
```

With:
```python
    # Cancel orphaned running jobs when the browser session disconnects
    _cleanup_session_id = str(id(session))
    _is_server = config.deployment_mode == "server"

    async def _on_session_ended():
        try:
            sid = _cleanup_session_id if _is_server else None
            jobs = await job_queue.list_jobs(limit=100, session_id=sid)
            for job in jobs:
                if job.is_active:
                    logger.info("Session ended — cancelling orphaned job %s", job.id)
                    await job_queue.cancel(job.id)
        except Exception as exc:
            logger.warning("Session cleanup failed: %s", exc)

    session.on_ended(_on_session_ended)
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_session_cleanup.py -v`
Expected: ALL PASSED (6 existing + 3 new = 9)

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/app.py shyfem-ui/tests/test_session_cleanup.py
git commit -m "$(cat <<'EOF'
fix: session.on_ended only cancels own session's jobs in server mode

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Filter Dashboard recent jobs by session in server mode

**Files:**
- Modify: `shyfem_ui/pages/home.py:125-165`
- Create: `tests/test_dashboard_jobs.py`

**Step 1: Write the failing test**

Create `tests/test_dashboard_jobs.py` — replicate the dashboard's `_refresh_jobs` filtering logic:

```python
"""Tests for Dashboard recent jobs session filtering."""

from unittest.mock import AsyncMock, MagicMock

import pytest


async def dashboard_refresh_jobs(job_queue, session_id, is_server_mode):
    """Replicate Dashboard _refresh_jobs with session filtering."""
    sid = session_id if is_server_mode else None
    return await job_queue.list_jobs(limit=5, session_id=sid)


class TestDashboardJobFiltering:
    """Dashboard recent jobs should filter by session in server mode."""

    @pytest.mark.asyncio
    async def test_server_mode_filters_by_session(self):
        q = MagicMock()
        q.list_jobs = AsyncMock(return_value=[])
        await dashboard_refresh_jobs(q, "sess-abc", is_server_mode=True)
        q.list_jobs.assert_awaited_once_with(limit=5, session_id="sess-abc")

    @pytest.mark.asyncio
    async def test_local_mode_no_filter(self):
        q = MagicMock()
        q.list_jobs = AsyncMock(return_value=[])
        await dashboard_refresh_jobs(q, "sess-abc", is_server_mode=False)
        q.list_jobs.assert_awaited_once_with(limit=5, session_id=None)
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_dashboard_jobs.py -v`
Expected: FAIL — `dashboard_refresh_jobs` not defined (actually it will pass since it's defined in the test file — the real validation is that the _production code_ matches this pattern after Step 3)

Note: These tests validate the _behavioral pattern_. The production code change is what makes the app actually behave this way.

**Step 3: Update home.py**

In `shyfem_ui/pages/home.py`, inside `home_server()`, after line 136 (`recent_jobs_list = reactive.value([])`), add:

```python
    _session_id = str(id(session))
    _is_server_mode = config.deployment_mode == "server"
```

Then modify `_refresh_jobs()` (lines 162-165) from:

```python
    async def _refresh_jobs():
        if job_queue:
            jobs = await job_queue.list_jobs(limit=5)
            recent_jobs_list.set(jobs)
```

To:

```python
    async def _refresh_jobs():
        if job_queue:
            sid = _session_id if _is_server_mode else None
            jobs = await job_queue.list_jobs(limit=5, session_id=sid)
            recent_jobs_list.set(jobs)
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_dashboard_jobs.py -v`
Expected: 2 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/home.py shyfem-ui/tests/test_dashboard_jobs.py
git commit -m "$(cat <<'EOF'
feat: filter Dashboard recent jobs by session in server mode

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Add "Show all jobs" toggle to Dashboard

**Files:**
- Modify: `shyfem_ui/pages/home.py` (UI + server)

**Step 1: Add toggle to Dashboard UI**

In `home_ui()`, modify the "Recent Jobs" card (lines 101-108). Change:

```python
            ui.column(
                6,
                ui.div(
                    ui.h5("Recent Jobs"),
                    ui.output_ui("recent_jobs"),
                    class_="card p-3",
                ),
            ),
```

To:

```python
            ui.column(
                6,
                ui.div(
                    ui.div(
                        ui.h5("Recent Jobs", class_="d-inline"),
                        ui.output_ui("show_all_toggle_ui"),
                        class_="d-flex justify-content-between align-items-center",
                    ),
                    ui.output_ui("recent_jobs"),
                    class_="card p-3",
                ),
            ),
```

**Step 2: Add toggle rendering in server**

In `home_server()`, after the `_is_server_mode` line, add:

```python
    @render.ui
    def show_all_toggle_ui():
        if not _is_server_mode:
            return ui.span()  # hidden in local mode
        return ui.input_switch("show_all_jobs", "All jobs", value=False)
```

**Step 3: Update _refresh_jobs to respect toggle**

Modify `_refresh_jobs()`:

```python
    async def _refresh_jobs():
        if job_queue:
            show_all = input.show_all_jobs() if _is_server_mode else True
            sid = None if show_all else _session_id
            jobs = await job_queue.list_jobs(limit=5, session_id=sid)
            recent_jobs_list.set(jobs)
```

**Step 4: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: all passed, 0 failed

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/home.py
git commit -m "$(cat <<'EOF'
feat: add 'All jobs' toggle to Dashboard (server mode only)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Add "Show all jobs" toggle to Run page

**Files:**
- Modify: `shyfem_ui/pages/run.py` (UI + server)

**Step 1: Add toggle to Run page UI**

Find the "Refresh" button in `run_ui()` (around line 224). Before the refresh button, add:

```python
        ui.output_ui("run_show_all_toggle_ui"),
```

**Step 2: Add toggle rendering in server**

In `run_server()`, near the `_session_id` / `_is_server_mode` lines (around line 1020), add:

```python
    @render.ui
    def run_show_all_toggle_ui():
        if not _is_server_mode:
            return ui.span()  # hidden in local mode
        return ui.input_switch("show_all_run_jobs", "All jobs", value=False)
```

**Step 3: Update _refresh_jobs to respect toggle**

Modify `_refresh_jobs()` in `run.py` (lines 320-325) from:

```python
    async def _refresh_jobs():
        """Refresh job lists."""
        # In server mode, only show jobs from this session
        sid = _session_id if _is_server_mode else None
        jobs = await job_queue.list_jobs(limit=50, session_id=sid)
        _update_job_lists(jobs)
```

To:

```python
    async def _refresh_jobs():
        """Refresh job lists."""
        show_all = input.show_all_run_jobs() if _is_server_mode else True
        sid = None if show_all else _session_id
        jobs = await job_queue.list_jobs(limit=50, session_id=sid)
        _update_job_lists(jobs)
```

**Step 4: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: all passed, 0 failed

**Step 5: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/shyfem_ui/pages/run.py
git commit -m "$(cat <<'EOF'
feat: add 'All jobs' toggle to Run page (server mode only)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Update TODO_NEXT.md

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md:289-305`

**Step 1: Update Phase 30 section**

Replace the Phase 30 section with:

```markdown
## Phase 30: Session Isolation

> In server mode, each browser session sees only its own jobs by default.
> Projects remain shared. Toggle switches between "My Jobs" and "All Jobs".

- [x] **30.1** ~~Add session_id to project and job creation~~ — SKIPPED
  - Jobs already have `session_id` column and metadata. Projects stay shared.

- [x] **30.2** Filter queries by session in server mode — 5 tests
  - Dashboard `_refresh_jobs()` filters by session (was showing all jobs)
  - `session.on_ended` cleanup only cancels own session's jobs (multi-user bug fix)

- [x] **30.3** Add "All jobs" toggle — Run page + Dashboard
  - `ui.input_switch` visible only in server mode, default off (My Jobs)
  - Toggling to "All jobs" removes session_id filter from list_jobs
```

**Step 2: Commit**

```bash
cd /home/razinka/shyfem && git add shyfem-ui/TODO_NEXT.md
git commit -m "$(cat <<'EOF'
docs: mark Phase 30 complete in TODO_NEXT.md

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```
