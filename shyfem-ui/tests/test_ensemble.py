"""Tests for ensemble page."""

from datetime import datetime, timedelta


def test_duration_chart_uses_ocean_colors():
    """Duration bar chart must use ocean theme colors, not Bootstrap defaults.

    Calls _build_duration_chart() directly with one completed and one failed
    job, then asserts the actual marker colors in the returned Plotly figure.
    """
    from shyfem_ui.pages.ensemble import _build_duration_chart
    from shyfem_ui.services.job_queue import JobInfo, JobStatus

    now = datetime.now()
    completed = JobInfo(
        id="1",
        name="run-ok",
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=JobStatus.COMPLETED,
        started_at=now,
        completed_at=now + timedelta(seconds=10),
    )
    failed = JobInfo(
        id="2",
        name="run-fail",
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=JobStatus.FAILED,
        started_at=now,
        completed_at=now + timedelta(seconds=5),
    )

    fig = _build_duration_chart([completed, failed])
    colors = list(fig.data[0].marker.color)

    assert "#198754" not in colors, "Bootstrap green must not be used — use ocean teal #3DB8A0"
    assert "#dc3545" not in colors, "Bootstrap red must not be used — use ocean coral #E8725A"
    assert "#3DB8A0" in colors, "Completed jobs must use ocean teal (#3DB8A0)"
    assert "#E8725A" in colors, "Failed jobs must use ocean coral (#E8725A)"
