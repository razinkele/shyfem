"""Tests for helper functions in pages/run.py."""

from datetime import datetime, timedelta

from shyfem_ui.pages.run import (
    _estimate_eta,
    _stat_card,
    detect_mesh_node_count,
    get_solver_recommendation,
)
from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus


def _make_job(**overrides) -> JobInfo:
    """Create a JobInfo with sensible defaults for testing."""
    defaults = {
        "id": "test-001",
        "name": "test job",
        "tool_name": "shyfem",
        "args": [],
        "working_dir": "/tmp/test",
        "status": JobStatus.RUNNING,
        "created_at": datetime.now(),
        "started_at": datetime.now() - timedelta(seconds=100),
        "progress": 0.5,
    }
    defaults.update(overrides)
    return JobInfo(**defaults)


class TestEstimateEta:
    """Tests for _estimate_eta()."""

    def test_not_running_returns_empty(self):
        job = _make_job(status=JobStatus.COMPLETED)
        assert _estimate_eta(job) == ""

    def test_no_start_time_returns_empty(self):
        job = _make_job(started_at=None)
        assert _estimate_eta(job) == ""

    def test_zero_progress_returns_calculating(self):
        job = _make_job(progress=0)
        assert _estimate_eta(job) == "calculating..."

    def test_negative_progress_returns_calculating(self):
        job = _make_job(progress=-0.1)
        assert _estimate_eta(job) == "calculating..."

    def test_half_progress_returns_seconds(self):
        """50% done after 30s → ~30s remaining."""
        job = _make_job(
            started_at=datetime.now() - timedelta(seconds=30),
            progress=0.5,
        )
        result = _estimate_eta(job)
        assert result.endswith("s")

    def test_long_eta_returns_minutes(self):
        """10% done after 60s → ~540s = 9m 0s remaining."""
        job = _make_job(
            started_at=datetime.now() - timedelta(seconds=60),
            progress=0.1,
        )
        result = _estimate_eta(job)
        assert "m" in result

    def test_very_long_eta_returns_hours(self):
        """1% done after 60s → ~5940s = ~1h 39m remaining."""
        job = _make_job(
            started_at=datetime.now() - timedelta(seconds=60),
            progress=0.01,
        )
        result = _estimate_eta(job)
        assert "h" in result


class TestStatCard:
    """Tests for _stat_card()."""

    def test_returns_ui_element(self):
        result = _stat_card("Running", "3", "bg-primary")
        # Shiny ui.div returns a Tag object
        assert result is not None

    def test_different_bg_classes(self):
        for bg in ["bg-primary", "bg-success", "bg-danger", "bg-warning"]:
            result = _stat_card("Label", "0", bg)
            assert result is not None


class TestGetSolverRecommendation:
    """Tests for solver recommendation logic."""

    def test_small_mesh_recommends_sparskit(self):
        rec = get_solver_recommendation(1500, 50000)
        assert rec["solver"] == "sparskit"
        assert "Direct" in rec["hint"]

    def test_large_mesh_recommends_petsc(self):
        rec = get_solver_recommendation(100000, 50000)
        assert rec["solver"] == "petsc"
        assert "Iterative" in rec["hint"]

    def test_threshold_boundary_recommends_petsc(self):
        rec = get_solver_recommendation(50000, 50000)
        assert rec["solver"] == "petsc"

    def test_below_threshold_recommends_sparskit(self):
        rec = get_solver_recommendation(49999, 50000)
        assert rec["solver"] == "sparskit"

    def test_zero_nodes_recommends_sparskit(self):
        rec = get_solver_recommendation(0, 50000)
        assert rec["solver"] == "sparskit"

    def test_none_nodes_returns_no_recommendation(self):
        rec = get_solver_recommendation(None, 50000)
        assert rec["solver"] is None
        assert "detect" in rec["hint"].lower() or "manually" in rec["hint"].lower()


class TestDetectMeshNodeCount:
    """Tests for mesh node count detection from STR file."""

    def test_valid_str_with_grid(self, tmp_path):
        """Detects node count from grid file referenced in STR."""
        # Create a minimal .grd file (3 nodes, 1 triangle)
        # Format: record_type id type x y [depth]  for nodes
        #         record_type id type n1 n2 n3      for elements
        grd_content = (
            "1 1 0 0.000000 0.000000 -5.000000\n"
            "1 2 0 1.000000 0.000000 -5.000000\n"
            "1 3 0 0.500000 1.000000 -5.000000\n"
            "2 1 0 1 2 3\n"
        )
        grid_dir = tmp_path / "GRID"
        grid_dir.mkdir()
        (grid_dir / "test.grd").write_text(grd_content)

        # Create STR file referencing the grid
        str_content = "$title\n  Test sim\n  test_id\n  GRID/test\n$end\n$para\n$end\n"
        str_file = tmp_path / "test.str"
        str_file.write_text(str_content)

        count = detect_mesh_node_count(str_file, tmp_path)
        assert count == 3

    def test_missing_grid_returns_none(self, tmp_path):
        """Returns None when grid file doesn't exist."""
        str_content = "$title\n  Test sim\n  test_id\n  GRID/missing\n$end\n$para\n$end\n"
        str_file = tmp_path / "test.str"
        str_file.write_text(str_content)

        count = detect_mesh_node_count(str_file, tmp_path)
        assert count is None

    def test_no_title_section_returns_none(self, tmp_path):
        """Returns None when STR has no $title section."""
        str_content = "$para\n  idt = '300s'\n$end\n"
        str_file = tmp_path / "test.str"
        str_file.write_text(str_content)

        count = detect_mesh_node_count(str_file, tmp_path)
        assert count is None

    def test_nonexistent_str_returns_none(self, tmp_path):
        """Returns None for nonexistent STR file."""
        count = detect_mesh_node_count(tmp_path / "nope.str", tmp_path)
        assert count is None


class TestSolverJobRouting:
    """Tests for solver metadata routing in job execution."""

    def test_jobspec_metadata_stores_solver(self):
        """JobSpec metadata can store solver choice."""
        spec = JobSpec(
            name="test",
            tool_name="shyfem",
            args=["test.str"],
            working_dir="/tmp/test",
            metadata={"solver": "petsc"},
        )
        assert spec.metadata["solver"] == "petsc"

    def test_jobspec_default_no_solver(self):
        """JobSpec metadata has no solver key by default."""
        spec = JobSpec(
            name="test",
            tool_name="shyfem",
            args=["test.str"],
            working_dir="/tmp/test",
        )
        assert "solver" not in spec.metadata
