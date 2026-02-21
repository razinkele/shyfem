# Solver Selection UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a solver dropdown to the Run page that lets users choose between SPARSKIT (direct) and PETSc (iterative) solvers, with mesh-size-based recommendations.

**Architecture:** Two binaries coexist (`bin/shyfem` for SPARSKIT, `bin/shyfem-petsc` for PETSc). The UI detects PETSc availability, reads mesh node count from the grid file referenced in the STR file, and recommends a solver. The solver choice routes to the correct binary in the job execution pipeline.

**Tech Stack:** Python 3.13, Shiny for Python, pytest, GNU Make, Fortran (build only)

---

### Task 1: Add `check_solver_available()` to ShyfemWrapper

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:69-75`
- Test: `shyfem-ui/tests/test_wrapper.py`

**Step 1: Write the failing tests**

Add to `shyfem-ui/tests/test_wrapper.py` at the end of the `TestShyfemWrapper` class:

```python
    def test_check_solver_available_sparskit(self, wrapper):
        """SPARSKIT available when bin/shyfem exists."""
        (wrapper.bin_dir / "shyfem").touch()
        assert wrapper.check_solver_available("sparskit") is True

    def test_check_solver_available_petsc_missing(self, wrapper):
        """PETSc unavailable when bin/shyfem-petsc doesn't exist."""
        assert wrapper.check_solver_available("petsc") is False

    def test_check_solver_available_petsc_present(self, wrapper):
        """PETSc available when bin/shyfem-petsc exists."""
        (wrapper.bin_dir / "shyfem-petsc").touch()
        assert wrapper.check_solver_available("petsc") is True

    def test_check_solver_available_unknown(self, wrapper):
        """Unknown solver returns False."""
        assert wrapper.check_solver_available("unknown") is False
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_wrapper.py::TestShyfemWrapper::test_check_solver_available_sparskit -v
```

Expected: FAIL — `AttributeError: 'ShyfemWrapper' object has no attribute 'check_solver_available'`

**Step 3: Implement `check_solver_available`**

In `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py`, add after the `check_available` method (after line 75):

```python
    # Map solver names to executable names
    SOLVER_EXECUTABLES = {
        "sparskit": "shyfem",
        "petsc": "shyfem-petsc",
    }

    def check_solver_available(self, solver: str) -> bool:
        """Check if a solver variant is available."""
        exe_name = self.SOLVER_EXECUTABLES.get(solver)
        if exe_name is None:
            return False
        return self.check_available(exe_name)
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_wrapper.py::TestShyfemWrapper::test_check_solver_available_sparskit tests/test_wrapper.py::TestShyfemWrapper::test_check_solver_available_petsc_missing tests/test_wrapper.py::TestShyfemWrapper::test_check_solver_available_petsc_present tests/test_wrapper.py::TestShyfemWrapper::test_check_solver_available_unknown -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/services/shyfem_wrapper.py tests/test_wrapper.py
git commit -m "feat: add check_solver_available() to ShyfemWrapper

Maps solver names (sparskit/petsc) to binary names (shyfem/shyfem-petsc).
Returns True only if the corresponding binary exists in bin/.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Add `solver` Parameter to `run_shyfem()`

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py:278-310`
- Test: `shyfem-ui/tests/test_wrapper.py`

**Step 1: Write the failing tests**

Add a new test class at the end of `shyfem-ui/tests/test_wrapper.py`:

```python
class TestRunShyfemSolver:
    """Tests for solver selection in run_shyfem."""

    @pytest.fixture
    def wrapper(self, tmp_path):
        shyfem_dir = tmp_path / "shyfem"
        shyfem_dir.mkdir()
        (shyfem_dir / "bin").mkdir()
        # Create both solver binaries as shell scripts
        for name in ("shyfem", "shyfem-petsc"):
            exe = shyfem_dir / "bin" / name
            exe.write_text("#!/bin/bash\necho 'solver=$0'")
            exe.chmod(0o755)
        return ShyfemWrapper(shyfem_dir)

    @pytest.mark.asyncio
    async def test_default_solver_uses_shyfem(self, wrapper, tmp_path):
        """No solver arg uses bin/shyfem."""
        result = await wrapper.run_shyfem("test.str", tmp_path)
        assert "shyfem" in result.command
        assert "shyfem-petsc" not in result.command

    @pytest.mark.asyncio
    async def test_petsc_solver_uses_shyfem_petsc(self, wrapper, tmp_path):
        """solver='petsc' uses bin/shyfem-petsc."""
        result = await wrapper.run_shyfem("test.str", tmp_path, solver="petsc")
        assert "shyfem-petsc" in result.command

    @pytest.mark.asyncio
    async def test_sparskit_solver_uses_shyfem(self, wrapper, tmp_path):
        """solver='sparskit' uses bin/shyfem."""
        result = await wrapper.run_shyfem("test.str", tmp_path, solver="sparskit")
        assert "shyfem" in result.command
        assert "shyfem-petsc" not in result.command

    @pytest.mark.asyncio
    async def test_petsc_solver_not_found_raises(self, wrapper, tmp_path):
        """solver='petsc' raises FileNotFoundError if binary missing."""
        # Remove petsc binary
        (wrapper.bin_dir / "shyfem-petsc").unlink()
        with pytest.raises(FileNotFoundError):
            await wrapper.run_shyfem("test.str", tmp_path, solver="petsc")
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_wrapper.py::TestRunShyfemSolver::test_default_solver_uses_shyfem -v
```

Expected: FAIL — `TypeError: run_shyfem() got an unexpected keyword argument 'solver'`

**Step 3: Modify `run_shyfem` to accept solver parameter**

Replace the `run_shyfem` method in `shyfem-ui/shyfem_ui/services/shyfem_wrapper.py` (lines 278-310):

```python
    async def run_shyfem(
        self,
        str_file: Path | str,
        working_dir: Path | str,
        mpi_enabled: bool = False,
        mpi_np: int = 1,
        mpirun_path: str = "mpirun",
        options: list[str] | None = None,
        solver: str = "sparskit",
        progress_callback: Callable[[float, str], None] | None = None,
        output_callback: Callable[[str], None] | None = None,
    ) -> CommandResult:
        """Run shyfem simulation.

        Args:
            str_file: Path to input .str file
            working_dir: Working directory
            mpi_enabled: Whether to use MPI
            mpi_np: Number of MPI processes
            mpirun_path: Path to mpirun executable
            options: Additional options
            solver: Solver variant ('sparskit' or 'petsc')
        """
        tool_name = self.SOLVER_EXECUTABLES.get(solver, "shyfem")
        args_list = options or []
        args_list.append(str(str_file))

        prefix = None
        if mpi_enabled and mpi_np > 1:
            prefix = [mpirun_path, "-np", str(mpi_np)]

        return await self.run_command(
            tool_name, args_list, working_dir,
            progress_callback, output_callback,
            command_prefix=prefix,
        )
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_wrapper.py::TestRunShyfemSolver -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/services/shyfem_wrapper.py tests/test_wrapper.py
git commit -m "feat: add solver parameter to run_shyfem()

Routes to bin/shyfem-petsc when solver='petsc', bin/shyfem otherwise.
Raises FileNotFoundError if the selected solver binary is missing.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 3: Add `solver_node_threshold` to Config

**Files:**
- Modify: `shyfem-ui/shyfem_ui/config.py:77`
- Test: `shyfem-ui/tests/test_config.py`

**Step 1: Write the failing test**

Read `tests/test_config.py` to understand the existing test style, then add:

```python
def test_solver_node_threshold_default():
    """Default solver node threshold is 50000."""
    from shyfem_ui.config import Config
    c = Config(shyfem_dir="/tmp/test", work_dir="/tmp/work")
    assert c.solver_node_threshold == 50000

def test_solver_node_threshold_override():
    """Solver node threshold can be overridden."""
    from shyfem_ui.config import Config
    c = Config(shyfem_dir="/tmp/test", work_dir="/tmp/work", solver_node_threshold=100000)
    assert c.solver_node_threshold == 100000
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py::test_solver_node_threshold_default -v
```

Expected: FAIL — `TypeError: ... unexpected keyword argument 'solver_node_threshold'`

**Step 3: Add the config field**

In `shyfem-ui/shyfem_ui/config.py`, after the `mpirun_path` field (line 77), add:

```python
    # Solver settings
    solver_node_threshold: int = Field(
        default=50000,
        description="Node count threshold for recommending PETSc over SPARSKIT"
    )
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_config.py::test_solver_node_threshold_default tests/test_config.py::test_solver_node_threshold_override -v
```

Expected: 2 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/config.py tests/test_config.py
git commit -m "feat: add solver_node_threshold config (default 50k nodes)

Threshold above which the UI recommends PETSc iterative solver.
Configurable via SHYFEM_UI_SOLVER_NODE_THRESHOLD env var.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Add Solver Recommendation Helper

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py`
- Test: `shyfem-ui/tests/test_run_helpers.py`

This is a pure function that returns a recommendation string based on node count and threshold.

**Step 1: Write the failing tests**

Add to `shyfem-ui/tests/test_run_helpers.py`:

```python
from shyfem_ui.pages.run import get_solver_recommendation


class TestGetSolverRecommendation:
    """Tests for solver recommendation logic."""

    def test_small_mesh_recommends_sparskit(self):
        rec = get_solver_recommendation(1500, 50000)
        assert rec["solver"] == "sparskit"
        assert "Direct" in rec["hint"]

    def test_large_mesh_recommends_petsc(self):
        rec = get_solver_recommendation(100000, 50000)
        assert rec["solver"] == "petsc"
        assert "Iterative" in rec["hint"]

    def test_threshold_boundary_recommends_petsc(self):
        rec = get_solver_recommendation(50000, 50000)
        assert rec["solver"] == "petsc"

    def test_below_threshold_recommends_sparskit(self):
        rec = get_solver_recommendation(49999, 50000)
        assert rec["solver"] == "sparskit"

    def test_zero_nodes_recommends_sparskit(self):
        rec = get_solver_recommendation(0, 50000)
        assert rec["solver"] == "sparskit"

    def test_none_nodes_returns_no_recommendation(self):
        rec = get_solver_recommendation(None, 50000)
        assert rec["solver"] is None
        assert "unknown" in rec["hint"].lower() or "detect" in rec["hint"].lower()
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py::TestGetSolverRecommendation -v
```

Expected: FAIL — `ImportError: cannot import name 'get_solver_recommendation'`

**Step 3: Implement `get_solver_recommendation`**

In `shyfem-ui/shyfem_ui/pages/run.py`, add after the `_get_job_metadata` function (after line 54):

```python
def get_solver_recommendation(
    num_nodes: int | None, threshold: int
) -> dict[str, str | None]:
    """Return solver recommendation based on mesh node count.

    Returns dict with 'solver' ('sparskit'/'petsc'/None) and 'hint' (display text).
    """
    if num_nodes is None:
        return {
            "solver": None,
            "hint": "Could not detect mesh size — select solver manually",
        }
    if num_nodes >= threshold:
        return {
            "solver": "petsc",
            "hint": (
                f"Mesh has {num_nodes:,} nodes. "
                f"Recommended: Iterative Solver (PETSc) — scales better for large meshes"
            ),
        }
    return {
        "solver": "sparskit",
        "hint": (
            f"Mesh has {num_nodes:,} nodes. "
            f"Recommended: Direct Solver (SPARSKIT) — fastest for small/medium meshes"
        ),
    }
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py::TestGetSolverRecommendation -v
```

Expected: 6 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/pages/run.py tests/test_run_helpers.py
git commit -m "feat: add get_solver_recommendation() helper

Returns solver name and display hint based on mesh node count vs threshold.
Recommends SPARSKIT below threshold, PETSc at or above.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Add Mesh Node Count Detection from STR File

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py`
- Test: `shyfem-ui/tests/test_run_helpers.py`

The STR file's `$title` section has the basin name as its 3rd line (e.g., `GRID/MM_coarse`). The grid file is `{basnam}.grd` relative to the working directory. We parse the grid to get node count.

**Step 1: Write the failing tests**

Add to `shyfem-ui/tests/test_run_helpers.py`:

```python
from pathlib import Path
from shyfem_ui.pages.run import detect_mesh_node_count


class TestDetectMeshNodeCount:
    """Tests for mesh node count detection from STR file."""

    def test_valid_str_with_grid(self, tmp_path):
        """Detects node count from grid file referenced in STR."""
        # Create a minimal .grd file (3 nodes, 1 triangle)
        grd_content = (
            "0 (ntype) 3 (nnode) 1 (nelem) 0 (nline)\n"
            "1 0 0.0 0.0 -5.0\n"
            "2 0 1.0 0.0 -5.0\n"
            "3 0 0.5 1.0 -5.0\n"
            "1 0 3 1 2 3\n"
        )
        grid_dir = tmp_path / "GRID"
        grid_dir.mkdir()
        (grid_dir / "test.grd").write_text(grd_content)

        # Create STR file referencing the grid
        str_content = "$title\n  Test sim\n  test_id\n  GRID/test\n$end\n$para\n$end\n"
        str_file = tmp_path / "test.str"
        str_file.write_text(str_content)

        count = detect_mesh_node_count(str_file, tmp_path)
        assert count == 3

    def test_missing_grid_returns_none(self, tmp_path):
        """Returns None when grid file doesn't exist."""
        str_content = "$title\n  Test sim\n  test_id\n  GRID/missing\n$end\n$para\n$end\n"
        str_file = tmp_path / "test.str"
        str_file.write_text(str_content)

        count = detect_mesh_node_count(str_file, tmp_path)
        assert count is None

    def test_no_title_section_returns_none(self, tmp_path):
        """Returns None when STR has no $title section."""
        str_content = "$para\n  idt = '300s'\n$end\n"
        str_file = tmp_path / "test.str"
        str_file.write_text(str_content)

        count = detect_mesh_node_count(str_file, tmp_path)
        assert count is None

    def test_nonexistent_str_returns_none(self, tmp_path):
        """Returns None for nonexistent STR file."""
        count = detect_mesh_node_count(tmp_path / "nope.str", tmp_path)
        assert count is None
```

**Step 2: Run tests to verify they fail**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py::TestDetectMeshNodeCount -v
```

Expected: FAIL — `ImportError: cannot import name 'detect_mesh_node_count'`

**Step 3: Implement `detect_mesh_node_count`**

In `shyfem-ui/shyfem_ui/pages/run.py`, add after `get_solver_recommendation` (and add the import for `GrdParser` and `StrParser` near the top):

At the top of the file, add these imports:

```python
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.parser_str import StrParser
```

Then add the function:

```python
def detect_mesh_node_count(
    str_file: Path | str, working_dir: Path | str
) -> int | None:
    """Detect mesh node count from the grid file referenced in a STR file.

    The STR $title section's 3rd line is the basin name (e.g. 'GRID/MM_coarse').
    The grid file is {basnam}.grd relative to working_dir.
    Returns node count or None if detection fails.
    """
    str_path = Path(str_file)
    work_path = Path(working_dir)

    if not str_path.exists():
        return None

    try:
        content = str_path.read_text()
        parsed = StrParser.parse(content)
    except Exception:
        return None

    title_sec = parsed.sections.get("title")
    if title_sec is None or len(title_sec.raw_lines) < 3:
        return None

    # 3rd non-empty line in $title is the basin name
    lines = [ln.strip() for ln in title_sec.raw_lines if ln.strip()]
    if len(lines) < 3:
        return None
    basnam = lines[2]

    # Try .grd then .bas extension
    for ext in (".grd", ".bas"):
        grid_path = work_path / f"{basnam}{ext}"
        if grid_path.exists():
            try:
                grd = GrdParser.parse_file(grid_path)
                return grd.num_nodes
            except Exception:
                continue

    return None
```

**Step 4: Run tests to verify they pass**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py::TestDetectMeshNodeCount -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/pages/run.py tests/test_run_helpers.py
git commit -m "feat: add detect_mesh_node_count() from STR grid reference

Parses STR $title section to find basin name, resolves .grd/.bas file,
returns node count via GrdParser. Returns None on any failure.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Add Solver Dropdown and Hint to Run Page UI

**Files:**
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:57-127` (run_ui function)
- Modify: `shyfem-ui/shyfem_ui/pages/run.py:255-449` (run_server function)

**Step 1: Add UI elements to `run_ui()`**

In `shyfem-ui/shyfem_ui/pages/run.py`, in the `run_ui()` function, after the MPI options panel_conditional block (after line 112, before the `# Job dependency` comment at line 113), insert:

```python
                    # Solver options (shown for shyfem)
                    ui.panel_conditional(
                        "input.tool_select === 'shyfem'",
                        ui.hr(),
                        ui.h6("Solver Options"),
                        ui.input_select(
                            "solver_select",
                            "Solver",
                            choices={
                                "sparskit": "Direct Solver (SPARSKIT)",
                                "petsc": "Iterative Solver (PETSc)",
                            },
                            selected="sparskit",
                        ),
                        ui.output_ui("solver_hint"),
                    ),
```

**Step 2: Add server logic for solver hint and availability**

In the `run_server()` function, after the `_on_project_changed` effect (after line 289), add:

```python
    @render.ui
    def solver_hint():
        """Show solver recommendation and availability hint."""
        # Check PETSc availability
        petsc_available = config.shyfem_dir and ShyfemWrapper(
            config.shyfem_dir
        ).check_solver_available("petsc")

        # Detect mesh size from input file
        input_file = input.input_file()
        working_dir = input.working_dir()
        num_nodes = None
        if input_file and working_dir:
            num_nodes = detect_mesh_node_count(input_file, working_dir)

        rec = get_solver_recommendation(num_nodes, config.solver_node_threshold)
        parts = []

        if not petsc_available:
            parts.append(
                ui.p(
                    "PETSc solver not installed. Build with: ",
                    ui.code("make petsc"),
                    class_="text-warning small mb-1",
                )
            )

        if rec["hint"]:
            parts.append(ui.p(rec["hint"], class_="text-muted small mb-0"))

        return ui.div(*parts) if parts else ui.div()
```

Add the `ShyfemWrapper` import near the top of the file if not already there:

```python
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
```

**Step 3: Update `_submit_job` to pass solver choice**

In the `_submit_job` function (around line 432-439), modify the JobSpec construction and the execution routing. After the `metadata` line and before `spec = JobSpec(...)`:

```python
        # Solver selection
        solver = input.solver_select() if tool == "shyfem" else "sparskit"
        if solver == "petsc":
            metadata["solver"] = "petsc"
```

**Step 4: Run existing tests to verify nothing is broken**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py -v
```

Expected: All existing tests PASS

**Step 5: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/pages/run.py
git commit -m "feat: add solver dropdown and mesh hint to Run page

Shows solver selection (SPARSKIT/PETSc) below MPI options for shyfem tool.
Displays mesh node count and recommendation hint. Warns if PETSc not installed.
Stores solver choice in job metadata.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 7: Route Solver Choice in Job Execution

**Files:**
- Modify: `shyfem-ui/shyfem_ui/services/job_local.py:245-265`
- Modify: `shyfem-ui/shyfem_ui/services/job_celery.py:167-187`
- Test: `shyfem-ui/tests/test_run_helpers.py`

**Step 1: Write the failing test**

Add to `shyfem-ui/tests/test_run_helpers.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from shyfem_ui.services.job_queue import JobSpec


class TestSolverJobRouting:
    """Tests for solver metadata routing in job execution."""

    def test_jobspec_metadata_stores_solver(self):
        """JobSpec metadata can store solver choice."""
        spec = JobSpec(
            name="test",
            tool_name="shyfem",
            args=["test.str"],
            working_dir="/tmp/test",
            metadata={"solver": "petsc"},
        )
        assert spec.metadata["solver"] == "petsc"

    def test_jobspec_default_no_solver(self):
        """JobSpec metadata has no solver key by default."""
        spec = JobSpec(
            name="test",
            tool_name="shyfem",
            args=["test.str"],
            working_dir="/tmp/test",
        )
        assert "solver" not in spec.metadata
```

**Step 2: Run tests to verify they pass** (these are metadata tests, should pass already)

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_run_helpers.py::TestSolverJobRouting -v
```

Expected: 2 PASSED

**Step 3: Modify `LocalJobQueue._execute_job`**

In `shyfem-ui/shyfem_ui/services/job_local.py`, replace the execution block (lines 245-265):

```python
            try:
                solver = spec.metadata.get("solver", "sparskit")
                if spec.tool_name == "shyfem" and spec.mpi_enabled and spec.mpi_np > 1:
                    # MPI execution
                    result = await self.wrapper.run_shyfem(
                        spec.args[-1] if spec.args else "",
                        spec.working_dir,
                        mpi_enabled=True,
                        mpi_np=spec.mpi_np,
                        mpirun_path="mpirun",
                        options=spec.args[:-1] if len(spec.args) > 1 else None,
                        solver=solver,
                        progress_callback=progress_callback,
                        output_callback=output_callback,
                    )
                elif spec.tool_name == "shyfem":
                    # Serial shyfem (may use petsc solver)
                    result = await self.wrapper.run_shyfem(
                        spec.args[-1] if spec.args else "",
                        spec.working_dir,
                        solver=solver,
                        progress_callback=progress_callback,
                        output_callback=output_callback,
                    )
                else:
                    result = await self.wrapper.run_command(
                        spec.tool_name,
                        spec.args,
                        spec.working_dir,
                        progress_callback,
                        output_callback,
                    )
```

**Step 4: Modify `execute_shyfem_job` in job_celery.py**

In `shyfem-ui/shyfem_ui/services/job_celery.py`, replace the execution block (around lines 167-187):

```python
    try:
        mpi_enabled = job_info.metadata.get("mpi_enabled", False)
        mpi_np = job_info.metadata.get("mpi_np", 1)
        solver = job_info.metadata.get("solver", "sparskit")

        if job_info.tool_name == "shyfem" and mpi_enabled and mpi_np > 1:
            result = asyncio.run(wrapper.run_shyfem(
                job_info.args[-1] if job_info.args else "",
                working_dir,
                mpi_enabled=True,
                mpi_np=mpi_np,
                mpirun_path="mpirun",
                options=job_info.args[:-1] if len(job_info.args) > 1 else None,
                solver=solver,
                progress_callback=progress_callback,
            ))
        elif job_info.tool_name == "shyfem":
            result = asyncio.run(wrapper.run_shyfem(
                job_info.args[-1] if job_info.args else "",
                working_dir,
                solver=solver,
                progress_callback=progress_callback,
            ))
        else:
            result = asyncio.run(wrapper.run_command(
                job_info.tool_name,
                job_info.args,
                working_dir,
                progress_callback=progress_callback,
            ))
```

**Step 5: Run all tests to verify nothing is broken**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_wrapper.py tests/test_run_helpers.py -v
```

Expected: All PASSED

**Step 6: Commit**

```bash
cd /home/razinka/shyfem/shyfem-ui
git add shyfem_ui/services/job_local.py shyfem_ui/services/job_celery.py tests/test_run_helpers.py
git commit -m "feat: route solver metadata to correct binary in job execution

Both LocalJobQueue and CeleryJobQueue read metadata['solver'] and pass
it to run_shyfem(). Serial shyfem jobs now also go through run_shyfem()
to support solver selection. Default remains 'sparskit'.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 8: Add `make petsc` Build Target

**Files:**
- Modify: `Makefile` (top-level)

**Step 1: Read the current Makefile structure**

Check the existing `fem`/`shyfem` targets around line 141.

**Step 2: Add the `petsc` target**

In the top-level `Makefile`, add the `petsc` target to the `.PHONY` list (line 110), then add the target after the `shyfem` target (after line 143):

Add `petsc` to the `.PHONY` line:

```makefile
.PHONY: default all nuopc compile fem shyfem petsc para_get para_compile para_clean \
```

Add the target:

```makefile
petsc: checkv libmod
	cd src; make SOLVER=PETSC PETSC_DIR=$(PETSC_DIR)
	@if [ -f bin/shyfem ]; then \
	  cp bin/shyfem bin/shyfem-petsc; \
	  echo "PETSc solver installed as bin/shyfem-petsc"; \
	else \
	  echo "ERROR: build failed - bin/shyfem not produced"; exit 1; \
	fi
```

Note: The SHYFEM build always produces `bin/shyfem`. The `petsc` target builds with `SOLVER=PETSC` and renames the output to `bin/shyfem-petsc`. Users should run `make fem` first (to get SPARSKIT binary), then `make petsc` (which overwrites `bin/shyfem` temporarily, then renames to `bin/shyfem-petsc`). After that, run `make fem` again to restore the SPARSKIT binary.

Actually, this is fragile. A better approach: build PETSc, rename, then rebuild SPARSKIT:

```makefile
petsc: checkv libmod
	cd src; make SOLVER=PETSC PETSC_DIR=$(PETSC_DIR)
	@if [ -f bin/shyfem ]; then \
	  mv bin/shyfem bin/shyfem-petsc; \
	  echo "PETSc solver built as bin/shyfem-petsc"; \
	  echo "Rebuilding default SPARSKIT solver..."; \
	  cd src/shyfem && make clean; \
	fi
	cd src; make
	@echo "Both solvers ready: bin/shyfem (SPARSKIT) and bin/shyfem-petsc (PETSc)"
```

**Step 3: Verify the target builds**

```bash
cd /home/razinka/shyfem
PATH=/usr/bin:$PATH make petsc PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real OMP=true MPI=true PARTS=METIS METISDIR=/usr 2>&1 | tail -10
```

Expected: Both `bin/shyfem` and `bin/shyfem-petsc` exist.

```bash
ls -la bin/shyfem bin/shyfem-petsc
```

**Step 4: Verify both binaries work**

```bash
cd /home/razinka/shyfem/testcases/examples/mar_menor
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH shyfem mm_hyd_00.str 2>&1 | grep "matrix solver"
OMP_NUM_THREADS=1 PATH=/home/razinka/shyfem/bin:/usr/bin:$PATH shyfem-petsc mm_hyd_00.str 2>&1 | grep "matrix solver"
```

Expected:
- `shyfem`: `matrix solver: sparsekit`
- `shyfem-petsc`: `matrix solver: PETSc`

**Step 5: Commit**

```bash
cd /home/razinka/shyfem
git add Makefile
git commit -m "feat: add 'make petsc' target for PETSc solver binary

Builds bin/shyfem-petsc alongside bin/shyfem (SPARSKIT).
Usage: make petsc PETSC_DIR=/usr/lib/petscdir/petsc3.19/x86_64-linux-gnu-real

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 9: Run Full Test Suite

**Files:**
- None modified

**Step 1: Run all shyfem-ui tests**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All tests pass (existing + new).

**Step 2: Count new tests added**

```bash
cd /home/razinka/shyfem/shyfem-ui
/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_wrapper.py tests/test_run_helpers.py -v 2>&1 | grep -c PASSED
```

Expected: ~20+ tests in these two files.
