"""Workflow engine for multi-step SHYFEM job chaining.

Supports predefined workflows like:
  Grid Prep -> Partition -> Simulate -> Post-process

Each workflow is a sequence of steps that auto-chain on completion.
Steps can reference outputs from previous steps.
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from shyfem_ui.models.workflow import Workflow, WorkflowStatus
from shyfem_ui.services.job_queue import ORPHANED_ERROR, JobInfo, JobQueue, JobSpec, JobStatus
from shyfem_ui.timeutil import utcnow

logger = logging.getLogger(__name__)

# A workflow in one of these states has an asyncio driver task in THIS process
# (WorkflowEngine._run_workflow). After a restart no such task exists.
_ACTIVE_STATUSES = (WorkflowStatus.PENDING, WorkflowStatus.RUNNING)
# Only these are pruned by retention. PAUSED is deliberately excluded: nothing
# sets it today and it has no job analogue, so it is never deleted (nor
# reconciled) rather than guessing what "paused" should mean.
_TERMINAL_STATUSES = (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED)


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
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Owner and project (DB columns). Every step job carries them so the
    # owner can list, read and cancel the steps and gets the job emails.
    user_id: int | None = None
    project_id: int | None = None

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
        created_at=row.created_at or utcnow(),
        started_at=_parse_dt(meta_entry.get("started_at")),
        completed_at=row.completed_at,
        error_message=meta_entry.get("error_message"),
        metadata=meta_entry.get("metadata", {}),
        user_id=row.user_id,
        project_id=row.project_id,
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
    step_dicts.append(
        {
            "__meta__": {
                "working_dir": wf.working_dir,
                "current_step_index": wf.current_step_index,
                "step_job_ids": wf.step_job_ids,
                "step_results": wf.step_results,
                "started_at": started_at,
                "error_message": wf.error_message,
                "metadata": wf.metadata,
            }
        }
    )
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
        return self._open_session(self._session_factory)

    @staticmethod
    def _open_session(session_factory=None):
        """Open a DB session from ``session_factory`` or the app default."""
        if session_factory is None:
            from shyfem_ui.db.base import get_session_factory

            return get_session_factory()()
        return session_factory()

    @staticmethod
    def _readable_rows(rows, purpose: str) -> dict:
        """Map row.id -> WorkflowInstance, skipping (and logging) any row whose
        JSON cannot be read, so one malformed legacy row cannot stall every
        later reconcile/prune pass."""
        out = {}
        for row in rows:
            try:
                out[row.id] = _row_to_instance(row)
            except Exception:
                logger.warning(
                    "Skipping unreadable workflow row %s during %s", row.id, purpose, exc_info=True
                )
        return out

    @staticmethod
    def _live_job_uuids(session, instances: dict) -> tuple[dict, set]:
        """(row.id -> its step job uuids, the subset still live in ``jobs``).

        Live = PENDING/QUEUED/RUNNING. Checked in the DB, not a queue's
        memory: these run at startup and from maintenance, outside any queue.
        """
        from shyfem_ui.models.project import Job

        job_ids = {
            rid: {str(j) for j in wf.step_job_ids.values() if j} for rid, wf in instances.items()
        }
        wanted = set().union(*job_ids.values()) if job_ids else set()
        if not wanted:
            return job_ids, set()
        live_statuses = (JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING)
        live = {
            uuid
            for (uuid,) in session.query(Job.job_uuid)
            .filter(Job.job_uuid.in_(wanted))
            .filter(Job.status.in_(live_statuses))
        }
        return job_ids, live

    @staticmethod
    def reconcile_orphaned_workflows(session_factory=None) -> int:
        """Mark workflow rows a previous process left active as FAILED.

        A workflow is driven by an asyncio task (``_run_workflow``) living in
        the web process -- in BOTH queue modes, since even under Celery the
        step chaining happens here. A PENDING/RUNNING row found at process
        start therefore has no driver and would otherwise stay "active"
        forever (and be immune to retention). Same reconciliation as jobs
        (N46, ``LocalJobQueue._load_history_from_db``): status FAILED, error
        ``ORPHANED_ERROR``, ``completed_at`` stamped if unset (UTC, like every
        workflow timestamp). The step job itself is NOT cancelled: if it is
        genuinely alive (a Celery worker) it finishes on its own and the job
        queue tracks it.

        Must run ONCE PER PROCESS, before any workflow is started (it is
        called from ``create_app``). Never call it from ``__init__``:
        pages/run.py builds one engine per Shiny session, so a second session
        would kill a live workflow belonging to the first.

        A row whose step job is still live (PENDING/QUEUED/RUNNING in
        ``jobs``) is left alone: a ``restart.txt`` deploy starts a new process
        while the old one keeps serving its sessions and driving their
        workflows, and marking those FAILED would misreport them (and refuse
        cancel) for the whole running step. A truly orphaned one is caught at
        a later start, once its job row is terminal.

        Best-effort: returns the number of rows reconciled, 0 on any DB error.
        """
        try:
            session = WorkflowEngine._open_session(session_factory)
        except Exception:
            logger.warning("Could not open DB to reconcile workflows", exc_info=True)
            return 0
        try:
            rows = session.query(Workflow).filter(Workflow.status.in_(_ACTIVE_STATUSES)).all()
            instances = WorkflowEngine._readable_rows(rows, "startup reconciliation")
            job_ids, live = WorkflowEngine._live_job_uuids(session, instances)
            now = utcnow()
            done = 0
            for row in rows:
                wf = instances.get(row.id)
                if wf is None or job_ids[row.id] & live:
                    continue
                wf.error_message = ORPHANED_ERROR
                row.status = WorkflowStatus.FAILED
                row.steps = _pack_steps(wf)
                row.updated_at = now
                if row.completed_at is None:
                    row.completed_at = now
                done += 1
            if done:
                session.commit()
                logger.warning(
                    "Reconciled %d phantom active workflow row(s) to FAILED at startup", done
                )
            return done
        except Exception:
            session.rollback()
            logger.warning("Could not reconcile orphaned workflows", exc_info=True)
            return 0
        finally:
            session.close()

    @staticmethod
    def cleanup_old_workflows(days: int, session_factory=None) -> int:
        """Delete finished workflow rows older than ``days``; return the count.

        The workflow analogue of ``JobQueue.cleanup_old_jobs`` and run with
        the same ``job_retention_days`` by maintenance. Only COMPLETED /
        FAILED / CANCELLED rows are candidates; age is ``completed_at``, or
        ``created_at`` when a finished row has no ``completed_at``. All
        workflow timestamps are naive UTC, so one ``utcnow()`` cutoff fits.

        A candidate is kept while any of its step jobs is still live
        (PENDING/QUEUED/RUNNING in the ``jobs`` table): a workflow can end
        FAILED/CANCELLED while the job it submitted keeps running.

        Synchronous DB work -- call it via ``asyncio.to_thread``. Best-effort:
        returns 0 on any DB error.
        """
        from sqlalchemy import and_, or_

        cutoff = utcnow() - timedelta(days=days)
        try:
            session = WorkflowEngine._open_session(session_factory)
        except Exception:
            logger.error("Could not open DB to prune old workflows", exc_info=True)
            return 0
        try:
            candidates = (
                session.query(Workflow)
                .filter(Workflow.status.in_(_TERMINAL_STATUSES))
                .filter(
                    or_(
                        and_(Workflow.completed_at.isnot(None), Workflow.completed_at < cutoff),
                        and_(Workflow.completed_at.is_(None), Workflow.created_at < cutoff),
                    )
                )
                .all()
            )
            # An unreadable row is kept, not guessed at: we cannot tell
            # whether it still references a live job.
            instances = WorkflowEngine._readable_rows(candidates, "retention pruning")
            job_ids, live = WorkflowEngine._live_job_uuids(session, instances)
            doomed = [rid for rid in instances if not (job_ids[rid] & live)]
            if doomed:
                session.query(Workflow).filter(Workflow.id.in_(doomed)).delete(
                    synchronize_session=False
                )
                session.commit()
            return len(doomed)
        except Exception:
            session.rollback()
            logger.error("DB cleanup of old workflow rows failed", exc_info=True)
            return 0
        finally:
            session.close()

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

    async def create_workflow(
        self,
        template_key: str,
        working_dir: Path | str = "",
        params: dict[str, str] | None = None,
        name: str | None = None,
        user_id: int | None = None,
        project_id: int | None = None,
    ) -> str:
        """Create and start a workflow from a template.

        Args:
            template_key: Key into WORKFLOW_TEMPLATES
            working_dir: Working directory for all steps
            params: Template parameter values like {"input_grd": "/path/to/file.grd",
                    "input_str": "/path/to/file.str", "mpi_np": "4"}
            name: Custom workflow name
            user_id: Owner (server-validated identity's id); scopes listings
            project_id: Project the workflow was launched from

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
                user_id=user_id,
                project_id=project_id,
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
            row.completed_at = utcnow()
            row.updated_at = utcnow()
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

    def list_workflows(self, limit: int = 50, user_id: int | None = None) -> list[WorkflowInstance]:
        """List workflows newest first; only ``user_id``'s when given.

        Callers in server mode go through ``run_logic.list_scoped_workflows``,
        which decides the ``user_id`` from the server-validated identity.
        """
        session = self._get_session()
        try:
            query = session.query(Workflow)
            if user_id is not None:
                query = query.filter(Workflow.user_id == user_id)
            rows = query.order_by(Workflow.created_at.desc()).limit(limit).all()
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
            if row.status == WorkflowStatus.CANCELLED and wf.status != WorkflowStatus.CANCELLED:
                # Cancelled meanwhile, possibly by another session's engine,
                # which cannot stop this driver task (J-05): keep CANCELLED
                # and let the driver see it, never overwrite it with
                # RUNNING / FAILED / COMPLETED.
                wf.status = WorkflowStatus.CANCELLED
            row.status = wf.status
            row.steps = _pack_steps(wf)
            row.updated_at = utcnow()
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
        wf.started_at = utcnow()
        self._save_instance(wf)

        params = wf.metadata.get("params", {})

        for i, step in enumerate(wf.steps):
            if wf.status != WorkflowStatus.RUNNING:
                break

            wf.current_step_index = i
            self._save_instance(wf)

            try:
                # Inside the try: an unresolvable argument (a previous step
                # produced no output) must fail the step and the workflow,
                # not escape the driver task and leave the row RUNNING.
                args = self._resolve_args(step.args_template, params, wf.step_results)

                # The owner and project ride on every step job exactly as on a
                # directly submitted job (run_logic._get_job_metadata): job
                # listing, cancel authorization and notifications read them.
                metadata: dict[str, Any] = {"workflow_id": workflow_id, "step": step.name}
                if wf.user_id is not None:
                    metadata["user_id"] = wf.user_id
                if wf.project_id is not None:
                    metadata["project_id"] = wf.project_id

                spec = JobSpec(
                    name=f"{wf.name}/{step.name}",
                    tool_name=step.tool_name,
                    args=args,
                    working_dir=Path(wf.working_dir) if wf.working_dir else Path("."),
                    mpi_enabled=step.mpi_enabled,
                    mpi_np=step.mpi_np,
                    metadata=metadata,
                )

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

                if wf.status != WorkflowStatus.RUNNING:
                    break  # the workflow was cancelled while this step ran
                if job_info and job_info.status == JobStatus.CANCELLED:
                    wf.status = WorkflowStatus.CANCELLED
                    wf.error_message = f"Step '{step.name}' was cancelled"
                    break
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

        wf.completed_at = utcnow()
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

        # Any leftover {step.output_dir} / {step.output_files[N]} reference means
        # a prior step it depends on produced no (such) output. Fail clearly here
        # instead of handing the literal token to the next tool as a filename.
        _STEP_REF = re.compile(r"\{[A-Za-z_]\w*\.output_(?:dir|files(?:\[\d+\])?)\}")
        unresolved = sorted({m for v in resolved for m in _STEP_REF.findall(v)})
        if unresolved:
            raise ValueError(
                "Unresolved workflow step reference(s): "
                + ", ".join(unresolved)
                + " — a previous step produced no matching output."
            )
        return resolved
