# Mar Menor Tutorial Guidance — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated Tutorial tab to the SHYFEM UI that provides step-by-step guidance through all 6 phases (14 simulations) of the Mar Menor tutorial.

**Architecture:** Tutorial content lives in `tutorial_content.py` (pure data, no UI). Tutorial page in `pages/tutorial.py` renders a two-column layout: phase navigator (left) + step content (right). Tab is conditionally shown when active project is a tutorial project.

**Tech Stack:** Shiny for Python (ui module), existing page module pattern, Bootstrap 5 components via `ui.tags`

**Test runner:** `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v`

---

### Task 1: Create tutorial content module

**Files:**
- Create: `shyfem_ui/tutorial_content.py`
- Test: `tests/test_tutorial_content.py`

**Step 1: Write the failing test**

Create `tests/test_tutorial_content.py`:

```python
"""Tests for tutorial content structure and completeness."""

import pytest


class TestTutorialContentStructure:
    """Validate the TUTORIAL_CONTENT data structure."""

    def test_has_six_phases(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        assert len(TUTORIAL_CONTENT) == 6

    def test_phase_keys(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            assert "id" in phase
            assert "title" in phase
            assert "description" in phase
            assert "simulations" in phase
            assert len(phase["simulations"]) > 0

    def test_simulation_keys(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                assert "name" in sim
                assert "str_file" in sim
                assert "title" in sim
                assert "summary" in sim
                assert "steps" in sim
                assert len(sim["steps"]) > 0

    def test_step_keys(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                for step in sim["steps"]:
                    assert "title" in step
                    assert "content" in step

    def test_all_str_files_exist_in_mar_menor(self):
        """Every referenced .str file must exist in the testcases source."""
        from pathlib import Path
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        mar_menor = Path(__file__).resolve().parents[1] / "testcases" / "examples" / "mar_menor"
        if not mar_menor.is_dir():
            mar_menor = Path("/home/razinka/shyfem/testcases/examples/mar_menor")
        if not mar_menor.is_dir():
            pytest.skip("Mar Menor testcase directory not found")
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                str_path = mar_menor / sim["str_file"]
                assert str_path.exists(), f"Missing: {sim['str_file']}"

    def test_total_simulation_count(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        total = sum(len(p["simulations"]) for p in TUTORIAL_CONTENT)
        assert total == 14

    def test_new_params_are_dicts(self):
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        for phase in TUTORIAL_CONTENT:
            for sim in phase["simulations"]:
                if "new_params" in sim:
                    assert isinstance(sim["new_params"], dict)


class TestHelpers:
    """Test helper functions."""

    def test_get_phase_by_id(self):
        from shyfem_ui.tutorial_content import get_phase
        phase = get_phase("phase1")
        assert phase is not None
        assert phase["title"].startswith("Phase 1")

    def test_get_phase_missing(self):
        from shyfem_ui.tutorial_content import get_phase
        assert get_phase("nonexistent") is None

    def test_get_simulation(self):
        from shyfem_ui.tutorial_content import get_simulation
        sim = get_simulation("mm_hyd_00")
        assert sim is not None
        assert sim["name"] == "mm_hyd_00"

    def test_get_simulation_missing(self):
        from shyfem_ui.tutorial_content import get_simulation
        assert get_simulation("nonexistent") is None

    def test_get_all_sim_names(self):
        from shyfem_ui.tutorial_content import get_all_sim_names
        names = get_all_sim_names()
        assert "mm_hyd_00" in names
        assert "mm_hyd_43" in names
        assert len(names) == 14
```

**Step 2: Run test to verify it fails**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_tutorial_content.py -v`
Expected: FAIL (module not found)

**Step 3: Write the tutorial content module**

Create `shyfem_ui/tutorial_content.py` with the full `TUTORIAL_CONTENT` data structure. Each of the 6 phases contains its simulations with:
- `name`, `str_file`, `title`, `summary`
- `new_params`: dict of param_name -> explanation (what changed vs previous sim)
- `steps`: list of dicts with `title`, `content`, optional `nav_target` (tab name to link to)

**Phase 1 content (4 sims):**
- `mm_hyd_00`: Minimal setup — `$title` and `$para` basics (itanf, itend, idt, ilin). Steps: prepare grid, understand STR, run sim, check output.
- `mm_hyd_01`: Output control — adds `idtout`, `idtext`, `$extra` monitor points. Steps: understand output timing, run, examine time series.
- `mm_hyd_02`: Wind forcing — adds `iwtype=3`, `dragco=2.5e-3`, wind file. Steps: understand wind params, run, compare to no-wind.
- `mm_hyd_03`: Bottom friction — adds `ireib=5`, `czdef=2.5e-3`. Steps: understand friction, run, compare.

**Phase 2 content (3 sims):**
- `mm_hyd_11`: Open boundary — adds `$bound1` with node list, `ibtyp=1`, level data. Steps: understand boundaries, run, examine water levels.
- `mm_hyd_12`: Boundary variations (12a/12b reference files exist but main sim is 12).
- `mm_hyd_13`: Refined boundary parameters.

**Phase 3 content (3 sims):**
- `mm_hyd_21`: Coriolis + rivers — adds `icor=1`, `dlat=38`, `$bound2` with `ibtyp=3` river.
- `mm_hyd_22`: Advection variations.
- `mm_hyd_23`: Horizontal diffusion.

**Phase 4 content (1 sim):**
- `mm_hyd_31`: Baroclinic salinity — `ibarcl=3`, `isalt=1`, `salref=35`, boundary salinity input, longer run (1 month).

**Phase 5 content (2 sims):**
- `mm_hyd_41`: Full 3D — `itemp=1`, `$levels`, turbulence (`iturb=1`), heat flux, evaporation.
- `mm_hyd_42`: Turbulence variations.

**Phase 6 content (1 sim):**
- `mm_hyd_43`: Non-linear — `ilin=0`, `coumax=0.8`, adaptive time-splitting (`itsplt=2`), Smagorinsky diffusion (`idhtyp=2`).

Helper functions:
```python
def get_phase(phase_id: str) -> dict | None:
    """Look up a phase by its id."""
    ...

def get_simulation(sim_name: str) -> dict | None:
    """Look up a simulation across all phases."""
    ...

def get_all_sim_names() -> list[str]:
    """Return ordered list of all simulation names."""
    ...
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_tutorial_content.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shyfem_ui/tutorial_content.py tests/test_tutorial_content.py
git commit -m "feat(tutorial): add tutorial content data structure with 6 phases"
```

---

### Task 2: Create Tutorial page module

**Files:**
- Create: `shyfem_ui/pages/tutorial.py`
- Test: `tests/test_tutorial_page.py`

**Step 1: Write the failing test**

Create `tests/test_tutorial_page.py`:

```python
"""Tests for Tutorial page rendering helpers."""

import pytest
from shiny import ui


class TestTutorialRenderHelpers:
    """Test pure rendering functions from tutorial page."""

    def test_render_phase_nav_item(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        phase = TUTORIAL_CONTENT[0]
        result = _render_phase_nav_item(phase, current_sim="mm_hyd_00", completed=set())
        assert result is not None

    def test_render_phase_nav_completed(self):
        from shyfem_ui.pages.tutorial import _render_phase_nav_item
        from shyfem_ui.tutorial_content import TUTORIAL_CONTENT
        phase = TUTORIAL_CONTENT[0]
        completed = {"mm_hyd_00", "mm_hyd_01", "mm_hyd_02", "mm_hyd_03"}
        result = _render_phase_nav_item(phase, current_sim=None, completed=completed)
        assert result is not None

    def test_render_step_content(self):
        from shyfem_ui.pages.tutorial import _render_step
        step = {"title": "Test Step", "content": "Do this thing."}
        result = _render_step(step, step_num=1)
        assert result is not None

    def test_render_step_with_nav_target(self):
        from shyfem_ui.pages.tutorial import _render_step
        step = {"title": "Run it", "content": "Click run.", "nav_target": "Run"}
        result = _render_step(step, step_num=1)
        assert result is not None

    def test_render_new_params_table(self):
        from shyfem_ui.pages.tutorial import _render_new_params
        params = {"iwtype": "Wind type (3 = speed/direction)", "dragco": "Wind drag coefficient"}
        result = _render_new_params(params)
        assert result is not None

    def test_render_new_params_empty(self):
        from shyfem_ui.pages.tutorial import _render_new_params
        result = _render_new_params({})
        assert result is None

    def test_render_sim_header(self):
        from shyfem_ui.pages.tutorial import _render_sim_header
        from shyfem_ui.tutorial_content import get_simulation
        sim = get_simulation("mm_hyd_01")
        result = _render_sim_header(sim)
        assert result is not None


class TestTutorialUI:
    """Test that tutorial_ui module function returns valid Tag."""

    def test_tutorial_ui_returns_tag(self):
        from shyfem_ui.pages.tutorial import tutorial_ui
        result = tutorial_ui()
        assert result is not None
```

**Step 2: Run test to verify it fails**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_tutorial_page.py -v`
Expected: FAIL (module not found)

**Step 3: Implement the Tutorial page**

Create `shyfem_ui/pages/tutorial.py` with:

1. `tutorial_ui()` — `@module.ui` function returning two-column layout:
   - Left column (`col-md-4`): Phase navigator with `ui.accordion` per phase, each containing clickable simulation links
   - Right column (`col-md-8`): Dynamic content area (`ui.output_ui("step_content")`)
   - Top: progress bar showing completed/total simulations

2. `tutorial_server()` — `@module.server` function with:
   - `active_project` reactive value (passed in)
   - `current_sim` reactive value (which simulation is selected)
   - `completed_sims` reactive value (set of completed sim names)
   - Click handlers for simulation links in the navigator
   - `@render.ui` for `step_content` that renders:
     - Simulation header (title, summary)
     - "What's New" params table (if `new_params` present)
     - Ordered steps with content and nav buttons
   - Mark-complete button per simulation

3. Pure rendering helper functions (testable without Shiny session):
   - `_render_phase_nav_item(phase, current_sim, completed)` → `ui.Tag`
   - `_render_step(step, step_num)` → `ui.Tag`
   - `_render_new_params(params)` → `ui.Tag | None`
   - `_render_sim_header(sim)` → `ui.Tag`

Server signature:
```python
@module.server
def tutorial_server(input, output, session, config, active_project, nav_callback=None):
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_tutorial_page.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add shyfem_ui/pages/tutorial.py tests/test_tutorial_page.py
git commit -m "feat(tutorial): add Tutorial page with phase navigator and step content"
```

---

### Task 3: Wire Tutorial tab into the app

**Files:**
- Modify: `shyfem_ui/pages/__init__.py`
- Modify: `shyfem_ui/app.py`

**Step 1: Add tutorial to the pages package**

In `shyfem_ui/pages/__init__.py`, add `"tutorial"` to `__all__`.

**Step 2: Add Tutorial tab to `_build_ui` in `app.py`**

In `shyfem_ui/app.py`:
1. Import `tutorial` in the pages import block (line ~19)
2. Add `ui.nav_panel("Tutorial", tutorial.tutorial_ui("tutorial"))` to `_build_ui` navset, after Dashboard and before Grid Prep

**Step 3: Add Tutorial server to `_build_server` in `app.py`**

In `_build_server` (after the home server call, ~line 529):
```python
tutorial.tutorial_server("tutorial", config, active_project=active_project, nav_callback=nav_to)
```

**Step 4: Update home.py to navigate to Tutorial tab after creation**

In `home.py`, in the `_create_tutorial_project` function (~line 518), change:
```python
_refresh_projects()
```
to:
```python
_refresh_projects()
if nav_callback:
    nav_callback("Tutorial")
```

**Step 5: Run the full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --ignore-glob=tests/test_playwright_*.py`
Expected: All existing tests PASS, no regressions

**Step 6: Commit**

```bash
git add shyfem_ui/pages/__init__.py shyfem_ui/app.py shyfem_ui/pages/home.py
git commit -m "feat(tutorial): wire Tutorial tab into app navigation"
```

---

### Task 4: Manual verification and cleanup

**Step 1: Restart Shiny Server**

```bash
sudo systemctl restart shiny-server
```

**Step 2: Test in browser**

1. Open dashboard
2. Delete existing tutorial project if needed
3. Click "Mar Menor Tutorial" button, create project
4. Verify it navigates to Tutorial tab
5. Click through phases and simulations
6. Verify navigation links go to correct tabs
7. Verify "What's New" parameter tables show correct diffs

**Step 3: Final commit with any fixes**

```bash
git add -A
git commit -m "fix(tutorial): address issues found during manual testing"
```
