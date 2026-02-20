# Phase 38: Job Notification Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show job completion/failure notifications on every page, not just the Run page.

**Architecture:** A `NotificationService` class detects job status transitions by comparing current statuses against a seen-set. Wired into `_build_server()` in `app.py` via `reactive.invalidate_later(5)` to poll every 5 seconds. Uses existing `ui.notification_show()`.

**Tech Stack:** Python, Shiny for Python reactives, existing `JobQueue.list_jobs()` API.

---

### Task 1: Add `NotificationService` with tests

**Files:**
- Create: `shyfem-ui/shyfem_ui/services/notification_service.py`
- Create: `shyfem-ui/tests/test_notification_service.py`

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_notification_service.py`:

```python
"""Tests for NotificationService job status transition detection."""

import pytest

from shyfem_ui.services.notification_service import NotificationService


class TestCheckTransitions:

    def setup_method(self):
        self.svc = NotificationService()

    def test_no_jobs_no_events(self):
        events = self.svc.check_transitions([])
        assert events == []

    def test_new_running_job_no_event(self):
        """A newly appeared running job should not trigger a notification."""
        jobs = [{"id": "j1", "name": "sim1", "status": "running"}]
        events = self.svc.check_transitions(jobs)
        assert events == []

    def test_running_to_completed(self):
        """Running -> completed should emit one event."""
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "completed"}])
        assert len(events) == 1
        assert events[0]["job_id"] == "j1"
        assert events[0]["job_name"] == "sim1"
        assert events[0]["old_status"] == "running"
        assert events[0]["new_status"] == "completed"

    def test_running_to_failed(self):
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "failed"}])
        assert len(events) == 1
        assert events[0]["new_status"] == "failed"

    def test_running_to_cancelled(self):
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "cancelled"}])
        assert len(events) == 1
        assert events[0]["new_status"] == "cancelled"

    def test_completed_stays_completed_no_duplicate(self):
        """Same terminal status on consecutive polls should not re-emit."""
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "completed"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "completed"}])
        assert events == []

    def test_multiple_jobs_mixed_transitions(self):
        """Multiple jobs with different transitions."""
        self.svc.check_transitions([
            {"id": "j1", "name": "sim1", "status": "running"},
            {"id": "j2", "name": "sim2", "status": "running"},
            {"id": "j3", "name": "sim3", "status": "pending"},
        ])
        events = self.svc.check_transitions([
            {"id": "j1", "name": "sim1", "status": "completed"},
            {"id": "j2", "name": "sim2", "status": "running"},  # unchanged
            {"id": "j3", "name": "sim3", "status": "running"},  # pending->running, not terminal
        ])
        assert len(events) == 1
        assert events[0]["job_id"] == "j1"

    def test_job_disappears_pruned(self):
        """Jobs no longer in the list should be pruned from seen set."""
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        self.svc.check_transitions([])  # j1 gone
        assert "j1" not in self.svc._seen

    def test_first_poll_already_completed_no_event(self):
        """On first poll, already-terminal jobs should not fire notifications."""
        events = self.svc.check_transitions([
            {"id": "j1", "name": "sim1", "status": "completed"},
            {"id": "j2", "name": "sim2", "status": "failed"},
        ])
        assert events == []

    def test_pending_to_completed_emits_event(self):
        """Even pending -> completed should notify (job may skip running)."""
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "pending"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "completed"}])
        assert len(events) == 1

    def test_pending_to_running_no_event(self):
        """Non-terminal transitions don't trigger notifications."""
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "pending"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        assert events == []
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_notification_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shyfem_ui.services.notification_service'`

**Step 3: Implement NotificationService**

Create `shyfem-ui/shyfem_ui/services/notification_service.py`:

```python
"""Job status transition detection for cross-page notifications."""

import logging

logger = logging.getLogger(__name__)

# Terminal statuses that warrant user notification
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


class NotificationService:
    """Detects job status transitions and emits notification events.

    Call check_transitions() periodically with the current job list.
    Returns events only for transitions TO terminal states.
    """

    def __init__(self):
        self._seen: dict[str, str] = {}  # job_id -> last_known_status

    def check_transitions(self, jobs: list[dict]) -> list[dict]:
        """Compare current job statuses against last seen.

        Args:
            jobs: List of dicts with keys: id, name, status.

        Returns:
            List of transition event dicts with keys:
            job_id, job_name, old_status, new_status.
        """
        current: dict[str, dict] = {}
        for job in jobs:
            current[job["id"]] = job

        events: list[dict] = []

        for job_id, job in current.items():
            status = job["status"]
            old_status = self._seen.get(job_id)

            if old_status is None:
                # First time seeing this job — record but don't notify
                self._seen[job_id] = status
                continue

            if status != old_status and status in _TERMINAL_STATUSES:
                events.append({
                    "job_id": job_id,
                    "job_name": job.get("name", job_id),
                    "old_status": old_status,
                    "new_status": status,
                })

            self._seen[job_id] = status

        # Prune jobs no longer in the list
        stale = set(self._seen) - set(current)
        for job_id in stale:
            del self._seen[job_id]

        return events
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_notification_service.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && git add shyfem_ui/services/notification_service.py tests/test_notification_service.py && git commit -m "feat: add NotificationService for job status transitions

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Wire NotificationService into app.py

**Files:**
- Modify: `shyfem-ui/shyfem_ui/app.py` — `_build_server()` (lines 505-548)

**Step 1: Add import**

At the top of `app.py`, after the existing imports (around line 31), add:

```python
from shyfem_ui.services.notification_service import NotificationService
```

**Step 2: Add notification polling to `_build_server()`**

Inside `_build_server()`, after the page server initializations (after line 547), add:

```python
    # --- Cross-page job notifications ---
    _notification_svc = NotificationService()

    @reactive.effect
    def _poll_job_notifications():
        reactive.invalidate_later(5)  # Poll every 5 seconds

        import asyncio

        async def _check():
            sid = _cleanup_session_id if _is_server else None
            jobs = await job_queue.list_jobs(limit=100, session_id=sid)
            job_dicts = [
                {"id": j.id, "name": j.name, "status": j.status.value}
                for j in jobs
            ]
            events = _notification_svc.check_transitions(job_dicts)
            for event in events:
                status = event["new_status"]
                name = event["job_name"]
                if status == "completed":
                    ui.notification_show(
                        f"Job '{name}' completed successfully.",
                        type="message",
                        duration=8,
                    )
                elif status == "failed":
                    ui.notification_show(
                        f"Job '{name}' failed.",
                        type="error",
                        duration=10,
                    )
                elif status == "cancelled":
                    ui.notification_show(
                        f"Job '{name}' was cancelled.",
                        type="warning",
                        duration=5,
                    )

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_check())
            else:
                asyncio.run(_check())
        except Exception:
            logger.debug("Notification poll error", exc_info=True)
```

**Step 3: Run full test suite**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: 775+ passed (764 baseline + 11 new), 0 failed

**Step 4: Commit**

```bash
cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && git add shyfem_ui/app.py && git commit -m "feat: wire job notification polling into app server

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Update TODO_NEXT.md and final verification

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md` — Add Phase 38 section after Phase 37

**Step 1: Add Phase 38 entry**

After the Phase 37 section, add:

```markdown
---

## Phase 38: Job Notification Improvements

> Cross-page job completion/failure notifications using app-level polling
> with status transition detection.

- [x] **38.1** Add `NotificationService` — 11 tests
  - Detects transitions to terminal states (completed, failed, cancelled)
  - First-poll deduplication (no alert storm on startup)
  - Prunes stale jobs from seen set

- [x] **38.2** Wire into `_build_server()` in `app.py`
  - `reactive.invalidate_later(5)` polls job queue every 5 seconds
  - Calls `ui.notification_show()` with appropriate type/duration
  - Session-aware in server mode (only own jobs)
```

**Step 2: Run full test suite**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: 775+ passed, 0 failed

**Step 3: Commit**

```bash
cd /home/razinka/shyfem/.claude/worktrees/phase38-notifications/shyfem-ui && git add TODO_NEXT.md && git commit -m "docs: mark Phase 38 job notifications complete

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
