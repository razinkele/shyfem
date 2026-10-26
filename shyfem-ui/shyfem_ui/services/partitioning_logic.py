"""Pure-logic helpers for the Partitioning page.

This module is the test-friendly extraction of logic that previously lived
inline inside `pages/partitioning.py` reactive handlers. The page wires
these helpers into Shiny reactive state; testing happens here.
"""

from __future__ import annotations

from pathlib import Path


def analyze_partitions(elem_grd: Path) -> tuple[dict, dict]:
    """Partition stats and the element-to-partition map from shyparts' output.

    shyparts writes ``<grd>.<np>.elem.grd``: the input grid with each
    element's type set to its partition (1..np). It writes no ``.par``
    files, which this used to look for (M-01).

    Returns:
        (stats, partition_map): stats has num_partitions, partition_files and
        elements_per_partition (partition 1 first); partition_map maps an
        element id to its 0-based partition index.
    """
    elem_grd = Path(elem_grd)
    stats: dict = {"num_partitions": 0, "partition_files": [], "elements_per_partition": []}
    pmap: dict[int, int] = {}
    if not elem_grd.is_file():
        return stats, pmap
    counts: dict[int, int] = {}
    with open(elem_grd) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 3 or parts[0] != "2":
                continue
            try:
                elem_id, part = int(parts[1]), int(parts[2])
            except ValueError:
                continue
            pmap[elem_id] = part - 1
            counts[part] = counts.get(part, 0) + 1
    if counts:
        n = max(counts)
        stats["num_partitions"] = n
        stats["partition_files"] = [str(elem_grd)]
        stats["elements_per_partition"] = [counts.get(k, 0) for k in range(1, n + 1)]
    return stats, pmap


def collect_shyparts_outputs(grd_file: Path, output_dir: Path, np_val: int) -> list[str]:
    """shyparts' output files, all in ``output_dir``.

    It writes ``<grd>.<np>.node.grd`` and ``<grd>.<np>.elem.grd`` next to the
    INPUT grid and ``partition.<np>.txt`` in its working folder; the two
    grids are moved into ``output_dir`` when that is elsewhere.
    """
    grd_file, output_dir = Path(grd_file), Path(output_dir)
    stem = grd_file.name[: -len(grd_file.suffix)] if grd_file.suffix else grd_file.name
    files = []
    for kind in ("node", "elem"):
        made = grd_file.parent / f"{stem}.{np_val}.{kind}.grd"
        target = output_dir / made.name
        if made.is_file() and made.resolve() != target.resolve():
            made.replace(target)
        if target.is_file():
            files.append(str(target))
    table = output_dir / f"partition.{np_val}.txt"
    if table.is_file():
        files.append(str(table))
    return files


def compute_load_balance(elements: list[int]) -> dict:
    """Compute load-balance metrics from per-partition element counts.

    Args:
        elements: List of element counts, one per partition.

    Returns:
        Dict with: n_parts, avg, min, max, imbalance_pct, labels (list of "P0".."Pn"),
        is_empty (True if elements is empty or all zero).
    """
    n_parts = len(elements)
    if n_parts == 0 or sum(elements) == 0:
        return {
            "n_parts": n_parts,
            "avg": 0.0,
            "min": 0,
            "max": 0,
            "imbalance_pct": 0.0,
            "labels": [f"P{i}" for i in range(n_parts)],
            "is_empty": True,
        }
    avg = sum(elements) / n_parts
    e_min = min(elements)
    e_max = max(elements)
    imbalance_pct = (e_max - e_min) / avg * 100.0 if avg > 0 else 0.0
    return {
        "n_parts": n_parts,
        "avg": avg,
        "min": e_min,
        "max": e_max,
        "imbalance_pct": imbalance_pct,
        "labels": [f"P{i}" for i in range(n_parts)],
        "is_empty": False,
    }


def validate_partition_files(files: list[str | Path]) -> list[tuple[str, str]]:
    """Check existence + size of each partition file.

    Args:
        files: Paths (string or Path) to partition files.

    Returns:
        List of (filename, status) tuples where status is either
        "<n> bytes - OK" or "MISSING".
    """
    results: list[tuple[str, str]] = []
    for f in files:
        path = Path(f)
        if path.exists():
            size = path.stat().st_size
            results.append((path.name, f"{size:,} bytes - OK"))
        else:
            results.append((path.name, "MISSING"))
    return results
