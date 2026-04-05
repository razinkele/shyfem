"""Tests for workflow engine."""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus
from shyfem_ui.services.workflow import (
    WORKFLOW_TEMPLATES,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowStatus,
    WorkflowStep,
)


@pytest.fixture
def mock_queue():
    """Create a mock JobQueue."""
    queue = MagicMock()
    _jobs = {}
    _counter = [0]

    async def mock_submit(spec):
        _counter[0] += 1
        job_id = f"job-{_counter[0]}"
        _jobs[job_id] = JobInfo(
            id=job_id,
            name=spec.name,
            tool_name=spec.tool_name,
            args=spec.args,
            working_dir=str(spec.working_dir),
            status=JobStatus.COMPLETED,
            return_code=0,
            output_files=[f"/tmp/output_{_counter[0]}.bas"],
            created_at=datetime.now(),
            completed_at=datetime.now(),
        )
        return job_id

    async def mock_get_status(job_id):
        return _jobs.get(job_id)

    async def mock_cancel(job_id):
        if job_id in _jobs:
            _jobs[job_id].status = JobStatus.CANCELLED
            return True
        return False

    queue.submit = mock_submit
    queue.get_status = mock_get_status
    queue.cancel = mock_cancel
    queue._jobs = _jobs
    return queue


@pytest.fixture
def engine(mock_queue):
    """Create a WorkflowEngine with mock queue."""
    return WorkflowEngine(mock_queue)


class TestWorkflowTemplates:
    """Tests for workflow template definitions."""

    def test_templates_exist(self):
        """Test that expected templates are defined."""
        assert "full_simulation" in WORKFLOW_TEMPLATES
        assert "grid_only" in WORKFLOW_TEMPLATES
        assert "simulation_postprocess" in WORKFLOW_TEMPLATES

    def test_template_structure(self):
        """Test template structure has required keys."""
        for key, tpl in WORKFLOW_TEMPLATES.items():
            assert "name" in tpl
            assert "description" in tpl
            assert "steps" in tpl
            assert len(tpl["steps"]) > 0

    def test_template_steps_are_workflow_steps(self):
        """Test all steps are WorkflowStep instances."""
        for key, tpl in WORKFLOW_TEMPLATES.items():
            for step in tpl["steps"]:
                assert isinstance(step, WorkflowStep)
                assert step.name
                assert step.tool_name

    def test_full_simulation_has_four_steps(self):
        """Test full_simulation pipeline has 4 steps."""
        tpl = WORKFLOW_TEMPLATES["full_simulation"]
        assert len(tpl["steps"]) == 4
        names = [s.name for s in tpl["steps"]]
        assert "grid_prep" in names
        assert "partitioning" in names
        assert "simulation" in names
        assert "postprocess" in names

    def test_offline_tracer_template_exists(self):
        """Test that offline_tracer template is defined."""
        assert "offline_tracer" in WORKFLOW_TEMPLATES

    def test_offline_tracer_has_two_steps(self):
        """Test offline_tracer workflow has exactly 2 steps."""
        tpl = WORKFLOW_TEMPLATES["offline_tracer"]
        assert len(tpl["steps"]) == 2

    def test_offline_tracer_step_names(self):
        """Test offline_tracer step names and tool assignments."""
        tpl = WORKFLOW_TEMPLATES["offline_tracer"]
        steps = tpl["steps"]
        assert steps[0].name == "Hydrodynamic run"
        assert steps[0].tool_name == "shyfem"
        assert steps[1].name == "Tracer run"
        assert steps[1].tool_name == "shyfem"
        assert steps[1].input_from == "Hydrodynamic run"


class TestWorkflowEngine:
    """Tests for WorkflowEngine core functionality."""

    def test_list_templates(self, engine):
        """Test listing available templates."""
        templates = engine.list_templates()
        assert isinstance(templates, dict)
        assert "full_simulation" in templates
        assert "name" in templates["full_simulation"]
        assert "steps" in templates["full_simulation"]

    @pytest.mark.asyncio
    async def test_create_workflow(self, engine, tmp_path):
        """Test creating a workflow from template."""
        wf_id = await engine.create_workflow(
            "grid_only",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/test.grd"},
        )
        assert isinstance(wf_id, str)
        assert len(wf_id) > 0

    @pytest.mark.asyncio
    async def test_create_workflow_invalid_template(self, engine, tmp_path):
        """Test creating workflow with invalid template raises ValueError."""
        with pytest.raises(ValueError, match="Unknown workflow template"):
            await engine.create_workflow(
                "nonexistent_template",
                working_dir=tmp_path,
            )

    @pytest.mark.asyncio
    async def test_get_workflow(self, engine, tmp_path):
        """Test getting workflow by ID."""
        wf_id = await engine.create_workflow(
            "grid_only",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/test.grd"},
        )
        await asyncio.sleep(0.5)

        wf = engine.get_workflow(wf_id)
        assert wf is not None
        assert wf.id == wf_id

    @pytest.mark.asyncio
    async def test_get_workflow_nonexistent(self, engine):
        """Test getting nonexistent workflow returns None."""
        assert engine.get_workflow("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_workflows(self, engine, tmp_path):
        """Test listing all workflows."""
        await engine.create_workflow(
            "grid_only",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/test.grd"},
        )
        await asyncio.sleep(0.1)

        workflows = engine.list_workflows()
        assert len(workflows) >= 1

    @pytest.mark.asyncio
    async def test_workflow_completes(self, engine, tmp_path):
        """Test that a workflow runs to completion."""
        wf_id = await engine.create_workflow(
            "grid_only",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/test.grd"},
        )
        # Wait for completion
        for _ in range(50):
            wf = engine.get_workflow(wf_id)
            if wf and not wf.is_active:
                break
            await asyncio.sleep(0.1)

        wf = engine.get_workflow(wf_id)
        assert wf.status == WorkflowStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_workflow_stores_step_results(self, engine, tmp_path):
        """Test that step results are stored."""
        wf_id = await engine.create_workflow(
            "grid_only",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/test.grd"},
        )
        for _ in range(50):
            wf = engine.get_workflow(wf_id)
            if wf and not wf.is_active:
                break
            await asyncio.sleep(0.1)

        wf = engine.get_workflow(wf_id)
        assert "grid_prep" in wf.step_results
        assert "job_id" in wf.step_results["grid_prep"]

    @pytest.mark.asyncio
    async def test_workflow_custom_name(self, engine, tmp_path):
        """Test creating workflow with custom name."""
        wf_id = await engine.create_workflow(
            "grid_only",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/test.grd"},
            name="My Custom Workflow",
        )
        wf = engine.get_workflow(wf_id)
        assert wf.name == "My Custom Workflow"

    @pytest.mark.asyncio
    async def test_cancel_workflow(self, engine, tmp_path, mock_queue):
        """Test cancelling a workflow."""
        # Make jobs take longer
        async def slow_submit(spec):
            job_id = f"slow-job"
            mock_queue._jobs[job_id] = JobInfo(
                id=job_id, name=spec.name, tool_name=spec.tool_name,
                args=spec.args, working_dir=str(spec.working_dir),
                status=JobStatus.RUNNING, created_at=datetime.now(),
            )
            return job_id

        mock_queue.submit = slow_submit

        wf_id = await engine.create_workflow(
            "full_simulation",
            working_dir=tmp_path,
            params={"input_grd": "/tmp/t.grd", "input_str": "/tmp/t.str"},
        )
        await asyncio.sleep(0.1)

        result = await engine.cancel_workflow(wf_id)
        assert result is True

        wf = engine.get_workflow(wf_id)
        assert wf.status == WorkflowStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_workflow(self, engine):
        """Test cancelling nonexistent workflow returns False."""
        result = await engine.cancel_workflow("nonexistent")
        assert result is False


class TestWorkflowInstance:
    """Tests for WorkflowInstance dataclass."""

    def test_is_active(self):
        """Test is_active property."""
        wf = WorkflowInstance(
            id="test", name="Test", steps=[], working_dir="/tmp",
            status=WorkflowStatus.RUNNING,
        )
        assert wf.is_active is True

        wf.status = WorkflowStatus.COMPLETED
        assert wf.is_active is False

    def test_progress(self):
        """Test progress property."""
        steps = [
            WorkflowStep(name="a", tool_name="shypre"),
            WorkflowStep(name="b", tool_name="shyfem"),
        ]
        wf = WorkflowInstance(
            id="test", name="Test", steps=steps, working_dir="/tmp",
            current_step_index=1,
        )
        assert wf.progress == pytest.approx(0.5)

    def test_progress_empty_steps(self):
        """Test progress with no steps."""
        wf = WorkflowInstance(
            id="test", name="Test", steps=[], working_dir="/tmp",
        )
        assert wf.progress == 0.0

    def test_current_step(self):
        """Test current_step property."""
        steps = [
            WorkflowStep(name="a", tool_name="shypre"),
            WorkflowStep(name="b", tool_name="shyfem"),
        ]
        wf = WorkflowInstance(
            id="test", name="Test", steps=steps, working_dir="/tmp",
            current_step_index=1,
        )
        assert wf.current_step.name == "b"

    def test_current_step_out_of_range(self):
        """Test current_step when index is out of range."""
        wf = WorkflowInstance(
            id="test", name="Test", steps=[], working_dir="/tmp",
            current_step_index=5,
        )
        assert wf.current_step is None

    def test_duration(self):
        """Test duration property."""
        wf = WorkflowInstance(
            id="test", name="Test", steps=[], working_dir="/tmp",
            started_at=datetime(2024, 1, 1, 12, 0, 0),
            completed_at=datetime(2024, 1, 1, 12, 5, 0),
        )
        assert wf.duration == pytest.approx(300.0)

    def test_duration_not_completed(self):
        """Test duration when not yet completed."""
        wf = WorkflowInstance(
            id="test", name="Test", steps=[], working_dir="/tmp",
            started_at=datetime.now(),
        )
        assert wf.duration is None


class TestResolveArgs:
    """Tests for WorkflowEngine._resolve_args."""

    def test_simple_param_substitution(self):
        """Test basic {param} substitution."""
        result = WorkflowEngine._resolve_args(
            ["{input_grd}", "-o", "{output}"],
            {"input_grd": "/tmp/test.grd", "output": "/tmp/out"},
            {},
        )
        assert result == ["/tmp/test.grd", "-o", "/tmp/out"]

    def test_step_output_files_substitution(self):
        """Test {step.output_files[N]} substitution."""
        result = WorkflowEngine._resolve_args(
            ["{grid_prep.output_files[0]}"],
            {},
            {"grid_prep": {"output_files": ["/tmp/test.bas"], "output_dir": "/tmp"}},
        )
        assert result == ["/tmp/test.bas"]

    def test_step_output_dir_substitution(self):
        """Test {step.output_dir} substitution."""
        result = WorkflowEngine._resolve_args(
            ["-d", "{grid_prep.output_dir}"],
            {},
            {"grid_prep": {"output_files": [], "output_dir": "/work/dir"}},
        )
        assert result == ["-d", "/work/dir"]

    def test_mixed_substitution(self):
        """Test combined param and step result substitution."""
        result = WorkflowEngine._resolve_args(
            ["-np", "{mpi_np}", "{grid_prep.output_files[0]}"],
            {"mpi_np": "4"},
            {"grid_prep": {"output_files": ["/tmp/grid.bas"], "output_dir": "/tmp"}},
        )
        assert result == ["-np", "4", "/tmp/grid.bas"]

    def test_no_substitution_needed(self):
        """Test args that don't need substitution pass through."""
        result = WorkflowEngine._resolve_args(
            ["-info", "literal_arg"],
            {},
            {},
        )
        assert result == ["-info", "literal_arg"]

    def test_unresolved_placeholders(self):
        """Test that unresolved placeholders remain as-is."""
        result = WorkflowEngine._resolve_args(
            ["{missing_param}"],
            {},
            {},
        )
        assert result == ["{missing_param}"]
