# PR #66 (feat/ui-assimilation) — Security & Silent-Failure Review

**Date:** 2026-08-07 (resumption of the review interrupted 2026-08-06)
**Scope:** `git diff df4f9c72^1..df4f9c72 -- shyfem-ui/` — `pages/physics.py`,
`services/parser_str.py`, `services/simulation_logic.py`, and the four touched
test files. Full post-merge state of each file reviewed, plus the Fortran core
ground truth (`iostr.f90`, `assimil_admin.f90`, `assimil.f90`, `nls.f90`).
**Method:** two independent agents (ui-security-reviewer, silent-failure-hunter),
findings cross-checked; the three highest-impact and both disputed items
re-verified by hand against code and a live reproduction.
**Baseline:** all 277 tests in the four touched test files pass at merge state.

Severity here ranks *scientific* wrong-results risk alongside security: a run
that completes with parameters different from what the UI showed is treated as
top-severity, per project convention.

---

## Verdict

The PR's headline claims hold: the param overlay is genuinely span-exact under
adversarial keys/values (prefix keys, regex metacharacters, quoted `=`), the
`$nduge` purge is justified (the core hard-stops on unknown sections), and the
file-field quote/newline scan does block STR-structure smuggling. Auth,
path-confinement (IDOR), spoofable identity, reactive-loop, and DB checks: all
CLEAN. No critical *security* finding.

However the save path has a cluster of **silent wrong-results** defects, and the
review surfaced one **pre-existing app-wide bug** more severe than anything in
the PR itself.

---

## Priority 0 — pre-existing, app-wide (verified by hand)

### P0.1 `validate_str()` crashes on every real parsed STR — validation is a no-op app-wide
- `services/str_validator.py:20-21,53` expects nested plain dicts; every page
  call site passes `StrFile.sections` (name → `StrSection` dataclass) →
  `TypeError: argument of type 'StrSection' is not iterable`.
  **Reproduced live.**
- `pages/physics.py:822-839`: `StrParser.save` succeeds (line 825), then
  `validate_str` raises (827) inside the same `try` → user sees
  `Save error: …not iterable` for a save that **did** happen; no validation runs.
- `pages/run.py:703-715`: preflight `validate_str` raises → swallowed by
  `except Exception: logger.debug("STR validation skipped (parse error)")` —
  the pre-run gate has never fired for any submitted STR.
- Same dead calls: `simulation.py:383`, `ensemble.py:424,567`. Tests stay green
  because `tests/test_str_validator.py` only ever passes hand-built plain dicts.
  The correct adapter exists in `components/str_editor.py:695+` (uses
  `.parameters`).
- **Fix:** make `validate_str` accept `StrSection` (or adapt at call sites);
  add a test that round-trips a *parsed* file; raise the run.py swallow from
  `debug` to a surfaced warning.

### P0.2 Unmodified `$name` file entries lose their quotes on save — working STR becomes fatal
- `pages/physics.py:768-795` (`_read_input_and_set`) +
  `parser_str.py:294-313` (`_format_value`, quotes only values with
  space/dash): opening the Input Files panel and saving *without edits*
  round-trips `wind = 'INPUT/wind.txt'` → `wind = INPUT/wind.txt`, which the
  core hard-stops on (`nls.f90` `no value found`). Pre-existing; PR #66's own
  `_assimil_apply` docstring (physics.py:434-436) names this defect as the
  reason the *new* fields are pre-quoted, leaving ~30 old fields exposed.
- **Fix:** quote all string values in `_format_value` (or preserve original
  quoting on round-trip).

## Priority 1 — new in PR #66 (silent wrong-results in the assimilation panel)

### P1.1 File-field rejection silently keeps the old value; "Saved" still shown
- `physics.py:463-474`: empty input, or inner text containing `'`, `"`, CR, LF
  → `continue` with no notification, no log. UI keeps showing the new path
  (panel never re-renders — `str_data` mutated in place), STR keeps the old
  one, run completes assimilating the **old observation file**. Clearing a
  field is likewise a silent no-op (a file can never be removed via the UI).
  **Verified by hand.**
- **Fix:** on rejection collect the field name, show an error notification and
  suppress the success message (or block the save). Make "cleared while
  enabled" an explicit error.

### P1.2 Re-enabling a disabled block silently does nothing (`nobs = 0`)
- Disable writes `nobs = 0` (`physics.py:444-446`); on re-enable the input
  prefills 0 (`min=1` is client-side only, line 548) and the save writes
  `nobs = 0` — the core skips the section with one stdout line. Checkbox on,
  "Saved", zero assimilation. Both agents reproduced independently.
- **Fix:** when enabled, force `nobs >= 1` (with notification) or reject.

### P1.3 Missing/unparseable numerics are silently skipped — new sections can be born incomplete
- `physics.py:451-461`: `except … continue` on parse failure. For a **new**
  section a cleared `corlength` simply never gets written → core error-stop at
  init; worse, defaults `mode=0, tau=0` (`physics.py:357-367`) pass every UI
  check and error-stop **mid-run** at the first observation
  (`assimil.f90:350-354`) — potentially hours in. For an existing section a
  cleared numeric keeps the old value while the UI shows blank.
- **Fix:** when enabled, require valid `nobs`, `corlength`, `sigobs`,
  `sigback`, and `tau > 0` when `mode = 0`; default `tau` to a positive value
  (template uses 1800).

### P1.4 Validator has zero `$assimil` awareness; `ibarcl` gate unenforced
- Even with P0.1 fixed, no rule covers assimilation. With `ibarcl <= 0` (or
  `itemp=0` for ivar 12) the sections parse cleanly, `assimil_ts` is never
  called, and the run completes with **no assimilation and no warning**
  (`baroclinic.f90:308,493`; `check_assimil` is empty).
- **Fix:** validator rules: assimil present ⇒ `ibarcl > 0`; per section:
  `nobs >= 1`, `corlength/sigobs/sigback > 0`, both files set,
  `mode in (0,1)`, `mode=0 ⇒ tau>0`, ivar 12 ⇒ `itemp=1`, ivar 11 ⇒ `isalt=1`.

## Priority 2 — medium

- **M1** `physics.py:744-753`: bare `except Exception: continue` around every
  assimilation input read — meant for Shiny's `SilentException`, also swallows
  real regressions (input-id drift → saves silently no-op forever). Catch
  `SilentException`/`KeyError` specifically; `logger.exception` the rest.
- **M2** `physics.py:338`: unnumbered `$assimil` is **core-fatal**
  (`read_assimil`: `num <= 0` → error stop; verified in
  `assimil_admin.f90:283-287`) but invisible to the panel regex → panel offers
  to create a duplicate; `$assimil0` (also fatal) is *adopted and written
  back*. Treat `assimil`/`assimil0` as validation errors. (One agent claimed
  plain `$assimil` is valid to the core — refuted by reading the Fortran.)
- **M3** `physics.py:759-766,847`: the "$nduge removed" notification fires on
  **Preview** (nothing written) and before save success — user can be told the
  fatal section is gone while it is still on disk. Also a decorated line
  (`$nduge  ! comment`) is not recognized as a section: no purge, no warning,
  and the parser **swallows its `$end`** (SECTION_END with no open section is
  dropped, `parser_str.py`), leaving generated output with an unterminated
  block. Notify only after successful write; flag inter-section `$nduge`
  lines; stop dropping ownerless `$end`.
- **M4** `parser_str.py:65,142-148,253-266`: `PARAM_PATTERN` matches inside
  trailing `!`/`#` comments (which the core strips — `nls.f90:426-427`):
  parse shows a value the core never uses, and overlay rewrites the *comment*
  and marks the param emitted, so the user's real edit is **silently
  discarded**. Strip unquoted comments before `finditer` in both parse and
  generate; re-attach verbatim.
- **M5** `physics.py:405-422`: `_assimil_is_array` is line-anchored — arrays on
  multi-assign lines (`nobs = 2  corlength = 100. 200.`) and Fortran
  continuation-line arrays escape it → field renders as editable scalar and
  save silently rewrites **station 1 only**, exactly the partial rewrite the
  docstring guarantees never happens. Scan with `finditer` + token counting.

## Priority 3 — low

- `parser_str.py:308-312`: `_format_value` loses precision for |v| > 1e6
  (`1234567 → "1.23e+06"`); use `%.9g`-style faithful formatting.
- `physics.py:456`: `int(float(x))` silently truncates `nobs = 2.7` → 2.
- `physics.py:537-542`: out-of-range `mode` (e.g. hand-written 2, loudly fatal
  in the core) is coerced to "0 - Nudging" and written back — UI silently
  rewrites a user's file value.
- `physics.py:838-839`: save catch-all has no `logger.exception`, and
  `_collect_panel_values()` has already mutated the shared `StrFile` — a later
  save writes the partial state. Collect into a copy, swap on success.
- No UI check that a long `filecoords/fileobs` path pushes the emitted line
  past the core's fatal 80-char cap (`nls.f90:398`).
- `filecoords`/`fileobs` accept arbitrary paths (absolute/`../`) opened by the
  worker at run time — pre-existing class shared by every `$name` field; real
  enforcement belongs at job launch. Recorded for completeness.
- Conservative false positive: `corlength = 2000.  ! meters` is treated as an
  array → field read-only (safe direction, but surprising).

---

## Explicitly checked and CLEAN

Auth fail-open (save routes through fail-closed `editor_denied_reason`);
spoofable identity (server-validated `_wsauth` only); STR path confinement
(`config.confine_path` on load and save); reactive self-write loop (no `.set()`
in save path — side effect: badges go stale after save, pre-existing pattern);
effect accumulation (4 static effects); conditional render registration;
connect-time `setInputValue` (no JS in diff); DB/test isolation (no DB in
scope). Span-exact overlay verified under adversarial inputs. The
`data_assimilation` template's `$assimil1/2` blocks satisfy every core
acceptance check (values, quoting, 80-char cap, `ibarcl=3`). Tests: no skip
patterns, negative sentinels lock the `$nduge` removal; `inspect.getsource`
asserts are brittle but fail loud.

## Suggested remediation shape

One small PR closes every wrong-results path: fix `validate_str` shape (P0.1)
+ ~8 validator rules (P1.4, M2), tighten `_assimil_apply` rejection paths to
notify-and-fail (P1.1-P1.3), and quote string values in `_format_value` (P0.2).
M1/M3-M5 and P3 items can follow separately.
