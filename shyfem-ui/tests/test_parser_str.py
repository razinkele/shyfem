"""Tests for .str file parser."""

import pytest
from shyfem_ui.services.parser_str import (
    COMMON_PARAMS,
    StrFile,
    StrParser,
    StrSection,
    get_param_info,
)


class TestStrParser:
    """Tests for StrParser class."""

    def test_parse_basic_section(self):
        """Test parsing a basic section."""
        content = """
$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
$end
"""
        result = StrParser.parse(content)

        assert "para" in result.sections
        para = result.sections["para"]
        # Quotes are stripped from string values during parsing
        assert para.parameters["itanf"] == "2020-01-01"
        assert para.parameters["itend"] == "2020-01-02"
        assert para.parameters["idt"] == 300

    def test_parse_multiple_params_per_line(self):
        """Test parsing multiple parameters on one line."""
        content = """
$para
    iwtype = 3     dragco = 2.5e-3
$end
"""
        result = StrParser.parse(content)
        para = result.sections["para"]

        assert para.parameters["iwtype"] == 3
        assert para.parameters["dragco"] == pytest.approx(2.5e-3)

    def test_parse_standalone_values(self):
        """Test parsing standalone values (like in $extra section)."""
        content = """
$extra
    128     'sea boundary'
    58      'inlet'
$end
"""
        result = StrParser.parse(content)
        extra = result.sections["extra"]

        assert "_standalone" in extra.parameters
        standalone = extra.parameters["_standalone"]
        assert len(standalone) == 2
        assert standalone[0]["id"] == 128
        assert standalone[0]["description"] == "sea boundary"

    def test_parse_comments(self):
        """Test that comments are handled correctly."""
        content = """
# This is a header comment
$para
    # This is a section comment
    idt = 300
$end
"""
        result = StrParser.parse(content)

        assert len(result.header_comments) >= 1
        assert "para" in result.sections

    def test_parse_empty_section(self):
        """Test parsing an empty section."""
        content = """
$empty
$end
"""
        result = StrParser.parse(content)

        assert "empty" in result.sections
        assert len(result.sections["empty"].parameters) == 0

    def test_get_param(self):
        """Test getting parameter values."""
        content = """
$para
    idt = 300
$end
"""
        result = StrParser.parse(content)

        assert result.get_param("para", "idt") == 300
        assert result.get_param("para", "nonexistent") is None
        assert result.get_param("para", "nonexistent", "default") == "default"
        assert result.get_param("nonexistent", "idt") is None

    def test_set_param(self):
        """Test setting parameter values."""
        str_file = StrFile()
        str_file.set_param("para", "idt", 300)
        str_file.set_param("para", "itanf", "'2020-01-01'")

        assert str_file.get_param("para", "idt") == 300
        assert str_file.get_param("para", "itanf") == "'2020-01-01'"

    def test_value_conversion(self):
        """Test automatic value type conversion."""
        content = """
$para
    int_val = 42
    float_val = 3.14
    sci_val = 1.5e-3
    str_val = 'hello'
    bool_true = .true.
    bool_false = .false.
$end
"""
        result = StrParser.parse(content)
        para = result.sections["para"]

        assert para.parameters["int_val"] == 42
        assert isinstance(para.parameters["int_val"], int)

        assert para.parameters["float_val"] == pytest.approx(3.14)
        assert isinstance(para.parameters["float_val"], float)

        assert para.parameters["sci_val"] == pytest.approx(1.5e-3)

        assert para.parameters["str_val"] == "hello"

        assert para.parameters["bool_true"] is True
        assert para.parameters["bool_false"] is False

    def test_generate_roundtrip(self):
        """Test that parse -> generate produces valid output."""
        original = """$para
        idt = 300
        itanf = '2020-01-01'
$end
"""
        parsed = StrParser.parse(original)
        generated = StrParser.generate(parsed)

        # Re-parse the generated content
        reparsed = StrParser.parse(generated)

        assert reparsed.get_param("para", "idt") == 300
        # Quotes are stripped during parsing
        assert reparsed.get_param("para", "itanf") == "2020-01-01"

    def test_parse_real_file_content(self):
        """Test parsing content similar to real .str files."""
        content = """
#------------------------------------------------------------------------
# Test simulation
#------------------------------------------------------------------------

$title
        2D sim for testing
        test_sim
        GRID/test_grid
$end

$para
        itanf = '2009-01-01'    itend = '2009-01-05'
        idt = '300s'
        idtout = '3h'
        idtext = '300s'

        date = 20090101

        ilin = 1
        iwtype = 3     dragco = 2.5e-3
        ireib = 5      czdef = 2.5e-3
$end

$extra
        128     'sea boundary'
        58      'inlet'
$end

$name
        wind='INPUT/wind.txt'
$end
"""
        result = StrParser.parse(content)

        assert "title" in result.sections
        assert "para" in result.sections
        assert "extra" in result.sections
        assert "name" in result.sections

        # Check para section
        para = result.sections["para"]
        assert para.parameters["ilin"] == 1
        assert para.parameters["iwtype"] == 3
        assert para.parameters["dragco"] == pytest.approx(2.5e-3)

        # Check extra section
        extra = result.sections["extra"]
        assert "_standalone" in extra.parameters
        assert len(extra.parameters["_standalone"]) == 2


class TestStrParserEdgeCases:
    """Tests for error handling and edge cases."""

    def test_parse_missing_end(self):
        """Section without $end should still parse (unclosed section)."""
        content = """
$para
    idt = 300
"""
        result = StrParser.parse(content)
        assert "para" in result.sections
        assert result.get_param("para", "idt") == 300

    def test_parse_empty_content(self):
        """Empty string should parse to empty StrFile."""
        result = StrParser.parse("")
        assert len(result.sections) == 0

    def test_parse_only_comments(self):
        """Content with only comments and no sections."""
        content = """
# This is a comment
! Another comment
# No sections here
"""
        result = StrParser.parse(content)
        assert len(result.sections) == 0
        assert len(result.header_comments) >= 1

    def test_parse_duplicate_section_names(self):
        """Later section with same name should overwrite earlier one."""
        content = """
$para
    idt = 300
$end
$para
    idt = 600
$end
"""
        result = StrParser.parse(content)
        # Latest wins
        assert result.get_param("para", "idt") == 600

    def test_parse_case_insensitive_section_names(self):
        """Section names should be case-insensitive."""
        content = """
$PARA
    idt = 300
$END
"""
        result = StrParser.parse(content)
        assert "para" in result.sections
        assert result.get_param("para", "idt") == 300

    def test_parse_double_quoted_string(self):
        """Test parsing double-quoted string values."""
        content = """
$name
    wind = "INPUT/wind.txt"
$end
"""
        result = StrParser.parse(content)
        assert result.get_param("name", "wind") == "INPUT/wind.txt"

    def test_parse_negative_values(self):
        """Test parsing negative numbers."""
        content = """
$para
    intval = -5
    floatval = -3.14
    scival = -1.5e-3
$end
"""
        result = StrParser.parse(content)
        para = result.sections["para"]
        assert para.parameters["intval"] == -5
        assert para.parameters["floatval"] == pytest.approx(-3.14)
        assert para.parameters["scival"] == pytest.approx(-1.5e-3)

    def test_parse_exclamation_comments(self):
        """Test Fortran-style ! comments within sections."""
        content = """
$para
    ! This is a Fortran comment
    idt = 300
$end
"""
        result = StrParser.parse(content)
        assert result.get_param("para", "idt") == 300
        assert len(result.sections["para"].comments) >= 1

    def test_parse_file_roundtrip(self, tmp_path):
        """Test parse_file and save round-trip via disk."""
        content = """$para
        idt = 300
        itanf = '2020-01-01'
$end
"""
        f = tmp_path / "test.str"
        f.write_text(content)

        parsed = StrParser.parse_file(f)
        assert parsed.file_path == f
        assert parsed.get_param("para", "idt") == 300

        out = tmp_path / "out.str"
        StrParser.save(parsed, out)
        reparsed = StrParser.parse_file(out)
        assert reparsed.get_param("para", "idt") == 300


class TestStrFileStructure:
    """Tests for _structure preservation and _modified_params tracking."""

    def test_structure_order_preserved(self):
        """Test that _structure records inter-section content."""
        content = """# Header
$para
    idt = 300
$end

# Inter-section comment

$name
    wind = 'test'
$end
"""
        result = StrParser.parse(content)
        # Should have structure entries for sections and inter-section content
        section_entries = [v for t, v in result._structure if t == "section"]
        assert "para" in section_entries
        assert "name" in section_entries

    def test_modified_params_tracked(self):
        """Test that set_param tracks modifications."""
        str_file = StrFile()
        str_file.set_param("para", "idt", 300)
        assert "idt" in str_file.sections["para"]._modified_params

    def test_generate_with_modification_overlay(self):
        """Test that generate overlays modified params on raw lines."""
        content = """$para
        idt = 300
        itanf = '2020-01-01'
$end
"""
        parsed = StrParser.parse(content)
        parsed.set_param("para", "idt", 600)

        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("para", "idt") == 600
        # Unmodified param preserved
        assert reparsed.get_param("para", "itanf") == "2020-01-01"

    def test_generate_new_section(self):
        """Test generating a new section from scratch."""
        str_file = StrFile()
        str_file.set_param("para", "idt", 300)
        str_file.set_param("para", "ilin", 1)

        generated = StrParser.generate(str_file)
        assert "$para" in generated
        assert "$end" in generated
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("para", "idt") == 300

    def test_format_value_bool(self):
        """Test _format_value for booleans."""
        assert StrParser._format_value(True) == ".true."
        assert StrParser._format_value(False) == ".false."

    def test_format_value_scientific(self):
        """Test _format_value for small floats."""
        result = StrParser._format_value(2.5e-5)
        assert "e" in result.lower()

    def test_format_value_string_with_spaces(self):
        """Test _format_value for strings with spaces."""
        result = StrParser._format_value("hello world")
        assert result.startswith("'") and result.endswith("'")

    def test_get_section_names(self):
        """Test get_section_names returns all sections."""
        content = """
$para
    idt = 300
$end
$name
    wind = 'test'
$end
"""
        result = StrParser.parse(content)
        names = result.get_section_names()
        assert "para" in names
        assert "name" in names


class TestCommonParams:
    """Tests for COMMON_PARAMS database and get_param_info."""

    def test_common_params_has_para_section(self):
        """Test that COMMON_PARAMS contains $para section."""
        assert "para" in COMMON_PARAMS

    def test_common_params_has_key_params(self):
        """Test that key parameters are defined."""
        assert "itanf" in COMMON_PARAMS["para"]
        assert "itend" in COMMON_PARAMS["para"]
        assert "idt" in COMMON_PARAMS["para"]

    def test_param_info_tuple_structure(self):
        """Test that each param info is a 5-tuple."""
        info = COMMON_PARAMS["para"]["idt"]
        assert len(info) == 5
        desc, ptype, default, units, options = info
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_get_param_info_found(self):
        """Test get_param_info for known parameter."""
        info = get_param_info("idt")
        assert info is not None
        assert len(info) == 5

    def test_get_param_info_with_section(self):
        """Test get_param_info with explicit section."""
        info = get_param_info("idt", section="para")
        assert info is not None

    def test_get_param_info_not_found(self):
        """Test get_param_info for unknown parameter."""
        info = get_param_info("nonexistent_param_xyz")
        assert info is None

    def test_get_param_info_wrong_section_falls_back(self):
        """Test get_param_info with wrong section falls back to all sections."""
        # When the given section doesn't exist, get_param_info searches all sections
        info = get_param_info("idt", section="nonexistent_section")
        # Falls back to global search, finds idt in "para"
        assert info is not None

    def test_get_param_info_section_scoped(self):
        """Test get_param_info returns None when param not in specified section."""
        # "idt" is in "para", not in "name"
        info = get_param_info("idt", section="name")
        assert info is None

    def test_common_params_has_restart_params(self):
        """Restart and offline params are defined in $para."""
        for param in ("itrst", "itmrst", "ityrst", "idtoff", "itmoff"):
            assert param in COMMON_PARAMS["para"], f"Missing {param}"

    def test_common_params_has_wave_and_mercury(self):
        """Wave coupling and mercury params are defined in $para."""
        for param in ("iwave", "dtwave", "imerc"):
            assert param in COMMON_PARAMS["para"], f"Missing {param}"
