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
                events.append(
                    {
                        "job_id": job_id,
                        "job_name": job.get("name", job_id),
                        "old_status": old_status,
                        "new_status": status,
                    }
                )

            self._seen[job_id] = status

        # Prune jobs no longer in the list
        stale = set(self._seen) - set(current)
        for job_id in stale:
            del self._seen[job_id]

        return events
