"""Tests for the unified timeseries_loader module."""

from pathlib import Path

from shyfem_ui.services.timeseries_loader import (
    _looks_numeric,
    load_timeseries,
    load_timeseries_raw,
)

# ── _looks_numeric ──────────────────────────────────────────────


class TestLooksNumeric:
    def test_integer(self):
        assert _looks_numeric("42") is True

    def test_negative_float(self):
        assert _looks_numeric("-3.14") is True

    def test_scientific(self):
        assert _looks_numeric("1.5e10") is True

    def test_word(self):
        assert _looks_numeric("time") is False

    def test_empty(self):
        assert _looks_numeric("") is False


# ── load_timeseries (rich) ──────────────────────────────────────


class TestLoadTimeseries:
    def test_csv_file(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("time,temp,sal\n1,10.5,35.0\n2,11.0,34.8\n")
        result = load_timeseries(f)
        assert result["columns"] == ["time", "temp", "sal"]
        assert len(result["data"]) == 2
        assert result["df"] is not None

    def test_whitespace_delimited_with_header(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("time temp sal\n1 10.5 35.0\n2 11.0 34.8\n")
        result = load_timeseries(f)
        assert "time" in result["columns"]
        assert len(result["data"]) >= 2

    def test_whitespace_delimited_no_header(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("1 10.5 35.0\n2 11.0 34.8\n")
        result = load_timeseries(f)
        # Pandas treats first row as header by default; columns will be from row 1
        assert len(result["columns"]) == 3
        # Only the second row remains as data
        assert len(result["data"]) >= 1

    def test_missing_file(self, tmp_path: Path):
        result = load_timeseries(tmp_path / "missing.csv")
        assert result["columns"] == []
        assert result["data"] == []
        assert result["df"] is None

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.csv"
        f.write_text("")
        result = load_timeseries(f)
        assert result["data"] == [] or result["df"] is not None

    def test_mixed_numeric_and_text_lines(self, tmp_path: Path):
        f = tmp_path / "mixed.txt"
        f.write_text("1 2 3\nfoo bar baz\n4 5 6\n")
        result = load_timeseries(f)
        # Should skip non-numeric lines in whitespace fallback
        assert len(result["data"]) >= 1

    def test_accepts_string_path(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        result = load_timeseries(str(f))
        assert result["columns"] == ["a", "b"]

    def test_returns_dict_keys(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("x,y\n1,2\n")
        result = load_timeseries(f)
        assert set(result.keys()) == {"columns", "data", "df"}


# ── load_timeseries_raw ────────────────────────────────────────


class TestLoadTimeseriesRaw:
    def test_basic(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("1 10.5 35.0\n2 11.0 34.8\n")
        result = load_timeseries_raw(f)
        assert len(result) == 2
        assert result[0] == [1.0, 10.5, 35.0]

    def test_skips_non_numeric(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("1 2 3\nheader line\n4 5 6\n")
        result = load_timeseries_raw(f)
        assert len(result) == 2

    def test_skips_blank_lines(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("1 2\n\n\n3 4\n")
        result = load_timeseries_raw(f)
        assert len(result) == 2

    def test_missing_file(self, tmp_path: Path):
        result = load_timeseries_raw(tmp_path / "nope.txt")
        assert result == []

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = load_timeseries_raw(f)
        assert result == []

    def test_accepts_string_path(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("1 2\n3 4\n")
        result = load_timeseries_raw(str(f))
        assert len(result) == 2
