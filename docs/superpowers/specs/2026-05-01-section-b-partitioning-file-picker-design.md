# Section B Pilot — Partitioning File-Picker Integration (Design)

**Origin:** `docs/followups/2026-04-29-ui-deep-review-deferred.md` Section B
("File-picker integration across pages"). This spec scopes the **first
pilot** of seven affected pages — `partitioning.py`. Lessons inform the
plan for the other six.

## Goal

Wire the existing `components/file_picker.py` into `pages/partitioning.py`
for the basin (`.bas`) and grid (`.grd`) file inputs. Replace the current
free-text path UX (placeholder `"/path/to/basin.bas"`) with a project-aware
dropdown + browse modal, while preserving the existing text input as a
fallback for legacy paste-an-absolute-path workflows.

## Non-goals

- Output-directory picker — separate abstraction (directory picker, not file
  picker). Tracked as Section L deferral.
- Other 6 pages (`grid_prep`, `postprocess`, `physics`, `simulation`, `run`,
  `ibm`) — tracked as Section M deferral; pilot validates the pattern first.
- Generalizing `file_picker.py` beyond its current API. The existing
  `build_file_choices(project_id, file_types=...)` is already general; the
  STR-specific helpers (`is_file_param`, `param_to_file_types`) are
  untouched and remain in the component module. One small addition — a
  pure `resolve_picker_path` helper — is added to `file_picker.py` since
  it is the logical inverse of `build_file_choices` and will be reused
  by the 6 follow-up pages.

## Context — what already exists

`components/file_picker.py` (304 LOC, last modified 2026-02-21) is a
working Shiny module:

- `file_picker_ui(label="Select File")` — module UI with a `<select>` dropdown + Browse button
- `file_picker_server(input, output, session, project_id: reactive.Value | None = None, file_types: list[str] | None = None, on_selected: Callable[[str], None] | None = None) -> reactive.Value[str]` — server logic (decorated with `@module.server`), returns a reactive value with the current selection. Note: `project_id` is positional-or-keyword with a `None` default; not keyword-only. The parameter is annotated with the **legacy `reactive.Value` alias (capital V)**; this spec uses the modern `reactive.value` (lowercase) at construction sites — runtime they're identical, but type-checkers may flag covariance. Either widen the component signature to `reactive.Value | reactive.value | None` in a follow-up, or pass the page-level `reactive.value` through unchanged (current Shiny accepts both at runtime).
- Browse button opens a modal with a sortable table of project files
- `build_file_choices(project_id, file_types=None) -> dict[str, str]` — pure helper mapping display labels to `rel_path` values; reads via `FileService.list_files`
- Already used by `components/str_editor.py` (lines 418–434) — the established pattern is **coexistence**: picker UI rendered next to a text input, picker fills the text input via the `on_selected` callback

`FileService` taxonomy (verified at `services/file_service.py:329-350`):

| Extension | file_type |
|---|---|
| `.grd` | `grid` |
| `.bas` | `basin` |
| `.str` | `str` |
| `.rst` | `restart` |
| `.nml` | `config` |
| `.shy/.ext/.flx/.nc` | `output` |

`.bas` → `"basin"` and `.grd` → `"grid"` are direct 1:1 mappings, so
filtering the picker by `file_types=["basin"]` (or `["grid"]`) works
without any service-layer change.

## Architecture

**No refactor of file_picker.py.** No new component beyond a pure helper
added to `components/file_picker.py`. Page-level wiring only.

**Helper placement (revised):** `resolve_picker_path` is added to
`components/file_picker.py` (not to `partitioning.py`), alongside the
existing `build_file_choices`. It is the logical inverse — `build_file_choices`
turns project state into rel_path choices, `resolve_picker_path` resolves
a chosen rel_path back to an absolute path. Co-locating prevents the 6
follow-up pages from each copy-pasting it before extraction.

**Project-context typing (new):** add `ProjectContext` and three
nested TypedDicts to `services/project_context.py` (the single
construction site at `_load`, lines 52–69). Without value types the
TypedDict buys nothing over a bare `dict`, so the value types are
specified concretely:

```python
from typing import TypedDict

class GridEntry(TypedDict):
    name: str
    grd_file: str | None
    bas_file: str | None

class SimulationEntry(TypedDict):
    name: str
    str_file: str | None

class FileEntry(TypedDict):
    id: int
    filename: str
    rel_path: str
    file_type: str
    size_bytes: int

class ProjectContext(TypedDict):
    id: int
    name: str
    work_dir: str
    description: str | None
    grids: list[GridEntry]
    simulations: list[SimulationEntry]
    files: list[FileEntry]
```

`_load` is re-annotated `-> ProjectContext | None` (currently
`dict | None`). Page-level parameter annotations on existing pages stay
at `dict | None` for now (structurally compatible). At
`resolve_picker_path` and `_fill_bas`/`_fill_grd` call sites, since the
page receives `active_project: dict | None` while the helper expects
`ProjectContext | None`, add an explicit `cast(ProjectContext | None,
proj)` at the wrapper call site to satisfy mypy/pyright. The cast is
the single migration point for the pilot — once all 6 follow-up pages
adopt the picker, re-typing `active_project` parameters to
`reactive.value[ProjectContext | None] | None` becomes a one-line
change and the casts disappear. The TypedDict earns its keep
immediately at the construction site and at the helper boundary
without forcing a multi-file rename.

**Parameter widening (justified):** `resolve_picker_path` accepts
`rel_path: str | None` even though the `on_selected` callback only
fires with `str` (the component guards `if val:` before invoking).
The wider type is intentional — the helper is meant for direct
non-callback use by the 6 follow-up pages, where callers may pass
defensively-typed values from forms or session state. The empty/None
branch is kept and tested.

In `pages/partitioning.py`:

1. Add 2 picker UIs above the existing `bas_path` and `grd_path` text inputs (preserve the text inputs as the canonical path-holder; picker is a convenience).

2. Add **one shared** `reactive.value[int | None]` (call it `project_id_val`),
   initialized to `None`, that is updated **inside the existing
   `_on_project_changed` effect** (lines 131–144 of `partitioning.py`).
   This avoids creating a second reactive node that re-derives the same
   value from `active_project` — the existing effect already fires on
   exactly this trigger.

   The current effect at lines 131–144 unconditionally overwrites
   `bas_path`/`grd_path` whenever the active project has matching grid
   files. The pseudocode below shows the **modified** version with
   three additions: (a) the new `project_id_val.set(...)` calls, (b)
   the `reactive.isolate()` block around input reads, and (c) the
   empty-guard on auto-fill. None of (a)–(c) exist in the current code.

   ```python
   # Annotation form is mypy/pyright fiction — at runtime,
   # reactive.value is constructed without subscripting:
   #     reactive.value(None) returns a reactive.Value instance.
   # The subscript syntax `reactive.value[int | None]` works only as a
   # type annotation (PEP 585 / __class_getitem__).
   project_id_val: "reactive.value[int | None]" = reactive.value(None)

   # The `active_project is None` check is on a constructor parameter,
   # not a reactive — it's constant for the lifetime of this server
   # invocation. Log once at server entry (BEFORE declaring the
   # reactive effect) rather than threading a one-shot flag through
   # the effect closure.
   if active_project is None:
       logger.warning(
           "partitioning_server received active_project=None — "
           "page wiring bug? File picker dropdowns will stay empty."
       )

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
           # `reactive.isolate()` prevents `input.bas_path()` / `input.grd_path()`
           # from registering as dependencies — without it, every keystroke in
           # those fields would re-run this effect and clobber the user's edit.
           # The intended trigger is `active_project` changing only.
           # The empty-guard then prevents overwriting picker selections when
           # active_project re-emits without an actual project change (e.g.,
           # job-completion notifications that refresh project metadata).
           with reactive.isolate():
               bas_empty = not input.bas_path()
               grd_empty = not input.grd_path()
           if grid.get("bas_file") and bas_empty:
               ui.update_text("bas_path", value=str(Path(work) / grid["bas_file"]))
           if grid.get("grd_file") and grd_empty:
               ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))
   ```

3. Add 2 picker server calls in the page's `partitioning_server` body:
   ```python
   file_picker_server(
       "fp_bas",
       project_id=project_id_val,  # reactive.value[int | None]
       file_types=["basin"],
       on_selected=_fill_bas,
   )
   file_picker_server(
       "fp_grd",
       project_id=project_id_val,
       file_types=["grid"],
       on_selected=_fill_grd,
   )
   ```

4. **Pure helper added to `components/file_picker.py`** (testable in
   isolation), plus thin per-input wrappers inside the server scope:

   ```python
   # In components/file_picker.py — pure-ish helper. No Shiny calls,
   # but does emit a logger.warning on the security-relevant branch
   # so containment failures don't disappear silently across the 6
   # pages that will reuse this helper.
   from shyfem_ui.services.project_context import ProjectContext

   def resolve_picker_path(
       active_project: ProjectContext | None, rel_path: str | None
   ) -> str | None:
       """Resolve a project-relative path to an absolute path.

       Returns None if the project is unknown, rel_path is empty, or the
       resolved path would escape the project work_dir (path traversal
       guard — `Path(work_dir) / "/etc/passwd"` silently yields
       `/etc/passwd`, and `Path(work_dir) / "../../etc"` escapes the
       root). Caller decides what to do with None (typically: skip the
       update_text call AND show a user-visible warning).
       """
       if active_project is None or not rel_path:
           return None
       work_dir = active_project.get("work_dir")
       if not work_dir:
           logger.warning(
               "Picker resolution failed: project %r has no work_dir "
               "(legacy/corrupt row?)",
               active_project.get("id"),
           )
           return None
       root = Path(work_dir).resolve()
       resolved = (root / rel_path).resolve()
       if not resolved.is_relative_to(root):
           logger.warning(
               "Picker rel_path %r escapes work_dir %r — dropdown/project "
               "state mismatch",
               rel_path, work_dir,
           )
           return None
       return str(resolved)

   # Inside partitioning_server — thin Shiny wrapper that distinguishes
   # benign empty-state (project not yet loaded) from a real mismatch
   # (user clicked a dropdown entry that resolves to None). The latter
   # is an actionable bug for the user, so log + notify rather than no-op.
   from typing import cast
   def _fill_bas(rel_path: str) -> None:
       proj = active_project.get() if active_project else None
       # cast: page-level active_project is dict | None for backwards
       # compat; helper expects ProjectContext | None. Structurally
       # identical at runtime; cast satisfies mypy/pyright.
       absolute = resolve_picker_path(cast("ProjectContext | None", proj), rel_path)
       if absolute is None:
           if proj is not None and rel_path:
               logger.warning(
                   "Picker selection %r could not be resolved for "
                   "project %r (work_dir missing or traversal guard rejected)",
                   rel_path, proj.get("id"),
               )
               ui.notification_show(
                   "Could not resolve selected file. Try re-selecting "
                   "after the project finishes loading.",
                   type="warning", duration=5,
               )
           return
       ui.update_text("bas_path", value=absolute)

   # _fill_grd is identical except for the input ID and the log message.
   ```

   The pure `resolve_picker_path` is exercised by the helper-level
   tests (test_file_picker_logic.py). The server-side `_fill_*`
   wrappers are tested via the captured `on_selected` callback from
   the `file_picker_server` mock — see test 11.

5. The existing `_run_shyparts` handler (defined at
   `partitioning.py:181-261`, with `validate_path` calls at lines 208
   and 217) is **unchanged** — it still reads `input.bas_path()` (now
   potentially populated by the picker callback) and passes it through
   `config.validate_path` as before.

The picker provides a `selected_path` reactive that we ignore in this
wiring — we route through the existing text-input contract, identical
to how `str_editor` consumes the picker.

## Data flow

```
User opens partitioning page
  → active_project.get() yields {"id": 7, "work_dir": "/var/lib/shyfem-ui/p7"}
  → project_id_val.set(7) inside _on_project_changed
  → file_picker_server's _update_choices effect re-runs
    → build_file_choices(7, file_types=["basin"]) returns {"BAS/sim.bas (basin)": "BAS/sim.bas"}
    → dropdown populated

User picks "BAS/sim.bas" from dropdown
  → file_picker's _on_selection effect fires
  → on_selected("BAS/sim.bas") called
  → _fill_bas("BAS/sim.bas") computes "/var/lib/shyfem-ui/p7/BAS/sim.bas"
  → ui.update_text("bas_path", value="/var/lib/shyfem-ui/p7/BAS/sim.bas")
  → input.bas_path() now reads the absolute path

User clicks Run shyparts
  → _run_shyparts (unchanged) reads input.bas_path()
  → config.validate_path validates the absolute path
  → wrapper.run_shyparts(...) is invoked
```

## Risks and mitigations

- **Risk:** Picker `selected_path` returns `rel_path`, but `config.validate_path` requires an absolute path. **Mitigation:** the callback resolves against `active_project["work_dir"]` before writing to the text input. Pure callback logic, easily testable.
- **Risk:** `active_project` is `None` at picker construction time. **Mitigation:** `file_picker_server` already handles `project_id=None` (returns empty choices, "No files available" placeholder, verified at `components/file_picker.py:192-196`). Callback also guards with `if proj is None`.
- **Risk:** User pastes an absolute path AND picks a project file — racy. **Mitigation:** picker overwrites text input on selection; user's last action wins. This matches str_editor's existing UX.
- **Risk:** Dropdown shows "No files available" indistinguishably for two cases — (a) no project selected, and (b) project has zero matching `.bas`/`.grd` files (verified: `components/file_picker.py:192-196` uses the same placeholder string for both branches). **Mitigation:** Acceptable for the pilot — both states are non-actionable for the user. Tracked in "Lessons" for resolution before the 6-page rollout if user feedback indicates confusion.
- **Risk:** Picker resolution returns `None` for a user-driven click (dropdown entry exists but `resolve_picker_path` rejects it — typically a stale dropdown after project switch, or a traversal-containment failure indicating dropdown/project mismatch). Silent no-op would leave the user wondering why their click did nothing. **Mitigation:** the wrapper distinguishes benign empty-state from a real mismatch and emits a `logger.warning` plus a `ui.notification_show` warning toast on the latter. The helper itself also logs the traversal-containment branch since it indicates a programmer error, not a benign empty.
- **Risk:** Startup race — does a `file_picker_server` `_update_choices` effect read `project_id_val.get()` before `_on_project_changed` has fired? **Mitigation:** Initial value `reactive.value(None)` is the well-defined "not yet known" state. `file_picker_server` already treats `project_id=None` as "no project" (returns empty choices, "No files available" placeholder at `components/file_picker.py:192-196`). Pre-fire reads yield an empty dropdown until the effect runs — no race, no flicker beyond a single re-render. Documented here so future maintainers don't "fix" it by switching to `@reactive.calc` and reintroducing the double-invalidation that the single-`reactive.value` design specifically avoids.
- **Risk:** `partitioning_server` has no `project_id` reactive today.
  **Mitigation:** introduce one `reactive.value[int | None]` and update
  it inside the existing `_on_project_changed` effect (which already
  fires on the same trigger). This avoids the double-invalidation
  cascade a `@reactive.calc` would create — `_on_project_changed` and
  the calc would both observe `active_project` and both fire on every
  change. Single source of truth, single observer.
- **Risk:** `_on_project_changed` could overwrite a user's picker
  selection if `active_project` re-emits without an actual project
  switch (e.g., a background job-completion notification refreshes
  project metadata, `id` unchanged). **Mitigation:** auto-fill block
  only writes when the corresponding text input is empty — `if not
  input.bas_path()` / `if not input.grd_path()`. User-entered or
  picker-selected paths survive reactive churn.

## Tests

The test plan is split between three files: pure-helper tests live in
`tests/test_file_picker_logic.py` (or extend an existing
`test_components_file_picker.py` if present), wiring/UX tests live in
`tests/test_partitioning_file_picker.py`, and the TypedDict
shape-pinning test extends `tests/test_project_context.py`. Total
**13 tests across the three files** (6 helper + 7 wiring/UX + 1
service-layer pinning).

### `tests/test_file_picker_logic.py` — pure helper tests (5)

1. **test_resolve_picker_path_basic** — happy path. Given
   `active_project={"id": 7, "work_dir": "/x", ...}` (full
   `ProjectContext` shape) and `rel_path="BAS/sim.bas"`, the resolved
   path is `"/x/BAS/sim.bas"`.

2. **test_resolve_picker_path_returns_none_when_no_project** —
   `resolve_picker_path(None, "anything")` returns `None`.

3. **test_resolve_picker_path_returns_none_when_empty_relpath** —
   `resolve_picker_path({"work_dir": "/x", ...}, "")` returns `None`.
   Same for `rel_path=None`.

4. **test_resolve_picker_path_rejects_traversal** — uses `caplog`
   filtered to `name == "shyfem_ui.components.file_picker"` at
   WARNING level. `resolve_picker_path({"work_dir": "/x", ...},
   "../../etc/passwd")` and `resolve_picker_path({"work_dir": "/x",
   ...}, "/etc/passwd")` both return `None`. Assert exactly one
   `logger.warning` record per call, with the rel_path in the message.
   This pins the security-relevant branch's observability contract.
   The logger-name filter is required because tests 4 and 11(b) both
   capture warnings and pytest collects across module loggers
   otherwise.

5. **test_resolve_picker_path_rejects_shape_defects** — uses `caplog`
   filtered to `name == "shyfem_ui.components.file_picker"`.
   `resolve_picker_path({"id": 7}, "x")` (missing `work_dir` key) and
   `resolve_picker_path({"work_dir": ""}, "x")` (empty `work_dir`)
   both return `None`. Both cases also emit exactly one
   `logger.warning` mentioning the project id. Once the
   `ProjectContext` TypedDict propagates to all call sites, the
   missing-key case becomes a static type error; until then, this
   test guards the runtime fallback and pins the log contract.

### `tests/test_partitioning_file_picker.py` — wiring + UX tests (6)

6. **test_picker_ui_renders_for_bas_and_grd** — render
   `partitioning_ui("test")` (the namespace argument is required —
   `partitioning_ui` is decorated with `@module.ui`). Assert exactly
   one `<select>` whose `id` starts with `test-fp_bas-` and exactly
   one starting with `test-fp_grd-`, and that each appears in the
   rendered HTML *before* the corresponding text-input id
   (`test-bas_path` / `test-grd_path`). This pins both presence and
   ordering against the existing solver-method dropdown that
   `partitioning_ui` already renders.

7. **test_partitioning_wires_file_types_to_pickers** — patch
   `shyfem_ui.pages.partitioning.file_picker_server` (the symbol seen
   by the page module after its `from shyfem_ui.components.file_picker
   import file_picker_server` import) with a `MagicMock`. **Defensive
   guard:** before patching, assert
   `hasattr(shyfem_ui.pages.partitioning, "file_picker_server")` so a
   future import-style refactor (e.g., aliased import) fails loudly at
   the patch site rather than silently no-opping the mock. Drive
   `partitioning_server` inside a test session (use the local-mode
   session fixture from `tests/_test_app.py`, which already mounts
   `partitioning_ui("partitioning")` and
   `partitioning_server("partitioning", ...)` at
   `tests/_test_app.py:158` and `:212` respectively;
   `tests/conftest.py` exposes the running app to tests).
   `partitioning_server` is decorated with `@module.server` and needs
   a Shiny session context. Assert the mock was called twice, with
   `file_types=["basin"]` and `file_types=["grid"]`.

8. **test_project_id_val_tracks_active_project** — drive
   `partitioning_server` in a session, set `active_project` to a
   project with `id=7`, assert `project_id_val.get() == 7`. Set
   `active_project` to `None`, assert `project_id_val.get() is None`.
   Catches `project_id_val.set(proj)` vs `proj.get("id")` bugs that
   test 7 alone would miss.

8b. **test_server_logs_warning_when_active_project_is_None** —
    drive `partitioning_server` with `active_project=None` (the
    *constructor* parameter, distinct from a reactive `None` value).
    With `caplog` filtered to `name == "shyfem_ui.pages.partitioning"`
    at WARNING, assert exactly one record whose message contains
    "received active_project=None". This pins the server-entry
    wiring-bug warning added at lines 156–160 of the spec, which is
    distinct from the reactive-None path covered by test 8.

9. **test_on_project_changed_does_not_overwrite_nonempty_text_input** —
   the iter-2 empty-guard regression test. Drive `partitioning_server`
   in a session; set `input.bas_path` to `"/preset"`; trigger
   `active_project` re-emit with a project whose `bas_file` is a
   different value; assert `input.bas_path()` is still `"/preset"`.
   Same for `grd_path`.

10. **test_typing_into_bas_path_does_not_retrigger_project_effect** —
    the iter-3 `reactive.isolate()` regression test. Spy on
    `project_id_val.set` (or counter-instrument `_on_project_changed`);
    after initial project load, mutate `input.bas_path` and assert the
    spy's call count is unchanged. Without `reactive.isolate()`, this
    fails immediately. With it, it pins the dependency-tracking fix.

11. **test_fill_bas_branches** — three sub-cases for the wrapper.
    Because `_fill_bas` is a closure inside `partitioning_server`, the
    test reaches it indirectly: it captures the `on_selected` kwarg
    passed to the patched `file_picker_server` mock from test 7's
    fixture, then invokes the captured callable to drive each branch.
    Concretely:
    `cb = mock_file_picker_server.call_args_list[0].kwargs["on_selected"]`
    then `cb("BAS/sim.bas")` for sub-case (a), `cb("../oops")` for
    sub-case (b), and so on.
    (a) **success** — with a valid `active_project`, `cb("BAS/sim.bas")`
    causes `ui.update_text` to be called with the absolute path; no
    notification, no warning;
    (b) **resolution failure with proj+rel_path** — set
    `active_project` to a project whose `work_dir` the rel_path
    escapes (e.g. rel_path `"../oops"`). The traversal trips two
    warnings: one from `resolve_picker_path` (logger name
    `shyfem_ui.components.file_picker`) and one from `_fill_bas`
    (logger name `shyfem_ui.pages.partitioning`). Filter `caplog` by
    logger name — assert exactly one record per logger, AND one
    `ui.notification_show` call with `type="warning"`. Assert
    `ui.update_text` was NOT called;
    (c) **silent return on no project** — set `active_project.get()`
    to `None`; `cb("x")` produces no log, no notification, no
    `update_text`. Mirror for `_fill_grd` via the second mock call.

    **Implementation note:** test 11 is a *single* pytest function
    with internal asserts for sub-cases (a)/(b)/(c) plus a final
    mirrored block for `_fill_grd` — **not** `@pytest.mark.parametrize`d.
    pytest collects exactly one item; the "13 tests" total depends on
    this.

### Pinning the TypedDict to runtime shape

The `ProjectContext` TypedDict is a static-only construct. Two narrow
tests pin it to runtime shape from the right side of each layer:

5b. **test_resolve_picker_path_accepts_project_context_shape** (in
    `test_file_picker_logic.py`) — construct a literal dict matching
    the `ProjectContext` keys (`id`, `name`, `work_dir`, `description`,
    `grids`, `simulations`, `files`), pass it to `resolve_picker_path`
    with a valid `rel_path`, assert non-`None`. Tests the helper
    against a faithful shape without crossing layers — no DB fixture,
    no `_load` import, no `services` dependency from a component test.

12. **test_load_returns_dict_with_required_keys** (in
    `test_project_context.py`) — call `_load` against a real DB
    fixture (with at least one grid, one simulation, one file row to
    exercise the nested lists). Assert the returned dict contains all
    top-level `ProjectContext` keys with the right value types
    (`work_dir: str`, `id: int`, etc.). **Also** assert that the
    first entry of `grids` contains all `GridEntry` keys (`name`,
    `grd_file`, `bas_file`); first entry of `simulations` contains
    `SimulationEntry` keys (`name`, `str_file`); first entry of
    `files` contains `FileEntry` keys (`id`, `filename`, `rel_path`,
    `file_type`, `size_bytes`). Without nested-shape assertions, a
    drift like `_load` dropping `bas_file` from grid dicts goes
    undetected at runtime. No import of `components.file_picker` —
    strictly tests `_load`'s contract. Together, 5b and 12 close the
    drift loop without inverting layers.

(The existing `tests/test_partitioning.py` and `tests/test_partitioning_logic.py`
already cover the wrapper-level shyparts wiring and don't need changes.)

## Files

- Modify: `shyfem-ui/shyfem_ui/services/project_context.py` — add a
  `ProjectContext` TypedDict declaring the dict shape produced by
  `_load` (lines 52–69). ~10 LOC, additive.
- Modify: `shyfem-ui/shyfem_ui/components/file_picker.py` — add the pure
  `resolve_picker_path` helper (~15 LOC including imports of `Path` and
  `ProjectContext`; no imports of Shiny reactive machinery).
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py` — 2 picker imports
  (`file_picker_ui`, `file_picker_server`, `resolve_picker_path`), 2
  picker UI calls in `partitioning_ui()`, 2 picker server calls + 2
  callback helpers in `partitioning_server()`, 1 `reactive.value[int |
  None]` set inside the existing `_on_project_changed` effect, plus the
  `not input.bas_path()` / `not input.grd_path()` guards on the existing
  auto-fill block. Estimate ~30 added LOC.
- Modify: `docs/followups/2026-04-29-ui-deep-review-deferred.md` — append
  Section L (output-directory picker) and Section M (6-page rollout).
- Add: `shyfem-ui/tests/test_file_picker_logic.py` — pure helper tests
  (6 tests including 5b shape-acceptance, ~70 LOC). Imports
  `resolve_picker_path` from `components.file_picker`.
- Add: `shyfem-ui/tests/test_partitioning_file_picker.py` — wiring + UX
  regression tests (7 tests including 8b, ~170 LOC). Uses local-mode
  session fixture.
- Modify: `shyfem-ui/tests/test_project_context.py` — add one test
  asserting `_load` returns a dict containing all `ProjectContext`
  keys with the right value types. No import of `components.file_picker`.

## Verification

After implementation:

1. `pytest tests/test_file_picker_logic.py tests/test_partitioning_file_picker.py -v` → 13 pass (6 helper tests including 5b + 7 wiring/UX tests including 8b).
2. `pytest tests/test_project_context.py -v` → existing tests + new shape-pinning test pass.
3. `pytest tests/test_partitioning.py tests/test_partitioning_logic.py tests/test_pages_access_control.py -q` → still green (no regression in the existing partitioning tests, no Phase C guard removed).
4. `ruff check --select F401 shyfem-ui/shyfem_ui/pages/partitioning.py shyfem-ui/shyfem_ui/components/file_picker.py shyfem-ui/shyfem_ui/services/project_context.py` → clean.
5. `mypy --strict shyfem-ui/shyfem_ui/components/file_picker.py shyfem-ui/shyfem_ui/services/project_context.py shyfem-ui/shyfem_ui/pages/partitioning.py` → clean. The project has no committed static-checker config (verified — no `[tool.mypy]` or `[tool.pyright]` in `pyproject.toml`); this is a manual one-off check on the changed files to verify the `ProjectContext` TypedDict and the `cast()` at the wrapper boundary type-check correctly. Skip if mypy is not installed in the dev environment.
6. Manual smoke test (optional): start the app in local mode, navigate to Partitioning, confirm the picker dropdown shows project basin files and that picking one fills the text input.

## Lessons to capture for the 6-page follow-up

- Whether the coexistence pattern (picker + text input) feels natural or noisy in the rendered UI.
- Whether one shared `_resolve_relpath` helper across pages is worth extracting (probably yes, after at least 3 pages have been wired).
- The `_fill_*` wrapper bodies (log + `ui.notification_show` + `ui.update_text`, plus the empty/None branching) should be extracted into a shared helper in `components/file_picker.py` — call it `fill_picker_input(text_input_id, active_project, rel_path)` — **no later than the second follow-up page**, to avoid the log/notify wording drifting across pages. This is a hard deadline, not "after at least 3 pages": the wrappers contain user-visible strings and observability calls that must stay consistent.
- Whether `file_types` filter values exist for every page's needs (e.g., does `.lgr` for `ibm.py` map cleanly to a FileService category?). May need taxonomy additions.
- Whether the ambiguous "No files available" placeholder (used both for "no project loaded" and "project has zero matching files" — verified at `components/file_picker.py:192-196` to be the same string) confuses users. If yes, split the placeholder by case in the picker component before the rollout.
