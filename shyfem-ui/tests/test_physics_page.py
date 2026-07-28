"""Tests for physics configuration page."""

import pytest

from shyfem_ui.pages.physics import (
    PHYSICS_PANELS,
    build_panel_params,
)
from shyfem_ui.services.parser_str import COMMON_PARAMS, StrFile, StrParser


class TestPhysicsPanels:
    """Physics panel definitions are complete and valid."""

    def test_all_21_panels_defined(self):
        assert len(PHYSICS_PANELS) == 21

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

    def test_imetout_decode_encode_roundtrip(self):
        from shyfem_ui.pages.physics import _imetout_decode, _imetout_encode

        flags = _imetout_decode(10010)  # heat (10s) + heat-fluxes (10000s)
        assert flags == {
            "wind": False,
            "heat": True,
            "rain": False,
            "ice": False,
            "hflx": True,
        }
        assert _imetout_encode(flags) == 10010

    def test_imetout_decode_zero_and_encode_empty(self):
        from shyfem_ui.pages.physics import _imetout_decode, _imetout_encode

        allf = ("wind", "heat", "rain", "ice", "hflx")
        assert _imetout_decode(0) == {f: False for f in allf}
        assert _imetout_encode({}) == 0

    def test_imetout_normalizes_digit_gt_one(self):
        from shyfem_ui.pages.physics import _imetout_decode, _imetout_encode

        # heat place = 3 (>1) decodes as "on", re-encodes as 1 -> 10
        assert _imetout_encode(_imetout_decode(30)) == 10

    def test_imetout_decode_handles_garbage(self):
        from shyfem_ui.pages.physics import _imetout_decode

        allf = ("wind", "heat", "rain", "ice", "hflx")
        assert _imetout_decode("x") == {f: False for f in allf}

    def test_imetout_load_reflects_stored_value(self):
        """Checkboxes must initialize from the STR's imetout, not always 0 —
        exercises the same path panel_heat uses (StrFile.get_param -> decode)."""
        from shyfem_ui.pages.physics import _imetout_decode

        parsed = StrParser.parse("$para\n    imetout = 10010\n$end\n")
        flags = _imetout_decode(parsed.get_param("para", "imetout"))
        assert flags == {
            "wind": False,
            "heat": True,
            "rain": False,
            "ice": False,
            "hflx": True,
        }
        # absent imetout -> all off (None handled, no crash)
        assert _imetout_decode(StrFile().get_param("para", "imetout")) == {
            f: False for f in ("wind", "heat", "rain", "ice", "hflx")
        }

    def test_panel_heat_loads_imetout_from_strfile_not_registry(self):
        """Regression lock: the load must read imetout via get_param, not the
        panel-registry build_panel_params (which never returns imetout)."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        assert 'get_param("para", "imetout")' in src

    def test_panel_heat_renders_imetout_checkboxes(self):
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        for f in (
            "imetout_wind",
            "imetout_heat",
            "imetout_rain",
            "imetout_ice",
            "imetout_hflx",
        ):
            assert f'"{f}"' in src, f"{f} checkbox not rendered"

    def test_tracers_panel_has_beaching(self):
        params = PHYSICS_PANELS["tracers"]["params"]
        for p in ("ibeach", "beachrate", "burryrate"):
            assert p in params, f"Missing {p} in tracers panel"
            assert params[p] == "para"

    def test_tracers_beaching_roundtrip(self):
        content = (
            "$para\n    iconz = 2\n    ibeach = 3\n"
            "    beachrate = 0.3\n    burryrate = 0.1\n$end\n"
        )
        parsed = StrParser.parse(content)
        result = build_panel_params(parsed, "tracers")
        assert result["ibeach"] == 3
        assert result["beachrate"] == pytest.approx(0.3)
        assert result["burryrate"] == pytest.approx(0.1)

    def test_panel_tracers_renders_beaching_inputs(self):
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        assert '"ibeach"' in src, "ibeach input not rendered"
        assert '"beachrate"' in src, "beachrate input not rendered"
        assert '"burryrate"' in src, "burryrate input not rendered"

    def test_scalar_or_none_distinguishes_scalar_from_array(self):
        from shyfem_ui.pages.physics import _scalar_or_none

        assert _scalar_or_none(0.3) == pytest.approx(0.3)
        assert _scalar_or_none("0.5") == pytest.approx(0.5)
        assert _scalar_or_none(0) == 0.0
        # array truncated by the parser to "0.3," -> not a clean scalar
        assert _scalar_or_none("0.3,") is None
        assert _scalar_or_none(None) is None
        assert _scalar_or_none("abc") is None

    def test_rate_field_scalar_renders_editable_input(self):
        from shyfem_ui.pages.physics import _rate_field

        html = str(_rate_field("beachrate", "Beaching rate", 0.3))
        assert 'id="beachrate"' in html, "scalar value must render editable input"

    def test_rate_field_array_renders_note_not_input(self):
        from shyfem_ui.pages.physics import _rate_field

        # parser-truncated per-area array value
        html = str(_rate_field("beachrate", "Beaching rate", "0.3,"))
        assert 'id="beachrate"' not in html, "array must NOT render an editable input"
        assert "edit the file directly" in html

    def test_array_beachrate_survives_save_roundtrip(self):
        """Loading + re-serializing an STR with per-area beaching rates must
        preserve the full array (no flatten-to-scalar corruption)."""
        content = (
            "$para\n    iconz = 2\n    ibeach = 3\n"
            "    beachrate = 0.3, 0.25, 0.1\n    burryrate = 0.1, 0.05, 0.02\n$end\n"
        )
        parsed = StrParser.parse(content)
        # build_panel_params must not raise on the array values
        result = build_panel_params(parsed, "tracers")
        assert result["ibeach"] == 3
        # untouched -> generate preserves the raw array lines verbatim
        generated = StrParser.generate(parsed)
        assert "0.3, 0.25, 0.1" in generated
        assert "0.1, 0.05, 0.02" in generated

    def test_lagrangian_panel_has_section(self):
        panel = PHYSICS_PANELS["lagrangian"]
        assert panel.get("section") == "lagrg" or "ilagr" in panel["params"]


class TestTimingPanel:
    """Simulation timing panel with itanf/itend/idt."""

    def test_panel_exists(self):
        assert "timing" in PHYSICS_PANELS

    def test_timing_params_present(self):
        params = PHYSICS_PANELS["timing"]["params"]
        for p in ("itanf", "itend", "idt", "date", "time", "tz"):
            assert p in params, f"Missing param {p}"

    def test_build_timing_defaults(self):
        result = build_panel_params(StrFile(), "timing")
        assert "itanf" in result
        assert "itend" in result
        assert "idt" in result


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


class TestTracerPanel:
    """Tracer/concentration panel exists and has correct params."""

    def test_panel_exists(self):
        assert "tracers" in PHYSICS_PANELS

    def test_tracer_params_present(self):
        params = PHYSICS_PANELS["tracers"]["params"]
        for p in ("iconz", "iage", "idecay", "conref", "chpar", "wsettl"):
            assert p in params, f"Missing param {p}"

    def test_tracer_params_in_common(self):
        for p in ("iconz", "iage", "idecay", "conref", "chpar", "wsettl"):
            assert p in COMMON_PARAMS["para"], f"{p} not in COMMON_PARAMS"

    def test_build_tracer_defaults(self):
        result = build_panel_params(StrFile(), "tracers")
        assert result["iconz"] == 0
        assert result["conref"] == 0.0


class TestBoundaryPanel:
    """Boundary conditions panel exists and has correct section."""

    def test_panel_exists(self):
        assert "boundary" in PHYSICS_PANELS

    def test_boundary_section(self):
        assert PHYSICS_PANELS["boundary"]["section"] == "bound"

    def test_build_boundary_defaults(self):
        result = build_panel_params(StrFile(), "boundary")
        assert "ibtyp" in result
        assert "boundn" in result
        assert "zfact" in result

    def test_output_has_idtrst(self):
        params = PHYSICS_PANELS["output"]["params"]
        assert "idtrst" in params


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


class TestWindPanel:
    def test_panel_exists(self):
        assert "wind" in PHYSICS_PANELS

    def test_wind_params(self):
        params = PHYSICS_PANELS["wind"]["params"]
        for p in ("iwtype", "dragco", "wsmax", "rfact"):
            assert p in params

    def test_build_wind_defaults(self):
        result = build_panel_params(StrFile(), "wind")
        assert result["dragco"] == 2.5e-3
        assert result["wsmax"] == 50.0


class TestInputFilesPanel:
    def test_panel_exists(self):
        assert "input_files" in PHYSICS_PANELS

    def test_has_name_section(self):
        assert PHYSICS_PANELS["input_files"].get("section") == "name"

    def test_build_includes_name_params(self):
        result = build_panel_params(StrFile(), "input_files")
        assert "wind" in result
        assert "restrt" in result


class TestAdvancedHydroPanel:
    def test_panel_exists(self):
        assert "advanced_hydro" in PHYSICS_PANELS

    def test_semi_implicit_params(self):
        params = PHYSICS_PANELS["advanced_hydro"]["params"]
        for p in ("azpar", "ampar", "afpar", "atpar", "adpar", "aapar"):
            assert p in params

    def test_depth_params(self):
        params = PHYSICS_PANELS["advanced_hydro"]["params"]
        for p in ("href", "hmin", "hmax"):
            assert p in params

    def test_build_defaults(self):
        result = build_panel_params(StrFile(), "advanced_hydro")
        assert result["azpar"] == 0.5
        assert result["href"] == 0.0


class TestWrtPanel:
    def test_panel_exists(self):
        assert "renewal_time" in PHYSICS_PANELS

    def test_has_wrt_section(self):
        assert PHYSICS_PANELS["renewal_time"].get("section") == "wrt"

    def test_wrt_in_common(self):
        assert "wrt" in COMMON_PARAMS
        for p in ("idtwrt", "c0", "iaout", "percmin", "iret"):
            assert p in COMMON_PARAMS["wrt"]

    def test_build_defaults(self):
        result = build_panel_params(StrFile(), "renewal_time")
        assert result["idtwrt"] == -1
        assert result["c0"] == 1.0


class TestEcologyExpanded:
    def test_ecology_has_bfmsc_section(self):
        assert PHYSICS_PANELS["ecology"].get("section") == "bfmsc"

    def test_build_has_bfm(self):
        result = build_panel_params(StrFile(), "ecology")
        assert "ibfm" in result


class TestLagrangianConnectivity:
    def test_connectivity_params(self):
        params = PHYSICS_PANELS["lagrangian"]["params"]
        for p in ("icnn", "radcnn", "ppscnn", "pldcnn"):
            assert p in params

    def test_build_has_connectivity(self):
        result = build_panel_params(StrFile(), "lagrangian")
        assert "icnn" in result


class TestNonhydPanel:
    def test_panel_exists(self):
        assert "nonhydrostatic" in PHYSICS_PANELS

    def test_has_nonhyd_section(self):
        assert PHYSICS_PANELS["nonhydrostatic"].get("section") == "nonhyd"

    def test_nonhyd_in_common(self):
        assert "nonhyd" in COMMON_PARAMS
        assert "inohyd" in COMMON_PARAMS["nonhyd"]

    def test_build_defaults(self):
        result = build_panel_params(StrFile(), "nonhydrostatic")
        assert result["inohyd"] == 0


class TestPhysicalConstants:
    def test_constants_in_common(self):
        for p in ("rowass", "roluft"):
            assert p in COMMON_PARAMS["para"]

    def test_constants_in_advanced_hydro(self):
        params = PHYSICS_PANELS["advanced_hydro"]["params"]
        assert "rowass" in params
        assert "roluft" in params

    def test_build_has_constants(self):
        result = build_panel_params(StrFile(), "advanced_hydro")
        assert result["rowass"] == 1025.0
        assert result["roluft"] == 1.225
