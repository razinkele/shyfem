"""Pure-helper tests for components.str_editor.

Covers:
- filter_sections: search-text filtering of STR sections
- validate_str_content: STR-text validation (structural, timing, boundary)
- generate_section_template: skeleton emission for a named section

The Shiny server function ``str_editor_server`` is NOT tested here — it
requires a reactive session and is exercised via Playwright.

Actual signatures confirmed from source:
    filter_sections(search_term: str, parsed: StrFile | None)
        -> dict[str, list[str]] | None
    validate_str_content(content: str, check_files: bool = False,
        working_dir: Path | None = None) -> list[str]
    generate_section_template(section_name: str) -> str
"""

import pytest

from shyfem_ui.components.str_editor import (
    filter_sections,
    generate_section_template,
    validate_str_content,
)
from shyfem_ui.services.parser_str import StrParser

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

MINIMAL_VALID_STR = """\
$title
    Test simulation
    test_run
$end
$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
$end
"""


def _errors(results: list[str]) -> list[str]:
    return [r for r in results if not r.startswith("Warning")]


def _warnings(results: list[str]) -> list[str]:
    return [r for r in results if r.startswith("Warning")]


@pytest.fixture
def parsed_str():
    """A parsed STR with $para and $name sections."""
    return StrParser.parse("""\
$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
    idtout = 3600
    czdef = 2.5e-3
$end
$name
    wind = 'INPUT/wind.txt'
$end
""")


# ===========================================================================
# TestFilterSections
# ===========================================================================


class TestFilterSections:
    """Tests for the section search-filter helper."""

    def test_returns_none_when_query_empty(self, parsed_str):
        """Blank search_term means 'show all' — returns None, not {}."""
        assert filter_sections("", parsed_str) is None

    def test_returns_none_when_query_whitespace_only(self, parsed_str):
        """Whitespace-only search is treated the same as empty."""
        assert filter_sections("   ", parsed_str) is None

    def test_returns_empty_dict_when_parsed_is_none(self):
        """Non-blank search with parsed=None returns {} (no sections to search)."""
        result = filter_sections("idt", None)
        assert result == {}

    def test_substring_match_on_param_name(self, parsed_str):
        """Substring match on a parameter name returns that param."""
        result = filter_sections("idt", parsed_str)
        assert result is not None
        assert "para" in result
        assert "idt" in result["para"]

    def test_case_insensitive_match(self, parsed_str):
        """Match is case-insensitive."""
        result_lower = filter_sections("idt", parsed_str)
        result_upper = filter_sections("IDT", parsed_str)
        assert result_lower == result_upper

    def test_no_match_returns_empty_dict(self, parsed_str):
        """Search term with no matches returns {} (not None)."""
        result = filter_sections("xyznoexist_abc", parsed_str)
        assert result == {}

    def test_returns_dict_of_string_lists(self, parsed_str):
        """Return type is dict[str, list[str]] when there are matches."""
        result = filter_sections("idt", parsed_str)
        assert result is not None
        for section, params in result.items():
            assert isinstance(section, str)
            assert isinstance(params, list)
            assert all(isinstance(p, str) for p in params)

    def test_sections_without_matches_omitted(self, parsed_str):
        """Sections with no matching params do not appear in the result."""
        # 'wind' matches the name section but not para
        result = filter_sections("wind", parsed_str)
        assert "name" in result
        assert "para" not in result

    def test_underscore_params_skipped(self):
        """Params whose names start with _ (internal markers) are never returned."""
        parsed = StrParser.parse("""\
$extra
    1  'output node'
$end
""")
        # _standalone would match "standalone" but should be skipped
        result = filter_sections("standalone", parsed)
        assert result == {}


# ===========================================================================
# TestValidateStrContent
# ===========================================================================


class TestValidateStrContent:
    """Tests for STR content validation."""

    # --- Valid input ---

    def test_accepts_minimal_valid_str(self):
        """Minimal valid STR (title + para with timing) has no errors."""
        errors = _errors(validate_str_content(MINIMAL_VALID_STR))
        assert errors == []

    # --- Required section ---

    def test_flags_missing_para(self):
        """Content without $para yields a 'Missing required section' error."""
        content = "$title\n    Test\n$end\n"
        errors = _errors(validate_str_content(content))
        assert any("Missing required section: $para" in e for e in errors)

    # --- Structural: unclosed section ---

    def test_flags_unclosed_section(self):
        """A section that is never closed yields a 'not closed' error."""
        content = "$para\n    itanf = 0\n    itend = 100\n    idt = 10\n"
        # No $end — section is open at EOF
        errors = _errors(validate_str_content(content))
        assert any("not closed" in e for e in errors)

    # --- Structural: orphan $end ---

    def test_flags_unexpected_end(self):
        """An $end with no matching section start is flagged."""
        content = "$para\n    idt = 300\n$end\n$end\n"
        errors = _errors(validate_str_content(content))
        assert any("Unexpected $end" in e for e in errors)

    # --- Boundary section: ibtyp check ---

    def test_bound_section_missing_ibtyp_warns(self):
        """A $bound1/$bound2/$boundN section without ibtyp triggers a warning."""
        content = (
            MINIMAL_VALID_STR
            + "$bound1\n    1  0  1  0.0\n$end\n"
        )
        warns = _warnings(validate_str_content(content))
        assert any("ibtyp" in w for w in warns)

    def test_bound_section_with_ibtyp_no_ibtyp_warning(self):
        """A $bound1 section that supplies ibtyp does not trigger the ibtyp warning."""
        content = (
            MINIMAL_VALID_STR
            + "$bound1\n    ibtyp = 1\n$end\n"
        )
        warns = _warnings(validate_str_content(content))
        assert not any("ibtyp" in w for w in warns)

    def test_plain_bound_section_not_checked_for_ibtyp(self):
        """The base $bound section (== 'bound') is exempt from the ibtyp check."""
        content = (
            MINIMAL_VALID_STR
            + "$bound\n    1  0  1  0.0\n$end\n"
        )
        warns = _warnings(validate_str_content(content))
        assert not any("ibtyp" in w for w in warns)

    # --- check_files flag does not affect non-file content ---

    def test_check_files_false_skips_file_check(self, tmp_path):
        """check_files=False never warns about missing files."""
        content = (
            MINIMAL_VALID_STR
            + "$name\n    wind = 'definitely_missing_file.txt'\n$end\n"
        )
        warns = _warnings(validate_str_content(content, check_files=False, working_dir=tmp_path))
        assert not any("file not found" in w for w in warns)


# ===========================================================================
# TestGenerateSectionTemplate
# ===========================================================================


class TestGenerateSectionTemplate:
    """Tests for section template emission."""

    @pytest.mark.parametrize("section_name", ["para", "title", "extra", "name", "bound"])
    def test_known_section_contains_start_and_end(self, section_name):
        """Every known section template starts with its section marker and closes with $end."""
        out = generate_section_template(section_name)
        assert out.startswith(f"${section_name}")
        assert "$end" in out

    def test_para_template_has_timing_params(self):
        """The $para template includes all three required timing parameters."""
        out = generate_section_template("para")
        assert "itanf" in out
        assert "itend" in out
        assert "idt" in out

    def test_unknown_section_returns_generic_template(self):
        """An unrecognised section name returns a generic skeleton with a comment."""
        out = generate_section_template("foobar_unknown")
        assert "$foobar_unknown" in out
        assert "Add parameters here" in out
        assert "$end" in out

    def test_unknown_section_does_not_raise(self):
        """generate_section_template never raises for arbitrary section names."""
        # Should not raise even for weird names
        generate_section_template("!@#_weird_name_123")

    def test_output_is_string(self):
        """Return type is always str."""
        assert isinstance(generate_section_template("para"), str)
        assert isinstance(generate_section_template("unknown_xyz"), str)
