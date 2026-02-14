"""Workflow engine for multi-step SHYFEM job chaining.

Supports predefined workflows like:
  Grid Prep -> Partition -> Simulate -> Post-process

Each workflow is a sequence of steps that auto-chain on completion.
Steps can reference outputs from previous steps.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobSpec, JobStatus


class WorkflowStatus(Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    name: str
    tool_name: str
    args_template: list[str] = field(default_factory=list)
    mpi_enabled: bool = False
    mpi_np: int = 1
    # Reference previous step outputs: "{step_name.output_dir}" or "{step_name.output_files[0]}"
    input_from: str | None = None
    # Additional options passed to the tool
    options: list[str] = field(default_factory=list)
    # Whether to continue the workflow if this step fails
    continue_on_failure: bool = False


@dataclass
class WorkflowInstance:
    """A running workflow instance."""
    id: str
    name: str
    steps: list[WorkflowStep]
    working_dir: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step_index: int = 0
    step_job_ids: dict[str, str] = field(default_factory=dict)  # step_name -> job_id
    step_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.status in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING)

    @property
    def progress(self) -> float:
        if not self.steps:
            return 0.0
        return self.current_step_index / len(self.steps)

    @property
    def current_step(self) -> WorkflowStep | None:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    @property
    def duration(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


# Predefined workflow templates
WORKFLOW_TEMPLATES = {
    "full_simulation": {
        "name": "Full Simulation Pipeline",
        "description": "Grid Prep -> Partition -> Simulate -> Post-process",
        "steps": [
            WorkflowStep(
                name="grid_prep",
                tool_name="shypre",
                args_template=["{input_grd}"],
            ),
            WorkflowStep(
                name="partitioning",
                tool_name="shyparts",
                args_template=["-np", "{mpi_np}", "{grid_prep.output_files[0]}"],
            ),
            WorkflowStep(
                name="simulation",
                tool_name="shyfem",
                args_template=["{input_str}"],
                mpi_enabled=True,
                mpi_np=4,
            ),
            WorkflowStep(
                name="postprocess",
                tool_name="shyelab",
                args_template=["-split", "{simulation.output_files[0]}"],
            ),
        ],
    },
    "grid_only": {
        "name": "Grid Preparation",
        "description": "Grid Prep -> Basin Analysis",
        "steps": [
            WorkflowStep(
                name="grid_prep",
                tool_name="shypre",
                args_template=["{input_grd}"],
            ),
            WorkflowStep(
                name="basin_analysis",
                tool_name="shybas",
                args_template=["-quality", "-grd", "{grid_prep.output_files[0]}"],
            ),
        ],
    },
    "simulation_postprocess": {
        "name": "Simulate + Post-process",
        "description": "Simulate -> Post-process -> Plot",
        "steps": [
            WorkflowStep(
                name="simulation",
                tool_name="shyfem",
                args_template=["{input_str}"],
                mpi_enabled=True,
                mpi_np=4,
            ),
            WorkflowStep(
                name="postprocess",
                tool_name="shyelab",
                args_template=["-split", "{simulation.output_files[0]}"],
            ),
        ],
    },
}


class WorkflowEngine:
    """Engine for managing multi-step workflows.

    Coordinates job submission and chaining through a JobQueue.
    """

    def __init__(self, job_queue: JobQueue):
        self._queue = job_queue
        self._workflows: dict[str, WorkflowInstance] = {}
        self._polling_tasks: dict[str, asyncio.Task] = {}

    def list_templates(self) -> dict[str, dict]:
        """List available workflow templates."""
        return {
            key: {"name": tpl["name"], "description": tpl["description"],
                   "steps": [s.name for s in tpl["steps"]]}
            for key, tpl in WORKFLOW_TEMPLATES.items()
        }

    async def create_workflow(
        self,
        template_key: str,
        working_dir: Path | str,
        params: dict[str, str] | None = None,
        name: str | None = None,
    ) -> str:
        """Create and start a workflow from a template.

        Args:
            template_key: Key into WORKFLOW_TEMPLATES
            working_dir: Working directory for all steps
            params: Template parameter values like {"input_grd": "/path/to/file.grd",
                    "input_str": "/path/to/file.str", "mpi_np": "4"}
            name: Custom workflow name

        Returns:
            Workflow ID
        """
        template = WORKFLOW_TEMPLATES.get(template_key)
        if not template:
            raise ValueError(f"Unknown workflow template: {template_key}")

        wf_id = str(uuid.uuid4())
        params = params or {}

        # Deep copy steps from template
        steps = []
        for step in template["steps"]:
            steps.append(WorkflowStep(
                name=step.name,
                tool_name=step.tool_name,
                args_template=list(step.args_template),
                mpi_enabled=step.mpi_enabled,
                mpi_np=int(params.get("mpi_np", step.mpi_np)),
                input_from=step.input_from,
                options=list(step.options),
                continue_on_failure=step.continue_on_failure,
            ))

        wf = WorkflowInstance(
            id=wf_id,
            name=name or template["name"],
            steps=steps,
            working_dir=str(working_dir),
            metadata={"template": template_key, "params": params},
        )
        self._workflows[wf_id] = wf

        # Start execution
        task = asyncio.create_task(self._run_workflow(wf_id))
        self._polling_tasks[wf_id] = task

        return wf_id

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow."""
        wf = self._workflows.get(workflow_id)
        if not wf or not wf.is_active:
            return False

        wf.status = WorkflowStatus.CANCELLED
        wf.completed_at = datetime.now()

        # Cancel current job
        step = wf.current_step
        if step and step.name in wf.step_job_ids:
            await self._queue.cancel(wf.step_job_ids[step.name])

        # Cancel polling task
        task = self._polling_tasks.pop(workflow_id, None)
        if task:
            task.cancel()

        return True

    def get_workflow(self, workflow_id: str) -> WorkflowInstance | None:
        """Get workflow status."""
        return self._workflows.get(workflow_id)

    def list_workflows(self, limit: int = 50) -> list[WorkflowInstance]:
        """List all workflows, newest first."""
        workflows = list(self._workflows.values())
        workflows.sort(key=lambda w: w.created_at, reverse=True)
        return workflows[:limit]

    async def _run_workflow(self, workflow_id: str) -> None:
        """Execute workflow steps sequentially."""
        wf = self._workflows.get(workflow_id)
        if not wf:
            return

        wf.status = WorkflowStatus.RUNNING
        wf.started_at = datetime.now()

        params = wf.metadata.get("params", {})

        for i, step in enumerate(wf.steps):
            if wf.status != WorkflowStatus.RUNNING:
                break

            wf.current_step_index = i

            # Resolve template arguments
            args = self._resolve_args(step.args_template, params, wf.step_results)

            # Create job spec
            spec = JobSpec(
                name=f"{wf.name}/{step.name}",
                tool_name=step.tool_name,
                args=args,
                working_dir=Path(wf.working_dir),
                mpi_enabled=step.mpi_enabled,
                mpi_np=step.mpi_np,
                metadata={"workflow_id": workflow_id, "step": step.name},
            )

            try:
                job_id = await self._queue.submit(spec)
                wf.step_job_ids[step.name] = job_id

                # Poll until job completes
                job_info = await self._wait_for_job(job_id)

                # Store result
                wf.step_results[step.name] = {
                    "job_id": job_id,
                    "status": job_info.status.value if job_info else "unknown",
                    "output_files": job_info.output_files if job_info else [],
                    "output_dir": wf.working_dir,
                    "return_code": job_info.return_code if job_info else -1,
                }

                if job_info and job_info.status != JobStatus.COMPLETED:
                    if not step.continue_on_failure:
                        wf.status = WorkflowStatus.FAILED
                        wf.error_message = (
                            f"Step '{step.name}' failed: "
                            f"{job_info.error_message or 'non-zero exit code'}"
                        )
                        break

            except asyncio.CancelledError:
                wf.status = WorkflowStatus.CANCELLED
                break
            except Exception as e:
                wf.status = WorkflowStatus.FAILED
                wf.error_message = f"Step '{step.name}' error: {e}"
                break

        if wf.status == WorkflowStatus.RUNNING:
            wf.status = WorkflowStatus.COMPLETED
            wf.current_step_index = len(wf.steps)

        wf.completed_at = datetime.now()
        self._polling_tasks.pop(workflow_id, None)

    async def _wait_for_job(self, job_id: str, poll_interval: float = 2.0) -> JobInfo | None:
        """Poll job queue until job completes."""
        while True:
            job_info = await self._queue.get_status(job_id)
            if job_info is None:
                return None
            if not job_info.is_active:
                return job_info
            await asyncio.sleep(poll_interval)

    @staticmethod
    def _resolve_args(
        templates: list[str],
        params: dict[str, str],
        step_results: dict[str, dict[str, Any]],
    ) -> list[str]:
        """Resolve template argument strings.

        Supports:
        - {param_name} - direct parameter substitution
        - {step_name.output_files[0]} - reference step output files
        - {step_name.output_dir} - reference step working directory
        """
        resolved = []
        for tmpl in templates:
            val = tmpl
            # Simple param substitution: {key}
            for key, value in params.items():
                val = val.replace(f"{{{key}}}", str(value))

            # Step result substitution: {step_name.field} or {step_name.output_files[N]}
            for step_name, result in step_results.items():
                val = val.replace(f"{{{step_name}.output_dir}}", str(result.get("output_dir", "")))
                output_files = result.get("output_files", [])
                # Replace indexed references
                for idx, fpath in enumerate(output_files):
                    val = val.replace(f"{{{step_name}.output_files[{idx}]}}", fpath)
                # Replace general reference with first file
                if output_files:
                    val = val.replace(f"{{{step_name}.output_files}}", output_files[0])

            resolved.append(val)
        return resolved
