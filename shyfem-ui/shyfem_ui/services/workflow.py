"""Workflow engine for multi-step SHYFEM job chaining.

Supports predefined workflows like:
  Grid Prep -> Partition -> Simulate -> Post-process

Each workflow is a sequence of steps that auto-chain on completion.
Steps can reference outputs from previous steps.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from shyfem_ui.models.workflow import Workflow, WorkflowStatus
from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobSpec, JobStatus


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
    # Whether to continue the workflow if this step fails
    continue_on_failure: bool = False

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON storage."""
        return {
            "name": self.name,
            "tool_name": self.tool_name,
            "args_template": list(self.args_template),
            "mpi_enabled": self.mpi_enabled,
            "mpi_np": self.mpi_np,
            "input_from": self.input_from,
            "continue_on_failure": self.continue_on_failure,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowStep":
        """Deserialize from a plain dict (JSON column read)."""
        return cls(
            name=d["name"],
            tool_name=d["tool_name"],
            args_template=d.get("args_template", []),
            mpi_enabled=d.get("mpi_enabled", False),
            mpi_np=d.get("mpi_np", 1),
            input_from=d.get("input_from"),
            continue_on_failure=d.get("continue_on_failure", False),
        )


@dataclass
class WorkflowInstance:
    """A running workflow instance (in-memory view of a DB row)."""

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
    "offline_tracer": {
        "name": "Offline Tracer Analysis",
        "description": "Run hydrodynamics first (writes offline data), "
                       "then run tracers on saved flow fields",
        "steps": [
            WorkflowStep(
                name="Hydrodynamic run",
                tool_name="shyfem",
                args_template=["{input_str}"],
            ),
            WorkflowStep(
                name="Tracer run",
                tool_name="shyfem",
                args_template=["{input_str_tracer}"],
                input_from="Hydrodynamic run",
            ),
        ],
    },
}


def _parse_dt(value: str | datetime | None) -> datetime | None:
    """Parse an ISO 8601 string or pass through a datetime / None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _row_to_instance(row: Workflow) -> WorkflowInstance:
    """Convert a DB ORM row to a WorkflowInstance dataclass.

    The steps JSON column stores actual WorkflowStep dicts followed by a
    sentinel entry ``{"__meta__": {...}}`` that carries transient runtime
    fields (working_dir, step indices, job IDs, results, etc.).
    """
    steps_raw = row.steps or []
    meta_entry: dict = {}
    clean_steps: list[WorkflowStep] = []
    for s in steps_raw:
        if "__meta__" in s:
            meta_entry = s["__meta__"]
        else:
            clean_steps.append(WorkflowStep.from_dict(s))

    return WorkflowInstance(
        id=str(row.id),
        name=row.name,
        steps=clean_steps,
        working_dir=meta_entry.get("working_dir", ""),
        status=row.status,
        current_step_index=meta_entry.get("current_step_index", 0),
        step_job_ids=meta_entry.get("step_job_ids", {}),
        step_results=meta_entry.get("step_results", {}),
        created_at=row.created_at or datetime.utcnow(),
        started_at=_parse_dt(meta_entry.get("started_at")),
        completed_at=row.completed_at,
        error_message=meta_entry.get("error_message"),
        metadata=meta_entry.get("metadata", {}),
    )


def _pack_steps(wf: "WorkflowInstance") -> list[dict]:
    """Serialize WorkflowInstance state into the steps JSON column.

    The step list is stored as a plain list of dicts. A special sentinel
    entry ``{"__meta__": {...}}`` is appended to carry transient runtime
    fields (working_dir, step results, indices, etc.) that have no dedicated
    columns.
    """
    step_dicts = [s.to_dict() for s in wf.steps]
    # Parse string datetimes back if needed (they come in as datetime objects)
    started_at = wf.started_at.isoformat() if isinstance(wf.started_at, datetime) else wf.started_at
    step_dicts.append({
        "__meta__": {
            "working_dir": wf.working_dir,
            "current_step_index": wf.current_step_index,
            "step_job_ids": wf.step_job_ids,
            "step_results": wf.step_results,
            "started_at": started_at,
            "error_message": wf.error_message,
            "metadata": wf.metadata,
        }
    })
    return step_dicts


class WorkflowEngine:
    """Engine for managing multi-step workflows.

    Coordinates job submission and chaining through a JobQueue.
    All workflow state is persisted to the database; no in-memory cache is kept.
    """

    def __init__(self, job_queue: JobQueue | None = None, session_factory=None):
        self._queue = job_queue
        self._session_factory = session_factory
        self._polling_tasks: dict[str, asyncio.Task] = {}

    def _get_session(self):
        """Open and return a new DB session."""
        if self._session_factory is None:
            from shyfem_ui.db.base import get_session_factory
            factory = get_session_factory()
            return factory()
        return self._session_factory()

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

    async def create_workflow(
        self,
        template_key: str,
        working_dir: Path | str = "",
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
            Workflow ID (as string representation of the DB integer PK)
        """
        template = WORKFLOW_TEMPLATES.get(template_key)
        if not template:
            raise ValueError(f"Unknown workflow template: {template_key}")

        params = params or {}

        # Deep copy steps from template (no options field)
        steps = []
        for step in template["steps"]:
            steps.append(
                WorkflowStep(
                    name=step.name,
                    tool_name=step.tool_name,
                    args_template=list(step.args_template),
                    mpi_enabled=step.mpi_enabled,
                    mpi_np=int(params.get("mpi_np", step.mpi_np)),
                    input_from=step.input_from,
                    continue_on_failure=step.continue_on_failure,
                )
            )

        wf = WorkflowInstance(
            id="",  # will be set after DB insert
            name=name or template["name"],
            steps=steps,
            working_dir=str(working_dir),
            metadata={"template": template_key, "params": params},
        )

        # Persist to DB
        session = self._get_session()
        try:
            row = Workflow(
                name=wf.name,
                template=template_key,
                status=WorkflowStatus.PENDING,
                steps=_pack_steps(wf),
                created_at=wf.created_at,
                updated_at=wf.created_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            wf_id = str(row.id)
        finally:
            session.close()

        # Start execution if we have a queue
        if self._queue is not None:
            task = asyncio.create_task(self._run_workflow(wf_id))
            self._polling_tasks[wf_id] = task

        return wf_id

    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow."""
        session = self._get_session()
        try:
            row = session.query(Workflow).filter(Workflow.id == int(workflow_id)).first()
            if not row:
                return False
            wf = _row_to_instance(row)
            if not wf.is_active:
                return False

            # Cancel current job
            step = wf.current_step
            if step and step.name in wf.step_job_ids and self._queue is not None:
                await self._queue.cancel(wf.step_job_ids[step.name])

            row.status = WorkflowStatus.CANCELLED
            row.completed_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            session.commit()
        finally:
            session.close()

        # Cancel polling task
        task = self._polling_tasks.pop(workflow_id, None)
        if task:
            task.cancel()

        return True

    def get_workflow(self, workflow_id: str) -> WorkflowInstance | None:
        """Get workflow status from DB."""
        session = self._get_session()
        try:
            try:
                pk = int(workflow_id)
            except (ValueError, TypeError):
                return None
            row = session.query(Workflow).filter(Workflow.id == pk).first()
            if row is None:
                return None
            return _row_to_instance(row)
        finally:
            session.close()

    def list_workflows(self, limit: int = 50) -> list[WorkflowInstance]:
        """List all workflows, newest first."""
        session = self._get_session()
        try:
            rows = (
                session.query(Workflow)
                .order_by(Workflow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_instance(r) for r in rows]
        finally:
            session.close()

    def _save_instance(self, wf: WorkflowInstance) -> None:
        """Persist a WorkflowInstance back to DB."""
        session = self._get_session()
        try:
            pk = int(wf.id)
            row = session.query(Workflow).filter(Workflow.id == pk).first()
            if row is None:
                return
            row.status = wf.status
            row.steps = _pack_steps(wf)
            row.updated_at = datetime.utcnow()
            if wf.completed_at:
                row.completed_at = wf.completed_at
            session.commit()
        finally:
            session.close()

    async def _run_workflow(self, workflow_id: str) -> None:
        """Execute workflow steps sequentially."""
        # Load fresh from DB
        wf = self.get_workflow(workflow_id)
        if not wf:
            return

        wf.status = WorkflowStatus.RUNNING
        wf.started_at = datetime.now()
        self._save_instance(wf)

        params = wf.metadata.get("params", {})

        for i, step in enumerate(wf.steps):
            if wf.status != WorkflowStatus.RUNNING:
                break

            wf.current_step_index = i
            self._save_instance(wf)

            # Resolve template arguments
            args = self._resolve_args(step.args_template, params, wf.step_results)

            # Create job spec
            spec = JobSpec(
                name=f"{wf.name}/{step.name}",
                tool_name=step.tool_name,
                args=args,
                working_dir=Path(wf.working_dir) if wf.working_dir else Path("."),
                mpi_enabled=step.mpi_enabled,
                mpi_np=step.mpi_np,
                metadata={"workflow_id": workflow_id, "step": step.name},
            )

            try:
                job_id = await self._queue.submit(spec)
                wf.step_job_ids[step.name] = job_id
                self._save_instance(wf)

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
                self._save_instance(wf)

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
        self._save_instance(wf)
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
