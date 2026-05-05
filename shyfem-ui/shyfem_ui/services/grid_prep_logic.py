"""Pure-logic helpers for the Grid Preparation page.

Extracted from `pages/grid_prep.py` for unit-testability. Helpers that
operate on the `GrdFile` parsed structure or on the dict returned by
`GrdParser.get_statistics()`. The page module re-exports these at
the same names so test files don't need migration.
"""

from __future__ import annotations

import json


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
