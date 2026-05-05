"""HTML report generator for SHYFEM simulation results.

Generates self-contained HTML reports with:
- Simulation parameters summary
- Grid information and statistics
- Runtime statistics (duration, resource usage)
- Embedded Plotly result plots
- Output file inventory

Reports are standalone HTML files with inline CSS and JS (no external deps).
"""

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from shyfem_ui.config import Config, get_config


class ReportBuilder:
    """Builds HTML reports for SHYFEM simulation results.

    Usage:
        builder = ReportBuilder(title="My Simulation")
        builder.add_parameters(str_file)
        builder.add_grid_info(grd_stats)
        builder.add_job_info(job_info)
        builder.add_plotly_figure(fig, "Time Series")
        html = builder.render()
        builder.save("/path/to/report.html")
    """

    def __init__(self, title: str = "SHYFEM Simulation Report", config: Config | None = None):
        self.title = title
        self.config = config or get_config()
        self.sections: list[dict[str, Any]] = []
        self._created_at = datetime.now()

    def add_section(self, title: str, content_html: str, icon: str = "") -> None:
        """Add a raw HTML section to the report."""
        self.sections.append(
            {
                "title": title,
                "html": content_html,
                "icon": icon,
            }
        )

    def add_parameters(self, str_file, section_filter: list[str] | None = None) -> None:
        """Add simulation parameters from a parsed StrFile.

        Args:
            str_file: Parsed StrFile object
            section_filter: Optional list of section names to include.
                If None, includes all sections.
        """
        rows = []
        for sec_name in str_file.get_section_names():
            if section_filter and sec_name not in section_filter:
                continue
            section = str_file.sections[sec_name]
            if not section.parameters:
                continue
            for key, value in sorted(section.parameters.items()):
                rows.append(
                    f"<tr><td><code>${sec_name}</code></td>"
                    f"<td><strong>{_esc(key)}</strong></td>"
                    f"<td>{_esc(str(value))}</td></tr>"
                )

        if not rows:
            self.add_section("Simulation Parameters", "<p>No parameters found.</p>")
            return

        table = (
            '<table class="report-table">'
            "<thead><tr><th>Section</th><th>Parameter</th><th>Value</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        self.add_section("Simulation Parameters", table)

    def add_grid_info(self, stats: dict) -> None:
        """Add grid statistics from GrdParser.get_statistics().

        Args:
            stats: Dict from GrdParser.get_statistics()
        """
        items = [
            ("Nodes", stats.get("num_nodes", "?")),
            ("Elements", stats.get("num_elements", "?")),
            ("Triangles", stats.get("num_triangles", "?")),
            ("Quads", stats.get("num_quads", "?")),
            ("Boundary Lines", stats.get("num_lines", "?")),
            ("Coordinate System", stats.get("coordinate_system", "unknown")),
        ]

        bounds = stats.get("bounds")
        if bounds:
            items.append(
                ("X Range", f"{bounds.get('x_min', '?'):.6g} to {bounds.get('x_max', '?'):.6g}")
            )
            items.append(
                ("Y Range", f"{bounds.get('y_min', '?'):.6g} to {bounds.get('y_max', '?'):.6g}")
            )

        depth = stats.get("depth_range")
        if depth and depth.get("min") is not None:
            items.append(("Depth Range", f"{depth['min']:.2f} to {depth['max']:.2f}"))
            items.append(("Mean Depth", f"{depth.get('mean', 0):.2f}"))

        rows = "".join(
            f"<tr><td><strong>{_esc(str(k))}</strong></td><td>{_esc(str(v))}</td></tr>"
            for k, v in items
        )
        table = (
            '<table class="report-table">'
            "<thead><tr><th>Property</th><th>Value</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
        self.add_section("Grid Information", table)

    def add_job_info(self, job_info) -> None:
        """Add runtime statistics from a JobInfo object.

        Args:
            job_info: JobInfo dataclass instance
        """
        items = [
            ("Job ID", job_info.id),
            ("Tool", job_info.tool_name),
            ("Status", job_info.status.value),
            ("Arguments", " ".join(job_info.args) if job_info.args else "none"),
            ("Working Dir", job_info.working_dir),
        ]

        if job_info.created_at:
            items.append(("Created", job_info.created_at.strftime("%Y-%m-%d %H:%M:%S")))
        if job_info.started_at:
            items.append(("Started", job_info.started_at.strftime("%Y-%m-%d %H:%M:%S")))
        if job_info.completed_at:
            items.append(("Completed", job_info.completed_at.strftime("%Y-%m-%d %H:%M:%S")))

        duration = job_info.duration
        if duration is not None:
            items.append(("Duration", _format_duration(duration)))

        if job_info.return_code is not None:
            items.append(("Return Code", str(job_info.return_code)))
        if job_info.error_message:
            items.append(("Error", job_info.error_message[:500]))

        mpi_np = job_info.metadata.get("mpi_np")
        if mpi_np and mpi_np > 1:
            items.append(("MPI Processes", str(mpi_np)))

        rows = "".join(
            f"<tr><td><strong>{_esc(str(k))}</strong></td><td>{_esc(str(v))}</td></tr>"
            for k, v in items
        )
        table = (
            '<table class="report-table">'
            "<thead><tr><th>Property</th><th>Value</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )

        status_class = {
            "completed": "badge-success",
            "failed": "badge-danger",
            "running": "badge-primary",
            "cancelled": "badge-warning",
        }.get(job_info.status.value, "badge-secondary")

        header = f'<span class="badge {status_class}">{_esc(job_info.status.value.upper())}</span>'
        self.add_section("Runtime Statistics", header + table)

    def add_output_files(self, files: list[str], working_dir: str | None = None) -> None:
        """Add output file inventory.

        Args:
            files: List of output file paths
            working_dir: Working directory for computing relative paths
        """
        if not files:
            self.add_section("Output Files", "<p>No output files.</p>")
            return

        rows = []
        for fp in files:
            path = Path(fp)
            suffix = path.suffix.lower()

            # File type badge
            type_map = {
                ".shy": ("SHYFEM", "badge-primary"),
                ".nc": ("NetCDF", "badge-success"),
                ".grd": ("Grid", "badge-info"),
                ".bas": ("Basin", "badge-info"),
                ".ext": ("Extract", "badge-warning"),
                ".ts": ("TimeSeries", "badge-warning"),
                ".flx": ("Flux", "badge-warning"),
                ".par": ("Partition", "badge-secondary"),
                ".txt": ("Text", "badge-secondary"),
                ".dat": ("Data", "badge-secondary"),
            }
            label, badge_cls = type_map.get(suffix, ("File", "badge-secondary"))

            # File size
            try:
                size = path.stat().st_size
                size_str = _format_size(size)
            except OSError:
                size_str = "?"

            rel = path.name
            if working_dir:
                try:
                    rel = str(path.relative_to(working_dir))
                except ValueError:
                    rel = str(path)

            rows.append(
                f"<tr><td><code>{_esc(rel)}</code></td>"
                f'<td><span class="badge {badge_cls}">{label}</span></td>'
                f"<td>{size_str}</td></tr>"
            )

        table = (
            '<table class="report-table">'
            "<thead><tr><th>File</th><th>Type</th><th>Size</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        self.add_section("Output Files", table)

    def add_plotly_figure(self, fig, title: str = "Plot") -> None:
        """Add an embedded Plotly figure.

        Args:
            fig: plotly.graph_objects.Figure instance
            title: Caption for the plot
        """
        fig_json = fig.to_json()
        div_id = f"plot-{len(self.sections)}-{id(fig) % 10000}"

        plot_html = (
            f'<div id="{div_id}" class="plotly-chart"></div>'
            f"<script>Plotly.newPlot('{div_id}', "
            f"{fig_json}"
            f", {{responsive: true}});</script>"
        )
        self.add_section(title, plot_html)

    def add_statistics_table(
        self,
        data: dict[str, dict[str, float]],
        title: str = "Variable Statistics",
    ) -> None:
        """Add a statistics summary table.

        Args:
            data: Dict mapping variable names to stats dicts
                  (each with keys like min, max, mean, std, count)
            title: Section title
        """
        if not data:
            self.add_section(title, "<p>No statistics available.</p>")
            return

        stat_keys = ["min", "max", "mean", "std", "range", "count"]
        header_cells = "<th>Variable</th>" + "".join(f"<th>{k.title()}</th>" for k in stat_keys)

        rows = []
        for var_name, stats in data.items():
            cells = f"<td><strong>{_esc(var_name)}</strong></td>"
            for k in stat_keys:
                val = stats.get(k)
                if val is None:
                    cells += "<td>-</td>"
                elif k == "count":
                    cells += f"<td>{int(val)}</td>"
                else:
                    cells += f"<td>{val:.4g}</td>"
            rows.append(f"<tr>{cells}</tr>")

        table = (
            '<table class="report-table">'
            f"<thead><tr>{header_cells}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        self.add_section(title, table)

    def add_text(self, title: str, text: str, preformatted: bool = False) -> None:
        """Add a text section.

        Args:
            title: Section title
            text: Content text
            preformatted: If True, render as <pre> block
        """
        if preformatted:
            content = f"<pre>{_esc(text)}</pre>"
        else:
            content = f"<p>{_esc(text)}</p>"
        self.add_section(title, content)

    def render(self) -> str:
        """Render the complete HTML report."""
        sections_html = []
        for i, sec in enumerate(self.sections):
            sections_html.append(
                f'<div class="section" id="section-{i}">'
                f"<h2>{sec.get('icon', '')} {_esc(sec['title'])}</h2>"
                f"<div class=\"section-body\">{sec['html']}</div>"
                f"</div>"
            )

        # Table of contents
        toc_items = "".join(
            f'<li><a href="#section-{i}">{_esc(sec["title"])}</a></li>'
            for i, sec in enumerate(self.sections)
        )

        # Plotly JS loader — cdn (default) or inline bundle for air-gapped use
        if self.config.report_plotly_mode == "inline":
            # Inline the full Plotly JS bundle — same path that
            # fig.to_html(include_plotlyjs=True) uses internally.
            try:
                from plotly.offline.offline import get_plotlyjs

                plotly_loader = f"<script>{get_plotlyjs()}</script>"
            except ImportError:
                # Fall back gracefully if plotly's internal layout changes.
                plotly_loader = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'
        else:
            plotly_loader = '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>'

        return _REPORT_TEMPLATE.format(
            title=_esc(self.title),
            created_at=self._created_at.strftime("%Y-%m-%d %H:%M:%S"),
            toc=toc_items,
            sections="\n".join(sections_html),
            plotly_loader=plotly_loader,
        )

    def save(self, path: str | Path) -> Path:
        """Render and save the report to a file.

        Args:
            path: Output file path

        Returns:
            Path to saved file
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(), encoding="utf-8")
        return path


def generate_job_report(
    job_info,
    str_file=None,
    grd_stats: dict | None = None,
    figures: list[tuple[Any, str]] | None = None,
    variable_stats: dict[str, dict[str, float]] | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    """Generate a complete simulation report.

    Convenience function that builds a full report from available data.

    Args:
        job_info: JobInfo object with runtime data
        str_file: Optional parsed StrFile for parameters
        grd_stats: Optional grid statistics dict
        figures: Optional list of (plotly_figure, title) tuples
        variable_stats: Optional dict of variable statistics
        output_dir: Directory to save the report. Defaults to job working dir.

    Returns:
        Path to the generated HTML file
    """
    title = f"SHYFEM Report: {job_info.name}"
    builder = ReportBuilder(title=title)

    # Parameters
    if str_file:
        builder.add_parameters(str_file)

    # Grid info
    if grd_stats:
        builder.add_grid_info(grd_stats)

    # Runtime
    builder.add_job_info(job_info)

    # Output files
    if job_info.output_files:
        builder.add_output_files(job_info.output_files, job_info.working_dir)

    # Variable statistics
    if variable_stats:
        builder.add_statistics_table(variable_stats)

    # Plotly figures
    if figures:
        for fig, fig_title in figures:
            builder.add_plotly_figure(fig, fig_title)

    # Save
    if output_dir is None:
        output_dir = job_info.working_dir
    out_path = Path(output_dir) / f"report_{job_info.id[:8]}.html"
    return builder.save(out_path)


def generate_comparison_report(
    jobs: list,
    title: str = "Simulation Comparison",
    figures: list[tuple[Any, str]] | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Generate a comparison report for multiple jobs.

    Args:
        jobs: List of JobInfo objects to compare
        title: Report title
        figures: Optional list of (plotly_figure, title) tuples
        output_path: Output file path

    Returns:
        Path to the generated HTML file
    """
    builder = ReportBuilder(title=title)

    if not jobs:
        builder.add_text("No Data", "No jobs provided for comparison.")
        out = output_path or "comparison_report.html"
        return builder.save(out)

    # Summary table
    header = "<th>Job</th><th>Tool</th><th>Status</th>" "<th>Duration</th><th>Return Code</th>"
    rows = []
    for job in jobs:
        duration = _format_duration(job.duration) if job.duration else "-"
        status_cls = {
            "completed": "badge-success",
            "failed": "badge-danger",
        }.get(job.status.value, "badge-secondary")

        rows.append(
            f"<tr>"
            f"<td><strong>{_esc(job.name)}</strong></td>"
            f"<td>{_esc(job.tool_name)}</td>"
            f'<td><span class="badge {status_cls}">{_esc(job.status.value)}</span></td>'
            f"<td>{duration}</td>"
            f"<td>{job.return_code if job.return_code is not None else '-'}</td>"
            f"</tr>"
        )

    table = (
        '<table class="report-table">'
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    builder.add_section("Job Summary", table)

    # Figures
    if figures:
        for fig, fig_title in figures:
            builder.add_plotly_figure(fig, fig_title)

    out = output_path or "comparison_report.html"
    return builder.save(out)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(s), quote=True)


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = seconds % 60
        return f"{m}m {s:.0f}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable units."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{plotly_loader}
<style>
  :root {{
    --bg: #ffffff;
    --text: #212529;
    --border: #dee2e6;
    --primary: #0d6efd;
    --success: #198754;
    --danger: #dc3545;
    --warning: #ffc107;
    --info: #0dcaf0;
    --secondary: #6c757d;
    --card-bg: #f8f9fa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    color: var(--text);
    background: var(--bg);
    line-height: 1.5;
    padding: 0;
  }}
  .header {{
    background: linear-gradient(135deg, #1a237e, #0d47a1);
    color: white;
    padding: 2rem;
  }}
  .header h1 {{ font-size: 1.5rem; font-weight: 600; }}
  .header .meta {{ opacity: 0.8; font-size: 0.85rem; margin-top: 0.25rem; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 1rem 2rem 3rem; }}
  .toc {{
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 1rem 1.5rem;
    margin: 1.5rem 0;
  }}
  .toc h3 {{ font-size: 0.9rem; text-transform: uppercase; color: var(--secondary); margin-bottom: 0.5rem; }}
  .toc ul {{ list-style: none; padding: 0; display: flex; flex-wrap: wrap; gap: 0.5rem 1.5rem; }}
  .toc a {{ color: var(--primary); text-decoration: none; font-size: 0.9rem; }}
  .toc a:hover {{ text-decoration: underline; }}
  .section {{
    margin-top: 2rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }}
  .section h2 {{
    font-size: 1.1rem;
    padding: 0.75rem 1rem;
    background: var(--card-bg);
    border-bottom: 1px solid var(--border);
    margin: 0;
  }}
  .section-body {{ padding: 1rem; }}
  .report-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }}
  .report-table th {{
    text-align: left;
    background: var(--card-bg);
    padding: 0.5rem 0.75rem;
    border-bottom: 2px solid var(--border);
    font-weight: 600;
  }}
  .report-table td {{
    padding: 0.4rem 0.75rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .report-table tr:last-child td {{ border-bottom: none; }}
  .report-table code {{
    background: #e9ecef;
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
    font-size: 0.85em;
  }}
  .badge {{
    display: inline-block;
    padding: 0.2em 0.6em;
    font-size: 0.75rem;
    font-weight: 600;
    border-radius: 4px;
    color: white;
  }}
  .badge-success {{ background: var(--success); }}
  .badge-danger {{ background: var(--danger); }}
  .badge-warning {{ background: var(--warning); color: #212529; }}
  .badge-primary {{ background: var(--primary); }}
  .badge-info {{ background: var(--info); color: #212529; }}
  .badge-secondary {{ background: var(--secondary); }}
  .plotly-chart {{ width: 100%; min-height: 400px; }}
  pre {{
    background: #f8f9fa;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.75rem;
    overflow-x: auto;
    font-size: 0.85rem;
    white-space: pre-wrap;
  }}
  .footer {{
    text-align: center;
    padding: 1rem;
    color: var(--secondary);
    font-size: 0.8rem;
    border-top: 1px solid var(--border);
    margin-top: 2rem;
  }}
  @media print {{
    .header {{ background: #333; -webkit-print-color-adjust: exact; }}
    .section {{ break-inside: avoid; }}
    .plotly-chart {{ min-height: 300px; }}
  }}
</style>
</head>
<body>
<div class="header">
  <h1>{title}</h1>
  <div class="meta">Generated: {created_at} | SHYFEM-UI Report</div>
</div>
<div class="container">
  <nav class="toc">
    <h3>Contents</h3>
    <ul>{toc}</ul>
  </nav>
  {sections}
</div>
<div class="footer">
  Generated by SHYFEM-UI &mdash; System of HydroDYnamic Finite Element Modules
</div>
</body>
</html>"""
