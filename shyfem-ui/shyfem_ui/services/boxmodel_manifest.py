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

from shyfem_ui.boxmodel_common import atomic_json
from shyfem_ui.config import Config

MANIFEST_NAME = "boxmodel.json"
MAX_MANIFEST_BYTES = 65_536
_SLUG = re.compile(r"^[a-z0-9_-]+$")


class ManifestError(ValueError):
    """User-facing manifest problem; the message names the key."""


def _section(d: dict, name: str) -> dict:
    """Fetch a top-level manifest section as a dict, defaulting absent/null to ``{}``.

    A present-but-wrong-type section (e.g. ``"boxes": [1, 2]`` or
    ``"observations": "x"``) would otherwise reach a bare ``.get(...)`` call
    downstream and raise ``AttributeError``, escaping ``load_manifest``'s
    ``ManifestError`` contract (spec §4: a bad manifest always yields a clear
    error, never a raw exception).
    """
    value = d.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ManifestError(f"{name}: must be an object")
    return value


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
    # expanduser() runs on the already-joined candidate, not on raw alone: a
    # relative value like "~otheruser/x" must stay a literal directory name
    # inside the project, never expand to another user's home directory once
    # it has been joined onto project_dir (an absolute raw value is its own
    # candidate here, so this only ever expands a leading "~" in an absolute
    # value, e.g. an unexpanded "~/curonian/runs/...").
    try:
        resolved = candidate.expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise ManifestError(f"{key}: cannot resolve path ({e})") from e
    if not raw.is_absolute():
        if not resolved.is_relative_to(proj):
            raise ManifestError(f"{key}: must stay inside the project directory")
    try:
        return config.confine_path(resolved, user, must_exist=False, for_write=False)
    except ValueError as e:
        raise ManifestError(f"{key}: {e}") from e


def load_manifest(project_dir: Path, config: Config, user: dict | None) -> BoxModelManifest:
    """Read ``boxmodel.json`` from a project and validate it.

    Reading and validating are separate (see ``parse_manifest``) so that an
    editor can check a candidate document BEFORE it replaces the live file.
    """
    project_dir = Path(project_dir)
    path = project_dir / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"{MANIFEST_NAME} not found in the project")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError(f"{MANIFEST_NAME} exceeds 64 KB")
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as e:
        # json.JSONDecodeError and UnicodeDecodeError are both ValueError
        # subclasses; OSError also covers a read_text() race/permission
        # failure after the is_file()/size checks above, and RecursionError
        # guards a pathologically deeply-nested JSON body within the 64 KB
        # cap -- all must yield ManifestError, never escape as a raw
        # exception (spec §4).
        raise ManifestError(f"{MANIFEST_NAME}: invalid JSON ({e})") from e
    return parse_manifest(d, project_dir, config, user)


def parse_manifest(d, project_dir: Path, config: Config, user: dict | None) -> BoxModelManifest:
    """Validate a manifest DOCUMENT. Reads nothing and writes nothing.

    The single source of truth for what a manifest may say -- the editor form
    asks this before writing, so the rules can never drift into a second copy,
    and the message it raises already names the offending key.
    """
    project_dir = Path(project_dir)
    if not isinstance(d, dict) or d.get("schema") != 1:
        raise ManifestError("schema: must be 1")
    title = d.get("title") or "Box model"
    if not isinstance(title, str) or len(title) > 200:
        raise ManifestError("title: must be a string of at most 200 characters")
    boxes = _section(d, "boxes")
    grid = _section(d, "grid")
    forcing = _section(d, "forcing")
    obs = _section(d, "observations")
    id_field = boxes.get("id_field") or "box"
    if not isinstance(id_field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", id_field):
        raise ManifestError("boxes.id_field: must be an identifier")
    polygons_layer = boxes.get("layer") or None
    if polygons_layer is not None and (
        not isinstance(polygons_layer, str) or len(polygons_layer) > 200
    ):
        raise ManifestError("boxes.layer: must be a string of at most 200 characters")
    runs_raw = d.get("runs")
    if not isinstance(runs_raw, list) or not runs_raw:
        raise ManifestError("runs: at least one run is required")
    runs: list[RunEntry] = []
    seen: set[str] = set()
    for i, r in enumerate(runs_raw):
        if not isinstance(r, dict):
            raise ManifestError(f"runs[{i}]: must be an object")
        rid = r.get("id")
        if not isinstance(rid, str) or not _SLUG.fullmatch(rid) or len(rid) > 64:
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
        polygons_layer=polygons_layer,
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


def write_manifest(
    project_dir: Path, doc: dict, config: Config, user: dict | None
) -> BoxModelManifest:
    """Validate ``doc`` and only then write it as the project's manifest.

    In that order on purpose. Writing first and re-reading would leave a window
    in which the page loads a broken manifest, and would need a rollback that
    can itself fail; validating first means a bad candidate never reaches the
    disk and the previous file stays exactly as it was.

    Returns the parsed manifest, so the caller can refresh the page from the
    same object the loader would have produced.
    """
    project_dir = Path(project_dir)
    parsed = parse_manifest(doc, project_dir, config, user)
    try:
        target = config.confine_path(project_dir, user, must_exist=True, for_write=True)
    except (ValueError, OSError) as e:
        raise ManifestError(f"{MANIFEST_NAME}: {e}") from e
    payload = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if len(payload.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ManifestError(f"{MANIFEST_NAME} exceeds 64 KB")
    try:
        atomic_json(Path(target) / MANIFEST_NAME, doc, indent=2)
    except OSError as e:
        raise ManifestError(f"{MANIFEST_NAME}: cannot write ({e})") from e
    return parsed
