"""STR parser: a continuation after a one-token value (S-11).

SHYFEM reads a section's values as one stream, so ``kbound = 1547`` followed
by a numbers-only line ``1548 1549`` is one three-node list. The parser only
continued a value that was already a list, so a boundary whose first line
held one node lost the rest (S-11).
"""

from pathlib import Path

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


def test_every_shipped_str_still_round_trips_byte_exact():
    files = sorted(TESTCASES.rglob("*.str"))
    assert files, "no testcase STR files found"
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.endswith("\n"):
            continue
        assert StrParser.generate(StrParser.parse(text)) == text, path
