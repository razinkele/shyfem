# Section B Partitioning File-Picker Pilot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-05-01-section-b-partitioning-file-picker-design.md`

**Goal:** Wire the existing `components/file_picker.py` into `pages/partitioning.py` so users can pick `.bas` and `.grd` files from a project-aware dropdown instead of pasting absolute paths.

**Architecture:** Add a pure `resolve_picker_path` helper to `components/file_picker.py` (with traversal-containment guard and structured warnings), introduce a `ProjectContext` TypedDict at the construction site in `services/project_context.py`, then wire two `file_picker_server` calls in `partitioning_server` — picker selection fires a thin wrapper that fills the existing `bas_path`/`grd_path` text inputs via `ui.update_text`. The existing `_run_shyparts` handler is unchanged.

**Tech Stack:** Python 3.13, Shiny for Python, pytest, Playwright (for interactive UX tests). Test runner: `/opt/micromamba/envs/shiny/bin/python -m pytest`.

---

## Test Infrastructure Note

The codebase has **no in-process Shiny session test fixture** — `tests/_test_app.py` runs a full Shiny app via subprocess and is driven by Playwright. Crucially, Shiny's `@module.server` decorator (verified at shiny 1.5.1, `shiny/module.py`) requires `require_active_session(None)` plus `sess.make_scope(id)` — there is no public API for invoking a `@module.server`-decorated function outside a real session, and no `shiny.testing` module exists in this version. Therefore:

- **Pure helper tests** (1–5b) → unit tests with direct function calls. Don't need any Shiny machinery.
- **UI-render test** (6) → unit test rendering `partitioning_ui("test")` (which is `@module.ui`-decorated, NOT `@module.server`, and is callable directly) and parsing the resulting HTML string.
- **TypedDict shape pinning** (12) → unit test extending `test_project_context.py`, drives `_load` via real DB fixture.
- **All session-driven tests** (7, 8, 8b, 9, 10, 11) → Playwright tests in `test_playwright_partitioning_picker.py`. These cover wiring (file_types correctness via observable dropdown contents), reactive effects (auto-fill, empty-guard, no-retrigger), wrapper branches (success/failure/no-project), and the server-entry warning.

The default pytest run **excludes** `test_playwright_*.py` (`addopts = "--ignore-glob=tests/test_playwright_*.py"`). Run Playwright tests with: `pytest tests/test_playwright_partitioning_picker.py --override-ini="addopts="`.

This deviates from the spec's "Tests" section, which declared tests 7, 8b, and 11 as unit tests using a `tests/_test_app.py` fixture pattern. That pattern doesn't exist (the file is a subprocess entry point, not a fixture); the realistic equivalent is Playwright. Coverage stays the same; only the harness changes.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `shyfem_ui/services/project_context.py` | Owns the `ProjectContext` TypedDict + `_load`'s return shape | Modify (~30 added LOC) |
| `shyfem_ui/components/file_picker.py` | Owns `resolve_picker_path` (pure helper) alongside existing `build_file_choices` | Modify (~25 added LOC) |
| `shyfem_ui/pages/partitioning.py` | Wires picker UI + server calls + `_fill_bas`/`_fill_grd` wrappers | Modify (~50 added LOC) |
| `tests/test_file_picker_logic.py` | Pure helper unit tests (1–5, 5b) | Create (~80 LOC) |
| `tests/test_partitioning_file_picker.py` | Mock-based wiring + UI-render + captured-callback unit tests (6, 7, 8b, 11) | Create (~150 LOC) |
| `tests/test_playwright_partitioning_picker.py` | Session-driven tests (7, 8, 8b, 9, 10, 11) — placeholder, isolate regression, empty-guard, no-project silent return, traversal warning | Create (~250 LOC) |
| `tests/_test_app.py` | Add `__test_set_active_project` JS hook so Playwright can drive `active_project` from the test side | Modify (~15 added LOC) |
| `tests/test_project_context.py` | Add nested-shape pinning test (12) | Modify (~30 added LOC) |
| `docs/followups/2026-04-29-ui-deep-review-deferred.md` | Append Section L (output-dir picker) + Section M (6-page rollout) | Modify |

---

## Task 1: Add `ProjectContext` TypedDict to project_context.py

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/project_context.py`
- Modify: `shyfem-ui/shyfem_ui/tests/test_project_context.py`

**Convention note:** the existing codebase uses `@dataclass` (13 instances in `services/`) for typed value objects, not `TypedDict`. TypedDict is chosen here for three pilot-specific reasons:
1. `_load` already returns `dict` literals consumed downstream as JSON-like data; converting to dataclass instances would touch every page that reads `active_project["work_dir"]`.
2. The 7 pages that already destructure the dict are out-of-scope for this pilot — TypedDict is structurally compatible with the existing `dict | None` annotations.
3. The shape is a DB-row projection, not a behaviour-bearing object — there are no methods or invariants to enforce beyond key presence.

The 6-page rollout (Section M) is the natural place to revisit and convert to `@dataclass(frozen=True, slots=True)` if invariant enforcement becomes valuable.

- [ ] **Step 1: Write the failing test (test 12)**

Append to `shyfem-ui/tests/test_project_context.py`:

```python
class TestProjectContextShape:
    def test_load_returns_dict_with_required_keys(self, tmp_path):
        """Pin _load's runtime return shape to ProjectContext TypedDict.

        If _load drops a key (e.g., bas_file from a grid dict), this test
        fails immediately. Catches drift between the static TypedDict
        declaration and runtime construction.
        """
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import (
            Grid, Project, ProjectFile, Simulation,
        )
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="ctx_proj", work_dir=str(tmp_path / "p"))
            db.add(p); db.flush()
            db.add(Grid(
                project_id=p.id, name="g", grd_file="g.grd", bas_file="g.bas",
            ))
            db.add(Simulation(
                project_id=p.id, name="s", str_file="s.str",
            ))
            db.add(ProjectFile(
                project_id=p.id,
                filename="g.grd",
                rel_path="g.grd",
                file_type="grid",
                size_bytes=42,
            ))
            db.flush()
            pid = p.id

        ctx = load_project_context(pid)

        # Top-level ProjectContext keys
        assert ctx is not None
        assert set(ctx.keys()) >= {
            "id", "name", "work_dir", "description",
            "grids", "simulations", "files",
        }
        assert isinstance(ctx["id"], int)
        assert isinstance(ctx["name"], str)
        assert isinstance(ctx["work_dir"], str)

        # Pin the TypedDict declarations themselves — fails if a future
        # commit changes any TypedDict's annotated keys without also
        # changing _load. (Without this, dropping a TypedDict key
        # leaves the test passing because the runtime dict is intact.)
        # Nested TypedDicts must be pinned independently — Python's
        # __annotations__ on TypedDict is shallow, so the top-level
        # check doesn't recurse.
        from shyfem_ui.services.project_context import (
            FileEntry,
            GridEntry,
            ProjectContext,
            SimulationEntry,
        )
        assert set(ProjectContext.__annotations__.keys()) == {
            "id", "name", "work_dir", "description",
            "grids", "simulations", "files",
        }
        assert set(GridEntry.__annotations__.keys()) == {
            "name", "grd_file", "bas_file",
        }
        assert set(SimulationEntry.__annotations__.keys()) == {
            "name", "str_file",
        }
        assert set(FileEntry.__annotations__.keys()) == {
            "id", "filename", "rel_path", "file_type", "size_bytes",
        }

        # Nested GridEntry keys
        assert ctx["grids"], "expected at least one grid"
        g0 = ctx["grids"][0]
        assert set(g0.keys()) >= {"name", "grd_file", "bas_file"}

        # Nested SimulationEntry keys
        assert ctx["simulations"], "expected at least one simulation"
        s0 = ctx["simulations"][0]
        assert set(s0.keys()) >= {"name", "str_file"}

        # Nested FileEntry keys
        assert ctx["files"], "expected at least one file"
        f0 = ctx["files"][0]
        assert set(f0.keys()) >= {
            "id", "filename", "rel_path", "file_type", "size_bytes",
        }
        assert isinstance(f0["id"], int)
        assert isinstance(f0["size_bytes"], int)
```

- [ ] **Step 2: Run the test to verify it errors (TypedDicts don't exist yet)**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_project_context.py::TestProjectContextShape::test_load_returns_dict_with_required_keys -v`

Expected: **ERROR** with `ImportError: cannot import name 'ProjectContext' from 'shyfem_ui.services.project_context'`. The test imports `ProjectContext`, `GridEntry`, `SimulationEntry`, `FileEntry` to pin the TypedDict declarations — none exist yet at this point. This is the TDD red phase: the test cannot pass until Step 3 adds the TypedDicts, and that's the point. If pytest instead reports PASS or a different error, the test or the existing file state is wrong — investigate before continuing.

- [ ] **Step 3: Add the TypedDict declarations**

Modify `shyfem-ui/shyfem_ui/services/project_context.py`. Replace the imports block at lines 1–5:

```python
"""Load full project context from DB for active-project state."""

from typing import TypedDict

from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Grid, Project, ProjectFile, Simulation
from shyfem_ui.services.access_control import check_project_access


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

- [ ] **Step 4: Re-annotate `_load` and `load_project_context` return types**

In the same file:

- Change `def load_project_context(...) -> dict | None:` to `def load_project_context(...) -> ProjectContext | None:`
- Change `def _load(db, project_id: int) -> dict | None:` to `def _load(db, project_id: int) -> ProjectContext | None:`

Leave the body unchanged — the existing dict literal is structurally compatible with `ProjectContext`.

- [ ] **Step 5: Run the test again to confirm still passing**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_project_context.py -v`

Expected: All tests pass (existing 4 tests + new shape-pinning test = 5 total).

- [ ] **Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/project_context.py shyfem-ui/tests/test_project_context.py
git commit -m "feat(ui): add ProjectContext TypedDict to project_context

Declares structural shape (ProjectContext + nested GridEntry,
SimulationEntry, FileEntry) at the _load construction site. Pins
runtime shape with a new test that fails immediately if _load
drops a key. Required by upcoming file-picker integration which
will type resolve_picker_path against ProjectContext | None."
```

---

## Task 2: Add `resolve_picker_path` helper to file_picker.py

**Files:**
- Modify: `shyfem-ui/shyfem_ui/components/file_picker.py`
- Create: `shyfem-ui/tests/test_file_picker_logic.py`

- [ ] **Step 1: Create the test file with all 6 helper tests (TDD - failing)**

Create `shyfem-ui/tests/test_file_picker_logic.py`:

```python
"""Pure unit tests for resolve_picker_path helper in components.file_picker.

These tests do NOT need a Shiny session — resolve_picker_path is a pure
helper that takes a dict and a string and returns a string or None.
"""

import logging


# Full ProjectContext-compatible literal used by happy-path tests.
# Annotated as ProjectContext (not bare dict) so mypy --strict accepts
# passing the result to resolve_picker_path (which expects
# ProjectContext | None). TypedDicts are nominal in mypy — bare dict
# literals don't satisfy the type without explicit narrowing.
from shyfem_ui.services.project_context import ProjectContext

def _proj(work_dir: str, project_id: int = 7) -> ProjectContext:
    return {
        "id": project_id,
        "name": "test",
        "work_dir": work_dir,
        "description": None,
        "grids": [],
        "simulations": [],
        "files": [],
    }


class TestResolvePickerPath:
    def test_resolve_picker_path_basic(self, tmp_path):
        """Happy path: project + valid rel_path resolves to absolute."""
        from shyfem_ui.components.file_picker import resolve_picker_path

        result = resolve_picker_path(_proj(str(tmp_path)), "BAS/sim.bas")
        assert result == str((tmp_path / "BAS" / "sim.bas").resolve())

    def test_resolve_picker_path_returns_none_when_no_project(self):
        from shyfem_ui.components.file_picker import resolve_picker_path

        assert resolve_picker_path(None, "anything") is None

    def test_resolve_picker_path_returns_none_when_empty_relpath(self, tmp_path):
        from shyfem_ui.components.file_picker import resolve_picker_path

        assert resolve_picker_path(_proj(str(tmp_path)), "") is None
        assert resolve_picker_path(_proj(str(tmp_path)), None) is None

    def test_resolve_picker_path_rejects_traversal(self, tmp_path, caplog):
        """Path-traversal containment guard returns None and logs warning.

        Filtered to logger 'shyfem_ui.components.file_picker' so other
        loggers' warnings don't pollute the assertion.
        """
        from shyfem_ui.components.file_picker import resolve_picker_path

        proj = _proj(str(tmp_path))

        # Case 1: ../-style traversal
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path(proj, "../../etc/passwd") is None
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "../../etc/passwd" in recs[0].getMessage()

        # Case 2: absolute path silently overrides Path / __truediv__
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path(proj, "/etc/passwd") is None
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "/etc/passwd" in recs[0].getMessage()

    def test_resolve_picker_path_rejects_shape_defects(self, caplog):
        """Missing or empty work_dir returns None and logs warning."""
        from shyfem_ui.components.file_picker import resolve_picker_path

        # Missing work_dir key entirely
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path({"id": 7}, "x") is None  # type: ignore[arg-type]
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "7" in recs[0].getMessage()

        # Empty work_dir string
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path({"id": 8, "work_dir": ""}, "x") is None  # type: ignore[arg-type]
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "8" in recs[0].getMessage()

        # Explicit work_dir=None — the `if not work_dir:` guard handles
        # this, but a future refactor to `if work_dir is None or
        # work_dir == "":` could silently change which branch fires.
        # Pin the contract.
        with caplog.at_level(logging.WARNING, logger="shyfem_ui.components.file_picker"):
            caplog.clear()
            assert resolve_picker_path({"id": 9, "work_dir": None}, "x") is None  # type: ignore[arg-type]
            recs = [r for r in caplog.records if r.name == "shyfem_ui.components.file_picker"]
            assert len(recs) == 1
            assert "9" in recs[0].getMessage()

    def test_resolve_picker_path_accepts_project_context_shape(self, tmp_path):
        """Test 5b: full ProjectContext-shaped dict resolves correctly.

        Pins the helper to a faithful runtime shape without crossing into
        the services layer (no DB fixture, no _load import).
        """
        from shyfem_ui.components.file_picker import resolve_picker_path

        ctx = {
            "id": 7,
            "name": "test",
            "work_dir": str(tmp_path),
            "description": None,
            "grids": [{"name": "g", "grd_file": "g.grd", "bas_file": "g.bas"}],
            "simulations": [],
            "files": [],
        }
        result = resolve_picker_path(ctx, "BAS/sim.bas")
        assert result == str((tmp_path / "BAS" / "sim.bas").resolve())
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_file_picker_logic.py -v`

Expected: 6 tests fail with `ImportError: cannot import name 'resolve_picker_path' from 'shyfem_ui.components.file_picker'`.

- [ ] **Step 3: Add `resolve_picker_path` to file_picker.py**

Modify `shyfem-ui/shyfem_ui/components/file_picker.py`. At the top of the file, add to the existing imports (insert after `from collections.abc import Callable` at line 4):

```python
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shyfem_ui.services.project_context import ProjectContext
```

Use `TYPE_CHECKING` to avoid an unconditional import — `services.project_context` imports from `db.base` which initializes the engine; pulling that in at every `from components.file_picker import` would slow startup unnecessarily. The string annotation `"ProjectContext | None"` works at runtime without the import.

Then add a new top-level function — insert it AFTER the existing `build_file_choices` function (after the `def build_file_choices(...)` block ends, before the `@module.ui` decorator for `file_picker_ui`):

```python
def resolve_picker_path(
    active_project: "ProjectContext | None",
    rel_path: str | None,
) -> str | None:
    """Resolve a project-relative path to an absolute path.

    Returns None if the project is unknown, rel_path is empty, or the
    resolved path would escape the project work_dir (path traversal
    guard — Path(work_dir) / "/etc/passwd" silently yields /etc/passwd,
    and Path(work_dir) / "../../etc" escapes the root).

    The traversal-containment failure and missing-work_dir branches log
    a WARNING since they indicate a programmer error or
    dropdown/project state mismatch — silent None would hide bugs.

    Args:
        active_project: ProjectContext-shaped dict or None.
        rel_path: Project-relative path from a picker dropdown, or None.

    Returns:
        Absolute path string contained within work_dir, or None.
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
            "Picker rel_path %r escapes work_dir %r — "
            "dropdown/project state mismatch",
            rel_path, work_dir,
        )
        return None
    return str(resolved)
```

Note: the parameter type is `ProjectContext | None` as a forward-reference string annotation (`TYPE_CHECKING` guards the import). At runtime the value is a plain dict — TypedDict is structurally validated only by static checkers — so no isinstance checks or schema validation are needed. The string annotation keeps `from shyfem_ui.components.file_picker import resolve_picker_path` cheap.

The `logger` used in this function is already defined at line 8 of `components/file_picker.py` as `logger = logging.getLogger(__name__)` — do not re-define.

Returns `str | None` collapses 5 distinct failure paths (None project, empty rel_path, missing work_dir, empty work_dir, traversal). Callers needing branch info must consume the WARNING log records — the return value alone does not differentiate. Document this in the docstring (the "Returns None if..." sentence already names all five cases).

- [ ] **Step 4: Run the tests to verify all 6 pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest shyfem-ui/tests/test_file_picker_logic.py -v`

Expected: 6 passed.

- [ ] **Step 5: Run F401 check on file_picker.py**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401 shyfem_ui/components/file_picker.py`

Expected: clean (no orphaned imports).

- [ ] **Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/components/file_picker.py shyfem-ui/tests/test_file_picker_logic.py
git commit -m "feat(ui): add resolve_picker_path helper to file_picker

Pure helper with path-traversal containment guard — rejects rel_path
values that escape work_dir (../-style or absolute), logs WARNING on
the security-relevant branch and on missing/empty work_dir. 6 unit
tests cover happy path, no-project, empty rel_path, traversal
rejection, shape defects, and full ProjectContext-shape acceptance."
```

---

## Task 3: Add picker UI to partitioning_ui

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py:27-46`

- [ ] **Step 1: Add the file_picker import**

Modify `shyfem-ui/shyfem_ui/pages/partitioning.py`. After line 11 (`from shyfem_ui.components.grid_map import ...`), add:

```python
from shyfem_ui.components.file_picker import (
    file_picker_server,
    file_picker_ui,
    resolve_picker_path,
)
```

- [ ] **Step 2: Add picker UIs above the existing text inputs**

In `partitioning_ui`, replace the block at lines 36–46:

```python
                ui.h5("Input Basin"),
                ui.input_text(
                    "bas_path",
                    "Basin File (.bas)",
                    placeholder="/path/to/basin.bas",
                ),
                ui.input_text(
                    "grd_path",
                    "Grid File (.grd) for visualization",
                    placeholder="/path/to/grid.grd (optional)",
                ),
```

with:

```python
                ui.h5("Input Basin"),
                file_picker_ui("fp_bas", label="Pick basin from project"),
                ui.input_text(
                    "bas_path",
                    "Basin File (.bas)",
                    placeholder="/path/to/basin.bas",
                ),
                file_picker_ui("fp_grd", label="Pick grid from project"),
                ui.input_text(
                    "grd_path",
                    "Grid File (.grd) for visualization",
                    placeholder="/path/to/grid.grd (optional)",
                ),
```

- [ ] **Step 3: Verify the page still imports cleanly**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -c "from shyfem_ui.pages import partitioning; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Run F401 check**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401 shyfem_ui/pages/partitioning.py`

Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/partitioning.py
git commit -m "feat(ui): add file picker UI controls above bas/grd path inputs

Two file_picker_ui modules (fp_bas, fp_grd) rendered above the existing
text inputs in partitioning_ui. Server wiring follows in next commit."
```

---

## Task 4: Wire picker server + project_id_val + modified _on_project_changed

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/partitioning.py:118-145`

- [ ] **Step 1: Add the `cast` and `TYPE_CHECKING` imports**

In `shyfem-ui/shyfem_ui/pages/partitioning.py`, add `from typing import TYPE_CHECKING, cast` immediately after `from pathlib import Path` (line 4) — keep it in the **stdlib import group**, BEFORE the first-party `from shyfem_ui.…` imports. The codebase uses ruff's isort (`select = ["I"]` in `pyproject.toml`), so misplaced imports fail CI.

Then add the `TYPE_CHECKING` block at the END of the imports block, after all the first-party imports:

```python
from typing import TYPE_CHECKING, cast

# (existing stdlib + third-party imports follow)
# (existing first-party shyfem_ui.* imports follow)

if TYPE_CHECKING:
    from shyfem_ui.services.project_context import ProjectContext
```

Run `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select I shyfem_ui/pages/partitioning.py` after this step to confirm ordering — expected: clean.

- [ ] **Step 2: Replace `_on_project_changed` with the modified version**

Replace lines 127–144 of `partitioning.py` (the docstring, the `wrapper =` line, and the existing auto-fill effect):

```python
    """Mesh partitioning page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # Auto-fill from active project
    @reactive.effect
    def _on_project_changed():
        if active_project is None:
            return
        proj = active_project.get()
        if proj is None:
            return
        work = proj["work_dir"]
        if proj["grids"]:
            grid = proj["grids"][0]
            if grid.get("bas_file"):
                ui.update_text("bas_path", value=str(Path(work) / grid["bas_file"]))
            if grid.get("grd_file"):
                ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))
```

with:

```python
    """Mesh partitioning page server logic."""
    wrapper = ShyfemWrapper(config.shyfem_dir)

    # Reactive value for picker project_id, updated inside _on_project_changed.
    # `reactive.value` is just an alias for the class `reactive.Value`
    # (verified — `reactive.value is reactive.Value` returns True).
    # Use the capital-V class name in the annotation (canonical), and
    # the lowercase callable form for construction (idiomatic).
    project_id_val: reactive.Value[int | None] = reactive.value(None)

    # active_project is None means the page was mounted without injection
    # (a wiring bug). Constant for the lifetime of this server invocation,
    # so log once at server entry rather than inside the effect.
    if active_project is None:
        logger.warning(
            "partitioning_server received active_project=None — "
            "page wiring bug? File picker dropdowns will stay empty."
        )

    # Auto-fill from active project
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
            # reactive.isolate() prevents input.bas_path()/input.grd_path()
            # from registering as dependencies of this effect; without it,
            # every keystroke would re-fire and clobber the user's edit.
            with reactive.isolate():
                bas_empty = not input.bas_path()
                grd_empty = not input.grd_path()
            if grid.get("bas_file") and bas_empty:
                ui.update_text("bas_path", value=str(Path(work) / grid["bas_file"]))
            if grid.get("grd_file") and grd_empty:
                ui.update_text("grd_path", value=str(Path(work) / grid["grd_file"]))

    # File picker wrappers — distinguish benign empty-state (no project)
    # from a real mismatch (user picked a stale dropdown entry). The
    # latter logs + shows a notification toast so the user understands
    # why the click didn't fill the text input.
    def _fill_bas(rel_path: str) -> None:
        proj = active_project.get() if active_project else None
        absolute = resolve_picker_path(cast("ProjectContext | None", proj), rel_path)
        if absolute is None:
            if proj is not None and rel_path:
                # Include target ('bas_path') in the message so callers
                # filtering caplog or querying logs can disambiguate
                # which input failed to resolve. Required for the
                # eventual shared `fill_picker_input` extraction at
                # the Section M deadline.
                logger.warning(
                    "Picker selection %r could not be resolved for "
                    "project %r (target=bas_path, work_dir missing "
                    "or traversal guard rejected)",
                    rel_path, proj.get("id"),
                )
                ui.notification_show(
                    "Could not resolve selected file. Try re-selecting "
                    "after the project finishes loading.",
                    type="warning", duration=5,
                )
            return
        ui.update_text("bas_path", value=absolute)

    def _fill_grd(rel_path: str) -> None:
        proj = active_project.get() if active_project else None
        absolute = resolve_picker_path(cast("ProjectContext | None", proj), rel_path)
        if absolute is None:
            if proj is not None and rel_path:
                logger.warning(
                    "Picker selection %r could not be resolved for "
                    "project %r (target=grd_path, work_dir missing "
                    "or traversal guard rejected)",
                    rel_path, proj.get("id"),
                )
                ui.notification_show(
                    "Could not resolve selected file. Try re-selecting "
                    "after the project finishes loading.",
                    type="warning", duration=5,
                )
            return
        ui.update_text("grd_path", value=absolute)

    # Wire pickers — file_types filter ensures dropdown shows only
    # the right kind of file per input.
    file_picker_server(
        "fp_bas",
        project_id=project_id_val,
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

- [ ] **Step 3: Verify the page imports and the existing partitioning tests still pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_partitioning.py tests/test_partitioning_logic.py tests/test_pages_access_control.py -q`

Expected: All existing tests pass (no regression).

- [ ] **Step 4: Run F401 check**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401 shyfem_ui/pages/partitioning.py`

Expected: clean.

- [ ] **Step 5: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/partitioning.py
git commit -m "feat(ui): wire file_picker_server for bas/grd inputs in partitioning

Adds project_id_val reactive (updated inside the existing
_on_project_changed effect, single source of truth, single observer).
Adds two file_picker_server calls with file_types=['basin'] and
['grid']. Adds _fill_bas/_fill_grd wrappers that resolve the
project-relative rel_path and write to the existing text inputs;
logs + notifies on resolution failure so user-driven clicks that fail
don't disappear silently.

Adds reactive.isolate() around input.bas_path()/input.grd_path()
reads inside _on_project_changed to prevent keystrokes from
re-triggering the effect, and a 'not input.X()' empty-guard so
project re-emits don't clobber picker selections.

Logs a one-shot WARNING at server entry if active_project is None,
which would indicate a page wiring bug for the 6-page rollout."
```

---

## Task 5: Add the UI-render unit test (test 6)

**Files:**
- Create: `shyfem-ui/tests/test_partitioning_file_picker.py`

- [ ] **Step 1: Create the test file with test 6**

The other session-driven tests (7, 8, 8b, 9, 10, 11) all need a Shiny session — they go in the Playwright file in Task 6. This file holds only the UI-render test, which works directly because `partitioning_ui` is `@module.ui`-decorated (callable as a regular function with a namespace argument).

Create `shyfem-ui/tests/test_partitioning_file_picker.py`:

```python
"""Unit tests for partitioning page file-picker UI rendering.

Only contains tests that don't need a Shiny session. Session-driven
tests (wiring, reactive effects, wrapper branches) live in
tests/test_playwright_partitioning_picker.py because @module.server
in shiny 1.5.1 cannot be invoked outside an active session
(verified — no shiny.testing module exists in this version).
"""


class TestPickerUiRenders:
    def test_picker_ui_renders_for_bas_and_grd(self):
        """Test 6: the picker <select>s appear above the text inputs.

        Renders partitioning_ui('test') (the namespace argument is
        required — partitioning_ui is decorated with @module.ui).
        Asserts exactly one <select id='test-fp_bas-...'> and one
        <select id='test-fp_grd-...'> appear, AND that each precedes
        the corresponding text-input id in the rendered HTML.
        """
        from shyfem_ui.pages.partitioning import partitioning_ui

        tag = partitioning_ui("test")
        html = str(tag)

        # Picker selects exist, namespaced under the module ID
        assert 'id="test-fp_bas-file_select"' in html, (
            "expected picker <select id='test-fp_bas-file_select'>"
        )
        assert 'id="test-fp_grd-file_select"' in html, (
            "expected picker <select id='test-fp_grd-file_select'>"
        )

        # bas picker appears before bas_path text input
        bas_picker_pos = html.find('id="test-fp_bas-file_select"')
        bas_input_pos = html.find('id="test-bas_path"')
        assert bas_picker_pos != -1 and bas_input_pos != -1
        assert bas_picker_pos < bas_input_pos, (
            "fp_bas picker must render before bas_path text input"
        )

        # grd picker appears before grd_path text input
        grd_picker_pos = html.find('id="test-fp_grd-file_select"')
        grd_input_pos = html.find('id="test-grd_path"')
        assert grd_picker_pos != -1 and grd_input_pos != -1
        assert grd_picker_pos < grd_input_pos, (
            "fp_grd picker must render before grd_path text input"
        )


class TestModuleImports:
    """Defensive guard + wiring assertion for the file picker integration.

    `hasattr(part_mod, 'file_picker_server')` alone is too weak — it
    passes if the symbol is rebound to None, aliased internally, or
    even left unused. The Playwright tests would silently pass too
    (they just check dropdown contents). This test verifies BOTH:
    (a) the symbol on the page module is the same callable from the
        component module (no aliasing / shadowing);
    (b) `partitioning_server`'s source actually CALLS file_picker_server
        twice with the right `file_types` filters — equivalent to spec
        test 7's wiring assertion, just done via source inspection
        since shiny 1.5.1 has no in-process @module.server invocation.
    """

    def test_partitioning_imports_and_wires_file_picker_server(self):
        import inspect

        import shyfem_ui.pages.partitioning as part_mod
        from shyfem_ui.components import file_picker as fp_mod

        # Identity check — the page's symbol IS the component's function
        assert hasattr(part_mod, "file_picker_server"), (
            "partitioning.py must do `from ...file_picker import "
            "file_picker_server` (no aliasing, no deferred import)"
        )
        assert part_mod.file_picker_server is fp_mod.file_picker_server, (
            "partitioning.file_picker_server must be the SAME object as "
            "components.file_picker.file_picker_server (no shadowing)"
        )
        assert hasattr(part_mod, "file_picker_ui")
        assert hasattr(part_mod, "resolve_picker_path")

        # Wiring assertion — partitioning_server source contains the
        # right two file_picker_server calls with the right file_types.
        src = inspect.getsource(part_mod.partitioning_server)
        assert src.count("file_picker_server(") >= 2, (
            "expected at least 2 file_picker_server calls "
            "(fp_bas + fp_grd) in partitioning_server"
        )
        assert 'file_types=["basin"]' in src, (
            "expected file_types=['basin'] for the .bas picker"
        )
        assert 'file_types=["grid"]' in src, (
            "expected file_types=['grid'] for the .grd picker"
        )

        # Spec test 8b — pin the active_project=None warning message.
        # Stderr capture from the test subprocess is unreachable from
        # tests (blocking PIPE), so source-inspection is the closest
        # we can get to runtime verification without a Shiny session.
        # The warning is load-bearing for the 6-page rollout — page
        # authors copying this pattern need it to fire when they
        # forget to inject active_project.
        assert "received active_project=None" in src, (
            "expected the active_project=None wiring-bug warning "
            "in partitioning_server (spec test 8b)"
        )
```

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_partitioning_file_picker.py -v`

Expected: 2 passed (`test_picker_ui_renders_for_bas_and_grd`, `test_partitioning_imports_and_wires_file_picker_server`).

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/tests/test_partitioning_file_picker.py
git commit -m "test(ui): UI-render + import-style unit tests for partitioning pickers

- test_picker_ui_renders_for_bas_and_grd: parses partitioning_ui('test')
  HTML; asserts the two picker <select>s render before their
  corresponding text inputs.
- test_partitioning_imports_and_wires_file_picker_server: identity
  guard (page symbol IS the component function) + wiring assertion
  (partitioning_server source contains 2 file_picker_server calls
  with file_types=['basin'] and file_types=['grid']). Equivalent to
  spec test 7 since shiny 1.5.1 has no @module.server invocation API.

Session-driven tests (wiring, reactive effects, wrapper branches)
follow in test_playwright_partitioning_picker.py since shiny 1.5.1
has no in-process @module.server invocation API."
```

---

## Task 6: Add Playwright tests for session-driven behaviour (tests 7 + 8 + 8b + 9 + 10 + 11)

**Files:**
- Create: `shyfem-ui/tests/test_playwright_partitioning_picker.py`

This task absorbs the spec's tests 7, 8, 8b, 9, 10, 11 — all of them require a Shiny session to fire reactive effects or wrap a server invocation. Coverage equivalence:

| Spec test | Playwright equivalent |
|---|---|
| 7 (file_types correctness) | Inspect dropdown contents — basin picker shows only `.bas` files, grid picker only `.grd`. |
| 8 (project_id_val tracks active_project) | After project switch, basin picker dropdown populates with that project's basin files. |
| 8b (active_project=None warning) | **Source-inspection assertion** in `test_partitioning_file_picker.py`'s wiring guard (asserts the warning string is present in `partitioning_server`'s source). Stderr capture would block on the subprocess pipe (`tests/conftest.py:_app_server` uses `stderr=subprocess.STDOUT` with no live reader), so runtime-fire verification is deferred to manual smoke test step 4c. |
| 9 (empty-guard) | Type path → navigate away → navigate back → assert path preserved. |
| 10 (reactive.isolate regression) | Type into `bas_path` → assert field doesn't get cleared by retrigger. |
| 11(a) success / 11(c) no-project | Playwright tests in this file (`test_picker_callback_silent_on_no_project` covers 11(c); 11(a) success covered by manual smoke test step 4c since it requires a real seeded project). |
| 11(b) wrapper traversal-failure | Playwright test `test_picker_callback_warns_on_traversal` — after seeding active_project via the JS hook, dispatch an `/etc/passwd` selection through `Shiny.setInputValue` and assert one `.shiny-notification` with `data-type="warning"` appears (since the helper-level traversal log is not visible cross-process, the user-visible side-effect — the toast — is the testable signal). Also `pytest.skip` if the JS hook isn't wired. |

- [ ] **Step 1: Wire `__test_set_active_project` JS hook in _test_app.py**

Tests 9 and 11(b) require setting `active_project` to a non-None value from JS during a Playwright run. Without this hook, those tests `pytest.skip` and the empty-guard + traversal-failure wrapper branches are NOT exercised in CI. The hook is small, scoped to the test app only, and never ships in production.

In `shyfem-ui/tests/_test_app.py`, modify the `server` function (around line 196). After the line `active_project = reactive.value(None)` (line 197), add a Shiny input listener that wires the JS-callable hook:

```python
    def server(input, output, session):
        active_project = reactive.value(None)
        tutorial_context = reactive.value(None)

        # Test-only debug hook: lets Playwright tests inject an
        # active_project value directly via Shiny.setInputValue.
        # The corresponding JS-side helper is registered below in
        # the head_content extras.
        @reactive.effect
        @reactive.event(input._test_set_active_project)
        def _test_active_project_hook():
            value = input._test_set_active_project()
            active_project.set(value if value else None)
```

Then locate the `_HEAD_EXTRAS` constant (used in `app_ui = ui.page_fillable(ui.head_content(_HEAD_EXTRAS), ...)` around line 186) and append a `<script>` block that exposes `window.__test_set_active_project` as a thin wrapper around `Shiny.setInputValue`. If `_HEAD_EXTRAS` is hard to extend in place, add a new `ui.tags.script(...)` element directly inside the `head_content(...)` call. The script is:

```html
<script>
window.__test_set_active_project = function(projectDict) {
    Shiny.setInputValue(
        '_test_set_active_project',
        projectDict,
        {priority: 'event'}
    );
};
</script>
```

- [ ] **Step 2: Create the Playwright test file**

Create `shyfem-ui/tests/test_playwright_partitioning_picker.py`:

```python
"""Playwright tests for partitioning file-picker session-driven behaviour.

These tests require a running Shiny app — shiny 1.5.1 has no public
API for invoking @module.server-decorated functions outside an active
session, so all wiring/effect/wrapper tests live here.

Run with:

    pytest tests/test_playwright_partitioning_picker.py \\
        --override-ini="addopts="

(default pytest config excludes test_playwright_*.py via
addopts = "--ignore-glob=tests/test_playwright_*.py").
"""

import pytest


@pytest.mark.e2e
class TestPartitioningPickerNoProject:
    """Behaviour when no active project is set (the default for the
    test app at session startup). Covers spec tests 7 (placeholder),
    10 (isolate regression), and 11(c) (no-project branch).
    """

    def test_picker_shows_no_files_available_when_no_project(
        self, pw_page, live_server,
    ):
        """Spec test 7 / partial: project_id=None branch of file_picker
        renders the 'No files available' placeholder.
        """
        pw_page.locator('a[data-target="Partitioning"]').click(force=True)
        pw_page.wait_for_timeout(1000)

        # Shiny's input_select uses Selectize.js by default — it hides the
        # native <select> (display:none) and renders a custom widget. The
        # <option> children are still in the DOM though, so query them
        # directly to be Selectize-agnostic.
        select = pw_page.locator('#partitioning-fp_bas-file_select')
        select.wait_for(state="attached", timeout=5000)
        option_texts = pw_page.locator(
            '#partitioning-fp_bas-file_select option'
        ).all_inner_texts()
        assert any("No files available" in t for t in option_texts), (
            f"expected 'No files available' placeholder, got options: {option_texts!r}"
        )

    def test_typing_into_bas_path_is_not_clobbered_by_reactive_effect(
        self, pw_page, live_server,
    ):
        """Spec test 10: reactive.isolate guard regression.

        Without reactive.isolate(), typing into bas_path would re-fire
        _on_project_changed every keystroke. The isolate + empty-guard
        together must let the typed value survive.
        """
        pw_page.locator('a[data-target="Partitioning"]').click(force=True)
        pw_page.wait_for_timeout(800)

        bas_input = pw_page.locator('#partitioning-bas_path')
        bas_input.wait_for(state="attached", timeout=5000)
        bas_input.fill("/tmp/manual-typed.bas")
        pw_page.wait_for_timeout(800)

        actual = bas_input.input_value()
        assert actual == "/tmp/manual-typed.bas", (
            f"bas_path was clobbered by a re-fired reactive effect: {actual!r}"
        )

    def test_empty_guard_preserves_user_input_across_navigation(
        self, pw_page, live_server,
    ):
        """Spec test 9: empty-guard regression.

        After typing a value into bas_path, set active_project to a
        project with bas_file (this triggers _on_project_changed's
        auto-fill branch), and assert the typed value survives.

        IMPORTANT: this test only exercises the empty-guard if
        active_project is set to a non-None value with a 'grids' list
        containing a 'bas_file'. In the default _test_app.py,
        active_project is reactive.value(None) and stays None unless
        explicitly set — so we set it via the JS Shiny.setInputValue
        path through a hidden test-only input (added in _test_app.py).
        Without this, the test would still pass but for the WRONG
        reason: _on_project_changed returns early at `proj is None`
        and never reaches the auto-fill block. The guard is then
        unexercised.

        If your environment doesn't expose this fixture, this test
        falls back to the no-project path and is functionally a
        duplicate of test 10. Mark with @pytest.mark.skipif if so;
        do not let a false-pass green-light the empty-guard.
        """
        pw_page.locator('a[data-target="Partitioning"]').click(force=True)
        pw_page.wait_for_timeout(800)

        bas_input = pw_page.locator('#partitioning-bas_path')
        bas_input.fill("/tmp/preset-value.bas")
        pw_page.wait_for_timeout(300)

        # Set active_project via the test app's debug hook. If the hook
        # doesn't exist, skip this test rather than letting it false-pass.
        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p',
                work_dir: '/tmp/p',
                description: null,
                grids: [{name: 'g', grd_file: 'g.grd', bas_file: 'g.bas'}],
                simulations: [],
                files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip(
                "test_app.py does not expose __test_set_active_project; "
                "empty-guard regression cannot be exercised — "
                "without active_project set to a real value, the "
                "auto-fill branch never runs and the guard is "
                "unexercised. Add the hook to _test_app.py to enable."
            )
        pw_page.wait_for_timeout(800)

        actual = bas_input.input_value()
        assert actual == "/tmp/preset-value.bas", (
            f"empty-guard failed; bas_path was overwritten to {actual!r}"
        )

    def test_picker_callback_silent_on_no_project(
        self, pw_page, live_server,
    ):
        """Spec test 11(c): _fill_bas with no project returns silently.

        Shiny's input_select uses Selectize.js, which hides the native
        `<select>` and swallows native `change` events on the hidden
        element. Dispatching a JS `change` event directly would NOT
        fire `_on_selection` inside `file_picker_server` — the test
        would pass for the wrong reason (the wrapper never ran).

        Instead, use `Shiny.setInputValue` which routes through Shiny's
        input pipeline and reliably fires `@reactive.event(input.file_select)`.
        We then assert the wrapper's no-project branch is silent (no
        log entry visible client-side, no notification toast, bas_path
        unchanged).

        Caveat: 'no log' is not directly observable from Playwright
        (logs go to the subprocess stderr → see Test 8b coverage note).
        Coverage here is limited to the user-visible side effects:
        text input + notification absence. The log-vs-notify branching
        is verified by code inspection during review.
        """
        pw_page.locator('a[data-target="Partitioning"]').click(force=True)
        pw_page.wait_for_timeout(800)

        bas_input = pw_page.locator('#partitioning-bas_path')
        bas_input.wait_for(state="attached", timeout=5000)

        # Route through Shiny's input pipeline so the file_picker's
        # @reactive.event(input.file_select) effect actually fires.
        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'partitioning-fp_bas-file_select', '',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(500)

        # bas_path stays empty; no notification toast appeared
        assert bas_input.input_value() == ""
        notifications = pw_page.locator('.shiny-notification').count()
        assert notifications == 0, (
            f"expected 0 notifications, found {notifications}"
        )

    def test_picker_callback_warns_on_traversal(
        self, pw_page, live_server,
    ):
        """Spec test 11(b): _fill_bas with active project + traversal
        rel_path triggers logger.warning + ui.notification_show.

        Requires the same `__test_set_active_project` JS hook used by
        test 9. Without the hook, active_project stays None and we
        can't reach the wrapper's traversal branch (which fires only
        when proj is not None and rel_path is non-empty AND
        resolve_picker_path returns None).
        """
        pw_page.locator('a[data-target="Partitioning"]').click(force=True)
        pw_page.wait_for_timeout(800)

        # Seed active_project via the test app's debug hook
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
            pytest.skip(
                "test_app.py does not expose __test_set_active_project; "
                "wrapper traversal-failure branch cannot be exercised."
            )
        pw_page.wait_for_timeout(500)

        # Send a traversal rel_path through Shiny's input pipeline.
        # The component's _on_selection effect picks it up, which calls
        # _fill_bas('/etc/passwd'). resolve_picker_path's containment
        # guard returns None, _fill_bas's failure branch fires:
        # logger.warning + ui.notification_show.
        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'partitioning-fp_bas-file_select', '/etc/passwd',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(800)

        # The user-visible side-effect — toast notification — confirms
        # the wrapper's traversal branch fired.
        notifications = pw_page.locator('.shiny-notification')
        count = notifications.count()
        assert count >= 1, (
            f"expected >= 1 .shiny-notification toast, found {count}"
        )
        # Verify it's a warning toast (type=warning sets a CSS class)
        warning_toasts = pw_page.locator(
            '.shiny-notification.shiny-notification-warning'
        ).count()
        assert warning_toasts >= 1, (
            f"expected at least 1 warning-class notification, "
            f"found {warning_toasts}"
        )

        # bas_path was NOT updated — the wrapper short-circuited
        bas_input = pw_page.locator('#partitioning-bas_path')
        assert bas_input.input_value() == "", (
            f"expected bas_path empty (wrapper rejected the selection), "
            f"got {bas_input.input_value()!r}"
        )
```

- [ ] **Step 3: Run the Playwright tests (manually, not in default suite)**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_partitioning_picker.py -v --override-ini="addopts="`

Expected: 5 passed. With Step 1's hook wired, tests 9 and 11(b) should NOT skip — if they do, inspect `_test_app.py` to confirm the hook is in place and the JS-side `window.__test_set_active_project` is exposed. If Playwright browsers are not installed, tests skip with the project's existing skip message — that's acceptable for CI environments without Playwright provisioned.

If a test fails because it can't find the picker selector (e.g. `#partitioning-fp_bas-file_select`), open the running app in a browser and inspect the actual id format Shiny generated. Adjust the locators accordingly — the namespace prefix is `partitioning-` (matching the module ID at `_test_app.py:158`), and the picker's internal select id is `file_select`.

**Note on coverage gap:** spec test 8 (full project switch populates the dropdown with real DB-seeded files) requires setting up basin/grid files on disk + DB rows + the FileService scan — out of scope for the pilot. Tracked in Section M as the natural place to add a more comprehensive fixture once the wrapper is extracted. Test 11(a) (success path) is covered by the manual smoke test in Task 8 step 4c.

- [ ] **Step 4: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/tests/test_playwright_partitioning_picker.py
git commit -m "test(ui): Playwright tests for partitioning picker session behaviour

Five E2E tests covering session-driven behaviour that can't be unit
tested (shiny 1.5.1 has no public @module.server invocation API):

- test_picker_shows_no_files_available_when_no_project: pins
  project_id=None placeholder behavior.
- test_typing_into_bas_path_is_not_clobbered_by_reactive_effect:
  reactive.isolate() regression — typing must not retrigger
  _on_project_changed (would clear or overwrite the field).
- test_empty_guard_preserves_user_input_across_navigation:
  'if not input.bas_path()' regression — project re-emit must not
  clobber user-entered values. Skips if __test_set_active_project
  hook isn't wired in _test_app.py.
- test_picker_callback_silent_on_no_project: wrapper no-project
  branch — silent return, no log/notify/update_text.
- test_picker_callback_warns_on_traversal: wrapper traversal-failure
  branch fires a warning notification toast. Skips if hook missing.

Excluded from default pytest run (test_playwright_* glob); run with
--override-ini=\"addopts=\". Test 8 (full-project flow showing the
dropdown populating with project basin files) deferred to Section M
since it needs full project seeding."
```

---

## Task 7: Update followups doc with Section L and Section M

**Files:**
- Modify: `docs/followups/2026-04-29-ui-deep-review-deferred.md`

- [ ] **Step 1: Read the current followups doc to know where to append**

Run: `cat /home/razinka/shyfem/docs/followups/2026-04-29-ui-deep-review-deferred.md | tail -20`

Expected: shows the last few sections, identifies the right append point.

- [ ] **Step 2: Append Section L and Section M**

Append to `docs/followups/2026-04-29-ui-deep-review-deferred.md`:

```markdown

## Section L — Output-directory picker

**Source:** Section B pilot (partitioning file-picker integration, 2026-05-01).

The pilot wires file pickers for INPUT files (`.bas`, `.grd`) but not for
the OUTPUT directory (`output_dir` text input on partitioning, run, and
similar pages). Output picking is a different abstraction — directory
picker, not file picker — and was deferred from the pilot.

When designing this:
- The picker must list directories (not files) under `work_dir`, and
  optionally allow creating a new subdirectory.
- It should integrate via the same coexistence pattern (picker + text
  input) the file picker uses, so the migration cost matches.
- Consider whether to share infrastructure with `components/file_picker.py`
  (e.g. a `directory_picker_server` sibling) or build a separate component.

## Section M — File-picker rollout to remaining 6 pages

**Source:** Section B pilot (partitioning file-picker integration, 2026-05-01).

The pilot scopes only `pages/partitioning.py`. The remaining pages with
free-text path inputs are:

- `pages/grid_prep.py` (mesh import paths)
- `pages/postprocess.py` (input `.shy`/`.nc` files)
- `pages/physics.py` (forcing files)
- `pages/simulation.py` (STR file)
- `pages/run.py` (STR file)
- `pages/ibm.py` (Lagrangian config — `.lgr` may not map to a FileService
  category; check the taxonomy first)

Apply the same pattern as the pilot:
1. Add `file_picker_ui` above each text input.
2. Add `file_picker_server` with the appropriate `file_types` filter.
3. Add an `_fill_X` wrapper that calls `resolve_picker_path`, logs +
   notifies on resolution failure.

**Hard deadline (from spec lessons):** by the SECOND follow-up page,
extract the per-page `_fill_X` wrapper bodies into a shared helper
`fill_picker_input(text_input_id, active_project, rel_path)` in
`components/file_picker.py`. This prevents user-visible string drift
across pages.

Before each page is wired:
- Confirm the page's file inputs map cleanly to `FileService` file_types.
  `.lgr` for ibm.py may need a new taxonomy entry (`lagrangian` or
  similar).
- Audit `_on_project_changed` (or equivalent) for the same patterns
  fixed in the pilot: missing `reactive.isolate()` around input reads,
  missing empty-guards on auto-fill.
```

- [ ] **Step 3: Commit**

```bash
cd /home/razinka/shyfem
git add docs/followups/2026-04-29-ui-deep-review-deferred.md
git commit -m "docs(ui): track Section L (output-dir picker) and Section M (rollout)

Section L: output-directory picker is a separate abstraction (dir
picker, not file picker), deferred from the partitioning pilot.

Section M: 6-page file-picker rollout. Lists the affected pages,
flags the .lgr taxonomy gap for ibm.py, and fixes a hard deadline
to extract the _fill_X wrapper into a shared helper by the SECOND
follow-up page (not third) to prevent user-visible string drift."
```

---

## Task 8: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full new test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_file_picker_logic.py tests/test_partitioning_file_picker.py tests/test_project_context.py -v`

Expected: 6 + 2 + 5 = 13 tests pass.
- `test_file_picker_logic.py`: 6 pure-helper tests (1, 2, 3, 4, 5, 5b).
- `test_partitioning_file_picker.py`: 2 unit tests (UI render + import-style guard) — the session-driven tests live in the Playwright file.
- `test_project_context.py`: 5 tests (4 pre-existing + 1 new shape-pinning).

- [ ] **Step 2: Run the partitioning regression tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_partitioning.py tests/test_partitioning_logic.py tests/test_pages_access_control.py -q`

Expected: all existing tests pass — no regression in shyparts wiring or access-control guards.

- [ ] **Step 3: Run F401 check on all modified files**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check --select F401 shyfem_ui/pages/partitioning.py shyfem_ui/components/file_picker.py shyfem_ui/services/project_context.py`

Expected: clean.

- [ ] **Step 4a: Guard against Playwright-test misnaming**

Run: `cd /home/razinka/shyfem/shyfem-ui && ! grep -lE "pw_page|pw_auth_page|@pytest.mark.e2e" tests/*.py | grep -v test_playwright_`

Expected: empty output (the `!` inverts: command succeeds if grep finds nothing). If a test file uses Playwright fixtures but isn't named `test_playwright_*.py`, the default `pytest -q` suite will collect it and fail with cryptic `pw_page` fixture errors. This guard catches that before pytest does.

- [ ] **Step 4b: Run the broader test suite to confirm no global regression**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest -q`

Expected: same pass count as before this branch + 9 new unit tests (6 helper + 2 picker page tests + 1 service shape pinning). The 5 Playwright tests are excluded from this default `pytest -q` run by `addopts = "--ignore-glob=tests/test_playwright_*.py"` and run separately in Step 5.

- [ ] **Step 4c: Optional manual smoke test**

Run the app in local mode and navigate to Partitioning:

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app
```

Open `http://127.0.0.1:8000/`, create a project with a basin file, navigate to Partitioning. Confirm:
- Two new dropdown widgets appear above the existing text inputs.
- The basin dropdown shows the project's `.bas` file.
- Picking a file fills the text input below it with the absolute path.
- The grid dropdown shows the project's `.grd` file (if any).

- [ ] **Step 5: Optional Playwright run**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_partitioning_picker.py -v --override-ini="addopts="`

Expected: 5 passed (3 of which run unconditionally; 2 may skip with `pytest.skip` if `__test_set_active_project` is not wired into `_test_app.py`). All 5 skip if Playwright browsers are not installed.

- [ ] **Step 6: Optional mypy check**

If mypy is available: `cd /home/razinka/shyfem/shyfem-ui && mypy --strict shyfem_ui/components/file_picker.py shyfem_ui/services/project_context.py shyfem_ui/pages/partitioning.py`

Expected: clean. Skip if mypy not installed (no static-checker config in pyproject.toml).

---

## Summary

When complete:
- **9 new unit tests** added across three files (the verification's `pytest -v` run will show 13 tests passing total — 9 new + 4 pre-existing in `test_project_context.py`):
  - 6 pure-helper tests in `test_file_picker_logic.py` (1, 2, 3, 4, 5, 5b);
  - 2 page-level tests in `test_partitioning_file_picker.py` (UI render + identity/wiring/8b-warning guard);
  - 1 service-layer shape-pinning test in `test_project_context.py` (test 12).
- **5 Playwright tests** in `test_playwright_partitioning_picker.py` covering session-driven behaviour (placeholder, isolate regression, empty-guard regression, no-project silent return, traversal-failure warning toast).
- `resolve_picker_path` pure helper added to `components/file_picker.py` with traversal-containment guard and structured warnings.
- `ProjectContext` TypedDict (with nested `GridEntry`, `SimulationEntry`, `FileEntry`) added to `services/project_context.py`.
- `pages/partitioning.py` wires two file pickers, maintains `project_id_val`, and uses `reactive.isolate()` + empty-guards to prevent user-typed values from being clobbered. Logs a one-shot WARNING at server entry if `active_project=None` (page wiring bug).
- Follow-up Sections L (output-dir picker) and M (6-page rollout) tracked in the deferred-followups doc, with a hard deadline to extract the per-page wrapper boilerplate by the second follow-up page.
