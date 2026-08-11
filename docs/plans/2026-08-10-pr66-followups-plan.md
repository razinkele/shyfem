# PR #66 Review Follow-ups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development. This is Python with a full test suite — TDD is mandatory: every task writes its failing test(s) first and its report carries RED output (pasted verbatim) and GREEN output.

**Goal:** Close the medium/low findings deferred by PR #68, from the PR #66 assimilation review (`docs/reviews/2026-08-07-pr66-assimilation-security-review.md`) and the two-agent review of the #68 branch itself. PR #68 fixed the P0/P1 wrong-results cluster; this batch closes the remainder.

**Tech stack:** Python 3.13 (`/opt/micromamba/envs/shiny/bin/python`), Shiny for Python, pytest. Run tests: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q --ignore=tests/test_playwright_run_picker.py`. Lint: `python -m ruff check shyfem_ui/ && python -m black --check shyfem_ui/` (CI lints `shyfem_ui/` only; keep tests black-clean anyway where already clean).

**Baseline at branch point:** `fix/pr66-followups-batch` off `main` at `549e34d2` (PR #68 merged). Suite: 2409 passed, 9 skipped.

## Global Constraints

- **TDD per item:** failing test first (RED pasted, failure reason must be "feature missing", not a typo/import error), minimal implementation, suite green (GREEN pasted).
- **File ownership is strict** (parallel execution): each worker owns one source file *and* its test file. Never edit a file outside your slice — report a needed cross-file change instead.
- The Fortran core is the ground truth. Cite `src/` line numbers in comments only where a constraint is non-obvious from the code (per CLAUDE.md comment rules).
- Preserve the round-trip contract: an unmodified STR must regenerate byte-identically. Every change to `_generate_section`/`_format_value` needs a round-trip test.
- No new bare `except Exception` — catch the specific exception, log the rest.

---

## Slice A — `shyfem_ui/services/parser_str.py` + `tests/test_parser_str.py`

### A1 (M4) — `PARAM_PATTERN` matches inside trailing comments
The core strips trailing `!`/`#` comments (`src/utils/generic/nls.f90:426-427`) before reading a value. The parser does not, so `tau = 3600  ! was tau = 1800` parses to `tau=1800` — the UI displays a value the core never uses. Worse on write: editing that param rewrites the *comment text* and marks the param emitted, so the user's real edit is silently discarded and the file runs with the core default.

**Fix shape (important — get this exact):** split each raw line at the first **unquoted** `!`/`#`; run `finditer` on the code part only; rebuild the code part by span; re-attach the comment verbatim. `_generate_section` deliberately matches the *unstripped* `raw_line` so spans stay aligned (see its own comment) — if you strip first and rebuild by span against the original, the comment is lost or misplaced.

**Tests must cover:** a param appearing both in code and in the trailing comment; a value containing `!` or `#` *inside quotes* (must not be treated as a comment); a comment-only line; a line with no comment (unchanged round-trip).

### A2 (M3, parser half) — ownerless `$end` is silently dropped
`SECTION_START` requires `^\s*\$(\w+)\s*$`, so a decorated `$nduge  ! legacy nudging` is not recognized as a section start; its block becomes inter-section lines and its `$end` hits the `SECTION_END` branch with `current_section is None` and is **dropped**, so generated output carries an unterminated block. Preserve ownerless `$end` lines verbatim in the inter-section stream (do not invent a section). Test: parse→generate round-trip of a file with a decorated `$nduge` block preserves every line.

### A3 (L1) — `_format_value` precision loss
`abs(value) > 1e6` → `f"{value:.2e}"` turns `1234567.0` into `1.23e+06` (0.4% error). Reachable via `tau` (11.5 days ≈ 1e6 s), `corlength`, `maxlength` on large domains. Use a faithful format (`f"{value:.9g}"` or equivalent) that round-trips through `float()` exactly for the magnitudes SHYFEM uses. Keep small-magnitude scientific notation working. Test: round-trip fidelity for `1234567.0`, `1e-5`, `0.1`, `1e7`.

### A4 — `_format_value` unbalanced quoting
A value containing **both** `'` and `"` (e.g. `a'b"c`) is wrapped in double quotes → `"a'b"c"`, which is unbalanced. Reject such values (raise `ValueError`) rather than emitting a broken STR; the assimilation fields already reject both quote characters, but `_read_input_and_set`-fed `$name` fields do not. Test both quote chars, and confirm the existing single-char cases still work.

---

## Slice B — `shyfem_ui/pages/physics.py` + `tests/test_physics_page.py`

### B1 (M1) — bare `except Exception: continue` around assimilation input reads
Two sites in `_collect_panel_values` (the checkbox read and the per-field read). They exist to tolerate Shiny's `SilentException` for never-rendered inputs, but they also swallow real errors (input-id drift after a rename, module-namespace bugs) with no log at any level — a regression would be undetectable: users edit the panel, save reports success, sections never change. Catch `shiny.types.SilentException` (and `KeyError`) specifically; `logger.exception` anything else and surface it as an error rather than silently skipping the block. Same pattern applies to the `imetout` composite read directly above. Test: a non-silent exception from an input read must be logged and reported, not swallowed.

### B2 (M3, UI half) — `$nduge` purge notification fires before anything is written
The notification lives inside `_collect_panel_values`, which now runs on **preview** (nothing written) and on the **save-abort path** (nothing written). The user is told the fatal section was removed while it is still on disk, and — since it was deleted from the in-memory `StrFile` — the later successful save purges it with *no* notification. Move the notification so it fires only after a successful write; have `_collect_panel_values` report the purge to its caller instead. Tests: purge reported but not announced on preview; announced exactly once after a successful save.

### B3 (M5) — `_assimil_is_array` misses real arrays and false-positives on comments
The detector is line-anchored (`^\s*{param}\s*=`), so it misses (a) multi-assign lines (`nobs = 2  corlength = 100. 200.`) and (b) Fortran continuation-line arrays. Both render as an editable scalar, and saving silently rewrites **station 1 only** — exactly the partial rewrite the docstring guarantees cannot happen. It also false-positives on `corlength = 2000.  ! meters` (trailing comment counted as a second token), making a plain scalar read-only. Scan with `finditer` for the param anywhere on the line and count remainder tokens up to the next `key =` or the comment boundary. Tests: multi-assign array detected; continuation-line array detected; trailing-comment scalar stays editable; genuine array still read-only and survives verbatim.

### B4 (L2) — silent integer truncation
`int(float(raw))` turns a typed `nobs = 2.7` into 2 with no feedback. Reject non-integral values for `_ASSIMIL_INT_FIELDS` with a field error (the `(name, errors)` contract from PR #68 already carries it). Test: `2.7` errors; `2.0` and `"2"` still accepted.

### B5 (L3) — out-of-range `mode` silently coerced
A hand-written `mode = 2` (which the core rejects loudly, pointing at the real mistake) renders as "0 - Nudging" and is written back as `mode = 0` — the UI silently rewrites a value the user set. Render a note/error for an out-of-range stored mode instead of coercing it into the dropdown. Test: `mode = 2` is surfaced, not silently rewritten to 0.

### B6 (L4) — `save_file` catch-all
No `logger.exception`, and `_collect_panel_values()` has already mutated the shared `StrFile` in place, so a subsequent save writes whatever partial state the failure left. Add `logger.exception`; prefer collecting into a copy and swapping on success. Test: the handler logs; a failed save does not leave partial state that a later save would persist.

### B7 (M2, UI half) — unnumbered `$assimil` invisible to the panel
`_ASSIMIL_NAME = ^assimil(\d+)$` does not match a hand-written `$assimil`, so it is neither adopted nor listed in the "Other $assimil sections" hint, and the panel offers to create a parallel `$assimil1`. (The validator now errors on it — PR #68 — so this is about the panel telling the user what is there.) List unnumbered/`$assimil0` sections in the others hint. Test: a file with plain `$assimil` surfaces it in the panel's listing.

---

## Slice C — `shyfem_ui/services/str_validator.py` + `tests/test_str_validator.py`

### C1 — `ValidationMessage.param` holds a section name
Every pre-existing rule sets `.param` to a parameter name; `_validate_assimil` sets it to the section name (`"assimil1"`). Nothing reads `.param` today, so this is latent — but it is a trap the moment `.param` is used for field highlighting. Set `.param` to the offending parameter and carry the section name in the message text (which already names it).

### C2 — 80-char line cap
`nls.f90:398` hard-stops on an STR line longer than 80 characters. A long `filecoords`/`fileobs` path pushes the emitted `        filecoords = '…'` past it. Add a validator rule that flags a file-path value whose emitted line would exceed the cap. Test: a path at the boundary passes, one over it errors.

---

## Out of batch (named so they do not evaporate)

- **STR-embedded data paths.** `filecoords`/`fileobs` — and every `$name` field — accept absolute or `../` paths, which the worker opens at run time with its own privileges. Real enforcement belongs at job launch (where the STR, workdir, and `restart_from` allowlist are already confined), not in the STR editor. Separate subsystem, separate change.
- **`_preflight_validate` dead hook.** `services/run_logic.py` defines it and `tests/test_run_validation.py` imports it, but no app code calls it — the submit handler never runs it. The tests are green against a function the app does not use. Pre-dates all of this work; needs its own decision (wire it up or delete it).

---

## Execution

Slices A, B, C are file-disjoint and run in parallel. Each produces one commit per item (or one per slice if items are small and cohesive), ruff+black clean. After all three land: two-stage parallel review (ui-security-reviewer + code-reviewer) on the combined diff, fix confirmed findings, then PR.
