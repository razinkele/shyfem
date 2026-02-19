"""Unit tests for pure helper functions in boundary_editor component.

Tests generate_bound_text() and parse_boundary_csv() from
shyfem_ui.components.boundary_editor.
"""

import pytest

from shyfem_ui.components.boundary_editor import (
    generate_bound_text,
    parse_boundary_csv,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bound(label="bound1", nodes="1 2 3", ibtyp=1, boundn="", zfact=1.0, intpol=1, bid=1):
    """Create a boundary dict with sensible defaults."""
    return {"id": bid, "label": label, "nodes": nodes, "ibtyp": ibtyp,
            "boundn": boundn, "zfact": zfact, "intpol": intpol}


# ---------------------------------------------------------------------------
# generate_bound_text
# ---------------------------------------------------------------------------

class TestGenerateBoundText:
    """Tests for generate_bound_text()."""

    def test_empty_list_returns_no_boundaries_message(self):
        """Empty boundary list produces a comment saying none defined."""
        result = generate_bound_text([])
        assert "No boundaries defined" in result

    def test_single_boundary_basic(self):
        """Single boundary contains $section_name, kbound, ibtyp, and $end."""
        result = generate_bound_text([_bound()])
        assert "$bound1" in result
        assert "kbound = 1 2 3" in result
        assert "ibtyp = 1" in result
        assert "$end" in result

    def test_boundn_included_when_set(self):
        """boundn line is emitted when a non-empty string is provided."""
        result = generate_bound_text([_bound(boundn="INPUT/tide.txt")])
        assert "boundn = 'INPUT/tide.txt'" in result

    def test_boundn_omitted_when_empty(self):
        """boundn line is suppressed when the value is an empty string."""
        result = generate_bound_text([_bound(boundn="")])
        assert "boundn" not in result

    def test_zfact_included_when_not_one(self):
        """zfact line is emitted when value differs from 1.0."""
        result = generate_bound_text([_bound(zfact=2.5)])
        assert "zfact = 2.5" in result

    def test_zfact_omitted_when_one(self):
        """zfact line is suppressed when value equals 1.0."""
        result = generate_bound_text([_bound(zfact=1.0)])
        assert "zfact" not in result

    def test_intpol_included_when_not_one(self):
        """intpol line is emitted when value differs from 1."""
        result = generate_bound_text([_bound(intpol=2)])
        assert "intpol = 2" in result

    def test_intpol_omitted_when_one(self):
        """intpol line is suppressed when value equals 1."""
        result = generate_bound_text([_bound(intpol=1)])
        assert "intpol" not in result

    def test_multiple_boundaries(self):
        """Multiple boundaries produce separate $end markers and section names."""
        bounds = [
            _bound(label="bound1", bid=1),
            _bound(label="bound2", bid=2),
        ]
        result = generate_bound_text(bounds)
        assert result.count("$end") == 2
        assert "$bound1" in result
        assert "$bound2" in result

    def test_nodes_empty_omits_kbound(self):
        """kbound line is omitted when nodes string is empty."""
        result = generate_bound_text([_bound(nodes="")])
        assert "kbound" not in result

    def test_full_boundary_all_fields(self):
        """All optional fields present when their values trigger inclusion."""
        b = _bound(
            label="bound5",
            nodes="10 20 30",
            ibtyp=3,
            boundn="INPUT/river.txt",
            zfact=0.5,
            intpol=2,
            bid=5,
        )
        result = generate_bound_text([b])
        assert "$bound5" in result
        assert "kbound = 10 20 30" in result
        assert "ibtyp = 3" in result
        assert "boundn = 'INPUT/river.txt'" in result
        assert "zfact = 0.5" in result
        assert "intpol = 2" in result
        assert "$end" in result


# ---------------------------------------------------------------------------
# parse_boundary_csv
# ---------------------------------------------------------------------------

class TestParseBoundaryCSV:
    """Tests for parse_boundary_csv()."""

    def test_valid_two_columns(self):
        """Minimum two-column CSV yields nodes and ibtyp."""
        result = parse_boundary_csv("1 2 3, 1")
        assert len(result) == 1
        assert result[0]["nodes"] == "1 2 3"
        assert result[0]["ibtyp"] == 1

    def test_all_five_columns(self):
        """All five columns populate boundn, zfact, and intpol."""
        result = parse_boundary_csv("4 5, 2, INPUT/tide.txt, 0.5, 2")
        assert len(result) == 1
        entry = result[0]
        assert entry["nodes"] == "4 5"
        assert entry["ibtyp"] == 2
        assert entry["boundn"] == "INPUT/tide.txt"
        assert entry["zfact"] == 0.5
        assert entry["intpol"] == 2

    def test_comment_lines_skipped(self):
        """Lines starting with '#' are ignored."""
        csv = "# header comment\n1 2, 1\n# another comment\n3 4, 2"
        result = parse_boundary_csv(csv)
        assert len(result) == 2

    def test_blank_lines_skipped(self):
        """Empty lines are ignored."""
        csv = "\n1 2, 1\n\n\n3 4, 2\n"
        result = parse_boundary_csv(csv)
        assert len(result) == 2

    def test_single_column_skipped(self):
        """Lines with fewer than 2 columns are skipped."""
        csv = "only_one_column\n1 2, 1"
        result = parse_boundary_csv(csv)
        assert len(result) == 1
        assert result[0]["nodes"] == "1 2"

    def test_multiple_lines_count_and_labels(self):
        """Multiple valid lines produce correct count and sequential labels."""
        csv = "1 2, 1\n3 4, 2\n5 6, 3"
        result = parse_boundary_csv(csv)
        assert len(result) == 3
        assert result[0]["label"] == "bound1"
        assert result[1]["label"] == "bound2"
        assert result[2]["label"] == "bound3"

    def test_start_id_parameter(self):
        """start_id shifts IDs and labels."""
        result = parse_boundary_csv("1 2, 1\n3 4, 2", start_id=5)
        assert result[0]["id"] == 5
        assert result[0]["label"] == "bound5"
        assert result[1]["id"] == 6
        assert result[1]["label"] == "bound6"

    def test_defaults_for_optional_columns(self):
        """Missing optional columns get default values."""
        result = parse_boundary_csv("1 2 3, 1")
        entry = result[0]
        assert entry["boundn"] == ""
        assert entry["zfact"] == 1.0
        assert entry["intpol"] == 1

    def test_invalid_ibtyp_raises_value_error(self):
        """Non-integer ibtyp string raises ValueError."""
        with pytest.raises(ValueError):
            parse_boundary_csv("1 2, abc")

    def test_whitespace_in_values_stripped(self):
        """Leading/trailing whitespace in each CSV column is stripped."""
        result = parse_boundary_csv("  1 2 3  ,  2  ,  INPUT/file.txt  ,  0.8  ,  2  ")
        entry = result[0]
        assert entry["nodes"] == "1 2 3"
        assert entry["ibtyp"] == 2
        assert entry["boundn"] == "INPUT/file.txt"
        assert entry["zfact"] == 0.8
        assert entry["intpol"] == 2
