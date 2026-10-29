"""Frozen copies of the grid-map builders as they were before V-06.

They are the oracle for tests/test_grid_map_vectorized.py: the vectorized
builders must produce the same geometry. Not production code.
"""
# ruff: noqa
# fmt: off

import math

from pyproj import Transformer

from shyfem_ui.components.grid_map import (
    PARTITION_COLORS,
    _compute_quality,
    _depth_to_colors,
    _detect_projected_crs,
    _is_geographic,
    _quality_to_colors,
    _warned_unprojected,
    _WARNED_MAX,
    _logger,
)
from shyfem_ui.services.parser_grd import GrdFile


def reference_lonlat(
    grd: GrdFile,
    epsg: int | None = None,
) -> dict[int, list[float]]:
    """Return ``{node_id: [lon, lat]}`` for every node in *grd*.

    Parameters
    ----------
    grd
        Parsed grid file.
    epsg
        Source EPSG code for reprojection (e.g. 32630 for UTM 30N).
        If ``None``, auto-detection is attempted (works for Gauss-Boaga;
        UTM requires explicit EPSG).
    """
    if not grd.nodes:
        return {}

    if _is_geographic(grd) and epsg is None:
        return {nid: [float(node.x), float(node.y)] for nid, node in grd.nodes.items()}

    # Projected grid — use explicit EPSG or try auto-detection
    source_epsg = epsg or _detect_projected_crs(grd)
    if source_epsg is None:
        key = (id(grd), epsg)
        if key not in _warned_unprojected:
            _logger.warning(
                "Could not determine projection for grid; "
                "using raw coordinates (set EPSG in map controls)"
            )
            if len(_warned_unprojected) >= _WARNED_MAX:
                _warned_unprojected.clear()
            _warned_unprojected.add(key)
        return {nid: [float(node.x), float(node.y)] for nid, node in grd.nodes.items()}

    t = Transformer.from_crs(source_epsg, 4326, always_xy=True)
    result: dict[int, list[float]] = {}
    for nid, node in grd.nodes.items():
        lng, lat = t.transform(float(node.x), float(node.y))
        result[nid] = [lng, lat]
    return result


def reference_edge_data(grd: GrdFile, epsg: int | None = None) -> list[dict]:
    """Build deduplicated wireframe edges for all elements.

    Shared edges between adjacent elements appear only once.

    Returns
    -------
    list[dict]
        Each dict has ``{"path": [[lon1, lat1], [lon2, lat2]]}``.
    """
    if not grd.elements:
        return []

    lonlat = reference_lonlat(grd, epsg=epsg)
    seen: set[tuple[int, int]] = set()
    edges: list[dict] = []

    for elem in grd.elements.values():
        n = len(elem.nodes)
        for i in range(n):
            a = elem.nodes[i]
            b = elem.nodes[(i + 1) % n]
            key = (min(a, b), max(a, b))
            if key in seen:
                continue
            seen.add(key)
            if a not in lonlat or b not in lonlat:
                continue
            edges.append({"path": [lonlat[a], lonlat[b]]})

    return edges


def reference_mesh_geometry(
    grd: GrdFile,
    mode: str = "depth",
    colorscale: str = "viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
    epsg: int | None = None,
) -> dict:
    """Convert a :class:`GrdFile` into indexed mesh geometry for ``simple_mesh_layer``.

    Vertex positions are in **metres** relative to the mesh centre, using
    the deck.gl ``METER_OFFSETS`` coordinate system.  Vertices are duplicated
    per element so that per-element coloring is preserved.

    Parameters
    ----------
    grd
        Parsed grid.
    mode
        Coloring mode: ``"depth"``, ``"depth_3d"``, ``"quality"``,
        ``"partitions"``, ``"boundaries"``.
    colorscale
        Palette name for depth coloring (key in :data:`PALETTES`).
    elevation_scale
        Vertical exaggeration for ``"depth_3d"`` mode.
    partition_map
        ``{elem_id: partition_index}`` for partition coloring.
    epsg
        Source EPSG code for coordinate reprojection.

    Returns
    -------
    dict
        Keys: ``positions``, ``normals``, ``colors`` (flat float lists),
        ``indices`` (flat int list), ``center`` (``[lon, lat]``),
        ``n_vertices``, ``n_triangles``.
    """
    lonlat = reference_lonlat(grd, epsg=epsg)

    # Compute centre in lon/lat
    all_lons = [pos[0] for pos in lonlat.values()]
    all_lats = [pos[1] for pos in lonlat.values()]
    ctr_lon = (min(all_lons) + max(all_lons)) / 2
    ctr_lat = (min(all_lats) + max(all_lats)) / 2

    # Metres-per-degree at centre latitude
    m_per_deg_lon = 111_320 * math.cos(math.radians(ctr_lat))
    m_per_deg_lat = 110_540

    z_scale = elevation_scale if mode == "depth_3d" else 0.0

    # Gather per-element data (same logic as _build_triangle_data)
    elements_data: list[dict] = []
    all_depths: list[float] = []
    all_qualities: list[float] = []

    for elem in grd.elements.values():
        node_coords: list[list[float]] = []
        node_depths: list[float] = []
        for nid in elem.nodes:
            if nid not in lonlat:
                break
            node_coords.append(lonlat[nid])
            node = grd.nodes.get(nid)
            d = node.depth if (node and node.depth is not None) else 0.0
            node_depths.append(d)
        else:
            avg_depth = sum(node_depths) / len(node_depths) if node_depths else 0.0
            quality = _compute_quality(node_coords)
            elements_data.append(
                {
                    "elem": elem,
                    "coords": node_coords,
                    "node_depths": node_depths,
                    "avg_depth": avg_depth,
                    "quality": quality,
                }
            )
            all_depths.append(avg_depth)
            all_qualities.append(quality)

    empty = {
        "positions": [],
        "normals": [],
        "colors": [],
        "indices": [],
        "center": [round(ctr_lon, 5), round(ctr_lat, 5)],
        "n_vertices": 0,
        "n_triangles": 0,
    }
    if not elements_data:
        return empty

    # Compute per-element RGBA colors (int 0-255)
    if mode in ("depth", "depth_3d"):
        elem_colors = _depth_to_colors(all_depths, colorscale)
    elif mode == "quality":
        elem_colors = _quality_to_colors(all_qualities)
    elif mode == "partitions":
        elem_colors = [
            PARTITION_COLORS[(partition_map or {}).get(ed["elem"].id, 0) % len(PARTITION_COLORS)]
            for ed in elements_data
        ]
    else:  # boundaries
        elem_colors = [[200, 200, 200, 80]] * len(elements_data)

    # Build geometry with duplicated vertices per element
    positions: list[float] = []
    colors: list[float] = []
    indices: list[int] = []
    vertex_idx = 0

    for i, ed in enumerate(elements_data):
        c = elem_colors[i]
        r, g, b = c[0] / 255.0, c[1] / 255.0, c[2] / 255.0

        coords = ed["coords"]
        nd = ed["node_depths"]
        n_verts = len(coords)

        for j in range(n_verts):
            lon, lat = coords[j]
            dx = (lon - ctr_lon) * m_per_deg_lon
            dy = (lat - ctr_lat) * m_per_deg_lat
            dz = abs(nd[j]) * z_scale
            positions.extend([dx, dy, dz])
            colors.extend([round(r, 3), round(g, 3), round(b, 3)])

        if n_verts >= 3:
            indices.extend([vertex_idx, vertex_idx + 1, vertex_idx + 2])
            if n_verts == 4:
                indices.extend([vertex_idx, vertex_idx + 2, vertex_idx + 3])
        vertex_idx += n_verts

    # Compute per-vertex normals (average of adjacent face normals)
    normals = [0.0] * len(positions)
    for fi in range(0, len(indices), 3):
        i0, i1, i2 = indices[fi], indices[fi + 1], indices[fi + 2]
        p0 = positions[i0 * 3 : i0 * 3 + 3]
        p1 = positions[i1 * 3 : i1 * 3 + 3]
        p2 = positions[i2 * 3 : i2 * 3 + 3]
        e1 = [p1[k] - p0[k] for k in range(3)]
        e2 = [p2[k] - p0[k] for k in range(3)]
        nx = e1[1] * e2[2] - e1[2] * e2[1]
        ny = e1[2] * e2[0] - e1[0] * e2[2]
        nz = e1[0] * e2[1] - e1[1] * e2[0]
        for vi in (i0, i1, i2):
            normals[vi * 3] += nx
            normals[vi * 3 + 1] += ny
            normals[vi * 3 + 2] += nz

    for vi in range(len(positions) // 3):
        nx, ny, nz = normals[vi * 3], normals[vi * 3 + 1], normals[vi * 3 + 2]
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        normals[vi * 3] = round(nx / length, 4)
        normals[vi * 3 + 1] = round(ny / length, 4)
        normals[vi * 3 + 2] = round(nz / length, 4)

    positions = [round(v, 2) for v in positions]

    return {
        "positions": positions,
        "normals": normals,
        "colors": colors,
        "indices": indices,
        "center": [round(ctr_lon, 5), round(ctr_lat, 5)],
        "n_vertices": len(positions) // 3,
        "n_triangles": len(indices) // 3,
    }
