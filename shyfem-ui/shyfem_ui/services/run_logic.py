"""Pure-logic helpers for the Run page.

Extracted from `pages/run.py` for unit-testability. The page module
re-exports each name at the same import path so existing tests
(test_run_helpers, test_run_validation, test_job_ownership,
test_pages_helpers) continue to work without modification.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from shiny import ui

from shyfem_ui.services.job_queue import JobInfo, JobQueue, JobSpec, JobStatus
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


async def list_scoped_jobs(
    job_queue: JobQueue,
    is_server_mode: bool,
    current_user_fn: Callable[[], dict | None] | None,
    show_all_fn: Callable[[], bool] | None = None,
    limit: int = 100,
) -> list[JobInfo]:
    """Server-validated, per-user job listing (F17 completion).

    Extracted from pages/run.py's ``_list_scoped_jobs`` (Batch 3) so every
    listing site -- Run, Dashboard, Compare, and the cross-page notification
    poll -- scopes the SAME way instead of maintaining independent copies
    that can silently drift apart. Scopes by the server-validated user
    identity's id, NEVER ``session_id`` (ephemeral per-WS-connection; does
    not track ownership across reconnects/tabs, so a user's own jobs would
    drop off after reconnect and CPython id() reuse could surface a prior
    user's job metadata) nor any client-pushed signal (e.g.
    ``input.current_user_role()``).

    Fail-closed: an unresolved identity in server mode (``current_user_fn``
    is None, or calling it returns None) returns no jobs rather than
    falling through to session_id scoping or an unfiltered list. Local
    (single-user) mode is always unfiltered.

    Args:
        job_queue: The queue to list from.
        is_server_mode: config.deployment_mode == "server".
        current_user_fn: Zero-arg callable returning the server-validated
            user dict (or None) -- e.g. the ``current_user`` closure every
            page server already receives, never a client-pushed value.
        show_all_fn: Optional zero-arg callable for the caller's
            *requested* scope (e.g. a "show all jobs" toggle), called only
            once identity is confirmed (mirrors the original call order so
            it is never evaluated before an unresolved-input input.*() call
            would be safe). Downgraded to the caller's own jobs unless the
            resolved identity is an admin (IDOR guard). Callers with no
            separate toggle (e.g. Compare) can pass a callable that always
            returns True to mean "all jobs when admin, own jobs otherwise".
        limit: Max jobs to return.
    """
    if not is_server_mode:
        return await job_queue.list_jobs(limit=limit)

    from shyfem_ui.models.user import ROLE_ADMIN

    usr = current_user_fn() if current_user_fn is not None else None
    if usr is None:
        return []

    requested_show_all = bool(show_all_fn()) if show_all_fn is not None else False
    show_all = requested_show_all and usr.get("role") == ROLE_ADMIN
    uid = None if show_all else usr["id"]
    return await job_queue.list_jobs(limit=limit, user_id=uid)


def list_scoped_workflows(
    workflow_engine,
    is_server_mode: bool,
    current_user_fn: Callable[[], dict | None] | None,
    show_all_fn: Callable[[], bool] | None = None,
    limit: int = 10,
) -> list:
    """Per-user workflow listing, scoped exactly like :func:`list_scoped_jobs`.

    The workflow history used to list every user's workflows to everyone
    (``create_workflow`` recorded no owner). Local mode is unfiltered; in
    server mode an unresolved identity sees nothing (no query is issued),
    a user sees their own, and only an admin who asks for it sees all --
    including rows created before owners were recorded (``user_id`` NULL),
    which no non-admin can match.
    """
    if not is_server_mode:
        return workflow_engine.list_workflows(limit=limit)

    from shyfem_ui.models.user import ROLE_ADMIN

    usr = current_user_fn() if current_user_fn is not None else None
    if usr is None:
        return []

    requested_show_all = bool(show_all_fn()) if show_all_fn is not None else False
    show_all = requested_show_all and usr.get("role") == ROLE_ADMIN
    return workflow_engine.list_workflows(limit=limit, user_id=None if show_all else usr["id"])


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
        restart_from: Optional restart file path, recorded in metadata for
            display/audit. This does NOT itself make the run continue from
            it -- the caller must apply it to the STR beforehand (see
            write_restart_str) and pass the derived file as validated_input;
            otherwise the run silently starts fresh (N42).

    Returns:
        JobSpec ready for queue.submit().
    """
    metadata = _get_job_metadata(session_id, user_id, project_id)
    if solver == "petsc":
        metadata["solver"] = "petsc"
    if restart_from:
        metadata["restart_file"] = restart_from
    return JobSpec(
        name=name,
        tool_name=tool_name,
        args=[str(validated_input)],
        working_dir=validated_workdir,
        mpi_enabled=mpi_enabled and tool_name == "shyfem",
        mpi_np=mpi_np if (mpi_enabled and tool_name == "shyfem") else 1,
        metadata=metadata,
    )


# SHYFEM date strings as the STR writes them: '1993-02-01' or '1993-02-01::12:00:00'.
_STR_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:::(\d{2}):(\d{2}):(\d{2}))?$")


def _str_date(value) -> datetime | None:
    """A STR date string as a datetime, or None when it is not one."""
    m = _STR_DATE.match(str(value).strip().strip("'\""))
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(g) if g else 0 for g in m.groups())
    try:
        return datetime(y, mo, d, hh, mm, ss)
    except ValueError:
        return None


def _continuation_name(runnam: str, dest_dir: Path) -> str:
    """``<runnam>_c<n>`` with the first n no output in ``dest_dir`` uses."""
    n = 1
    while any(dest_dir.glob(f"{runnam}_c{n}.*")):
        n += 1
    return f"{runnam}_c{n}"


def write_restart_str(
    str_path: Path, restart_file: str, dest_dir: Path, continue_until: str
) -> Path:
    """Write the STR that continues a finished run from its restart file.

    It follows the shipped working pair
    ``testcases/examples/weutro_box/eco_rst_part{1,2}.str``:

    * a NEW run name (``$title`` line 2, ``<runnam>_c<n>``): every output is
      ``<runnam>.<ext>`` in the working folder, so keeping the name truncated
      the source run's own ``.rst``/``.shy`` -- including the file this run
      restarts from (J-02);
    * ``itanf`` = the source's ``itend`` (the restart time) and ``itend`` =
      ``continue_until``; the unchanged ``itend`` gave a zero-step run (R-03);
    * ``restrt`` relative to the working folder when the file is inside it
      (an absolute path can break the core's 80-character line cap), and
      ``itrst = -1`` (read the last record; without it the core stops on
      "Cannot find time record");
    * the derived STR is validated like any submitted STR and refused, with
      nothing written, if the core would reject it.

    ``str_path`` is only read. ``dest_dir`` must already be confined by the
    caller (this writes into it).

    Raises:
        FileNotFoundError: restart_file does not exist.
        ValueError: continue_until missing/invalid/not after the restart
            time, the source has no run name, or the derived STR is invalid.
    """
    from shyfem_ui.services.str_validator import validate_str

    if not Path(restart_file).exists():
        raise FileNotFoundError(f"Restart file not found: {restart_file}")
    until = (continue_until or "").strip()
    until_dt = _str_date(until)
    if until_dt is None:
        raise ValueError(
            "Enter 'Continue until' as a date, e.g. 2002-01-01 or 2002-01-01::12:00:00"
        )

    base_str = StrParser.parse_file(str_path)
    restart_at = base_str.get_param("para", "itend")
    restart_dt = _str_date(restart_at) if restart_at is not None else None
    if restart_dt is not None and until_dt <= restart_dt:
        raise ValueError(
            f"'Continue until' ({until}) must be after the end of the run it continues "
            f"({str(restart_at).strip(chr(39))})"
        )

    title = base_str.sections.get("title")
    lines = [i for i, line in enumerate(title.raw_lines) if line.strip()] if title else []
    if len(lines) < 2:
        raise ValueError("The STR has no run name ($title line 2) to continue from")
    k = lines[1]
    old = title.raw_lines[k]
    runnam = old.strip()
    dest_dir = Path(dest_dir)
    title.raw_lines[k] = old[: len(old) - len(old.lstrip())] + _continuation_name(runnam, dest_dir)

    try:
        restrt = str(Path(restart_file).resolve().relative_to(dest_dir.resolve()))
    except ValueError:
        restrt = str(restart_file)
    # Pre-quoting keeps the value verbatim; StrParser strips the quotes on read.
    base_str.set_param("name", "restrt", f"'{restrt}'")
    base_str.set_param("para", "itrst", -1)
    if restart_at is not None:
        base_str.set_param("para", "itanf", restart_at)
    base_str.set_param("para", "itend", f"'{until}'")

    text = StrParser.generate(base_str)
    derived = StrParser.parse(text)
    errors = [m.message for m in validate_str(derived.sections) if m.level == "error"]
    if errors:
        raise ValueError("The continuation STR would not run: " + "; ".join(errors))

    # A uuid suffix keeps two continuations of one STR from colliding.
    derived_name = f"{str_path.stem}_restart_{uuid4().hex[:8]}{str_path.suffix}"
    derived_path = dest_dir / derived_name
    derived_path.write_text(text)
    return derived_path


def compute_restart_choices(jobs: list[JobInfo]) -> dict[str, str]:
    """Compute the restart-file choice set {absolute .rst path: label} from
    a list of jobs.

    This is the SINGLE source of truth for "which restart files may a
    submission legitimately reference": pages/run.py's restart_section
    calls it to render the "Continue from job" dropdown, and
    restart_selection_denied_reason calls it again server-side at submit
    time to build the allowlist a submitted restart_from is checked
    against. Sharing one function guarantees the dropdown and the
    allowlist can never silently drift apart.

    The caller is responsible for scoping `jobs` to what the current
    identity may see (see pages/run.py's _list_scoped_jobs: own jobs only
    for a non-admin, unscoped for admin + "show all" or local mode) --
    this function does no access-control itself, it only picks the latest
    .rst per completed shyfem job out of whatever list it's given.
    """
    choices: dict[str, str] = {}
    for job in jobs:
        if job.tool_name != "shyfem" or job.status != JobStatus.COMPLETED:
            continue
        work_dir = Path(job.working_dir)
        rst_files = sorted(work_dir.glob("*.rst"))
        if rst_files:
            choices[str(rst_files[-1])] = f"{job.name} ({rst_files[-1].name})"
    return choices


def restart_selection_denied_reason(restart_from: str | None, jobs: list[JobInfo]) -> str | None:
    """Server-side allowlist check for a submitted restart_from (N42 IDOR
    follow-up).

    restart_from is a client-controlled `input.restart_from()` value.
    Before this task it was inert (recorded in job metadata only); now
    write_restart_str actually opens the file it names and folds it into
    the STR the SHYFEM worker executes -- which makes a spoofed WS message
    (bypassing the "Continue from job" dropdown entirely, e.g. via the
    browser devtools or a crafted websocket frame) a real path-disclosure
    risk: an attacker could point restart_from at another user's .rst file.

    A bare confine_path check is NOT the right guard here: the admin
    "show all jobs" toggle legitimately lets an admin select a restart file
    outside their own sandbox, which confine_path would incorrectly reject.
    The correct guard is an allowlist -- restart_from must be exactly one
    of the paths compute_restart_choices() derives from the SAME
    already-scoped jobs list the dropdown itself was built from (own jobs
    only for non-admin; unscoped for admin+show-all or local mode, per
    pages/run.py's _list_scoped_jobs).

    Returns:
        None if restart_from is falsy (no restart requested -- nothing to
        check) or matches a computed choice. Otherwise a user-facing error
        string; the caller must show it and abort BEFORE write_restart_str
        or job submission run.
    """
    if not restart_from:
        return None
    if restart_from in compute_restart_choices(jobs):
        return None
    return (
        "Restart file is not a valid selection for your account -- "
        "choose one from the Continue from job dropdown."
    )


def restart_info_text(restart_from: str | None, jobs: list[JobInfo]) -> str | None:
    """Gated display text for the restart_info render (Finding 2, final
    security review).

    pages/run.py's restart_info render used to stat() whatever path
    input.restart_from() held with NO allowlist -- since restart_from is a
    client-controlled input, that was a filesystem-wide existence/size
    oracle over anything the shiny worker process can stat (a spoofed WS
    value, unconstrained by the dropdown, could probe arbitrary paths).

    This gates on restart_selection_denied_reason FIRST -- the SAME
    allowlist _submit_job checks -- and only touches the filesystem for a
    restart_from that is a member of the caller-scoped `jobs`' choice set.
    Once past that gate, a "file not found" warning is still safe to show:
    it's the user's OWN legitimate selection (already visible to them),
    and covers only the narrow TOCTOU race where the .rst was deleted
    between being listed and this render -- not a probe of an arbitrary
    path.

    Returns:
        None if restart_from is falsy or denied by the allowlist (render
        nothing). Otherwise a display string: "<name> (<KB> KB)" if the
        file exists, or a "not found" warning if it doesn't.
    """
    if not restart_from:
        return None
    if restart_selection_denied_reason(restart_from, jobs):
        return None
    rst_path = Path(restart_from)
    if rst_path.exists():
        size_kb = rst_path.stat().st_size / 1024
        return f"Restart file: {rst_path.name} ({size_kb:.0f} KB)"
    return f"Warning: restart file not found: {restart_from}"
