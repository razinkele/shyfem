# Section M File-Picker Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll the file-picker pattern proven in the Section B partitioning pilot out to the remaining 6 pages with free-text path inputs (`grid_prep`, `postprocess`, `physics`, `simulation`, `run`, `ibm`), eliminating the 20-LOC-per-page `_fill_X` wrapper boilerplate via a shared `fill_picker_input` helper extracted to `components/file_picker.py`.

**Architecture:** Three layers. (1) Pre-flight: add `.lgr → "lagrangian"` to FileService taxonomy with an Alembic backfill migration. (2) Helper extraction: pull the per-page `_fill_X` wrapper bodies (logger.warning + ui.notification_show + ui.update_text) into `fill_picker_input(target_id: PickerTargetId, project: ProjectContext | None, rel_path: str)` in `components/file_picker.py`, then refactor `partitioning.py` to use it (validates the extraction before any new page consumes it). (3) Per-page rollout: each page gets `file_picker_ui` rendered above its existing text input, a `project_id_val` reactive value updated inside the page's `_on_project_changed` effect (added if missing — except `simulation.py` which reuses its pre-existing `project_id_reactive`), `reactive.isolate()` everywhere inside reactive effects + empty-guards on `_on_project_changed` only (NOT on `_on_tutorial_context` — see Test Infrastructure Note F), and `file_picker_server` calls whose `on_selected=` is a lambda delegating to `fill_picker_input` with the unwrapped project (`active_project.get() if active_project else None`).

**Tech Stack:** Python 3.13, Shiny for Python 1.5.1, Alembic, pytest, Playwright. Test runner: `/opt/micromamba/envs/shiny/bin/python -m pytest`.

**References:**
- Pilot spec: `docs/superpowers/specs/2026-05-01-section-b-partitioning-file-picker-design.md`
- Pilot plan: `docs/superpowers/plans/2026-05-01-section-b-partitioning-file-picker.md`
- Pilot pattern: `shyfem-ui/shyfem_ui/pages/partitioning.py:118-250` (canonical wiring)
- Wrapper bodies to extract: `shyfem-ui/shyfem_ui/pages/partitioning.py:196-235`
- Followups doc: `docs/followups/2026-04-29-ui-deep-review-deferred.md`

---

## Revisions Applied (2026-05-05, post-review-pass)

This plan was reviewed by 8 specialist agents (general code review, project-conventions review, silent-failure hunter, type design, comment quality, test coverage, bug-focused, independent second-opinion). The following revisions reflect their findings. **Read the "Test Infrastructure Notes (READ FIRST)" section below before executing any per-page task.**

| Severity | Issue | Where fixed |
|---|---|---|
| Critical | `@module.server` decorator wraps in a closure; `inspect.getsource(page_mod.X_server)` returns the wrapper, not the body — every wiring assertion would fail | Test Infra Note A; per-page tests now use `get_server_source(page_module, server_name)` from new `tests/_test_helpers.py` |
| Critical | Migration path was `alembic/versions/`; actual is `migrations/versions/` (per `alembic.ini` `script_location`) | Task 2 file paths corrected |
| Critical | Sidebar selector `a[data-target="X"]` is wrong; pilot uses `.sf-nav-item[data-nav='X']` | All Playwright snippets in Tasks 4–9 corrected |
| Critical | `simulation.py:183-194` already declares `project_id_reactive` + `_sync_project_id` feeding `str_editor_server`; plan's added `project_id_val` would create a duplicate | Task 6 now reuses the existing reactive |
| Critical | `_on_tutorial_context` empty-guard would silently break tutorial UX (tutorial nav is explicit user action, not reactive churn) | Test Infra Note F; Tasks 4, 5, 6, 8 updated to apply isolate-only on tutorial-context, NOT empty-guard |
| Critical | `grid_prep.py` and `postprocess.py` also have `_on_tutorial_context` (initial survey missed); plan only treated `_on_project_changed` for them | Tasks 4 and 5 now have a Step 4b for `_on_tutorial_context` |
| Critical | `postprocess.py`'s `shy_path` prefill is `proj["work_dir"]` (project-tied directory); a naive empty-guard leaks project A's directory into B on switch | Test Infra Note G; Task 5 uses `last_project_id` to detect actual project change |
| Critical | Playwright `pw_page` is session-scoped; first test in each file inherits state from the last test of the alphabetically-prior file | Test Infra Note B; Task 4 Playwright file gets an autouse `_reset_active_project` fixture (template for the others via "same template" instructions) |
| Important | Helper signature took `reactive.Value[ProjectContext | None] | None` (double-Optional, awkward to test); now takes unwrapped `ProjectContext | None` directly. Lambdas at call sites do `active_project.get() if active_project else None` | Test Infra Note E; Task 3 helper signature updated; all 6 page lambdas updated |
| Important | `target_id: str` allowed silent typos (`ui.update_text("typo", ...)` is a no-op); now `Literal[...]` of the 6 known input ids | Test Infra Note H; Task 3 helper signature updated |
| Important | Migration used untyped style; project's existing migrations use typed annotations (`Sequence[str]`); also `downgrade()` could stomp post-Task-1 inserted rows; also no audit query for the `file_type='other'` filter assumption | Task 2 Step 2 (audit query) and Step 3 (typed annotations + downgrade WARNING) |
| Important | `physics.py:9` already has `from pathlib import Path`; plan's "if not imported, add it" branch is dead | Task 7 Step 1 fixed |
| Important | `ibm.py:226-227` has `if MapWidget is None: return` early-return; plan's new code would register before this guard | Task 9 Step 3 places `project_id_val` AFTER the guard |
| Important | Recommendation flipped: extend `_stub_run_server` instead of skipping Playwright for `run.py` | Task 8 Step 4b adds stub extension; Task 8 Step 9 creates Playwright file |
| Important | `run.py`'s `working_dir` (project-tied directory like postprocess's `shy_path`) needs the `last_project_id` pattern, not just empty-guard | Task 8 Step 4 updated |
| Minor | "See Section M plan" comment in `partitioning.py` reintroduces the rot Task 3 is removing | Task 3 Step 5's replacement comment trimmed; "See Section M plan" line removed |
| Minor | `fill_picker_input` docstring duplicated `resolve_picker_path`'s containment language; risk of drift | Task 3 Step 3 docstring trimmed; references `resolve_picker_path` for containment contract |

Lower-severity comment/docstring style nits from the comment-analyzer review (temporal references, redundant per-page commit message bodies, brittle line-number references in test docstrings) are not individually corrected; an executor following the Test Infrastructure Notes will avoid most of them naturally. Consolidated tracking in followups under Section M.3 if needed post-merge.

---

## Test Infrastructure Notes (READ FIRST)

These conventions apply to EVERY per-page test in Tasks 4–9. Without them, the wiring assertions silently no-op or fail outright.

### A. Source-inspection requires closure unwrap

`@module.server`-decorated functions return a wrapper closure. `get_server_source(page_mod, "X_server")` returns the WRAPPER body (`def wrapper(id, *args, **kwargs)`), not the inner function — it does NOT contain `file_picker_server(`, `fill_picker_input(`, etc. Every wiring assertion in Tasks 4–9 must unwrap first, mirroring `tests/test_partitioning_file_picker.py:88-90`:

```python
inner_fn = page_mod.<page>_server.__closure__[0].cell_contents
assert inner_fn.__name__ == "<page>_server", "closure unwrap got wrong cell"
src = inspect.getsource(inner_fn)
```

To avoid copy-paste drift, extract a helper in `tests/_test_helpers.py` (create if missing):

```python
import inspect

def get_server_source(page_module, server_name: str) -> str:
    """Unwrap the @module.server decorator and return the inner source."""
    fn = getattr(page_module, server_name)
    inner = fn.__closure__[0].cell_contents
    assert inner.__name__ == server_name, (
        f"closure[0] is {inner.__name__!r}, expected {server_name!r}"
    )
    return inspect.getsource(inner)
```

Each per-page wiring test then uses `src = get_server_source(page_mod, "X_server")`.

### B. Playwright fixture pollution — autouse reset

`pw_page` is session-scoped (`tests/conftest.py:165-192`) and `_test_app.py:212`'s `active_project = reactive.value(None)` is shared across every page server. The pilot's tests dodged pollution by being alphabetically last (`test_playwright_partitioning_picker.py`); new files (`g/i/p/s` before `partitioning`) break that ordering luck.

Add to each new Playwright class:

```python
@pytest.fixture(autouse=True)
def _reset_active_project(self, pw_page):
    """Reset active_project to None before each test in this class.

    Without this, the first test inherits whatever active_project was
    set by the LAST test of the previous (alphabetically prior) file,
    making test order load-bearing.
    """
    pw_page.evaluate("""
        if (typeof window.__test_set_active_project === 'function') {
            window.__test_set_active_project(null);
        }
    """)
    pw_page.wait_for_timeout(200)
    yield
```

### C. Sidebar selector schema

The pilot's working selector is `.sf-nav-item[data-nav='X']` (matching `app.py:328-354`). Page display names (the `data-nav` value) per `app.py:59-75`:

| `data-nav` value | Page module |
|---|---|
| `Grid Prep` | `grid_prep` |
| `Partitioning` | `partitioning` |
| `Physics` | `physics` |
| `Simulation` | `simulation` |
| `Run` | `run` |
| `IBM` | `ibm` |
| `Post-Process` | `postprocess` |

Note: `postprocess` page's display name has a hyphen (`Post-Process`).

### D. Pre-existing reactives — survey before adding `project_id_val`

Some pages already declare a `project_id`-shaped reactive feeding OTHER components. **Do NOT add a duplicate.** Audit before each task:

```bash
grep -nE "project_id\s*=\s*reactive\.(value|Value)" shyfem-ui/shyfem_ui/pages/<page>.py
```

Confirmed pre-existing values:
- `simulation.py:183` declares `project_id_reactive = reactive.value(None)` and `_sync_project_id` (lines 186-190) — used by `str_editor_server` (line 194). REUSE this in Task 6 — do NOT add `project_id_val`.
- Other 5 pages: no pre-existing reactive (verified by grep).

### E. Helper signature decision — take `ProjectContext | None` directly

The helper `fill_picker_input` takes the unwrapped `ProjectContext | None`, NOT the reactive container. Lambdas at call sites do the unwrap:

```python
on_selected=lambda rel: fill_picker_input(
    "bas_path",
    active_project.get() if active_project else None,
    rel,
)
```

This eliminates the awkward `reactive.Value[ProjectContext | None] | None` double-Optional, decouples the helper from Shiny's reactive system, and makes helper unit tests trivial (no `_RV` shim required — pass a plain dict).

### F. Tutorial-context effects: isolate-only, no empty-guard

`_on_tutorial_context` effects (present on `grid_prep`, `postprocess`, `simulation`, `run`) fire when the user explicitly clicks a tutorial step's "Open in X" button. That is an explicit user action, NOT reactive churn. Empty-guarding it would silently break the tutorial UX (user expects the tutorial's STR/grid to load; nothing happens).

Apply only `reactive.isolate()` around `input.X()` reads (to prevent dependency-loop re-fires), but DO NOT add `if X_empty:` empty-guards. Tutorial overrides are intentional.

`_on_project_changed` effects DO get both `reactive.isolate()` AND empty-guards — that effect can fire on metadata refreshes which are NOT explicit user intent.

### G. Postprocess stale-data: track project_id changes

Unlike `partitioning.bas_path` (project-tied file), `postprocess.shy_path`'s prefill is `proj["work_dir"]` (a directory). With a naive empty-guard, switching from project A to B leaves `shy_path` showing project A's directory — the user picks an output and runs analysis against the wrong project's outputs.

Track the last-seen project id; force re-fill on project change:

```python
last_project_id: reactive.Value[int | None] = reactive.value(None)

@reactive.effect
def _on_project_changed():
    if active_project is None:
        return
    proj = active_project.get()
    if proj is None:
        project_id_val.set(None)
        last_project_id.set(None)
        return
    pid = proj.get("id")
    project_id_val.set(pid)
    project_changed = last_project_id.get() != pid
    last_project_id.set(pid)
    work = proj["work_dir"]
    with reactive.isolate():
        shy_empty = not input.shy_path()
    # Force re-fill if project actually changed (not just metadata refresh).
    if shy_empty or project_changed:
        ui.update_text("shy_path", value=work)
```

This pattern applies wherever the prefill is project-metadata (not user choice). Specifically: postprocess (`shy_path` ← work_dir), run (`working_dir` ← work_dir).

### H. Helper `target_id` is a Literal type

To catch typos at type-check time:

```python
from typing import Literal
PickerTargetId = Literal[
    "bas_path", "grd_path", "shy_path",
    "str_path", "input_file", "lgr_path",
]
```

A typo `fill_picker_input("bad_path", ...)` then surfaces as a mypy error rather than a silent `ui.update_text("bad_path", ...)` no-op.

### I. `fill_picker_input` is silent on empty-state — wiring-bug observability lives at the call site (or NOT)

The helper does NOT distinguish "page didn't wire `active_project`" (`project is None` here because the lambda passed `None`) from "no project loaded" (`project is None` here because `active_project.get()` returned `None`) — both are silent. By the time the value reaches the helper it's already an unwrapped `ProjectContext | None`; the helper has no way to tell which case fired.

If an individual page wants to surface the wiring-bug case, it can add a one-line warning at the top of its server, e.g.:

```python
def my_page_server(input, output, session, config, active_project=None):
    if active_project is None:
        logger.warning(
            "my_page_server received active_project=None — wiring bug?"
        )
```

The pilot's `partitioning.py:148-157` had this pattern; Task 3 Step 5 deletes it. After deletion, NO page logs the wiring-bug case. That is the deliberate choice for this rollout — the cost (a per-effect warning that fires whenever the page is mounted in the test harness without `active_project`) outweighed the benefit. If a future page wants the warning, add it at server entry as shown above.

---

## Pre-flight Notes — Surveyed State

| Page | Text input id | Line range | Extension(s) | FileService type | `_on_project_changed` line | `reactive.isolate()` | empty-guard | mount namespace |
|---|---|---|---|---|---|---|---|---|
| `pages/grid_prep.py` | `grd_path` | 53–57 | `.grd` | `"grid"` | 130–142 | NO | NO | `"grid_prep"` |
| `pages/postprocess.py` | `shy_path` | 127–131 | `.shy/.nc/.ext/.flx` | `"output"` | 240–248 | NO | NO | `"postprocess"` |
| `pages/physics.py` | `str_path` | 228–231 | `.str` | `"str"` | **none — must add** | n/a | n/a | `"physics"` |
| `pages/simulation.py` | `str_path` | 35–39 | `.str` | `"str"` | 151–162 | NO | NO | `"simulation"` |
| `pages/run.py` | `input_file` | 80–84 | `.str` | `"str"` | 263–274 | NO | NO | `"run"` |
| `pages/ibm.py` | `lgr_path` | 161–165 | `.lgr` | **none — must add `"lagrangian"`** | 249–258 | NO | NO | `"ibm"` |

**Key constraints:**
- All 6 pages already pass `active_project` into their `*_server`. (Initial survey suggested `physics_server` was missing it; verified at `app.py:782` it IS passed.)
- `physics_server` has NO existing `_on_project_changed` effect. Task 7 adds one.
- `pages/run.py` uses a stub server in `tests/_test_app.py:245` (`_stub_run_server`) to avoid event-loop deadlocks. Playwright tests for `run.py` are out of scope; coverage is unit-tests + manual smoke. This is documented in Task 9.
- `.lgr` extension currently maps to `"other"` via the catch-all branch in `services/file_service.py:_infer_file_type`. Task 1 adds `"lagrangian"` and backfills existing rows.
- `_test_app.py` already exposes `__test_set_active_project` (added in pilot). All 6 target pages are mounted in `_test_app.py` (lines 156, 163, 166, 168, 169, 171 per the survey). No new mounts needed.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `shyfem_ui/services/file_service.py` | Adds `.lgr → "lagrangian"` branch in `_infer_file_type` | Modify (1 added branch) |
| `shyfem-ui/migrations/versions/<rev>_lagrangian_file_type.py` | One-shot UPDATE of existing `.lgr` rows from `"other"` to `"lagrangian"` | Create |
| `shyfem_ui/components/file_picker.py` | Adds `fill_picker_input` helper (extracts wrapper body) | Modify (~30 added LOC) |
| `shyfem_ui/pages/partitioning.py` | Refactored to use `fill_picker_input` | Modify (-~40 / +~10 LOC net) |
| `shyfem_ui/pages/grid_prep.py` | Wire picker for `grd_path` | Modify (~25 added LOC) |
| `shyfem_ui/pages/postprocess.py` | Wire picker for `shy_path` | Modify (~25 added LOC) |
| `shyfem_ui/pages/physics.py` | Wire picker for `str_path` (incl. NEW `_on_project_changed`) | Modify (~50 added LOC) |
| `shyfem_ui/pages/simulation.py` | Wire picker for `str_path` | Modify (~25 added LOC) |
| `shyfem_ui/pages/run.py` | Wire picker for `input_file` | Modify (~25 added LOC) |
| `shyfem_ui/pages/ibm.py` | Wire picker for `lgr_path` (filtered to `"lagrangian"`) | Modify (~25 added LOC) |
| `tests/test_file_picker_logic.py` | Add tests for `fill_picker_input` helper | Modify (+~80 LOC) |
| `tests/test_partitioning_file_picker.py` | Refactor wiring assertion to check `fill_picker_input` use | Modify (~10 LOC) |
| `tests/test_grid_prep_file_picker.py` | UI-render + import-style tests | Create (~50 LOC) |
| `tests/test_postprocess_file_picker.py` | UI-render + import-style tests | Create (~50 LOC) |
| `tests/test_physics_file_picker.py` | UI-render + import-style tests | Create (~50 LOC) |
| `tests/test_simulation_file_picker.py` | UI-render + import-style tests | Create (~50 LOC) |
| `tests/test_run_file_picker.py` | UI-render + import-style tests | Create (~50 LOC) |
| `tests/test_ibm_file_picker.py` | UI-render + import-style tests + `lagrangian` taxonomy assertion | Create (~60 LOC) |
| `tests/_test_helpers.py` | `get_server_source(page_module, server_name)` closure-unwrap helper | Create (~15 LOC) |
| `tests/test_playwright_grid_prep_picker.py` | Session-driven tests | Create (~150 LOC) |
| `tests/test_playwright_postprocess_picker.py` | Session-driven tests | Create (~150 LOC) |
| `tests/test_playwright_physics_picker.py` | Session-driven tests | Create (~150 LOC) |
| `tests/test_playwright_simulation_picker.py` | Session-driven tests | Create (~150 LOC) |
| `tests/test_playwright_ibm_picker.py` | Session-driven tests | Create (~150 LOC) |
| `tests/test_file_service.py` | Add test pinning `.lgr → "lagrangian"` | Modify (~15 added LOC) |
| `docs/followups/2026-04-29-ui-deep-review-deferred.md` | Mark Section M complete; close out Section L tracking entry only | Modify |

---

## Why Helper Extraction Comes Before Any New Page

The pilot's "Lessons" section says: extract `fill_picker_input` "no later than the second follow-up page" to prevent user-visible string drift across the 6 pages. Two ways to satisfy that:

- **(a)** Wire page #1 inline (re-proving the pattern), then extract before page #2.
- **(b)** Extract first using the partitioning wrappers as reference, refactor partitioning, then wire all 6 pages with the helper.

This plan picks **(b)**. The pilot already proved the pattern on partitioning; re-proving on a second page would duplicate ~40 LOC that gets immediately deleted in the refactor. (b) is one less round-trip and one less commit per page. The deadline is satisfied: by the time any of the 6 pages lands, the helper exists.

---

## Task 1: Add `.lgr → "lagrangian"` to FileService taxonomy

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/file_service.py`
- Modify: `shyfem-ui/tests/test_file_service.py`

**Why this task:** `pages/ibm.py` filters the picker to `.lgr` files. Currently `_infer_file_type` falls through to `"other"` for `.lgr`, which would force the picker filter to be `file_types=["other"]` — a category that includes any unrecognized file and pollutes the dropdown. A dedicated `"lagrangian"` type is the clean answer.

- [ ] **Step 1: Add the failing test (red)**

Append to `shyfem-ui/tests/test_file_service.py` (locate the existing `TestInferFileType` class or equivalent — search the file for `_infer_file_type` and add a test method to the same class; if no class exists, add one at the end of the file):

```python
def test_infer_file_type_lagrangian_lgr(self):
    """`.lgr` (Lagrangian particle output) maps to 'lagrangian' file_type.

    Used by pages/ibm.py to filter the file picker to Lagrangian files
    only. Without this, .lgr files fall through to 'other' and would
    require the picker filter to include 'other' — which pollutes the
    dropdown with any unrecognized file type.
    """
    from shyfem_ui.services.file_service import FileService

    assert FileService._infer_file_type("trajectories.lgr") == "lagrangian"
    assert FileService._infer_file_type("OUTPUT/sim.lgr") == "lagrangian"
    # Case-insensitive on extension (the existing branches use .lower())
    assert FileService._infer_file_type("OUT.LGR") == "lagrangian"
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_service.py -v -k lagrangian`

Expected: FAIL with `assert "other" == "lagrangian"`.

- [ ] **Step 3: Add the `.lgr` branch to `_infer_file_type`**

In `shyfem-ui/shyfem_ui/services/file_service.py`, modify `_infer_file_type` (around line 329–350). Insert one new branch immediately AFTER the `if ext in (".shy", ".ext", ".flx", ".nc"): return "output"` branch and BEFORE the subdirectory hint:

```python
        if ext == ".lgr":
            return "lagrangian"
```

Final block should look like:

```python
        if ext in (".shy", ".ext", ".flx", ".nc"):
            return "output"
        if ext == ".lgr":
            return "lagrangian"
        # Subdirectory hints
        if len(parts) > 1 and parts[0].upper() == "INPUT":
            return "forcing"
        return "other"
```

- [ ] **Step 4: Run the test to confirm it passes (green)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_service.py -v -k lagrangian`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/file_service.py shyfem-ui/tests/test_file_service.py
git commit -m "feat(ui): add .lgr -> 'lagrangian' file_type in FileService

Required by Section M file-picker rollout — pages/ibm.py needs to
filter the picker dropdown to .lgr Lagrangian particle output files.
Without a dedicated type, .lgr falls through to 'other' which would
force ibm's picker filter to include any unrecognized file."
```

---

## Task 2: Alembic migration to backfill existing `.lgr` rows

**Files:**
- Create: `shyfem-ui/migrations/versions/<auto-generated-rev>_lagrangian_file_type.py`

**Why this task:** `_infer_file_type` runs at scan/insert time and the result is persisted on `ProjectFile.file_type`. Existing `.lgr` rows (if any) are stored as `"other"` and won't be updated by the new branch unless we either rescan or backfill. A one-shot UPDATE migration is the smallest reliable fix.

- [ ] **Step 1: Generate the migration scaffold**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m alembic revision -m "lagrangian file_type for lgr"`

Expected: prints `Generating .../migrations/versions/<rev>_lagrangian_file_type.py ... done`. Note the `<rev>` hash — it goes into the filename and the `revision = "..."` line of the new file. (Path is `migrations/versions/`, NOT `alembic/versions/` — `shyfem-ui/alembic.ini` `script_location` is `migrations`.)

- [ ] **Step 2: Pre-migration audit query (sanity-check the assumption)**

The migration UPDATE filter `file_type = 'other'` assumes all legacy `.lgr` rows are typed `'other'`. Verify before writing the body:

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "
from shyfem_ui.db.base import db_session
from sqlalchemy import text
with db_session() as db:
    rows = db.execute(text(
        \"SELECT DISTINCT file_type FROM project_files \"
        \"WHERE lower(rel_path) LIKE '%.lgr'\"
    )).all()
    print('Distinct file_types for .lgr rows:', [r[0] for r in rows])
"
```

Expected output: `[]` (no `.lgr` rows in dev DB) or `['other']` (only legacy rows). If the output contains anything else (e.g., `['output']` from an earlier mis-classification), STOP and adjust the migration filter — the backfill must cover all observed types, not just `'other'`.

- [ ] **Step 3: Fill in the migration body**

Open the generated file `shyfem-ui/migrations/versions/<rev>_lagrangian_file_type.py` and replace its body with this block, matching the project's existing migration style (typed `revision`/`down_revision`, `Sequence[str]` annotations) per `migrations/versions/c32b63d6ef96_add_project_files_table.py:8-18` and `25e58be88f8b_unique_project_file_rel_path.py:8-18`:

```python
"""lagrangian file_type for lgr

Backfills existing `.lgr` ProjectFile rows from file_type='other' to
'lagrangian' so pages/ibm.py's picker filter file_types=['lagrangian']
sees them. New .lgr inserts (post-Task-1) get the right type at scan
time; this migration only fixes legacy rows.

Revision ID: <auto-filled>
Revises: <auto-filled — the previous head>
Create Date: <auto-filled>
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "<auto-filled — leave the value Alembic generated>"
down_revision: Union[str, Sequence[str], None] = "<auto-filled — leave the value Alembic generated>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite-compatible case-insensitive LIKE via lower(rel_path).
    # Pre-migration audit (Step 2) confirmed all legacy .lgr rows are
    # currently typed 'other'; if the audit found other types, widen
    # the filter or run additional UPDATE statements before this one.
    op.execute(
        "UPDATE project_files SET file_type = 'lagrangian' "
        "WHERE file_type = 'other' AND lower(rel_path) LIKE '%.lgr'"
    )


def downgrade() -> None:
    """Downgrade schema.

    WARNING: this reverts ALL `lagrangian`-typed `.lgr` rows back to
    `'other'`, including any inserted by the new `_infer_file_type`
    branch AFTER Task 1 landed. Only safe in dev with a fresh DB. After
    downgrading you must either re-seed test data or trigger a rescan
    (`FileService.scan_project(...)`) to restore correct classifications;
    otherwise Task 1's `test_infer_file_type_lagrangian_lgr` will
    appear to "regress" because the rows were stomped, not the code.
    """
    op.execute(
        "UPDATE project_files SET file_type = 'other' "
        "WHERE file_type = 'lagrangian' AND lower(rel_path) LIKE '%.lgr'"
    )
```

Leave the `revision` / `down_revision` strings exactly as Alembic generated them in Step 1. Do NOT hand-edit those values.

- [ ] **Step 3: Run the migration against the dev DB**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m alembic upgrade head`

Expected: `Running upgrade <prev_rev> -> <new_rev>, lagrangian file_type for lgr` printed. No errors.

- [ ] **Step 4: Confirm the test suite still passes (no migration regression)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_service.py -v`

Expected: all pass, including Task 1's new lagrangian test.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/migrations/versions/*lagrangian_file_type.py
git commit -m "chore(db): backfill .lgr ProjectFile rows to 'lagrangian'

One-shot UPDATE migration. Required after the FileService taxonomy
change in the previous commit — _infer_file_type only runs at
scan/insert time, so legacy .lgr rows would stay at file_type='other'
and be invisible to pages/ibm.py's picker filter."
```

---

## Task 3: Extract `fill_picker_input` helper into `components/file_picker.py`

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/file_picker.py`
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py`
- Modify: `shyfem-ui/tests/test_file_picker_logic.py`
- Modify: `shyfem-ui/tests/test_partitioning_file_picker.py`
- Create: `shyfem-ui/tests/_test_helpers.py` (closure-unwrap helper, per Test Infrastructure Note A)

**Why this task:** the pilot's `_fill_bas` and `_fill_grd` wrappers in `partitioning.py:196-235` duplicate ~40 LOC of identical structure: `proj.get()` → `resolve_picker_path` → on-failure `logger.warning` + `ui.notification_show` → on-success `ui.update_text`. The only difference between them is the `target_id` string and the log-message field name. Per spec lessons, this MUST be extracted before any of the 6 follow-up pages copy it.

**Helper contract (per Test Infrastructure Notes E, H, I):**
- Signature: `fill_picker_input(target_id: PickerTargetId, project: ProjectContext | None, rel_path: str) -> None`
- `target_id` is a `Literal[...]` covering the 6 known input ids (catches typos at type-check time).
- `project` is the unwrapped dict, NOT a reactive container. Lambdas at call sites do `active_project.get() if active_project else None`.
- A page-server can opt to log a wiring-bug WARNING at server entry if `active_project is None`. The helper itself only knows about the unwrapped value.

- [ ] **Step 1: Add the failing helper test (red)**

Append to `shyfem-ui/tests/test_file_picker_logic.py`. The helper calls Shiny `ui.update_text` and `ui.notification_show`, which require an active session. Test the resolve-and-branch logic by patching those two functions:

```python
class TestFillPickerInput:
    """Tests for fill_picker_input — the extracted wrapper body.

    Helper takes the unwrapped `project: ProjectContext | None` (NOT a
    reactive container — see Test Infrastructure Note E). Lambdas at
    call sites do `active_project.get() if active_project else None`.

    Patch ui.update_text and ui.notification_show so the test runs
    without a Shiny session.
    """

    def _make_proj(self, tmp_path, project_id: int = 7) -> dict:
        return {
            "id": project_id, "name": "p", "work_dir": str(tmp_path),
            "description": None,
            "grids": [], "simulations": [], "files": [],
        }

    def _patch_ui(self, monkeypatch) -> tuple[list, list]:
        from shyfem_ui.components import file_picker
        update_calls: list = []
        notify_calls: list = []
        monkeypatch.setattr(
            file_picker.ui, "update_text",
            lambda tid, value: update_calls.append((tid, value)),
        )
        monkeypatch.setattr(
            file_picker.ui, "notification_show",
            lambda *a, **kw: notify_calls.append((a, kw)),
        )
        return update_calls, notify_calls

    def test_fill_picker_input_success_calls_update_text(self, tmp_path, monkeypatch):
        """Happy path: valid project + rel_path -> ui.update_text is called
        with the absolute path; no notification, no warning.
        """
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path)

        file_picker.fill_picker_input("bas_path", proj, "BAS/sim.bas")

        assert len(update_calls) == 1
        target_id, value = update_calls[0]
        assert target_id == "bas_path"
        assert value == str((tmp_path / "BAS" / "sim.bas").resolve())
        assert notify_calls == []

    def test_fill_picker_input_silent_when_no_project(self, monkeypatch):
        """No-project branch: silent return — no log, no notify, no update_text."""
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)

        file_picker.fill_picker_input("bas_path", None, "anything")

        assert update_calls == []
        assert notify_calls == []

    def test_fill_picker_input_silent_when_empty_rel_path(self, tmp_path, monkeypatch):
        """Empty-rel_path branch: silent return.

        The picker dropdown's empty placeholder fires on_selected with
        rel_path='' on initial render. The wrapper must NOT log/notify
        for this — only programmer-error cases.
        """
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path)

        file_picker.fill_picker_input("bas_path", proj, "")

        assert update_calls == []
        assert notify_calls == []

    def test_fill_picker_input_warns_on_traversal(self, tmp_path, monkeypatch, caplog):
        """Resolution-failure branch: logs WARNING + shows toast.

        Filtered to logger 'shyfem_ui.components.file_picker' so the
        helper's own warning AND resolve_picker_path's warning are
        captured under the same logger.
        """
        import logging
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path, project_id=42)

        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            file_picker.fill_picker_input("bas_path", proj, "../../etc/passwd")

        assert update_calls == []
        assert len(notify_calls) == 1
        assert notify_calls[0][1].get("type") == "warning"
        recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
        assert len(recs) >= 2  # one from resolve_picker_path, one from fill_picker_input
        assert any("bas_path" in r.getMessage() for r in recs)

    def test_fill_picker_input_target_id_appears_in_log(self, tmp_path, monkeypatch, caplog):
        """Pin the log-message contract: target_id MUST appear in the wrapper's warning.

        Ops uses target_id to know which field on which page failed.
        """
        import logging
        from shyfem_ui.components import file_picker
        update_calls, notify_calls = self._patch_ui(monkeypatch)
        proj = self._make_proj(tmp_path, project_id=99)

        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            # Use one of the 6 known PickerTargetId Literals
            file_picker.fill_picker_input("lgr_path", proj, "/etc/passwd")

        wrapper_recs = [
            r for r in caplog.records
            if r.name == "shyfem_ui.components.file_picker"
            and "target=" in r.getMessage()
        ]
        assert len(wrapper_recs) == 1
        assert "lgr_path" in wrapper_recs[0].getMessage()
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_picker_logic.py::TestFillPickerInput -v`

Expected: 5 fails with `AttributeError: module 'shyfem_ui.components.file_picker' has no attribute 'fill_picker_input'`.

- [ ] **Step 3: Implement `fill_picker_input` in `components/file_picker.py`**

In `shyfem-ui/shyfem_ui/components/file_picker.py`, add the `Literal` type alias and the helper IMMEDIATELY AFTER the `resolve_picker_path` function (which already exists from the pilot). The new code goes between `resolve_picker_path`'s closing `return str(resolved)` and the `@module.ui` decorator for `file_picker_ui`. Search for `def file_picker_ui(` to locate the boundary.

First, add `Literal` to the existing `typing` import (top of file, around line 6):

```python
from typing import TYPE_CHECKING, Literal
```

Then insert this block:

```python
# Set of input ids that the file picker can target. Literal-typed so
# typos at call sites (e.g. fill_picker_input("bad_path", ...)) surface
# at type-check time rather than as silent ui.update_text("bad_path",
# ...) no-ops.
PickerTargetId = Literal[
    "bas_path", "grd_path", "shy_path",
    "str_path", "input_file", "lgr_path",
]


def fill_picker_input(
    target_id: PickerTargetId,
    project: "ProjectContext | None",
    rel_path: str,
) -> None:
    """Resolve a picker selection and write it to a Shiny text input.

    Bridges resolve_picker_path's pure logic to the session-bound
    ui.update_text + ui.notification_show calls. Silent on the benign
    empty-state (no project / empty rel_path); logs a WARNING naming
    target_id and shows a warning toast when a non-empty selection
    fails to resolve. See resolve_picker_path's docstring for the
    containment / traversal contract.

    Args:
        target_id: Shiny text input id (no namespace prefix).
        project: unwrapped ProjectContext, or None for benign empty-state.
            Callers pass `active_project.get() if active_project else None`.
        rel_path: project-relative path from the picker, "" for the
            empty-placeholder selection.
    """
    absolute = resolve_picker_path(project, rel_path)
    if absolute is None:
        # Only log/notify for actionable mismatches (project loaded +
        # non-empty rel_path that fails resolution). Empty-state is
        # the picker's idle baseline and not an error.
        if project is not None and rel_path:
            logger.warning(
                "Picker selection %r could not be resolved for "
                "project %r (target=%s, work_dir missing or "
                "traversal guard rejected)",
                rel_path, project.get("id"), target_id,
            )
            ui.notification_show(
                "Could not resolve selected file. Try re-selecting "
                "after the project finishes loading.",
                type="warning", duration=5,
            )
        return
    ui.update_text(target_id, value=absolute)
```

`ProjectContext` is already in the `TYPE_CHECKING` block (added during the pilot). `Literal` is a stdlib import — `from typing import Literal` is the only addition. No runtime cycle.

- [ ] **Step 4: Run the helper tests to confirm they pass (green)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_picker_logic.py -v`

Expected: 11 passed (6 pre-existing `resolve_picker_path` tests + 5 new `fill_picker_input` tests).

- [ ] **Step 5: Refactor `partitioning.py` to use the helper**

In `shyfem-ui/shyfem_ui/pages/partitioning.py`, replace lines 187–250 (the comment block, `_fill_bas`, `_fill_grd`, and the two `file_picker_server` calls) with:

```python
    # File pickers delegate the resolve/log/notify branching to
    # fill_picker_input (see its docstring in components/file_picker.py).
    file_picker_server(
        "fp_bas",
        project_id=project_id_val,
        file_types=["basin"],
        on_selected=lambda rel: fill_picker_input(
            "bas_path",
            active_project.get() if active_project else None,
            rel,
        ),
    )
    file_picker_server(
        "fp_grd",
        project_id=project_id_val,
        file_types=["grid"],
        on_selected=lambda rel: fill_picker_input(
            "grd_path",
            active_project.get() if active_project else None,
            rel,
        ),
    )
```

Also DELETE the `if active_project is None: logger.warning(...)` server-entry block at `partitioning.py:148-157` (and the multi-line comment immediately preceding it justifying the entry-time check). After the helper extraction, that warning is no longer load-bearing — the helper handles `None` projects silently as benign empty-state. If a future page wants to surface the wiring-bug case, it can add a one-line warning in its own server, but the pattern is no longer canonical.

Then update the imports block at lines 12–16. Replace:

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    resolve_picker_path,
)
```

with:

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

The `resolve_picker_path` import is removed because the lambdas delegate to `fill_picker_input` which calls it internally. The `cast` import (line 5: `from typing import TYPE_CHECKING, cast`) and the `if TYPE_CHECKING: from shyfem_ui.services.project_context import ProjectContext` block (line 30–31) are also no longer needed in `partitioning.py` since the only `cast(...)` and `ProjectContext` reference were inside `_fill_bas`/`_fill_grd`. Verify by grep before deletion:

```bash
cd /home/razinka/shyfem/shyfem-ui && grep -nE "\bcast\b|ProjectContext" shyfem_ui/pages/partitioning.py
```

Expected: no remaining matches after the refactor. If matches remain, leave the imports.

- [ ] **Step 6: Update the partitioning wiring assertion test**

The pilot's wiring guard in `tests/test_partitioning_file_picker.py` (the `TestModuleImports` class) asserts `file_picker_server(` is called twice with the right `file_types`. After this refactor it still is — but the wrapper-pattern assertion would fail (the `_fill_bas`/`_fill_grd` named functions no longer exist).

Open `shyfem-ui/tests/test_partitioning_file_picker.py` and update the `test_partitioning_imports_and_wires_file_picker_server` method. Replace any assertion that references `_fill_bas`, `_fill_grd`, or `received active_project=None` with an assertion that the page imports `fill_picker_input`:

```python
        # After Section M extraction: per-page wrappers are gone; the
        # page now delegates via lambdas to the shared
        # fill_picker_input helper.
        assert hasattr(part_mod, "fill_picker_input"), (
            "partitioning.py must do `from ...file_picker import "
            "fill_picker_input`"
        )
        assert part_mod.fill_picker_input is fp_mod.fill_picker_input, (
            "partitioning.fill_picker_input must be the SAME object as "
            "components.file_picker.fill_picker_input"
        )
        assert "fill_picker_input(" in src, (
            "partitioning_server must call fill_picker_input(...) "
            "in its on_selected= lambdas"
        )
        # The active_project=None warning was a per-page wrapper detail;
        # after extraction it's the helper's job. No longer asserted here.
```

If the existing test has the line `assert "received active_project=None" in src`, DELETE that line. The active_project=None server-entry warning was specific to the inline-wrapper era and no longer fires in `partitioning_server`. The helper itself is silent when given `None` because the empty-state is benign, and pages can choose whether to log a wiring-bug warning at the top of their server.

- [ ] **Step 7: Run the full test sweep**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_picker_logic.py tests/test_partitioning_file_picker.py tests/test_partitioning.py tests/test_partitioning_logic.py -v`

Expected: all pass. The pilot's helper tests (6) + new helper tests (5) + partitioning unit tests (2) + partitioning regression tests = green.

- [ ] **Step 8: Run the partitioning Playwright tests to confirm no behavioural regression**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_partitioning_picker.py -v --override-ini="addopts="`

Expected: 5 passed (or 5 skipped if Playwright browsers are not installed). No failures. The behavioural contract is identical pre/post refactor.

- [ ] **Step 9: F401 sweep**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/components/file_picker.py shyfem_ui/pages/partitioning.py`

Expected: clean.

- [ ] **Step 10: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/components/file_picker.py shyfem-ui/shyfem_ui/pages/partitioning.py shyfem-ui/tests/test_file_picker_logic.py shyfem-ui/tests/test_partitioning_file_picker.py
git commit -m "feat(ui): extract fill_picker_input helper; refactor partitioning

Pulls the per-page _fill_X wrapper bodies (resolve+log+notify+
update_text) into components/file_picker.py:fill_picker_input.
Refactors partitioning.py's two wrappers into one-line lambdas that
delegate. Adds 5 helper tests covering success / no-project /
empty-rel_path / traversal-warning / target_id-in-log branches.

Required before any of the 6 Section M pages land — without
extraction, user-visible strings (warning toast text, log message
fields) would drift across pages and force a painful retrofit."
```

---

## Task 4: Wire picker for `pages/grid_prep.py` (`.grd` → `"grid"`)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/grid_prep.py`
- Create: `shyfem-ui/tests/test_grid_prep_file_picker.py`
- Create: `shyfem-ui/tests/test_playwright_grid_prep_picker.py`

- [ ] **Step 1: Add picker imports**

In `shyfem-ui/shyfem_ui/pages/grid_prep.py`, add to the existing imports (locate the `from shyfem_ui.components.X import ...` block and append a new import for the file picker):

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

- [ ] **Step 2: Add picker UI above the existing text input**

In `grid_prep_ui` (around lines 53–57), find the `ui.input_text("grd_path", ...)` block. Insert a `file_picker_ui` call IMMEDIATELY before it:

```python
                file_picker_ui("fp_grd", label="Pick grid from project"),
                ui.input_text(
                    "grd_path",
                    # ... existing args unchanged
                ),
```

- [ ] **Step 3: Add `project_id_val` reactive value at the top of `grid_prep_server`**

Locate `def grid_prep_server(...)` (line 118). Immediately AFTER the `def` line and any existing docstring, insert:

```python
    # Reactive value driven by `_on_project_changed`; consumed by the
    # file picker to filter dropdown choices to the active project.
    project_id_val: reactive.Value[int | None] = reactive.value(None)
```

- [ ] **Step 4: Modify `_on_project_changed` to update `project_id_val` + add `reactive.isolate()` + empty-guards**

Locate `_on_project_changed` (lines 130–142). Replace the body with the canonical pattern. The exact replacement depends on the existing body structure — read the current code first, then translate.

For grid_prep's likely structure (auto-fills `grd_path` from `proj["grids"][0]["grd_file"]`):

```python
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            project_id_val.set(None)
            return
        project_id_val.set(proj.get("id"))
        work = proj["work_dir"]
        if proj["grids"]:
            grid = proj["grids"][0]
            with reactive.isolate():
                grd_empty = not input.grd_path()
            if grid.get("grd_file") and grd_empty:
                ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))
```

If the existing code reads OTHER inputs inside the effect (besides `input.grd_path()`), wrap THOSE in `reactive.isolate()` too — the goal is that NO `input.X()` call inside the effect registers as a dependency. Read the existing block first to find them.

- [ ] **Step 4b: Modify `_on_tutorial_context` (lines 145–155) — isolate-only, no empty-guard**

Per Test Infrastructure Note F, `_on_tutorial_context` fires on explicit user navigation ("Open in Grid Prep" button) and SHOULD override picker selections. Apply only `reactive.isolate()` around `input.X()` reads — do NOT add empty-guards:

```python
    @reactive.effect
    def _on_tutorial_context():
        # ... existing tutorial_context.get() and target computation ...
        # Wrap any input.X() reads in reactive.isolate(). Leave
        # ui.update_text("grd_path", value=...) UNCONDITIONAL — tutorial
        # navigation is intentional override, not reactive churn.
```

- [ ] **Step 5: Add the `file_picker_server` call**

After `_on_project_changed`, add:

```python
    file_picker_server(
        "fp_grd",
        project_id=project_id_val,
        file_types=["grid"],
        on_selected=lambda rel: fill_picker_input("grd_path", active_project.get() if active_project else None, rel),
    )
```

- [ ] **Step 6: Verify the page imports cleanly + F401 clean**

Run:
```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import grid_prep; print('OK')"
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/pages/grid_prep.py
```

Expected: `OK` and clean ruff.

- [ ] **Step 7: Create the unit test file**

Create `shyfem-ui/tests/test_grid_prep_file_picker.py`:

```python
"""Unit tests for grid_prep page file-picker UI rendering and wiring."""

class TestPickerUiRenders:
    def test_picker_renders_above_grd_path(self):
        """fp_grd <select> appears in HTML before #test-grd_path."""
        from shyfem_ui.pages.grid_prep import grid_prep_ui

        tag = grid_prep_ui("test")
        html = str(tag)

        assert 'id="test-fp_grd-file_select"' in html, (
            "expected picker <select id='test-fp_grd-file_select'>"
        )
        picker_pos = html.find('id="test-fp_grd-file_select"')
        input_pos = html.find('id="test-grd_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos, (
            "fp_grd picker must render before grd_path text input"
        )


class TestModuleImports:
    def test_grid_prep_imports_and_wires_file_picker_server(self):
        import shyfem_ui.pages.grid_prep as page_mod

        from shyfem_ui.components import file_picker as fp_mod

        from tests._test_helpers import get_server_source

        # Identity guards
        assert hasattr(page_mod, "file_picker_server")
        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert hasattr(page_mod, "file_picker_ui")
        assert hasattr(page_mod, "fill_picker_input")
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        # Wiring assertion
        src = get_server_source(page_mod, "grid_prep_server")
        assert src.count("file_picker_server(") >= 1, (
            "expected at least 1 file_picker_server call in grid_prep_server"
        )
        assert 'file_types=["grid"]' in src, (
            "expected file_types=['grid'] for the .grd picker"
        )
        # Pin the helper-delegation lambda to prevent regressions
        # to per-page _fill_X wrappers.
        assert 'fill_picker_input("grd_path"' in src, (
            "expected fill_picker_input('grd_path', ...) lambda in grid_prep_server"
        )
        # Pin the reactive.isolate guard pattern carried over from pilot
        assert "reactive.isolate()" in src, (
            "expected reactive.isolate() in _on_project_changed to "
            "prevent input keystrokes from re-firing the effect"
        )
```

- [ ] **Step 8: Run the unit tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_prep_file_picker.py -v`

Expected: 2 passed.

- [ ] **Step 9: Create the Playwright test file**

Create `shyfem-ui/tests/test_playwright_grid_prep_picker.py`:

```python
"""Playwright tests for grid_prep file-picker session-driven behaviour."""

import pytest


@pytest.mark.e2e
class TestGridPrepPickerNoProject:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        """Per Test Infrastructure Note B — reset session-scoped state.

        pw_page + active_project are session-scoped; without this reset
        the first test inherits whatever state the LAST test of the
        alphabetically-prior file left set, making test order
        load-bearing.
        """
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project(null);
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_picker_shows_no_files_available_when_no_project(
        self, pw_page, live_server,
    ):
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(1000)

        select = pw_page.locator('#grid_prep-fp_grd-file_select')
        select.wait_for(state="attached", timeout=5000)
        option_texts = pw_page.locator(
            '#grid_prep-fp_grd-file_select option'
        ).all_inner_texts()
        assert any("No files available" in t for t in option_texts), (
            f"expected 'No files available' placeholder, got: {option_texts!r}"
        )

    def test_typing_into_grd_path_is_not_clobbered_by_reactive_effect(
        self, pw_page, live_server,
    ):
        """reactive.isolate guard regression."""
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(800)

        grd_input = pw_page.locator('#grid_prep-grd_path')
        grd_input.wait_for(state="attached", timeout=5000)
        grd_input.fill("/tmp/manual-typed.grd")
        pw_page.wait_for_timeout(800)

        actual = grd_input.input_value()
        assert actual == "/tmp/manual-typed.grd", (
            f"grd_path was clobbered by a re-fired reactive effect: {actual!r}"
        )

    def test_empty_guard_preserves_user_input(self, pw_page, live_server):
        """`if not input.grd_path()` regression — project re-emit must
        not clobber user-entered values.
        """
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(800)

        grd_input = pw_page.locator('#grid_prep-grd_path')
        grd_input.fill("/tmp/preset-value.grd")
        pw_page.wait_for_timeout(300)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p',
                work_dir: '/tmp/p',
                description: null,
                grids: [{name: 'g', grd_file: 'newgrid.grd', bas_file: 'g.bas'}],
                simulations: [],
                files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip(
                "test_app.py does not expose __test_set_active_project"
            )
        pw_page.wait_for_timeout(800)

        assert grd_input.input_value() == "/tmp/preset-value.grd", (
            f"empty-guard failed; grd_path was overwritten to "
            f"{grd_input.input_value()!r}"
        )

    def test_picker_callback_warns_on_traversal(self, pw_page, live_server):
        """fill_picker_input traversal-failure branch fires a warning toast."""
        pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
        pw_page.wait_for_timeout(800)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p',
                work_dir: '/tmp/p',
                description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.wait_for_timeout(500)

        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'grid_prep-fp_grd-file_select', '/etc/passwd',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(800)

        warning_toasts = pw_page.locator(
            '.shiny-notification.shiny-notification-warning'
        ).count()
        assert warning_toasts >= 1, (
            f"expected at least 1 warning notification, got {warning_toasts}"
        )

        grd_input = pw_page.locator('#grid_prep-grd_path')
        assert grd_input.input_value() == "", (
            f"expected grd_path empty (wrapper rejected the selection), "
            f"got {grd_input.input_value()!r}"
        )
```

- [ ] **Step 10: Run the Playwright tests (manual, not in default suite)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_grid_prep_picker.py -v --override-ini="addopts="`

Expected: 4 passed (or skipped if Playwright unavailable). The `data-target` selector value (`"Grid Prep"`) must match the page's display name in the sidebar — verify by opening `shyfem_ui/app.py` and grepping for `"Grid Prep"`. If the actual name is different (e.g., `"Grid Preparation"`), update the locator.

- [ ] **Step 11: Run regression tests for grid_prep**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_prep.py tests/test_grid_prep_logic.py -q`

(Adjust filenames to whatever exists for grid_prep — `ls tests/test_grid_prep*.py` to confirm.)

Expected: all pre-existing tests pass.

- [ ] **Step 12: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/grid_prep.py shyfem-ui/tests/test_grid_prep_file_picker.py shyfem-ui/tests/test_playwright_grid_prep_picker.py
git commit -m "feat(ui): wire file_picker for grd_path in grid_prep

Adds file_picker_ui above grd_path, file_picker_server with
file_types=['grid'], and a one-line lambda that delegates to
fill_picker_input. Adds reactive.isolate() + empty-guard to
_on_project_changed (was missing both — pilot lessons applied).

Test coverage: UI render + import-style/wiring guards (unit), plus
4 Playwright tests (placeholder, isolate regression, empty-guard,
traversal-warning toast)."
```

---

## Task 5: Wire picker for `pages/postprocess.py` (`.shy/.nc/.ext/.flx` → `"output"`)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/postprocess.py`
- Create: `shyfem-ui/tests/test_postprocess_file_picker.py`
- Create: `shyfem-ui/tests/test_playwright_postprocess_picker.py`

**Page-specific note:** the existing `_on_project_changed` (lines 240–248) sets `shy_path` to `proj["work_dir"]` (a directory, not a file). The empty-guard rule still applies — if the input is non-empty (which it will be after first project load), don't auto-fill. The picker's user-driven click overwrites unconditionally on success, which is the expected UX.

- [ ] **Step 1: Add picker imports**

In `shyfem-ui/shyfem_ui/pages/postprocess.py`:

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

- [ ] **Step 2: Add picker UI above the existing text input**

In `postprocess_ui`, find the `ui.input_text("shy_path", ...)` block (line 127). Insert before it:

```python
                file_picker_ui("fp_shy", label="Pick output file from project"),
```

- [ ] **Step 3: Add `project_id_val` + `last_project_id` reactive values at the top of `postprocess_server`**

Locate `def postprocess_server(...)` (line 233). After the def + docstring:

```python
    project_id_val: reactive.Value[int | None] = reactive.value(None)
    # Tracks the last-seen project id so _on_project_changed can
    # distinguish "metadata refresh of same project" (preserve user
    # input) from "user switched to different project" (force re-fill).
    # See Test Infrastructure Note G — postprocess's prefill is the
    # work_dir DIRECTORY, not a project-tied file, so a naive
    # empty-guard would leak project A's directory into project B.
    last_project_id: reactive.Value[int | None] = reactive.value(None)
```

- [ ] **Step 4: Modify `_on_project_changed` (lines 241–248) — apply Test Infrastructure Note G**

Read the existing effect first (`sed -n '241,248p' shyfem-ui/shyfem_ui/pages/postprocess.py`), then translate to:

```python
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            project_id_val.set(None)
            last_project_id.set(None)
            return
        pid = proj.get("id")
        project_id_val.set(pid)
        project_changed = last_project_id.get() != pid
        last_project_id.set(pid)
        work = proj["work_dir"]
        with reactive.isolate():
            shy_empty = not input.shy_path()
        # Force re-fill on actual project change (not just metadata
        # refresh). Without project_changed, switching from project A
        # to B would leak A's work_dir into shy_path until the user
        # manually clears it.
        if shy_empty or project_changed:
            ui.update_text("shy_path", value=work)
```

- [ ] **Step 4b: Modify `_on_tutorial_context` (lines 251+) — isolate-only, no empty-guard**

Per Test Infrastructure Note F, tutorial overrides are intentional. Wrap any `input.X()` reads inside `reactive.isolate()` but DO NOT add empty-guards:

```python
    @reactive.effect
    def _on_tutorial_context():
        # ... existing tutorial_context.get() logic ...
        # If the existing body reads input.shy_path() or other inputs
        # for branching, wrap those reads in reactive.isolate(). Leave
        # ui.update_text calls unconditional — tutorial nav is an
        # explicit user action and should override.
```

- [ ] **Step 5: Add the `file_picker_server` call**

After `_on_project_changed`:

```python
    file_picker_server(
        "fp_shy",
        project_id=project_id_val,
        file_types=["output"],
        on_selected=lambda rel: fill_picker_input("shy_path", active_project.get() if active_project else None, rel),
    )
```

- [ ] **Step 6: Verify imports + F401**

Run:
```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import postprocess; print('OK')"
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/pages/postprocess.py
```

Expected: `OK` and clean.

- [ ] **Step 7: Create the unit test file**

Create `shyfem-ui/tests/test_postprocess_file_picker.py`:

```python
"""Unit tests for postprocess page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_shy_path(self):
        from shyfem_ui.pages.postprocess import postprocess_ui

        tag = postprocess_ui("test")
        html = str(tag)

        assert 'id="test-fp_shy-file_select"' in html
        picker_pos = html.find('id="test-fp_shy-file_select"')
        input_pos = html.find('id="test-shy_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_postprocess_wires_file_picker_server(self):
        import shyfem_ui.pages.postprocess as page_mod

        from shyfem_ui.components import file_picker as fp_mod

        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "postprocess_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["output"]' in src
        assert 'fill_picker_input("shy_path"' in src
        assert "reactive.isolate()" in src
```

- [ ] **Step 8: Run unit tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_postprocess_file_picker.py -v`

Expected: 2 passed.

- [ ] **Step 9: Create the Playwright test file**

Create `shyfem-ui/tests/test_playwright_postprocess_picker.py` — copy the structure from Task 4 Step 9, but with these substitutions:
- All `grid_prep` → `postprocess` (page-name occurrences)
- `data-nav='Grid Prep'` → `data-nav='Post-Process'` (note hyphen; verified against `app.py:75`)
- `#grid_prep-fp_grd-file_select` → `#postprocess-fp_shy-file_select`
- `#grid_prep-grd_path` → `#postprocess-shy_path`
- `/tmp/manual-typed.grd` → `/tmp/manual-typed.shy`
- `/tmp/preset-value.grd` → `/tmp/preset-value.shy`
- The empty-guard test: skip the second part of the test (the project re-emit) because postprocess's prefill is the work_dir, not a file path — set the input to a NON-WORK_DIR string and verify it survives re-emit.

The exact content for the postprocess Playwright file:

```python
"""Playwright tests for postprocess file-picker session-driven behaviour."""

import pytest


@pytest.mark.e2e
class TestPostprocessPickerNoProject:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        """Per Test Infrastructure Note B — reset session-scoped state."""
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project(null);
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_picker_shows_no_files_available_when_no_project(
        self, pw_page, live_server,
    ):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(1000)

        select = pw_page.locator('#postprocess-fp_shy-file_select')
        select.wait_for(state="attached", timeout=5000)
        option_texts = pw_page.locator(
            '#postprocess-fp_shy-file_select option'
        ).all_inner_texts()
        assert any("No files available" in t for t in option_texts)

    def test_typing_into_shy_path_is_not_clobbered(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(800)

        shy_input = pw_page.locator('#postprocess-shy_path')
        shy_input.wait_for(state="attached", timeout=5000)
        shy_input.fill("/tmp/manual-typed.shy")
        pw_page.wait_for_timeout(800)

        assert shy_input.input_value() == "/tmp/manual-typed.shy"

    def test_empty_guard_preserves_user_input(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(800)

        shy_input = pw_page.locator('#postprocess-shy_path')
        shy_input.fill("/tmp/preset-value.shy")
        pw_page.wait_for_timeout(300)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: '/tmp/different-workdir',
                description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.wait_for_timeout(800)

        assert shy_input.input_value() == "/tmp/preset-value.shy", (
            "empty-guard failed; shy_path was overwritten with project work_dir"
        )

    def test_picker_callback_warns_on_traversal(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(800)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: '/tmp/p',
                description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.wait_for_timeout(500)

        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'postprocess-fp_shy-file_select', '/etc/passwd',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(800)

        warnings = pw_page.locator(
            '.shiny-notification.shiny-notification-warning'
        ).count()
        assert warnings >= 1
```

- [ ] **Step 10: Run Playwright + regression**

Run:
```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_postprocess_picker.py -v --override-ini="addopts="
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_postprocess.py tests/test_postprocess_logic.py -q
```

Expected: Playwright 4 passed (or skipped); regression all pass.

- [ ] **Step 11: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/postprocess.py shyfem-ui/tests/test_postprocess_file_picker.py shyfem-ui/tests/test_playwright_postprocess_picker.py
git commit -m "feat(ui): wire file_picker for shy_path in postprocess

Adds file_picker_ui above shy_path, file_picker_server with
file_types=['output'] (matches .shy/.nc/.ext/.flx), and a lambda
delegating to fill_picker_input. Adds reactive.isolate() + empty-guard
to _on_project_changed (was missing both)."
```

---

## Task 6: Wire picker for `pages/simulation.py` (`.str` → `"str"`)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/simulation.py`
- Create: `shyfem-ui/tests/test_simulation_file_picker.py`
- Create: `shyfem-ui/tests/test_playwright_simulation_picker.py`

**Page-specific note:** simulation.py has TWO existing reactive effects: `_on_project_changed` (lines 151–162) AND `_on_tutorial_context` (lines 165–176). BOTH may set `str_path`. Apply `reactive.isolate()` + empty-guard to BOTH effects (not just the first) — otherwise tutorial loads can clobber picker selections.

- [ ] **Step 1: Add picker imports**

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

- [ ] **Step 2: Add picker UI above `ui.input_text("str_path", ...)` (line 35–39)**

```python
                file_picker_ui("fp_str", label="Pick STR file from project"),
```

- [ ] **Step 3: REUSE the existing `project_id_reactive` (do NOT add a duplicate)**

Per Test Infrastructure Note D: `simulation.py:183` already declares `project_id_reactive = reactive.value(None)` and `_sync_project_id` (lines 186–190) which feeds `str_editor_server` (line 194). Reuse it for the picker. Do NOT add a new `project_id_val` — that would create two redundant reactives, and removing `_sync_project_id` would break the STR editor's project-aware filtering.

No code change in this step — just confirm by reading `simulation.py:183-194`. The picker call in Step 5 will pass `project_id=project_id_reactive`.

- [ ] **Step 4: Modify both `_on_project_changed` and `_on_tutorial_context`**

For `_on_project_changed` (lines 152–162) — apply `reactive.isolate()` AND empty-guard (project metadata refreshes can fire this; protect picker selections):

```python
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        # NOTE: project_id_reactive is updated by the existing
        # _sync_project_id effect (lines 186-190); do NOT duplicate
        # that work here.
        work_dir = proj["work_dir"]
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                with reactive.isolate():
                    str_empty = not input.str_path()
                if str_empty:
                    ui.update_text(
                        "str_path",
                        value=str(Path(work_dir) / sim["str_file"]),
                    )
```

For `_on_tutorial_context` (lines 166–176) — per Test Infrastructure Note F, apply ONLY `reactive.isolate()`, NOT the empty-guard. Tutorial-context navigation is an explicit user action ("Open in Simulation" button); the user expects the tutorial's STR file to load and an empty-guard would silently break that. Read the existing body, then wrap any `input.X()` reads in `reactive.isolate()` (to prevent dependency-loop re-fires), but leave `ui.update_text` unconditional:

```python
    @reactive.effect
    def _on_tutorial_context():
        # ... existing logic that reads tutorial_context.get() ...
        # ... existing logic that computes the str_path target ...
        # Wrap any other input.X() reads in reactive.isolate() so the
        # effect only fires on tutorial_context changes, not on every
        # keystroke in dependent inputs.
        # Tutorial overrides are intentional: NO empty-guard here.
        ui.update_text("str_path", value=<computed_target_path>)
```

- [ ] **Step 5: Add the `file_picker_server` call**

```python
    file_picker_server(
        "fp_str",
        project_id=project_id_reactive,  # reuse existing reactive (Note D)
        file_types=["str"],
        on_selected=lambda rel: fill_picker_input(
            "str_path",
            active_project.get() if active_project else None,
            rel,
        ),
    )
```

- [ ] **Step 6: Verify + F401**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import simulation; print('OK')"
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/pages/simulation.py
```

- [ ] **Step 7: Create unit test file**

Create `shyfem-ui/tests/test_simulation_file_picker.py`:

```python
"""Unit tests for simulation page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_str_path(self):
        from shyfem_ui.pages.simulation import simulation_ui

        tag = simulation_ui("test")
        html = str(tag)

        assert 'id="test-fp_str-file_select"' in html
        picker_pos = html.find('id="test-fp_str-file_select"')
        input_pos = html.find('id="test-str_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_simulation_wires_file_picker_server(self):
        import shyfem_ui.pages.simulation as page_mod

        from shyfem_ui.components import file_picker as fp_mod

        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "simulation_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["str"]' in src
        assert 'fill_picker_input("str_path"' in src
        # _on_project_changed gets isolate+empty-guard.
        # _on_tutorial_context (simulation.py:166-176) does not read
        # input.X() so it adds no isolate block. Pin to >= 1.
        assert src.count("reactive.isolate()") >= 1, (
            "expected reactive.isolate() in _on_project_changed"
        )
        # Per Test Infrastructure Note D, simulation reuses the
        # pre-existing project_id_reactive (which feeds str_editor_server).
        # Pin that the page did NOT introduce a duplicate project_id_val
        # that would orphan str_editor_server.
        assert "project_id=project_id_reactive" in src, (
            "simulation must reuse project_id_reactive (existing reactive "
            "feeding str_editor_server), not introduce a new project_id_val"
        )
```

- [ ] **Step 8: Run unit tests**

`cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_simulation_file_picker.py -v`

Expected: 2 passed.

- [ ] **Step 9: Create Playwright test file**

Create `shyfem-ui/tests/test_playwright_simulation_picker.py` — same template as Task 4 Step 9 with these substitutions:
- `grid_prep` → `simulation`
- `data-nav='Grid Prep'` → `data-nav='Simulation'`
- `fp_grd` → `fp_str`
- `grd_path` → `str_path`
- `/tmp/manual-typed.grd` → `/tmp/manual-typed.str`
- `/tmp/preset-value.grd` → `/tmp/preset-value.str`
- File-extension references in the project dict: replace `bas_file: 'g.bas'` etc. with a `simulations` list: `simulations: [{name: 's', str_file: 'newsim.str'}]`

- [ ] **Step 10: Run Playwright + regression**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_simulation_picker.py -v --override-ini="addopts="
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_simulation.py tests/test_simulation_logic.py -q
```

- [ ] **Step 11: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/simulation.py shyfem-ui/tests/test_simulation_file_picker.py shyfem-ui/tests/test_playwright_simulation_picker.py
git commit -m "feat(ui): wire file_picker for str_path in simulation

Adds picker filtered to file_types=['str']. Applies reactive.isolate()
+ empty-guard to BOTH _on_project_changed and _on_tutorial_context
effects (both can write str_path; both must respect picker selections).

Wiring assertion test pins isolate-count >= 2 to prevent regression."
```

---

## Task 7: Wire picker for `pages/physics.py` (`.str` → `"str"`)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/physics.py`
- Create: `shyfem-ui/tests/test_physics_file_picker.py`
- Create: `shyfem-ui/tests/test_playwright_physics_picker.py`

**Page-specific note:** physics.py has NO existing `_on_project_changed` effect. Task 7 ADDS one. It also already passes `active_project` through (verified at `app.py:782` and physics.py:261). The new effect uses the project's `simulations[0].str_file` for prefill, mirroring simulation.py's pattern.

- [ ] **Step 1: Add picker imports**

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

`from pathlib import Path` is already imported at `physics.py:9` — no addition needed (verified).

- [ ] **Step 2: Add picker UI above `ui.input_text("str_path", ...)` (line 228–231)**

```python
                file_picker_ui("fp_str", label="Pick STR file from project"),
```

- [ ] **Step 3: Add `project_id_val` reactive + the new `_on_project_changed` effect**

In `physics_server` (line 261), after the def + docstring, insert:

```python
    project_id_val: reactive.Value[int | None] = reactive.value(None)

    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            project_id_val.set(None)
            return
        project_id_val.set(proj.get("id"))
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                with reactive.isolate():
                    str_empty = not input.str_path()
                if str_empty:
                    ui.update_text(
                        "str_path",
                        value=str(Path(proj["work_dir"]) / sim["str_file"]),
                    )
```

- [ ] **Step 4: Add the `file_picker_server` call**

```python
    file_picker_server(
        "fp_str",
        project_id=project_id_val,
        file_types=["str"],
        on_selected=lambda rel: fill_picker_input("str_path", active_project.get() if active_project else None, rel),
    )
```

- [ ] **Step 5: Verify + F401**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import physics; print('OK')"
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/pages/physics.py
```

- [ ] **Step 6: Create unit test file**

Create `shyfem-ui/tests/test_physics_file_picker.py`:

```python
"""Unit tests for physics page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_str_path(self):
        from shyfem_ui.pages.physics import physics_ui

        tag = physics_ui("test")
        html = str(tag)

        assert 'id="test-fp_str-file_select"' in html
        picker_pos = html.find('id="test-fp_str-file_select"')
        input_pos = html.find('id="test-str_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_physics_wires_file_picker_server(self):
        import shyfem_ui.pages.physics as page_mod

        from shyfem_ui.components import file_picker as fp_mod

        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "physics_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["str"]' in src
        assert 'fill_picker_input("str_path"' in src
        # physics had NO _on_project_changed before this rollout —
        # pin that the new effect was added.
        assert "_on_project_changed" in src, (
            "physics_server must add a _on_project_changed effect "
            "(physics had no prior auto-fill)"
        )
        assert "reactive.isolate()" in src
```

- [ ] **Step 7: Run unit tests**

`cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics_file_picker.py -v`

- [ ] **Step 8: Create Playwright test file**

Create `shyfem-ui/tests/test_playwright_physics_picker.py` — same template as Task 4 Step 9 with substitutions:
- `grid_prep` → `physics`
- `data-nav='Grid Prep'` → `data-nav='Physics'`
- `fp_grd` → `fp_str`
- `grd_path` → `str_path`
- File extensions: `.str` instead of `.grd`
- Project dict: include `simulations: [{name: 's', str_file: 'sim.str'}]`

- [ ] **Step 9: Run Playwright + regression**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_physics_picker.py -v --override-ini="addopts="
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_physics.py tests/test_physics_logic.py -q
```

- [ ] **Step 10: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/physics.py shyfem-ui/tests/test_physics_file_picker.py shyfem-ui/tests/test_playwright_physics_picker.py
git commit -m "feat(ui): wire file_picker for str_path in physics

Adds picker filtered to file_types=['str']. ALSO adds the missing
_on_project_changed effect — physics had no prior auto-fill, so the
picker comes with auto-population of the page's str_path field from
the active project's first simulation.str_file (with reactive.isolate
+ empty-guard from day one)."
```

---

## Task 8: Wire picker for `pages/run.py` (`.str` → `"str"`)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py`
- Create: `shyfem-ui/tests/test_run_file_picker.py`
- Modify: `docs/followups/2026-04-29-ui-deep-review-deferred.md` (add Playwright-coverage gap entry)

**Page-specific note (REVISED post-review):** `run.py`'s test mount in `_test_app.py:168` uses `_stub_run_server` (line 245) instead of the full `run_server` to avoid event-loop deadlocks. The deadlock is structural — it stems from `run_server`'s job-queue reactive effects, not anything the picker introduces. Three review responses converged on **expanding the stub (option a) over skipping Playwright (option b)**: the cost is ~8 LOC of mirrored picker wiring, and the benefit is real browser-side coverage of run.py's picker (which has NO other coverage). Option (b) leaves the picker on `run.py` exercised only by unit tests and a manual smoke. After 6 months, "stub drift" will be smaller than the cost of unnoticed regressions.

**This plan picks (a) for run.py — extend the stub.** Followup Section M.1 still tracks the deeper structural issue (the deadlock) but the picker itself ships with Playwright coverage.

- [ ] **Step 1: Add picker imports**

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

- [ ] **Step 2: Add picker UI above `ui.input_text("input_file", ...)` (line 80–84)**

```python
                file_picker_ui("fp_input", label="Pick STR file from project"),
```

- [ ] **Step 3: Add `project_id_val` reactive value at the top of `run_server`**

After `def run_server(...)` (line 241–250) and its docstring:

```python
    project_id_val: reactive.Value[int | None] = reactive.value(None)
```

- [ ] **Step 4: Modify both `_on_project_changed` and `_on_tutorial_context` effects (lines 263–290)**

`run.py`'s `_on_project_changed` writes BOTH `working_dir` (a directory, project-tied) AND `input_file` (a file). Apply Note G's last-project-id pattern to `working_dir` (it's a directory prefill, like postprocess's `shy_path`); apply isolate+empty-guard to `input_file` (file prefill, like simulation's `str_path`). Per Note F, `_on_tutorial_context` gets isolate-only.

Add `last_project_id: reactive.Value[int | None] = reactive.value(None)` next to `project_id_val` in Step 3.

For `_on_project_changed` (lines 263–274):

```python
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            project_id_val.set(None)
            last_project_id.set(None)
            return
        pid = proj.get("id")
        project_id_val.set(pid)
        project_changed = last_project_id.get() != pid
        last_project_id.set(pid)
        work = proj["work_dir"]

        # working_dir is a directory prefill (project-tied, NOT user
        # choice). Use the Note-G pattern: force re-fill on actual
        # project change so project A's directory doesn't leak into B.
        with reactive.isolate():
            wd_empty = not input.working_dir()
        if wd_empty or project_changed:
            ui.update_text("working_dir", value=work)

        # input_file is a file prefill (project-tied, picker can override).
        # Standard isolate + empty-guard.
        if proj["simulations"]:
            sim = proj["simulations"][0]
            if sim.get("str_file"):
                with reactive.isolate():
                    input_file_empty = not input.input_file()
                if input_file_empty:
                    ui.update_text(
                        "input_file",
                        value=str(Path(work) / sim["str_file"]),
                    )
```

For `_on_tutorial_context` (lines 277–290) — apply Note F (isolate-only, no empty-guard). Read the existing body, wrap any `input.X()` reads in `reactive.isolate()`, but leave `ui.update_text` calls UNCONDITIONAL. Tutorial nav is intentional override.

- [ ] **Step 4b: Extend `_stub_run_server` to mirror picker wiring**

Per the page-specific note above, this plan picks option (a). In `shyfem-ui/tests/_test_app.py`, locate `_stub_run_server` (around line 47 — it's `@module.server`-decorated; do NOT remove the decorator). Add the picker wiring INSIDE the existing function body, matching the real `run_server`. Add `active_project=None` to the parameter list:

```python
@module.server  # KEEP existing decorator
def _stub_run_server(input, output, session, config, job_queue, active_project=None):
    """Stub for run_server that avoids the deadlocking reactive effects
    while still mounting the picker so Playwright tests can exercise it.
    """
    from shiny import reactive, ui
    from shyfem_ui.components.file_picker import (
        file_picker_server,
        fill_picker_input,
    )

    project_id_val: reactive.Value[int | None] = reactive.value(None)

    @reactive.effect
    def _stub_on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        project_id_val.set(proj.get("id") if proj else None)

    file_picker_server(
        "fp_input",
        project_id=project_id_val,
        file_types=["str"],
        on_selected=lambda rel: fill_picker_input(
            "input_file",
            active_project.get() if active_project else None,
            rel,
        ),
    )
```

The stub doesn't replicate the empty-guard / tutorial-context logic — Playwright tests for run.py only need to verify the picker UI wiring, not the auto-fill semantics. The auto-fill is covered by the unit-test wiring assertion.

- [ ] **Step 5: Add the `file_picker_server` call**

```python
    file_picker_server(
        "fp_input",
        project_id=project_id_val,
        file_types=["str"],
        on_selected=lambda rel: fill_picker_input("input_file", active_project.get() if active_project else None, rel),
    )
```

- [ ] **Step 5b: Update the `_stub_run_server` call site in `_test_app.py`**

The stub now requires `active_project`. Locate the existing call (around `_test_app.py:245`):

```python
_stub_run_server("run", config, job_queue)
```

Replace with:

```python
_stub_run_server("run", config, job_queue, active_project=active_project)
```

`active_project` is already in scope at the call site (declared at `_test_app.py:212`).

- [ ] **Step 6: Verify + F401**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import run; print('OK')"
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/pages/run.py
```

- [ ] **Step 7: Create unit test file**

Create `shyfem-ui/tests/test_run_file_picker.py`:

```python
"""Unit tests for run page file-picker UI rendering and wiring.

NOTE: run.py uses _stub_run_server in tests (search _test_app.py for
_stub_run_server) to work around an event-loop deadlock in run_server's
job-queue effects. The stub mirrors the picker's wiring (project_id_val
+ file_picker_server) so Playwright tests CAN exercise the picker —
see test_playwright_run_picker.py. The deadlock itself remains tracked
as Section M.1 in the followups doc.
"""


class TestPickerUiRenders:
    def test_picker_renders_above_input_file(self):
        from shyfem_ui.pages.run import run_ui

        tag = run_ui("test")
        html = str(tag)

        assert 'id="test-fp_input-file_select"' in html
        picker_pos = html.find('id="test-fp_input-file_select"')
        input_pos = html.find('id="test-input_file"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_run_wires_file_picker_server(self):
        import shyfem_ui.pages.run as page_mod

        from shyfem_ui.components import file_picker as fp_mod

        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "run_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["str"]' in src
        assert 'fill_picker_input("input_file"' in src
        # Both effects must be isolate-guarded
        isolate_count = src.count("reactive.isolate()")
        assert isolate_count >= 2, (
            f"expected reactive.isolate() in both _on_project_changed "
            f"AND _on_tutorial_context (found {isolate_count})"
        )
```

- [ ] **Step 8: Run unit tests + regression**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_file_picker.py -v
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run.py tests/test_run_logic.py -q
```

- [ ] **Step 9: Create Playwright test file (now possible since stub mounts the picker)**

Create `shyfem-ui/tests/test_playwright_run_picker.py` mirroring Task 4's template, but with the substitutions appropriate for run.py:
- `data-nav='Run'`
- picker id `#run-fp_input-file_select`
- text input `#run-input_file`
- file extension `.str`
- The stub's `_on_project_changed` only updates `project_id_val`; auto-fill semantics aren't tested via Playwright on run.py — coverage is the picker UI wiring + traversal-warning behaviour.

- [ ] **Step 9b: Update the Section M.1 followup to reflect the new state**

`run.py` now HAS Playwright coverage (via the stub-extension approach). Update `docs/followups/2026-04-29-ui-deep-review-deferred.md` Section M.1 to note that the deadlock-in-real-server gap remains tracked but the picker-coverage gap is closed:

```markdown

## Section M.1 — run.py reactive-effect deadlock (open)

**Source:** Section M file-picker rollout (2026-05-04 → 2026-05-05).

`run_server` cannot be mounted in the test app due to event-loop
deadlocks in its reactive effects (job-queue + tutorial-context
interplay). The Section M rollout works around this for picker
coverage by extending `_stub_run_server` to mount the picker without
the deadlocking effects (`_test_app.py:245`).

**Open work:** the underlying deadlock means run_server cannot be
exercised end-to-end in tests at all. Picker coverage is workable but
fragile: any future picker-adjacent change to run_server must also
update the stub, or stub drift silently breaks Playwright coverage.

**Resolution options:**
1. Refactor run_server to extract the deadlock-causing effects into a
   helper that the test can replace via dependency injection.
2. Identify the specific deadlocking interaction and break the cycle
   directly (likely the right fix; needs investigation).

Tracked but not scoped.
```

- [ ] **Step 10: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/run.py shyfem-ui/tests/_test_app.py shyfem-ui/tests/test_run_file_picker.py shyfem-ui/tests/test_playwright_run_picker.py docs/followups/2026-04-29-ui-deep-review-deferred.md
git commit -m "feat(ui): wire file_picker for input_file in run

Adds picker filtered to file_types=['str']. _on_project_changed uses
last_project_id change-detection for working_dir (project-tied
directory; same pattern as postprocess). input_file gets
reactive.isolate + empty-guard. _on_tutorial_context gets isolate-only
(tutorial overrides are explicit user intent).

Playwright coverage enabled by extending _stub_run_server to mirror
the picker wiring. The underlying run_server deadlock remains tracked
as Section M.1; this rollout works around it for picker tests only."
```

---

## Task 9: Wire picker for `pages/ibm.py` (`.lgr` → `"lagrangian"`)

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/ibm.py`
- Create: `shyfem-ui/tests/test_ibm_file_picker.py`
- Create: `shyfem-ui/tests/test_playwright_ibm_picker.py`

**Page-specific notes:**

1. **`if MapWidget is None: return` early-return at `ibm.py:226-227`** — the page short-circuits when deckgl is unavailable. Place ALL new picker code (Steps 3–5 below) AFTER this early-return guard. If placed before, the picker registers but the rest of the page won't initialize, and the picker's `_on_project_changed` effect would still fire on a non-functional page.

2. **glob-vs-FileService divergence (silent):** the existing `_on_project_changed` does a glob-search of `work_dir` for `.lgr` files. The picker dropdown only lists files tracked by FileService. If a `.lgr` is generated by run.py mid-session (before FileService scan), the glob fills `lgr_path` automatically while the picker stays empty — the user sees a populated input and an empty picker dropdown, with no indication that the value's provenance is the glob, not a picker click. This is a known UX limitation of this rollout; tracked in the followups doc as a Section M.2 follow-up. Resolution options: (a) drop the glob (picker is canonical), or (b) emit a `logger.info` when glob fills `lgr_path` so provenance is observable in logs. This rollout keeps option (a)'s behaviour for now (preserve glob).

- [ ] **Step 1: Add picker imports**

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    fill_picker_input,
)
```

- [ ] **Step 2: Add picker UI above `ui.input_text("lgr_path", ...)` (line 161–165)**

```python
                file_picker_ui("fp_lgr", label="Pick Lagrangian output from project"),
```

- [ ] **Step 3: Add `project_id_val` reactive value AFTER the `if MapWidget is None: return` guard**

Place AFTER `ibm.py:226-227`'s early-return (NOT in the def's preamble). Look for the line `if MapWidget is None: return` and insert below it:

```python
    project_id_val: reactive.Value[int | None] = reactive.value(None)
```

- [ ] **Step 4: Modify `_on_project_changed` (lines 249–258)**

Read the existing glob-based body first. Then translate to:

```python
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            project_id_val.set(None)
            return
        project_id_val.set(proj.get("id"))
        work = proj["work_dir"]
        # Existing glob fallback — keep it for .lgr files that aren't
        # tracked in FileService (e.g., generated mid-run before scan).
        # Only fill if the input is empty so picker selections survive.
        with reactive.isolate():
            lgr_empty = not input.lgr_path()
        if lgr_empty:
            # ... existing glob logic ...
            # (preserve the existing ui.update_text call but only inside
            # the `if lgr_empty:` branch)
```

If the existing glob logic is more complex (multiple matches, picking the latest, etc.), preserve it inside the `if lgr_empty:` branch — only the empty-guard wrapping is new.

- [ ] **Step 5: Add the `file_picker_server` call**

```python
    file_picker_server(
        "fp_lgr",
        project_id=project_id_val,
        file_types=["lagrangian"],
        on_selected=lambda rel: fill_picker_input("lgr_path", active_project.get() if active_project else None, rel),
    )
```

- [ ] **Step 6: Verify + F401**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import ibm; print('OK')"
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I shyfem_ui/pages/ibm.py
```

- [ ] **Step 7: Create unit test file**

Create `shyfem-ui/tests/test_ibm_file_picker.py`:

```python
"""Unit tests for ibm page file-picker UI rendering and wiring."""


class TestPickerUiRenders:
    def test_picker_renders_above_lgr_path(self):
        from shyfem_ui.pages.ibm import ibm_ui

        tag = ibm_ui("test")
        html = str(tag)

        assert 'id="test-fp_lgr-file_select"' in html
        picker_pos = html.find('id="test-fp_lgr-file_select"')
        input_pos = html.find('id="test-lgr_path"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_ibm_wires_file_picker_server(self):
        import shyfem_ui.pages.ibm as page_mod

        from shyfem_ui.components import file_picker as fp_mod

        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "ibm_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["lagrangian"]' in src
        assert 'fill_picker_input("lgr_path"' in src
        assert "reactive.isolate()" in src


class TestLagrangianFileType:
    """Pin the dependency between ibm.py and the FileService taxonomy.

    If `.lgr` falls back to 'other' (Task 1 reverted), ibm's picker
    silently shows nothing. Without this test, the regression would
    only surface in a Playwright run.
    """

    def test_lgr_extension_maps_to_lagrangian_file_type(self):
        from shyfem_ui.services.file_service import FileService

        assert FileService._infer_file_type("trajectories.lgr") == "lagrangian"
```

- [ ] **Step 8: Run unit tests**

`cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_ibm_file_picker.py -v`

- [ ] **Step 9: Create Playwright test file**

Create `shyfem-ui/tests/test_playwright_ibm_picker.py` — same template as Task 4 Step 9 with substitutions:
- `grid_prep` → `ibm`
- `data-nav='Grid Prep'` → `data-nav='IBM'`
- `fp_grd` → `fp_lgr`
- `grd_path` → `lgr_path`
- File extensions: `.lgr`
- Project dict: include `files: [{id: 1, filename: 'traj.lgr', rel_path: 'traj.lgr', file_type: 'lagrangian', size_bytes: 100}]` to verify the picker filter actually queries `lagrangian`

- [ ] **Step 10: Run Playwright + regression**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_ibm_picker.py -v --override-ini="addopts="
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_ibm.py tests/test_ibm_logic.py -q 2>/dev/null || cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q -k ibm
```

- [ ] **Step 11: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/ibm.py shyfem-ui/tests/test_ibm_file_picker.py shyfem-ui/tests/test_playwright_ibm_picker.py
git commit -m "feat(ui): wire file_picker for lgr_path in ibm

Adds picker filtered to file_types=['lagrangian']. Preserves the
existing glob-based auto-fill but gates it behind reactive.isolate()
+ empty-guard so picker selections survive project re-emits.

Depends on the .lgr -> 'lagrangian' taxonomy entry added in Task 1."
```

---

## Task 10: Final verification + Section M close-out

**Files:**
- Modify: `docs/followups/2026-04-29-ui-deep-review-deferred.md` — mark Section M complete

- [ ] **Step 1: Full unit-test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest -q`

Expected: previous baseline pass count + 12+ new tests (2 per page × 6 pages = 12, plus the 5 new helper tests in Task 3, plus the 1 new file_service test in Task 1). The 6 new Playwright files are excluded from default `pytest -q` by the existing `--ignore-glob=tests/test_playwright_*.py` in `pyproject.toml`.

If a test fails, drill into the specific page that broke and fix BEFORE proceeding. Common regression sources:

- Display name mismatch in `data-target` selectors (e.g., page renamed but Playwright file not updated).
- `Path` import missing in pages where `from pathlib import Path` was assumed pre-existing (most pages have it; physics may not — verify before Step 5 of Task 7).
- Existing `_on_project_changed` effects with bodies more complex than the survey suggested. Re-read each page before applying the canonical pattern.

- [ ] **Step 2: Full Playwright run (manual)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_*_picker.py -v --override-ini="addopts="`

Expected: 5 (partitioning, pre-existing) + 4 × 5 = 25 total Playwright picker tests. (run.py is excluded — no Playwright file.) Some may skip if `__test_set_active_project` hook is unavailable for traversal-warning tests, or if Playwright browsers aren't installed.

- [ ] **Step 3: F401 + isort sweep across all touched files**

Run:
```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401,I \
  shyfem_ui/components/file_picker.py \
  shyfem_ui/services/file_service.py \
  shyfem_ui/pages/partitioning.py \
  shyfem_ui/pages/grid_prep.py \
  shyfem_ui/pages/postprocess.py \
  shyfem_ui/pages/physics.py \
  shyfem_ui/pages/simulation.py \
  shyfem_ui/pages/run.py \
  shyfem_ui/pages/ibm.py
```

Expected: clean.

- [ ] **Step 4: Pattern-drift guard — pin every page exposes the helper**

Run a one-shot grep to verify the 6 pages all import `fill_picker_input`:

```bash
cd /home/razinka/shyfem/shyfem-ui && for p in grid_prep postprocess physics simulation run ibm partitioning; do
  echo "=== $p ==="
  grep -c "fill_picker_input" shyfem_ui/pages/$p.py
done
```

Expected: each page reports `>= 2` (one in the import, one in the lambda). If any reports `0` or `1`, that page wasn't fully wired — investigate before close-out.

- [ ] **Step 5: Manual smoke test (the 6 pages + run.py specifically)**

Run the app in local mode:

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app
```

Open `http://127.0.0.1:8000/`. Create or load a project that has at least: a `.bas`, a `.grd`, a `.str`, an `.shy` (or `.nc`), and a `.lgr` (or none — the empty-state placeholder is the test there). Navigate to each of the 7 pages with pickers (the 6 Section M pages + partitioning) and confirm:

1. **Grid Prep** — picker shows `.grd` files; selecting one fills `grd_path` with absolute path.
2. **Postprocess** — picker shows `.shy/.nc/.ext/.flx` files; selecting one fills `shy_path`.
3. **Physics** — picker shows `.str` files; selecting one fills `str_path`. Auto-fill on first project load works (this is the page that had no `_on_project_changed` before).
4. **Simulation** — picker shows `.str` files; selecting one fills `str_path`.
5. **Run** — picker shows `.str` files; selecting one fills `input_file`. **(Critical: this is the only page without Playwright coverage.)**
6. **IBM** — picker shows `.lgr` files (filtered to `"lagrangian"` file_type); selecting one fills `lgr_path`. If no `.lgr` files exist in the project, the placeholder "No files available" is shown.
7. **Partitioning (regression)** — `.bas` and `.grd` pickers still work after the helper extraction.

If any page shows wrong file types, the `file_types=` filter is wrong. If any page's picker doesn't fill the input on selection, the `on_selected` lambda or `fill_picker_input` is broken.

- [ ] **Step 6: Mark Section M complete in followups doc**

In `docs/followups/2026-04-29-ui-deep-review-deferred.md`, find the `## Section M` block (added by the pilot). Replace its contents with:

```markdown
## Section M — File-picker rollout to remaining 6 pages — COMPLETE 2026-05-XX

**Shipped:** 2026-05-XX (replace XX with actual merge date), commit
`<merge-sha>`. The file-picker pattern is now live on all 7 pages:
partitioning (pilot), grid_prep, postprocess, physics, simulation,
run, ibm.

**Helper extraction:** `fill_picker_input(target_id: PickerTargetId,
project: ProjectContext | None, rel_path: str)` in
`components/file_picker.py` owns the resolve+log+notify+update_text
branching. All 7 pages delegate via lambdas that unwrap the active
project (`active_project.get() if active_project else None`) before
calling.

**Taxonomy addition:** `.lgr → "lagrangian"` added to FileService
(`_infer_file_type`); legacy rows backfilled by Alembic migration
`<rev>_lagrangian_file_type`.

**Pattern adoption per page:** `_on_project_changed` effects get
`reactive.isolate()` + empty-guard. `_on_tutorial_context` effects get
`reactive.isolate()` only (no empty-guard — tutorial nav is
intentional override). Pages with project-tied directory prefills
(`postprocess.shy_path` ← `work_dir`, `run.working_dir` ← `work_dir`)
also get a `last_project_id` change-detector to force re-fill on
actual project switch. `physics.py` had no prior `_on_project_changed`
effect; one was added as part of the rollout.

**Outstanding gaps:**
- Section M.1 — `run_server`'s reactive-effect deadlock blocks
  end-to-end test mounting. Picker coverage works around this via
  `_stub_run_server` extension; the underlying deadlock remains
  unresolved.
- Section M.2 — `pages/ibm.py` retains a glob fallback for `.lgr`
  files outside the FileService index. Picker dropdown and the glob
  can disagree on which file is shown; provenance is unobservable.
  Resolution: drop the glob (picker becomes canonical) or emit
  `logger.info` when glob fills `lgr_path`.

**Section L (output-directory picker) remains deferred** — different
abstraction (directory picker, not file picker). Tracked separately.
```

- [ ] **Step 7: Final commit**

```bash
cd /home/razinka/shyfem
git add docs/followups/2026-04-29-ui-deep-review-deferred.md
git commit -m "docs(ui): mark Section M file-picker rollout complete

7 pages (partitioning + 6 rollout targets) now use the shared
fill_picker_input helper. Section L (output-dir picker), M.1
(run_server deadlock), M.2 (ibm.py glob/picker provenance) remain
tracked."
```

---

## Summary

When complete:

- **`fill_picker_input` shared helper** in `components/file_picker.py` owns the resolve+log+notify+update_text branching for ALL pages.
- **`partitioning.py` refactored** to use the helper — `_fill_bas`/`_fill_grd` deleted, replaced by one-line lambdas.
- **6 pages newly wired** with file pickers: `grid_prep` (`grid`), `postprocess` (`output`), `physics` (`str` — including new `_on_project_changed`), `simulation` (`str`), `run` (`str`), `ibm` (`lagrangian`).
- **`.lgr → "lagrangian"`** in FileService taxonomy + Alembic backfill migration for legacy rows.
- **5 helper tests** in `test_file_picker_logic.py` (success, no-project, empty-rel_path, traversal-warning, target_id-in-log).
- **12 page-level unit tests** (UI render + import-style/wiring guard for each of 6 pages).
- **20 Playwright tests** (4 per page × 5 pages — `run.py` excluded). Each: placeholder, isolate regression, empty-guard, traversal-warning toast.
- **2 followups updated/added**: Section M marked complete, Section M.1 added for the run.py Playwright gap.

**Total estimated diff:** ~600 added LOC across pages + ~1500 added LOC across tests + 1 Alembic migration + 1 doc update.

**Risk profile:** medium-low. The pattern is proven (pilot shipped 8bfc5fc); each per-page task is structurally identical and independently mergeable. Highest-risk task: Task 7 (physics.py) — adds a new reactive effect rather than modifying one. Highest-touch task: Task 3 (helper extraction + partitioning refactor) — touches the proven pilot, so regression coverage matters.
