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
  untouched and remain in the component module.

## Context — what already exists

`components/file_picker.py` (304 LOC, last modified 2026-02-21) is a
working Shiny module:

- `file_picker_ui(label="Select File")` — module UI with a `<select>` dropdown + Browse button
- `file_picker_server(input, output, session, *, project_id: reactive.Value, file_types: list[str] | None = None, on_selected: Callable[[str], None] | None = None) -> reactive.Value[str]` — server logic, returns a reactive value with the current selection
- Browse button opens a modal with a sortable table of project files
- `build_file_choices(project_id, file_types=None) -> dict[str, str]` — pure helper mapping display labels to `rel_path` values; reads via `FileService.list_files`
- Already used by `components/str_editor.py` (lines 419–432) — the established pattern is **coexistence**: picker UI rendered next to a text input, picker fills the text input via the `on_selected` callback

`FileService` taxonomy (verified at `services/file_service.py:329-352`):

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

**No refactor of file_picker.py.** No new component. Page-level wiring
only.

In `pages/partitioning.py`:

1. Add 2 picker UIs above the existing `bas_file` and `grd_file` text inputs (preserve the text inputs as the canonical path-holder; picker is a convenience).

2. Add 2 picker server calls in the page's `partitioning_server` body:
   ```python
   file_picker_server(
       "fp_bas",
       project_id=project_id_reactive,  # reactive.Value[int | None]
       file_types=["basin"],
       on_selected=_fill_bas,
   )
   file_picker_server(
       "fp_grd",
       project_id=project_id_reactive,
       file_types=["grid"],
       on_selected=_fill_grd,
   )
   ```

3. **One pure helper at module level** (testable in isolation), plus thin
   per-input wrappers inside the server scope:

   ```python
   # Module-level — pure, no Shiny calls, no reactive reads:
   def resolve_picker_path(
       active_project: dict | None, rel_path: str
   ) -> str | None:
       """Resolve a project-relative path to an absolute path.

       Returns None if the project is unknown or rel_path is empty —
       caller decides what to do (typically: skip the update_text call).
       """
       if active_project is None or not rel_path:
           return None
       work_dir = active_project.get("work_dir")
       if not work_dir:
           return None
       return str(Path(work_dir) / rel_path)

   # Inside partitioning_server — thin Shiny wrapper:
   def _fill_bas(rel_path: str) -> None:
       absolute = resolve_picker_path(active_project.get(), rel_path)
       if absolute is not None:
           ui.update_text("bas_file", value=absolute)

   # _fill_grd is identical except for the input ID.
   ```

   The pure `resolve_picker_path` is what the tests in section 2/3/4
   below exercise. The server-side `_fill_*` wrappers are trivial
   (3 lines each) and don't need their own tests.

4. The existing `_run_shyparts` handler is **unchanged** — it still reads
   `input.bas_file()` (now potentially populated by the picker callback)
   and passes it through `config.validate_path` as before.

The picker provides a `selected_path` reactive that we ignore in this
wiring — we route through the existing text-input contract, identical
to how `str_editor` consumes the picker.

## Data flow

```
User opens partitioning page
  → active_project.get() yields {"id": 7, "work_dir": "/var/lib/shyfem-ui/p7"}
  → project_id_reactive set to 7
  → file_picker_server's _update_choices effect re-runs
    → build_file_choices(7, file_types=["basin"]) returns {"BAS/sim.bas (basin)": "BAS/sim.bas"}
    → dropdown populated

User picks "BAS/sim.bas" from dropdown
  → file_picker's _on_selection effect fires
  → on_selected("BAS/sim.bas") called
  → _fill_bas("BAS/sim.bas") computes "/var/lib/shyfem-ui/p7/BAS/sim.bas"
  → ui.update_text("bas_file", value="/var/lib/shyfem-ui/p7/BAS/sim.bas")
  → input.bas_file() now reads the absolute path

User clicks Run shyparts
  → _run_shyparts (unchanged) reads input.bas_file()
  → config.validate_path validates the absolute path
  → wrapper.run_shyparts(...) is invoked
```

## Risks and mitigations

- **Risk:** Picker `selected_path` returns `rel_path`, but `config.validate_path` requires an absolute path. **Mitigation:** the callback resolves against `active_project["work_dir"]` before writing to the text input. Pure callback logic, easily testable.
- **Risk:** `active_project` is `None` at picker construction time. **Mitigation:** `file_picker_server` already handles `project_id=None` (returns empty choices, "No files available" placeholder). Callback also guards with `if proj is None`.
- **Risk:** User pastes an absolute path AND picks a project file — racy. **Mitigation:** picker overwrites text input on selection; user's last action wins. This matches str_editor's existing UX.
- **Risk:** `project_id_reactive` doesn't exist as a separate reactive in
  `partitioning_server` today. **Mitigation:** introduce a small reactive
  derived from `active_project` (one `@reactive.calc` returning
  `active_project.get()["id"] if active_project.get() else None`).

## Tests

`tests/test_partitioning_file_picker.py` — 5 tests:

1. **test_picker_ui_renders_for_bas_and_grd** — render `partitioning_ui()`,
   assert two `<select>` elements with picker IDs `fp_bas` and `fp_grd`
   appear above the corresponding text inputs.

2. **test_resolve_picker_path_basic** — pure function test of the
   module-level `resolve_picker_path`. Given
   `active_project={"work_dir": "/x"}` and `rel_path="BAS/sim.bas"`,
   the resolved path is `"/x/BAS/sim.bas"`.

3. **test_resolve_picker_path_returns_none_when_no_project** —
   `resolve_picker_path(None, "anything")` returns `None`.

4. **test_resolve_picker_path_returns_none_when_empty_relpath** —
   `resolve_picker_path({"work_dir": "/x"}, "")` returns `None`.
   Same for `resolve_picker_path({"work_dir": "/x"}, None)` if the
   caller passes None defensively.

5. **test_picker_filters_by_basin_file_type** — wrap `file_picker_server`
   with a mock `FileService.list_files`; assert the call passes
   `file_type="basin"` (and only "basin"), not the full unfiltered list.

(The existing `tests/test_partitioning.py` and `tests/test_partitioning_logic.py`
already cover the wrapper-level shyparts wiring and don't need changes.)

## Files

- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py` — 2 picker imports,
  2 picker UI calls in `partitioning_ui()`, 2 picker server calls + 2
  callback helpers in `partitioning_server()`, 1 reactive.calc for
  `project_id_reactive`. Estimate ~30 added LOC.
- Modify: `docs/followups/2026-04-29-ui-deep-review-deferred.md` — append
  Section L (output-directory picker) and Section M (6-page rollout).
- Add: `shyfem-ui/tests/test_partitioning_file_picker.py` — 5 tests, ~80 LOC.

## Verification

After implementation:

1. `pytest tests/test_partitioning_file_picker.py -v` → 5 pass.
2. `pytest tests/test_partitioning.py tests/test_partitioning_logic.py tests/test_pages_access_control.py -q` → still green (no regression in the existing partitioning tests, no Phase C guard removed).
3. `ruff check --select F401 shyfem-ui/shyfem_ui/pages/partitioning.py` → clean (no new orphaned imports).
4. Manual smoke test (optional): start the app in local mode, navigate to Partitioning, confirm the picker dropdown shows project basin files and that picking one fills the text input.

## Lessons to capture for the 6-page follow-up

- Whether the coexistence pattern (picker + text input) feels natural or noisy in the rendered UI.
- Whether one shared `_resolve_relpath` helper across pages is worth extracting (probably yes, after at least 3 pages have been wired).
- Whether `file_types` filter values exist for every page's needs (e.g., does `.lgr` for `ibm.py` map cleanly to a FileService category?). May need taxonomy additions.
