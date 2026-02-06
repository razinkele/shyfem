"""Tests for .str file parser."""

import pytest
from shyfem_ui.services.parser_str import StrFile, StrParser


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
