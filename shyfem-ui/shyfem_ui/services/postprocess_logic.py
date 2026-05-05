"""Pure-logic helpers for the Postprocess page.

Extracted from `pages/postprocess.py` to make the parsing, file
discovery, formatting, and CLI-option construction independently
testable. The page imports these and wires them into Shiny reactive
state.
"""

from __future__ import annotations

import re
from pathlib import Path


def format_size(size: int) -> str:
    """Format a byte count as a human-readable string (B / KB / MB)."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def parse_shyelab_info(output: str) -> dict:
    """Parse shyelab -info output into a structured dictionary.

    Handles the Fortran write(6,*) output format from io_shy.f90's shy_info
    subroutine, including:
    - Label: value pairs (main file info)
    - Basin info (nkn = N  nel = N format)
    - Variable descriptions table
    - Layer depth listings
    """
    info = {}
    lines = output.splitlines()
    i = 0

    variables = []
    layer_depths = []
    in_variables = False
    parsing_layer_values = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        i += 1

        if not stripped:
            in_variables = False
            parsing_layer_values = False
            continue

        # Detect section headers
        if "information on shy file" in stripped.lower():
            continue

        # Variable descriptions table
        if "total number of available variables" in stripped.lower():
            match = re.search(r"(\d+)", stripped)
            if match:
                info["Total Variables"] = match.group(1)
            continue

        if "varnum" in stripped.lower() and "varid" in stripped.lower():
            in_variables = True
            continue

        if in_variables:
            var_match = re.match(r"\s*(\d+)\s+(\d+)\s*(.*)", stripped)
            if var_match:
                var_name = var_match.group(3).strip()
                variables.append(var_name)
                continue
            else:
                in_variables = False

        # Layer depths header
        if re.match(r"levels\s*:", stripped, re.IGNORECASE):
            match = re.search(r":\s*(\d+)", stripped)
            if match:
                info["Levels"] = match.group(1)
            parsing_layer_values = True
            continue

        # Layer depth values
        if parsing_layer_values:
            floats = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", stripped)
            if floats:
                layer_depths.extend(floats)
                continue
            else:
                parsing_layer_values = False

        # Layer statistics table
        if (
            "layer" in stripped.lower()
            and "count" in stripped.lower()
            and "accumulated" in stripped.lower()
        ):
            continue

        # Basin info: nkn = N   nel = N
        basin_match = re.findall(r"(\w+)\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)", stripped)
        if basin_match and len(basin_match) >= 2 and "=" in stripped:
            for key, value in basin_match:
                display_key = key.lower()
                if display_key in ("nkn", "nel", "mbw", "ngr", "isphe"):
                    info[display_key] = value
                elif display_key in ("dcor", "dirn"):
                    info[display_key] = value
                elif "min" in display_key or "max" in display_key:
                    info[display_key] = value
            continue

        # Label: value pairs (primary shy_info output)
        colon_match = re.match(r"\s*([\w/]+)\s*:\s+(.*)", stripped)
        if colon_match:
            key = colon_match.group(1).strip()
            value = colon_match.group(2).strip()
            key_map = {
                "filename": "File Name",
                "nvers": "Version",
                "ftype": "File Type",
                "nkn": "Nodes",
                "nel": "Elements",
                "nlv": "Layers",
                "nvar": "Variables",
                "date": "Reference Date",
                "time": "Reference Time",
                "title": "Title",
                "femver": "SHYFEM Version",
                "hzmin/off": "Min Depth / Offset",
                "dtaver": "Averaging Period",
            }
            display_key = key_map.get(key, key)
            if value in ("T", ".TRUE."):
                value = "Yes"
            elif value in ("F", ".FALSE."):
                value = "No"
            info[display_key] = value
            continue

    if variables:
        info["Variable Names"] = ", ".join(variables)
    if layer_depths:
        info["Layer Depths"] = ", ".join(layer_depths)

    return info


def discover_shy_files(directory: str | Path) -> list[dict]:
    """Discover .shy files in a directory, returning sorted metadata.

    Each entry is a dict with keys: path, name, size_str.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        return []
    files = sorted(dir_path.glob("*.shy"), key=lambda p: p.name)
    result = []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        result.append({"path": str(f), "name": f.name, "size_str": format_size(size)})
    return result


def build_shyelab_options(
    *,
    operation: str,
    op_flags: list[str],
    custom_options: str = "",
    tmin: str | None = None,
    tmax: str | None = None,
    selected_vars: list[str] | None = None,
    scanned_vars_count: int = 0,
    selected_layer: str = "all",
) -> list[str]:
    """Build shyelab CLI option list from page-input values.

    Args:
        operation: One of "avg", "custom", etc. — the chosen operation key.
        op_flags: The flags list for the operation (from SHYELAB_OPERATIONS[op]["flags"]).
        custom_options: Free-text custom options (used only when operation == "custom").
        tmin, tmax: Optional time-range strings (passed through verbatim if non-empty).
        selected_vars: Variable filter list. If a strict subset of all scanned variables,
            each is added as ``-<var>``. Otherwise the filter is omitted (interpreted as
            "all").
        scanned_vars_count: Total number of scanned variables; used to detect "all
            selected".
        selected_layer: Layer selection ("all" or a specific layer string).

    Returns:
        List of CLI option strings ready to hand to shyelab.
    """
    if operation == "custom":
        return custom_options.split() if custom_options else []

    options = list(op_flags)

    if tmin:
        options.extend(["-tmin", tmin])
    if tmax:
        options.extend(["-tmax", tmax])

    if selected_vars and 0 < len(selected_vars) < scanned_vars_count:
        for var in selected_vars:
            options.append(f"-{var}")

    if selected_layer != "all":
        options.extend(["-layer", selected_layer])

    return options
