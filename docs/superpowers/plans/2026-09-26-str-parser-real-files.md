# `parser_str`: read real SHYFEM STR files (issue #86) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `shyfem_ui/services/parser_str.py` read the STR files SHYFEM itself accepts, so the Physics page, the STR editor and the boundary editor stop silently showing nothing for real configurations. Closes issue #86.

**This is a correctness bug, not a tolerance feature.** Measured on the current parser:

| Input | Today | SHYFEM |
|---|---|---|
| `&para … &end` | section dropped | accepted (`nls.f90:543` takes `&` or `$`) |
| `$bound1     ---- Baltic sea ----` | section dropped, block becomes inter-section text | accepted; the reader names the trailing text "extra information" (`nls_is_section(section, num, extra)`) |
| `kbound = 1855 1856 1882 1883` | **`kbound = 1855`** — silently truncated to the first token | a four-node list |
| the same list continued on following lines | continuation ignored | one list |

On the real Curonian STR (`curonian29_1993_2016.str`, 241 lines) that means 4 of 11 sections parse: `title, waves, name, extra`. `para` and all five `bound*` are dropped, so the Physics page shows no `itanf`/`itend`/`idt` and no boundaries, and the STR editor's form view shows nothing for them.

**Architecture: parse wider, keep the generator's contract.** `generate()` promises an unmodified section round-trips verbatim from `raw_lines`. Widening what counts as a section header would move real text out of the verbatim inter-section path and into a regenerated header, which would *lose* the decoration — so the section records its original header and end marker and emits them verbatim. Values gain a list type, which two render sites must format instead of `str()`-ing.

**Reference implementation to diff against, not to replace:** `shyfem_ui/services/boxmodel_setup.py::read_str_tolerant` (box-model PR 3) already reads this file correctly, with its own 89-line verbatim excerpt of it in `tests/test_boxmodel_setup.py`. It stays: it is a read-only reader for one page with no round-trip duty, and it is a free second opinion the new tests can compare against on the same excerpt.

## Global Constraints

- **The headline test is byte-exact round-trip on the real file**: `generate(parse(text)) == text` for all 241 lines of the Curonian STR, and for `testcases/examples/mar_menor/*.str`. Measure it before and after; the "before" number is part of the PR body.
- Every one of the 94 existing tests in `tests/test_parser_str.py` passes **unchanged**. A test that must change is a behaviour change and goes in the PR body with its justification.
- `_format_value` must emit a `list[int]` as `1 2 3`. Emitting Python's `[1, 2, 3]` into an STR makes the core hard-stop (`nls.f90` 'no value found'), so this is the one path where a bug is fatal rather than cosmetic. Test it explicitly.
- `&` and `$` do **not** have to pair: `nls_is_section` accepts either character and `section == 'end'` closes whatever opened. Preserving the original marker is for round-trip fidelity, not correctness.
- 13 modules import this parser. Their tests (`test_str_validator`, `test_str_editor_logic`, `test_str_templates`, `test_str_param_search`, `test_physics_page`, `test_simulation_logic`, `test_run_logic`, `test_page_compare`, `test_ensemble_helpers`, `test_dead_controls_wired`) are the regression net and all must stay green.
- Worktree `/tmp/claude-1000/wt-str`, branch `fix/str-parser-real-files`; worker interpreter for every run; E2E never concurrently with the unit suite; never `git stash`/`checkout --`/`reset` in a shared worktree.
- Commit style: conventional commits, trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File structure

| File | Responsibility |
|---|---|
| `shyfem_ui/services/parser_str.py` | Widened `SECTION_START`/`SECTION_END`; `StrSection.header_line`/`end_marker`; list-valued params; `format_int_list`; `_format_value` list support. |
| `tests/test_parser_str.py` | New classes for each behaviour + the real-file round-trip. |
| `shyfem_ui/components/boundary_editor.py`, `shyfem_ui/pages/physics.py` | Format an `int_list` for display instead of `str(...)`. |
| `tests/test_boundary_editor*.py` / `tests/test_physics_page.py` | The two render sites. |
| `tests/test_playwright_physics_picker.py` (or a new E2E) | Load a Curonian-shaped STR on the Physics page and see the parameters and boundaries. |
| `docs/…`, `CHANGELOG.md`, issue #86 | Record it. |

---

### Task 1 (coordinator, TDD): the parser

**Steps:**
- [ ] Record the baseline: for the Curonian STR and each `testcases/examples/mar_menor/*.str`, print `len(sections)`, the section names, and whether `generate(parse(t)) == t`. This is the before column.
- [ ] Tests first, one class each:
  - `TestAmpersandSections`: `&para … &end` parses; `$para … &end` and `&para … $end` both parse (markers need not pair); the marker is preserved on round-trip.
  - `TestDecoratedHeaders`: `$bound1     ---- Baltic sea ---- raw CMEMS sla` parses as `bound1`; the header line round-trips verbatim; `extra` text is available (`StrSection.header_extra`); a decorated `$end` still closes.
  - `TestListValues`: `kbound = 1855 1856 1882 1883` → `[1855, 1856, 1882, 1883]`; `sedgrs = 0.1 0.2` → `[0.1, 0.2]`; a multi-pair line (`itanf = '1993-01-01'   itend = '2016-12-31'\tidt = '5m'`) still splits into three scalars; a bare token followed by `=` starts a new pair, never extends the list; `levels` continuation lines extend the list; `_format_value([1, 2, 3])` → `1 2 3`; a modified single-line list saves as `kbound = 1 2 9`; a modified multi-line list emits one line and drops the continuations (SHYFEM-valid, not byte-identical — asserted as such).
  - `TestRealFileRoundTrip`: the Curonian STR (checked in as a test asset or read from the admin project if present — decide and say which; a checked-in asset is preferable so CI covers it) parses to 11 sections including `para` and `bound1..bound5`, `kbound` lengths are 28/4/2/2/2, `itanf` is `'1993-01-01'` and comes from `&para` only (the decoy `itanf = 347068800` in the prose above it is inter-section text and must not leak), and `generate(parse(t)) == t` byte-exact.
- [ ] Implement, smallest change that passes: widen the two regexes, add `header_line`/`end_marker`/`header_extra`, extend `PARAM_PATTERN`'s bare branch to a token run with a `(?!\s*=)` guard, extend `_convert_value` to return a list when every token converts, add `format_int_list`, teach `_format_value` about lists, and handle continuation lines in the parse loop.
- [ ] Run `tests/test_parser_str.py` plus all ten consumer test files; then the full unit suite.

### Task 2 (agent, after Task 1 is green): consumers and E2E

**Steps:**
- [ ] `boundary_editor.py:167` and `physics.py:3115` render an `int_list` through `format_int_list`, not `str()`; their tests pin `"1855 1856 1882 1883"`, never `"[1855, ...]"`.
- [ ] One E2E: a Curonian-shaped STR in the project, loaded on the Physics page → `itanf`, `itend`, `idtbox` populated and the boundary panel showing five boundaries with their node lists.
- [ ] Check `str_validator.py` for anything that assumed a scalar `kbound`.

### Task 3: docs, issue, verification, PR

**Steps:**
- [ ] `CHANGELOG.md` `[Unreleased]` — Fixed, not Added: the parser silently truncated list values and dropped `&`/decorated sections.
- [ ] Update issue #86 with the measured truncation (`kbound = 1855 1856 → 1855`), then close it from the PR.
- [ ] Consider whether `boxmodel_setup.read_str_tolerant` should now delegate — **default: no**, keep both and say why in the PR (different duties, and it is the independent oracle).
- [ ] ruff/black; full unit suite; all Playwright files (not concurrently); correctness review **before** merge, focused on the round-trip contract and the fatal-output path. Merge is the user's call.

## Self-review

| Issue #86 claim | Where |
|---|---|
| `&para` rejected | `TestAmpersandSections` |
| decorated `$boundN` header rejected | `TestDecoratedHeaders` |
| multi-line `kbound` truncated | `TestListValues` continuation cases |
| (found while planning) single-line list truncated to its first token | `TestListValues` first case — the most damaging of the four |
| the Physics page shows nothing for the Curonian STR | Task 2's E2E |
