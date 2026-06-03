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
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "ibarcl": 1, "itemp": 0, "isalt": 0}})
        warnings = [m for m in msgs if m.level == "warning"]
        assert any("temp" in m.message.lower() or "salt" in m.message.lower() for m in warnings)

    def test_iheat_nonzero_needs_ibarcl(self):
        msgs = validate_str({"para": {"itanf": "0", "itend": "86400", "idt": "300", "iheat": 3, "ibarcl": 0}})
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
        msgs = validate_str({
            "para": {"itanf": "0", "itend": "86400", "idt": "300", "iturb": 1},
            "name": {"gotmpa": "gotmturb.nml"},
        })
        warnings = [m for m in msgs if m.level == "warning"]
        assert not any("gotm" in m.message.lower() for m in warnings)

    def test_no_false_positive_with_valid_sedtr(self):
        msgs = validate_str({
            "para": {"itanf": "0", "itend": "86400", "idt": "300", "issedi": 1},
            "sedtr": {"isedi": 1},
        })
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
            errors = [m for m in msgs if m.level == "error" and "iturb" in m.message and "invalid" in m.message]
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
        msgs = validate_str({
            "para": {**self._VALID, "dzreg": 5.0},
            "levels": {"_standalone": [1, 2, 5, 10]},
        })
        errors = [m for m in msgs if m.level == "error"]
        assert any("dzreg" in m.message for m in errors)

    def test_nsigma_with_levels_needs_hsigma(self):
        msgs = validate_str({
            "para": {**self._VALID, "nsigma": 5},
            "levels": {"_standalone": [10, 20, 50]},
        })
        errors = [m for m in msgs if m.level == "error"]
        assert any("hsigma" in m.message for m in errors)

    def test_nsigma_with_levels_and_hsigma_ok(self):
        msgs = validate_str({
            "para": {**self._VALID, "nsigma": 5, "hsigma": 10.0},
            "levels": {"_standalone": [10, 20, 50]},
        })
        errors = [m for m in msgs if m.level == "error" and "hsigma" in m.message]
        assert len(errors) == 0

    def test_hybrid_nsigma_dzreg_without_hsigma(self):
        msgs = validate_str({
            "para": {**self._VALID, "nsigma": 5, "dzreg": 2.0},
        })
        errors = [m for m in msgs if m.level == "error"]
        assert any("hsigma" in m.message for m in errors)

    def test_hybrid_nsigma_dzreg_with_hsigma_ok(self):
        msgs = validate_str({
            "para": {**self._VALID, "nsigma": 5, "dzreg": 2.0, "hsigma": 10.0},
        })
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
        msgs = validate_str({
            "para": {**self._VALID, "iturb": 1, "itemp": 1, "isalt": 0},
            "name": {"gotmpa": "gotmturb.nml"},
        })
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
