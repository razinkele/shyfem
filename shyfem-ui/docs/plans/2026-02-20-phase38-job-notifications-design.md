# Phase 38: Job Notification Improvements — Design

**Created:** 2026-02-20
**Status:** Approved
**Approach:** App-level polling with NotificationService (Approach A)

---

## Goal

Show job completion/failure notifications regardless of which page the user
is on, so users don't miss background job events.

## Decisions

- **Mechanism:** App-level polling (every 5s) with status transition detection
- **Notification style:** Simple text via `ui.notification_show()` — no action buttons
- **Scope:** Cross-page alerts only (no notification center, no browser desktop notifications)

## NotificationService

Pure Python class tracking job status transitions:

```python
class NotificationService:
    _seen: dict[str, str]  # job_id -> last_known_status

    def check_transitions(self, jobs: list[dict]) -> list[dict]:
        """Return list of terminal transition events."""
```

Rules:
- Only emits events for transitions TO terminal states: completed, failed, cancelled
- Ignores pending→running (not alert-worthy)
- First poll with already-terminal jobs → no event (avoids alert storm on startup)
- Prunes _seen entries for jobs no longer in the list
- Returns: `[{"job_id": str, "job_name": str, "old_status": str, "new_status": str}]`

## App-Level Wiring

In `app.py` server function:
- One `NotificationService` per session
- `reactive.invalidate_later(5)` to poll every 5 seconds
- `job_queue.list_jobs()` → `service.check_transitions()` → `notification_show()`
- Notification types:
  - completed: type="message", duration=8s
  - failed: type="error", duration=10s
  - cancelled: type="warning", duration=5s

## Testing (~10-12 tests)

Pure function tests on `check_transitions()`:
- No jobs → no events
- New running job → no event
- Running → completed → one event
- Running → failed → one event
- Completed stays completed → no duplicate
- Multiple jobs mixed transitions
- Job disappears → pruned from seen
- First poll with already-completed → no event
- Running → cancelled → one event
