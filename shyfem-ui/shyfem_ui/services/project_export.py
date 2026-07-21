"""Project export, import, and clone operations."""

import json
import shutil
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

MANIFEST_VERSION = "1.0"

# File extensions to exclude from export (job logs)
_EXCLUDE_EXTENSIONS = frozenset({".stdout", ".stderr"})
MAX_IMPORT_FILES = 10000
MAX_IMPORT_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMPORT_COMPRESSION_RATIO = 100


def export_project(work_dir: Path, project_meta: dict) -> BytesIO:
    """Export a project as a ZIP archive with manifest.

    Args:
        work_dir: Absolute path to the project's work directory.
        project_meta: Dict with keys: name, description, grids, simulations.

    Returns:
        BytesIO containing the ZIP archive.
    """
    buf = BytesIO()
    work_dir = Path(work_dir).resolve()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write project files
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


def import_project(zip_data: BytesIO, base_dir: Path) -> dict:
    """Import a project from a ZIP archive.

    Args:
        zip_data: BytesIO containing the ZIP archive.
        base_dir: Base directory where the project will be extracted.

    Returns:
        Dict with keys: name, description, work_dir (Path), grids, simulations.

    Raises:
        ValueError: If the archive is invalid.
    """
    base_dir = Path(base_dir)

    with zipfile.ZipFile(zip_data, "r") as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        if "manifest.json" not in names:
            raise ValueError("Invalid archive: missing manifest.json")
        _validate_archive_limits(infos)

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

        project_dir.mkdir(parents=True)

        # Extract files (skip manifest)
        for member in names:
            if member == "manifest.json":
                continue
            if member.endswith("/"):
                continue
            target = project_dir / member
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

    return {
        "name": name,
        "description": project_info.get("description"),
        "work_dir": project_dir,
        "grids": manifest.get("grids", []),
        "simulations": manifest.get("simulations", []),
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
        if info.file_size <= 0:
            continue
        compressed_size = max(info.compress_size, 1)
        ratio = info.file_size / compressed_size
        if ratio > MAX_IMPORT_COMPRESSION_RATIO:
            raise ValueError(f"archive member {info.filename!r} has suspicious compression ratio")


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
        project_meta: Dict with keys: name, description, grids, simulations.
        base_dir: Base directory where the clone will be created.
        new_name: Optional name for the clone. Defaults to "Original (Copy)".

    Returns:
        Dict with keys: name, description, work_dir (Path), grids, simulations.
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
    }
