"""Tests for STR cross-parameter validation."""

import pytest

from shyfem_ui.services.str_validator import validate_str, ValidationMessage


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
