# Section L — Output-Directory Picker Design

**Origin:** Section B file-picker pilot (2026-05-04) deferred output-directory
picking as Section L because it is a different abstraction — a directory
picker, not a file picker. The Section M rollout (2026-05-05) closed
file-picker coverage on 7 pages but left the 3 pages with `output_dir`
text inputs (`partitioning`, `grid_prep`, `postprocess`) unchanged. Section
L is that work.

## Goal

Add a project-aware directory picker to the 3 pages with `output_dir`
text inputs, mirroring Section M's coexistence pattern (picker UI rendered
above the existing text input; picker fills the text input via
`on_selected`). Picker enumerates existing subdirectories of the active
project's `work_dir` and includes a `+ Create` button for creating new
subdirectories inline.

## Non-goals

- **No auto-fill on project change.** Unlike `bas_path`/`grd_path`/`str_path`
  (which have project-tied canonical files in
  `proj["grids"][0].bas_file` / `proj["simulations"][0].str_file`), there
  is no canonical "the project's output directory." The existing
  fallback at use-time (`output_dir = input.output_dir() or
  str(<input_file>.parent)`) handles the empty case unchanged. The
  picker is a convenience to populate the text input on user click,
  nothing more.
- **No nested-tree widget.** A flat dropdown of relative paths
  (`OUTPUT`, `OUTPUT/run_001`, `runs/RUN_2026-04`) covers the SHYFEM
  project layout convention without the complexity of an expand/collapse
  tree component.
- **No reuse of `file_picker_server`.** The data sources are different
  (`FileService.list_files()` vs `Path(work_dir).rglob("*")`); the UX
  differs (Create-new flow has no analog in the file picker). A new
  `components/directory_picker.py` module keeps both pickers focused.
- **No retroactive Section M change.** The 7 file-picker pages
  (`partitioning`, `grid_prep`, `postprocess`, `physics`, `simulation`,
  `run`, `ibm`) are unchanged.

## Context — what already exists

`shyfem-ui/shyfem_ui/components/file_picker.py` (~340 LOC, post-Section-M)
exports:

- `file_picker_ui(label="Select File")` — UI module: dropdown + Browse.
- `file_picker_server(input, output, session, project_id, file_types,
  on_selected)` — server module: `FileService.list_files`-driven.
- `resolve_picker_path(project, rel_path) -> str | None` — pure helper:
  resolves rel_path against `project["work_dir"]`, runs `.is_relative_to(root)`
  containment guard, returns absolute path or None.
- `fill_picker_input(target_id, project, rel_path) -> None` — bridges
  `resolve_picker_path` to `ui.update_text` + `ui.notification_show`.
- `PickerTargetId = Literal["bas_path", "grd_path", "shy_path",
  "str_path", "input_file", "lgr_path"]`.

`output_dir` text inputs in 3 pages:

- `pages/partitioning.py:80` — placeholder "/path/to/output", consumed
  at line 265: `output_dir = input.output_dir() or str(bas_file.parent)`.
- `pages/grid_prep.py:77` — placeholder "/path/to/output", consumed at
  lines 303 + 404 (the second consumer also globs `*.bas` in it).
- `pages/postprocess.py:164` — placeholder "/path/to/output (default:
  same as input)", consumed at lines 518, 629, 775, 1106 (4 separate
  handlers, all using the same `or str(path.parent)` fallback).

All consumers validate via `config.validate_path(output_dir)` before
use. The text input is freeform — accepts any path on disk — and the
fallback covers empty input.

## Architecture

**One new module: `shyfem-ui/shyfem_ui/components/directory_picker.py`.**
Three exported names:

```python
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from shiny import module, reactive, ui

if TYPE_CHECKING:
    from shyfem_ui.services.project_context import ProjectContext

logger = logging.getLogger(__name__)


def list_project_directories(work_dir: str, cap: int = 100) -> list[str]:
    """List relative paths to all subdirectories of work_dir.

    Pure helper — testable without a Shiny session. Walks recursively
    via Path.rglob("*"), filters to actual directories (Path.is_dir()),
    sorts alphabetically, caps at the given limit. Returns a list of
    relative paths (e.g. ["OUTPUT", "OUTPUT/run_001", "runs/RUN_2026-04"]).

    Args:
        work_dir: Absolute path to the project work directory. If empty
            or missing on disk, returns [].
        cap: Maximum number of entries to return. If the directory has
            more, the result is truncated to the first cap entries (after
            sort). Default 100.

    Returns:
        Sorted list of relative paths. Empty list on missing/inaccessible
        work_dir or any unexpected exception (logged at WARNING).
    """
    if not work_dir:
        return []
    root = Path(work_dir)
    if not root.is_dir():
        return []
    try:
        entries = sorted(
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_dir()
        )
    except (PermissionError, OSError) as e:
        logger.warning("Failed to list directories under %r: %s", work_dir, e)
        return []
    if len(entries) > cap:
        entries = entries[:cap]
    return entries


def _validate_new_dir_name(name: str) -> tuple[bool, str | None]:
    """Validate a user-typed directory name from the Create modal.

    Returns (is_valid, error_message). Rejects:
    - Empty / whitespace-only.
    - Absolute paths (leading "/").
    - Path-traversal segments (".." anywhere in the path).
    - Single-dot segments ("./") — not malicious but redundant.

    Allows nested names like "runs/RUN_001" — Path.mkdir(parents=True)
    handles them.
    """
    name = (name or "").strip()
    if not name:
        return (False, "Directory name cannot be empty.")
    if name.startswith("/"):
        return (False, "Path must be project-relative (no leading '/').")
    parts = name.split("/")
    if any(p in ("", "..", ".") for p in parts):
        return (False, "Path must not contain '..' or empty segments.")
    return (True, None)


@module.ui
def directory_picker_ui(label: str = "Select Directory") -> ui.Tag:
    """Directory picker UI — dropdown + Create button.

    Renders three controls in a flex row:
    1. Dropdown (`dir_select`) listing existing subdirectories.
    2. "+ Create" button (`create_btn`) opening the create modal.
    """
    return ui.div(
        ui.div(
            ui.input_select(
                "dir_select",
                label,
                choices={"": "No directories available"},
                width="100%",
            ),
            class_="flex-grow-1",
        ),
        ui.div(
            ui.input_action_button(
                "create_btn",
                "+ Create",
                class_="btn-sm btn-outline-secondary mt-4",
            ),
            class_="ms-2",
        ),
        class_="d-flex align-items-start directory-picker-component",
    )


@module.server
def directory_picker_server(
    input,
    output,
    session,
    project_id: reactive.Value[int | None] | None = None,
    on_selected: Callable[[str], None] | None = None,
) -> reactive.Value[str]:
    """Directory picker server logic.

    Enumerates Path(work_dir).rglob("*") capped at 100 sorted entries,
    populates the dropdown, fires on_selected(rel_path) when the user
    picks. The Create modal lets the user mkdir a new subdirectory under
    work_dir; on success, the dropdown refreshes and the new entry is
    selected.

    Args:
        project_id: Reactive holding the active project's id. Used to
            re-load directory choices when the project changes. None
            means "no project loaded" -> dropdown shows placeholder.
        on_selected: Callback invoked with the chosen rel_path. Pages
            wire this via fill_picker_input("output_dir", ...) to write
            the absolute path into their existing output_dir text input.

    Returns:
        Reactive holding the currently-selected rel_path.
    """
    selected = reactive.value("")

    @reactive.calc
    def _work_dir() -> str:
        if project_id is None:
            return ""
        pid = project_id.get()
        if pid is None:
            return ""
        from shyfem_ui.services.project_context import load_project_context
        ctx = load_project_context(pid)
        return ctx.get("work_dir", "") if ctx else ""

    @reactive.effect
    def _refresh_choices():
        wd = _work_dir()
        dirs = list_project_directories(wd)
        if dirs:
            choices = {"": "Pick a directory…"}
            choices.update({d: d for d in dirs})
        else:
            choices = {"": "No directories available"}
        ui.update_select("dir_select", choices=choices)

    @reactive.effect
    @reactive.event(input.dir_select)
    def _on_select():
        val = input.dir_select()
        if val:
            selected.set(val)
            if on_selected is not None:
                on_selected(val)

    @reactive.effect
    @reactive.event(input.create_btn)
    def _open_create_modal():
        ui.modal_show(
            ui.modal(
                ui.input_text(
                    "new_dir_name",
                    "New directory name",
                    placeholder="e.g. OUTPUT/run_001",
                ),
                ui.input_action_button(
                    "create_confirm_btn",
                    "Create",
                    class_="btn-primary",
                ),
                ui.modal_button("Cancel"),
                title="Create new subdirectory",
                easy_close=True,
            )
        )

    @reactive.effect
    @reactive.event(input.create_confirm_btn)
    def _on_create_confirm():
        name = input.new_dir_name() or ""
        is_valid, err = _validate_new_dir_name(name)
        if not is_valid:
            ui.notification_show(err, type="error", duration=5)
            return
        wd = _work_dir()
        if not wd:
            ui.notification_show(
                "Cannot create directory: no active project.",
                type="error", duration=5,
            )
            return
        try:
            (Path(wd) / name).mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            logger.warning("mkdir failed for %r in %r: %s", name, wd, e)
            ui.notification_show(
                f"Failed to create directory: {e}",
                type="error", duration=6,
            )
            return
        # Refresh + select. Refresh fires via _refresh_choices's
        # _work_dir reactive dep; just update_select directly with new
        # name selected so the user sees immediate feedback.
        dirs = list_project_directories(wd)
        choices = {"": "Pick a directory…"}
        choices.update({d: d for d in dirs})
        ui.update_select("dir_select", choices=choices, selected=name)
        selected.set(name)
        if on_selected is not None:
            on_selected(name)
        ui.modal_remove()
        ui.notification_show(
            f"Directory created: {name}", type="message", duration=4,
        )

    return selected
```

**One-line extension to `components/file_picker.py`:**

```python
PickerTargetId = Literal[
    "bas_path", "grd_path", "shy_path",
    "str_path", "input_file", "lgr_path",
    "output_dir",  # added by Section L
]
```

`fill_picker_input("output_dir", project, rel_path)` then works unchanged.
`resolve_picker_path` resolves `Path(work_dir / rel_path).resolve()` and
the containment guard applies. `.resolve()` does not require existence,
so the helper handles paths created in the same session correctly.

## Per-page wiring (3 pages)

Pattern is identical for all three pages. In each:

1. Add import:
   ```python
   from shyfem_ui.components.directory_picker import (
       directory_picker_server,
       directory_picker_ui,
   )
   ```
   (`fill_picker_input` is already imported by Section M for the file
   picker; reuse it.)

2. In the page's `*_ui` function, immediately ABOVE the existing
   `ui.input_text("output_dir", ...)`:
   ```python
   directory_picker_ui("dp_output", label="Pick output directory from project"),
   ```

3. In the page's `*_server` function, alongside the existing
   `file_picker_server(...)` calls:
   ```python
   directory_picker_server(
       "dp_output",
       project_id=project_id_val,
       on_selected=lambda rel: fill_picker_input(
           "output_dir",
           active_project.get() if active_project else None,
           rel,
       ),
   )
   ```
   `project_id_val` already exists on each page from Section M (or
   `project_id_reactive` on simulation; Section L doesn't touch
   simulation since simulation has no `output_dir`).

No changes to existing `_on_project_changed` or `_on_tutorial_context`
effects — the picker has no auto-fill behaviour.

## UI shape

```
┌──────────────────────────────────────────────────────┐
│ [ Pick a directory…              v ]   [+ Create]    │  ← directory_picker_ui
├──────────────────────────────────────────────────────┤
│ Output Directory                                     │
│ [ /path/to/output                              ]     │  ← existing text input
└──────────────────────────────────────────────────────┘
```

The picker is a single row above the text input. `+ Create` opens a
modal:

```
┌─ Create new subdirectory ───────────┐
│                                     │
│ New directory name                  │
│ [ e.g. OUTPUT/run_001         ]     │
│                                     │
│        [ Create ]   [ Cancel ]      │
└─────────────────────────────────────┘
```

On submit: validates via `_validate_new_dir_name`, mkdirs with
`parents=True, exist_ok=True`, refreshes the dropdown, selects the new
entry, fires `on_selected`, shows a success toast, closes the modal.

## Data flow

```
User opens partitioning page
  → active_project.get() yields {"id": 7, "work_dir": "/var/lib/shyfem-ui/p7"}
  → project_id_val.set(7) inside _on_project_changed (existing)
  → directory_picker_server's _refresh_choices effect re-runs
    → list_project_directories("/var/lib/shyfem-ui/p7") returns
      ["OUTPUT", "OUTPUT/run_001", "runs/RUN_2026-04"]
    → dropdown populated with those 3 entries

User picks "OUTPUT/run_001"
  → directory_picker's _on_select effect fires
  → on_selected("OUTPUT/run_001") called
  → fill_picker_input("output_dir", active_project.get(), "OUTPUT/run_001")
  → resolve_picker_path returns "/var/lib/shyfem-ui/p7/OUTPUT/run_001"
  → ui.update_text("output_dir", value=<absolute>)
  → input.output_dir() now reads the absolute path

User clicks Run shyparts
  → existing handler reads input.output_dir()
  → config.validate_path(output_dir) (existing) validates absolute path
  → wrapper.run_shyparts(...) is invoked
```

For Create-new flow:

```
User clicks "+ Create"
  → modal opens

User types "runs/RUN_002" + clicks Create
  → _on_create_confirm fires
  → _validate_new_dir_name("runs/RUN_002") returns (True, None)
  → Path("/var/lib/shyfem-ui/p7/runs/RUN_002").mkdir(parents=True, exist_ok=True)
  → list_project_directories(...) re-listed (now includes new entry)
  → ui.update_select("dir_select", choices=..., selected="runs/RUN_002")
  → on_selected("runs/RUN_002") fires
  → text input filled with absolute path
  → Modal closes, success toast shows
```

## Error handling

| Scenario | Behavior |
|---|---|
| `work_dir` empty/missing on disk | `list_project_directories` returns `[]`; dropdown shows "No directories available"; `+ Create` button still works (creates at work_dir root) |
| `Path.rglob` raises `PermissionError`/`OSError` | Caught in `list_project_directories`, logged WARNING, returns `[]`; UI degrades to empty placeholder |
| User types `..` or `/` in Create modal | `_validate_new_dir_name` rejects with toast; modal stays open |
| `mkdir(parents=True, exist_ok=True)` fails (disk full, permission) | Caught, error toast shown, modal stays open for retry |
| Dir count exceeds 100 | Truncated to first 100 (sorted). No truncation indicator yet — flagged as deferred polish below |
| Selected dir was deleted externally | `resolve_picker_path` resolves the absolute path successfully (existence not checked); `fill_picker_input` writes it. Validation deferred to consumer's `config.validate_path` at use-time (existing) |

**Deferred polish (post-merge):** if list size exceeds cap, append
synthetic `(showing 100 of N — refine project layout)` entry to the
dropdown so the user knows results were truncated. Skip in this round
to keep scope tight.

## Tests

### Unit tests — pure helpers (`tests/test_directory_picker_logic.py`)

6 tests, all sync (no Shiny session):

1. `test_list_project_directories_basic` — `tmp_path` with 3 subdirs
   (one nested), verify sorted relative paths returned.
2. `test_list_project_directories_empty_workdir` — empty string returns
   `[]`.
3. `test_list_project_directories_missing_workdir` — non-existent path
   returns `[]`.
4. `test_list_project_directories_cap_respected` — `tmp_path` with 150
   subdirs, `cap=100`, verify result has exactly 100 entries (sorted).
5. `test_list_project_directories_filters_files` — `tmp_path` with 2
   dirs + 3 files at root + 1 file inside one dir, verify only the dirs
   appear.
6. `test_validate_new_dir_name` — parametrized over: `""`, `"   "`,
   `"/abs"`, `"foo/.."`, `"foo/."`, `"foo//bar"`, `"valid"`,
   `"runs/RUN_001"` — verify accept/reject pairs.

### Per-page unit tests (3 files, 2 tests each)

`tests/test_partitioning_dir_picker.py`, `tests/test_grid_prep_dir_picker.py`,
`tests/test_postprocess_dir_picker.py`. Each:

1. `test_picker_renders_above_output_dir` — render the page UI, assert
   `id="test-dp_output-dir_select"` appears in HTML before
   `id="test-output_dir"`.

2. `test_<page>_wires_directory_picker_server` — uses
   `tests._test_helpers.get_server_source` (closure-unwrap helper from
   Section M). Asserts:
   - `directory_picker_server(` appears in the unwrapped server source.
   - `re.search(r'fill_picker_input\(\s*"output_dir"', src)` matches
     (whitespace-tolerant per Section M's black-formatting fix).
   - The page imports `directory_picker_server` and
     `directory_picker_ui` from `components.directory_picker`.

### Helper extension test (`tests/test_file_picker_logic.py`)

1 new test in the existing `TestFillPickerInput` class:

`test_fill_picker_input_accepts_output_dir_target` — calls
`fill_picker_input("output_dir", proj, "OUTPUT/run_001")` and asserts
`ui.update_text` was called with target_id `"output_dir"` and the
absolute path. Pins the new Literal value works through the existing
helper.

### Playwright tests (`tests/test_playwright_directory_picker.py`)

5 Playwright tests against partitioning page (avoiding per-page
duplication that Section M's review flagged). Each uses the conftest
autouse `_reset_active_project_state` fixture (Section M.2 + 2dddf51
infrastructure):

1. `test_picker_shows_no_directories_when_no_project` — navigate to
   Partitioning, assert dropdown placeholder is "No directories
   available".
2. `test_typing_into_output_dir_is_not_clobbered` — type into the
   text input, assert value survives a project re-emit (regression
   for `_on_project_changed`'s isolate guard).
3. `test_pick_existing_directory_fills_text_input` — seed an
   `active_project` with `work_dir` containing one real subdir (use
   `tmp_path`), pick it from the dropdown, assert `output_dir`
   text input fills with the absolute path.
4. `test_create_new_directory_modal_happy_path` — set active_project
   with a tmp_path work_dir, click `+ Create`, type "runs/RUN_TEST",
   click Create. Assert modal closes, success toast appears,
   dropdown shows new entry selected, text input fills.
5. `test_create_new_directory_validation_rejects_traversal` — open
   the create modal, type "../escape", click Create. Assert error
   toast appears, modal stays open.

## Files

- **Create:** `shyfem-ui/shyfem_ui/components/directory_picker.py`
  (~150 LOC: `list_project_directories`, `_validate_new_dir_name`,
  `directory_picker_ui`, `directory_picker_server`).
- **Modify:** `shyfem-ui/shyfem_ui/components/file_picker.py` —
  1-line addition to `PickerTargetId` Literal.
- **Modify:** `shyfem-ui/shyfem_ui/pages/partitioning.py` — picker UI +
  server wiring (~10 added LOC).
- **Modify:** `shyfem-ui/shyfem_ui/pages/grid_prep.py` — same.
- **Modify:** `shyfem-ui/shyfem_ui/pages/postprocess.py` — same.
- **Create:** `shyfem-ui/tests/test_directory_picker_logic.py`
  (~80 LOC: 6 unit tests).
- **Create:** `shyfem-ui/tests/test_partitioning_dir_picker.py`
  (~50 LOC: 2 tests).
- **Create:** `shyfem-ui/tests/test_grid_prep_dir_picker.py`
  (~50 LOC: 2 tests).
- **Create:** `shyfem-ui/tests/test_postprocess_dir_picker.py`
  (~50 LOC: 2 tests).
- **Create:** `shyfem-ui/tests/test_playwright_directory_picker.py`
  (~150 LOC: 5 Playwright tests).
- **Modify:** `shyfem-ui/tests/test_file_picker_logic.py` — 1 new test
  in `TestFillPickerInput` (~15 LOC).
- **Modify:** `docs/followups/2026-04-29-ui-deep-review-deferred.md` —
  mark Section L complete on close-out.

**Net add:** ~430 LOC (component + tests + page wirings). Three pages
each get ~10 LOC. No deletions.

## Verification

After implementation:

1. `pytest tests/test_directory_picker_logic.py -v` → 6 pass (pure
   helper tests, no Shiny session).
2. `pytest tests/test_partitioning_dir_picker.py
   tests/test_grid_prep_dir_picker.py
   tests/test_postprocess_dir_picker.py -v` → 6 pass.
3. `pytest tests/test_file_picker_logic.py -v` → existing 11 tests +
   1 new = 12 pass.
4. `pytest tests/test_partitioning.py tests/test_partitioning_logic.py
   tests/test_grid_prep.py tests/test_grid_prep_logic.py
   tests/test_postprocess.py tests/test_postprocess_logic.py -q` →
   all pre-existing pass (no regression).
5. `pytest -q --ignore-glob='tests/test_playwright_*.py'` → ≥1900
   baseline + 9 new tests = ≥1909 pass.
6. `pytest tests/test_playwright_*.py -q --override-ini="addopts="`
   → 185 pre-existing + 5 new = 190 pass.
7. `ruff check --select F401,I shyfem_ui/components/directory_picker.py
   shyfem_ui/components/file_picker.py shyfem_ui/pages/partitioning.py
   shyfem_ui/pages/grid_prep.py shyfem_ui/pages/postprocess.py` → clean.
8. `black --check shyfem_ui/components/directory_picker.py
   shyfem_ui/components/file_picker.py` → clean.
9. Manual smoke test (optional): start the app in local mode, navigate
   to Partitioning, confirm the directory picker dropdown shows
   project subdirs, picking one fills `output_dir`, `+ Create`
   creates a new subdir and selects it.

## Wall-clock estimate

Implementation via subagent-driven dev:

| Task | ~Time |
|---|---|
| Module + helpers + 6 unit tests | 20 min |
| `PickerTargetId` extension + 1 helper test | 5 min |
| Partitioning wiring + 2 unit tests | 10 min |
| Grid_prep wiring + 2 unit tests | 10 min |
| Postprocess wiring + 2 unit tests | 10 min |
| Playwright file (5 tests) | 25 min |
| Final verification + ruff/black + commit | 15 min |
| Subagent review checkpoints | 30 min |
| **Total** | **~2 hours** |

## Lessons captured for the next session

- The `directory_picker.py` module is intentionally not generic over
  data sources. If a third picker abstraction emerges (e.g., remote-file
  picker, Git-tree picker), DO NOT unify them with file_picker via a
  mode flag. Each gets its own module; shared concerns (resolve, log,
  notify, update_text) live in `fill_picker_input` + `resolve_picker_path`
  in `file_picker.py` (the helper module, regardless of name).

- The deferred truncation indicator (cap=100 case) is a real UX gap.
  If a future complaint surfaces about "I have 200 dirs and the picker
  only shows 100", add the synthetic last entry. Cheap, no API change.

- The `_validate_new_dir_name` rejection rules are intentionally
  conservative (no `..`, no `/`, no empty segments). If users complain
  about legitimate names being rejected (e.g., paths with spaces or
  unicode), widen the allowed set explicitly rather than relaxing the
  guard wholesale.
