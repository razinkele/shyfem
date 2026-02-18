"""Project export, import, and clone operations."""

import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

MANIFEST_VERSION = "1.0"

# File extensions to exclude from export (job logs)
_EXCLUDE_EXTENSIONS = frozenset({".stdout", ".stderr"})


def export_project(work_dir: Path, project_meta: dict) -> BytesIO:
    """Export a project as a ZIP archive with manifest.

    Args:
        work_dir: Absolute path to the project's work directory.
        project_meta: Dict with keys: name, description, grids, simulations.

    Returns:
        BytesIO containing the ZIP archive.
    """
    buf = BytesIO()
    work_dir = Path(work_dir)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Write project files
        for file_path in sorted(work_dir.rglob("*")):
            if not file_path.is_file():
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
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    buf.seek(0)
    return buf
