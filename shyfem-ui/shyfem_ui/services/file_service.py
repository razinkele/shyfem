"""File management service for project data files."""

import hashlib
from pathlib import Path, PurePosixPath

from shyfem_ui.config import get_config
from shyfem_ui.db.base import db_session
from shyfem_ui.models.project import Project, ProjectFile


class FileService:
    """Manages project files: upload, delete, list, validate."""

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

        config = get_config()
        size = len(file_data)

        with db_session() as db:
            project = db.query(Project).filter_by(id=project_id).first()
            if project is None:
                raise ValueError(f"Project {project_id} not found")

            work_dir = Path(project.work_dir)

            # Check project storage quota
            current = _sum_project_bytes(db, project_id)
            limit = config.max_project_storage_mb * 1024 * 1024
            if current + size > limit:
                raise ValueError(
                    f"Upload would exceed project storage limit "
                    f"({config.max_project_storage_mb} MB)"
                )

            # Determine target path
            if subdir:
                # Validate subdir
                safe_sub = PurePosixPath(subdir)
                if ".." in safe_sub.parts:
                    raise ValueError(f"Invalid subdir: {subdir!r}")
                target_dir = work_dir / str(safe_sub)
                rel_path = f"{safe_sub}/{safe_name}"
            else:
                target_dir = work_dir
                rel_path = safe_name

            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / safe_name

            # Write file
            target.write_bytes(file_data)

            # Compute checksum
            checksum = hashlib.sha256(file_data).hexdigest()

            # Create DB record
            pf = ProjectFile(
                project_id=project_id,
                filename=safe_name,
                rel_path=rel_path,
                file_type=file_type,
                size_bytes=size,
                checksum=checksum,
            )
            db.add(pf)
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
    def get_project_storage(project_id: int) -> dict:
        """Get storage usage for a project.

        Returns:
            Dict with used_bytes and file_count.
        """
        with db_session() as db:
            total = _sum_project_bytes(db, project_id)
            count = db.query(ProjectFile).filter_by(project_id=project_id).count()
            return {"used_bytes": total, "file_count": count}


def _sum_project_bytes(db, project_id: int) -> int:
    """Sum size_bytes for all files in a project."""
    from sqlalchemy import func as sa_func
    result = (
        db.query(sa_func.coalesce(sa_func.sum(ProjectFile.size_bytes), 0))
        .filter_by(project_id=project_id)
        .scalar()
    )
    return int(result)
