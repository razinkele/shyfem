"""Pure-logic helpers for the Grid Preparation page.

Extracted from `pages/grid_prep.py` for unit-testability. Helpers that
operate on the `GrdFile` parsed structure or on the dict returned by
`GrdParser.get_statistics()`. The page module re-exports these at
the same names so test files don't need migration.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from shyfem_ui.services.file_service import check_plain_file_name
from shyfem_ui.services.partitioning_logic import stage_grid


def stage_for_shypre(grd_path: Path, output_dir: Path) -> Path:
    """The grid shypre runs on, inside ``output_dir``; never overwrites a grid.

    Reuses an identical file of that name, copies when there is none, and
    keeps the copy (it sits next to the ``.bas``).

    Raises:
        ValueError: ``output_dir`` holds a different file of that name. It
            may be the copy an earlier run left there, which the page cannot
            tell from a user's file.
        OSError: the copy failed.
    """
    grd_path = Path(grd_path)
    try:
        staged, _ = stage_grid(grd_path, output_dir, folder="output directory")
    except ValueError:
        raise ValueError(
            f"The output directory already has a different {grd_path.name}. "
            "It may be the copy an earlier run left there: remove or rename it, "
            "or choose another output directory."
        ) from None
    return staged


def named_upload(temp_path: Path, uploaded_name: str) -> Path:
    """Copy an upload (Shiny stores it as ``0.grd``) under its own name.

    The copy goes to ``<temp folder>/named/<uploaded_name>``; ``temp_path`` is
    left alone. shypre names its ``.bas`` after the grid, so the name matters.

    Raises:
        ValueError: the name is empty, has a path separator (``/`` or
            ``\\``) or ``..``, or does not end in ``.grd``.
    """
    temp_path = Path(temp_path)
    try:
        check_plain_file_name(uploaded_name)
    except ValueError:
        raise ValueError(f"Invalid grid file name: {uploaded_name!r}") from None
    if "\\" in uploaded_name or not uploaded_name.endswith(".grd"):
        raise ValueError(f"Invalid grid file name: {uploaded_name!r}")
    dest = temp_path.parent / "named" / uploaded_name
    dest.parent.mkdir(exist_ok=True)
    shutil.copy2(temp_path, dest)
    return dest


def grid_stats_to_json(stats: dict, grid_name: str) -> str:
    """Serialize grid statistics to formatted JSON.

    Sets are coerced to sorted lists for stable diff-friendly output.

    Args:
        stats: Dictionary from GrdParser.get_statistics().
        grid_name: Name of the grid file for metadata.

    Returns:
        Pretty-printed JSON string.
    """

    def _default(obj):
        if isinstance(obj, set):
            return sorted(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    payload = {
        "grid_name": grid_name,
        "statistics": stats,
    }
    return json.dumps(payload, indent=4, default=_default)


def compute_boundary_summary(grd) -> list[dict]:
    """Summarize boundary line assignments.

    Args:
        grd: Anything with a `.lines` mapping where each line has
            `.line_type` and `.nodes` (list of int).

    Returns:
        List of dicts with `line_id`, `line_type`, `node_count`,
        `node_range_str` (e.g. "1-50"), sorted by `line_id`.
    """
    result = []
    for lid, line in sorted(grd.lines.items()):
        nids = line.nodes
        node_range = f"{min(nids)}-{max(nids)}" if nids else ""
        result.append(
            {
                "line_id": lid,
                "line_type": line.line_type,
                "node_count": len(nids),
                "node_range_str": node_range,
            }
        )
    return result


def format_element_shape(elem) -> str:
    """Return a human-readable shape label for a grid element.

    Args:
        elem: Anything with `is_triangle`, `is_quad` properties and `.nodes`
            (list).

    Returns:
        "Tri" for triangles, "Quad" for quads, "<N>-gon" otherwise.
    """
    if elem.is_triangle:
        return "Tri"
    if elem.is_quad:
        return "Quad"
    return f"{len(elem.nodes)}-gon"
