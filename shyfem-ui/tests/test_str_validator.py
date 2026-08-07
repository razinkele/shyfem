"""Tests for STR cross-parameter validation."""

from shyfem_ui.services.str_validator import validate_str


class TestBasicValidation:
    """Core timing and required params."""

    def test_missing_itend_is_error(self):
        msgs = validate_str({"para": {"itanf": "0", "idt": "300"}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("itend" in m.message for m in errors)

    def test_missing_idt_is_error(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400"}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("idt" in m.message for m in errors)

    def test_valid_minimal_no_errors(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300"}})
        errors = [m for m in msgs if m.level == "error"]
        assert len(errors) == 0

    def test_idt_zero_is_error(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "0"}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("idt" in m.message and "> 0" in m.message for m in errors)

    def test_itend_lte_itanf_is_error(self):
        msgs = validate_str({"para": {"itanf": "100", "itend": "50", "idt": "10"}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("itend" in m.message and "itanf" in m.message for m in errors)


class TestDependencyValidation:
    """Parameter dependency checks."""

    def test_iturb_gotm_needs_gotmpa_file(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "iturb": 1}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("gotm" in m.message.lower() for m in warnings)

    def test_ibarcl_prognostic_needs_ts(self):
        msgs = validate_str(
            {
                "para": {
                    "itanf": "0",
                    "itend": "86400",
                    "idt": "300",
                    "ibarcl": 1,
                    "itemp": 0,
                    "isalt": 0,
                }
            }
        )
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("temp" in m.message.lower() or "salt" in m.message.lower() for m in warnings)

    def test_iheat_nonzero_needs_ibarcl(self):
        msgs = validate_str(
            {"para": {"itanf": "0", "itend": "86400", "idt": "300", "iheat": 3, "ibarcl": 0}}
        )
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("ibarcl" in m.message.lower() or "barcl" in m.message.lower() for m in warnings)

    def test_sediment_active_needs_sedtr(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "issedi": 1}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("sedtr" in m.message.lower() or "isedi" in m.message.lower() for m in warnings)

    def test_lagrangian_active_needs_lagrg(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "ilagr": 3}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("lagrg" in m.message.lower() for m in warnings)

    def test_no_false_positive_with_valid_gotm(self):
        msgs = validate_str(
            {
                "para": {"itanf": "0", "itend": "86400", "idt": "300", "iturb": 1},
                "name": {"gotmpa": "gotmturb.nml"},
            }
        )
        warnings = [m for m in msgs if m.level == "warning"]
        assert not any("gotm" in m.message.lower() for m in warnings)

    def test_no_false_positive_with_valid_sedtr(self):
        msgs = validate_str(
            {
                "para": {"itanf": "0", "itend": "86400", "idt": "300", "issedi": 1},
                "sedtr": {"isedi": 1},
            }
        )
        warnings = [m for m in msgs if m.level == "warning"]
        assert not any("sedtr" in m.message.lower() for m in warnings)


class TestRangeValidation:
    """Parameter range checks from Fortran source."""

    _VALID = {"itanf": "0", "itend": "86400", "idt": "300"}

    def test_iturb_invalid_value(self):
        msgs = validate_str({"para": {**self._VALID, "iturb": 7}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("iturb" in m.message for m in errors)

    def test_iturb_valid_values(self):
        for val in (0, 1, 2, 3):
            msgs = validate_str({"para": {**self._VALID, "iturb": val}})
            errors = [
                m
                for m in msgs
                if m.level == "error" and "iturb" in m.message and "invalid" in m.message
            ]
            assert len(errors) == 0, f"iturb={val} should be valid"

    def test_ibarcl_invalid_value(self):
        msgs = validate_str({"para": {**self._VALID, "ibarcl": 9}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("ibarcl" in m.message for m in errors)

    def test_iwave_invalid_value(self):
        msgs = validate_str({"para": {**self._VALID, "iwave": 8}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("iwave" in m.message for m in errors)

    def test_itdrag_3_without_waves(self):
        msgs = validate_str({"para": {**self._VALID, "itdrag": 3, "iwave": 0}})
        errors = [m for m in msgs if m.level == "error"]
        assert any("itdrag" in m.message for m in errors)

    def test_itdrag_3_with_waves_ok(self):
        msgs = validate_str({"para": {**self._VALID, "itdrag": 3, "iwave": 2}})
        errors = [m for m in msgs if m.level == "error" and "itdrag" in m.message]
        assert len(errors) == 0


class TestLevelSystemValidation:
    """Level system consistency checks (initialize.f90:476-555)."""

    _VALID = {"itanf": "0", "itend": "86400", "idt": "300"}

    def test_dzreg_with_explicit_levels_is_error(self):
        msgs = validate_str(
            {
                "para": {**self._VALID, "dzreg": 5.0},
                "levels": {"_standalone": [1, 2, 5, 10]},
            }
        )
        errors = [m for m in msgs if m.level == "error"]
        assert any("dzreg" in m.message for m in errors)

    def test_nsigma_with_levels_needs_hsigma(self):
        msgs = validate_str(
            {
                "para": {**self._VALID, "nsigma": 5},
                "levels": {"_standalone": [10, 20, 50]},
            }
        )
        errors = [m for m in msgs if m.level == "error"]
        assert any("hsigma" in m.message for m in errors)

    def test_nsigma_with_levels_and_hsigma_ok(self):
        msgs = validate_str(
            {
                "para": {**self._VALID, "nsigma": 5, "hsigma": 10.0},
                "levels": {"_standalone": [10, 20, 50]},
            }
        )
        errors = [m for m in msgs if m.level == "error" and "hsigma" in m.message]
        assert len(errors) == 0

    def test_hybrid_nsigma_dzreg_without_hsigma(self):
        msgs = validate_str(
            {
                "para": {**self._VALID, "nsigma": 5, "dzreg": 2.0},
            }
        )
        errors = [m for m in msgs if m.level == "error"]
        assert any("hsigma" in m.message for m in errors)

    def test_hybrid_nsigma_dzreg_with_hsigma_ok(self):
        msgs = validate_str(
            {
                "para": {**self._VALID, "nsigma": 5, "dzreg": 2.0, "hsigma": 10.0},
            }
        )
        errors = [m for m in msgs if m.level == "error" and "hsigma" in m.message]
        assert len(errors) == 0

    def test_plain_dzreg_without_levels_ok(self):
        msgs = validate_str({"para": {**self._VALID, "dzreg": 5.0}})
        errors = [m for m in msgs if m.level == "error" and "dzreg" in m.message]
        assert len(errors) == 0


class TestGotmTurbulenceWarning:
    """GOTM without T/S gradients warning."""

    _VALID = {"itanf": "0", "itend": "86400", "idt": "300"}

    def test_gotm_without_ts_warns(self):
        msgs = validate_str({"para": {**self._VALID, "iturb": 1, "itemp": 0, "isalt": 0}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("gotm" in m.message.lower() or "gradient" in m.message.lower() for m in warnings)

    def test_gotm_with_temp_no_warning(self):
        msgs = validate_str(
            {
                "para": {**self._VALID, "iturb": 1, "itemp": 1, "isalt": 0},
                "name": {"gotmpa": "gotmturb.nml"},
            }
        )
        warnings = [m for m in msgs if m.level == "warning" and "gradient" in m.message.lower()]
        assert len(warnings) == 0


class TestPhysicalConstantsValidation:
    """Sanity checks for physical constants."""

    _VALID = {"itanf": "0", "itend": "86400", "idt": "300"}

    def test_normal_rowass_no_warning(self):
        msgs = validate_str({"para": {**self._VALID, "rowass": 1025.0}})
        warnings = [m for m in msgs if m.level == "warning" and "rowass" in m.message]
        assert len(warnings) == 0

    def test_extreme_rowass_warns(self):
        msgs = validate_str({"para": {**self._VALID, "rowass": 500.0}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("rowass" in m.message for m in warnings)

    def test_extreme_roluft_warns(self):
        msgs = validate_str({"para": {**self._VALID, "roluft": 50.0}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("roluft" in m.message for m in warnings)

    def test_normal_roluft_no_warning(self):
        msgs = validate_str({"para": {**self._VALID, "roluft": 1.225}})
        warnings = [m for m in msgs if m.level == "warning" and "roluft" in m.message]
        assert len(warnings) == 0


class TestOutputConsistency:
    """Output interval vs active module checks."""

    _VALID = {"itanf": "0", "itend": "86400", "idt": "300"}

    def test_idtcon_without_scalars_info(self):
        msgs = validate_str({"para": {**self._VALID, "idtcon": 3600, "iconz": 0, "ibarcl": 0}})
        infos = [m for m in msgs if m.level == "info"]
        assert any("idtcon" in m.message for m in infos)

    def test_idtcon_with_tracers_no_info(self):
        msgs = validate_str({"para": {**self._VALID, "idtcon": 3600, "iconz": 1}})
        infos = [m for m in msgs if m.level == "info" and "idtcon" in m.message]
        assert len(infos) == 0

    def test_idtcon_with_baroclinic_no_info(self):
        msgs = validate_str({"para": {**self._VALID, "idtcon": 3600, "ibarcl": 1}})
        infos = [m for m in msgs if m.level == "info" and "idtcon" in m.message]
        assert len(infos) == 0


class TestQuotedTimingValues:
    """apply_quick_settings writes timing params QUOTED (e.g. "'0'"); the
    numeric sanity checks must still apply after stripping the quotes (M7)."""

    def test_quoted_zero_idt_is_caught(self):
        msgs = validate_str({"para": {"itend": "'100'", "idt": "'0'"}})
        assert any(m.param == "idt" and "> 0" in m.message for m in msgs)

    def test_quoted_negative_idt_is_caught(self):
        msgs = validate_str({"para": {"itend": "'100'", "idt": "'-5'"}})
        assert any(m.param == "idt" and "> 0" in m.message for m in msgs)

    def test_quoted_itend_le_itanf_is_caught(self):
        msgs = validate_str({"para": {"itanf": "'20'", "itend": "'10'", "idt": "'1'"}})
        assert any(m.param == "itend" and "itanf" in m.message for m in msgs)

    def test_quoted_valid_timing_has_no_timing_error(self):
        msgs = validate_str({"para": {"itanf": "'0'", "itend": "'100'", "idt": "'300'"}})
        timing_errs = [m for m in msgs if m.param in ("idt", "itend") and m.level == "error"]
        assert timing_errs == []


class TestParsedStrFileCompat:
    """validate_str must accept StrFile.sections (name -> StrSection
    dataclass) — the shape every page call site actually passes. It used
    to TypeError on it, making validation an app-wide no-op."""

    def _parse(self, text):
        from shyfem_ui.services.parser_str import StrParser

        return StrParser.parse(text)

    def test_accepts_parsed_sections_without_raising(self):
        sf = self._parse("$para\n        itanf = 0  itend = 86400  idt = 300\n$end\n")
        msgs = validate_str(sf.sections)
        assert [m for m in msgs if m.level == "error"] == []

    def test_parsed_missing_itend_is_error(self):
        sf = self._parse("$para\n        itanf = 0  idt = 300\n$end\n")
        msgs = validate_str(sf.sections)
        assert any("itend" in m.message for m in msgs if m.level == "error")

    def test_parsed_levels_section_detected_for_dzreg_conflict(self):
        # $levels holds raw lines only (no key=value params) — its presence
        # must still register for the dzreg-conflict rule.
        sf = self._parse(
            "$para\n        itend = 86400  idt = 300  dzreg = 2.\n$end\n\n"
            "$levels\n        2. 4. 6.\n$end\n"
        )
        msgs = validate_str(sf.sections)
        assert any("dzreg" in m.message for m in msgs if m.level == "error")


class TestAssimilValidation:
    """Rules for numbered $assimilN sections (assimil_admin.f90 /
    assimil.f90 acceptance checks + the silent ibarcl gate)."""

    _PARA = "$para\n        itend = 86400  idt = 300  ibarcl = 3{extra}\n$end\n\n"

    def _section(self, name="assimil1", files=True, **over):
        vals = {
            "ivar": 12,
            "nobs": 1,
            "mode": 0,
            "tau": 1800.0,
            "corlength": 2000.0,
            "sigobs": 0.1,
            "sigback": 1.0,
        }
        vals.update(over)
        body = "".join(f"        {k} = {v}\n" for k, v in vals.items() if v is not None)
        if files:
            body += "        filecoords = 'c.dat'\n        fileobs = 'o.dat'\n"
        return f"${name}\n{body}$end\n"

    def _msgs(self, sections_text, para_extra=""):
        from shyfem_ui.services.parser_str import StrParser

        text = self._PARA.format(extra=para_extra) + sections_text
        return validate_str(StrParser.parse(text).sections)

    def test_valid_section_has_no_assimil_errors(self):
        msgs = self._msgs(self._section())
        assert [m for m in msgs if m.level == "error"] == []

    def test_mode1_without_tau_is_not_an_error(self):
        # tau is only consumed in nudging mode (mode=0); direct insertion
        # (mode=1) must not demand it (assimil.f90:350-354).
        msgs = self._msgs(self._section(mode=1, tau=0.0))
        assert [m for m in msgs if m.level == "error"] == []

    def test_unnumbered_assimil_section_is_error(self):
        # read_assimil error-stops on num <= 0: plain $assimil is fatal.
        msgs = self._msgs(self._section(name="assimil"))
        assert any("assimil" in m.message and m.level == "error" for m in msgs)

    def test_assimil0_is_error(self):
        msgs = self._msgs(self._section(name="assimil0"))
        assert any(m.level == "error" and "assimil0" in m.message for m in msgs)

    def test_ibarcl_zero_with_enabled_assimil_is_error(self):
        # ibarcl<=0 -> barocl() never runs -> assimil_ts never called:
        # the run completes with NO assimilation and no warning.
        msgs = self._msgs(self._section(), para_extra="")
        # rebuild with ibarcl = 0
        from shyfem_ui.services.parser_str import StrParser

        text = "$para\n        itend = 86400  idt = 300  ibarcl = 0\n$end\n\n" + self._section()
        msgs = validate_str(StrParser.parse(text).sections)
        assert any("ibarcl" in m.message and m.level == "error" for m in msgs)

    def test_mode0_with_zero_tau_is_error(self):
        # core error-stops MID-RUN at the first observation time.
        msgs = self._msgs(self._section(tau=0.0))
        assert any("tau" in m.message and m.level == "error" for m in msgs)

    def test_missing_files_is_error(self):
        msgs = self._msgs(self._section(files=False))
        errs = [m.message for m in msgs if m.level == "error"]
        assert any("filecoords" in e for e in errs)
        assert any("fileobs" in e for e in errs)

    def test_nonpositive_tuning_params_are_errors(self):
        msgs = self._msgs(self._section(corlength=0.0, sigobs=0.0, sigback=0.0))
        errs = [m.message for m in msgs if m.level == "error"]
        for p in ("corlength", "sigobs", "sigback"):
            assert any(p in e for e in errs), p

    def test_invalid_mode_is_error(self):
        msgs = self._msgs(self._section(mode=2))
        assert any("mode" in m.message and m.level == "error" for m in msgs)

    def test_missing_ivar_is_error(self):
        msgs = self._msgs(self._section(ivar=None))
        assert any("ivar" in m.message and m.level == "error" for m in msgs)

    def test_nobs_zero_is_info_not_error_and_skips_required_checks(self):
        # nobs = 0 is the UI's disable convention: the core skips the
        # section with a log line. Missing files/tuning must NOT error,
        # and neither must ibarcl = 0 — nothing will run anyway.
        from shyfem_ui.services.parser_str import StrParser

        text = (
            "$para\n        itend = 86400  idt = 300  ibarcl = 0\n$end\n\n"
            + self._section(nobs=0, files=False, corlength=0.0)
        )
        msgs = validate_str(StrParser.parse(text).sections)
        assert [m for m in msgs if m.level == "error"] == []
        assert any("nobs" in m.message and m.level == "info" for m in msgs)

    def test_duplicate_ivar_across_sections_is_error(self):
        two = self._section(name="assimil1") + "\n" + self._section(name="assimil2")
        msgs = self._msgs(two)
        assert any("ivar" in m.message and m.level == "error" for m in msgs)

    def test_ivar12_with_itemp_zero_is_error(self):
        msgs = self._msgs(self._section(), para_extra="  itemp = 0")
        assert any("itemp" in m.message and m.level == "error" for m in msgs)

    def test_ivar11_with_isalt_zero_is_error(self):
        msgs = self._msgs(self._section(ivar=11), para_extra="  isalt = 0")
        assert any("isalt" in m.message and m.level == "error" for m in msgs)


class TestDurationStringRobustness:
    """idt*/output-interval params legitimately hold quoted duration
    strings ('1h', '30m') — the documented STR format used by 9 of the
    mar_menor files and 5 templates. Comparisons like `idtcon > 0` must
    not TypeError on them: a validator crash re-creates the app-wide
    no-op this branch removes (save misreported, run gate bypassed,
    ensemble submit dead)."""

    def _parse(self, text):
        from shyfem_ui.services.parser_str import StrParser

        return StrParser.parse(text)

    def test_duration_string_idtcon_does_not_crash(self):
        sf = self._parse(
            "$para\n"
            "        itanf = 0  itend = 86400  idt = 300\n"
            "        idtcon = '1h'\n"
            "$end\n"
        )
        msgs = validate_str(sf.sections)  # must not raise
        assert [m for m in msgs if m.level == "error"] == []

    def test_string_values_in_guarded_params_do_not_crash(self):
        # Every param compared with > 0 must survive a string value.
        sf = self._parse(
            "$para\n"
            "        itanf = 0  itend = 86400  idt = 300\n"
            "        iheat = '1h'  ilagr = 'x'  iconz = 'y'\n"
            "        nsigma = 'a'  dzreg = 'b'  hsigma = 'c'\n"
            "$end\n"
        )
        validate_str(sf.sections)  # must not raise


class TestAssimilMissingRequiredIdentity:
    """The core defaults nobs and ivar to -1 and error-stops on either
    being unset (assimil_admin.f90:349) — BEFORE the nobs=0 skip. A
    missing nobs must not be reported as a benign 'disabled' info."""

    def _msgs(self, section_text):
        from shyfem_ui.services.parser_str import StrParser

        text = "$para\n        itend = 86400  idt = 300  ibarcl = 3\n$end\n\n" + section_text
        return validate_str(StrParser.parse(text).sections)

    def test_missing_nobs_is_error_not_disabled_info(self):
        msgs = self._msgs("$assimil1\n        ivar = 12\n        mode = 1\n$end\n")
        assert any("nobs" in m.message and m.level == "error" for m in msgs)
        assert not any("disabled" in m.message for m in msgs)

    def test_nobs_zero_without_ivar_is_error(self):
        msgs = self._msgs("$assimil1\n        nobs = 0\n$end\n")
        assert any("ivar" in m.message and m.level == "error" for m in msgs)

    def test_nobs_zero_with_ivar_still_benign_info(self):
        msgs = self._msgs("$assimil1\n        nobs = 0\n        ivar = 12\n$end\n")
        assert [m for m in msgs if m.level == "error"] == []
        assert any("disabled" in m.message and m.level == "info" for m in msgs)
