"""J-09: a job reloaded from the database shows its creation time in local time.

``jobs.created_at`` is filled by ``server_default=func.now()`` (SQLite
``CURRENT_TIMESTAMP``: UTC), while every other job time (queued, started,
completed) and a job created in this process are naive local. A reloaded
job therefore showed "Created" hours before "Started" (−3 h at Klaipėda in
summer), and the elapsed time of a reloaded pending job was off by as much.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.job_queue import JobStatus


@pytest.fixture()
def vilnius_tz():
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Vilnius"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _row(created_utc: datetime, started_local: datetime):
    return SimpleNamespace(
        job_uuid="j1",
        name="run",
        job_type="shyfem",
        working_dir="/tmp",
        status=JobStatus.COMPLETED,
        progress=1.0,
        progress_message="",
        created_at=created_utc,
        queued_at=started_local,
        started_at=started_local,
        completed_at=started_local + timedelta(minutes=5),
        return_code=0,
        error_message=None,
        stdout_file=None,
        stderr_file=None,
        output_files=[],
        simulation_id=None,
        session_id=None,
        user_id=1,
        project_id=2,
    )


def test_reloaded_created_at_is_local(vilnius_tz):
    # 2026-07-15 09:00 UTC == 12:00 in Vilnius (EEST, UTC+3)
    created_utc = datetime(2026, 7, 15, 9, 0, 0)
    started_local = datetime(2026, 7, 15, 12, 0, 1)
    info = LocalJobQueue._db_row_to_job_info(_row(created_utc, started_local))
    assert info.created_at == datetime(2026, 7, 15, 12, 0, 0)
    assert info.created_at.tzinfo is None
    assert info.created_at <= info.started_at


def test_winter_offset_and_none(vilnius_tz):
    info = LocalJobQueue._db_row_to_job_info(
        _row(datetime(2026, 1, 15, 9, 0), datetime(2026, 1, 15, 11, 0, 1))
    )
    assert info.created_at == datetime(2026, 1, 15, 11, 0)  # EET, UTC+2
    row = _row(datetime(2026, 1, 15, 9, 0), datetime(2026, 1, 15, 11, 0, 1))
    row.created_at = None
    info = LocalJobQueue._db_row_to_job_info(row)
    assert info.created_at is None


def test_utc_server_unchanged():
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        created = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        info = LocalJobQueue._db_row_to_job_info(_row(created, created))
        assert info.created_at == created
    finally:
        os.environ.pop("TZ", None)
        time.tzset()
