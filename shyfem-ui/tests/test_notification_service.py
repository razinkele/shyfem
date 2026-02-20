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
