"""Tests for .str file parser."""

import pytest

from shyfem_ui.services.parser_str import (
    COMMON_PARAMS,
    COMMON_SECTIONS,
    StrFile,
    StrParser,
    format_param_display,
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
        """A repeated section keeps both blocks; lookups take the first.

        This previously asserted "latest wins", which described the bug
        rather than a requirement: the second block replaced the first in
        the name-keyed dict, so generate() emitted the survivor at both
        positions and destroyed the first block's content on save.
        """
        content = """
$para
    idt = 300
$end
$para
    idt = 600
$end
"""
        result = StrParser.parse(content)
        assert result.get_param("para", "idt") == 300
        # the repeat is not addressable by name — it lives in _structure —
        # but it is not lost either
        assert result.get_section_names() == ["para"]
        out = StrParser.generate(result)
        assert "idt = 300" in out and "idt = 600" in out

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
        section_entries = [v.name for t, v in result._structure if t == "section"]
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
    """Tests for COMMON_PARAMS database."""

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

    def test_common_params_has_imetout(self):
        """imetout meteo-output selector is registered in $para."""
        assert "imetout" in COMMON_PARAMS["para"]
        assert COMMON_PARAMS["para"]["imetout"][1] == "int"

    def test_parse_imetout(self):
        content = "$para\n    imetout = 10010\n$end\n"
        para = StrParser.parse(content).sections["para"].parameters
        assert para["imetout"] == 10010 and isinstance(para["imetout"], int)

    def test_common_params_has_beaching(self):
        """Eulerian beaching params are registered in $para."""
        for p in ("ibeach", "beachrate", "burryrate"):
            assert p in COMMON_PARAMS["para"], f"Missing {p} in $para"
        assert COMMON_PARAMS["para"]["ibeach"][1] == "int"
        assert COMMON_PARAMS["para"]["beachrate"][1] == "float"
        assert COMMON_PARAMS["para"]["burryrate"][1] == "float"

    def test_parse_beaching_params(self):
        """A $para block with ibeach=3 + rates parses to int/float."""
        content = "$para\n    ibeach = 3\n    beachrate = 0.3\n    burryrate = 0.1\n$end\n"
        para = StrParser.parse(content).sections["para"].parameters
        assert para["ibeach"] == 3 and isinstance(para["ibeach"], int)
        assert para["beachrate"] == pytest.approx(0.3)
        assert para["burryrate"] == pytest.approx(0.1)

    def test_common_params_has_restart_params(self):
        """Restart and offline params are defined in $para."""
        for param in ("itrst", "itmrst", "ityrst", "idtoff", "itmoff"):
            assert param in COMMON_PARAMS["para"], f"Missing {param}"

    def test_common_params_has_wave_and_mercury(self):
        """Wave coupling and mercury params are defined in $para."""
        for param in ("iwave", "dtwave", "imerc"):
            assert param in COMMON_PARAMS["para"], f"Missing {param}"

    def test_ireib_description_has_all_models(self):
        """ireib description lists all 11 friction models (0-10)."""
        desc = COMMON_PARAMS["para"]["ireib"][4]  # options field
        for keyword in ("Chezy", "Strickler", "roughness", "fluid mud", "hybrid"):
            assert keyword.lower() in desc.lower(), f"ireib missing {keyword}"

    def test_iheat_description_has_coare(self):
        """iheat description includes COARE algorithm."""
        desc = COMMON_PARAMS["para"]["iheat"][4]
        assert "COARE" in desc

    def test_ibarcl_description_has_nudging(self):
        """ibarcl description includes nudging and assimilation modes."""
        desc = COMMON_PARAMS["para"]["ibarcl"][4]
        assert "nudging" in desc.lower()

    def test_bound_ibtyp_has_radiation(self):
        """ibtyp description includes radiation boundary type."""
        desc = COMMON_PARAMS["bound"]["ibtyp"][4]
        assert "radiation" in desc.lower() or "31" in desc

    def test_common_params_name_has_ecology_files(self):
        """$name section has ecology input file entries."""
        for f in ("bioin", "biosin", "biocon", "biolight", "mercin", "bfmini"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_name_has_sediment_files(self):
        """$name section has sediment input file entries."""
        for f in ("sedp", "sedt", "sedcon"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_name_has_lagrangian_files(self):
        """$name section has lagrangian input file entries."""
        for f in ("lgrlin", "lgrtrj", "statcnn", "surfvel"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_name_has_scalar_boundary_files(self):
        """$name section has scalar boundary file entries."""
        for f in ("saltn", "tempn", "conzn"):
            assert f in COMMON_PARAMS["name"], f"Missing {f} in $name"

    def test_common_params_has_sedtr_section(self):
        """COMMON_PARAMS has $sedtr section with key params."""
        assert "sedtr" in COMMON_PARAMS
        for p in ("isedi", "sedgrs", "percin", "tauin", "sedhpar"):
            assert p in COMMON_PARAMS["sedtr"], f"Missing {p} in $sedtr"

    def test_common_params_has_lagrg_section(self):
        """COMMON_PARAMS has $lagrg section with key params."""
        assert "lagrg" in COMMON_PARAMS
        for p in ("ilagr", "nbdy", "nbdymax", "ioil", "ilarv", "lbeach", "ldecay"):
            assert p in COMMON_PARAMS["lagrg"], f"Missing {p} in $lagrg"

    def test_common_params_has_connec_section(self):
        """COMMON_PARAMS has $connec section."""
        assert "connec" in COMMON_PARAMS
        for p in ("icnn", "radcnn", "ppscnn", "pldcnn"):
            assert p in COMMON_PARAMS["connec"], f"Missing {p} in $connec"

    def test_common_params_has_bfmsc_section(self):
        """COMMON_PARAMS has $bfmsc section."""
        assert "bfmsc" in COMMON_PARAMS
        assert "ibfm" in COMMON_PARAMS["bfmsc"]

    def test_nduge_metadata_removed(self):
        """$nduge is a fiction of the old UI: no core code reads it and
        iostr.f90 hard-stops on unknown sections, so the UI must never
        recreate it via the dedicated-section save path."""
        assert "nduge" not in COMMON_PARAMS
        assert "nduge" not in COMMON_SECTIONS


class TestNewSectionRoundTrip:
    """Test that new sections can be parsed and re-generated."""

    def test_sedtr_roundtrip(self):
        content = """$sedtr
        isedi = 1
        sedgrs = '0.063 0.125 0.25 0.5'
        percin = '0.25 0.25 0.25 0.25'
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("sedtr", "isedi") == 1
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("sedtr", "isedi") == 1

    def test_lagrg_roundtrip(self):
        content = """$lagrg
        ilagr = 2
        nbdy = 100
        ioil = 1
        lbeach = 0.5
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("lagrg", "ilagr") == 2
        assert parsed.get_param("lagrg", "ioil") == 1
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("lagrg", "ilagr") == 2

    def test_nduge_roundtrip(self):
        content = """$nduge
        nvars = 3
        ttau = 3600
        sigma = 5000
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("nduge", "nvars") == 3
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("nduge", "nvars") == 3

    def test_assimil_numbered_sections_parse_distinct(self):
        content = (
            "$assimil1\n"
            "        nobs = 2\n"
            "        ivar = 12\n"
            "        corlength = 2000.\n"
            "$end\n"
            "\n"
            "$assimil2\n"
            "        nobs = 1\n"
            "        ivar = 11\n"
            "$end\n"
        )
        parsed = StrParser.parse(content)
        assert parsed.get_param("assimil1", "ivar") == 12
        assert parsed.get_param("assimil2", "ivar") == 11
        assert parsed.get_param("assimil1", "nobs") == 2

    def test_assimil_section_roundtrips_verbatim_when_unmodified(self):
        line = "        corlength = 2000. 3000."  # per-station array form
        content = f"$assimil1\n        nobs = 2\n        ivar = 12\n{line}\n$end\n"
        out = StrParser.generate(StrParser.parse(content))
        assert line in out.splitlines()
        # spec test 3: untouched load -> save is byte-identical. Single
        # section only: the generator's inter-section blank-line handling
        # precludes multi-section byte-identity, so per-section is the
        # guarantee.
        assert out == content

    def test_multi_assign_line_overlay_targets_correct_param_by_span(self):
        """A first-occurrence substring replace mis-targets a param whose
        name is a suffix of an earlier key on the same multi-assign line
        (``vcorlength`` contains ``corlength``): modifying ``corlength``
        must not clobber ``vcorlength``'s value."""
        content = (
            "$assimil1\n"
            "        nobs = 1\n"
            "        ivar = 12\n"
            "        vcorlength = 2000.  corlength = 2000.\n"
            "$end\n"
        )
        parsed = StrParser.parse(content)
        parsed.set_param("assimil1", "corlength", 999.0)
        out = StrParser.generate(parsed)
        assert "vcorlength = 2000." in out
        assert "corlength = 999.0" in out
        assert "vcorlength = 999.0" not in out

    def test_multi_section_str_with_new_sections(self):
        """Full STR with multiple new sections parses correctly."""
        content = """$para
        idt = 300
        ilagr = 2
$end
$lagrg
        ilagr = 2
        nbdy = 100
        idtl = 3600
$end
$sedtr
        isedi = 1
$end
"""
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "idt") == 300
        assert parsed.get_param("lagrg", "nbdy") == 100
        assert parsed.get_param("sedtr", "isedi") == 1


class TestNoPhantomEndSection:
    """A bare '$end' line must only close the current section, never be
    parsed as a NEW section named 'end'.

    Found while wiring N42 (run.py restart selection): SECTION_START's
    ``\\$(\\w+)`` regex matches "$end" too (the word "end" is a valid
    \\w+), and the parser checked SECTION_START before SECTION_END -- so
    every legitimate closing "$end" was ALSO recorded as a phantom section
    literally named "end" in both sections{} and _structure. generate()
    then re-emitted each phantom as its own extra "$end" pair, so every
    STR this codebase writes via StrParser.generate()/save() (ensemble.py's
    per-combo runs, physics.py's save_file, simulation.py's save, and this
    task's write_restart_str) carried a stray, ownerless "$end" between
    every pair of real sections.

    That is not cosmetic: SHYFEM's actual Fortran STR reader
    (src/shyfem/iostr.f90, subroutine nlsh2d) is NOT tolerant of it --
    encountering "$end" where it expects the next section header is a
    hard ``stop 'error stop : nlsh2d'`` (see the `section.eq.'end'` branch
    there). Any consumer that fed a generate()-round-tripped STR to the
    real binary would have crashed on startup, before ever reaching
    whatever section (e.g. $name/restrt) came after the phantom.
    """

    def test_end_marker_is_not_recorded_as_a_section(self):
        content = "$title\n        test\n$end\n$para\n        idt = 300\n$end\n"
        parsed = StrParser.parse(content)

        assert "end" not in parsed.sections
        assert set(parsed.sections.keys()) == {"title", "para"}

    def test_end_marker_is_not_recorded_in_structure(self):
        content = "$title\n        test\n$end\n$para\n        idt = 300\n$end\n"
        parsed = StrParser.parse(content)

        section_names = [sec.name for kind, sec in parsed._structure if kind == "section"]
        assert section_names == ["title", "para"]

    def test_generated_output_has_exactly_one_end_per_section(self):
        content = "$title\n        test\n$end\n$para\n        idt = 300\n$end\n"
        parsed = StrParser.parse(content)
        generated = StrParser.generate(parsed)

        assert generated.count("$end") == 2

    def test_generated_output_has_no_ownerless_end_between_sections(self):
        """A section header must always follow directly after the previous
        section's $end (aside from blank/comment lines) -- never another
        bare $end, which is what a phantom 'end' section would emit."""
        content = "$title\n        test\n$end\n$para\n        idt = 300\n$end\n"
        parsed = StrParser.parse(content)
        generated = StrParser.generate(parsed)

        lines = [ln for ln in generated.splitlines() if ln.strip()]
        end_positions = [i for i, ln in enumerate(lines) if ln.strip() == "$end"]
        assert len(end_positions) == 2
        for pos in end_positions:
            if pos + 1 < len(lines):
                assert lines[pos + 1].strip().startswith("$") and not lines[
                    pos + 1
                ].strip().startswith("$end"), (
                    f"line after $end at index {pos} is {lines[pos + 1]!r} -- "
                    "looks like a phantom 'end' section, not a real next section"
                )

    def test_regenerated_real_mar_menor_str_has_no_phantom_end(self, tmp_path):
        """End-to-end guard using an actual shipped testcase STR file."""
        from pathlib import Path

        real_str = (
            Path(__file__).parent.parent.parent
            / "testcases"
            / "examples"
            / "mar_menor"
            / "mm_hyd_00.str"
        )
        if not real_str.exists():
            pytest.skip("testcases/examples/mar_menor/mm_hyd_00.str not present")

        parsed = StrParser.parse_file(real_str)
        assert "end" not in parsed.sections

        generated = StrParser.generate(parsed)
        # One $end per real section, none dangling as their own section.
        assert generated.count("$end") == len([n for k, n in parsed._structure if k == "section"])


class TestTrailingCommentsAreNotCode:
    """The core stops reading a line at the first ``!``/``#`` that is not
    inside a quoted value (nls.f90 nls_skip_whitespace_on_line). Matching
    ``key = value`` inside the comment made the UI display a value the core
    never uses, and — worse — made an overlay save rewrite the *comment*
    and mark the param emitted, so the user's real edit never reached the
    file and the run silently used the core default."""

    def test_param_named_only_in_a_comment_is_not_parsed(self):
        parsed = StrParser.parse("$para\n        idt = 300  ! tau = 1800\n$end\n")
        assert parsed.sections["para"].parameters == {"idt": 300}

    def test_commented_out_older_value_does_not_shadow_the_live_one(self):
        parsed = StrParser.parse("$para\n        tau = 3600  ! was tau = 1800\n$end\n")
        assert parsed.get_param("para", "tau") == 3600

    def test_editing_a_param_named_in_a_comment_emits_a_real_assignment(self):
        parsed = StrParser.parse("$para\n        idt = 300  ! tau = 1800\n$end\n")
        parsed.set_param("para", "tau", 7200)
        lines = StrParser.generate(parsed).splitlines()
        assert "        idt = 300  ! tau = 1800" in lines
        assert "        tau = 7200" in lines

    def test_comment_survives_verbatim_when_a_code_param_changes(self):
        parsed = StrParser.parse("$para\n        idt = 300  ! tau = 1800\n$end\n")
        parsed.set_param("para", "idt", 600)
        assert "        idt = 600  ! tau = 1800" in StrParser.generate(parsed).splitlines()

    def test_quoted_comment_char_is_part_of_the_value(self):
        content = "$name\n        wind = 'IN!PUT/w#nd.txt'  ! forcing\n$end\n"
        parsed = StrParser.parse(content)
        assert parsed.get_param("name", "wind") == "IN!PUT/w#nd.txt"
        parsed.set_param("name", "rain", "rain.txt")
        lines = StrParser.generate(parsed).splitlines()
        assert "        wind = 'IN!PUT/w#nd.txt'  ! forcing" in lines

    def test_hash_comment_is_stripped_like_bang(self):
        parsed = StrParser.parse("$para\n        idt = 300  # tau = 1800\n$end\n")
        assert parsed.sections["para"].parameters == {"idt": 300}

    def test_comment_only_lines_are_untouched_by_an_overlay(self):
        content = "$para\n! header note\n        idt = 300\n# tau = 1800\n$end\n"
        parsed = StrParser.parse(content)
        parsed.set_param("para", "idt", 600)
        lines = StrParser.generate(parsed).splitlines()
        assert "! header note" in lines
        assert "# tau = 1800" in lines

    def test_unmodified_section_with_comments_roundtrips_byte_identically(self):
        content = (
            "$para\n"
            "        idt = 300  ! tau = 1800\n"
            "! standalone note\n"
            "        itanf = '2020-01-01'\n"
            "$end\n"
        )
        assert StrParser.generate(StrParser.parse(content)) == content

    def test_overlay_leaves_every_other_line_byte_identical(self):
        content = (
            "$para\n"
            "        idt = 300  ! tau = 1800\n"
            "        itanf = '2020-01-01'   # start\n"
            "$end\n"
        )
        parsed = StrParser.parse(content)
        parsed.set_param("para", "idt", 600)
        out = StrParser.generate(parsed)
        assert out == content.replace("idt = 300", "idt = 600")

    def test_labelled_standalone_node_survives(self):
        # $extra/$flux/$volume node lists routinely carry a trailing label.
        content = "$extra\n        128     'sea boundary'  ! main inlet\n$end\n"
        parsed = StrParser.parse(content)
        assert parsed.get_param("extra", "_standalone") == [
            {"id": 128, "description": "sea boundary"}
        ]
        assert StrParser.generate(parsed) == content
        parsed.set_param("extra", "idtext", 300)
        assert "        128     'sea boundary'  ! main inlet" in (
            StrParser.generate(parsed).splitlines()
        )


class TestOwnerlessEndPreserved:
    """A ``$end`` with no section open must survive regeneration: dropping it
    leaves the STR with an unterminated block, which the core's reader
    (iostr.f90 nlsh2d) hard-stops on.

    Until issue #86 this class also documented a decorated header
    (``$nduge  ! legacy nudging``) NOT being a section -- that was the bug,
    not the contract: SHYFEM's reader takes the text after a section name as
    a documented ``extra`` field (nls.f90::nls_is_section), so such a header
    opens section ``nduge`` there. Recognising it is also what lets the app's
    core-fatal-``$nduge`` purge find a decorated one. The round-trip and
    ``$end``-count guarantees below are unchanged and still the point.
    """

    DECORATED = (
        "$title\n"
        "        test\n"
        "$end\n"
        "\n"
        "$nduge  ! legacy nudging\n"
        "        nduge = 1\n"
        "$end\n"
        "\n"
        "$para\n"
        "        idt = 300\n"
        "$end\n"
    )

    def test_decorated_block_roundtrips_every_line(self):
        out = StrParser.generate(StrParser.parse(self.DECORATED))
        assert [ln for ln in out.splitlines() if ln.strip()] == [
            ln for ln in self.DECORATED.splitlines() if ln.strip()
        ]

    def test_decorated_header_is_a_section(self):
        """Reversed by issue #86 -- see the class docstring."""
        parsed = StrParser.parse(self.DECORATED)
        assert set(parsed.sections) == {"title", "nduge", "para"}
        assert parsed.sections["nduge"].header_extra == "! legacy nudging"
        assert parsed.get_param("nduge", "nduge") == 1

    def test_a_truly_ownerless_end_is_still_preserved(self):
        """The guarantee this class exists for, with no decorated header in
        sight: a stray ``$end`` that never had an opener."""
        text = "$title\n        test\n$end\n\n$end\n\n$para\n        idt = 300\n$end\n"
        out = StrParser.generate(StrParser.parse(text))
        assert out == text
        assert [ln for ln in out.splitlines() if ln.strip() == "$end"] == ["$end"] * 3

    def test_end_count_survives_regeneration(self):
        out = StrParser.generate(StrParser.parse(self.DECORATED))
        assert [ln for ln in out.splitlines() if ln.strip() == "$end"] == ["$end"] * 3


class TestFormatValueQuoting:
    """Bare (unquoted) non-numeric strings must be quoted on emit: the
    core's reader hard-stops on an unquoted character value (nls.f90
    'no value found'), so `wind = INPUT/wind.txt` is fatal. Before this
    rule, a no-op save of the Input Files panel stripped the quotes from
    every dash-less filename and broke the STR."""

    def test_bare_filename_is_quoted(self):
        assert StrParser._format_value("INPUT/wind.txt") == "'INPUT/wind.txt'"

    def test_prequoted_not_double_wrapped(self):
        assert StrParser._format_value("'obs.dat'") == "'obs.dat'"
        assert StrParser._format_value('"obs.dat"') == '"obs.dat"'

    def test_numeric_strings_stay_bare(self):
        # These are numbers to the Fortran reader (incl. d-exponents);
        # quoting them would turn a numeric param into a character one.
        for s in ("5", "-5", "0.5", "1e-3", "1.5E+6", "1.d-3", ".5"):
            assert StrParser._format_value(s) == s, s

    def test_fortran_logicals_stay_bare(self):
        assert StrParser._format_value(".true.") == ".true."
        assert StrParser._format_value(".False.") == ".False."

    def test_apostrophe_value_uses_double_quotes(self):
        # nls.f90 accepts '..' and ".." — a value containing an apostrophe
        # must switch delimiter, not emit an unbalanced quote.
        assert StrParser._format_value("O'Brien.dat") == '"O\'Brien.dat"'

    def test_name_section_roundtrip_keeps_quotes(self):
        # The physics Input Files panel reads back the (unquoted) display
        # value of every rendered field and re-sets it on save; that
        # unmodified round-trip must not strip the quotes the core needs.
        content = "$name\n        wind = 'INPUT/wind.txt'\n$end\n"
        sf = StrParser.parse(content)
        sf.set_param("name", "wind", sf.get_param("name", "wind"))
        out = StrParser.generate(sf)
        assert "wind = 'INPUT/wind.txt'" in out

    def test_value_with_both_quote_chars_is_rejected(self):
        # nls.f90's reader is delimiter-matched with no escape mechanism:
        # a value holding both quote characters has no valid emission, so
        # wrapping it in either one ships an unbalanced, fatal STR line.
        with pytest.raises(ValueError):
            StrParser._format_value("a'b\"c")

    def test_prequoted_value_containing_the_other_quote_still_passes(self):
        assert StrParser._format_value('"a\'b"') == '"a\'b"'
        assert StrParser._format_value("'a\"b'") == "'a\"b'"


class TestFormatValuePrecision:
    """``_format_value`` must emit a form that ``float()`` reads back
    exactly. A fixed-precision ``%.2e`` rewrote e.g. ``tau = 1234567.``
    (11.5 days, a plausible nudging relaxation time) as ``1.23e+06`` --
    a 0.4% change to a value the user never edited."""

    @pytest.mark.parametrize("value", [1234567.0, 1e-5, 0.1, 1e7, 1234567.891, 9.87654321e-7])
    def test_float_roundtrips_exactly(self, value):
        assert float(StrParser._format_value(value)) == value

    def test_large_float_is_not_truncated_on_save(self):
        content = "$para\n        idt = 300\n$end\n"
        parsed = StrParser.parse(content)
        parsed.set_param("para", "tau", 1234567.0)
        assert StrParser.parse(StrParser.generate(parsed)).get_param("para", "tau") == 1234567.0


class TestDuplicateSectionNames:
    """A .str file may repeat a section: the core's reader dispatches in a
    loop (subnsa.f90 nrdsec), so two $color blocks are two color tables.
    Keying sections by name alone made the second overwrite the first, and
    since _structure recorded the name twice, generate() emitted the
    survivor at both positions — silently destroying the first block's
    content on save. 7 of the repo's 64 .str files repeat a section.
    """

    _TWO = (
        "$para\n        itanf = 0\n$end\n\n"
        "$color\n        x0col = 0.05\n        colfil = 'first.dat'\n$end\n\n"
        "$color\n        icolor = 1\n        colfil = 'second.dat'\n$end\n"
    )

    def test_both_blocks_survive_generation(self):
        out = StrParser.generate(StrParser.parse(self._TWO))
        assert "first.dat" in out, "the first block must not be destroyed"
        assert "second.dat" in out
        assert out.count("$color") == 2

    def test_no_content_is_duplicated(self):
        out = StrParser.generate(StrParser.parse(self._TWO))
        assert out.count("first.dat") == 1
        assert out.count("second.dat") == 1

    def test_every_non_blank_line_round_trips(self):
        want = [ln for ln in self._TWO.splitlines() if ln.strip()]
        got = [
            ln for ln in StrParser.generate(StrParser.parse(self._TWO)).splitlines() if ln.strip()
        ]
        assert got == want

    def test_round_trip_is_stable_across_two_saves(self):
        # A save->reload->save cycle must not shift content again: the keys
        # a reparse derives have to match the ones the first parse used.
        # Compared on non-blank lines because generate() adds a blank line
        # per section on every pass — a separate pre-existing defect that
        # affects files with no repeated sections at all.
        once = StrParser.generate(StrParser.parse(self._TWO))
        twice = StrParser.generate(StrParser.parse(once))
        assert [ln for ln in twice.splitlines() if ln.strip()] == [
            ln for ln in once.splitlines() if ln.strip()
        ]

    def test_repeats_never_enter_the_name_space(self):
        # The dict keys are treated as real section names across the app
        # (Shiny input ids, COMMON_PARAMS lookups, emitted headers), so a
        # repeat must not invent one: it is reachable through _structure.
        sf = StrParser.parse(self._TWO)
        assert sf.get_section_names() == ["para", "color"]
        assert all(name.isidentifier() for name in sf.get_section_names())
        blocks = [s for kind, s in sf._structure if kind == "section"]
        assert [s.name for s in blocks] == ["para", "color", "color"]

    def test_structure_is_stable_across_a_reload(self):
        sf = StrParser.parse(self._TWO)
        reloaded = StrParser.parse(StrParser.generate(sf))
        assert reloaded.get_section_names() == sf.get_section_names()
        assert reloaded.get_param("color", "colfil") == "first.dat"

    def test_lookup_resolves_to_the_first_occurrence(self):
        sf = StrParser.parse(self._TWO)
        assert sf.get_param("color", "colfil") == "first.dat"
        assert sf.get_param("color", "x0col") == 0.05

    def test_set_param_edits_the_first_occurrence_only(self):
        sf = StrParser.parse(self._TWO)
        sf.set_param("color", "colfil", "'edited.dat'")
        out = StrParser.generate(sf)
        assert "edited.dat" in out
        assert "second.dat" in out, "the later block must be untouched"
        assert "first.dat" not in out

    def test_three_occurrences_all_survive(self):
        text = self._TWO + "\n$color\n        colfil = 'third.dat'\n$end\n"
        out = StrParser.generate(StrParser.parse(text))
        for expected in ("first.dat", "second.dat", "third.dat"):
            assert out.count(expected) == 1, expected
        assert out.count("$color") == 3

    def test_apnbath_preserves_every_line(self):
        # The real file that exposed this: 2 bare $color headers.
        from pathlib import Path

        path = (
            Path(__file__).parent.parent.parent
            / "testcases"
            / "examples"
            / "mar_menor"
            / "apnbath.str"
        )
        if not path.exists():
            pytest.skip("testcases/examples/mar_menor/apnbath.str not present")
        want = [ln.rstrip() for ln in path.read_text().splitlines() if ln.strip()]
        got = [
            ln.rstrip()
            for ln in StrParser.generate(StrParser.parse_file(path)).splitlines()
            if ln.strip()
        ]
        assert got == want


# A verbatim excerpt of the real Curonian 29-box STR (curonian29_1993_2016.str),
# the configuration behind the box-model runs. Every construct below appears in
# that file; the parser dropped 7 of its 11 sections before issue #86 was fixed.
# Kept as a string (not a repo asset) so CI exercises it, matching the precedent
# in tests/test_boxmodel_setup.py::CURONIAN_EXCERPT.
CURONIAN_STR = """************************ SECTION TITLE **********************
 - set simulation title and grid name

$title
        Curonian 29-box, 2d, 1993-2016 continuous
        curonian29
\tcuronian29
$end

************************ SECTION PARA **********************
 - set parameter for the simulation

 -----\tthe starting time of the input files is 1/1/1997 = 0
 itanf  = 347068800\t itend  = 536450400\tidt = 300\t--> 2008-2013

&para
        itanf  = '1993-01-01'   itend  = '2016-12-31'\tidt = '5m'
\tidtbox = '1h'\t\t!box output -- the deliverable
        date   = 19930101   time   = 000000
        ireib  = 5\tczdef  = 0.0025
\tnomp   = 4
&end
\tnsigma = 12

************************ SECTION BOUND **********************
 - set open boundary conditions

$bound1     ---- Baltic sea ---- raw CMEMS sla, NOT rescaled
       kbound  = 1547 1548 1549 1550
                 1554 1555
\tibtyp  = 1
\tboundn = 'fem_forcing/sea_level.fem'
$end

$bound2     ---- Nemunas (Silininkai) river ---- discharge in m3/s
      kbound = 1855 1856 1882 1883
      zfact  = 0.25
      ibtyp  = 3
      boundn = 'fem_forcing/nemunas.txt'
      temp   = -999
$end

levels
      1 2 3 4 5 6 7 8 9 10 11 13 15 18 25 35
end

$name
      !gotmpa = ''\t\t!not needed: iturb = 0 (2-d run)
      wind = 'fem_forcing/wind.fem'
$end

$extra
        1823 'Klaipeda'
        1657 'Juodkrante'
$end
"""


class TestAmpersandSections:
    """SHYFEM's reader takes '&' or '$' for both openers and 'end'
    (nls.f90::nls_is_section: `if( c .ne. '&' .and. c .ne. '$' ) return`,
    and `if( section == 'end' ) return` regardless of which opened it), so
    the parser must too. The whole &para block of every real Curonian STR
    was dropped before this.
    """

    def test_ampersand_section_is_parsed(self):
        parsed = StrParser.parse("&para\n  idt = 300\n&end\n")
        assert "para" in parsed.sections
        assert parsed.get_param("para", "idt") == 300

    def test_markers_need_not_pair(self):
        for text in ("&para\n  idt = 300\n$end\n", "$para\n  idt = 300\n&end\n"):
            parsed = StrParser.parse(text)
            assert parsed.get_param("para", "idt") == 300, text

    def test_original_markers_round_trip(self):
        text = "&para\n  idt = 300\n&end\n"
        assert StrParser.generate(StrParser.parse(text)) == text

    def test_a_bare_end_is_not_a_section_end(self):
        """`levels … end` blocks sit outside sections; a bare `end` must not
        close anything, or the block's contents leak into the section above."""
        parsed = StrParser.parse("$para\n  idt = 300\n$end\n\nlevels\n 1 2 3\nend\n")
        assert parsed.get_param("para", "idt") == 300
        assert "levels" not in parsed.sections


class TestDecoratedHeaders:
    """`$bound1     ---- Baltic sea ----` is a section, not prose: the
    Fortran reader reads the trailing text as a documented field
    (`nls_is_section(section, num, extra)`). All five Curonian boundaries
    were dropped before this."""

    def test_decorated_header_is_a_section(self):
        parsed = StrParser.parse("$bound1     ---- Baltic sea ---- raw sla\n  ibtyp = 1\n$end\n")
        assert "bound1" in parsed.sections
        assert parsed.get_param("bound1", "ibtyp") == 1

    def test_trailing_text_is_available_and_round_trips_verbatim(self):
        text = "$bound1     ---- Baltic sea ---- raw sla\n  ibtyp = 1\n$end\n"
        parsed = StrParser.parse(text)
        assert parsed.sections["bound1"].header_extra == "---- Baltic sea ---- raw sla"
        assert StrParser.generate(parsed) == text

    def test_a_decorated_header_survives_a_parameter_edit(self):
        text = "$bound1     ---- Baltic sea ----\n  ibtyp = 1\n$end\n"
        parsed = StrParser.parse(text)
        parsed.set_param("bound1", "ibtyp", 3)
        out = StrParser.generate(parsed)
        assert "$bound1     ---- Baltic sea ----" in out
        assert "ibtyp = 3" in out


class TestListValues:
    """`kbound = 1855 1856 1882 1883` was silently truncated to `1855` --
    the most damaging of issue #86's four symptoms, because the value looked
    plausible. COMMON_PARAMS already types kbound as 'int_list'."""

    def test_space_separated_ints_become_a_list(self):
        parsed = StrParser.parse("$bound1\n  kbound = 1855 1856 1882 1883\n  ibtyp = 3\n$end\n")
        assert parsed.get_param("bound1", "kbound") == [1855, 1856, 1882, 1883]
        assert parsed.get_param("bound1", "ibtyp") == 3

    def test_space_separated_floats_become_a_list(self):
        parsed = StrParser.parse("$sedtr\n  sedgrs = 0.1 0.2 0.5\n$end\n")
        assert parsed.get_param("sedtr", "sedgrs") == [0.1, 0.2, 0.5]

    def test_a_single_value_is_still_a_scalar(self):
        parsed = StrParser.parse("$bound1\n  kbound = 1855\n$end\n")
        assert parsed.get_param("bound1", "kbound") == 1855

    def test_a_multi_pair_line_still_splits_into_scalars(self):
        """The guard that makes lists safe: a bare token followed by '=' opens
        a new pair and must never be swallowed into the previous list."""
        parsed = StrParser.parse(
            "&para\n  itanf = '1993-01-01'   itend = '2016-12-31'\tidt = '5m'\n&end\n"
        )
        assert parsed.get_param("para", "itanf") == "1993-01-01"
        assert parsed.get_param("para", "itend") == "2016-12-31"
        assert parsed.get_param("para", "idt") == "5m"

    def test_bare_pairs_on_one_line_do_not_merge(self):
        parsed = StrParser.parse("&para\n  ireib  = 5\tczdef  = 0.0025\n&end\n")
        assert parsed.get_param("para", "ireib") == 5
        assert parsed.get_param("para", "czdef") == 0.0025

    def test_continuation_lines_extend_the_list(self):
        parsed = StrParser.parse(
            "$bound1\n  kbound = 1547 1548 1549\n           1554 1555\n  ibtyp = 1\n$end\n"
        )
        assert parsed.get_param("bound1", "kbound") == [1547, 1548, 1549, 1554, 1555]
        assert parsed.get_param("bound1", "ibtyp") == 1

    def test_a_list_formats_space_separated_not_as_a_python_repr(self):
        """The fatal path: `[1, 2, 3]` in an STR makes the core hard-stop."""
        assert StrParser._format_value([1855, 1856]) == "1855 1856"
        assert StrParser._format_value([0.1, 0.25]) == "0.1 0.25"

    def test_a_modified_single_line_list_saves_space_separated(self):
        parsed = StrParser.parse("$bound1\n  kbound = 1855 1856\n$end\n")
        parsed.set_param("bound1", "kbound", [1855, 1856, 9])
        out = StrParser.generate(parsed)
        assert "kbound = 1855 1856 9" in out
        assert "[" not in out

    def test_a_modified_multi_line_list_collapses_to_one_line(self):
        """Not byte-identical by design: the overlay writer rewrites a param
        within one line, so an edited multi-line list is emitted once and its
        continuation lines are dropped. The result must still be valid."""
        parsed = StrParser.parse(
            "$bound1\n  kbound = 1547 1548\n           1554\n  ibtyp = 1\n$end\n"
        )
        parsed.set_param("bound1", "kbound", [1, 2])
        out = StrParser.generate(parsed)
        assert "kbound = 1 2" in out
        assert "1554" not in out
        assert StrParser.parse(out).get_param("bound1", "kbound") == [1, 2]
        assert StrParser.parse(out).get_param("bound1", "ibtyp") == 1


class TestNoSpuriousBlankAfterEnd:
    """generate() appended a blank line after every `$end`, so a parsed file
    never round-tripped byte-exact. Harmless while only 4 of 11 sections
    parsed; once they all do, saving a real STR in the editor would insert a
    blank line throughout the user's file."""

    def test_a_parsed_section_gains_no_blank_line(self):
        text = "$para\n  idt = 300\n$end\n"
        assert StrParser.generate(StrParser.parse(text)) == text

    def test_two_sections_keep_their_original_separation(self):
        text = "$para\n  idt = 300\n$end\n\n$name\n  wind = 'w.fem'\n$end\n"
        assert StrParser.generate(StrParser.parse(text)) == text


class TestRealSTRRoundTrip:
    """The headline test: the real Curonian STR parses completely and comes
    back byte-identical."""

    def test_every_section_is_parsed(self):
        parsed = StrParser.parse(CURONIAN_STR)
        assert set(parsed.sections) == {"title", "para", "bound1", "bound2", "name", "extra"}

    def test_the_parameter_section_is_read_from_ampersand_para_only(self):
        """The prose above &para carries a decoy `itanf = 347068800`; it is
        outside any section and must not leak into the parameters."""
        parsed = StrParser.parse(CURONIAN_STR)
        assert parsed.get_param("para", "itanf") == "1993-01-01"
        assert parsed.get_param("para", "itend") == "2016-12-31"
        assert parsed.get_param("para", "idtbox") == "1h"
        assert parsed.get_param("para", "nomp") == 4

    def test_boundary_node_lists_are_complete(self):
        parsed = StrParser.parse(CURONIAN_STR)
        assert parsed.get_param("bound1", "kbound") == [1547, 1548, 1549, 1550, 1554, 1555]
        assert parsed.get_param("bound2", "kbound") == [1855, 1856, 1882, 1883]
        assert parsed.get_param("bound2", "zfact") == 0.25
        assert parsed.get_param("bound2", "boundn") == "fem_forcing/nemunas.txt"

    def test_standalone_rows_still_parse(self):
        parsed = StrParser.parse(CURONIAN_STR)
        rows = parsed.sections["extra"].parameters["_standalone"]
        assert [r["id"] for r in rows] == [1823, 1657]

    def test_round_trips_byte_exact(self):
        assert StrParser.generate(StrParser.parse(CURONIAN_STR)) == CURONIAN_STR

    def test_the_shipped_mar_menor_files_round_trip_byte_exact(self):
        from pathlib import Path

        base = Path(__file__).parent.parent.parent / "testcases" / "examples" / "mar_menor"
        if not base.is_dir():
            pytest.skip("testcases/examples/mar_menor not present")
        checked = 0
        for path in sorted(base.glob("*.str")):
            text = path.read_text()
            assert StrParser.generate(StrParser.parse(text)) == text, path.name
            checked += 1
        assert checked > 0

    def test_a_single_token_continuation_also_extends(self):
        """The case that slipped through first: one number on its own line.
        A value of one token is a scalar, but a continuation of one token is
        still a continuation."""
        parsed = StrParser.parse(
            "$bound1\n  kbound = 1547 1548\n           1554\n  ibtyp = 1\n$end\n"
        )
        assert parsed.get_param("bound1", "kbound") == [1547, 1548, 1554]
        assert parsed.get_param("bound1", "ibtyp") == 1

    def test_a_non_numeric_line_is_not_a_continuation(self):
        parsed = StrParser.parse("$name\n  wind = 'w.fem'\n  some prose here\n$end\n")
        assert parsed.get_param("name", "wind") == "w.fem"


class TestFormatParamDisplay:
    """The shared formatter the UI's render sites use for a parsed value.

    Two sites stringified a parameter with ``str()``, which turns a parsed
    list into ``"[1855, 1856]"`` -- shown to the user, and read straight back
    out of the field on save, where ``_format_value`` quotes it into a
    character value the core hard-stops on. One formatter, so the two sites
    cannot drift apart.
    """

    def test_an_int_list_renders_space_separated(self):
        assert format_param_display([1855, 1856, 1882, 1883]) == "1855 1856 1882 1883"

    def test_a_float_list_renders_space_separated(self):
        assert format_param_display([0.1, 0.25]) == "0.1 0.25"

    def test_a_python_repr_never_reaches_the_field(self):
        assert "[" not in format_param_display([1855, 1856])
        assert "," not in format_param_display([1855, 1856])

    def test_a_scalar_renders_as_itself_and_is_not_quoted(self):
        assert format_param_display(1855) == "1855"
        assert format_param_display(0.25) == "0.25"
        assert format_param_display("fem_forcing/nemunas.txt") == "fem_forcing/nemunas.txt"

    def test_a_missing_value_renders_empty(self):
        """An absent parameter must leave the field blank, not show "None"."""
        assert format_param_display(None) == ""

    def test_a_logical_renders_in_fortran_form(self):
        assert format_param_display(True) == ".true."
        assert format_param_display(False) == ".false."

    def test_what_the_field_shows_re_parses_to_the_same_list(self):
        """The round-trip guard: the displayed text is what a save writes back,
        so it has to be a value the parser reads as the very same list."""
        value = [1547, 1548, 1549, 1550, 1554, 1555]
        text = f"$bound1\n  kbound = {format_param_display(value)}\n$end\n"
        assert StrParser.parse(text).get_param("bound1", "kbound") == value
