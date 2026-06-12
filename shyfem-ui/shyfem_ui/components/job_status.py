"""Job status display component."""

from datetime import datetime

from shiny import ui

from shyfem_ui.services.job_queue import JobInfo, JobStatus


def get_status_badge(status: JobStatus) -> ui.Tag:
    """Get a styled badge for job status."""
    badge_classes = {
        JobStatus.PENDING: "bg-secondary",
        JobStatus.QUEUED: "bg-info",
        JobStatus.RUNNING: "bg-primary",
        JobStatus.COMPLETED: "bg-success",
        JobStatus.FAILED: "bg-danger",
        JobStatus.CANCELLED: "bg-warning",
    }

    badge_class = badge_classes.get(status, "bg-secondary")
    return ui.span(status.value.upper(), class_=f"badge {badge_class}")


def format_duration(seconds: float | None) -> str:
    """Format duration in human-readable form."""
    if seconds is None:
        return "-"

    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def format_datetime(dt: datetime | None) -> str:
    """Format datetime for display."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def job_list_table(jobs: list[JobInfo]) -> ui.Tag:
    """Create a table displaying multiple jobs."""
    if not jobs:
        return ui.p("No jobs found", class_="text-muted text-center")

    rows = []
    for job in jobs:
        rows.append(
            ui.tags.tr(
                ui.tags.td(job.name),
                ui.tags.td(ui.code(job.tool_name)),
                ui.tags.td(get_status_badge(job.status)),
                ui.tags.td(f"{int(job.progress * 100)}%"),
                ui.tags.td(format_datetime(job.created_at)),
                ui.tags.td(format_duration(job.duration)),
            )
        )

    return ui.tags.table(
        ui.tags.thead(
            ui.tags.tr(
                ui.tags.th("Name"),
                ui.tags.th("Tool"),
                ui.tags.th("Status"),
                ui.tags.th("Progress"),
                ui.tags.th("Created"),
                ui.tags.th("Duration"),
            )
        ),
        ui.tags.tbody(*rows),
        class_="table table-striped table-hover",
    )
