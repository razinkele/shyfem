"""Tests for physics configuration page."""

import pytest

from shyfem_ui.pages.physics import (
    PHYSICS_PANELS,
    build_panel_params,
)
from shyfem_ui.services.parser_str import COMMON_PARAMS, StrFile, StrParser


class TestPhysicsPanels:
    """Physics panel definitions are complete and valid."""

    def test_all_13_panels_defined(self):
        assert len(PHYSICS_PANELS) == 13

    def test_each_panel_has_required_keys(self):
        for pid, panel in PHYSICS_PANELS.items():
            assert "label" in panel, f"Panel {pid} missing label"
            assert "icon" in panel, f"Panel {pid} missing icon"
            assert "params" in panel, f"Panel {pid} missing params"

    def test_hydrodynamics_panel_params(self):
        params = PHYSICS_PANELS["hydrodynamics"]["params"]
        assert "ilin" in params
        assert "icor" in params
        assert "hzmin" in params

    def test_friction_panel_params(self):
        params = PHYSICS_PANELS["friction"]["params"]
        assert "ireib" in params
        assert "czdef" in params

    def test_ecology_panel_params(self):
        params = PHYSICS_PANELS["ecology"]["params"]
        assert "ibio" in params

    def test_lagrangian_panel_has_section(self):
        panel = PHYSICS_PANELS["lagrangian"]
        assert panel.get("section") == "lagrg" or "ilagr" in panel["params"]


class TestBuildPanelParams:
    """build_panel_params extracts params from StrFile."""

    def test_extracts_known_param(self):
        from shyfem_ui.services.parser_str import StrParser
        content = "$para\n    ireib = 5\n    czdef = 2.5e-3\n$end\n"
        parsed = StrParser.parse(content)
        result = build_panel_params(parsed, "friction")
        assert result["ireib"] == 5

    def test_returns_defaults_for_missing(self):
        result = build_panel_params(StrFile(), "friction")
        assert "ireib" in result

    def test_hydrodynamics_panel_all_keys(self):
        params = build_panel_params(StrFile(), "hydrodynamics")
        expected_keys = set(PHYSICS_PANELS["hydrodynamics"]["params"].keys())
        assert set(params.keys()) == expected_keys

    def test_lagrangian_includes_dedicated_section(self):
        content = "$lagrg\n    nbdy = 100\n    rwhpar = 5.0\n$end\n"
        sf = StrParser.parse(content)
        params = build_panel_params(sf, "lagrangian")
        assert params["nbdy"] == 100
        assert params["rwhpar"] == pytest.approx(5.0)
        assert "ilagr" in params

    def test_sediment_includes_dedicated_section(self):
        params = build_panel_params(StrFile(), "sediment")
        assert "issedi" in params
        if "sedtr" in COMMON_PARAMS and "isedi" in COMMON_PARAMS["sedtr"]:
            assert "isedi" in params

    def test_output_panel_keys(self):
        params = build_panel_params(StrFile(), "output")
        assert "idtout" in params
        assert "netcdf" in params
        assert "itrst" in params


class TestPhysicsPanelsConfig:
    """Validate the PHYSICS_PANELS dictionary structure."""

    def test_all_params_reference_known_sections(self):
        known_sections = set(COMMON_PARAMS.keys())
        for pid, panel in PHYSICS_PANELS.items():
            for param, section in panel["params"].items():
                assert section in known_sections, (
                    f"Panel {pid}, param {param} references unknown "
                    f"section '{section}'"
                )

    def test_dedicated_sections_exist_in_common_params(self):
        for pid, panel in PHYSICS_PANELS.items():
            dedicated = panel.get("section")
            if dedicated:
                assert dedicated in COMMON_PARAMS, (
                    f"Panel {pid} has dedicated section '{dedicated}' "
                    f"not in COMMON_PARAMS"
                )


class TestPhysicsIntegration:
    """End-to-end: parse STR -> extract panel params -> modify -> serialize -> re-parse."""

    def test_full_roundtrip(self):
        content = """$para
        idt = 300
        ireib = 5
        czdef = 2.5e-3
        iturb = 1
        ibarcl = 1
        ilagr = 2
$end
$lagrg
        nbdy = 100
$end
"""
        parsed = StrParser.parse(content)

        friction = build_panel_params(parsed, "friction")
        assert friction["ireib"] == 5

        lagr = build_panel_params(parsed, "lagrangian")
        # ilagr is mapped to "para" section in PHYSICS_PANELS
        assert lagr["ilagr"] == 2
        # nbdy comes from the dedicated "lagrg" section
        assert lagr["nbdy"] == 100

        # Modify a value
        parsed.set_param("para", "ireib", 6)
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("para", "ireib") == 6
        assert reparsed.get_param("para", "iturb") == 1
        assert reparsed.get_param("lagrg", "nbdy") == 100

    def test_roundtrip_preserves_floats(self):
        content = "$para\n    czdef = 0.0025\n    coumax = 1.5\n$end\n"
        parsed = StrParser.parse(content)
        params = build_panel_params(parsed, "friction")
        assert params["czdef"] == pytest.approx(0.0025)

        parsed.set_param("para", "czdef", 0.003)
        generated = StrParser.generate(parsed)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("para", "czdef") == pytest.approx(0.003)

    def test_roundtrip_multiple_panels(self):
        content = """$para
        iturb = 3
        iheat = 2
        ibarcl = 3
        iwave = 1
$end
"""
        parsed = StrParser.parse(content)

        turb = build_panel_params(parsed, "turbulence")
        assert turb["iturb"] == 3

        heat = build_panel_params(parsed, "heat")
        assert heat["iheat"] == 2

        ts = build_panel_params(parsed, "temperature_salinity")
        assert ts["ibarcl"] == 3

        waves = build_panel_params(parsed, "waves")
        assert waves["iwave"] == 1

    def test_set_param_creates_section_if_missing(self):
        sf = StrFile()
        sf.set_param("lagrg", "nbdy", 50)
        assert sf.get_param("lagrg", "nbdy") == 50

        generated = StrParser.generate(sf)
        reparsed = StrParser.parse(generated)
        assert reparsed.get_param("lagrg", "nbdy") == 50

    def test_collect_remap_ids_are_valid(self):
        """Verify the remapped input IDs point to valid params."""
        remap = {
            "ibarcl_assim": ("para", "ibarcl"),
            "idtcon_out": ("para", "idtcon"),
            "icon_av_out": ("para", "icon_av"),
        }
        for input_id, (section, param) in remap.items():
            assert section in COMMON_PARAMS, (
                f"Remap {input_id} -> {section}.{param}: "
                f"section not in COMMON_PARAMS"
            )
            assert param in COMMON_PARAMS[section], (
                f"Remap {input_id} -> {section}.{param}: "
                f"param not in COMMON_PARAMS[{section}]"
            )
