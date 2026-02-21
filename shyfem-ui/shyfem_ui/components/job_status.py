"""Job status display component."""

from datetime import datetime

from shiny import module, reactive, render, ui

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


@module.ui
def job_status_ui():
    """Job status component UI."""
    return ui.div(
        ui.output_ui("job_card"),
        class_="job-status-component",
    )


@module.server
def job_status_server(
    input,
    output,
    session,
    job_info: reactive.Value[JobInfo | None],
):
    """Job status component server logic.

    Args:
        job_info: Reactive value containing current job info
    """

    @render.ui
    def job_card():
        job = job_info.get()
        if job is None:
            return ui.div(
                ui.p("No job selected", class_="text-muted text-center"),
                class_="card-body",
            )

        # Progress bar
        progress_pct = int(job.progress * 100)
        progress_bar = ui.div(
            ui.div(
                class_="progress-bar",
                style=f"width: {progress_pct}%",
                role="progressbar",
                **{
                    "aria-valuenow": str(progress_pct),
                    "aria-valuemin": "0",
                    "aria-valuemax": "100",
                },
            ),
            class_="progress mb-2",
        )

        # Status details
        details = [
            ("Status", get_status_badge(job.status)),
            ("Tool", ui.code(job.tool_name)),
            ("Progress", f"{progress_pct}%"),
            ("Created", format_datetime(job.created_at)),
        ]

        if job.started_at:
            details.append(("Started", format_datetime(job.started_at)))

        if job.completed_at:
            details.append(("Completed", format_datetime(job.completed_at)))
            details.append(("Duration", format_duration(job.duration)))

        if job.return_code is not None:
            details.append(("Return Code", str(job.return_code)))

        detail_rows = [
            ui.div(
                ui.span(label + ":", class_="fw-bold me-2"),
                value if isinstance(value, ui.Tag) else ui.span(str(value)),
                class_="d-flex justify-content-between mb-1",
            )
            for label, value in details
        ]

        # Error message if failed
        error_section = None
        if job.status == JobStatus.FAILED and job.error_message:
            error_section = ui.div(
                ui.strong("Error:"),
                ui.pre(job.error_message, class_="text-danger small mt-1"),
                class_="mt-2",
            )

        # Output files
        files_section = None
        if job.output_files:
            file_items = [ui.li(ui.code(f), class_="small") for f in job.output_files]
            files_section = ui.div(
                ui.strong("Output Files:"),
                ui.ul(*file_items, class_="mb-0"),
                class_="mt-2",
            )

        return ui.div(
            ui.div(
                ui.h6(job.name, class_="card-title"),
                progress_bar if job.is_active else None,
                (
                    ui.div(job.progress_message, class_="small text-muted mb-2")
                    if job.progress_message
                    else None
                ),
                *detail_rows,
                error_section,
                files_section,
                class_="card-body",
            ),
            class_="card",
        )


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
