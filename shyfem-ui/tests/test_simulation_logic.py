"""Tests for pure helpers extracted from pages/simulation.py."""

import pytest

from shyfem_ui.services.simulation_logic import (
    _quote_value,
    apply_quick_settings,
    generate_template,
)
from shyfem_ui.services.parser_str import StrFile

ALL_TEMPLATES = [
    "basic_2d",
    "basic_3d",
    "wind_driven",
    "tidal",
    "baroclinic",
    "eulerian_tracer",
    "lagrangian",
    "tidal_estuary",
    "sediment_transport",
    "water_quality",
    "storm_surge",
    "thermal",
    "ice_model",
    "oil_spill",
    "data_assimilation",
    "offline_tracer",
    "wave_coupled",
]


# ---------------------------------------------------------------------------
# generate_template
# ---------------------------------------------------------------------------


class TestGenerateTemplateBasic:

    @pytest.mark.parametrize("name", ALL_TEMPLATES)
    def test_known_template_returns_non_empty_str(self, name):
        out = generate_template(name)
        assert isinstance(out, str)
        assert len(out.strip()) > 50, f"template {name!r} suspiciously short: {len(out)} chars"

    @pytest.mark.parametrize("name", ALL_TEMPLATES)
    def test_known_template_has_title_and_para(self, name):
        out = generate_template(name)
        assert "$title" in out, f"{name!r} missing $title"
        assert "$para" in out, f"{name!r} missing $para"
        assert "$end" in out, f"{name!r} missing $end"

    def test_unknown_name_falls_back_to_basic_2d(self):
        """Unrecognised names must return the basic_2d fallback, not raise."""
        out = generate_template("totally_unknown_template_xyz")
        expected = generate_template("basic_2d")
        assert out == expected

    def test_empty_name_falls_back_to_basic_2d(self):
        out = generate_template("")
        expected = generate_template("basic_2d")
        assert out == expected

    def test_returns_distinct_content_per_template(self):
        """Two different templates must produce different bodies."""
        assert generate_template("basic_2d") != generate_template("baroclinic")
        assert generate_template("lagrangian") != generate_template("storm_surge")

    def test_all_templates_distinct(self):
        """Every template must produce a unique string (no accidental duplicates)."""
        bodies = [generate_template(n) for n in ALL_TEMPLATES]
        assert len(set(bodies)) == len(ALL_TEMPLATES), "duplicate template bodies found"


class TestGenerateTemplateContent:
    """Spot-check key params in selected templates."""

    def test_baroclinic_has_ibarcl(self):
        assert "ibarcl" in generate_template("baroclinic")

    def test_lagrangian_has_lagrg_section(self):
        assert "$lagrg" in generate_template("lagrangian")

    def test_oil_spill_has_ioil(self):
        assert "ioil" in generate_template("oil_spill")

    def test_storm_surge_has_wetting_drying(self):
        out = generate_template("storm_surge")
        assert "hzoff" in out
        assert "hzon" in out

    def test_water_quality_has_ibio(self):
        assert "ibio" in generate_template("water_quality")

    def test_offline_tracer_has_idtoff(self):
        assert "idtoff" in generate_template("offline_tracer")

    def test_wave_coupled_has_iwave(self):
        assert "iwave" in generate_template("wave_coupled")

    def test_ice_model_has_icemod(self):
        assert "icemod" in generate_template("ice_model")

    def test_data_assimilation_has_nduge(self):
        assert "$nduge" in generate_template("data_assimilation")

    def test_eulerian_tracer_has_iconz_and_iage(self):
        out = generate_template("eulerian_tracer")
        assert "iconz" in out
        assert "iage" in out

    def test_tidal_estuary_has_salinity_and_3d(self):
        out = generate_template("tidal_estuary")
        assert "isalt" in out
        assert "nlv" in out

    def test_thermal_has_levels_section(self):
        assert "$levels" in generate_template("thermal")


# ---------------------------------------------------------------------------
# _quote_value (private but tested directly — it's a pure function)
# ---------------------------------------------------------------------------


class TestQuoteValue:

    def test_plain_string_gets_quoted(self):
        assert _quote_value("2020-01-01") == "'2020-01-01'"

    def test_already_single_quoted_not_doubled(self):
        assert _quote_value("'2020-01-01'") == "'2020-01-01'"

    def test_already_double_quoted_converted(self):
        assert _quote_value('"2020-01-01"') == "'2020-01-01'"

    def test_strips_leading_trailing_whitespace(self):
        assert _quote_value("  300s  ") == "'300s'"

    def test_empty_string_stays_empty_quoted(self):
        assert _quote_value("") == "''"


# ---------------------------------------------------------------------------
# apply_quick_settings
# ---------------------------------------------------------------------------


class TestApplyQuickSettings:

    def test_none_input_creates_fresh_strfile(self):
        result = apply_quick_settings(None, start="2020-01-01")
        assert isinstance(result, StrFile)

    def test_none_input_sets_itanf(self):
        result = apply_quick_settings(None, start="2020-01-01")
        assert result.get_param("para", "itanf") == "'2020-01-01'"

    def test_all_four_params_applied(self):
        result = apply_quick_settings(
            None,
            start="2020-01-01",
            end="2020-12-31",
            dt="60s",
            output_int="1h",
        )
        assert result.get_param("para", "itanf") == "'2020-01-01'"
        assert result.get_param("para", "itend") == "'2020-12-31'"
        assert result.get_param("para", "idt") == "'60s'"
        assert result.get_param("para", "idtout") == "'1h'"

    def test_empty_strings_preserve_existing_param(self):
        sf = StrFile()
        sf.set_param("para", "itanf", "'2019-01-01'")
        result = apply_quick_settings(sf, start="", end="", dt="", output_int="")
        # Nothing should have been overwritten
        assert result.get_param("para", "itanf") == "'2019-01-01'"

    def test_empty_strings_do_not_create_params(self):
        result = apply_quick_settings(None, start="", end="", dt="", output_int="")
        assert result.get_param("para", "itanf") is None
        assert result.get_param("para", "itend") is None
        assert result.get_param("para", "idt") is None
        assert result.get_param("para", "idtout") is None

    def test_returns_same_strfile_object_when_provided(self):
        sf = StrFile()
        result = apply_quick_settings(sf, start="2020-01-01")
        assert result is sf

    def test_strips_and_re_quotes(self):
        """Pre-quoted values must not be double-quoted."""
        result = apply_quick_settings(None, start="'2020-01-01'")
        assert result.get_param("para", "itanf") == "'2020-01-01'"

    def test_partial_update_leaves_other_params_untouched(self):
        sf = StrFile()
        sf.set_param("para", "itend", "'2025-12-31'")
        sf.set_param("para", "idt", "'600s'")
        result = apply_quick_settings(sf, start="2020-01-01")
        # Only itanf was updated; the others remain
        assert result.get_param("para", "itend") == "'2025-12-31'"
        assert result.get_param("para", "idt") == "'600s'"
        assert result.get_param("para", "itanf") == "'2020-01-01'"

    def test_only_output_int_provided(self):
        result = apply_quick_settings(None, output_int="30m")
        assert result.get_param("para", "idtout") == "'30m'"
        assert result.get_param("para", "itanf") is None


class TestQuickSettingsRoundTrip:
    """apply_quick_settings -> generate -> parse must round-trip cleanly. The
    bug: values were pre-quoted by apply_quick_settings AND re-quoted by
    _format_value, emitting itanf = ''2020-01-01'' (double-quoted), which the
    parser then can't read — so the run the user just configured was broken."""

    def test_no_double_quoting_and_round_trips(self):
        from shyfem_ui.services.parser_str import StrParser

        sf = apply_quick_settings(None, start="2020-01-01", end="2020-12-31", dt="60s")
        text = StrParser.generate(sf)
        # No doubled quotes anywhere in the emitted .str
        assert "''" not in text, f"double-quoting present:\n{text}"
        # Parses back to usable raw values (parser strips the single quotes)
        reparsed = StrParser.parse(text)
        assert reparsed.get_param("para", "itanf") == "2020-01-01"
        assert reparsed.get_param("para", "itend") == "2020-12-31"
        assert reparsed.get_param("para", "idt") == "60s"
