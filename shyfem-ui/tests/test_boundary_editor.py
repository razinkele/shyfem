"""Unit tests for pure helper functions in boundary_editor component.

Tests generate_bound_text() and parse_boundary_csv() from
shyfem_ui.components.boundary_editor.
"""

import pytest
from shiny import reactive

from shyfem_ui.components import boundary_editor as be
from shyfem_ui.components.boundary_editor import (
    generate_bound_text,
    parse_boundary_csv,
)

# ---------------------------------------------------------------------------
# Reactivity harness for _add_boundary / _import_csv (N41)
# ---------------------------------------------------------------------------
#
# boundary_editor_server's reactive.effects can't be driven through a real
# Shiny session in this test suite -- run_server() (job-queue polling)
# deadlocks the event loop when actually started (see MEMORY.md / the stub
# in tests/_test_app.py), so this codebase's established seam for exercising
# @module.server internals is either source inspection (get_server_source /
# test_handler_dedup.py) or, where real reactive behavior must be observed
# (as here — Shiny's reactive.Value identity semantics are exactly the bug),
# unwrapping the @module.server closure to call the plain inner function
# with minimal stand-ins for input/output/session. boundary_editor_server
# uses none of session's API directly, and output is only touched via
# @render.ui (which is never invoked here since nothing subscribes to the
# outputs), so `None` is a safe stand-in for both.


class _FakeInputs:
    """Minimal stand-in for Shiny's `input` proxy: attribute/item access
    returns a callable reading a per-key reactive.Value (matching how
    `input.foo` / `input["foo"]` behave), and `.set()` drives a value change
    exactly like a real client interaction would."""

    def __init__(self):
        self._values: dict[str, reactive.Value] = {}

    def _cell(self, key: str) -> reactive.Value:
        if key not in self._values:
            self._values[key] = reactive.Value(None)
        return self._values[key]

    def __getattr__(self, key: str):
        return self._cell(key).get

    def __getitem__(self, key: str):
        return self.__getattr__(key)

    def set(self, key: str, value) -> None:
        self._cell(key).set(value)


def _mount_boundary_editor(monkeypatch):
    """Mount a fresh, un-namespaced boundary_editor_server instance and
    return (fake_input, result_dict). Silences ui.notification_show (it
    requires a live Shiny session, which this harness deliberately doesn't
    provide) so it doesn't raise mid-effect and mask the assertions below."""
    from shyfem_ui.components import boundary_editor as be

    monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
    inner = be.boundary_editor_server.__closure__[0].cell_contents
    fake_input = _FakeInputs()
    result = inner(fake_input, None, None)
    return fake_input, result


class TestBoundaryListReactivity:
    """N41: Add/CSV-import mutated the reactive list in place and then
    set() the SAME object reference. Shiny's reactive.Value._set()
    short-circuits with `self._value is value` and returns False without
    invalidating dependents when that happens -- so boundary_list and the
    remove-handler registration effect never re-ran. The fix is
    copy-on-write: build a NEW list before calling boundaries.set()."""

    async def test_add_boundary_changes_list_object_identity(self, monkeypatch):
        fake_input, result = _mount_boundary_editor(monkeypatch)
        boundaries = result["boundaries"]

        with reactive.isolate():
            before = boundaries.get()

        fake_input.set("add_boundary_btn", 1)
        await reactive.flush()

        with reactive.isolate():
            after = boundaries.get()

        assert id(before) != id(after), (
            "_add_boundary set() the same list object Shiny already held -- "
            "reactive.Value short-circuits identical-identity sets and never "
            "invalidates dependents (N41)"
        )
        assert len(after) == 1
        assert after[0]["label"] == "bound1"

    async def test_add_boundary_twice_yields_two_rows_and_two_identity_changes(self, monkeypatch):
        fake_input, result = _mount_boundary_editor(monkeypatch)
        boundaries = result["boundaries"]

        with reactive.isolate():
            gen0 = boundaries.get()

        fake_input.set("add_boundary_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            gen1 = boundaries.get()

        fake_input.set("add_boundary_btn", 2)
        await reactive.flush()
        with reactive.isolate():
            gen2 = boundaries.get()

        assert id(gen0) != id(gen1) != id(gen2)
        assert id(gen0) != id(gen2)
        assert len(gen2) == 2
        assert [b["label"] for b in gen2] == ["bound1", "bound2"]

    async def test_import_csv_changes_list_object_identity(self, monkeypatch):
        fake_input, result = _mount_boundary_editor(monkeypatch)
        boundaries = result["boundaries"]

        with reactive.isolate():
            before = boundaries.get()

        fake_input.set("csv_input", "1 2 3, 1\n4 5 6, 2")
        fake_input.set("do_csv_import_btn", 1)
        await reactive.flush()

        with reactive.isolate():
            after = boundaries.get()

        assert id(before) != id(
            after
        ), "_import_csv set() the same list object Shiny already held (N41)"
        assert len(after) == 2
        assert after[0]["nodes"] == "1 2 3"
        assert after[1]["nodes"] == "4 5 6"

    async def test_import_csv_appends_to_existing_boundaries(self, monkeypatch):
        """Import must extend, not replace, boundaries already added."""
        fake_input, result = _mount_boundary_editor(monkeypatch)
        boundaries = result["boundaries"]

        fake_input.set("add_boundary_btn", 1)
        await reactive.flush()

        fake_input.set("csv_input", "7 8 9, 2")
        fake_input.set("do_csv_import_btn", 1)
        await reactive.flush()

        with reactive.isolate():
            after = boundaries.get()

        assert len(after) == 2
        assert after[0]["label"] == "bound1"
        assert after[1]["nodes"] == "7 8 9"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bound(label="bound1", nodes="1 2 3", ibtyp=1, boundn="", zfact=None, intpol=None, bid=1):
    """Create a boundary dict with sensible defaults."""
    return {
        "id": bid,
        "label": label,
        "nodes": nodes,
        "ibtyp": ibtyp,
        "boundn": boundn,
        "zfact": zfact,
        "intpol": intpol,
    }


# ---------------------------------------------------------------------------
# generate_bound_text
# ---------------------------------------------------------------------------


class TestGenerateBoundText:
    """Tests for generate_bound_text()."""

    def test_empty_list_returns_no_boundaries_message(self):
        """Empty boundary list produces a comment saying none defined."""
        result = generate_bound_text([])
        assert "No boundaries defined" in result

    def test_single_boundary_basic(self):
        """Single boundary contains $section_name, kbound, ibtyp, and $end."""
        result = generate_bound_text([_bound()])
        assert "$bound1" in result
        assert "kbound = 1 2 3" in result
        assert "ibtyp = 1" in result
        assert "$end" in result

    def test_boundn_included_when_set(self):
        """boundn line is emitted when a non-empty string is provided."""
        result = generate_bound_text([_bound(boundn="INPUT/tide.txt")])
        assert "boundn = 'INPUT/tide.txt'" in result

    def test_boundn_omitted_when_empty(self):
        """boundn line is suppressed when the value is an empty string."""
        result = generate_bound_text([_bound(boundn="")])
        assert "boundn" not in result

    def test_zfact_included_when_not_one(self):
        """zfact line is emitted when value differs from 1.0."""
        result = generate_bound_text([_bound(zfact=2.5)])
        assert "zfact = 2.5" in result

    def test_zfact_omitted_when_unset(self):
        """zfact line is suppressed when no value was given (None)."""
        result = generate_bound_text([_bound(zfact=None)])
        assert "zfact" not in result

    def test_intpol_included_when_set(self):
        """intpol line is emitted whenever it is set."""
        result = generate_bound_text([_bound(intpol=2)])
        assert "intpol = 2" in result

    def test_intpol_1_is_emitted(self):
        """1 is stepwise, not the core default (0): it must be written (S-03)."""
        result = generate_bound_text([_bound(intpol=1)])
        assert "intpol = 1" in result

    def test_a_long_node_list_is_written_in_lines_of_at_most_80_chars(self):
        """SHYFEM stops on a line over 80 characters (nls_check_line_length);
        a list goes on over numbers-only lines, which the core reads whole."""
        from shyfem_ui.services.parser_str import StrParser

        ids = list(range(10000, 10040))
        text = generate_bound_text([_bound(nodes=" ".join(str(i) for i in ids))])
        assert all(len(line) <= 80 for line in text.splitlines())
        assert StrParser.parse(text).get_param("bound1", "kbound") == ids

    def test_intpol_omitted_when_unset(self):
        """An unset intpol (None) leaves the core default; nothing is written."""
        result = generate_bound_text([_bound(intpol=None)])
        assert "intpol" not in result

    def test_multiple_boundaries(self):
        """Multiple boundaries produce separate $end markers and section names."""
        bounds = [
            _bound(label="bound1", bid=1),
            _bound(label="bound2", bid=2),
        ]
        result = generate_bound_text(bounds)
        assert result.count("$end") == 2
        assert "$bound1" in result
        assert "$bound2" in result

    def test_nodes_empty_omits_kbound(self):
        """kbound line is omitted when nodes string is empty."""
        result = generate_bound_text([_bound(nodes="")])
        assert "kbound" not in result

    def test_full_boundary_all_fields(self):
        """All optional fields present when their values trigger inclusion."""
        b = _bound(
            label="bound5",
            nodes="10 20 30",
            ibtyp=3,
            boundn="INPUT/river.txt",
            zfact=0.5,
            intpol=2,
            bid=5,
        )
        result = generate_bound_text([b])
        assert "$bound5" in result
        assert "kbound = 10 20 30" in result
        assert "ibtyp = 3" in result
        assert "boundn = 'INPUT/river.txt'" in result
        assert "zfact = 0.5" in result
        assert "intpol = 2" in result
        assert "$end" in result


# ---------------------------------------------------------------------------
# parse_boundary_csv
# ---------------------------------------------------------------------------


class TestParseBoundaryCSV:
    """Tests for parse_boundary_csv()."""

    def test_valid_two_columns(self):
        """Minimum two-column CSV yields nodes and ibtyp."""
        result = parse_boundary_csv("1 2 3, 1")
        assert len(result) == 1
        assert result[0]["nodes"] == "1 2 3"
        assert result[0]["ibtyp"] == 1

    def test_all_five_columns(self):
        """All five columns populate boundn, zfact, and intpol."""
        result = parse_boundary_csv("4 5, 2, INPUT/tide.txt, 0.5, 2")
        assert len(result) == 1
        entry = result[0]
        assert entry["nodes"] == "4 5"
        assert entry["ibtyp"] == 2
        assert entry["boundn"] == "INPUT/tide.txt"
        assert entry["zfact"] == 0.5
        assert entry["intpol"] == 2

    def test_comment_lines_skipped(self):
        """Lines starting with '#' are ignored."""
        csv = "# header comment\n1 2, 1\n# another comment\n3 4, 2"
        result = parse_boundary_csv(csv)
        assert len(result) == 2

    def test_blank_lines_skipped(self):
        """Empty lines are ignored."""
        csv = "\n1 2, 1\n\n\n3 4, 2\n"
        result = parse_boundary_csv(csv)
        assert len(result) == 2

    def test_single_column_skipped(self):
        """Lines with fewer than 2 columns are skipped."""
        csv = "only_one_column\n1 2, 1"
        result = parse_boundary_csv(csv)
        assert len(result) == 1
        assert result[0]["nodes"] == "1 2"

    def test_multiple_lines_count_and_labels(self):
        """Multiple valid lines produce correct count and sequential labels."""
        csv = "1 2, 1\n3 4, 2\n5 6, 3"
        result = parse_boundary_csv(csv)
        assert len(result) == 3
        assert result[0]["label"] == "bound1"
        assert result[1]["label"] == "bound2"
        assert result[2]["label"] == "bound3"

    def test_start_id_parameter(self):
        """start_id shifts IDs and labels."""
        result = parse_boundary_csv("1 2, 1\n3 4, 2", start_id=5)
        assert result[0]["id"] == 5
        assert result[0]["label"] == "bound5"
        assert result[1]["id"] == 6
        assert result[1]["label"] == "bound6"

    def test_defaults_for_optional_columns(self):
        """Missing optional columns get default values."""
        result = parse_boundary_csv("1 2 3, 1")
        entry = result[0]
        assert entry["boundn"] == ""
        assert entry["zfact"] is None
        assert entry["intpol"] is None

    def test_invalid_ibtyp_raises_value_error(self):
        """Non-integer ibtyp string raises ValueError."""
        with pytest.raises(ValueError, match=r"line 1, column 2 \(ibtyp\): 'abc'"):
            parse_boundary_csv("1 2, abc")

    def test_whitespace_in_values_stripped(self):
        """Leading/trailing whitespace in each CSV column is stripped."""
        result = parse_boundary_csv("  1 2 3  ,  2  ,  INPUT/file.txt  ,  0.8  ,  2  ")
        entry = result[0]
        assert entry["nodes"] == "1 2 3"
        assert entry["ibtyp"] == 2
        assert entry["boundn"] == "INPUT/file.txt"
        assert entry["zfact"] == 0.8
        assert entry["intpol"] == 2


# ---------------------------------------------------------------------------
# Boundary type completeness
# ---------------------------------------------------------------------------


class TestBoundaryTypesComplete:
    """Boundary type choices cover all Fortran ibtyp values."""

    def test_radiation_boundary_generates(self):
        """ibtyp=31 (radiation) generates correct $bound text."""
        result = generate_bound_text([_bound(ibtyp=31)])
        assert "ibtyp = 31" in result

    def test_closed_wall_generates(self):
        """ibtyp=-1 (closed wall) generates correct $bound text."""
        result = generate_bound_text([_bound(ibtyp=-1)])
        assert "ibtyp = -1" in result

    def test_momentum_boundary_generates(self):
        """ibtyp=4 (momentum) generates correct $bound text."""
        result = generate_bound_text([_bound(ibtyp=4)])
        assert "ibtyp = 4" in result

    def test_csv_import_radiation_type(self):
        """CSV import handles ibtyp=31."""
        csv = "1 2 3, 31, INPUT/open.txt, 1.0, 1"
        result = parse_boundary_csv(csv)
        assert len(result) == 1
        assert result[0]["ibtyp"] == 31


# ---------------------------------------------------------------------------
# Scalar boundary files
# ---------------------------------------------------------------------------


class TestScalarBoundaryFiles:
    """Scalar file fields (saltn, tempn, conzn) in boundary text."""

    def test_saltn_in_bound_text(self):
        """saltn is emitted in $bound section when set."""
        b = _bound()
        b["saltn"] = "INPUT/salt.txt"
        result = generate_bound_text([b])
        assert "saltn = 'INPUT/salt.txt'" in result

    def test_tempn_in_bound_text(self):
        """tempn is emitted in $bound section when set."""
        b = _bound()
        b["tempn"] = "INPUT/temp.txt"
        result = generate_bound_text([b])
        assert "tempn = 'INPUT/temp.txt'" in result

    def test_empty_scalar_files_omitted(self):
        """Empty scalar file strings are not emitted."""
        b = _bound()
        b["saltn"] = ""
        b["tempn"] = ""
        b["conzn"] = ""
        result = generate_bound_text([b])
        assert "saltn" not in result
        assert "tempn" not in result
        assert "conzn" not in result


# ---------------------------------------------------------------------------
# Loading node lists from a real STR (issue #86)
# ---------------------------------------------------------------------------


class TestLoadNodeListFromStr:
    """`kbound = 1855 1856 1882 1883` now parses as a list, so the load that
    did `str(section.parameters.get("kbound", ""))` put "[1855, 1856, 1882,
    1883]" in the Nodes field -- and `generate_bound_text` writes that field
    back verbatim (`kbound = {b['nodes']}`), which is a line the core
    hard-stops on ('no value found'). The field must show, and emit, the
    space-separated run the file itself spells."""

    def _sf(self):
        from shyfem_ui.services.parser_str import StrParser

        return StrParser.parse(
            "$bound1     ---- Baltic sea ----\n"
            "       kbound  = 1547 1548 1549 1550\n"
            "                 1554 1555\n"
            "\tibtyp  = 1\n"
            "\tboundn = 'fem_forcing/sea_level.fem'\n"
            "$end\n"
            "\n"
            "$bound2     ---- Nemunas river ----\n"
            "      kbound = 1855 1856 1882 1883\n"
            "      zfact  = 0.25\n"
            "      ibtyp  = 3\n"
            "$end\n"
        )

    def _load(self, monkeypatch):
        from shyfem_ui.components import boundary_editor as be

        monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
        inner = be.boundary_editor_server.__closure__[0].cell_contents
        fake_input = _FakeInputs()
        result = inner(fake_input, None, None, parsed_str=reactive.Value(self._sf()))
        return result

    async def test_node_lists_load_space_separated(self, monkeypatch):
        result = self._load(monkeypatch)
        await reactive.flush()
        with reactive.isolate():
            bounds = result["boundaries"].get()
        assert [b["label"] for b in bounds] == ["bound1", "bound2"]
        # The continuation line is part of the list, and neither field may
        # carry a Python repr.
        assert bounds[0]["nodes"] == "1547 1548 1549 1550 1554 1555"
        assert bounds[1]["nodes"] == "1855 1856 1882 1883"

    async def test_generated_bound_section_is_a_valid_str(self, monkeypatch):
        """The text this component emits must re-parse to the same node lists
        -- `[1547, ...]` in the Nodes field would ship a fatal STR line."""
        from shyfem_ui.services.parser_str import StrParser

        result = self._load(monkeypatch)
        await reactive.flush()
        with reactive.isolate():
            bounds = result["boundaries"].get()
        text = generate_bound_text(bounds)
        assert "[" not in text
        reparsed = StrParser.parse(text)
        assert reparsed.get_param("bound1", "kbound") == [1547, 1548, 1549, 1550, 1554, 1555]
        assert reparsed.get_param("bound2", "kbound") == [1855, 1856, 1882, 1883]

    async def test_a_single_node_boundary_still_loads_as_one_number(self, monkeypatch):
        from shyfem_ui.components import boundary_editor as be
        from shyfem_ui.services.parser_str import StrParser

        monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
        inner = be.boundary_editor_server.__closure__[0].cell_contents
        sf = StrParser.parse("$bound1\n  kbound = 1855\n  ibtyp = 1\n$end\n")
        result = inner(_FakeInputs(), None, None, parsed_str=reactive.Value(sf))
        await reactive.flush()
        with reactive.isolate():
            bounds = result["boundaries"].get()
        assert bounds[0]["nodes"] == "1855"


# ---------------------------------------------------------------------------
# Loading a $bound with a value that is not a number; an explicit zfact = 1.0
# ---------------------------------------------------------------------------


def _load_str(monkeypatch, text, notes=None):
    from shyfem_ui.components import boundary_editor as be
    from shyfem_ui.services.parser_str import StrParser

    def note(msg, *a, **k):
        if notes is not None:
            notes.append(msg)

    monkeypatch.setattr(be.ui, "notification_show", note)
    inner = be.boundary_editor_server.__closure__[0].cell_contents
    fake_input = _FakeInputs()
    result = inner(fake_input, None, None, parsed_str=reactive.Value(StrParser.parse(text)))
    return fake_input, result


class TestLoadUnreadableValues:
    """int()/float() ran on ibtyp, zfact and intpol straight from the file, in
    a reactive effect: a value that is not a number closed the session."""

    @pytest.mark.parametrize(
        "line, name",
        [("ibtyp = level", "ibtyp"), ("zfact = 'half'", "zfact"), ("intpol = cubic", "intpol")],
    )
    async def test_a_value_that_is_not_a_number_is_reported(self, monkeypatch, line, name):
        notes: list = []
        text = (
            f"$bound1\n  kbound = 1 2\n  ibtyp = 1\n$end\n$bound2\n  kbound = 3 4\n  {line}\n$end\n"
        )
        _, result = _load_str(monkeypatch, text, notes)
        await reactive.flush()  # raised here before
        with reactive.isolate():
            bounds = result["boundaries"].get()
        # The editor shows nothing it cannot write back faithfully.
        assert bounds == []
        assert len(notes) == 1 and "bound2" in notes[0] and name in notes[0]


class TestExplicitZfactOne:
    """Generate dropped zfact = 1.0 even when the file had it; an explicit value
    must round-trip, and an absent one stay absent."""

    async def test_an_explicit_zfact_of_one_is_generated(self, monkeypatch):
        _, result = _load_str(
            monkeypatch, "$bound1\n  kbound = 1 2\n  ibtyp = 1\n  zfact = 1.0\n$end\n"
        )
        await reactive.flush()
        with reactive.isolate():
            bounds = result["boundaries"].get()
        assert "zfact = 1.0" in generate_bound_text(bounds)

    async def test_an_absent_zfact_stays_absent(self, monkeypatch):
        _, result = _load_str(monkeypatch, "$bound1\n  kbound = 1 2\n  ibtyp = 1\n$end\n")
        await reactive.flush()
        with reactive.isolate():
            bounds = result["boundaries"].get()
        assert "zfact" not in generate_bound_text(bounds)

    async def test_generate_keeps_the_explicit_one_through_the_card(self, monkeypatch):
        fake_input, result = _load_str(
            monkeypatch, "$bound1\n  kbound = 1 2\n  ibtyp = 1\n  zfact = 1.\n$end\n"
        )
        await reactive.flush()
        # The card fields as the browser reports them.
        fake_input.set("bound_nodes_1", "1 2")
        fake_input.set("bound_type_1", "1")
        fake_input.set("bound_file_1", "")
        fake_input.set("bound_zfact_1", "1.0")
        fake_input.set("bound_intpol_1", "")
        fake_input.set("generate_str_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            text = result["generated_text"].get()
        assert "zfact = 1.0" in text

    async def test_a_cleared_zfact_field_writes_no_zfact(self, monkeypatch):
        fake_input, result = _load_str(
            monkeypatch, "$bound1\n  kbound = 1 2\n  ibtyp = 1\n  zfact = 0.5\n$end\n"
        )
        await reactive.flush()
        fake_input.set("bound_nodes_1", "1 2")
        fake_input.set("bound_type_1", "1")
        fake_input.set("bound_file_1", "")
        fake_input.set("bound_zfact_1", "")
        fake_input.set("bound_intpol_1", "")
        fake_input.set("generate_str_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            text = result["generated_text"].get()
        assert "zfact" not in text

    @pytest.mark.parametrize("raw", ["half", "nan", "inf"])
    async def test_a_zfact_that_is_not_a_number_is_reported_not_generated(self, monkeypatch, raw):
        notes: list = []
        fake_input, result = _load_str(
            monkeypatch, "$bound1\n  kbound = 1 2\n  ibtyp = 1\n  zfact = 0.5\n$end\n", notes
        )
        await reactive.flush()
        fake_input.set("bound_nodes_1", "1 2")
        fake_input.set("bound_type_1", "1")
        fake_input.set("bound_file_1", "")
        fake_input.set("bound_zfact_1", raw)
        fake_input.set("bound_intpol_1", "")
        fake_input.set("generate_str_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            text = result["generated_text"].get()
        assert text == ""
        assert any("zfact" in n and "bound1" in n for n in notes)


class TestNonFiniteNumbers:
    """nan and inf are floats to Python and nothing to SHYFEM's reader."""

    @pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-Infinity", "1d400"])
    def test_a_non_finite_value_is_not_a_number(self, raw):
        with pytest.raises(ValueError, match="not a number"):
            be._optional_float(raw)

    def test_a_finite_d_exponent_still_parses(self):
        assert be._optional_float("2.d0") == 2.0

    def test_csv_import_refuses_a_nan_zfact(self):
        with pytest.raises(ValueError, match=r"zfact.*not a number"):
            be.parse_boundary_csv("1 2 3,1,,nan")


class _ShinyLikeInputs(_FakeInputs):
    """Like real Shiny 1.8: reading an input the browser has not reported yet
    raises SilentException; it does not return None."""

    def _cell(self, key: str) -> reactive.Value:
        if key not in self._values:
            self._values[key] = reactive.Value()
        return self._values[key]


class TestGenerateBeforeACardReports:
    async def test_an_unreported_card_falls_back_to_its_stored_values(self, monkeypatch):
        from shyfem_ui.components import boundary_editor as be
        from shyfem_ui.services.parser_str import StrParser

        monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
        inner = be.boundary_editor_server.__closure__[0].cell_contents
        fake_input = _ShinyLikeInputs()
        text = "$bound1\n  kbound = 1 2\n  ibtyp = 1\n  zfact = 0.5\n$end\n"
        result = inner(fake_input, None, None, parsed_str=reactive.Value(StrParser.parse(text)))
        await reactive.flush()
        # No card field has reported; Generate silently did nothing.
        fake_input.set("generate_str_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            generated = result["generated_text"].get()
        assert "$bound1" in generated and "zfact = 0.5" in generated


class TestLoadReviewFixes:
    async def test_a_fortran_d_exponent_zfact_loads(self, monkeypatch):
        """The core reads `zfact = 2.d0` (convert.f90 accepts d/D exponents);
        it was reported as 'not a number' and blocked every boundary."""
        notes: list = []
        _, result = _load_str(
            monkeypatch, "$bound1\n  kbound = 1 2\n  ibtyp = 1\n  zfact = 2.d0\n$end\n", notes
        )
        await reactive.flush()
        with reactive.isolate():
            bounds = result["boundaries"].get()
        assert notes == []
        assert bounds[0]["zfact"] == 2.0

    async def test_a_refused_file_clears_the_previous_files_boundaries(self, monkeypatch):
        """Loading file B with a value that is not a number left file A's
        cards on screen (and in Generate) as if they were B's."""
        from shyfem_ui.components import boundary_editor as be
        from shyfem_ui.services.parser_str import StrParser

        monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
        inner = be.boundary_editor_server.__closure__[0].cell_contents
        parsed = reactive.Value(StrParser.parse("$bound1\n  kbound = 1 2\n  ibtyp = 1\n$end\n"))
        result = inner(_FakeInputs(), None, None, parsed_str=parsed)
        await reactive.flush()
        with reactive.isolate():
            assert len(result["boundaries"].get()) == 1
        parsed.set(StrParser.parse("$bound1\n  kbound = 3 4\n  ibtyp = level\n$end\n"))
        await reactive.flush()
        with reactive.isolate():
            assert result["boundaries"].get() == []

    async def test_a_file_without_bound_sections_clears_the_previous_files_boundaries(
        self, monkeypatch
    ):
        """Loading file B with no $bound sections left file A's cards on
        screen (and in Generate) as if they were B's."""
        from shyfem_ui.components import boundary_editor as be
        from shyfem_ui.services.parser_str import StrParser

        monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
        inner = be.boundary_editor_server.__closure__[0].cell_contents
        parsed = reactive.Value(StrParser.parse("$bound1\n  kbound = 1 2\n  ibtyp = 1\n$end\n"))
        result = inner(_FakeInputs(), None, None, parsed_str=parsed)
        await reactive.flush()
        with reactive.isolate():
            assert len(result["boundaries"].get()) == 1
        parsed.set(StrParser.parse("$para\n  itanf = 0\n$end\n"))
        await reactive.flush()
        with reactive.isolate():
            assert result["boundaries"].get() == []

    async def test_hand_added_cards_survive_a_resync_of_a_file_without_bounds(self, monkeypatch):
        """parsed_str is re-set on every STR text edit, quick-setting apply and
        template load, not only on a file load. Cards the user added to a file
        that has no $bound (not yet Generated into it) must not be wiped by
        such a re-sync."""
        from shyfem_ui.components import boundary_editor as be
        from shyfem_ui.services.parser_str import StrParser

        monkeypatch.setattr(be.ui, "notification_show", lambda *a, **k: None)
        inner = be.boundary_editor_server.__closure__[0].cell_contents
        fake_input = _FakeInputs()
        parsed = reactive.Value(StrParser.parse("$para\n  itanf = 0\n$end\n"))
        result = inner(fake_input, None, None, parsed_str=parsed)
        await reactive.flush()
        fake_input.set("add_boundary_btn", 1)
        await reactive.flush()
        with reactive.isolate():
            assert len(result["boundaries"].get()) == 1
        parsed.set(StrParser.parse("$para\n  itanf = 0\n  itend = 3600\n$end\n"))
        await reactive.flush()
        with reactive.isolate():
            assert len(result["boundaries"].get()) == 1
