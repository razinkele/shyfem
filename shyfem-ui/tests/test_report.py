"""Tests for HTML report generator."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from shyfem_ui.services.job_queue import JobInfo, JobStatus
from shyfem_ui.services.report import (
    ReportBuilder,
    generate_comparison_report,
    generate_job_report,
    _esc,
    _format_duration,
    _format_size,
)


class TestReportBuilder:
    """Tests for ReportBuilder class."""

    def test_render_empty_report(self):
        """Test rendering a report with no sections."""
        builder = ReportBuilder(title="Test Report")
        html = builder.render()

        assert "<!DOCTYPE html>" in html
        assert "Test Report" in html
        assert "SHYFEM-UI Report" in html

    def test_add_section(self):
        """Test adding a raw HTML section."""
        builder = ReportBuilder()
        builder.add_section("My Section", "<p>Content</p>")
        html = builder.render()

        assert "My Section" in html
        assert "<p>Content</p>" in html

    def test_add_text_plain(self):
        """Test adding plain text section."""
        builder = ReportBuilder()
        builder.add_text("Notes", "This is a note.")
        html = builder.render()

        assert "Notes" in html
        assert "This is a note." in html

    def test_add_text_preformatted(self):
        """Test adding preformatted text section."""
        builder = ReportBuilder()
        builder.add_text("Log", "line1\nline2", preformatted=True)
        html = builder.render()

        assert "<pre>" in html
        assert "line1" in html

    def test_add_parameters(self):
        """Test adding parameters from mock StrFile."""
        mock_str = MagicMock()
        mock_str.get_section_names.return_value = ["para"]
        mock_section = MagicMock()
        mock_section.parameters = {"idt": 300, "ilin": 1}
        mock_str.sections = {"para": mock_section}

        builder = ReportBuilder()
        builder.add_parameters(mock_str)
        html = builder.render()

        assert "Simulation Parameters" in html
        assert "idt" in html
        assert "300" in html

    def test_add_parameters_with_filter(self):
        """Test adding parameters with section filter."""
        mock_str = MagicMock()
        mock_str.get_section_names.return_value = ["para", "name"]
        mock_para = MagicMock()
        mock_para.parameters = {"idt": 300}
        mock_name = MagicMock()
        mock_name.parameters = {"wind": "test.txt"}
        mock_str.sections = {"para": mock_para, "name": mock_name}

        builder = ReportBuilder()
        builder.add_parameters(mock_str, section_filter=["para"])
        html = builder.render()

        assert "idt" in html
        assert "wind" not in html

    def test_add_parameters_empty(self):
        """Test adding parameters with no sections."""
        mock_str = MagicMock()
        mock_str.get_section_names.return_value = []
        mock_str.sections = {}

        builder = ReportBuilder()
        builder.add_parameters(mock_str)
        html = builder.render()
        assert "No parameters found" in html

    def test_add_grid_info(self):
        """Test adding grid statistics."""
        stats = {
            "num_nodes": 1000,
            "num_elements": 1800,
            "num_triangles": 1800,
            "num_quads": 0,
            "num_lines": 50,
            "coordinate_system": "geographic",
            "bounds": {"x_min": 12.0, "x_max": 13.0, "y_min": 45.0, "y_max": 46.0},
            "depth_range": {"min": 0.5, "max": 25.0, "mean": 8.5},
        }

        builder = ReportBuilder()
        builder.add_grid_info(stats)
        html = builder.render()

        assert "Grid Information" in html
        assert "1000" in html
        assert "1800" in html
        assert "geographic" in html

    def test_add_job_info(self):
        """Test adding runtime statistics from JobInfo."""
        job = JobInfo(
            id="abc-123",
            name="Test Job",
            tool_name="shyfem",
            args=["test.str"],
            working_dir="/tmp/work",
            status=JobStatus.COMPLETED,
            return_code=0,
            created_at=datetime(2024, 1, 1, 10, 0, 0),
            started_at=datetime(2024, 1, 1, 10, 0, 5),
            completed_at=datetime(2024, 1, 1, 10, 5, 5),
        )

        builder = ReportBuilder()
        builder.add_job_info(job)
        html = builder.render()

        assert "Runtime Statistics" in html
        assert "abc-123" in html
        assert "shyfem" in html
        assert "COMPLETED" in html

    def test_add_job_info_with_mpi(self):
        """Test adding job info with MPI metadata."""
        job = JobInfo(
            id="mpi-123",
            name="MPI Job",
            tool_name="shyfem",
            args=["test.str"],
            working_dir="/tmp",
            status=JobStatus.COMPLETED,
            metadata={"mpi_np": 8},
        )

        builder = ReportBuilder()
        builder.add_job_info(job)
        html = builder.render()
        assert "8" in html

    def test_add_job_info_failed(self):
        """Test adding failed job shows error."""
        job = JobInfo(
            id="fail-123",
            name="Failed Job",
            tool_name="shyfem",
            args=[],
            working_dir="/tmp",
            status=JobStatus.FAILED,
            error_message="Segmentation fault",
        )

        builder = ReportBuilder()
        builder.add_job_info(job)
        html = builder.render()
        assert "FAILED" in html
        assert "Segmentation fault" in html

    def test_add_output_files(self, tmp_path):
        """Test adding output file inventory."""
        # Create some files
        f1 = tmp_path / "out.shy"
        f1.write_text("x" * 100)
        f2 = tmp_path / "out.nc"
        f2.write_text("x" * 5000)

        builder = ReportBuilder()
        builder.add_output_files([str(f1), str(f2)], str(tmp_path))
        html = builder.render()

        assert "Output Files" in html
        assert "out.shy" in html
        assert "out.nc" in html
        assert "SHYFEM" in html
        assert "NetCDF" in html

    def test_add_output_files_empty(self):
        """Test adding empty output files list."""
        builder = ReportBuilder()
        builder.add_output_files([])
        html = builder.render()
        assert "No output files" in html

    def test_add_statistics_table(self):
        """Test adding variable statistics table."""
        stats = {
            "temperature": {"min": 15.0, "max": 25.0, "mean": 20.0,
                            "std": 2.5, "range": 10.0, "count": 1000},
            "salinity": {"min": 30.0, "max": 38.0, "mean": 35.0,
                         "std": 1.2, "range": 8.0, "count": 1000},
        }

        builder = ReportBuilder()
        builder.add_statistics_table(stats, "Variable Statistics")
        html = builder.render()

        assert "Variable Statistics" in html
        assert "temperature" in html
        assert "salinity" in html
        assert "20" in html

    def test_add_statistics_table_empty(self):
        """Test adding empty statistics table."""
        builder = ReportBuilder()
        builder.add_statistics_table({})
        html = builder.render()
        assert "No statistics available" in html

    def test_table_of_contents(self):
        """Test that table of contents is generated."""
        builder = ReportBuilder()
        builder.add_text("Section A", "Content A")
        builder.add_text("Section B", "Content B")
        html = builder.render()

        assert "Contents" in html
        assert "Section A" in html
        assert "Section B" in html
        assert 'href="#section-0"' in html
        assert 'href="#section-1"' in html

    def test_save(self, tmp_path):
        """Test saving report to file."""
        builder = ReportBuilder(title="Save Test")
        builder.add_text("Test", "Content")

        path = builder.save(tmp_path / "report.html")
        assert path.exists()
        content = path.read_text()
        assert "Save Test" in content

    def test_save_creates_directories(self, tmp_path):
        """Test save creates parent directories."""
        builder = ReportBuilder()
        path = builder.save(tmp_path / "subdir" / "report.html")
        assert path.exists()

    def test_html_escaping(self):
        """Test that HTML special chars are escaped."""
        builder = ReportBuilder(title="<script>alert('xss')</script>")
        html = builder.render()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_multiple_sections(self):
        """Test report with many sections."""
        builder = ReportBuilder()
        for i in range(10):
            builder.add_text(f"Section {i}", f"Content {i}")

        html = builder.render()
        assert html.count("section-") >= 10


class TestConvenienceFunctions:
    """Tests for generate_job_report and generate_comparison_report."""

    def test_generate_job_report(self, tmp_path):
        """Test generate_job_report creates HTML file."""
        job = JobInfo(
            id="rep-123",
            name="Report Job",
            tool_name="shyfem",
            args=["test.str"],
            working_dir=str(tmp_path),
            status=JobStatus.COMPLETED,
            output_files=[],
        )

        path = generate_job_report(job, output_dir=tmp_path)
        assert path.exists()
        assert path.suffix == ".html"

        content = path.read_text()
        assert "Report Job" in content

    def test_generate_job_report_with_all_data(self, tmp_path):
        """Test generate_job_report with all optional data."""
        job = JobInfo(
            id="full-123",
            name="Full Report",
            tool_name="shyfem",
            args=["test.str"],
            working_dir=str(tmp_path),
            status=JobStatus.COMPLETED,
        )

        mock_str = MagicMock()
        mock_str.get_section_names.return_value = ["para"]
        mock_section = MagicMock()
        mock_section.parameters = {"idt": 300}
        mock_str.sections = {"para": mock_section}

        stats = {"temperature": {"min": 10, "max": 20, "mean": 15,
                                  "std": 2, "range": 10, "count": 100}}
        grid_stats = {"num_nodes": 500, "num_elements": 800}

        path = generate_job_report(
            job, str_file=mock_str, grd_stats=grid_stats,
            variable_stats=stats, output_dir=tmp_path,
        )
        assert path.exists()
        content = path.read_text()
        assert "idt" in content
        assert "500" in content

    def test_generate_comparison_report(self, tmp_path):
        """Test generate_comparison_report creates HTML file."""
        jobs = [
            JobInfo(id="a", name="Job A", tool_name="shyfem", args=[],
                    working_dir="/tmp", status=JobStatus.COMPLETED,
                    return_code=0, started_at=datetime(2024, 1, 1),
                    completed_at=datetime(2024, 1, 1, 0, 5)),
            JobInfo(id="b", name="Job B", tool_name="shyfem", args=[],
                    working_dir="/tmp", status=JobStatus.FAILED,
                    return_code=1),
        ]

        path = generate_comparison_report(
            jobs, output_path=tmp_path / "compare.html",
        )
        assert path.exists()
        content = path.read_text()
        assert "Job A" in content
        assert "Job B" in content

    def test_generate_comparison_report_empty(self, tmp_path):
        """Test comparison report with no jobs."""
        path = generate_comparison_report(
            [], output_path=tmp_path / "empty.html",
        )
        assert path.exists()
        content = path.read_text()
        assert "No jobs provided" in content


class TestReportPlotlyMode:
    """Tests for configurable Plotly JS embedding mode."""

    def test_inline_mode_bundles_js(self, tmp_path):
        """Inline mode embeds the full Plotly bundle; no CDN <script> tag."""
        import plotly.graph_objects as go

        cfg = MagicMock(report_plotly_mode="inline")
        rb = ReportBuilder(title="Test", config=cfg)
        rb.add_plotly_figure(go.Figure())
        html_out = rb.render()

        # Inline mode must NOT emit a CDN <script src="..."> tag.
        # (The bundle itself contains the string "cdn.plot.ly" for TopoJSON
        # data URLs — that's expected and unavoidable.)
        assert 'src="https://cdn.plot.ly/plotly-' not in html_out
        # Plotly's bundle is large; CDN reference is ~80 chars
        assert len(html_out) > 500_000, (
            f"inline html should be >500KB, got {len(html_out)}"
        )
        # The bundle exposes a global Plotly identifier
        assert "Plotly" in html_out

    def test_cdn_mode_uses_cdn(self, tmp_path):
        """CDN mode emits a CDN script tag (default behaviour)."""
        import plotly.graph_objects as go

        cfg = MagicMock(report_plotly_mode="cdn")
        rb = ReportBuilder(title="Test", config=cfg)
        rb.add_plotly_figure(go.Figure())
        html_out = rb.render()

        assert "cdn.plot.ly/plotly-2.35.2.min.js" in html_out


class TestHelpers:
    """Tests for helper functions."""

    def test_esc(self):
        """Test HTML escaping."""
        assert _esc("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"
        assert _esc('"quotes"') == "&quot;quotes&quot;"
        assert _esc("normal") == "normal"

    def test_format_duration_seconds(self):
        """Test duration formatting for seconds."""
        assert _format_duration(30.5) == "30.5s"

    def test_format_duration_minutes(self):
        """Test duration formatting for minutes."""
        result = _format_duration(125.0)
        assert "2m" in result

    def test_format_duration_hours(self):
        """Test duration formatting for hours."""
        result = _format_duration(7200.0)
        assert "2h" in result

    def test_format_size_bytes(self):
        """Test file size formatting."""
        assert _format_size(100) == "100 B"

    def test_format_size_kb(self):
        """Test file size in KB."""
        result = _format_size(2048)
        assert "KB" in result

    def test_format_size_mb(self):
        """Test file size in MB."""
        result = _format_size(5 * 1024 * 1024)
        assert "MB" in result
