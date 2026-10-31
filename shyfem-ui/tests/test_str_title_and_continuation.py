"""STR parser: a continuation after a one-token value (S-11), and $title text.

SHYFEM reads a section's values as one stream, so ``kbound = 1547`` followed
by a numbers-only line ``1548 1549`` is one three-node list. The parser only
continued a value that was already a list, so a boundary whose first line
held one node lost the rest (S-11).

``$title`` is three lines of text (title, run name, basin), not parameters;
a title such as ``strip mesh restart (nkn=6 > nel=4)`` parsed as two
parameters, which the editors showed as form fields and an Apply wrote over
the title line.
"""

from pathlib import Path

import pytest

from shyfem_ui.services import parser_str as ps
from shyfem_ui.services.parser_str import StrParser

REPO = Path(__file__).resolve().parents[2]
TESTCASES = REPO / "testcases"


def test_a_continuation_after_a_one_token_value_extends_it():
    sf = StrParser.parse("$bound1\n  kbound = 1547\n     1548 1549\n  ibtyp = 1\n$end\n")
    assert sf.get_param("bound1", "kbound") == [1547, 1548, 1549]
    assert sf.get_param("bound1", "ibtyp") == 1


def test_a_one_token_continuation_after_a_one_token_value():
    sf = StrParser.parse("$bound1\n  kbound = 1547\n  1548\n$end\n")
    assert sf.get_param("bound1", "kbound") == [1547, 1548]


def test_a_quoted_value_is_never_continued():
    sf = StrParser.parse("$name\n  wind = 'w.fem'\n  12\n$end\n")
    assert sf.get_param("name", "wind") == "w.fem"


def test_an_edited_one_token_value_drops_its_continuation():
    text = "$bound1\n  kbound = 1547\n     1548 1549\n  ibtyp = 1\n$end\n"
    sf = StrParser.parse(text)
    assert StrParser.generate(sf) == text
    sf.set_param("bound1", "kbound", [7, 8])
    out = StrParser.generate(sf)
    assert StrParser.parse(out).get_param("bound1", "kbound") == [7, 8]
    assert "1548" not in out


def test_title_text_is_not_parsed_as_parameters():
    text = "$title\n  strip mesh restart (nkn=6 > nel=4)\n  strip_rst\n  strip\n$end\n"
    sf = StrParser.parse(text)
    assert sf.sections["title"].parameters == {}
    assert StrParser.generate(sf) == text


def test_shipped_restart_strip_title_has_no_parameters():
    path = TESTCASES / "examples" / "restart_strip" / "strip_rst.str"
    if not path.exists():
        pytest.skip("restart_strip testcase not present")
    assert StrParser.parse_file(path).sections["title"].parameters == {}


def test_every_shipped_str_still_round_trips_byte_exact():
    files = sorted(TESTCASES.rglob("*.str"))
    assert files, "no testcase STR files found"
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.endswith("\n"):
            continue
        assert StrParser.generate(StrParser.parse(text)) == text, path


# ---------------------------------------------------------------------------
# A written line never exceeds the 80 characters SHYFEM reads
# ---------------------------------------------------------------------------
#
# nls.f90::nls_check_line_length stops the run on any STR line longer than
# 80 characters. A list is read as one stream over following numbers-only
# lines, so a long list is written over several lines; a quoted text cannot
# be split and is refused.

_IDS = list(range(10000, 10040))  # 40 five-digit nodes: 240 characters on one line


def test_a_wrapped_assignment_stays_within_80_chars_and_keeps_every_number():
    lines = ps.wrap_str_assignment("kbound", _IDS)
    assert len(lines) > 1
    assert lines[0].startswith("        kbound = ")
    assert all(len(line) <= ps.STR_MAX_LINE == 80 for line in lines)
    tokens = " ".join(lines).split()
    assert tokens[:2] == ["kbound", "="]
    assert [int(t) for t in tokens[2:]] == _IDS


def test_a_short_assignment_is_one_line():
    assert ps.wrap_str_assignment("ibtyp", 1) == ["        ibtyp = 1"]


def test_an_edited_long_list_is_written_over_several_lines():
    sf = StrParser.parse("$bound1\n  kbound = 1 2\n  ibtyp = 1\n$end\n")
    sf.set_param("bound1", "kbound", _IDS)
    out = StrParser.generate(sf)
    assert all(len(line) <= 80 for line in out.splitlines())
    again = StrParser.parse(out)
    assert again.get_param("bound1", "kbound") == _IDS
    assert again.get_param("bound1", "ibtyp") == 1
    assert StrParser.generate(again) == out  # stable
    # The wrapped lines are ordinary continuations now: an edit drops them.
    again.set_param("bound1", "kbound", [7, 8])
    out2 = StrParser.generate(again)
    assert StrParser.parse(out2).get_param("bound1", "kbound") == [7, 8]
    assert "10001" not in out2


def test_a_long_list_on_a_multi_assignment_line_moves_the_rest_after_it():
    # The core reads a numbers-only line as more values of the LAST name,
    # so the continuation lines must follow the list's own line at once and
    # ibtyp must come after them, on its own line.
    sf = StrParser.parse("$bound1\n  kbound = 1 2  ibtyp = 1   ! open sea\n$end\n")
    sf.set_param("bound1", "kbound", _IDS)
    out = StrParser.generate(sf)
    lines = out.splitlines()
    assert all(len(line) <= 80 for line in lines)
    again = StrParser.parse(out)
    assert again.get_param("bound1", "kbound") == _IDS
    assert again.get_param("bound1", "ibtyp") == 1
    assert StrParser.generate(again) == out
    # The comment survives, before the list and never between its lines:
    # a comment ends a continuation for the UI parser.
    comment_at = next(i for i, line in enumerate(lines) if "! open sea" in line)
    kbound_at = next(i for i, line in enumerate(lines) if "kbound" in line)
    ibtyp_at = next(i for i, line in enumerate(lines) if "ibtyp" in line)
    assert comment_at < kbound_at < ibtyp_at
    assert all(
        "kbound" not in line and "ibtyp" not in line for line in lines[kbound_at + 1 : ibtyp_at]
    )


def test_a_new_section_with_a_long_list_is_wrapped():
    sf = StrParser.parse("$title\n  run\n  r\n  b\n$end\n")
    sf.set_param("bound1", "kbound", _IDS)  # a section built in memory
    sf.set_param("bound1", "ibtyp", 1)
    out = StrParser.generate(sf)
    assert all(len(line) <= 80 for line in out.splitlines())
    assert StrParser.parse(out).get_param("bound1", "kbound") == _IDS


def test_a_text_value_over_80_chars_is_written_whole_for_the_validator():
    # A text cannot be continued on the next line. It is written as it is,
    # and validate_str reports the line (an error that stops a save or a
    # submit), as it did before lists were wrapped.
    from shyfem_ui.services.str_validator import validate_str

    sf = StrParser.parse("$name\n  wind = 'w.fem'\n$end\n")
    sf.set_param("name", "wind", "w" * 90)
    out = StrParser.generate(sf)
    wind_lines = [line for line in out.splitlines() if "wind" in line]
    assert len(wind_lines) == 1 and len(wind_lines[0]) > 80
    assert len([m for m in validate_str(sf.sections) if "80" in m.message]) == 1
