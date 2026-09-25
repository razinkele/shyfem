"""Dropdowns of files / directories inside the active project.

Every page that used to offer a free-text path box ("/path/to/input.str")
now renders one of these instead. Option *values* are absolute paths inside
the (confined) project work_dir, so the load/run handlers that consume
``input.<id>()`` and re-confine the value stay unchanged; option *labels*
are project-relative.

The helpers are plain functions returning a Tag (or a muted ``<p>`` when
there is nothing to choose from), meant to be called from a ``@render.ui``
so the list refreshes whenever the active project changes.

Paths outside the project (tutorial assets, the bundled Mar Menor sample)
cannot be pushed into a dropdown with ``ui.update_select`` -- a value that is
not one of the options is a silent no-op. Pages therefore keep a
``reactive.Value`` for such a path and pass it back here as ``extra`` +
``selected`` so it is injected as an option and preselected on render.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from shiny import ui

from shyfem_ui.services.project_files import list_project_dirs, list_project_files

if TYPE_CHECKING:
    from shyfem_ui.config import Config

logger = logging.getLogger(__name__)

_MUTED = "text-muted small mb-2"


def _confined_root(proj: Mapping | None, user: dict | None, config: Config) -> Path | None:
    """The project's work_dir, confined to the requesting user, or None."""
    if proj is None:
        return None
    try:
        return Path(config.confine_path(proj["work_dir"], user, must_exist=True))
    except (KeyError, ValueError, OSError):
        return None


def _load_manifest_or_none(root: Path, config: Config, user: dict | None):
    """The project's box-model manifest, or None when absent/invalid.

    Separated so tests can stub the manifest without a real ``boxmodel.json``.
    """
    from shyfem_ui.services.boxmodel_manifest import ManifestError, load_manifest

    try:
        return load_manifest(root, config, user)
    except (ManifestError, ValueError, OSError):
        return None


def _match_choice(wanted: str | None, choices: Mapping[str, str]) -> str:
    """The option value equal to ``wanted``, matching by resolved path when
    the literal string differs (e.g. a project ``work_dir`` recorded through a
    symlink while option values come from the confined, resolved root).
    Returns ``""`` when nothing matches."""
    if not wanted:
        return ""
    if wanted in choices:
        return wanted
    try:
        target = Path(wanted).resolve()
    except OSError:
        return ""
    for value in choices:
        try:
            if Path(value).resolve() == target:
                return value
        except OSError:
            continue
    return ""


def default_project_file(proj: Mapping | None, kind: Literal["str", "grd", "bas"]) -> str | None:
    """Absolute path of the project's default file of ``kind``, or None.

    Mirrors the old text-box auto-fill: the first simulation's STR file, or
    the first grid's .grd/.bas.
    """
    if proj is None:
        return None
    work_dir = proj.get("work_dir")
    if not work_dir:
        return None
    if kind == "str":
        sims = proj.get("simulations") or []
        rel = sims[0].get("str_file") if sims else None
    else:
        grids = proj.get("grids") or []
        rel = grids[0].get(f"{kind}_file") if grids else None
    return str(Path(work_dir) / rel) if rel else None


def project_file_select(
    select_id: str,
    label: str,
    exts: Sequence[str],
    *,
    proj: Mapping | None,
    user: dict | None,
    config: Config,
    selected: str | Sequence[str] | None = None,
    extra: Mapping[str, str] | None = None,
    include_runs: bool = False,
    multiple: bool = False,
) -> ui.Tag:
    """A dropdown of the active project's files whose suffix is in ``exts``.

    Args:
        select_id: Input id (the page reads ``input.<select_id>()``).
        label: Input label.
        exts: Suffixes to list, with the leading dot.
        proj: Active project context (``active_project.get()``) or None.
        user: ``current_user()`` or None; used for path confinement.
        config: App config.
        selected: Absolute path(s) to preselect when present in the options.
        extra: ``{abs_path: label}`` options to inject (a sample or tutorial
            file living outside the project). Not confined here -- the
            consuming handler re-confines whatever value it receives.
        include_runs: Also list matching files from the project's box-model
            run directories (``boxmodel.json`` manifest, already confined).
        multiple: Render a multi-select (selectize) with no placeholder.
    """
    choices: dict[str, str] = {}
    if proj is None:
        # A sample/tutorial file can still be offered without a project.
        if not extra:
            return ui.p(f"Open a project to choose a {label.lower()}.", class_=_MUTED)
    else:
        root = _confined_root(proj, user, config)
        if root is None:
            return ui.p("Project directory unavailable.", class_=_MUTED)
        for rel in list_project_files(root, exts):
            choices[str(root / rel)] = rel
        if include_runs:
            manifest = _load_manifest_or_none(root, config, user)
            if manifest is not None:
                for run in manifest.runs:
                    for rel in list_project_files(Path(run.dir), exts):
                        choices.setdefault(str(Path(run.dir) / rel), f"{run.label} / {rel}")
    for path, extra_label in (extra or {}).items():
        choices.setdefault(str(path), extra_label)

    if not choices:
        return ui.p(f"No {'/'.join(exts)} files in this project.", class_=_MUTED)

    if multiple:
        wanted = [selected] if isinstance(selected, str) else list(selected or [])
        sel = [m for m in (_match_choice(w, choices) for w in wanted) if m]
        return ui.input_selectize(
            select_id, label, choices=choices, selected=sel or None, multiple=True
        )

    sel_one = _match_choice(selected, choices) if isinstance(selected, str) else ""
    ordered = {"": "— select a file —", **choices}
    return ui.input_select(select_id, label, choices=ordered, selected=sel_one)


def project_dir_select(
    select_id: str,
    label: str,
    *,
    proj: Mapping | None,
    user: dict | None,
    config: Config,
    selected: str | None = None,
    default_label: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> ui.Tag:
    """A dropdown of the project directory and its subdirectories.

    Option values are absolute paths; the project root is labelled
    ``"<name>/"``. When ``default_label`` is given, an empty option carrying
    that label comes first and is the default (the page then falls back to
    its own rule, e.g. "same directory as the input file"); otherwise the
    project root is preselected. ``extra`` injects directories outside the
    project (the bundled sample's directory), as for ``project_file_select``.
    """
    choices: dict[str, str] = {}
    root: Path | None = None
    if proj is None:
        if not extra:
            return ui.p(f"Open a project to choose a {label.lower()}.", class_=_MUTED)
    else:
        root = _confined_root(proj, user, config)
        if root is None:
            return ui.p("Project directory unavailable.", class_=_MUTED)
        name = str(proj.get("name") or root.name)
        for rel in list_project_dirs(root):
            if rel == ".":
                choices[str(root)] = f"{name}/"
            else:
                choices[str(root / rel)] = f"{rel}/"
        if not choices:
            return ui.p("Project directory unavailable.", class_=_MUTED)
    for path, extra_label in (extra or {}).items():
        choices.setdefault(str(path), extra_label)

    matched = _match_choice(selected, choices) if selected else ""
    if default_label is not None:
        ordered = {"": default_label, **choices}
        sel = matched
    else:
        ordered = choices
        sel = matched or (str(root) if root is not None else next(iter(choices)))
    return ui.input_select(select_id, label, choices=ordered, selected=sel)
