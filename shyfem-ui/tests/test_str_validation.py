"""Tests for STR validation engine: validate_str_content, _check_range,
generate_section_template, and get_parameter_help."""

import pytest

from shyfem_ui.components.str_editor import (
    _check_range,
    generate_section_template,
    get_parameter_help,
    validate_str_content,
)


# ---------------------------------------------------------------------------
# Helpers
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
    """Return only error strings (exclude warnings)."""
    return [r for r in results if not r.startswith("Warning")]


def _warnings(results: list[str]) -> list[str]:
    """Return only warning strings."""
    return [r for r in results if r.startswith("Warning")]


# ===========================================================================
# TestValidateStructure
# ===========================================================================


class TestValidateStructure:
    """Structural validation: section matching, required sections."""

    def test_empty_content_missing_para(self):
        """Empty content triggers missing $para error."""
        result = validate_str_content("")
        errs = _errors(result)
        assert any("Missing required section: $para" in e for e in errs)

    def test_missing_end(self):
        """Unclosed section triggers 'not closed' error."""
        content = "$para\n    idt = 300\n"
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("not closed" in e for e in errs)

    def test_extra_end(self):
        """$end without a matching section start triggers 'Unexpected $end'."""
        content = "$para\n    idt = 300\n$end\n$end\n"
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("Unexpected $end" in e for e in errs)

    def test_missing_para_section(self):
        """Content with no $para section → error."""
        content = "$title\n    Test\n$end\n"
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("Missing required section: $para" in e for e in errs)

    def test_missing_title_warning(self):
        """Content without $title → warning (not error)."""
        content = "$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
        result = validate_str_content(content)
        warns = _warnings(result)
        assert any("$title" in w for w in warns)
        # Must NOT be an error
        errs = _errors(result)
        assert not any("$title" in e for e in errs)

    def test_valid_minimal_no_errors(self):
        """Valid minimal STR has no errors (warnings are acceptable)."""
        result = validate_str_content(MINIMAL_VALID_STR)
        errs = _errors(result)
        assert errs == []


# ===========================================================================
# TestValidateTiming
# ===========================================================================


class TestValidateTiming:
    """Timing parameter checks inside $para."""

    def _para(self, body: str) -> str:
        return f"$title\n    Test\n$end\n$para\n{body}\n$end\n"

    def test_missing_itanf(self):
        """Missing itanf → error."""
        content = self._para("    itend = 100\n    idt = 10")
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("itanf" in e for e in errs)

    def test_missing_itend(self):
        """Missing itend → error."""
        content = self._para("    itanf = 0\n    idt = 10")
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("itend" in e for e in errs)

    def test_missing_idt(self):
        """Missing idt → error."""
        content = self._para("    itanf = 0\n    itend = 100")
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("idt" in e for e in errs)

    def test_itanf_gte_itend(self):
        """itanf >= itend → error."""
        content = self._para("    itanf = 100\n    itend = 50\n    idt = 10")
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("itanf" in e and "itend" in e for e in errs)

    def test_idt_zero(self):
        """idt = 0 → error (must be positive)."""
        content = self._para("    itanf = 0\n    itend = 100\n    idt = 0")
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("idt" in e and "positive" in e for e in errs)

    def test_idt_negative(self):
        """idt < 0 → error."""
        content = self._para("    itanf = 0\n    itend = 100\n    idt = -5")
        result = validate_str_content(content)
        errs = _errors(result)
        assert any("idt" in e and "positive" in e for e in errs)


# ===========================================================================
# TestValidateDepthAndRange
# ===========================================================================


class TestValidateDepthAndRange:
    """Depth consistency and unknown-parameter checks."""

    def _para(self, body: str) -> str:
        return f"$title\n    Test\n$end\n$para\n{body}\n$end\n"

    def test_hzmin_gte_hzoff_warning(self):
        """hzmin >= hzoff → warning."""
        content = self._para(
            "    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    hzmin = 0.10\n    hzoff = 0.05"
        )
        result = validate_str_content(content)
        warns = _warnings(result)
        assert any("hzmin" in w and "hzoff" in w for w in warns)

    def test_unknown_param_warning(self):
        """A truly unknown parameter produces a warning."""
        content = self._para(
            "    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    xyznoexist = 42"
        )
        result = validate_str_content(content)
        warns = _warnings(result)
        assert any("xyznoexist" in w for w in warns)

    def test_idt_prefixed_not_flagged(self):
        """Parameters starting with 'idt' are NOT flagged as unknown."""
        content = self._para(
            "    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    idtfoo = 999"
        )
        result = validate_str_content(content)
        warns = _warnings(result)
        assert not any("idtfoo" in w for w in warns)

    def test_itm_prefixed_not_flagged(self):
        """Parameters starting with 'itm' are NOT flagged as unknown."""
        content = self._para(
            "    itanf = 0\n    itend = 100\n    idt = 10\n"
            "    itmfoo = 123"
        )
        result = validate_str_content(content)
        warns = _warnings(result)
        assert not any("itmfoo" in w for w in warns)


# ===========================================================================
# TestValidateFiles
# ===========================================================================


class TestValidateFiles:
    """File-existence checks in $name section."""

    def _str_with_name(self, filename: str) -> str:
        return (
            "$title\n    Test\n$end\n"
            "$para\n    itanf = 0\n    itend = 100\n    idt = 10\n$end\n"
            f"$name\n    wind = '{filename}'\n$end\n"
        )

    def test_missing_file_warning(self, tmp_path):
        """Missing file with check_files=True → warning."""
        content = self._str_with_name("nonexistent_file.txt")
        result = validate_str_content(content, check_files=True, working_dir=tmp_path)
        warns = _warnings(result)
        assert any("file not found" in w for w in warns)

    def test_existing_file_no_warning(self, tmp_path):
        """Existing file → no file-not-found warning."""
        real_file = tmp_path / "wind_data.txt"
        real_file.write_text("1.0 2.0\n")
        content = self._str_with_name("wind_data.txt")
        result = validate_str_content(content, check_files=True, working_dir=tmp_path)
        warns = _warnings(result)
        assert not any("file not found" in w for w in warns)

    def test_check_files_false_skips(self, tmp_path):
        """check_files=False skips file existence checks."""
        content = self._str_with_name("nonexistent_file.txt")
        result = validate_str_content(content, check_files=False, working_dir=tmp_path)
        warns = _warnings(result)
        assert not any("file not found" in w for w in warns)


# ===========================================================================
# TestCheckRange
# ===========================================================================


class TestCheckRange:
    """Tests for _check_range helper."""

    # --- [lo, hi] bracket ranges ---

    def test_bracket_in_range(self):
        """Value within [0,1] → no warning."""
        warnings = []
        _check_range(warnings, "para", "azpar", 0.5, "[0,1]")
        assert warnings == []

    def test_bracket_lower_boundary(self):
        """Value at lower boundary [0,1] → no warning."""
        warnings = []
        _check_range(warnings, "para", "azpar", 0.0, "[0,1]")
        assert warnings == []

    def test_bracket_upper_boundary(self):
        """Value at upper boundary [0,1] → no warning."""
        warnings = []
        _check_range(warnings, "para", "azpar", 1.0, "[0,1]")
        assert warnings == []

    def test_bracket_below_range(self):
        """Value below [0,1] → warning."""
        warnings = []
        _check_range(warnings, "para", "azpar", -0.1, "[0,1]")
        assert len(warnings) == 1
        assert "outside range" in warnings[0]

    def test_bracket_above_range(self):
        """Value above [0,1] → warning."""
        warnings = []
        _check_range(warnings, "para", "azpar", 1.5, "[0,1]")
        assert len(warnings) == 1
        assert "outside range" in warnings[0]

    # --- >0 constraint ---

    def test_gt_zero_positive(self):
        """Positive value with >0 constraint → no warning."""
        warnings = []
        _check_range(warnings, "para", "hzmin", 0.01, ">0")
        assert warnings == []

    def test_gt_zero_zero(self):
        """Zero with >0 constraint → warning."""
        warnings = []
        _check_range(warnings, "para", "hzmin", 0.0, ">0")
        assert len(warnings) == 1
        assert ">0" in warnings[0]

    def test_gt_zero_negative(self):
        """Negative value with >0 constraint → warning."""
        warnings = []
        _check_range(warnings, "para", "hzmin", -1.0, ">0")
        assert len(warnings) == 1
        assert ">0" in warnings[0]

    # --- >=0 constraint ---

    def test_gte_zero_positive(self):
        """Positive value with >=0 constraint → no warning."""
        warnings = []
        _check_range(warnings, "para", "diftur", 1.0, ">=0")
        assert warnings == []

    def test_gte_zero_zero(self):
        """Zero with >=0 constraint → no warning."""
        warnings = []
        _check_range(warnings, "para", "diftur", 0.0, ">=0")
        assert warnings == []

    def test_gte_zero_negative(self):
        """Negative value with >=0 constraint → warning."""
        warnings = []
        _check_range(warnings, "para", "diftur", -0.5, ">=0")
        assert len(warnings) == 1
        assert ">=0" in warnings[0]

    # --- Non-matching options ---

    def test_non_matching_options_no_warning(self):
        """Options that don't match range patterns → no warning."""
        warnings = []
        _check_range(warnings, "para", "ilin", 1, "0=linear, 1=nonlinear")
        assert warnings == []


# ===========================================================================
# TestGenerateSectionTemplate
# ===========================================================================


class TestGenerateSectionTemplate:
    """Tests for generate_section_template."""

    @pytest.mark.parametrize("section", ["para", "title", "extra", "name", "bound"])
    def test_known_section_has_content_and_end(self, section):
        """Known sections produce a template with section start and $end."""
        template = generate_section_template(section)
        assert template.startswith(f"${section}")
        assert "$end" in template

    def test_unknown_section_generic(self):
        """Unknown section → generic template with 'Add parameters here'."""
        template = generate_section_template("foobar")
        assert "$foobar" in template
        assert "Add parameters here" in template
        assert "$end" in template

    def test_para_has_timing_params(self):
        """Para template includes timing parameters."""
        template = generate_section_template("para")
        assert "itanf" in template
        assert "itend" in template
        assert "idt" in template


# ===========================================================================
# TestGetParameterHelp
# ===========================================================================


class TestGetParameterHelp:
    """Tests for get_parameter_help."""

    def test_known_param_non_none(self):
        """Known parameter returns non-None help string."""
        result = get_parameter_help("para", "idt")
        assert result is not None
        assert len(result) > 0

    def test_param_with_units(self):
        """Parameter with units includes 'Units:' in result."""
        # idt has units = "s"
        result = get_parameter_help("para", "idt")
        assert result is not None
        assert "Units:" in result

    def test_param_with_default(self):
        """Parameter with a default value includes 'Default:' in result."""
        # azpar has default 0.5
        result = get_parameter_help("para", "azpar")
        assert result is not None
        assert "Default:" in result

    def test_param_with_options(self):
        """Parameter with options includes the options text."""
        # azpar has options "[0,1]"
        result = get_parameter_help("para", "azpar")
        assert result is not None
        assert "[0,1]" in result

    def test_unknown_param_returns_none(self):
        """Unknown parameter → None."""
        result = get_parameter_help("para", "xyznoexist")
        assert result is None

    def test_unknown_section_returns_none(self):
        """Unknown section → None."""
        result = get_parameter_help("nonexistent_section", "idt")
        assert result is None

    def test_name_section_param(self):
        """Name section parameter returns non-None help."""
        result = get_parameter_help("name", "wind")
        assert result is not None
        assert len(result) > 0
