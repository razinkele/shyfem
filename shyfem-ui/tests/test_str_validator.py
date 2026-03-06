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
