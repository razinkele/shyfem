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


class TestLagrangianTemplate:
    """Proper lagrangian template has $lagrg section."""

    def test_has_lagrg_section(self):
        content = generate_template("lagrangian")
        assert "$lagrg" in content

    def test_has_ilagr(self):
        content = generate_template("lagrangian")
        parsed = StrParser.parse(content)
        assert parsed.get_param("lagrg", "ilagr") == 2

    def test_has_nbdy(self):
        content = generate_template("lagrangian")
        assert "nbdy" in content


class TestEulerianTracer:
    """Renamed eulerian_tracer template has iconz and iage."""

    def test_has_iconz(self):
        content = generate_template("eulerian_tracer")
        assert "iconz" in content

    def test_has_iage(self):
        content = generate_template("eulerian_tracer")
        assert "iage" in content


class TestThermalTemplate:
    """Thermal template has heat flux and T/S."""

    def test_has_iheat(self):
        content = generate_template("thermal")
        assert "iheat" in content

    def test_has_baroclinic(self):
        content = generate_template("thermal")
        assert "ibarcl" in content

    def test_has_levels(self):
        content = generate_template("thermal")
        assert "$levels" in content


class TestOilSpillTemplate:
    """Oil spill template has $lagrg with ioil."""

    def test_has_lagrg(self):
        content = generate_template("oil_spill")
        assert "$lagrg" in content

    def test_has_ioil(self):
        content = generate_template("oil_spill")
        parsed = StrParser.parse(content)
        assert parsed.get_param("lagrg", "ioil") == 1


class TestDataAssimilationTemplate:
    """Data assimilation template has $nduge."""

    def test_has_nduge(self):
        content = generate_template("data_assimilation")
        assert "$nduge" in content

    def test_has_ibarcl_4(self):
        content = generate_template("data_assimilation")
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "ibarcl") == 4


class TestOfflineTracerTemplate:
    """Offline tracer template has idtoff."""

    def test_has_idtoff(self):
        content = generate_template("offline_tracer")
        assert "idtoff" in content


class TestWaveCoupledTemplate:
    """Wave-coupled template has iwave."""

    def test_has_iwave(self):
        content = generate_template("wave_coupled")
        assert "iwave" in content


class TestIceModelTemplate:
    """Ice model template has icemod."""

    def test_has_icemod(self):
        content = generate_template("ice_model")
        parsed = StrParser.parse(content)
        assert parsed.get_param("para", "icemod") == 1
