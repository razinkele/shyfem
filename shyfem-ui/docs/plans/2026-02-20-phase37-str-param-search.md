# Phase 37: STR Parameter Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a search/filter box to the STR editor form view that filters parameters by name or description.

**Architecture:** Pure Python filtering. A `filter_sections()` function takes a search term and parsed StrFile, returns matching params grouped by section. `_build_form_panel()` gains a `search_filter` param to render only matching entries. Wired via Shiny reactive in `str_editor_server`.

**Tech Stack:** Python, Shiny for Python, existing `COMMON_PARAMS` dict as search index.

---

### Task 1: Add `filter_sections()` pure function with tests

**Files:**
- Create: `shyfem-ui/tests/test_str_param_search.py`
- Modify: `shyfem-ui/shyfem_ui/components/str_editor.py` (add function after line 468)

**Step 1: Write the failing tests**

Create `shyfem-ui/tests/test_str_param_search.py`:

```python
"""Tests for STR parameter search filtering."""

import pytest

from shyfem_ui.components.str_editor import filter_sections
from shyfem_ui.services.parser_str import StrParser


@pytest.fixture
def sample_str():
    """A minimal parsed STR with known params."""
    return StrParser.parse("""
$title
    Test Simulation
    sim
    GRID/grid
$end

$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
    idtout = 3600
    ireib = 5
    czdef = 2.5e-3
$end

$name
    wind = 'INPUT/wind.txt'
    gotmpa = 'INPUT/gotm.nml'
$end
""")


class TestFilterSections:

    def test_empty_search_returns_none(self, sample_str):
        """Empty string means no filtering — return None."""
        assert filter_sections("", sample_str) is None
        assert filter_sections("  ", sample_str) is None

    def test_match_by_param_name(self, sample_str):
        """Substring match on parameter name."""
        result = filter_sections("idt", sample_str)
        assert "para" in result
        assert "idt" in result["para"]
        assert "idtout" in result["para"]

    def test_match_by_description(self, sample_str):
        """Match against COMMON_PARAMS description text."""
        result = filter_sections("time step", sample_str)
        assert "para" in result
        # "idt" has description "Time step of integration"
        assert "idt" in result["para"]

    def test_case_insensitive(self, sample_str):
        result = filter_sections("IDT", sample_str)
        assert "para" in result
        assert "idt" in result["para"]

    def test_no_matches_returns_empty(self, sample_str):
        result = filter_sections("xyznonexistent", sample_str)
        assert result == {}

    def test_sections_with_no_matches_omitted(self, sample_str):
        """Sections where no param matches should not appear."""
        result = filter_sections("wind", sample_str)
        assert "name" in result
        assert "para" not in result

    def test_unknown_param_matched_by_name(self):
        """Params not in COMMON_PARAMS are matched by name only."""
        parsed = StrParser.parse("""
$para
    mycustomparam = 42
$end
""")
        result = filter_sections("mycustom", parsed)
        assert "para" in result
        assert "mycustomparam" in result["para"]

    def test_special_chars_treated_as_literal(self, sample_str):
        """Regex special chars should not cause errors."""
        result = filter_sections("[invalid(regex", sample_str)
        assert result == {}

    def test_match_across_sections(self, sample_str):
        """A broad term can match params in multiple sections."""
        # "file" appears in descriptions of wind, gotmpa, etc.
        result = filter_sections("file", sample_str)
        assert "name" in result

    def test_standalone_entries_skipped(self):
        """Params starting with _ (standalone entries) are skipped."""
        parsed = StrParser.parse("""
$extra
    1  'output node'
$end
""")
        result = filter_sections("standalone", parsed)
        assert result == {}

    def test_returns_count_info(self, sample_str):
        """Result dict only contains param name lists."""
        result = filter_sections("idt", sample_str)
        for section, params in result.items():
            assert isinstance(params, list)
            assert all(isinstance(p, str) for p in params)
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase37-str-search/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_param_search.py -v`
Expected: FAIL — `ImportError: cannot import name 'filter_sections'`

**Step 3: Implement `filter_sections()`**

Add to `shyfem-ui/shyfem_ui/components/str_editor.py` after the `_parse_options_to_choices` function (after line 468):

```python
def filter_sections(
    search_term: str,
    parsed: StrFile | None,
) -> dict[str, list[str]] | None:
    """Filter parsed STR sections/params by search term.

    Args:
        search_term: User's search text (case-insensitive substring).
        parsed: Parsed STR file.

    Returns:
        None if search_term is blank (meaning "show all").
        Otherwise dict mapping section_name -> list of matching param names.
        Sections with zero matches are omitted.
    """
    if not search_term or not search_term.strip():
        return None
    if parsed is None:
        return {}

    term = search_term.strip().lower()
    result: dict[str, list[str]] = {}

    for section_name, section in parsed.sections.items():
        matches = []
        known_params = COMMON_PARAMS.get(section_name, {})

        for param_name in section.parameters:
            if param_name.startswith("_"):
                continue

            # Match against param name
            if term in param_name.lower():
                matches.append(param_name)
                continue

            # Match against description (known params only)
            info = known_params.get(param_name)
            if info:
                desc = info[0]  # (description, type, default, units, options)
                if term in desc.lower():
                    matches.append(param_name)

        if matches:
            result[section_name] = matches

    return result
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase37-str-search/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_param_search.py -v`
Expected: All 11 tests PASS

**Step 5: Commit**

```bash
git add tests/test_str_param_search.py shyfem_ui/components/str_editor.py
git commit -m "feat: add filter_sections() for STR parameter search"
```

---

### Task 2: Add search input to form panel UI

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/str_editor.py` — `_build_form_panel()` (lines 326-443)

**Step 1: Modify `_build_form_panel()` to accept and use `search_filter`**

Change the function signature at line 326 from:

```python
def _build_form_panel(parsed: StrFile | None) -> ui.Tag:
```

to:

```python
def _build_form_panel(parsed: StrFile | None, search_filter: dict[str, list[str]] | None = None) -> ui.Tag:
```

Then modify the section loop (lines 334-428) to skip non-matching sections and params:

In the section loop starting at line 335, add at the top of the loop body:

```python
        # If search filter is active, skip sections with no matches
        if search_filter is not None and section_name not in search_filter:
            continue
        matching_params = search_filter.get(section_name) if search_filter is not None else None
```

In the parameter loop at line 342, add a skip check:

```python
        for param_name, param_val in section.parameters.items():
            if param_name.startswith("_"):
                # ... existing standalone handling ...
                continue

            # Skip non-matching params when filter is active
            if matching_params is not None and param_name not in matching_params:
                continue
```

For matching params, add a highlight style to the label. Where the label `ui.span(param_name, ...)` is created (lines 368 and 405), add background highlight when the param is in `matching_params`:

```python
            highlight_style = "background-color: #fff3cd; padding: 0 4px; border-radius: 2px;" if matching_params and param_name in matching_params else ""
```

Apply to both known-param labels (line 368) and unknown-param labels (line 405):

```python
            label_parts = [ui.span(param_name, class_="fw-bold small", style=highlight_style)]
```

**Step 2: Add search input and match count to the form panel return value**

Replace the return block at lines 430-443 with:

```python
    # Build match count badge
    match_info = None
    if search_filter is not None:
        total_params = sum(len(v) for v in search_filter.values())
        total_sections = len(search_filter)
        if total_params > 0:
            match_info = ui.span(
                f"{total_params} param{'s' if total_params != 1 else ''} in {total_sections} section{'s' if total_sections != 1 else ''}",
                class_="badge bg-info text-dark ms-2",
            )
        else:
            match_info = ui.span("No matches", class_="badge bg-secondary ms-2")

    return ui.div(
        # Search bar
        ui.div(
            ui.div(
                ui.input_text(
                    "param_search",
                    "",
                    placeholder="Search parameters (e.g. 'wind', 'time step')...",
                    width="100%",
                ),
                match_info,
                class_="d-flex align-items-center",
            ),
            class_="mb-2",
        ),
        ui.div(
            ui.input_action_button(
                "apply_form_btn",
                "Apply Form Changes",
                class_="btn-sm btn-primary mb-2",
            ),
            class_="d-flex justify-content-end",
        ),
        ui.div(
            *section_cards,
            style="max-height: 500px; overflow-y: auto;",
        ) if section_cards else ui.div(
            ui.p("No matching parameters.", class_="text-muted text-center p-4"),
        ),
    )
```

**Step 3: Run full test suite to verify nothing broke**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase37-str-search/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_param_search.py tests/test_str_validation.py -v`
Expected: All tests PASS (no regressions)

**Step 4: Commit**

```bash
git add shyfem_ui/components/str_editor.py
git commit -m "feat: add search input and filtering to STR form panel"
```

---

### Task 3: Wire search reactively in `str_editor_server`

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/str_editor.py` — `str_editor_server()` (lines 102-323) and `editor_view()` (line 244)

**Step 1: Update `editor_view()` to pass search filter to `_build_form_panel()`**

At line 260, change:

```python
        form_panel = _build_form_panel(parsed)
```

to:

```python
        # Compute search filter
        try:
            search_term = input.param_search()
        except Exception:
            search_term = ""
        search_filter = filter_sections(search_term, parsed)
        form_panel = _build_form_panel(parsed, search_filter=search_filter)
```

The `try/except` handles the case where `param_search` input doesn't exist yet (raw mode, no file loaded).

**Step 2: Verify search works end-to-end**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase37-str-search/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_str_param_search.py -v`
Expected: All 11 tests PASS

**Step 3: Run full test suite**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase37-str-search/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: 753+ passed, 0 failed

**Step 4: Commit**

```bash
git add shyfem_ui/components/str_editor.py
git commit -m "feat: wire parameter search reactively in STR editor"
```

---

### Task 4: Update TODO_NEXT.md and run final verification

**Files:**
- Modify: `shyfem-ui/TODO_NEXT.md` — Add Phase 37 section after Phase 36

**Step 1: Add Phase 37 entry to TODO_NEXT.md**

After the Phase 36 section (around line 438), add:

```markdown
---

## Phase 37: STR Parameter Search

> Search/filter box in the STR editor form view. Filters parameters across
> all sections by name or description with match highlighting.

- [x] **37.1** Add `filter_sections()` pure function — 11 tests
  - Case-insensitive substring match on param name + description
  - Unknown params matched by name only, standalone entries skipped
  - Returns `None` for empty search (show all), `{}` for no matches

- [x] **37.2** Add search input to form panel UI
  - Text input with placeholder, match count badge
  - Non-matching sections hidden, matching param labels highlighted
  - Empty results show "No matching parameters" message

- [x] **37.3** Wire search reactively in `str_editor_server`
  - `input.param_search()` → `filter_sections()` → `_build_form_panel(search_filter=...)`
```

**Step 2: Run full test suite**

Run: `cd /home/razinka/shyfem/.claude/worktrees/phase37-str-search/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --tb=short -q`
Expected: 764+ passed (753 baseline + 11 new), 0 failed

**Step 3: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 37 STR parameter search complete"
```
