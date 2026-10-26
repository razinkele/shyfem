"""Tests for the unified timeseries_loader module."""

from pathlib import Path

import pytest

from shyfem_ui.services.timeseries_loader import (
    _load_whitespace,
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

    @pytest.mark.parametrize(
        "text",
        ["1 10.5 35.0\n2 11.0 34.8\n", "1,10.5,35.0\n2,11.0,34.8\n", "1;10.5;35.0\n2;11.0;34.8\n"],
    )
    def test_no_header_keeps_the_first_row(self, tmp_path: Path, text):
        """V-04: a numeric first line is data, not a header. pandas took it as
        the header, so the first record vanished and the columns were named
        "1", "10.5", "35.0"."""
        f = tmp_path / "data.txt"
        f.write_text(text)
        result = load_timeseries(f)
        assert result["columns"] == ["col0", "col1", "col2"]
        assert [list(map(float, r)) for r in result["data"]] == [[1, 10.5, 35.0], [2, 11.0, 34.8]]

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


# ── _load_whitespace: leading blank line header detection (F48) ─


class TestLoadWhitespaceLeadingBlankLine:
    def test_leading_blank_line_header_detected_identically(self, tmp_path: Path):
        """A leading blank line must not shift the header off index 0.

        _load_whitespace historically only checked ``enumerate`` index ``i == 0``
        to decide whether the first row is a header. Blank lines are skipped
        with ``continue`` but still consume an index, so a file that starts
        with a blank line before the header silently lost its header row.
        """
        with_blank = tmp_path / "with_blank.txt"
        with_blank.write_text("\ntime temp sal\n1 10.5 35.0\n2 11.0 34.8\n")

        without_blank = tmp_path / "without_blank.txt"
        without_blank.write_text("time temp sal\n1 10.5 35.0\n2 11.0 34.8\n")

        result_with = _load_whitespace(with_blank)
        result_without = _load_whitespace(without_blank)

        assert result_with["columns"] == ["time", "temp", "sal"]
        assert result_with["columns"] == result_without["columns"]
        assert result_with["data"] == result_without["data"]

    def test_multiple_leading_blank_lines_header_detected(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("\n\n\ntime temp\n1 10.5\n")
        result = _load_whitespace(f)
        assert result["columns"] == ["time", "temp"]
        assert result["data"] == [[1.0, 10.5]]

    def test_no_leading_blank_still_works(self, tmp_path: Path):
        f = tmp_path / "data.txt"
        f.write_text("time temp\n1 10.5\n")
        result = _load_whitespace(f)
        assert result["columns"] == ["time", "temp"]
        assert result["data"] == [[1.0, 10.5]]

    def test_leading_blank_line_no_header_still_numeric(self, tmp_path: Path):
        """File with no header row (first non-blank row is numeric) is unaffected."""
        f = tmp_path / "data.txt"
        f.write_text("\n1 10.5\n2 11.0\n")
        result = _load_whitespace(f)
        assert result["columns"] == ["col0", "col1"]
        assert result["data"] == [[1.0, 10.5], [2.0, 11.0]]


def test_load_shyfem_forcing_txt(tmp_path):
    """SHYFEM 'date::time value' forcing parses to a datetime time axis."""
    from shyfem_ui.services.timeseries_loader import load_timeseries

    f = tmp_path / "nemunas.txt"
    f.write_text(
        "1990-01-03::06:00:00        655.157\n"
        "1990-01-04::06:00:00        568.419\n"
        "1990-01-05::06:00:00        514.847\n"
    )
    r = load_timeseries(f)
    df = r["df"]
    assert df is not None
    assert list(df.columns) == ["time", "value"]
    assert str(df["time"].dtype).startswith("datetime64")
    assert df.shape == (3, 2)
    assert abs(df["value"].iloc[0] - 655.157) < 1e-6


def test_load_observations_long_is_pivoted(tmp_path):
    """A long date,site,variable,value CSV becomes one column per series."""
    from shyfem_ui.services.timeseries_loader import load_timeseries

    f = tmp_path / "observations.csv"
    f.write_text(
        "date,site,variable,value\n"
        "2001-01-01,Nida,level,516.0\n"
        "2001-01-01,Nida,salinity,0.05\n"
        "2001-01-02,Nida,level,517.0\n"
        "2001-01-01,Klaipeda,salinity,6.5\n"
    )
    r = load_timeseries(f)
    df = r["df"]
    assert df is not None
    assert "date" in df.columns
    assert {"Nida level", "Nida salinity", "Klaipeda salinity"} <= set(df.columns)
    # two distinct dates -> two rows
    assert df.shape[0] == 2
