"""Interactive grid map component using deck.gl (via shiny_deckgl).

Provides zoomable/pannable mesh visualization with:
- Mesh wireframe via path_layer (deduplicated edges)
- Filled triangles via polygon_layer (depth, quality, partitions, boundaries)
- Clickable nodes via scatterplot_layer
- Boundary line highlighting via path_layer
- Tooltip HTML on all features
"""

from __future__ import annotations

import math

from shiny_deckgl import (
    CARTO_DARK,
    CARTO_POSITRON,
    OSM_LIBERTY,
    PALETTE_CHLOROPHYLL,
    PALETTE_OCEAN,
    PALETTE_PLASMA,
    PALETTE_THERMAL,
    PALETTE_VIRIDIS,
    color_bins,
    path_layer,
    polygon_layer,
    scatterplot_layer,
)

from shyfem_ui.services.parser_grd import GrdFile

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------

BOUNDARY_COLORS: list[list[int]] = [
    [231, 76, 60, 255],    # red
    [46, 204, 113, 255],   # green
    [243, 156, 18, 255],   # orange
    [155, 89, 182, 255],   # purple
    [26, 188, 156, 255],   # teal
    [230, 126, 34, 255],   # dark orange
    [52, 152, 219, 255],   # blue
    [233, 30, 99, 255],    # pink
]

PARTITION_COLORS: list[list[int]] = [
    [31, 119, 180, 200],
    [255, 127, 14, 200],
    [44, 160, 44, 200],
    [214, 39, 40, 200],
    [148, 103, 189, 200],
    [140, 86, 75, 200],
    [227, 119, 194, 200],
    [127, 127, 127, 200],
    [188, 189, 34, 200],
    [23, 190, 207, 200],
    [174, 199, 232, 200],
    [255, 187, 120, 200],
    [152, 223, 138, 200],
    [255, 152, 150, 200],
    [197, 176, 213, 200],
    [196, 156, 148, 200],
    [247, 182, 210, 200],
    [199, 199, 199, 200],
    [219, 219, 141, 200],
    [158, 218, 229, 200],
]

# Map from user-facing palette name to shiny_deckgl palette
PALETTES: dict[str, list[list[int]]] = {
    "viridis": PALETTE_VIRIDIS,
    "plasma": PALETTE_PLASMA,
    "ocean": PALETTE_OCEAN,
    "thermal": PALETTE_THERMAL,
    "chlorophyll": PALETTE_CHLOROPHYLL,
}

# Map from user-facing basemap name to URL
BASEMAPS: dict[str, str] = {
    "positron": CARTO_POSITRON,
    "dark": CARTO_DARK,
    "osm": OSM_LIBERTY,
}

# RdYlGn-like palette for quality coloring (red=bad, green=good)
_QUALITY_PALETTE: list[list[int]] = [
    [215, 48, 39],    # 0.0 - red (bad)
    [253, 174, 97],   # ~0.2
    [254, 224, 139],  # ~0.4
    [217, 239, 139],  # ~0.6
    [145, 207, 96],   # ~0.8
    [26, 152, 80],    # 1.0 - green (good)
]


# ---------------------------------------------------------------------------
# Task 1: _get_lonlat
# ---------------------------------------------------------------------------

def _get_lonlat(grd: GrdFile) -> dict[int, list[float]]:
    """Return ``{node_id: [lon, lat]}`` for every node in *grd*.

    For geographic coordinate systems, ``x`` is longitude and ``y`` is
    latitude.  For Cartesian/UTM systems, the raw ``(x, y)`` values are
    returned as-is (the caller is responsible for any projection).
    """
    return {
        nid: [float(node.x), float(node.y)]
        for nid, node in grd.nodes.items()
    }


# ---------------------------------------------------------------------------
# Task 2: _build_edge_data
# ---------------------------------------------------------------------------

def _build_edge_data(grd: GrdFile) -> list[dict]:
    """Build deduplicated wireframe edges for all elements.

    Shared edges between adjacent elements appear only once.

    Returns
    -------
    list[dict]
        Each dict has ``{"path": [[lon1, lat1], [lon2, lat2]]}``.
    """
    if not grd.elements:
        return []

    lonlat = _get_lonlat(grd)
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


# ---------------------------------------------------------------------------
# Task 3: _build_triangle_data + helpers
# ---------------------------------------------------------------------------

def _compute_quality(coords: list[list[float]]) -> float:
    """Compute element quality as min(side) / max(side).

    Parameters
    ----------
    coords
        List of ``[x, y]`` vertex coordinates (at least 3).

    Returns
    -------
    float
        Quality ratio in ``[0, 1]``.  1.0 = equilateral, 0.0 = degenerate.
    """
    n = len(coords)
    sides: list[float] = []
    for i in range(n):
        j = (i + 1) % n
        dx = coords[j][0] - coords[i][0]
        dy = coords[j][1] - coords[i][1]
        sides.append(math.sqrt(dx * dx + dy * dy))
    max_side = max(sides)
    if max_side == 0.0:
        return 0.0
    return min(sides) / max_side


def _depth_to_colors(
    depths: list[float],
    palette_name: str,
) -> list[list[int]]:
    """Map depth values to RGBA colors using ``color_bins()``.

    Parameters
    ----------
    depths
        Scalar depth values (one per element).
    palette_name
        Key into :data:`PALETTES` (falls back to viridis).

    Returns
    -------
    list[list[int]]
        One ``[R, G, B, A]`` per input depth.
    """
    if not depths:
        return []
    palette = PALETTES.get(palette_name, PALETTE_VIRIDIS)
    return color_bins(depths, n_bins=6, palette=palette)


def _quality_to_colors(qualities: list[float]) -> list[list[int]]:
    """Map quality ratios ``[0..1]`` to RGBA using a RdYlGn palette.

    Parameters
    ----------
    qualities
        Quality ratios (one per element).

    Returns
    -------
    list[list[int]]
        One ``[R, G, B, A]`` per input quality.
    """
    if not qualities:
        return []
    return color_bins(qualities, n_bins=6, palette=_QUALITY_PALETTE)


def _build_triangle_data(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "viridis",
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
) -> list[dict]:
    """Build filled polygon data for deck.gl ``polygon_layer``.

    Parameters
    ----------
    grd
        Parsed grid.
    mode
        One of ``"mesh"``, ``"depth"``, ``"depth_3d"``, ``"quality"``,
        ``"partitions"``, ``"boundaries"``.
    colorscale
        Palette name for depth coloring (key in :data:`PALETTES`).
    elevation_scale
        Multiplier for 3-D elevation (used only when *mode* = ``"depth_3d"``).
    partition_map
        ``{elem_id: partition_index}`` for partition coloring.

    Returns
    -------
    list[dict]
        Each dict contains at minimum: ``polygon``, ``fill_color``,
        ``elem_id``, ``depth``, ``quality``, ``tooltip_html``.
        ``"depth_3d"`` mode also adds ``elevation``.
    """
    if mode == "mesh":
        return []

    if mode == "partitions" and not partition_map:
        return []

    if not grd.elements or not grd.nodes:
        return []

    lonlat = _get_lonlat(grd)

    # Gather per-element data
    records: list[dict] = []
    all_depths: list[float] = []
    all_qualities: list[float] = []

    for elem in grd.elements.values():
        coords = []
        node_depths: list[float] = []
        for nid in elem.nodes:
            if nid not in lonlat:
                break
            coords.append(lonlat[nid])
            node = grd.nodes.get(nid)
            d = node.depth if (node and node.depth is not None) else 0.0
            node_depths.append(d)
        else:
            # All nodes resolved
            avg_depth = sum(node_depths) / len(node_depths) if node_depths else 0.0
            quality = _compute_quality(coords)
            records.append({
                "polygon": coords,
                "elem_id": elem.id,
                "depth": round(avg_depth, 6),
                "quality": round(quality, 6),
                "node_depths": node_depths,
            })
            all_depths.append(avg_depth)
            all_qualities.append(quality)

    if not records:
        return []

    # Compute colors based on mode
    if mode in ("depth", "depth_3d"):
        colors = _depth_to_colors(all_depths, colorscale)
    elif mode == "quality":
        colors = _quality_to_colors(all_qualities)
    elif mode == "partitions":
        colors = []
        for rec in records:
            part = partition_map.get(rec["elem_id"], 0)  # type: ignore[union-attr]
            colors.append(PARTITION_COLORS[part % len(PARTITION_COLORS)])
    elif mode == "boundaries":
        colors = [[200, 200, 200, 80]] * len(records)
    else:
        colors = [[200, 200, 200, 255]] * len(records)

    # Build final output
    result: list[dict] = []
    for i, rec in enumerate(records):
        entry: dict = {
            "polygon": rec["polygon"],
            "fill_color": colors[i],
            "elem_id": rec["elem_id"],
            "depth": rec["depth"],
            "quality": rec["quality"],
            "tooltip_html": _triangle_tooltip(rec, mode),
        }
        if mode == "depth_3d":
            entry["elevation"] = rec["depth"] * elevation_scale
        result.append(entry)

    return result


def _triangle_tooltip(rec: dict, mode: str) -> str:
    """Build tooltip HTML for a triangle element."""
    parts = [f"<b>Elem {rec['elem_id']}</b>"]
    if mode in ("depth", "depth_3d", "boundaries"):
        parts.append(f"Depth: {rec['depth']:.2f}")
    if mode == "quality":
        parts.append(f"Quality: {rec['quality']:.3f}")
    if mode == "partitions":
        parts.append(f"Depth: {rec['depth']:.2f}")
    return "<br>".join(parts)


# ---------------------------------------------------------------------------
# Task 4: _build_boundary_data + _build_node_data
# ---------------------------------------------------------------------------

def _build_boundary_data(grd: GrdFile) -> dict[int, list[dict]]:
    """Build boundary line data grouped by line type.

    Parameters
    ----------
    grd
        Parsed grid.

    Returns
    -------
    dict[int, list[dict]]
        ``{line_type: [{"path": [[lon,lat],...], "line_id": int,
        "tooltip_html": str}, ...]}``
    """
    if not grd.lines:
        return {}

    lonlat = _get_lonlat(grd)
    grouped: dict[int, list[dict]] = {}

    for line in grd.lines.values():
        path: list[list[float]] = []
        for nid in line.nodes:
            if nid in lonlat:
                path.append(lonlat[nid])
        if len(path) < 2:
            continue

        tooltip = (
            f"<b>Boundary {line.id}</b><br>"
            f"Type: {line.line_type}<br>"
            f"Nodes: {len(line.nodes)}"
        )

        entry = {
            "path": path,
            "line_id": line.id,
            "tooltip_html": tooltip,
        }

        if line.line_type not in grouped:
            grouped[line.line_type] = []
        grouped[line.line_type].append(entry)

    return grouped


def _build_node_data(grd: GrdFile) -> list[dict]:
    """Build node data for deck.gl ``scatterplot_layer``.

    Parameters
    ----------
    grd
        Parsed grid.

    Returns
    -------
    list[dict]
        Each dict: ``{"position": [lon,lat], "node_id": int,
        "depth": float, "node_type": int, "tooltip_html": str}``.
    """
    if not grd.nodes:
        return []

    lonlat = _get_lonlat(grd)
    result: list[dict] = []

    for nid, node in grd.nodes.items():
        depth = node.depth if node.depth is not None else 0.0
        pos = lonlat[nid]

        parts = [f"<b>Node {nid}</b>"]
        parts.append(f"Lon: {pos[0]:.6f}")
        parts.append(f"Lat: {pos[1]:.6f}")
        if node.depth is not None:
            parts.append(f"Depth: {node.depth:.2f}")
        else:
            parts.append("No depth")
        parts.append(f"Type: {node.node_type}")
        tooltip = "<br>".join(parts)

        result.append({
            "position": pos,
            "node_id": nid,
            "depth": float(depth),
            "node_type": node.node_type,
            "tooltip_html": tooltip,
        })

    return result


# ---------------------------------------------------------------------------
# Task 5: build_layers
# ---------------------------------------------------------------------------

def build_layers(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "viridis",
    show_boundaries: bool = False,
    show_nodes: bool = False,
    elevation_scale: float = 1.0,
    partition_map: dict[int, int] | None = None,
) -> list[dict]:
    """Assemble deck.gl layers for the given grid and display mode.

    Parameters
    ----------
    grd
        Parsed grid file.
    mode
        Display mode: ``"mesh"``, ``"depth"``, ``"depth_3d"``,
        ``"boundaries"``, ``"quality"``, ``"partitions"``.
    colorscale
        Palette name for depth coloring (key in :data:`PALETTES`).
    show_boundaries
        Overlay boundary lines regardless of *mode*.
    show_nodes
        Overlay node scatter points.
    elevation_scale
        Multiplier for 3-D extrusion (``"depth_3d"`` mode only).
    partition_map
        ``{elem_id: partition_index}`` for partition coloring.

    Returns
    -------
    list[dict]
        Layer definitions suitable for ``shiny_deckgl.output_deckgl``.
    """
    # Empty grid => no layers
    if not grd.nodes or not grd.elements:
        return []

    layers: list[dict] = []

    # --- Shared polygon layer kwargs ---
    _poly_common: dict = {
        "pickable": True,
        "opacity": 0.85,
        "autoHighlight": True,
        "highlightColor": [255, 255, 255, 80],
        "getFillColor": "@@d.fill_color",
        "getPolygon": "@@d.polygon",
        "getLineColor": [0, 0, 0, 0],
        "getLineWidth": 0,
    }

    # --- Wireframe edge data (reused across modes) ---
    edge_data = _build_edge_data(grd)

    # --- Build layers per mode ---

    if mode == "mesh":
        # Wireframe only, blue edges
        layers.append(path_layer(
            "wireframe",
            edge_data,
            getPath="@@d.path",
            getColor=[45, 156, 186, 255],
            widthMinPixels=1,
            pickable=False,
        ))

    elif mode == "depth":
        # Filled polygons + thin gray wireframe
        tri_data = _build_triangle_data(grd, mode=mode, colorscale=colorscale)
        layers.append(polygon_layer(
            "triangles",
            tri_data,
            **_poly_common,
        ))
        layers.append(path_layer(
            "wireframe",
            edge_data,
            getPath="@@d.path",
            getColor=[150, 150, 150, 80],
            widthMinPixels=0.5,
            pickable=False,
        ))

    elif mode == "depth_3d":
        # Filled polygons with extrusion, NO wireframe
        tri_data = _build_triangle_data(
            grd, mode=mode, colorscale=colorscale,
            elevation_scale=elevation_scale,
        )
        layers.append(polygon_layer(
            "triangles",
            tri_data,
            **_poly_common,
            extruded=True,
            getElevation="@@d.elevation",
        ))

    elif mode == "boundaries":
        # Light filled polygons + thin wireframe + bold boundary lines
        tri_data = _build_triangle_data(grd, mode=mode, colorscale=colorscale)
        layers.append(polygon_layer(
            "triangles",
            tri_data,
            **_poly_common,
        ))
        layers.append(path_layer(
            "wireframe",
            edge_data,
            getPath="@@d.path",
            getColor=[150, 150, 150, 80],
            widthMinPixels=0.5,
            pickable=False,
        ))
        # Add bold boundary path_layers
        boundary_data = _build_boundary_data(grd)
        for btype, blines in boundary_data.items():
            color = BOUNDARY_COLORS[btype % len(BOUNDARY_COLORS)]
            layers.append(path_layer(
                f"boundary_{btype}",
                blines,
                getPath="@@d.path",
                getColor=color,
                widthMinPixels=3,
                pickable=True,
            ))

    elif mode == "quality":
        # Filled polygons + thin wireframe
        tri_data = _build_triangle_data(grd, mode=mode, colorscale=colorscale)
        layers.append(polygon_layer(
            "triangles",
            tri_data,
            **_poly_common,
        ))
        layers.append(path_layer(
            "wireframe",
            edge_data,
            getPath="@@d.path",
            getColor=[150, 150, 150, 80],
            widthMinPixels=0.5,
            pickable=False,
        ))

    elif mode == "partitions":
        # Filled polygons only (no wireframe)
        tri_data = _build_triangle_data(
            grd, mode=mode, colorscale=colorscale,
            partition_map=partition_map,
        )
        layers.append(polygon_layer(
            "triangles",
            tri_data,
            **_poly_common,
        ))

    # --- Optional boundary overlay (not in boundaries mode, already done) ---
    if show_boundaries and mode != "boundaries":
        boundary_data = _build_boundary_data(grd)
        for btype, blines in boundary_data.items():
            color = BOUNDARY_COLORS[btype % len(BOUNDARY_COLORS)]
            layers.append(path_layer(
                f"boundary_{btype}",
                blines,
                getPath="@@d.path",
                getColor=color,
                widthMinPixels=3,
                pickable=True,
            ))

    # --- Optional node overlay ---
    if show_nodes:
        node_data = _build_node_data(grd)
        layers.append(scatterplot_layer(
            "nodes",
            node_data,
            getPosition="@@d.position",
            getFillColor=[255, 60, 60, 220],
            radiusMinPixels=3,
            radiusMaxPixels=6,
            pickable=True,
        ))

    return layers


# ---------------------------------------------------------------------------
# Task 6: _compute_view_state
# ---------------------------------------------------------------------------

def _compute_view_state(
    grd: GrdFile,
    is_3d: bool = False,
) -> dict:
    """Compute an initial deck.gl view state that fits the grid bounds.

    Parameters
    ----------
    grd
        Parsed grid file.
    is_3d
        If ``True``, tilt the camera for 3-D perspective.

    Returns
    -------
    dict
        View state with ``longitude``, ``latitude``, ``zoom``,
        ``pitch``, ``bearing``, and ``bounds``.
    """
    if not grd.nodes:
        return {
            "longitude": 0,
            "latitude": 0,
            "zoom": 2,
            "pitch": 0,
            "bearing": 0,
            "bounds": [[-180, -90], [180, 90]],
        }

    xmin, ymin, xmax, ymax = grd.get_bounds()

    center_lon = (xmin + xmax) / 2.0
    center_lat = (ymin + ymax) / 2.0

    dx = max(xmax - xmin, 1e-6)
    dy = max(ymax - ymin, 1e-6)
    extent = max(dx, dy)
    zoom = math.log2(360.0 / extent)
    zoom = max(0, min(20, zoom))

    pitch = 45 if is_3d else 0
    bearing = -30 if is_3d else 0

    return {
        "longitude": center_lon,
        "latitude": center_lat,
        "zoom": zoom,
        "pitch": pitch,
        "bearing": bearing,
        "bounds": [[xmin, ymin], [xmax, ymax]],
    }


# ---------------------------------------------------------------------------
# Backward-compatibility stubs (removed when migration is complete)
# ---------------------------------------------------------------------------

def _build_edge_arrays(grd: GrdFile):
    """Legacy Plotly edge builder -- kept for backward compatibility.

    Returns (edge_x, edge_y, x, y, node_ids, node_map).
    """
    import numpy as np

    node_ids = sorted(grd.nodes.keys())
    node_map = {nid: i for i, nid in enumerate(node_ids)}
    x = np.array([grd.nodes[nid].x for nid in node_ids])
    y = np.array([grd.nodes[nid].y for nid in node_ids])

    edge_x: list = []
    edge_y: list = []
    for elem in grd.elements.values():
        indices = [node_map.get(nid) for nid in elem.nodes]
        indices = [i for i in indices if i is not None]
        if len(indices) < 3:
            continue
        for i in range(len(indices)):
            j = (i + 1) % len(indices)
            edge_x.extend([float(x[indices[i]]), float(x[indices[j]]), None])
            edge_y.extend([float(y[indices[i]]), float(y[indices[j]]), None])

    return edge_x, edge_y, x, y, node_ids, node_map


def build_mesh_figure(
    grd: GrdFile,
    mode: str = "mesh",
    colorscale: str = "Viridis",
    show_boundaries: bool = True,
    show_nodes: bool = False,
    partition_map: dict[int, int] | None = None,
):
    """Legacy Plotly figure builder -- kept for backward compatibility.

    Will be removed when the full deck.gl migration is complete (Task 7+).
    """
    import numpy as np  # noqa: E402
    import plotly.graph_objects as go  # noqa: E402

    if not grd.nodes:
        fig = go.Figure()
        fig.add_annotation(
            text="No grid data loaded",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font_size=18, font_color="gray",
        )
        fig.update_layout(height=600)
        return fig

    edge_x, edge_y, x, y, node_ids, node_map = _build_edge_arrays(grd)
    fig = go.Figure()

    if mode == "mesh":
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="#2D9CBA", width=0.5),
            hoverinfo="skip", name="Mesh",
        ))
    elif mode == "depth":
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="rgba(200,200,200,0.3)", width=0.3),
            hoverinfo="skip", showlegend=False,
        ))
        depths = np.array([
            grd.nodes[nid].depth if grd.nodes[nid].depth is not None else 0.0
            for nid in node_ids
        ])
        if not np.all(depths == 0):
            fig.add_trace(go.Scattergl(
                x=x.tolist(), y=y.tolist(), mode="markers",
                marker=dict(size=4, color=depths.tolist(), colorscale=colorscale,
                            colorbar=dict(title="Depth", thickness=15), showscale=True),
                hoverinfo="text", name="Depth",
            ))
    elif mode == "quality":
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="rgba(200,200,200,0.3)", width=0.3),
            hoverinfo="skip", showlegend=False,
        ))
        qualities, cx_arr, cy_arr = [], [], []
        for elem in grd.elements.values():
            if not elem.is_triangle:
                continue
            indices = [node_map.get(nid) for nid in elem.nodes]
            if any(i is None for i in indices):
                continue
            ex, ey = x[indices], y[indices]
            sides = [
                np.sqrt((ex[(i + 1) % 3] - ex[i]) ** 2 + (ey[(i + 1) % 3] - ey[i]) ** 2)
                for i in range(3)
            ]
            q = min(sides) / max(sides) if max(sides) > 0 else 0
            qualities.append(q)
            cx_arr.append(float(np.mean(ex)))
            cy_arr.append(float(np.mean(ey)))
        if qualities:
            fig.add_trace(go.Scattergl(
                x=cx_arr, y=cy_arr, mode="markers",
                marker=dict(size=5, color=qualities, colorscale="RdYlGn",
                            cmin=0, cmax=1,
                            colorbar=dict(title="Quality", thickness=15), showscale=True),
                hoverinfo="text", name="Quality",
            ))
    elif mode == "boundaries":
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="rgba(200,200,200,0.4)", width=0.3),
            hoverinfo="skip", showlegend=False,
        ))
        show_boundaries = True
    elif mode == "partitions" and partition_map:
        num_parts = max(partition_map.values()) + 1 if partition_map else 1
        _pcolors = [
            "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
            "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
        ]
        part_edges: dict[int, tuple[list, list]] = {p: ([], []) for p in range(num_parts)}
        for elem in grd.elements.values():
            part = partition_map.get(elem.id, 0)
            indices = [node_map.get(nid) for nid in elem.nodes]
            indices = [i for i in indices if i is not None]
            if len(indices) < 3:
                continue
            for i in range(len(indices)):
                j = (i + 1) % len(indices)
                part_edges[part][0].extend([float(x[indices[i]]), float(x[indices[j]]), None])
                part_edges[part][1].extend([float(y[indices[i]]), float(y[indices[j]]), None])
        for p in range(num_parts):
            color = _pcolors[p % len(_pcolors)]
            if part_edges[p][0]:
                fig.add_trace(go.Scattergl(
                    x=part_edges[p][0], y=part_edges[p][1], mode="lines",
                    line=dict(color=color, width=0.7), hoverinfo="skip", name=f"P{p}",
                ))
    else:
        fig.add_trace(go.Scattergl(
            x=edge_x, y=edge_y, mode="lines",
            line=dict(color="#2D9CBA", width=0.5),
            hoverinfo="skip", name="Mesh",
        ))

    if show_boundaries and grd.lines:
        _bcolors = ["#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
                     "#1abc9c", "#e67e22", "#3498db", "#e91e63"]
        line_types = sorted(grd.get_line_types())
        for lt_idx, lt in enumerate(line_types):
            bx, by = [], []
            for line in grd.lines.values():
                if line.line_type != lt:
                    continue
                indices = [node_map.get(nid) for nid in line.nodes]
                indices = [i for i in indices if i is not None]
                if len(indices) < 2:
                    continue
                for i in range(len(indices) - 1):
                    bx.extend([float(x[indices[i]]), float(x[indices[i + 1]]), None])
                    by.extend([float(y[indices[i]]), float(y[indices[i + 1]]), None])
            if bx:
                color = _bcolors[lt_idx % len(_bcolors)]
                fig.add_trace(go.Scattergl(
                    x=bx, y=by, mode="lines",
                    line=dict(color=color, width=3),
                    hoverinfo="skip", name=f"Boundary type {lt}",
                ))

    if show_nodes:
        fig.add_trace(go.Scattergl(
            x=x.tolist(), y=y.tolist(), mode="markers",
            marker=dict(size=3, color="red"),
            hoverinfo="text", name="Nodes",
        ))

    fig.update_layout(
        xaxis=dict(scaleanchor="y", scaleratio=1, title="X"),
        yaxis=dict(title="Y"),
        hovermode="closest", showlegend=True,
        margin=dict(l=50, r=20, t=60, b=50),
        height=600, dragmode="pan",
    )
    return fig


# ---------------------------------------------------------------------------
# Shiny module: grid_map_ui + grid_map_server (Task 7 — deck.gl)
# ---------------------------------------------------------------------------

from typing import Callable

from shiny import module, reactive, render, ui  # noqa: E402

from shiny_deckgl import (  # noqa: E402
    MapWidget,
    head_includes as deckgl_head_includes,
    zoom_widget,
)

# View-mode choices for the dropdown
_VIEW_MODES: dict[str, str] = {
    "mesh": "Mesh",
    "depth": "Depth",
    "depth_3d": "Depth 3D",
    "boundaries": "Boundaries",
    "quality": "Quality",
}

# User-facing palette names (keys of PALETTES dict defined above)
_PALETTE_CHOICES: dict[str, str] = {
    "viridis": "Viridis",
    "plasma": "Plasma",
    "ocean": "Ocean",
    "thermal": "Thermal",
    "chlorophyll": "Chlorophyll",
}

# User-facing basemap names (keys of BASEMAPS dict defined above)
_BASEMAP_CHOICES: dict[str, str] = {
    "positron": "Positron",
    "dark": "Dark",
    "osm": "OSM",
}


@module.ui
def grid_map_ui(height: str = "600px"):
    """Deck.gl interactive grid map UI.

    Includes map controls (view mode, palette, basemap, elevation slider,
    boundary/node toggles) and the MapWidget output.
    """
    # The MapWidget in the UI uses the bare ID; @module.ui auto-namespaces it.
    _map = MapWidget(
        id="deckgl_map",
        tooltip={"html": "{tooltip_html}"},
        picking_radius=5,
    )

    return ui.div(
        deckgl_head_includes(),
        # Controls row
        ui.div(
            ui.div(
                ui.input_select(
                    "map_mode",
                    "View",
                    choices=_VIEW_MODES,
                    selected="mesh",
                    width="120px",
                ),
                ui.input_select(
                    "map_colors",
                    "Colors",
                    choices=_PALETTE_CHOICES,
                    selected="viridis",
                    width="120px",
                ),
                ui.input_select(
                    "map_basemap",
                    "Basemap",
                    choices=_BASEMAP_CHOICES,
                    selected="positron",
                    width="120px",
                ),
                ui.panel_conditional(
                    "input.map_mode === 'depth_3d'",
                    ui.input_slider(
                        "elevation_scale",
                        "Elevation",
                        min=1,
                        max=50,
                        value=10,
                        width="140px",
                    ),
                ),
                ui.input_checkbox("show_boundaries", "Boundaries", value=True),
                ui.input_checkbox("show_nodes", "Nodes", value=False),
                class_="d-flex flex-wrap align-items-end gap-2",
            ),
            class_="mb-2",
        ),
        # Map widget
        _map.ui(width="100%", height=height),
        # Inspection info panel (click feedback)
        ui.output_ui("inspect_info"),
        class_="grid-map-component",
    )


@module.server
def grid_map_server(
    input,
    output,
    session,
    grd_file: reactive.Value,
    partition_map: reactive.Value | None = None,
    on_node_click: Callable[[int], None] | None = None,
):
    """Deck.gl interactive grid map server logic.

    Parameters
    ----------
    input, output, session
        Shiny module server arguments (injected by ``@module.server``).
    grd_file
        Reactive value holding the current ``GrdFile`` (or ``None``).
    partition_map
        Optional reactive value holding ``{elem_id: partition_index}`` or ``None``.
    on_node_click
        Optional callback invoked with the clicked node ID.
    """
    # Create MapWidget with the RESOLVED id (module namespace prefix).
    map_id = module.resolve_id("deckgl_map")
    _map = MapWidget(
        id=map_id,
        tooltip={"html": "{tooltip_html}"},
        picking_radius=5,
    )

    selected_node: reactive.Value[int | None] = reactive.value(None)

    @reactive.effect
    async def _update_map():
        """Rebuild layers and push to the map when inputs change."""
        grd = grd_file.get()
        if grd is None:
            # Clear the map
            await _map.update(session, layers=[], widgets=[zoom_widget()])
            return

        mode = input.map_mode()
        colorscale = input.map_colors()
        show_bdry = input.show_boundaries()
        show_nd = input.show_nodes()
        basemap_key = input.map_basemap()

        # Elevation scale — only read when mode is depth_3d
        elev_scale = 1.0
        if mode == "depth_3d":
            try:
                elev_scale = float(input.elevation_scale())
            except Exception:
                elev_scale = 10.0

        # Partition map
        pmap = None
        if partition_map is not None:
            pmap = partition_map.get()

        # If mode is "partitions" but there's a partition map, use it
        actual_mode = mode
        if pmap and mode == "mesh":
            actual_mode = "partitions"

        layers = build_layers(
            grd,
            mode=actual_mode,
            colorscale=colorscale,
            show_boundaries=show_bdry,
            show_nodes=show_nd,
            elevation_scale=elev_scale,
            partition_map=pmap,
        )

        vs = _compute_view_state(grd, is_3d=(mode == "depth_3d"))

        await _map.update(
            session,
            layers=layers,
            view_state=vs,
            transition_duration=500,
            widgets=[zoom_widget()],
        )

        # Set basemap style
        basemap_url = BASEMAPS.get(basemap_key, BASEMAPS["positron"])
        await _map.set_style(session, basemap_url)

        # Fit bounds to grid extent
        bounds = vs.get("bounds")
        if bounds:
            await _map.fit_bounds(
                session,
                bounds=bounds,
                max_zoom=18,
                duration=800,
            )

    # Handle click events
    @reactive.effect
    def _handle_click():
        click_data = input[f"{map_id}_click"]()
        if click_data is None:
            return
        # Extract node_id from the clicked object
        obj = click_data.get("object") if isinstance(click_data, dict) else None
        if obj and "node_id" in obj:
            nid = int(obj["node_id"])
            selected_node.set(nid)
            if on_node_click is not None:
                on_node_click(nid)

    @render.ui
    def inspect_info():
        """Display selected node info as a badge."""
        nid = selected_node.get()
        if nid is None:
            return ui.div()
        grd = grd_file.get()
        if grd is None or nid not in grd.nodes:
            return ui.div()
        node = grd.nodes[nid]
        depth_str = f"{node.depth:.2f}" if node.depth is not None else "N/A"
        return ui.div(
            ui.span(
                f"Node {nid}",
                class_="badge bg-primary me-1",
            ),
            ui.span(
                f"({node.x:.6f}, {node.y:.6f})",
                class_="badge bg-secondary me-1",
            ),
            ui.span(
                f"Depth: {depth_str}",
                class_="badge bg-info",
            ),
            class_="mt-2",
        )

    return {"selected_node": selected_node}
