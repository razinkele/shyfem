"""Email notification service — sends SMTP notifications on job completion.

If smtp_host is not configured, all methods log a warning and return silently.
SMTP errors are caught and logged — a notification failure must never crash a job.
"""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from pathlib import Path

import jinja2

from shyfem_ui.config import Config

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)

# Terminal statuses that warrant user notification (used by JobTransitionDetector)
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


class NotificationService:
    """Sends email notifications for simulation job completion events."""

    def __init__(self, config: Config):
        self._config = config

    def notify_job_success(self, user: dict, job: dict) -> None:
        """Send a 'simulation finished' email to the user.

        Args:
            user: Dict with at least 'username' and 'email' keys.
            job: Dict with 'name', 'duration', 'working_dir' keys.
        """
        if not self._config.smtp_host:
            logger.warning(
                "SMTP not configured — skipping success notification for %s", user.get("username")
            )
            return
        if not user.get("email"):
            return

        body = _jinja_env.get_template("job_success.txt").render(
            username=user["username"],
            job_name=job["name"],
            duration=_format_duration(job.get("duration")),
            working_dir=job.get("working_dir", ""),
        )
        self._send(user["email"], body)

    def notify_job_failed(self, user: dict, job: dict) -> None:
        """Send a 'simulation failed' email to the user.

        Args:
            user: Dict with at least 'username' and 'email' keys.
            job: Dict with 'name', 'stderr' keys.
        """
        if not self._config.smtp_host:
            logger.warning(
                "SMTP not configured — skipping failure notification for %s", user.get("username")
            )
            return
        if not user.get("email"):
            return

        stderr = job.get("stderr") or ""
        stderr_tail = "\n".join(stderr.splitlines()[-10:])

        body = _jinja_env.get_template("job_failed.txt").render(
            username=user["username"],
            job_name=job["name"],
            stderr_tail=stderr_tail,
        )
        self._send(user["email"], body)

    def _send(self, to_addr: str, rendered_template: str) -> None:
        """Parse subject from template first line, send via SMTP.

        Template format: first line is 'Subject: ...' followed by blank line and body.
        """
        lines = rendered_template.strip().splitlines()
        subject_line = lines[0] if lines else "Subject: SHYFEM Notification"
        subject = subject_line.removeprefix("Subject:").strip()
        if len(lines) >= 2 and lines[1].strip() != "":
            logger.warning(
                "Email template missing blank separator after Subject line; body may be incomplete"
            )
        body = "\n".join(lines[2:]).strip()  # skip subject + blank line

        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = self._config.smtp_from
        msg["To"] = to_addr

        try:
            port = self._config.smtp_port
            timeout = self._config.smtp_timeout_seconds
            if port == 465:
                # Implicit TLS (SMTPS)
                ctx = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    self._config.smtp_host, port, context=ctx, timeout=timeout
                ) as smtp:
                    if self._config.smtp_user:
                        smtp.login(self._config.smtp_user, self._config.smtp_password)
                    smtp.sendmail(self._config.smtp_from, to_addr, msg.as_string())
            elif port == 587:
                # Explicit TLS (STARTTLS)
                ctx = ssl.create_default_context()
                with smtplib.SMTP(self._config.smtp_host, port, timeout=timeout) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ctx)
                    if self._config.smtp_user:
                        smtp.login(self._config.smtp_user, self._config.smtp_password)
                    smtp.sendmail(self._config.smtp_from, to_addr, msg.as_string())
            else:
                # Plain SMTP (typically port 25, local relay)
                with smtplib.SMTP(self._config.smtp_host, port, timeout=timeout) as smtp:
                    smtp.ehlo()
                    if self._config.smtp_user:
                        smtp.login(self._config.smtp_user, self._config.smtp_password)
                    smtp.sendmail(self._config.smtp_from, to_addr, msg.as_string())
            logger.info("Notification sent to %s: %s", to_addr, subject)
        except Exception:
            logger.warning("Failed to send notification to %s", to_addr, exc_info=True)


class JobTransitionDetector:
    """Detects job status transitions and emits notification events.

    Used by the UI polling loop to trigger in-browser toasts when a job
    transitions to a terminal state (completed / failed / cancelled).

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
