"""Tests for job_status component pure functions."""

from datetime import datetime

import pytest

from shyfem_ui.components.job_status import (
    format_datetime,
    format_duration,
    get_status_badge,
    job_list_table,
)
from shyfem_ui.services.job_queue import JobInfo, JobStatus


# ── format_duration ──────────────────────────────────────────────


def test_format_duration_none():
    assert format_duration(None) == "-"


def test_format_duration_zero():
    assert format_duration(0) == "0.0s"


def test_format_duration_seconds():
    assert format_duration(30) == "30.0s"


def test_format_duration_minutes():
    assert format_duration(90) == "1m 30s"


def test_format_duration_hours():
    assert format_duration(3661) == "1h 1m"


def test_format_duration_fractional():
    assert format_duration(5.7) == "5.7s"


# ── format_datetime ──────────────────────────────────────────────


def test_format_datetime_none():
    assert format_datetime(None) == "-"


def test_format_datetime_value():
    dt = datetime(2026, 2, 14, 10, 30, 45)
    assert format_datetime(dt) == "2026-02-14 10:30:45"


# ── get_status_badge ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,expected_class",
    [
        (JobStatus.PENDING, "bg-secondary"),
        (JobStatus.QUEUED, "bg-info"),
        (JobStatus.RUNNING, "bg-primary"),
        (JobStatus.COMPLETED, "bg-success"),
        (JobStatus.FAILED, "bg-danger"),
        (JobStatus.CANCELLED, "bg-warning"),
    ],
)
def test_get_status_badge(status, expected_class):
    badge = get_status_badge(status)
    rendered = str(badge)
    assert expected_class in rendered
    assert status.value.upper() in rendered


# ── job_list_table ───────────────────────────────────────────────


def _make_job(name="test", status=JobStatus.COMPLETED, progress=1.0):
    return JobInfo(
        id="job-1",
        name=name,
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=status,
        progress=progress,
        created_at=datetime(2026, 2, 14, 12, 0, 0),
    )


def test_job_list_table_empty():
    result = str(job_list_table([]))
    assert "No jobs found" in result


def test_job_list_table_single():
    table = str(job_list_table([_make_job(name="Run 1")]))
    assert "Run 1" in table
    assert "shyfem" in table


def test_job_list_table_multiple():
    jobs = [_make_job(name="A"), _make_job(name="B")]
    table = str(job_list_table(jobs))
    assert "A" in table
    assert "B" in table
