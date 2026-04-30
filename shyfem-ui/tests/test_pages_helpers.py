"""Unit tests for pure helper functions in shyfem_ui/pages/."""

from datetime import datetime, timedelta

import pytest
from shiny import ui

from shyfem_ui.services.job_queue import JobInfo, JobStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_job(**overrides) -> JobInfo:
    defaults = dict(
        id="job-001",
        name="Test Job",
        tool_name="shyfem",
        args=["-f", "sim.str"],
        working_dir="/tmp/sim",
        status=JobStatus.RUNNING,
        progress=0.5,
        created_at=datetime(2025, 1, 15, 10, 0, 0),
        started_at=datetime(2025, 1, 15, 10, 0, 0),
    )
    defaults.update(overrides)
    return JobInfo(**defaults)


# ---------------------------------------------------------------------------
# _parse_shyelab_info (postprocess.py)
# ---------------------------------------------------------------------------

class TestParseShyelabInfo:
    """Test the Fortran shyelab -info output parser."""

    @staticmethod
    def _parse(text: str) -> dict:
        from shyfem_ui.services.postprocess_logic import parse_shyelab_info
        return parse_shyelab_info(text)

    def test_empty_input(self):
        result = self._parse("")
        assert result == {}

    def test_colon_pairs(self):
        text = "filename: test.shy\nnvers: 5\nftype: OUS\n"
        result = self._parse(text)
        assert result["File Name"] == "test.shy"
        assert result["Version"] == "5"
        assert result["File Type"] == "OUS"

    def test_boolean_mapping(self):
        text = "flag: T\nother: .FALSE.\n"
        result = self._parse(text)
        assert result["flag"] == "Yes"
        assert result["other"] == "No"

    def test_basin_info(self):
        text = "nkn = 1234   nel = 5678   mbw = 42\n"
        result = self._parse(text)
        assert result["nkn"] == "1234"
        assert result["nel"] == "5678"
        assert result["mbw"] == "42"

    def test_variable_descriptions(self):
        text = (
            "total number of available variables: 3\n"
            "varnum  varid  description\n"
            "  1   10  water level\n"
            "  2   20  u-velocity\n"
            "  3   30  v-velocity\n"
            "\n"
        )
        result = self._parse(text)
        assert result["Total Variables"] == "3"
        assert "Variable Names" in result
        names = result["Variable Names"]
        assert "water level" in names
        assert "u-velocity" in names
        assert "v-velocity" in names

    def test_layer_depths(self):
        text = "levels: 5\n  0.5  1.0  2.0  5.0  10.0\n\n"
        result = self._parse(text)
        assert result["Levels"] == "5"
        assert "Layer Depths" in result
        depths = result["Layer Depths"].split(", ")
        assert len(depths) == 5

    def test_information_header_skipped(self):
        text = "information on shy file\nfilename: grid.shy\n"
        result = self._parse(text)
        assert "information on shy file" not in result
        assert result["File Name"] == "grid.shy"

    def test_full_realistic_output(self):
        text = (
            "information on shy file\n"
            "filename: adriatic.shy\n"
            "nvers: 7\n"
            "ftype: TS\n"
            "nkn: 12345\n"
            "nel: 24000\n"
            "nlv: 10\n"
            "nvar: 3\n"
            "date: 20200101\n"
            "time: 0\n"
            "title: Adriatic Sea\n"
            "femver: SHYFEM 7.5.72\n"
            "\n"
            "total number of available variables: 3\n"
            "varnum  varid  description\n"
            "  1   1  water level\n"
            "  2   2  salinity\n"
            "  3   3  temperature\n"
            "\n"
            "levels: 10\n"
            "  0.5 1.0 2.0 5.0 10.0 20.0 50.0 100.0 200.0 500.0\n"
            "\n"
        )
        result = self._parse(text)
        assert result["File Name"] == "adriatic.shy"
        assert result["Title"] == "Adriatic Sea"
        assert result["SHYFEM Version"] == "SHYFEM 7.5.72"
        assert result["Levels"] == "10"
        assert result["Total Variables"] == "3"


# ---------------------------------------------------------------------------
# _stat_card (run.py)
# ---------------------------------------------------------------------------

class TestStatCard:
    @staticmethod
    def _card(label, value, bg_class):
        from shyfem_ui.pages.run import _stat_card
        return _stat_card(label, value, bg_class)

    def test_basic_card(self):
        result = self._card("Jobs", "5", "bg-primary")
        assert isinstance(result, ui.Tag)
        rendered = str(result)
        assert "5" in rendered
        assert "Jobs" in rendered
        assert "bg-primary" in rendered

    def test_different_bg(self):
        result = self._card("Errors", "0", "bg-danger")
        rendered = str(result)
        assert "bg-danger" in rendered
        assert "Errors" in rendered


# ---------------------------------------------------------------------------
# _estimate_eta (run.py)
# ---------------------------------------------------------------------------

class TestEstimateEta:
    @staticmethod
    def _eta(job: JobInfo) -> str:
        from shyfem_ui.pages.run import _estimate_eta
        return _estimate_eta(job)

    def test_not_running(self):
        job = _make_job(status=JobStatus.COMPLETED, progress=1.0)
        assert self._eta(job) == ""

    def test_no_started_at(self):
        job = _make_job(status=JobStatus.RUNNING, started_at=None, progress=0.5)
        assert self._eta(job) == ""

    def test_zero_progress(self):
        job = _make_job(progress=0.0)
        assert self._eta(job) == "calculating..."

    def test_seconds_remaining(self):
        now = datetime.now()
        job = _make_job(
            started_at=now - timedelta(seconds=30),
            progress=0.9,
        )
        result = self._eta(job)
        # ~3.3 seconds remaining  → should end with "s"
        assert result.endswith("s")
        assert "m" not in result
        assert "h" not in result

    def test_minutes_remaining(self):
        now = datetime.now()
        job = _make_job(
            started_at=now - timedelta(seconds=60),
            progress=0.5,
        )
        result = self._eta(job)
        # ~60s remaining → "1m 0s"
        assert "m" in result

    def test_hours_remaining(self):
        now = datetime.now()
        job = _make_job(
            started_at=now - timedelta(seconds=600),
            progress=0.1,
        )
        result = self._eta(job)
        # ~5400s remaining → "1h 30m"
        assert "h" in result


# ---------------------------------------------------------------------------
# _load_obs_file (timeseries.py)
# ---------------------------------------------------------------------------

class TestLoadObsFile:
    @staticmethod
    def _load(path):
        from shyfem_ui.components.timeseries import _load_obs_file
        return _load_obs_file(path)

    def test_csv_file(self, tmp_path):
        f = tmp_path / "obs.csv"
        f.write_text("time,value\n1.0,10.5\n2.0,20.3\n3.0,30.1\n")
        result = self._load(f)
        assert "time" in result["columns"]
        assert "value" in result["columns"]
        assert len(result["data"]) == 3

    def test_whitespace_delimited(self, tmp_path):
        f = tmp_path / "obs.dat"
        f.write_text("time val1 val2\n1.0 10.0 20.0\n2.0 30.0 40.0\n")
        result = self._load(f)
        assert "time" in result["columns"]
        assert len(result["data"]) == 2

    def test_numeric_only_file(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("1.0 2.0 3.0\n4.0 5.0 6.0\n")
        result = self._load(f)
        # pandas uses first row as header; data has 1 row remaining
        assert len(result["columns"]) == 3
        assert len(result["data"]) == 1

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("")
        result = self._load(f)
        assert result["data"] == [] or result["columns"] == []
