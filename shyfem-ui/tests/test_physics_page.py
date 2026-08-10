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

    def _assim_sf(self, extra=""):
        from shyfem_ui.services.parser_str import StrParser

        return StrParser.parse(
            "$para\n        ibarcl = 3\n$end\n\n"
            "$assimil7\n"
            "        nobs = 2\n"
            "        ivar = 12\n"
            "        mode = 1\n"
            "        tau = 1800.\n"
            "        corlength = 2000.\n"
            "        sigobs = 0.1\n"
            "        sigback = 1.0\n"
            "        filecoords = 'mm_assim_coords.dat'\n"
            "        fileobs = 'mm_assim_obs.dat'\n"
            "$end\n" + extra
        )

    def test_assimil_find_adopts_by_ivar_not_number(self):
        from shyfem_ui.pages.physics import _assimil_find

        sf = self._assim_sf()
        assert _assimil_find(sf, 12) == "assimil7"
        assert _assimil_find(sf, 11) is None

    def test_assimil_nobs_corrupt_reads_as_zero(self):
        from shyfem_ui.pages.physics import _assimil_nobs
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse("$assimil1\n        nobs = 2, 3\n        ivar = 12\n$end\n")
        assert _assimil_nobs(sf, "assimil1") == 0  # "2," is not a clean int

    def test_assimil_new_name_skips_taken_numbers(self):
        from shyfem_ui.pages.physics import _assimil_new_name
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse("$assimil1\n        ivar = 30\n$end\n")
        assert _assimil_new_name(sf, 1) == "assimil2"
        assert _assimil_new_name(sf, 2) == "assimil2"

    def test_assimil_is_array_detects_space_form(self):
        """Space-separated per-station arrays parse to a clean first-token
        scalar (PARAM_PATTERN truncation), so detection must come from the
        section's raw line, not the parsed value."""
        from shyfem_ui.pages.physics import _assimil_is_array
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse(
            "$assimil1\n        corlength = 2000. 3000.\n        tau = 1800.\n$end\n"
        )
        assert _assimil_is_array(sf, "assimil1", "corlength") is True
        assert _assimil_is_array(sf, "assimil1", "tau") is False
        assert _assimil_is_array(sf, None, "corlength") is False
        assert _assimil_is_array(sf, "missing", "corlength") is False

    def test_assimil_apply_creates_wellformed_section(self):
        from shyfem_ui.pages.physics import _assimil_apply
        from shyfem_ui.services.parser_str import StrFile, StrParser

        sf = StrFile()
        name, errors = _assimil_apply(
            sf,
            11,
            2,
            True,
            {
                "nobs": 1,
                "mode": "0",
                "tau": 1800.0,
                "corlength": 2000.0,
                "sigobs": 0.1,
                "sigback": 1.0,
                "filecoords": "coords.dat",
                "fileobs": "obs.dat",
            },
        )
        assert errors == []
        assert name == "assimil2"
        assert sf.get_param("assimil2", "ivar") == 11
        assert sf.get_param("assimil2", "nobs") == 1
        assert sf.get_param("assimil2", "mode") == 0  # "0" coerced to int
        assert sf.get_param("assimil2", "filecoords") == "'coords.dat'"
        out = StrParser.generate(sf)
        assert "$assimil2" in out
        assert "filecoords = 'coords.dat'" in out  # quoted, not bare

    def test_assimil_apply_disable_touches_only_nobs(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        name, errors = _assimil_apply(sf, 12, 1, False, {"corlength": 9999.0})
        assert (name, errors) == ("assimil7", [])
        assert sf.get_param("assimil7", "nobs") == 0
        assert sf.get_param("assimil7", "corlength") == 2000.0  # untouched
        assert sf.sections["assimil7"]._modified_params == {"nobs"}
        # disabled + no section for this ivar -> no-op, nothing created
        from shyfem_ui.services.parser_str import StrFile

        empty = StrFile()
        assert _assimil_apply(empty, 12, 1, False, {}) == (None, [])
        assert empty.get_section_names() == []

    def test_assimil_apply_skips_missing_fields(self):
        """A field absent from values (array-note case: no input was
        created) must not be written, so its raw line survives."""
        from shyfem_ui.pages.physics import _assimil_apply
        from shyfem_ui.services.parser_str import StrParser

        sf = self._assim_sf()
        _, errors = _assimil_apply(sf, 12, 1, True, {"nobs": 2, "tau": 900.0})
        assert errors == []  # required fields satisfied by existing raw lines
        out = StrParser.generate(sf)
        assert "        corlength = 2000." in out.splitlines()
        assert sf.get_param("assimil7", "tau") == 900.0
        # write-back went to the adopted section's own name — no spurious
        # $assimil1 created alongside it
        assert "assimil1" not in sf.get_section_names()

    def test_assimil_apply_file_field_rejects_quotes_and_newlines(self):
        """A file-field value carrying a quote or newline could smuggle
        STR structure (fake $end/$section) or emit an unbalanced quote;
        such values must be reported as errors with nothing written."""
        from shyfem_ui.pages.physics import _assimil_apply
        from shyfem_ui.services.parser_str import StrFile, StrParser

        sf = StrFile()
        name, errors = _assimil_apply(
            sf,
            12,
            1,
            True,
            {
                "nobs": 1,
                "filecoords": "evil'\n$end\n$para",
                "fileobs": "ok.dat",
            },
        )
        assert any("filecoords" in e and "quote" in e for e in errors)
        # nothing written at all — no smuggled structure can reach the STR
        assert sf.get_section_names() == []
        assert "$para" not in StrParser.generate(sf)

    def test_assimil_apply_nonfinite_numeric_is_error(self):
        """inf/nan must not crash the coercion (OverflowError on
        int(float('inf'))) and must be reported, with nothing written."""
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        name, errors = _assimil_apply(
            sf, 12, 1, True, {"nobs": "inf", "tau": "nan", "corlength": 2000.0}
        )
        assert name == "assimil7"
        assert any("nobs" in e for e in errors)
        assert any("tau" in e for e in errors)
        assert sf.get_param("assimil7", "nobs") == 2  # unchanged, not written
        assert sf.get_param("assimil7", "tau") == 1800.0  # unchanged, not written
        assert sf.sections["assimil7"]._modified_params == set()

    def test_purge_nduge(self):
        from shyfem_ui.pages.physics import _purge_nduge
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse("$nduge\n        nvars = 3\n$end\n\n$para\n        idt = 300\n$end\n")
        assert _purge_nduge(sf) is True
        assert "nduge" not in StrParser.generate(sf)
        assert _purge_nduge(sf) is False  # second call: nothing to do

    def test_ibarcl_assim_remap_removed(self):
        """The baroclinic panel owns ibarcl; a duplicate select here was
        a last-writer-wins footgun (and offered only the wrong modes)."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        assert "ibarcl_assim" not in src

    def test_panel_assimilation_renders_block_inputs(self):
        """Behavioral: render both blocks and check the namespaced ids in
        the HTML (the ids are f-string-built, so source-grepping for
        literals like "assim_t_on" would never match)."""
        from shyfem_ui.pages.physics import _assimil_block
        from shyfem_ui.services.parser_str import StrFile

        html = str(_assimil_block(StrFile(), "Temperature", "t", 12)) + str(
            _assimil_block(StrFile(), "Salinity", "s", 11)
        )
        for input_id in ("assim_t_on", "assim_s_on", "assim_t_nobs", "assim_s_fileobs"):
            assert input_id in html, f"missing {input_id}"

    def test_assimil_blocks_reflect_stored_values(self):
        """Spec test 1: an mm_hyd_assim-shaped STR (T + S sections) fills
        both blocks — checkbox from nobs, numerics and filenames from the
        adopted section."""
        from shyfem_ui.pages.physics import _assimil_block

        sf = self._assim_sf(
            "\n$assimil2\n        nobs = 0\n        ivar = 11\n        tau = 600.\n$end\n"
        )
        t_html = str(_assimil_block(sf, "Temperature", "t", 12))
        assert "checked" in t_html  # nobs = 2 -> enabled
        assert 'value="1800.0"' in t_html  # tau from $assimil7
        assert "mm_assim_coords.dat" in t_html  # filecoords, unquoted on load
        s_html = str(_assimil_block(sf, "Salinity", "s", 11))
        assert "checked" not in s_html  # nobs = 0 -> disabled
        assert 'value="600.0"' in s_html  # stored tuning still shown

    def test_assimil_block_space_separated_array_renders_note(self):
        """Spec test 4, space form: the parser truncates space-separated
        per-station values to a clean scalar, so the block must classify
        the field from its raw line and render the note, not an input."""
        from shyfem_ui.pages.physics import _assimil_block
        from shyfem_ui.services.parser_str import StrParser

        sf = StrParser.parse(
            "$assimil1\n        nobs = 2\n        ivar = 12\n"
            "        corlength = 2000. 3000.\n$end\n"
        )
        html = str(_assimil_block(sf, "Temperature", "t", 12))
        assert "assim_t_corlength" not in html
        assert "set in the STR" in html

    def test_module_badges_key_assimilation_not_nduge(self):
        """The sidebar badge must reflect real $assimil sections, not the
        dead $nduge (which would advertise a guaranteed-fatal STR)."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        assert '"nduge" in sf.sections' not in src
        assert '("Assimilation",' in src

    def test_assimil_block_reads_strfile_not_registry(self):
        """Slice-2 lesson: composite params must come from the StrFile
        (build_panel_params only returns registered params -> always 0)."""
        import inspect

        from shyfem_ui.pages.physics import _assimil_block

        sig = inspect.signature(_assimil_block)
        assert list(sig.parameters)[0] == "sf"

    def test_assimil_num_field_array_renders_note_not_input(self):
        from shyfem_ui.pages.physics import _assimil_num_field

        note = _assimil_num_field("t", "corlength", "Correlation length (m)", "2000.,")
        assert "assim_t_corlength" not in str(note)
        assert "set in the STR" in str(note)

    def test_assimil_num_field_scalar_renders_input(self):
        from shyfem_ui.pages.physics import _assimil_num_field

        tag = _assimil_num_field("t", "corlength", "Correlation length (m)", 2000.0)
        assert "assim_t_corlength" in str(tag)

    def test_assimil_num_field_absent_uses_default(self):
        from shyfem_ui.pages.physics import _assimil_num_field

        tag = str(_assimil_num_field("s", "sigback", "Background error sigma", None))
        assert "assim_s_sigback" in tag
        assert 'value="1.0"' in tag  # _ASSIMIL_DEFAULTS["sigback"]

    def test_collect_panel_values_wires_assimil_and_nduge_purge(self):
        """Regression locks on the composite save step: per-block guarded
        checkbox read, per-field guarded input reads feeding
        _assimil_apply, and the unconditional $nduge purge."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        collect = src[src.index("def _collect_panel_values") : src.index("def _read_input_and_set")]
        assert "_assimil_apply(" in collect
        assert "_purge_nduge(" in collect
        assert 'input[f"assim_{prefix}_on"]' in collect
        assert 'input[f"assim_{prefix}_{param}"]' in collect
        assert (
            '("t", 12, 1, "Temperature")' in collect and '("s", 11, 2, "Salinity")' in collect
        )  # T=ivar 12, S=ivar 11 — order is load-bearing
        assert "return errors" in collect  # apply errors must reach the caller


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
                    f"Panel {pid}, param {param} references unknown " f"section '{section}'"
                )

    def test_dedicated_sections_exist_in_common_params(self):
        for pid, panel in PHYSICS_PANELS.items():
            dedicated = panel.get("section")
            if dedicated:
                assert dedicated in COMMON_PARAMS, (
                    f"Panel {pid} has dedicated section '{dedicated}' " f"not in COMMON_PARAMS"
                )

    def test_assimilation_panel_registry_is_composite(self):
        """No 1:1 registered params and no dedicated section: the old
        registry wrote a $nduge section the core hard-rejects."""
        from shyfem_ui.pages.physics import PHYSICS_PANELS

        panel = PHYSICS_PANELS["assimilation"]
        assert panel["params"] == {}
        assert "section" not in panel


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
            "idtcon_out": ("para", "idtcon"),
            "icon_av_out": ("para", "icon_av"),
        }
        for input_id, (section, param) in remap.items():
            assert section in COMMON_PARAMS, (
                f"Remap {input_id} -> {section}.{param}: " f"section not in COMMON_PARAMS"
            )
            assert param in COMMON_PARAMS[section], (
                f"Remap {input_id} -> {section}.{param}: " f"param not in COMMON_PARAMS[{section}]"
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


class TestAssimilApplyErrors:
    """_assimil_apply must notify-and-fail, never keep-old-value silently:
    a save whose STR differs from the panel state is the top-severity
    failure class for this codebase (run completes with parameters the
    user never saw)."""

    def _assim_sf(self):
        return StrParser.parse(
            "$para\n        ibarcl = 3\n$end\n\n"
            "$assimil7\n"
            "        nobs = 2\n"
            "        ivar = 12\n"
            "        mode = 1\n"
            "        tau = 1800.\n"
            "        corlength = 2000.\n"
            "        sigobs = 0.1\n"
            "        sigback = 1.0\n"
            "        filecoords = 'mm_assim_coords.dat'\n"
            "        fileobs = 'mm_assim_obs.dat'\n"
            "$end\n"
        )

    def _valid_values(self):
        return {
            "nobs": 1,
            "mode": 0,
            "tau": 1800.0,
            "corlength": 2000.0,
            "sigobs": 0.1,
            "sigback": 1.0,
            "filecoords": "coords.dat",
            "fileobs": "obs.dat",
        }

    def test_valid_apply_returns_name_and_no_errors(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = StrFile()
        name, errors = _assimil_apply(sf, 12, 1, True, self._valid_values())
        assert name == "assimil1"
        assert errors == []
        assert sf.get_param("assimil1", "nobs") == 1

    def test_invalid_file_field_is_error_and_nothing_written(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = StrFile()
        vals = self._valid_values()
        vals["filecoords"] = "evil'\n$end\n$para"
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert any("filecoords" in e for e in errors)
        # no partial section may be created on error
        assert sf.get_section_names() == []

    def test_cleared_file_field_is_error_when_enabled(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        vals = self._valid_values()
        vals["fileobs"] = ""
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert any("fileobs" in e for e in errors)
        # old value untouched, no partial write of the good fields
        assert sf.get_param("assimil7", "fileobs") == "mm_assim_obs.dat"
        assert sf.sections["assimil7"]._modified_params == set()

    def test_nobs_zero_when_enabled_is_error(self):
        # Re-enabling a block disabled via the checkbox prefills nobs with
        # the stored 0; writing it through would silently disable
        # assimilation while the UI shows it on.
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        vals = self._valid_values()
        vals["nobs"] = 0
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert any("nobs" in e for e in errors)
        assert sf.get_param("assimil7", "nobs") == 2  # untouched

    def test_unparseable_and_nonfinite_numerics_are_errors(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        vals = self._valid_values()
        vals["corlength"] = "abc"
        vals["tau"] = "inf"
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert any("corlength" in e for e in errors)
        assert any("tau" in e for e in errors)
        assert sf.sections["assimil7"]._modified_params == set()

    def test_mode0_with_zero_tau_is_error(self):
        # The core error-stops MID-RUN on mode=0 with tau<=0
        # (assimil.f90) — potentially hours into a simulation.
        from shyfem_ui.pages.physics import _assimil_apply

        sf = StrFile()
        vals = self._valid_values()
        vals["mode"] = 0
        vals["tau"] = 0.0
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert any("tau" in e for e in errors)
        assert sf.get_section_names() == []

    def test_new_section_missing_required_numeric_is_error(self):
        from shyfem_ui.pages.physics import _assimil_apply

        sf = StrFile()
        vals = self._valid_values()
        del vals["corlength"]  # input absent AND no raw line to fall back on
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert any("corlength" in e for e in errors)
        assert sf.get_section_names() == []

    def test_existing_section_absent_field_keeps_raw_line_no_error(self):
        # The array-note case: no input was created, the section's raw
        # line must survive and satisfy the required-field check.
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        vals = self._valid_values()
        del vals["corlength"]
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert errors == []
        assert sf.get_param("assimil7", "corlength") == 2000.0

    def test_cleared_optional_numeric_stages_zero(self):
        # Optional tuning (maxlength/layer/vcorlength) cleared in the UI
        # means "unset" -> explicit 0, the core default.
        from shyfem_ui.pages.physics import _assimil_apply

        sf = self._assim_sf()
        vals = self._valid_values()
        vals["mode"] = 1  # tau not required in direct-insertion mode
        vals["tau"] = ""
        vals["vcorlength"] = ""
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert errors == []
        assert sf.get_param("assimil7", "vcorlength") == 0.0
        assert sf.get_param("assimil7", "tau") == 0.0

    def test_defaults_are_core_safe(self):
        # A freshly enabled block saved with untouched defaults must not
        # produce a config the core rejects (the old tau=0 default
        # error-stopped mid-run in nudging mode).
        from shyfem_ui.pages.physics import _ASSIMIL_DEFAULTS, _assimil_apply

        assert _ASSIMIL_DEFAULTS["tau"] > 0
        sf = StrFile()
        vals = dict(_ASSIMIL_DEFAULTS)
        vals["filecoords"] = "coords.dat"
        vals["fileobs"] = "obs.dat"
        name, errors = _assimil_apply(sf, 12, 1, True, vals)
        assert errors == []

    def test_save_file_blocks_on_assimil_errors(self):
        # save_file must abort before StrParser.save when the panel
        # collection reports errors — the write must never happen.
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        save = src[src.index("def save_file") : src.index("def preview_str")]
        collect_pos = save.index("_collect_panel_values()")
        write_pos = save.index("StrParser.save")
        assert collect_pos < write_pos
        gate = save[collect_pos:write_pos]
        assert "return" in gate  # abort path between collect and write


class TestSaveValidationOrdering:
    def test_save_file_validates_before_write(self):
        """Error-level validate_str findings must block the write, not be
        reported after the invalid file is already on disk (mirrors the
        str_editor convention of validate-then-write)."""
        import inspect

        from shyfem_ui.pages import physics

        src = inspect.getsource(physics)
        save = src[src.index("def save_file") : src.index("def preview_str")]
        validate_pos = save.index("validate_str(")
        write_pos = save.index("StrParser.save")
        assert validate_pos < write_pos
        assert "return" in save[validate_pos:write_pos]  # errors abort the save
