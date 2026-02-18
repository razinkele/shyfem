"""Tests for STR template library."""

import pytest

from shyfem_ui.pages.simulation import generate_template
from shyfem_ui.services.parser_str import StrParser


ALL_TEMPLATES = [
    "basic_2d",
    "basic_3d",
    "wind_driven",
    "tidal",
    "baroclinic",
    "lagrangian",
    "tidal_estuary",
    "sediment_transport",
    "water_quality",
    "storm_surge",
]


class TestTemplatesParse:
    """Every template must parse without error and have required sections."""

    @pytest.mark.parametrize("name", ALL_TEMPLATES)
    def test_template_parses(self, name):
        content = generate_template(name)
        parsed = StrParser.parse(content)
        assert "title" in parsed.sections
        assert "para" in parsed.sections

    @pytest.mark.parametrize("name", ALL_TEMPLATES)
    def test_template_not_empty(self, name):
        content = generate_template(name)
        assert len(content.strip()) > 50


class TestWindDriven:
    """Enhanced wind_driven template has Coriolis and diffusion."""

    def test_has_coriolis(self):
        content = generate_template("wind_driven")
        assert "icor" in content

    def test_has_smagorinsky(self):
        content = generate_template("wind_driven")
        assert "idhtyp" in content


class TestTidalEstuary:
    """Tidal estuary template is 3D with salinity."""

    def test_has_3d_levels(self):
        content = generate_template("tidal_estuary")
        assert "nlv" in content

    def test_has_salinity(self):
        content = generate_template("tidal_estuary")
        assert "isalt" in content

    def test_has_baroclinic(self):
        content = generate_template("tidal_estuary")
        assert "ibarcl" in content


class TestSedimentTransport:
    """Sediment transport template activates simple sedi module."""

    def test_has_issedi(self):
        content = generate_template("sediment_transport")
        assert "issedi" in content

    def test_has_3d(self):
        content = generate_template("sediment_transport")
        assert "nlv" in content


class TestWaterQuality:
    """Water quality template activates EUTRO module."""

    def test_has_ibio(self):
        content = generate_template("water_quality")
        assert "ibio" in content

    def test_has_baroclinic(self):
        content = generate_template("water_quality")
        assert "ibarcl" in content


class TestStormSurge:
    """Storm surge template has wetting/drying and Coriolis."""

    def test_has_wetting_drying(self):
        content = generate_template("storm_surge")
        assert "hzoff" in content
        assert "hzon" in content

    def test_has_coriolis(self):
        content = generate_template("storm_surge")
        assert "icor" in content

    def test_has_high_res_timestep(self):
        content = generate_template("storm_surge")
        parsed = StrParser.parse(content)
        idt = parsed.sections["para"].parameters.get("idt", "")
        assert "60" in idt or "30" in idt
