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
from uuid import uuid4

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
        restart_from: Optional restart file path, recorded in metadata for
            display/audit. This does NOT itself make the run continue from
            it -- the caller must apply it to the STR beforehand (see
            write_restart_str) and pass the derived file as validated_input;
            otherwise the run silently starts fresh (N42).
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


def write_restart_str(str_path: Path, restart_file: str, dest_dir: Path) -> Path:
    """Apply a 'Continue from job' restart selection to a STR file (N42).

    Previously restart_from was recorded only in build_job_spec's metadata;
    nothing ever wrote it into the STR SHYFEM actually reads, so a selected
    restart was silently ignored and every run started cold. SHYFEM reads
    the restart file via the ``$name`` section's ``restrt`` parameter (see
    services/parser_str.py PARAM_DOCS['name']['restrt']), so this parses
    str_path, sets that parameter, and writes the result to a NEW file under
    dest_dir via StrParser.save() -- the user's original STR is only ever
    read, never mutated.

    restrt alone is NOT sufficient for SHYFEM to actually continue: the
    ``$para`` section's ``itrst`` parameter (default 0, per
    src/shyfem/def_para.f90's ``addpar('itrst',0.)``) selects WHICH time
    record in the restart file to use. With the default itrst=0/ityrst=0,
    src/shyfem/restart.f90's rst_perform_restart looks for a record whose
    time exactly equals 0 and, failing to find one (the normal case --
    restart records are at real simulation times), hard-aborts with
    ``stop 'error stop rst_perform_restart: Cannot find time record'``
    before the simulation ever starts. Setting itrst=-1 sets
    ``blast=.true.``/``atrst=-1.``, which reads the LAST record in the file
    unconditionally, regardless of ityrst -- this is the "normal case"
    continuation and is exactly what both shipped, working restart
    testcases do: testcases/examples/weutro_box/eco_rst_part2.str:14 and
    merc_rst_part2.str:13 both set ``itrst = -1`` in ``$para`` (NOT
    ``$name`` -- confirmed against those two files; itanf/itend are left
    untouched here deliberately, that's a separate, deferred enhancement).

    Args:
        str_path: The source (already validated) STR file to continue from.
        restart_file: Path to the .rst restart file. Must already exist --
            a stale selection (e.g. the source job's .rst was deleted) must
            abort loudly rather than silently emit an STR referencing a
            missing file, which would otherwise fail deep in SHYFEM's
            Fortran I/O with an opaque error instead of a clear UI message.
        dest_dir: Directory to write the derived STR into. The caller is
            responsible for validating this directory is safe to write to
            (e.g. via Config.confine_path) BEFORE calling this function --
            it performs the actual disk write.

    Returns:
        Path to the newly written STR file. Pass this (not the original
        str_path) as validated_input to build_job_spec so the submitted job
        actually continues from restart_file.

    Raises:
        FileNotFoundError: restart_file does not exist.
    """
    if not Path(restart_file).exists():
        raise FileNotFoundError(f"Restart file not found: {restart_file}")

    # A fresh parse of str_path -- unlike ensemble.py's _apply_param_combo
    # (which regenerates+reparses to protect a base_str shared across many
    # combos from mutation), nothing else holds a reference to this object,
    # so set_param can act on it directly; no extra generate()->parse()
    # round-trip needed.
    base_str = StrParser.parse_file(str_path)
    # _format_value only auto-quotes strings containing a space or '-'; an
    # absolute restart path with neither (e.g. no hyphens in the project/user
    # names) would otherwise be emitted UNQUOTED (`restrt = /a/b/out.rst`).
    # Pre-quoting is the idiom _format_value itself documents for this case
    # ("Already single-quoted ... emit as-is") -- it skips re-wrapping, and
    # StrParser.parse() strips the quotes back off on read.
    base_str.set_param("name", "restrt", f"'{restart_file}'")
    # itrst is a real/numeric parameter (addpar('itrst',0.)) -- pass a bare
    # int so _format_value emits `itrst = -1` unquoted, matching both
    # testcases exactly (neither quotes it).
    base_str.set_param("para", "itrst", -1)

    dest_dir = Path(dest_dir)
    # A uuid suffix avoids two restart-enabled submissions against the same
    # STR/working directory colliding and clobbering each other's derived
    # file mid-run (the same working dir can host concurrent jobs).
    derived_name = f"{str_path.stem}_restart_{uuid4().hex[:8]}{str_path.suffix}"
    derived_path = dest_dir / derived_name
    StrParser.save(base_str, derived_path)
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
