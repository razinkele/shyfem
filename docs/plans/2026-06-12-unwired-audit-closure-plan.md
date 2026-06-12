# Unwired-UI Audit Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four remaining items of the 2026-06-08 unwired-UI audit (`docs/reviews/2026-06-08-shyfem-ui-unwired-audit.md`): remove `run_shyplot`, route workflow-template reads through `WorkflowEngine.list_templates`, wire `filter_by_time` into the IBM particle view, and surface the write-only Grid/Simulation metadata columns in a project Details modal.

**Architecture:** All code changes live in the Shiny-for-Python UI (`shyfem-ui/`); Task 5 additionally appends a closure note to the parent plan under `docs/plans/`. Each item follows the project's established audit-fix pattern: a TDD "source-lock" test in `tests/test_dead_controls_wired.py` (asserts the wiring exists / dead symbol is gone), plus behavior tests where there is real logic. One branch, one commit per task.

**Owner decisions (2026-06-12, locked):** run_shyplot → **remove**; lgr filter_by_time → **surface** (time-range inputs on IBM page); list_templates → **route pages through it**; Grid/Simulation columns → **surface** (project Details modal).

**Tech Stack:** Shiny for Python, SQLAlchemy, pytest. Python env: `/opt/micromamba/envs/shiny/bin/python`.

**Conventions (per CLAUDE.md + the parent plan `docs/plans/2026-06-08-shyfem-ui-unwired-fixes-plan.md`):**
- Branch: `fix/ui-unwired-closure` off `main`.
- Every test run: `cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest …` (Playwright tests are excluded by default via `addopts`).
- Ruff must stay clean: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check .`
- UI merges deploy to laguna (Shiny Server symlinks the git tree) → **hold the final merge for the owner's go-ahead**.

---

### Task 0: Create the branch and record the suite baseline

- [ ] **Step 1: Branch off up-to-date main**

```bash
cd /home/razinka/shyfem
git checkout main && git pull
git checkout -b fix/ui-unwired-closure
```

- [ ] **Step 2: Record the green baseline (used by Task 5's final check)**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest -q | tail -1
```
Expected: `N passed` with 0 failed. Note N — Task 5 asserts "0 failed and count > N" rather than a hard-coded number.

---

### Task 1: Remove the `run_shyplot` wrapper method (P5 — decision: remove)

`ShyfemWrapper.run_shyplot` (`shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:402-421`) has no caller. The `shyplot` *tool* stays fully supported — the run page offers it (`pages/run.py:80`) and jobs dispatch it generically through `wrapper.run_command` (`services/job_local.py:330`). Only the dedicated convenience method is dead.

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:402-421` (delete method)
- Modify: `shyfem-ui/tests/test_wrapper.py:481-484` (drop the parametrize entry)
- Test: `shyfem-ui/tests/test_dead_controls_wired.py` (add source-lock)

- [ ] **Step 1: Write the failing source-lock test**

Append to `shyfem-ui/tests/test_dead_controls_wired.py`:

```python
def test_run_shyplot_wrapper_removed():
    """P5 decision (2026-06-12): shyplot stays available as a generic tool
    (run page + job dispatch via run_command); the dedicated wrapper method
    had no caller and was removed."""
    from shyfem_ui.services import shyfem_wrapper

    src = inspect.getsource(shyfem_wrapper)
    assert "def run_shyplot" not in src
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_dead_controls_wired.py::test_run_shyplot_wrapper_removed -v
```
Expected: FAIL (`assert "def run_shyplot" not in src`).

- [ ] **Step 3: Delete the method**

In `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py`, delete this entire block (lines 402-421):

```python
    async def run_shyplot(
        self,
        input_file: Path | str,
        working_dir: Path | str,
        options: list[str] | None = None,
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyplot to generate plots.

        Args:
            input_file: Path to input file (.shy, .bas, etc.)
            working_dir: Working directory
            options: Additional options like ["-colplot"]
        """
        args = list(options) if options else []   # copy: never mutate caller's list
        args.append(str(input_file))
        return await self.run_command(
            "shyplot", args, working_dir, progress_callback, output_callback
        )
```

Do NOT touch the `"shyplot"` entries elsewhere in the file (tool list at line 44, output-extension map at line 59) — those serve the generic `run_command` path.

- [ ] **Step 4: Remove the orphaned test entry**

In `shyfem-ui/tests/test_wrapper.py`, the parametrize at line 481-484:

```python
    @pytest.mark.parametrize("method,posarg", [
        ("run_shypre", "g.grd"), ("run_shybas", "b.bas"),
        ("run_shyparts", "b.bas"), ("run_shyplot", "i.shy"),
    ])
```

becomes:

```python
    @pytest.mark.parametrize("method,posarg", [
        ("run_shypre", "g.grd"), ("run_shybas", "b.bas"),
        ("run_shyparts", "b.bas"),
    ])
```

- [ ] **Step 5: Run the affected tests**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_dead_controls_wired.py tests/test_wrapper.py -v
```
Expected: all PASS.

- [ ] **Step 6: Grep for stragglers, then commit**

```bash
cd /home/razinka/shyfem && grep -rn "run_shyplot" shyfem-ui/ --include="*.py" | grep -v test_dead_controls_wired
```
Expected: no output (the source-lock test added in Step 1 legitimately names the symbol, hence the exclusion). Then:

```bash
git add shyfem-ui/shyfem_ui/services/shyfem_wrapper.py shyfem-ui/tests/test_wrapper.py shyfem-ui/tests/test_dead_controls_wired.py
git commit -m "refactor(ui): remove uncalled run_shyplot wrapper method (audit P5)

shyplot remains a supported tool via the generic run_command dispatch
(run page tool select + job_local); only the dedicated convenience
method was dead. Decision 2026-06-12: remove."
```

---

### Task 2: Route template reads through `WorkflowEngine.list_templates` (P5 — decision: route)

`pages/run.py` reads the module constant `WORKFLOW_TEMPLATES` directly in two places (line 162: template select choices; line 1213: `wf_template_info` panel) while the engine accessor sits unused. Make `list_templates` the single UI-facing source: a `@staticmethod` (line 162 runs at UI-build time, before any engine instance exists) whose steps carry `name` + `tool_name` (line 1213 needs both).

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/workflow.py:289-298`
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:48,162,1213-1224`
- Test: `shyfem-ui/tests/test_workflow.py:155-161`, `shyfem-ui/tests/test_dead_controls_wired.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_list_templates` in `shyfem-ui/tests/test_workflow.py` (lines 155-161):

```python
    def test_list_templates(self, engine):
        """Test listing available templates."""
        templates = engine.list_templates()
        assert isinstance(templates, dict)
        assert "full_simulation" in templates
        tpl = templates["full_simulation"]
        assert "name" in tpl
        assert "description" in tpl
        # Steps carry name + tool_name so UI pages render from the accessor
        # instead of reaching into WORKFLOW_TEMPLATES (2026-06-08 audit P5).
        assert all({"name", "tool_name"} <= set(s) for s in tpl["steps"])

    def test_list_templates_is_callable_without_an_engine(self):
        """The template select is built at UI-definition time, before any
        engine exists — the accessor must work as a static method."""
        from shyfem_ui.services.workflow import WorkflowEngine

        templates = WorkflowEngine.list_templates()
        assert "full_simulation" in templates
```

Append to `shyfem-ui/tests/test_dead_controls_wired.py`:

```python
def test_run_page_uses_template_accessor():
    """P5: pages must go through WorkflowEngine.list_templates, not read
    the WORKFLOW_TEMPLATES module constant directly."""
    from shyfem_ui.pages import run

    src = inspect.getsource(run)
    assert "WORKFLOW_TEMPLATES" not in src
    assert "list_templates()" in src
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_workflow.py::TestWorkflowEngine::test_list_templates tests/test_workflow.py::TestWorkflowEngine::test_list_templates_is_callable_without_an_engine tests/test_dead_controls_wired.py::test_run_page_uses_template_accessor -v
```
Expected: 3 FAIL (steps are plain strings; staticmethod call raises TypeError; run.py contains WORKFLOW_TEMPLATES).

- [ ] **Step 3: Enrich the accessor**

In `shyfem-ui/shyfem_ui/services/workflow.py`, replace lines 289-298:

```python
    def list_templates(self) -> dict[str, dict]:
        """List available workflow templates."""
        return {
            key: {
                "name": tpl["name"],
                "description": tpl["description"],
                "steps": [s.name for s in tpl["steps"]],
            }
            for key, tpl in WORKFLOW_TEMPLATES.items()
        }
```

with:

```python
    @staticmethod
    def list_templates() -> dict[str, dict]:
        """List available workflow templates as a UI-renderable summary.

        Static because the template select is built at UI-definition time,
        before any engine (and its job_queue) exists.
        """
        return {
            key: {
                "name": tpl["name"],
                "description": tpl["description"],
                "steps": [{"name": s.name, "tool_name": s.tool_name} for s in tpl["steps"]],
            }
            for key, tpl in WORKFLOW_TEMPLATES.items()
        }
```

- [ ] **Step 4: Switch run.py to the accessor**

In `shyfem-ui/shyfem_ui/pages/run.py`:

1. Line 48 — drop the constant from the import:

```python
from shyfem_ui.services.workflow import WorkflowEngine, WorkflowStatus
```

2. Line 162 — the template select choices:

```python
                                        choices={
                                            k: v["name"]
                                            for k, v in WorkflowEngine.list_templates().items()
                                        },
```

3. In `wf_template_info` (line ~1213), replace:

```python
        tpl = WORKFLOW_TEMPLATES.get(key)
        if not tpl:
            return None

        steps_list = [
            ui.tags.li(
                ui.code(step.tool_name),
                ui.span(f" - {step.name}", class_="text-muted"),
            )
            for step in tpl["steps"]
        ]
```

with:

```python
        tpl = workflow_engine.list_templates().get(key)
        if not tpl:
            return None

        steps_list = [
            ui.tags.li(
                ui.code(step["tool_name"]),
                ui.span(f" - {step['name']}", class_="text-muted"),
            )
            for step in tpl["steps"]
        ]
```

4. Remove the now-dead re-export from `shyfem-ui/shyfem_ui/services/__init__.py` — after this task nothing imports `WORKFLOW_TEMPLATES` via the package (engine internals and `tests/test_workflow.py` import it from `shyfem_ui.services.workflow` directly), and an audit-closure PR must not ship a freshly unwired export. Three edits in that file:
   - Delete the docstring line: `    WORKFLOW_TEMPLATES: Built-in workflow templates (full simulation, post-process, etc.).`
   - Import line becomes: `from shyfem_ui.services.workflow import WorkflowEngine`
   - Delete `    "WORKFLOW_TEMPLATES",` from `__all__`.

(`workflow_engine` is instantiated at line 1201, above the `wf_template_info` render — no ordering issue. The `WORKFLOW_TEMPLATES` module constant itself stays in `workflow.py` as the engine's internal source of truth.)

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_workflow.py tests/test_dead_controls_wired.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/workflow.py shyfem-ui/shyfem_ui/services/__init__.py shyfem-ui/shyfem_ui/pages/run.py shyfem-ui/tests/test_workflow.py shyfem-ui/tests/test_dead_controls_wired.py
git commit -m "refactor(ui): route template reads through WorkflowEngine.list_templates (audit P5)

The accessor becomes the single UI-facing source (static, steps carry
name + tool_name); run.py no longer reaches into WORKFLOW_TEMPLATES and
the consumerless services/__init__ re-export is dropped."
```

---

### Task 3: Wire `filter_by_time` into the IBM particle view (P5 — decision: surface)

`lgr_service.filter_by_time` (`shyfem-ui/shyfem_ui/services/lgr_service.py:127`) is implemented and unit-tested (`tests/test_lgr_service.py:95-136`) but nothing calls it. Add From/To time inputs to the IBM sidebar and cut the displayed tracks through a shared `@reactive.calc`, so the map layers AND the stats panel reflect the same filtered view. The load-status badge (`ibm_status`) deliberately keeps showing the raw loaded counts.

Time strings are `"YYYY-MM-DD HH:MM:SS"`, compared lexicographically (that is `filter_by_time`'s documented contract); empty inputs mean "no bound". Malformed input cannot crash anything — it just filters to nothing — so no validation layer (YAGNI).

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/ibm.py:45` (import), `:199` (sidebar UI, after the `show_ends` checkbox), `:256` (server calc), `:357-359` (`_update_ibm_map`), `:509-510` (`ibm_stats_panel`)
- Test: `shyfem-ui/tests/test_dead_controls_wired.py`

- [ ] **Step 1: Write the failing tests**

Append to `shyfem-ui/tests/test_dead_controls_wired.py`:

```python
def test_ibm_time_filter_is_wired():
    """P5: lgr_service.filter_by_time had no UI caller. The IBM page must
    read the time-range inputs and cut tracks through filter_by_time
    (behavior of the filter itself is covered in test_lgr_service.py)."""
    from shyfem_ui.pages import ibm

    src = inspect.getsource(ibm)
    assert "filter_by_time(" in src, "filter_by_time is not called"
    assert "input.time_min()" in src, "time_min input is not read"
    assert "input.time_max()" in src, "time_max input is not read"
```

And close a real coverage gap in `shyfem-ui/tests/test_lgr_service.py`: the existing
`filter_by_time` block (lines 95-136) never exercises a non-empty `tmax` that trims.
Add after `test_filter_empty_string_treated_as_no_bound` (line ~131-135), using the
block's existing `_make_track()` helper (3 steps at 00/01/02:00):

```python
def test_filter_tmax_trims_late_steps():
    """tmax removes steps after the cutoff (inclusive bound)."""
    track = _make_track()
    result = filter_by_time([track], tmin=None, tmax="2020-01-01 01:00:00")
    assert len(result) == 1
    assert len(result[0].path) == 2
    assert result[0].times[-1] == "2020-01-01 01:00:00"
```

- [ ] **Step 2: Run them to verify the source-lock fails (the tmax test should already pass)**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_dead_controls_wired.py::test_ibm_time_filter_is_wired tests/test_lgr_service.py -v
```
Expected: the source-lock FAILs; `test_filter_tmax_trims_late_steps` PASSes (it documents existing behavior — that is fine, it locks the upper-bound branch the UI is about to depend on).

- [ ] **Step 3: Add the sidebar inputs**

In `shyfem-ui/shyfem_ui/pages/ibm.py`, inside `ibm_ui()`'s sidebar, directly after the last Display checkbox (`ui.input_checkbox("show_ends", "End Points", value=True),` at line ~199), insert:

```python
                ui.hr(),
                ui.h6("Time Filter"),
                ui.input_text(
                    "time_min",
                    "From (YYYY-MM-DD HH:MM:SS)",
                    placeholder="no lower bound",
                    update_on="blur",
                ),
                ui.input_text(
                    "time_max",
                    "To (YYYY-MM-DD HH:MM:SS)",
                    placeholder="no upper bound",
                    update_on="blur",
                ),
                ui.output_ui("time_range_hint"),
```

`update_on="blur"` is load-bearing, not cosmetic: `_update_ibm_map` is an ungated
`@reactive.effect` that rebuilds every deck.gl layer and resets the camera on each
dependency flush. With the default per-keystroke updates, typing a 19-char timestamp
would rebuild the map ~19 times, and the partial strings (e.g. `"2024-1"`) compare
lexicographically above all real timestamps — filtering everything out and flying the
camera to the default Adriatic view mid-keystroke.

- [ ] **Step 4: Add the shared filtered-tracks calc and consume it**

1. Line 45 — extend the import:

```python
from shyfem_ui.services.lgr_service import LgrService, ParticleTrack, filter_by_time
```

2. In `ibm_server`, directly after the state declarations (`load_error: reactive.Value[...]` at line ~257), add:

```python
    @reactive.calc
    def filtered_tracks() -> list[ParticleTrack]:
        # Tracks currently displayed: raw loads cut by the time-range inputs.
        # filter_by_time treats ""/None as "no bound" and compares the
        # "YYYY-MM-DD HH:MM:SS" strings lexicographically.
        return filter_by_time(
            tracks_data.get(),
            input.time_min().strip() or None,
            input.time_max().strip() or None,
        )

    @render.ui
    def time_range_hint():
        # Without this the filter is unaimable: the user would have to guess
        # exact timestamps. Shows the span of the *loaded* (unfiltered) data.
        tracks = tracks_data.get()
        starts = [t.times[0] for t in tracks if t.times]
        ends = [t.times[-1] for t in tracks if t.times]
        if not starts:
            return None
        return ui.p(f"Loaded: {min(starts)} – {max(ends)}", class_="text-muted small mb-0")
```

3. In `_update_ibm_map` (line ~357), replace:

```python
        tracks = tracks_data.get()
        filtered = tracks  # trips_layer handles time via animation controls
```

with:

```python
        filtered = filtered_tracks()
```

4. In `ibm_stats_panel` (line ~510), replace `tracks = tracks_data.get()` with:

```python
        tracks = filtered_tracks()
```

and make the active filter visible in the panel header — a narrow window can leave
single-point tracks that the map still draws but `compute_track_stats` skips
(`len < 2` guard at line ~105), so the counts can legitimately disagree with the
load badge. The header at line ~541 currently reads:

```python
            ui.h6(
                ui.tags.i(class_="bi bi-bar-chart me-1"),
                "Particle Statistics",
                class_="mt-3 mb-2",
            ),
```

Change it to:

```python
            ui.h6(
                ui.tags.i(class_="bi bi-bar-chart me-1"),
                (
                    "Particle Statistics (time-filtered)"
                    if (input.time_min().strip() or input.time_max().strip())
                    else "Particle Statistics"
                ),
                class_="mt-3 mb-2",
            ),
```

(The ternary is wrapped in parentheses in black-normalized form — CI runs `black --check`, so write it this way from the start.)

(Leave `ibm_status` at line ~498 reading `tracks_data.get()` — it reports what was *loaded*, not what is shown.)

- [ ] **Step 5: Run the IBM tests + source locks**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_dead_controls_wired.py tests/test_ibm.py tests/test_ibm_trips.py tests/test_lgr_service.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/pages/ibm.py shyfem-ui/tests/test_dead_controls_wired.py shyfem-ui/tests/test_lgr_service.py
git commit -m "feat(ui): time-range filter on IBM particle view via filter_by_time (audit P5)

From/To inputs (update_on=blur — the map effect rebuilds all layers per
flush) feed a shared reactive calc; map layers and the stats panel show
the same filtered view, a hint shows the loaded time span, the
load-status badge keeps raw counts."
```

---

### Task 4: Surface Grid/Simulation metadata in a project Details modal (P6 — decision: surface)

`Grid.num_layers/min_depth/max_depth` and `Simulation.start_time/end_time/time_step` (`shyfem-ui/shyfem_ui/models/project.py:107-109,139-141`) are populated by the project-import path (`pages/home.py:1176-1180` for Grid, `:1193-1195` for Simulation) but never displayed. The tutorial-bootstrap and clone paths create rows with these columns left `None` — the modal's `_fmt` renders those as "—", which is correct (and incidentally makes the pre-existing clone metadata loss visible). Surface them: extend `load_project_context` to include the fields, and add a per-project "Details" action on the dashboard that opens a read-only modal. The modal reuses `load_project_context`'s existing viewer-level access gate (fail-closed in server mode).

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/project_context.py:105-106`
- Modify: `shyfem-ui/shyfem_ui/pages/home.py` (`:322` comment, `:463` row actions, new handler factory near `_make_open_proj_handler` at `:792`)
- Test: `shyfem-ui/tests/test_project_context.py`, `shyfem-ui/tests/test_dead_controls_wired.py`

- [ ] **Step 1: Write the failing context test**

Add to `class TestLoadProjectContext` in `shyfem-ui/tests/test_project_context.py`:

```python
    def test_context_includes_grid_and_sim_metadata(self, tmp_path):
        """2026-06-08 audit P6: the import-populated metadata columns must be
        readable from the context so the dashboard Details modal can show them."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Grid, Project, Simulation
        from shyfem_ui.services.project_context import load_project_context

        with db_session() as db:
            p = Project(name="meta_proj", work_dir=str(tmp_path / "proj"))
            db.add(p)
            db.flush()
            g = Grid(
                project_id=p.id,
                name="grid1",
                grd_file="GRID/g.grd",
                bas_file="GRID/g.bas",
                num_layers=12,
                min_depth=0.5,
                max_depth=44.0,
            )
            db.add(g)
            db.flush()
            s = Simulation(
                project_id=p.id,
                grid_id=g.id,
                name="sim1",
                str_file="sim1.str",
                start_time="2024-01-01 00:00:00",
                end_time="2024-01-31 00:00:00",
                time_step=300.0,
            )
            db.add(s)
            db.flush()
            pid = p.id

        ctx = load_project_context(pid, user=None, is_server_mode=False)
        assert ctx is not None
        grid = ctx["grids"][0]
        assert grid["num_layers"] == 12
        assert grid["min_depth"] == 0.5
        assert grid["max_depth"] == 44.0
        sim = ctx["simulations"][0]
        assert sim["start_time"] == "2024-01-01 00:00:00"
        assert sim["end_time"] == "2024-01-31 00:00:00"
        assert sim["time_step"] == 300.0
```

And append the source-lock to `shyfem-ui/tests/test_dead_controls_wired.py`:

```python
def test_project_details_modal_is_wired():
    """P6: Grid/Simulation metadata columns were write-only. The dashboard
    must surface them via a per-project Details modal, and the modal's read
    must go through the gated context loader (fail-closed in server mode).

    NOTE: locks are on the bracket-access render expressions, NOT bare
    "num_layers"/"time_step" — those substrings already exist in home.py's
    import handler and would make the lock vacuous."""
    from shyfem_ui.pages import home

    src = inspect.getsource(home)
    assert "_make_details_handler(" in src, "no details handler factory"
    assert 'g["num_layers"]' in src, "grid metadata not rendered in the modal"
    assert 's["time_step"]' in src, "simulation metadata not rendered in the modal"
    assert "load_project_context(pid, user=" in src, (
        "details modal must read through the gated context loader"
    )
```

Also update the existing shape-pin test in the same file — `TestProjectContextShape::test_load_returns_dict_with_required_keys` (line ~173) deliberately pins the TypedDict annotation keys with exact equality to force co-updates like this one. At lines ~284-292, replace:

```python
        assert set(GridEntry.__annotations__.keys()) == {
            "name",
            "grd_file",
            "bas_file",
        }
        assert set(SimulationEntry.__annotations__.keys()) == {
            "name",
            "str_file",
        }
```

with:

```python
        assert set(GridEntry.__annotations__.keys()) == {
            "name",
            "grd_file",
            "bas_file",
            "num_layers",
            "min_depth",
            "max_depth",
        }
        assert set(SimulationEntry.__annotations__.keys()) == {
            "name",
            "str_file",
            "start_time",
            "end_time",
            "time_step",
        }
```

(The `>=` runtime-shape checks earlier in that test are superset-tolerant and need no change.)

- [ ] **Step 2: Run them to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_context.py tests/test_dead_controls_wired.py::test_project_details_modal_is_wired -v
```
Expected: 3 FAIL (KeyError `num_layers` in the new test; the updated shape-pin fails because the TypedDicts lack the new keys; the source-lock fails on its first assert — `_make_details_handler(` does not exist in home.py yet).

- [ ] **Step 3: Extend the context dicts AND their TypedDict declarations**

In `shyfem-ui/shyfem_ui/services/project_context.py`, first keep the declared types
honest — extend the TypedDicts at lines 10-18:

```python
class GridEntry(TypedDict):
    name: str
    grd_file: str | None
    bas_file: str | None
    num_layers: int | None
    min_depth: float | None
    max_depth: float | None


class SimulationEntry(TypedDict):
    name: str
    str_file: str | None
    start_time: str | None
    end_time: str | None
    time_step: float | None
```

Then replace lines 105-106:

```python
        "grids": [{"name": g.name, "grd_file": g.grd_file, "bas_file": g.bas_file} for g in grids],
        "simulations": [{"name": s.name, "str_file": s.str_file} for s in sims],
```

with:

```python
        "grids": [
            {
                "name": g.name,
                "grd_file": g.grd_file,
                "bas_file": g.bas_file,
                "num_layers": g.num_layers,
                "min_depth": g.min_depth,
                "max_depth": g.max_depth,
            }
            for g in grids
        ],
        "simulations": [
            {
                "name": s.name,
                "str_file": s.str_file,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "time_step": s.time_step,
            }
            for s in sims
        ],
```

(Existing consumers — `grid_prep.py:151`, `partitioning.py:156` — read keys by name; extra keys are harmless.)

- [ ] **Step 4: Add the Details link to the project row**

In `shyfem-ui/shyfem_ui/pages/home.py`, in `projects_list` (line ~463), add a Details link as the first action in the actions `td`, before `share_btn`:

The actions cell currently reads (line ~463):

```python
                    ui.tags.td(
                        share_btn,
                        ui.input_action_link(
                            f"export_{p['id']}",
                            "Export",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"clone_{p['id']}",
                            "Clone",
                            class_="btn btn-sm btn-outline-secondary",
                        ),
                    ),
```

Change it to:

```python
                    ui.tags.td(
                        ui.input_action_link(
                            f"details_{p['id']}",
                            "Details",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        share_btn,
                        ui.input_action_link(
                            f"export_{p['id']}",
                            "Export",
                            class_="btn btn-sm btn-outline-secondary me-1",
                        ),
                        ui.input_action_link(
                            f"clone_{p['id']}",
                            "Clone",
                            class_="btn btn-sm btn-outline-secondary",
                        ),
                    ),
```

- [ ] **Step 5: Add the handler factory (dedup-guarded, gated read)**

Still in `home.py`, directly after `_make_open_proj_handler` (ends ~line 801), add — following the exact registration pattern used by the neighbours:

```python
    @reactive.effect
    def _register_details_handlers():
        project_data = projects.get()
        for p in project_data:
            _make_details_handler(p["id"])

    def _make_details_handler(pid: int):
        key = f"details_{pid}"
        if key in _registered_handlers:
            return
        _registered_handlers.add(key)

        @reactive.effect
        @reactive.event(input[key])
        def _show_details():
            from shyfem_ui.services.project_context import load_project_context

            # The viewer-level read gate is THIS call (fail-closed in server
            # mode). Handler registration filtering via projects.get() is NOT
            # a security boundary: _registered_handlers never shrinks, so a
            # handler registered while a project was shared outlives the
            # share's revocation for the rest of the session.
            ctx = load_project_context(pid, user=(_user()))
            if ctx is None:
                ui.notification_show("Project not found or access denied", type="error", duration=6)
                return

            def _fmt(value, suffix=""):
                return f"{value}{suffix}" if value is not None else "—"

            grid_rows = [
                ui.tags.tr(
                    ui.tags.td(g["name"]),
                    ui.tags.td(_fmt(g["num_layers"])),
                    ui.tags.td(_fmt(g["min_depth"], " m")),
                    ui.tags.td(_fmt(g["max_depth"], " m")),
                )
                for g in ctx["grids"]
            ]
            sim_rows = [
                ui.tags.tr(
                    ui.tags.td(s["name"]),
                    ui.tags.td(s["start_time"] or "—"),
                    ui.tags.td(s["end_time"] or "—"),
                    ui.tags.td(_fmt(s["time_step"], " s")),
                )
                for s in ctx["simulations"]
            ]
            grids_block = (
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(
                            ui.tags.th("Name"),
                            ui.tags.th("Layers"),
                            ui.tags.th("Min depth"),
                            ui.tags.th("Max depth"),
                        )
                    ),
                    ui.tags.tbody(*grid_rows),
                    class_="table table-sm",
                )
                if grid_rows
                else ui.p("No grids imported.", class_="text-muted")
            )
            sims_block = (
                ui.tags.table(
                    ui.tags.thead(
                        ui.tags.tr(
                            ui.tags.th("Name"),
                            ui.tags.th("Start"),
                            ui.tags.th("End"),
                            ui.tags.th("Time step"),
                        )
                    ),
                    ui.tags.tbody(*sim_rows),
                    class_="table table-sm",
                )
                if sim_rows
                else ui.p("No simulations.", class_="text-muted")
            )
            m = ui.modal(
                ui.h6("Grids"),
                grids_block,
                ui.h6("Simulations"),
                sims_block,
                title=f"Project: {ctx['name']}",
                easy_close=True,
                footer=ui.modal_button("Close"),
                size="l",
            )
            ui.modal_show(m)
```

Also update the dedup-set comment at line ~322 to include the new prefix:

```python
    # (open_proj_, project_, details_, export_, clone_, share_, confirm_share_, unshare_)
```

- [ ] **Step 6: Run the affected tests**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_project_context.py tests/test_dead_controls_wired.py tests/test_pages_access_control.py tests/test_pages_helpers.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/razinka/shyfem
git add shyfem-ui/shyfem_ui/services/project_context.py shyfem-ui/shyfem_ui/pages/home.py shyfem-ui/tests/test_project_context.py shyfem-ui/tests/test_dead_controls_wired.py
git commit -m "feat(ui): surface Grid/Simulation metadata in a project Details modal (audit P6)

num_layers/min_depth/max_depth + start/end/time_step were populated on
import but never shown. load_project_context now exposes them and the
dashboard gains a gated read-only Details modal."
```

---

### Task 5: Full verification, audit closure note, merge gate

- [ ] **Step 1: Full suite + ruff + black**

```bash
cd /home/razinka/shyfem/shyfem-ui && CONDA_PREFIX="" /opt/micromamba/envs/shiny/bin/python -m pytest
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m ruff check .
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m black --check shyfem_ui/
```
Expected: 0 failed and a pass count strictly greater than the baseline recorded in Task 0 Step 2 (the tasks add tests), ruff clean, black clean (CI runs `black --check shyfem_ui/` — `.github/workflows/ui-ci.yml:34` — so it must pass locally; if black reports diffs, run `black shyfem_ui/`, re-run the suite, and amend the offending task's commit). If anything fails, fix before proceeding (use superpowers:systematic-debugging).

- [ ] **Step 2: Mark the parent plan closed**

Append to `docs/plans/2026-06-08-shyfem-ui-unwired-fixes-plan.md`:

```markdown

---
## Closure (2026-06-12)
All phases complete. P1-P4 merged via f888d38 / 3467d45 / 40d21cf /
4810808; P5 cancel_workflow + P6 _active_nav merged via 824501f; the
P5/P6 remainder finished via
`docs/plans/2026-06-12-unwired-audit-closure-plan.md`: run_shyplot
removed, list_templates routed (+ dead services/__init__ re-export
dropped), IBM time filter surfaced, Grid/Simulation metadata surfaced
in the dashboard Details modal.
Decision checklist: (1) theme → delete; (2) celery_task_id → wire;
(3) run_shyplot remove / cancel_workflow surface / lgr time-filter
surface / list_templates route; (4) write-only columns → surface.
(Note: these "P" numbers are this plan's PHASE numbers; the audit
report's own section numbering differs — map via item names.)
```

```bash
cd /home/razinka/shyfem
git add docs/plans/2026-06-08-shyfem-ui-unwired-fixes-plan.md
git commit -m "docs: close out the 2026-06-08 unwired-UI audit plan"
```

- [ ] **Step 3: Push and present for merge**

```bash
git push -u origin fix/ui-unwired-closure
```

**STOP — hold for the owner's go-ahead before merging.** UI merges deploy to laguna immediately (Shiny Server symlinks the git tree). On go-ahead:

```bash
git checkout main
git merge --no-ff fix/ui-unwired-closure -m "Merge fix/ui-unwired-closure: audit P5/P6 remainder — all 2026-06-08 unwired items closed"
git push origin main
```

- [ ] **Step 4: Post-merge smoke check on laguna**

Open `https://laguna.ku.lt/shyfem-ui/` and verify: (a) dashboard project row shows a working Details modal; (b) IBM page shows the Time Filter inputs + loaded-range hint, the map still renders after loading a `.lgr`, and the particle *trails* (not just the start/end markers and stats) visibly change when a filter is applied — if the trails do not respond, that is a pre-existing trips-layer animation issue (`currentTime` never advances because the layer lacks `_tripsAnimation`); file it separately, do NOT scope-creep into this branch; (c) a filter window matching nothing recenters the map to the default Adriatic view — known and accepted; (d) Run page workflow template select still lists templates with the info panel.
