"""Pure-logic helpers for the Partitioning page.

This module is the test-friendly extraction of logic that previously lived
inline inside `pages/partitioning.py` reactive handlers. The page wires
these helpers into Shiny reactive state; testing happens here.
"""

from __future__ import annotations

from pathlib import Path


def parse_par_file(path: Path) -> list[int]:
    """Parse a shyparts .par file and return the list of element IDs.

    Each non-empty line is expected to start with an integer element ID.
    Malformed lines are silently skipped (consistent with the original
    page-handler behavior).

    Args:
        path: Path to the .par file. If it does not exist, returns [].

    Returns:
        List of int element IDs in file order.
    """
    if not path.exists():
        return []
    ids: list[int] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ids.append(int(line.split()[0]))
            except (ValueError, IndexError):
                continue
    return ids


def analyze_partitions(output_dir: Path, np_val: int) -> tuple[dict, dict]:
    """Walk partition.NNNN.par files and build stats + element-to-partition map.

    Args:
        output_dir: Directory containing partition.NNNN.par files.
        np_val: Number of partitions expected (loop bound).

    Returns:
        (stats, partition_map) where:
        - stats: dict with keys num_partitions, partition_files (list[str]),
          elements_per_partition (list[int])
        - partition_map: dict mapping element_id -> partition_index
    """
    stats: dict = {
        "num_partitions": np_val,
        "partition_files": [],
        "elements_per_partition": [],
    }
    pmap: dict[int, int] = {}
    for i in range(np_val):
        par_file = output_dir / f"partition.{i:04d}.par"
        if par_file.exists():
            stats["partition_files"].append(str(par_file))
            ids = parse_par_file(par_file)
            stats["elements_per_partition"].append(len(ids))
            for elem_id in ids:
                pmap[elem_id] = i
    return stats, pmap


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
