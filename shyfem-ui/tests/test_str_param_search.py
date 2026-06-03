"""Tests for STR parameter search filtering."""

import pytest

from shyfem_ui.components.str_editor import filter_sections
from shyfem_ui.services.parser_str import StrParser


@pytest.fixture
def sample_str():
    """A minimal parsed STR with known params."""
    return StrParser.parse("""
$title
    Test Simulation
    sim
    GRID/grid
$end

$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
    idtout = 3600
    ireib = 5
    czdef = 2.5e-3
$end

$name
    wind = 'INPUT/wind.txt'
    gotmpa = 'INPUT/gotm.nml'
$end
""")


class TestFilterSections:

    def test_empty_search_returns_none(self, sample_str):
        """Empty string means no filtering — return None."""
        assert filter_sections("", sample_str) is None
        assert filter_sections("  ", sample_str) is None

    def test_match_by_param_name(self, sample_str):
        """Substring match on parameter name."""
        result = filter_sections("idt", sample_str)
        assert "para" in result
        assert "idt" in result["para"]
        assert "idtout" in result["para"]

    def test_match_by_description(self, sample_str):
        """Match against COMMON_PARAMS description text."""
        result = filter_sections("time step", sample_str)
        assert "para" in result
        assert "idt" in result["para"]

    def test_case_insensitive(self, sample_str):
        result = filter_sections("IDT", sample_str)
        assert "para" in result
        assert "idt" in result["para"]

    def test_no_matches_returns_empty(self, sample_str):
        result = filter_sections("xyznonexistent", sample_str)
        assert result == {}

    def test_sections_with_no_matches_omitted(self, sample_str):
        """Sections where no param matches should not appear."""
        result = filter_sections("wind", sample_str)
        assert "name" in result
        assert "para" not in result

    def test_unknown_param_matched_by_name(self):
        """Params not in COMMON_PARAMS are matched by name only."""
        parsed = StrParser.parse("""
$para
    mycustomparam = 42
$end
""")
        result = filter_sections("mycustom", parsed)
        assert "para" in result
        assert "mycustomparam" in result["para"]

    def test_special_chars_treated_as_literal(self, sample_str):
        """Regex special chars should not cause errors."""
        result = filter_sections("[invalid(regex", sample_str)
        assert result == {}

    def test_match_across_sections(self, sample_str):
        """A broad term can match params in multiple sections."""
        result = filter_sections("file", sample_str)
        assert "name" in result

    def test_standalone_entries_skipped(self):
        """Params starting with _ (standalone entries) are skipped."""
        parsed = StrParser.parse("""
$extra
    1  'output node'
$end
""")
        result = filter_sections("standalone", parsed)
        assert result == {}

    def test_returns_count_info(self, sample_str):
        """Result dict only contains param name lists."""
        result = filter_sections("idt", sample_str)
        for _section, params in result.items():
            assert isinstance(params, list)
            assert all(isinstance(p, str) for p in params)
