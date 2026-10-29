"""File management service for project data files."""

import hashlib
import logging
import os
import re
import stat as _stat
import threading
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy.exc import IntegrityError

from shyfem_ui.config import get_config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Project, ProjectFile

# <job uuid>.<suffix>: the files a job keeps next to its working directory.
_JOB_FILE_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"\.(stdout|stderr|job|pid|exit)$",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

# Uploads run in threads (F-05), so two into the same project could both pass
# the storage-quota check before either is written. One lock per project, held
# from the quota check to the commit, keeps them in turn within this process.
_upload_locks_guard = threading.Lock()
_upload_locks: defaultdict[int, threading.Lock] = defaultdict(threading.Lock)


def _upload_lock(project_id: int) -> threading.Lock:
    with _upload_locks_guard:
        return _upload_locks[project_id]


# Every file_type a row may carry: the upload picker's choices plus the ones
# _infer_file_type produces. A type read from an archive must be one of these.
FILE_TYPES = frozenset(
    {
        "grid",
        "basin",
        "str",
        "forcing",
        "boundary",
        "initial_condition",
        "restart",
        "config",
        "output",
        "lagrangian",
        "other",
    }
)


def _project_files_on_disk(work_dir: str | Path):
    """Yield (rel_path, size) for each project file in the work dir.

    Project files are what ``project_export.is_project_file`` accepts:
    regular files only, symlinks neither listed nor followed. The walk is
    lazy, so a caller wanting only the first file does not list the whole
    tree. A directory that cannot be listed raises OSError.
    """
    from shyfem_ui.services.project_export import _EXCLUDE_DIRNAMES, is_project_file

    root = Path(work_dir).resolve()
    if not root.is_dir():
        return

    def _raise(err: OSError):
        raise err

    for dirpath, dirnames, filenames in os.walk(root, onerror=_raise):
        dirnames[:] = sorted(d for d in dirnames if d not in _EXCLUDE_DIRNAMES)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = PurePosixPath(path.relative_to(root).as_posix())
            if not is_project_file(rel):
                continue
            st = path.lstat()
            if _stat.S_ISREG(st.st_mode):
                yield str(rel), st.st_size


class FileService:
    """Manages project files: upload, delete, list."""

    @staticmethod
    def upload_file(
        project_id: int,
        file_data: bytes,
        filename: str,
        file_type: str,
        subdir: str | None = None,
    ) -> dict:
        """Upload a file to a project.

        Args:
            project_id: Project to add the file to.
            file_data: Raw file bytes.
            filename: Original filename (validated for safety).
            file_type: Category — grid, basin, str, forcing, boundary,
                       initial_condition, restart, config, output, other.
            subdir: Optional subdirectory within work_dir (e.g. "GRID", "INPUT").

        Returns:
            Dict with id, filename, rel_path, file_type, size_bytes, checksum.

        Raises:
            ValueError: On invalid filename, missing project, or quota exceeded.
        """
        # Validate filename — no path separators, no traversal
        safe_name = PurePosixPath(filename).name
        if safe_name != filename or not filename or ".." in filename:
            raise ValueError(f"Invalid filename: {filename!r}")
        if _JOB_FILE_NAME.match(filename):
            # A job's log and bookkeeping files (J-01) belong to the server.
            raise ValueError(f"Reserved filename: {filename!r}")

        config = get_config()
        size = len(file_data)

        with _upload_lock(project_id), db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                raise ValueError(f"Project {project_id} not found")

            work_dir = Path(project.work_dir)

            # Check project storage quota
            current = _sum_project_bytes(db, project_id, work_dir=project.work_dir)
            limit = config.max_project_storage_mb * 1024 * 1024
            if current + size > limit:
                raise ValueError(
                    f"Upload would exceed project storage limit "
                    f"({config.max_project_storage_mb} MB)"
                )

            # Determine target path
            if subdir:
                # Validate subdir: reject traversal AND absolute paths. An
                # absolute subdir would make ``work_dir / subdir`` resolve to the
                # absolute path (RHS wins in pathlib), escaping the sandbox.
                safe_sub = PurePosixPath(subdir)
                if safe_sub.is_absolute() or ".." in safe_sub.parts:
                    raise ValueError(f"Invalid subdir: {subdir!r}")
                target_dir = work_dir / str(safe_sub)
                rel_path = f"{safe_sub}/{safe_name}"
            else:
                target_dir = work_dir
                rel_path = safe_name

            # Defense in depth: the resolved final target must stay within
            # work_dir (covers symlinks and any traversal that slipped through).
            work_root = work_dir.resolve()
            target = (target_dir / safe_name).resolve()
            if target != work_root and not str(target).startswith(str(work_root) + "/"):
                raise ValueError(f"Upload path escapes the project directory: {subdir!r}")

            target_dir.mkdir(parents=True, exist_ok=True)

            # Write file
            target.write_bytes(file_data)

            # Compute checksum
            checksum = hashlib.sha256(file_data).hexdigest()

            # Upsert DB record — handle re-upload of the same rel_path
            try:
                existing = (
                    db.query(ProjectFile)
                    .filter_by(project_id=project_id, rel_path=rel_path)
                    .one_or_none()
                )
                if existing is None:
                    pf = ProjectFile(
                        project_id=project_id,
                        filename=safe_name,
                        rel_path=rel_path,
                        file_type=file_type,
                        size_bytes=size,
                        checksum=checksum,
                    )
                    db.add(pf)
                else:
                    pf = existing
                    pf.size_bytes = size
                    pf.checksum = checksum
                    pf.uploaded_at = datetime.now(UTC)
                db.flush()
            except IntegrityError:
                # Concurrent upload of the same path lost the read-then-insert race
                # against the UNIQUE constraint. Retry as a pure update — but use
                # one_or_none() because the concurrent winner may also have rolled back.
                db.rollback()
                existing = (
                    db.query(ProjectFile)
                    .filter_by(project_id=project_id, rel_path=rel_path)
                    .one_or_none()
                )
                if existing is None:
                    logger.error(
                        "Both concurrent uploads of %s failed; disk file may be orphaned",
                        rel_path,
                    )
                    raise RuntimeError(
                        f"Upload of {rel_path} failed due to concurrent write conflict; "
                        "please retry"
                    ) from None
                pf = existing
                pf.size_bytes = size
                pf.checksum = checksum
                pf.uploaded_at = datetime.now(UTC)
                db.flush()

            return {
                "id": pf.id,
                "filename": pf.filename,
                "rel_path": pf.rel_path,
                "file_type": pf.file_type,
                "size_bytes": pf.size_bytes,
                "checksum": pf.checksum,
            }

    @staticmethod
    def delete_file(file_id: int) -> None:
        """Delete a file from disk and DB.

        Raises:
            ValueError: If file_id does not exist.
        """
        with db_session() as db:
            pf = db.query(ProjectFile).filter_by(id=file_id).first()
            if pf is None:
                raise ValueError(f"File {file_id} not found")

            project = db.query(Project).filter_by(id=pf.project_id).first()
            if project:
                disk_path = Path(project.work_dir) / pf.rel_path
                if disk_path.exists():
                    disk_path.unlink()

            db.delete(pf)

    @staticmethod
    def list_files(project_id: int, file_type: str | None = None) -> list[dict]:
        """List files in a project, optionally filtered by type.

        Returns:
            List of dicts with id, filename, rel_path, file_type, size_bytes,
            uploaded_at, checksum.
        """
        with db_session() as db:
            q = db.query(ProjectFile).filter_by(project_id=project_id)
            if file_type:
                q = q.filter_by(file_type=file_type)
            q = q.order_by(ProjectFile.filename)
            return [
                {
                    "id": pf.id,
                    "filename": pf.filename,
                    "rel_path": pf.rel_path,
                    "file_type": pf.file_type,
                    "size_bytes": pf.size_bytes,
                    "uploaded_at": pf.uploaded_at.isoformat() if pf.uploaded_at else None,
                    "checksum": pf.checksum,
                }
                for pf in q.all()
            ]

    @staticmethod
    def get_file_path(file_id: int) -> Path:
        """Get absolute path for a file (for download or job use).

        Raises:
            ValueError: If file_id does not exist.
        """
        with db_session() as db:
            pf = db.query(ProjectFile).filter_by(id=file_id).first()
            if pf is None:
                raise ValueError(f"File {file_id} not found")
            project = db.query(Project).filter_by(id=pf.project_id).first()
            return Path(project.work_dir) / pf.rel_path

    @staticmethod
    def get_file_project_id(file_id: int) -> int | None:
        """Return the project_id that owns a file, or None if file not found.

        Used by download/preview handlers to verify the requesting user has
        access to the file's project before serving its bytes.
        """
        with db_session() as db:
            pf = db.query(ProjectFile).filter_by(id=file_id).first()
            return pf.project_id if pf else None

    # Extensions to skip when seeding tutorial files
    _SKIP_EXTENSIONS = frozenset({".sh", ".stdout", ".stderr", ".job", ".pid", ".exit"})
    _SKIP_FILENAMES = frozenset({"Makefile", "README", "util.sh", "run_all.sh"})

    @staticmethod
    def _infer_file_type(rel_path: str) -> str:
        """Infer file_type from path and extension."""
        p = PurePosixPath(rel_path)
        ext = p.suffix.lower()
        parts = p.parts

        if ext == ".grd":
            return "grid"
        if ext == ".bas":
            return "basin"
        if ext == ".str":
            return "str"
        if ext == ".rst":
            return "restart"
        if ext == ".nml":
            return "config"
        if ext in (".shy", ".ext", ".flx", ".nc"):
            return "output"
        if ext == ".lgr":
            return "lagrangian"
        # Subdirectory hints
        if len(parts) > 1 and parts[0].upper() == "INPUT":
            return "forcing"
        return "other"

    @classmethod
    def register_existing_files(
        cls, project_id: int, *, db=None, type_hints: dict[str, str] | None = None
    ) -> int:
        """Add a row for each project file on disk that has none; return how many.

        Import and clone call this so the copied files are listed and counted
        against the quota. A type in ``type_hints`` (rel_path -> file_type)
        replaces the inferred one when it is in FILE_TYPES. Sizes come from
        stat(); no checksum, since a cloned project can be hundreds of MB.
        """
        if db is None:
            with db_session() as db:
                return cls.register_existing_files(project_id, db=db, type_hints=type_hints)
        project = db.query(Project).filter_by(id=project_id).first()
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        hints = type_hints or {}
        known = {rel for (rel,) in db.query(ProjectFile.rel_path).filter_by(project_id=project_id)}
        rows = []
        for rel, size in _project_files_on_disk(project.work_dir):
            if rel in known:
                continue
            hint = hints.get(rel)
            rows.append(
                ProjectFile(
                    project_id=project_id,
                    filename=PurePosixPath(rel).name,
                    rel_path=rel,
                    file_type=hint if hint in FILE_TYPES else cls._infer_file_type(rel),
                    size_bytes=size,
                )
            )
        db.add_all(rows)
        db.flush()
        return len(rows)

    @staticmethod
    def has_project_files(project_id: int) -> bool:
        """True when the project has a file row or a project file on disk.

        Seeding is only safe into a project for which this is False: the
        seed copies over same-named files, and projects made before rows
        were registered on import and clone have files but no rows.
        """
        with db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                return False
            if db.query(ProjectFile.id).filter_by(project_id=project_id).first() is not None:
                return True
            work_dir = project.work_dir
        try:
            return next(_project_files_on_disk(work_dir), None) is not None
        except OSError:
            # Unlistable: assume files, so the seed cannot copy over them.
            logger.warning("Cannot list %s; treating the project as non-empty", work_dir)
            return True

    @classmethod
    def seed_tutorial_files(cls, project_id: int) -> None:
        """Copy Mar Menor tutorial files into a project.

        Copies grid, input, and STR files from testcases/examples/mar_menor/
        into the project work directory and creates ProjectFile records.

        Args:
            project_id: Target project.

        Raises:
            ValueError: If project not found, tutorial data missing, or the
                project already has files (the copy would overwrite them).
        """
        import shutil

        config = get_config()
        tutorial_dir = config.shyfem_dir / "testcases" / "examples" / "mar_menor"
        if not tutorial_dir.exists():
            raise ValueError(f"Tutorial data not found: {tutorial_dir}")

        with db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            work_dir = Path(project.work_dir)

        if cls.has_project_files(project_id):
            raise ValueError(
                "This project already has files; tutorial files are only seeded "
                "into an empty project. Create a new project for the tutorial."
            )

        # Walk tutorial directory and copy relevant files. Accumulate row dicts
        # and insert in a single transaction at the end so we don't pay one
        # round-trip per file.
        rows: list[dict] = []
        for src_file in sorted(tutorial_dir.rglob("*")):
            if not src_file.is_file():
                continue
            if src_file.suffix in cls._SKIP_EXTENSIONS:
                continue
            if src_file.name in cls._SKIP_FILENAMES:
                continue
            # Skip output/partition files
            if src_file.name.startswith("partition."):
                continue
            if src_file.suffix in (".inf",):
                continue
            # Skip large output files
            if ".hydro." in src_file.name or ".ext" == src_file.suffix:
                if src_file.stat().st_size > 100_000:
                    continue

            rel = src_file.relative_to(tutorial_dir)
            rel_str = str(rel)
            dest = work_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

            file_type = cls._infer_file_type(rel_str)
            file_data = src_file.read_bytes()
            checksum = hashlib.sha256(file_data).hexdigest()

            rows.append(
                {
                    "project_id": project_id,
                    "filename": src_file.name,
                    "rel_path": rel_str,
                    "file_type": file_type,
                    "size_bytes": len(file_data),
                    "checksum": checksum,
                }
            )

        if rows:
            with db_session() as db:
                db.add_all([ProjectFile(**r) for r in rows])

    @staticmethod
    def get_project_storage(project_id: int) -> dict[str, int]:
        """Get storage usage for a project.

        Returns:
            Dict with used_bytes (uploaded files PLUS the on-disk box-model
            cache), cache_bytes (the cache-only part of that total, so the UI
            can explain a number the file list does not account for) and
            file_count (uploaded files only -- cache files are not rows).

        ``used_bytes`` must be computed exactly the way the upload quota
        check computes it (``_sum_project_bytes`` with the project's
        ``work_dir``): displaying a smaller number than the one enforced is
        how a user ends up refused an upload with "plenty of space left" on
        screen.
        """
        with db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            work_dir = project.work_dir if project is not None else None
            # _sum_project_bytes without work_dir = the DB rows only; the cache
            # is added separately so the tree is walked exactly once.
            db_bytes = _sum_project_bytes(db, project_id)
            count = db.query(ProjectFile).filter_by(project_id=project_id).count()
        cache = _cache_bytes(work_dir)
        return {"used_bytes": db_bytes + cache, "cache_bytes": cache, "file_count": count}


def _cache_bytes(work_dir: str | Path | None) -> int:
    """Total size of the regular files under the project's box-model cache,
    charging each cache run ONCE.

    A build publishes in two steps (``<run>`` -> ``<run>.old-<token>``,
    ``<run>.tmp-<token>`` -> ``<run>``), so for a moment one run's bytes are
    on disk twice and the project was charged twice for that single run
    against ``SHYFEM_UI_MAX_PROJECT_STORAGE_MB`` -- in both windows. A large
    run could push a project over its quota purely by being rebuilt.

    So directories are grouped by run id (the name before ``.tmp-``/``.old-``)
    and each group is charged its LARGEST member: one run's worth of bytes,
    whichever copy that is. Simply skipping the marker directories would be
    wrong in the other direction -- an ``error``-phase ``.tmp-`` dir is kept
    on purpose (``cache_status`` reports it, the next ``start_build`` clears
    it), so it can sit there for days holding the biggest artefact of all, a
    fully written ``state_daily.parquet``, and its bytes must be charged.

    What this does not model: two workers building the same run at once is
    charged as one run, and a publish in progress is charged for one copy
    rather than the two briefly on disk. Both are bounded and transient;
    over-charging a rebuild is the failure that actually hurt. Run ids are
    ``[a-z0-9_-]{1,64}`` (no dots), so a published name can never carry a
    marker.

    Symlinks are counted as links (``lstat``), never followed, so a link into
    the project's own tree is not double-counted and one pointing outside it
    cannot inflate the figure. A file that disappears mid-walk (a build
    publishing underneath us) is skipped rather than raising.
    """
    if not work_dir:
        return 0
    # Literal rather than an import of services.boxmodel_cache.CACHE_DIRNAME:
    # this module is on the upload path and must not pull in pandas.
    cache = Path(work_dir) / ".boxmodel_cache"
    if not cache.is_dir():
        return 0
    try:
        entries = list(cache.iterdir())
    except OSError:
        return 0
    charges: dict[str, int] = {}
    for entry in entries:
        run_id = entry.name
        for marker in (".tmp-", ".old-"):
            if marker in run_id:
                run_id = run_id.split(marker, 1)[0]
                break
        paths = entry.rglob("*") if (entry.is_dir() and not entry.is_symlink()) else [entry]
        size = 0
        for p in paths:
            try:
                st = p.lstat()
            except OSError:
                continue
            if _stat.S_ISREG(st.st_mode):
                size += st.st_size
        charges[run_id] = max(charges.get(run_id, 0), size)
    return sum(charges.values())


def _sum_project_bytes(db, project_id: int, work_dir: str | Path | None = None) -> int:
    """Sum size_bytes for all files in a project, plus the on-disk box-model cache."""
    from sqlalchemy import func as sa_func

    result = (
        db.query(sa_func.coalesce(sa_func.sum(ProjectFile.size_bytes), 0))
        .filter_by(project_id=project_id)
        .scalar()
    )
    return int(result) + _cache_bytes(work_dir)
