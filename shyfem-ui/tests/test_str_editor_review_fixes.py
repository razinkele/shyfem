"""STR editor fixes from the 2026-10-19 UI review (S-04, S-05, S-06, S-09)."""

from shyfem_ui.components.str_editor import validate_str_content

_VALID_PARA = "$title\n    t\n$end\n$para\n    itanf = 0\n    itend = 3600\n    idt = 300\n"


class TestStructuralCheckMatchesTheParser:
    """S-09: the closing marker may carry a comment, and '&' works like '$'
    (nls.f90 nls_is_section). The hand-rolled scan flagged both as an
    unclosed section, and that error blocked the inline Save."""

    def test_end_with_a_trailing_comment_closes_the_section(self):
        content = _VALID_PARA + "$end  ! end of para\n"
        assert not [e for e in validate_str_content(content) if "not closed" in e]

    def test_ampersand_markers_close_the_section(self):
        content = _VALID_PARA.replace("$para", "&para") + "&end\n"
        result = validate_str_content(content)
        assert not [e for e in result if "not closed" in e or "Unexpected" in e], result

    def test_dollar_section_closed_by_ampersand_end(self):
        content = _VALID_PARA + "&end\n"
        assert not [e for e in validate_str_content(content) if "not closed" in e]

    def test_a_really_unclosed_section_is_still_reported(self):
        content = _VALID_PARA  # no $end for $para
        assert any("$para not closed" in e for e in validate_str_content(content))

    def test_a_stray_end_is_still_reported(self):
        content = _VALID_PARA + "$end\n$end ! again\n"
        assert any("Unexpected $end" in e for e in validate_str_content(content))
