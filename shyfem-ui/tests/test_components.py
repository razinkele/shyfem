"""Unit tests for pure helper functions in shyfem_ui/components/."""

from datetime import datetime

import pytest
from shiny import ui

from shyfem_ui.components.job_status import (
    format_datetime,
    format_duration,
    get_status_badge,
    job_list_table,
)
from shyfem_ui.services.job_queue import JobInfo, JobStatus
from shyfem_ui.services.parser_grd import Element, GrdFile, Node

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> JobInfo:
    """Create a JobInfo with sensible defaults."""
    defaults = dict(
        id="job-001",
        name="Test Job",
        tool_name="shyfem",
        args=["-f", "sim.str"],
        working_dir="/tmp/sim",
        status=JobStatus.COMPLETED,
        progress=1.0,
        created_at=datetime(2025, 1, 15, 10, 0, 0),
        started_at=datetime(2025, 1, 15, 10, 0, 5),
        completed_at=datetime(2025, 1, 15, 10, 5, 5),
    )
    defaults.update(overrides)
    return JobInfo(**defaults)


def _make_triangle_grid() -> GrdFile:
    """Build a minimal GrdFile with one triangle element."""
    grd = GrdFile()
    grd.nodes = {
        1: Node(id=1, node_type=0, x=0.0, y=0.0, depth=1.0),
        2: Node(id=2, node_type=0, x=1.0, y=0.0, depth=2.0),
        3: Node(id=3, node_type=0, x=0.5, y=1.0, depth=3.0),
    }
    grd.elements = {
        1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),
    }
    return grd


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_none(self):
        assert format_duration(None) == "-"

    def test_seconds(self):
        assert format_duration(42.123) == "42.1s"

    def test_zero(self):
        assert format_duration(0.0) == "0.0s"

    def test_minutes(self):
        assert format_duration(125) == "2m 5s"

    def test_exactly_one_minute(self):
        assert format_duration(60) == "1m 0s"

    def test_hours(self):
        assert format_duration(7265) == "2h 1m"

    def test_large_value(self):
        assert format_duration(36000) == "10h 0m"


# ---------------------------------------------------------------------------
# format_datetime
# ---------------------------------------------------------------------------

class TestFormatDatetime:
    def test_none(self):
        assert format_datetime(None) == "-"

    def test_typical(self):
        dt = datetime(2025, 3, 15, 8, 30, 45)
        assert format_datetime(dt) == "2025-03-15 08:30:45"

    def test_midnight(self):
        dt = datetime(2025, 1, 1, 0, 0, 0)
        assert format_datetime(dt) == "2025-01-01 00:00:00"


# ---------------------------------------------------------------------------
# get_status_badge
# ---------------------------------------------------------------------------

class TestGetStatusBadge:
    @pytest.mark.parametrize(
        "status, expected_class",
        [
            (JobStatus.PENDING, "bg-secondary"),
            (JobStatus.QUEUED, "bg-info"),
            (JobStatus.RUNNING, "bg-primary"),
            (JobStatus.COMPLETED, "bg-success"),
            (JobStatus.FAILED, "bg-danger"),
            (JobStatus.CANCELLED, "bg-warning"),
        ],
    )
    def test_badge_class(self, status, expected_class):
        badge = get_status_badge(status)
        # The returned tag should be a span with the correct class
        assert isinstance(badge, ui.Tag)
        rendered = str(badge)
        assert expected_class in rendered
        assert status.value.upper() in rendered


# ---------------------------------------------------------------------------
# job_list_table
# ---------------------------------------------------------------------------

class TestJobListTable:
    def test_empty_list(self):
        result = job_list_table([])
        rendered = str(result)
        assert "No jobs found" in rendered

    def test_single_job(self):
        job = _make_job()
        result = job_list_table([job])
        rendered = str(result)
        assert "Test Job" in rendered
        assert "shyfem" in rendered
        assert "100%" in rendered

    def test_multiple_jobs(self):
        jobs = [
            _make_job(id="j1", name="Job A", status=JobStatus.COMPLETED),
            _make_job(id="j2", name="Job B", status=JobStatus.FAILED),
        ]
        result = job_list_table(jobs)
        rendered = str(result)
        assert "Job A" in rendered
        assert "Job B" in rendered
        assert "table" in rendered


# ---------------------------------------------------------------------------
# _build_edge_arrays  &  build_mesh_figure
# ---------------------------------------------------------------------------

class TestBuildEdgeArrays:
    def test_single_triangle(self):
        from shyfem_ui.components.grid_map import _build_edge_arrays

        grd = _make_triangle_grid()
        edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)

        # 3 edges × 3 values (start, end, None) = 9
        assert len(edge_x) == 9
        assert len(edge_y) == 9

        # Every 3rd value is None (edge separator)
        for idx in (2, 5, 8):
            assert edge_x[idx] is None
            assert edge_y[idx] is None

        assert len(node_ids) == 3
        assert set(node_ids) == {1, 2, 3}
        assert len(node_map) == 3

    def test_empty_grid(self):
        from shyfem_ui.components.grid_map import _build_edge_arrays

        grd = GrdFile()
        edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)
        assert edge_x == []
        assert edge_y == []
        assert len(node_ids) == 0


class TestBuildMeshFigure:
    def test_empty_grid_annotation(self):
        from shyfem_ui.components.grid_map import build_mesh_figure

        grd = GrdFile()
        fig = build_mesh_figure(grd)
        # Should have an annotation about no data
        assert any("No grid data" in a.text for a in fig.layout.annotations)

    def test_mesh_mode(self):
        from shyfem_ui.components.grid_map import build_mesh_figure

        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd, mode="mesh")
        assert len(fig.data) >= 1
        assert fig.data[0].name == "Mesh"

    def test_depth_mode(self):
        from shyfem_ui.components.grid_map import build_mesh_figure

        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd, mode="depth")
        # Should have wireframe + depth traces
        assert len(fig.data) >= 2

    def test_quality_mode(self):
        from shyfem_ui.components.grid_map import build_mesh_figure

        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd, mode="quality")
        # Should have wireframe + quality trace
        assert len(fig.data) >= 2

    def test_partition_mode(self):
        from shyfem_ui.components.grid_map import build_mesh_figure

        grd = _make_triangle_grid()
        partition = {1: 0}
        fig = build_mesh_figure(grd, mode="partitions", partition_map=partition)
        assert len(fig.data) >= 1

    def test_boundary_mode(self):
        from shyfem_ui.components.grid_map import build_mesh_figure

        grd = _make_triangle_grid()
        fig = build_mesh_figure(grd, mode="boundaries")
        # At minimum, light mesh wireframe
        assert len(fig.data) >= 1
