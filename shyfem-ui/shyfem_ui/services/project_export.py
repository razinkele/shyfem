"""Project export, import, and clone operations."""

import asyncio
import json
import posixpath
import shutil
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath

from shyfem_ui.config import get_config

MANIFEST_VERSION = "1.0"

# File extensions to exclude from export (job logs)
# Job logs and the detached-job bookkeeping files (J-01) are not project data.
_EXCLUDE_EXTENSIONS = frozenset({".stdout", ".stderr", ".job", ".pid", ".exit"})
# Directory names excluded from export, with everything below them (spec §9).
# ``.boxmodel_cache`` is a derived Parquet cache that is rebuilt from the run
# output on demand, so shipping it only inflates the archive (and the export
# size cap) with bytes the importing project would regenerate anyway. Kept as
# a literal rather than imported from ``services.boxmodel_cache`` to avoid
# pulling that module (and pandas) into every export; ``file_service.py`` sets
# the same precedent for ``boxmodel_cache.CACHE_DIRNAME``.
_EXCLUDE_DIRNAMES = frozenset({".boxmodel_cache"})
# App bookkeeping kept in the work-dir root (services/project_summary.py
# SUMMARY_NAME); rewritten whenever the project is opened, so not user data.
_EXCLUDE_ROOT_FILES = frozenset({".project_summary.json"})
MAX_IMPORT_FILES = 10000
# A hard ceiling on the number of archive ENTRIES, checked before any per-member
# work. MAX_IMPORT_FILES counts only the members that survive filtering (bare
# directory entries have always been excluded; the box-model cache is excluded
# too), so on its own it does not bound the traversal check, which must run over
# every name. Without this cap an archive of millions of bare directory entries
# would keep one worker thread resolving paths for minutes. Generous enough that
# no real project trips it: MAX_IMPORT_FILES is 10 000.
MAX_IMPORT_ENTRIES = 200000
MAX_IMPORT_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMPORT_COMPRESSION_RATIO = 100
# Only apply the per-member ratio (zip-bomb) check to members whose UNCOMPRESSED
# size exceeds this floor. Legitimately tiny but highly compressible files (a
# weutro_box CSV deflates ~164:1; a small zero-filled grid) otherwise fail the
# app's OWN export->import round-trip with a false "suspicious ratio". The
# 2 GiB total + file-count caps still bound resource use for small members.
MIN_RATIO_CHECK_BYTES = 4 * 1024 * 1024


async def export_project(
    work_dir: Path, project_meta: dict, max_export_bytes: int | None = None
) -> BytesIO:
    """Export a project as a ZIP archive with manifest.

    Runs the CPU/disk-bound ZIP build in a worker thread (via asyncio.to_thread)
    so the Shiny event loop stays responsive while a large project is compressed.

    Args:
        work_dir: Absolute path to the project's work directory.
        project_meta: Dict with keys: name, description, grids, simulations, files.
        max_export_bytes: Cap on total uncompressed size of exported files.
            Defaults to config.max_export_bytes when not given.

    Returns:
        BytesIO containing the ZIP archive.

    Raises:
        ValueError: If the project's files exceed max_export_bytes.
    """
    if max_export_bytes is None:
        max_export_bytes = get_config().max_export_bytes
    return await asyncio.to_thread(_export_project_sync, work_dir, project_meta, max_export_bytes)


def _export_project_sync(work_dir: Path, project_meta: dict, max_export_bytes: int) -> BytesIO:
    """Synchronous ZIP-build body for export_project. Call via asyncio.to_thread,
    not directly, so the blocking compression/disk work never runs on the event
    loop thread."""
    buf = BytesIO()
    work_dir = Path(work_dir).resolve()

    # Pre-sum file sizes (and collect the filtered file list) before writing
    # any bytes to the ZIP, so an oversized project is rejected without ever
    # starting compression.
    files_to_export: list[Path] = []
    total_size = 0
    for file_path in sorted(work_dir.rglob("*")):
        if file_path.is_symlink():
            continue
        if not file_path.is_file():
            continue
        resolved = file_path.resolve()
        try:
            resolved.relative_to(work_dir)
        except ValueError:
            continue
        if file_path.suffix in _EXCLUDE_EXTENSIONS:
            continue
        # Before the size accounting, so excluded bytes never count toward
        # (or trip) the export cap.
        if _EXCLUDE_DIRNAMES.intersection(file_path.relative_to(work_dir).parts):
            continue
        total_size += file_path.stat().st_size
        if total_size > max_export_bytes:
            max_mb = max_export_bytes // (1024 * 1024)
            raise ValueError(
                f"project export exceeds {max_mb} MB limit "
                f"(work dir contains at least {total_size} bytes)"
            )
        files_to_export.append(file_path)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write project files
        for file_path in files_to_export:
            arcname = str(file_path.relative_to(work_dir))
            zf.write(file_path, arcname)

        # Write manifest
        manifest = {
            "version": MANIFEST_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "project": {
                "name": project_meta["name"],
                "description": project_meta.get("description"),
            },
            "grids": project_meta.get("grids", []),
            "simulations": project_meta.get("simulations", []),
            "files": project_meta.get("files", []),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    return buf


async def import_project(zip_data: BytesIO, base_dir: Path) -> dict:
    """Import a project from a ZIP archive.

    Runs the disk-bound extraction in a worker thread (via asyncio.to_thread)
    so the Shiny event loop stays responsive while a large archive is unpacked.

    Args:
        zip_data: BytesIO containing the ZIP archive.
        base_dir: Base directory where the project will be extracted.

    Returns:
        Dict with keys: name, description, work_dir (Path), grids, simulations,
        files (each {rel_path, file_type}; feed it to create_project_records).

    Raises:
        ValueError: If the archive is invalid.
    """
    return await asyncio.to_thread(_import_project_sync, zip_data, base_dir)


def _import_project_sync(zip_data: BytesIO, base_dir: Path) -> dict:
    """Synchronous extraction body for import_project. Call via
    asyncio.to_thread, not directly, so the blocking disk I/O never runs on
    the event loop thread."""
    base_dir = Path(base_dir)

    with zipfile.ZipFile(zip_data, "r") as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        if len(names) > MAX_IMPORT_ENTRIES:
            raise ValueError(f"archive contains too many entries (max {MAX_IMPORT_ENTRIES})")
        if "manifest.json" not in names:
            raise ValueError("Invalid archive: missing manifest.json")
        # Our exports never write a ".." component. Refused before any check
        # reads a name, so every check sees the path that would be written:
        # ".boxmodel_cache/../big.str" passed as a cache member (exempt from
        # the limits below) yet normalises to a project file.
        for member in names:
            if ".." in member.split("/"):
                raise ValueError(f"path traversal in archive: {member!r}")
        # Cache members are dropped before the limits are computed, so a stale
        # cache cannot push a legitimate archive over the file-count or size
        # budget (spec §9). The traversal check below still runs over EVERY
        # member, so a traversal attempt disguised under the cache prefix is
        # rejected rather than silently skipped.
        cache_members = {name for name in names if _is_cache_member(name)}
        _validate_archive_limits([i for i in infos if i.filename not in cache_members])

        try:
            manifest = json.loads(zf.read("manifest.json"))
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Invalid manifest: {e}") from e

        if "version" not in manifest:
            raise ValueError("Invalid manifest: missing version")

        project_info = manifest.get("project", {})
        name = project_info.get("name", "imported_project")

        # Determine unique directory name
        project_dir = base_dir / _sanitize_dirname(name)
        if project_dir.exists():
            suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = f"{name}_{suffix}"
            project_dir = base_dir / _sanitize_dirname(name)

        # Check traversal against the actual extraction root, not just base_dir.
        project_dir_resolved = project_dir.resolve()
        for member in names:
            if member == "manifest.json":
                continue
            if Path(member).is_absolute():
                raise ValueError(f"path traversal in archive (absolute): {member!r}")
            target = (project_dir / member).resolve()
            try:
                target.relative_to(project_dir_resolved)
            except ValueError as e:
                raise ValueError(
                    f"path traversal in archive: {member!r} resolves outside {project_dir_resolved}"
                ) from e

        # Not exist_ok: this call must create the directory, because a failed
        # extraction below removes it.
        project_dir.mkdir(parents=True)

        try:
            # Extract files (skip manifest)
            for member in names:
                if member == "manifest.json":
                    continue
                if member.endswith("/"):
                    continue
                # Without ".." (refused above) this is the path written; "./x" and
                # "a//x" are the forms it still collapses.
                rel = PurePosixPath(posixpath.normpath(member))
                if not is_project_file(rel):
                    # Job files, cache and bookkeeping get no file row, so they
                    # would sit on disk uncounted by the storage limit (F-01).
                    continue
                target = project_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
        except BaseException:
            # A corrupt member (bad CRC), an encrypted one, or a full disk
            # stops the extraction part-way. No project row will point at the
            # partial directory, so nothing could delete it later and it would
            # sit outside the storage limit (F-03): remove it here.
            shutil.rmtree(project_dir, ignore_errors=True)
            raise

    return {
        "name": name,
        "description": project_info.get("description"),
        "work_dir": project_dir,
        "grids": manifest.get("grids", []),
        "simulations": manifest.get("simulations", []),
        "files": manifest.get("files", []),
    }


def _validate_archive_limits(infos: list[zipfile.ZipInfo]) -> None:
    """Reject archives that are too large or suspiciously compressed."""
    file_infos = [info for info in infos if not info.filename.endswith("/")]
    if len(file_infos) > MAX_IMPORT_FILES:
        raise ValueError(f"archive contains too many files (max {MAX_IMPORT_FILES})")

    total_uncompressed = sum(info.file_size for info in file_infos)
    if total_uncompressed > MAX_IMPORT_UNCOMPRESSED_BYTES:
        max_mb = MAX_IMPORT_UNCOMPRESSED_BYTES // (1024 * 1024)
        raise ValueError(f"archive uncompressed size exceeds {max_mb} MB")

    for info in file_infos:
        # Skip the ratio check below the floor: a small file's high ratio is
        # harmless (bounded absolute size) and legit round-trip data trips it.
        if info.file_size < MIN_RATIO_CHECK_BYTES:
            continue
        compressed_size = max(info.compress_size, 1)
        ratio = info.file_size / compressed_size
        if ratio > MAX_IMPORT_COMPRESSION_RATIO:
            raise ValueError(f"archive member {info.filename!r} has suspicious compression ratio")


def is_project_file(rel: PurePosixPath) -> bool:
    """True for a work-dir file that is project data: one that gets a file row
    and counts against the storage limit. ``rel`` is relative to the work dir."""
    if rel.suffix in _EXCLUDE_EXTENSIONS or _EXCLUDE_DIRNAMES.intersection(rel.parts):
        return False
    return str(rel) not in _EXCLUDE_ROOT_FILES


def _is_cache_member(name: str) -> bool:
    """True when an archive member lies under an excluded cache directory.

    Spec §9: import skips every member under ``.boxmodel_cache/`` so such
    files never touch disk or the size budget, forcing a rebuild from the run
    output. Exports written by this app never contain them; a hand-built
    bundle, or an archive from a version that predates the export rule, can.
    """
    return bool(_EXCLUDE_DIRNAMES.intersection(Path(name).parts))


def _sanitize_dirname(name: str) -> str:
    """Convert a project name to a safe directory name."""
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    return safe.strip().replace(" ", "_") or "project"


def clone_project(
    work_dir: Path,
    project_meta: dict,
    base_dir: Path,
    new_name: str | None = None,
) -> dict:
    """Clone a project by copying its work directory.

    Args:
        work_dir: Source project's work directory.
        project_meta: Dict with keys: name, description, grids, simulations, files.
        base_dir: Base directory where the clone will be created.
        new_name: Optional name for the clone. Defaults to "Original (Copy)".

    Returns:
        Dict with keys: name, description, work_dir (Path), grids, simulations,
        files (each {rel_path, file_type}; feed it to create_project_records).
    """
    import shutil

    work_dir = Path(work_dir)
    base_dir = Path(base_dir)
    name = new_name or f"{project_meta['name']} (Copy)"
    clone_dir = base_dir / _sanitize_dirname(name)

    if clone_dir.exists():
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{name}_{suffix}"
        clone_dir = base_dir / _sanitize_dirname(name)

    def _ignore_logs(directory, files):
        return [f for f in files if Path(f).suffix in _EXCLUDE_EXTENSIONS]

    shutil.copytree(work_dir, clone_dir, ignore=_ignore_logs)

    return {
        "name": name,
        "description": project_meta.get("description"),
        "work_dir": clone_dir,
        "grids": project_meta.get("grids", []),
        "simulations": project_meta.get("simulations", []),
        "files": project_meta.get("files", []),
    }


def export_meta(ctx: dict) -> dict:
    """The project_meta that export and clone take, from load_project_context.

    Each file row is reduced to its rel_path and file_type: the type the
    user chose is what a new project cannot infer, and a row id means
    nothing in another database.
    """
    return {
        "name": ctx["name"],
        "description": ctx.get("description"),
        "grids": ctx.get("grids", []),
        "simulations": ctx.get("simulations", []),
        "files": [
            {"rel_path": f["rel_path"], "file_type": f["file_type"]} for f in ctx.get("files", [])
        ],
    }


def _type_hints(files) -> dict[str, str]:
    """rel_path -> file_type from a manifest's (untrusted) file list."""
    hints = {}
    for f in files if isinstance(files, list) else []:
        if isinstance(f, dict):
            rel, file_type = f.get("rel_path"), f.get("file_type")
            if isinstance(rel, str) and isinstance(file_type, str):
                hints[rel] = file_type
    return hints


def create_project_records(result: dict, owner_id: int | None) -> int:
    """Create the Project, Grid, Simulation and file rows for an import or clone.

    ``result`` is what import_project or clone_project returned; its files are
    already in ``result["work_dir"]``. All rows go in one transaction, which
    is rolled back (and ValueError raised) when the files exceed the project
    storage limit. Returns the new project id.
    """
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Grid, Project, Simulation
    from shyfem_ui.services.file_service import FileService, _sum_project_bytes

    config = get_config()
    with db_session() as db:
        project = Project(
            name=result["name"],
            description=result.get("description"),
            work_dir=str(result["work_dir"]),
            owner_id=owner_id,
        )
        db.add(project)
        db.flush()

        grid_name_to_id = {}
        for g in result.get("grids", []):
            grid = Grid(
                project_id=project.id,
                name=g["name"],
                description=g.get("description"),
                grd_file=g.get("grd_file"),
                bas_file=g.get("bas_file"),
                num_nodes=g.get("num_nodes"),
                num_elements=g.get("num_elements"),
                num_layers=g.get("num_layers"),
                min_depth=g.get("min_depth"),
                max_depth=g.get("max_depth"),
            )
            db.add(grid)
            db.flush()
            grid_name_to_id[g["name"]] = grid.id

        for s in result.get("simulations", []):
            db.add(
                Simulation(
                    project_id=project.id,
                    grid_id=grid_name_to_id.get(s.get("grid_name")),
                    name=s["name"],
                    description=s.get("description"),
                    str_file=s.get("str_file"),
                    start_time=s.get("start_time"),
                    end_time=s.get("end_time"),
                    time_step=s.get("time_step"),
                    mpi_enabled=s.get("mpi_enabled", False),
                    mpi_np=s.get("mpi_np", 1),
                )
            )

        FileService.register_existing_files(
            project.id, db=db, type_hints=_type_hints(result.get("files"))
        )
        used = _sum_project_bytes(db, project.id, work_dir=project.work_dir)
        if used > config.max_project_storage_mb * 1024 * 1024:
            raise ValueError(
                f"the project's files ({used // (1024 * 1024)} MB) exceed the project "
                f"storage limit ({config.max_project_storage_mb} MB)"
            )
        return project.id
