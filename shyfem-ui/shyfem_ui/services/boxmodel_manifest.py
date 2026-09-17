"""Load and validate a project's ``boxmodel.json`` (spec §4).

Validation resolves paths through ``Config.confine_path`` (read-only) but
opens nothing; every consumer re-checks at open time. Errors are
``ManifestError`` with the offending key, meant for a page-level message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from shyfem_ui.config import Config

MANIFEST_NAME = "boxmodel.json"
MAX_MANIFEST_BYTES = 65_536
_SLUG = re.compile(r"^[a-z0-9_-]+$")
_VARIABLES = ("salinity", "temperature", "level")


class ManifestError(ValueError):
    """User-facing manifest problem; the message names the key."""


@dataclass(frozen=True)
class RunEntry:
    id: str
    label: str
    dir: Path


@dataclass
class BoxModelManifest:
    title: str
    polygons: Path | None
    polygons_layer: str | None
    id_field: str
    grd: Path
    bas: Path | None
    boxes_txt: Path | None
    str_path: Path | None
    forcing_dir: Path | None
    runs: list[RunEntry] = field(default_factory=list)
    observations: Path | None = None
    sites: Path | None = None


def _resolve(
    value, key: str, project_dir: Path, config: Config, user: dict | None, *, required: bool
) -> Path | None:
    """Resolve one manifest path field and confine it.

    A *relative* value resolves against ``project_dir`` (spec §4) and must
    stay inside it -- this containment check is mode-independent: it is a
    manifest-schema invariant ("resolves against the project directory"
    means "resolves to somewhere in the project directory"), not a
    ``Config.confine_path`` concern, so a ``../`` escape is rejected even
    when the resulting absolute path would otherwise be allowed by
    local-mode's broader work_dir/shyfem_dir/tmp allowance.

    An *absolute* value (e.g. an out-of-sandbox run directory named in
    ``runs[].dir``, per spec §4's Curonian example) skips that containment
    check and is confined only by ``Config.confine_path`` -- in local mode
    that permits anything under work_dir/shyfem_dir/tmp; in server mode it
    permits only the user's own home, the bundled read-only assets, and the
    admin-declared analysis roots. This is the "enforced by the
    confinement, not by string prefix checks" rule for the run-dir case:
    there is no manual ``resolved_analysis_roots()`` prefix check here --
    ``confine_path`` alone decides, in both modes.
    """
    if value in (None, ""):
        if required:
            raise ManifestError(f"{key}: required")
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise ManifestError(f"{key}: must be a path string")
    raw = Path(value)
    proj = project_dir.resolve()
    candidate = raw if raw.is_absolute() else proj / raw
    try:
        resolved = candidate.expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise ManifestError(f"{key}: cannot resolve path ({e})") from e
    if not raw.is_absolute():
        if resolved != proj and not resolved.is_relative_to(proj):
            raise ManifestError(f"{key}: must stay inside the project directory")
    try:
        return config.confine_path(resolved, user, must_exist=False, for_write=False)
    except ValueError as e:
        raise ManifestError(f"{key}: {e}") from e


def load_manifest(project_dir: Path, config: Config, user: dict | None) -> BoxModelManifest:
    project_dir = Path(project_dir)
    path = project_dir / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"{MANIFEST_NAME} not found in the project")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError(f"{MANIFEST_NAME} exceeds 64 KB")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError(f"{MANIFEST_NAME}: invalid JSON ({e})") from e
    if not isinstance(d, dict) or d.get("schema") != 1:
        raise ManifestError("schema: must be 1")
    title = d.get("title") or "Box model"
    if not isinstance(title, str) or len(title) > 200:
        raise ManifestError("title: must be a string of at most 200 characters")
    boxes = d.get("boxes") or {}
    grid = d.get("grid") or {}
    forcing = d.get("forcing") or {}
    obs = d.get("observations") or {}
    id_field = boxes.get("id_field") or "box"
    if not isinstance(id_field, str) or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", id_field):
        raise ManifestError("boxes.id_field: must be an identifier")
    runs_raw = d.get("runs")
    if not isinstance(runs_raw, list) or not runs_raw:
        raise ManifestError("runs: at least one run is required")
    runs: list[RunEntry] = []
    seen: set[str] = set()
    for i, r in enumerate(runs_raw):
        if not isinstance(r, dict):
            raise ManifestError(f"runs[{i}]: must be an object")
        rid = r.get("id")
        if not isinstance(rid, str) or not _SLUG.match(rid) or len(rid) > 64:
            raise ManifestError(f"runs[{i}].id: must match [a-z0-9_-]+ (max 64)")
        if rid in seen:
            raise ManifestError(f"runs[{i}].id: {rid!r} is not unique")
        seen.add(rid)
        label = r.get("label") or rid
        if not isinstance(label, str) or len(label) > 200:
            raise ManifestError(f"runs[{i}].label: must be a string of at most 200 characters")
        rdir = _resolve(r.get("dir"), f"runs[{i}].dir", project_dir, config, user, required=True)
        runs.append(RunEntry(rid, label, rdir))
    return BoxModelManifest(
        title=title,
        polygons=_resolve(
            boxes.get("polygons"), "boxes.polygons", project_dir, config, user, required=False
        ),
        polygons_layer=boxes.get("layer") or None,
        id_field=id_field,
        grd=_resolve(grid.get("grd"), "grid.grd", project_dir, config, user, required=True),
        bas=_resolve(grid.get("bas"), "grid.bas", project_dir, config, user, required=False),
        boxes_txt=_resolve(
            grid.get("boxes_txt"), "grid.boxes_txt", project_dir, config, user, required=False
        ),
        str_path=_resolve(d.get("str"), "str", project_dir, config, user, required=False),
        forcing_dir=_resolve(
            forcing.get("dir"), "forcing.dir", project_dir, config, user, required=False
        ),
        runs=runs,
        observations=_resolve(
            obs.get("file"), "observations.file", project_dir, config, user, required=False
        ),
        sites=_resolve(
            obs.get("sites"), "observations.sites", project_dir, config, user, required=False
        ),
    )
