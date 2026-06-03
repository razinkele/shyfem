"""Tests for NotificationService — SMTP email notifications."""

import smtplib
from unittest.mock import MagicMock, patch

from shyfem_ui.config import Config
from shyfem_ui.services.notification_service import NotificationService


def _make_config(**kwargs) -> Config:
    defaults = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_user": "noreply@example.com",
        "smtp_password": "secret",
        "smtp_from": "SHYFEM UI <noreply@example.com>",
    }
    defaults.update(kwargs)
    return Config(**defaults)


def _make_user(email="alice@example.com"):
    return {"username": "alice", "email": email}


def _make_job(success=True, name="test_sim", duration=42.0, working_dir="/data/shyfem/alice/projects/p1"):
    return {
        "name": name,
        "success": success,
        "duration": duration,
        "working_dir": working_dir,
        "stderr": "error: something went wrong\n" * 15,  # >10 lines
    }


class TestNotificationServiceNoSmtp:

    def test_no_smtp_host_skips_silently(self, caplog):
        """No smtp_host configured → no exception, logs warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.services.notification_service"):
            svc = NotificationService(Config(smtp_host=""))
            svc.notify_job_success(_make_user(), _make_job())
        assert "SMTP" in caplog.text or "smtp" in caplog.text.lower()

    def test_no_smtp_host_notify_failed_skips(self, caplog):
        """No smtp_host → notify_job_failed skips silently and logs warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.services.notification_service"):
            svc = NotificationService(Config(smtp_host=""))
            svc.notify_job_failed(_make_user(), _make_job(success=False))
        assert "SMTP" in caplog.text or "smtp" in caplog.text.lower()


class TestNotificationServiceSmtp:

    def test_notify_success_sends_email(self):
        """notify_job_success sends an email via SMTP."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_success(_make_user(), _make_job())
        mock_smtp.sendmail.assert_called_once()
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "finished" in msg_str.lower() or "success" in msg_str.lower()
        assert "test_sim" in msg_str

    def test_notify_success_subject_contains_job_name(self):
        """Success email subject contains the job name."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_success(_make_user(), _make_job(name="my_run"))
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "my_run" in msg_str

    def test_notify_failed_sends_email(self):
        """notify_job_failed sends an email with 'failed' in subject."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_failed(_make_user(), _make_job(success=False))
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "failed" in msg_str.lower()

    def test_notify_failed_truncates_stderr_to_10_lines(self):
        """Only the last 10 lines of stderr appear in the failure email body."""
        svc = NotificationService(_make_config())
        job = _make_job(success=False)
        job["stderr"] = "\n".join(f"line {i}" for i in range(20))  # 20 lines
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_failed(_make_user(), job)
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        # Last 10 lines are 10-19; first 10 (0-9) should not be in the email
        assert "line 0" not in msg_str
        assert "line 10" in msg_str

    def test_smtp_failure_does_not_raise(self, caplog):
        """SMTP error is caught and logged, not re-raised."""
        import logging
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "unavailable")):
            with caplog.at_level(logging.WARNING):
                svc.notify_job_success(_make_user(), _make_job())  # must not raise
        assert caplog.text  # something was logged

    def test_user_with_no_email_skips_silently(self):
        """User with no email address → no exception, no email sent."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            svc.notify_job_success({"username": "user", "email": None}, _make_job())
        mock_smtp_cls.assert_not_called()

    def test_notify_success_body_contains_output_path(self):
        """Success email body includes the job's working directory."""
        svc = NotificationService(_make_config())
        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            svc.notify_job_success(_make_user(), _make_job(working_dir="/data/shyfem/alice/p1"))
        _, _, msg_str = mock_smtp.sendmail.call_args[0]
        assert "/data/shyfem/alice/p1" in msg_str


class TestJobTransitionDetector:

    def setup_method(self):
        from shyfem_ui.services.notification_service import JobTransitionDetector
        self.svc = JobTransitionDetector()

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
        self.svc.check_transitions([
            {"id": "j1", "name": "a", "status": "running"},
            {"id": "j2", "name": "b", "status": "running"},
        ])
        events = self.svc.check_transitions([
            {"id": "j1", "name": "a", "status": "completed"},
            {"id": "j2", "name": "b", "status": "running"},
        ])
        assert len(events) == 1
        assert events[0]["job_id"] == "j1"

    def test_job_disappears_pruned(self):
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        self.svc.check_transitions([])
        assert "j1" not in self.svc._seen

    def test_first_poll_already_completed_no_event(self):
        """If a job is already completed on first poll, no event emitted."""
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "completed"}])
        assert events == []

    def test_pending_to_completed_emits_event(self):
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "pending"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "completed"}])
        assert len(events) == 1

    def test_pending_to_running_no_event(self):
        self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "pending"}])
        events = self.svc.check_transitions([{"id": "j1", "name": "sim1", "status": "running"}])
        assert events == []
