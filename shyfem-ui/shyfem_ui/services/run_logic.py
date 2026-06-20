"""Pure-logic helpers for the Run page.

Extracted from `pages/run.py` for unit-testability. The page module
re-exports each name at the same import path so existing tests
(test_run_helpers, test_run_validation, test_job_ownership,
test_pages_helpers) continue to work without modification.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from shiny import ui

from shyfem_ui.services.job_queue import JobInfo, JobSpec, JobStatus
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.parser_str import StrParser

logger = logging.getLogger(__name__)


def _preflight_validate(simulation_id: int | None) -> list[str]:
    """Run pre-flight file validation for a simulation.

    Returns list of warning strings. Empty = all OK.
    Returns empty list for None or invalid simulation IDs (non-blocking).
    """
    if simulation_id is None:
        return []
    try:
        from shyfem_ui.services.file_service import FileService

        return FileService.validate_simulation_files(simulation_id)
    except ValueError:
        # Simulation not found / invalid id — nothing to validate (non-blocking).
        return []
    except Exception:
        # A real validator failure must NOT look identical to "all clean".
        logger.warning(
            "Pre-flight validation failed for simulation %s", simulation_id, exc_info=True
        )
        return ["Pre-flight validation could not be completed — see logs."]


def _get_job_metadata(
    session_id: str, user_id: int | None = None, project_id: int | None = None
) -> dict:
    """Build job metadata dict with session_id and optional user_id/project_id.

    ``user_id`` (owner) and ``project_id`` are the basis for cancel
    authorization (job_cancel_denied_reason): the owner, an admin, or a
    project-editor may cancel the job.
    """
    meta = {"session_id": session_id}
    if user_id is not None:
        meta["user_id"] = user_id
    if project_id is not None:
        meta["project_id"] = project_id
    return meta


def get_solver_recommendation(num_nodes: int | None, threshold: int) -> dict[str, str | None]:
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


def detect_mesh_node_count(str_file: Path | str, working_dir: Path | str) -> int | None:
    """Detect mesh node count from the grid file referenced in a STR file.

    The STR $title section's 3rd non-empty line is the basin name (e.g. 'GRID/MM_coarse').
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
        logger.debug("Failed to parse STR file %s", str_path, exc_info=True)
        return None

    title_sec = parsed.sections.get("title")
    if title_sec is None or len(title_sec.raw_lines) < 3:
        return None

    # 3rd non-empty, non-comment line in $title is the basin name
    lines = [
        ln.strip()
        for ln in title_sec.raw_lines
        if ln.strip() and not ln.strip().startswith(("#", "!"))
    ]
    if len(lines) < 3:
        return None
    basnam = lines[2]

    # Try .grd then .bas extension. basnam is attacker-influenced STR content,
    # so reject a joined path that escapes working_dir (defense-in-depth; the
    # caller also confines working_dir to the user's sandbox).
    work_root = work_path.resolve()
    for ext in (".grd", ".bas"):
        grid_path = (work_root / f"{basnam}{ext}").resolve()
        if grid_path != work_root and not str(grid_path).startswith(str(work_root) + "/"):
            continue
        if grid_path.exists():
            try:
                grd = GrdParser.parse_file(grid_path)
                return grd.num_nodes
            except Exception:
                logger.debug("Failed to parse grid file %s", grid_path, exc_info=True)
                continue

    return None


def _stat_card(label: str, value: str, bg_class: str) -> ui.Tag:
    """Create a small stat card."""
    return ui.div(
        ui.span(value, class_="fs-4 fw-bold"),
        ui.br(),
        ui.span(label, class_="small"),
        class_=f"text-center text-white px-3 py-2 rounded {bg_class}",
        style="min-width: 80px;",
    )


def _estimate_eta(job: JobInfo) -> str:
    """Estimate time remaining for a running job."""
    if job.status != JobStatus.RUNNING or not job.started_at:
        return ""
    if job.progress <= 0:
        return "calculating..."

    elapsed = (datetime.now() - job.started_at).total_seconds()
    if elapsed <= 0:
        return ""

    estimated_total = elapsed / job.progress
    remaining = estimated_total - elapsed

    if remaining < 60:
        return f"{int(remaining)}s"
    elif remaining < 3600:
        return f"{int(remaining // 60)}m {int(remaining % 60)}s"
    else:
        h = int(remaining // 3600)
        m = int((remaining % 3600) // 60)
        return f"{h}h {m}m"


def build_job_spec(
    *,
    name: str,
    tool_name: str,
    validated_input: Path,
    validated_workdir: Path,
    mpi_enabled: bool = False,
    mpi_np: int = 1,
    solver: str | None = None,
    session_id: str,
    user_id: int | None = None,
    project_id: int | None = None,
    restart_from: str | None = None,
    depends_on: str | None = None,
) -> JobSpec:
    """Build a JobSpec from the validated user inputs.

    Pure: no Shiny imports, no reactive state, no I/O. Caller passes
    pre-validated paths and config values; this function assembles
    them into a JobSpec with appropriate metadata.

    Args:
        name: Human-readable job name.
        tool_name: SHYFEM tool to invoke (shyfem, shyelab, etc.).
        validated_input: Validated path to the input file.
        validated_workdir: Validated working directory.
        mpi_enabled: Whether to launch via mpirun (only for tool="shyfem").
        mpi_np: Number of MPI processes (only used when mpi_enabled).
        solver: "petsc" or "sparskit" or None. petsc is recorded in metadata.
        session_id: Session ID for ownership tracking.
        user_id: User ID for ownership tracking (None in local mode).
        project_id: Active project ID, basis for cancel authorization (None when
            no project is active).
        restart_from: Optional restart file path (recorded in metadata).
        depends_on: Optional parent job ID (recorded in metadata).

    Returns:
        JobSpec ready for queue.submit().
    """
    metadata = _get_job_metadata(session_id, user_id, project_id)
    if solver == "petsc":
        metadata["solver"] = "petsc"
    if restart_from:
        metadata["restart_file"] = restart_from
    if depends_on:
        metadata["depends_on"] = depends_on
    return JobSpec(
        name=name,
        tool_name=tool_name,
        args=[str(validated_input)],
        working_dir=validated_workdir,
        mpi_enabled=mpi_enabled and tool_name == "shyfem",
        mpi_np=mpi_np if (mpi_enabled and tool_name == "shyfem") else 1,
        metadata=metadata,
    )
