"""Mesh builder service — pure Python mesh generation pipeline.

Converts GeoJSON/Shapefile coastlines into simulation-ready .grd meshes
using constrained Delaunay triangulation (Triangle library) with optional
bathymetry interpolation via scipy or shybas.
"""

import logging
import math
from dataclasses import replace as _dc_replace
from pathlib import Path

import numpy as np

try:
    import fiona
except ImportError:
    fiona = None

try:
    import pyproj
except ImportError:
    pyproj = None

try:
    import shapely.geometry
    import shapely.ops
except ImportError:
    shapely = None

try:
    import triangle
except ImportError:
    triangle = None

try:
    from scipy.interpolate import (
        CloughTocher2DInterpolator,
        LinearNDInterpolator,
        RBFInterpolator,
        griddata,
    )
    from scipy.spatial import cKDTree
except ImportError:
    CloughTocher2DInterpolator = LinearNDInterpolator = RBFInterpolator = griddata = None
    cKDTree = None

from shyfem_ui.services.parser_grd import (
    Element,
    GrdFile,
    GrdParser,
    Line,
    Node,
)

logger = logging.getLogger(__name__)


def _wgs84_transformer(source_crs, *, context: str):
    """Return a transformer for projected CRS, or None for geographic/no CRS."""
    if not source_crs:
        return None
    if pyproj is None:
        raise ValueError(f"Cannot reproject {context}: pyproj is not installed")
    try:
        src_crs = pyproj.CRS.from_user_input(source_crs)
        if src_crs.is_projected:
            logger.info("Reprojecting %s from %s to WGS84", context, src_crs.name)
            return pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
        return None
    except Exception as exc:
        raise ValueError(
            f"Could not determine CRS for {context}; refusing to use raw coordinates"
        ) from exc


def _coords_exceed_wgs84_bounds(xs, ys) -> bool:
    """True if any coordinate falls outside valid WGS84 bounds (|lon|>180 or
    |lat|>90). Impossible for real geographic lon/lat, so it is a strong signal
    that an untagged (or geographic-labelled) dataset was actually projected and
    NOT reprojected — tagging such coords epsg=4326 would silently mis-project
    the whole mesh."""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if xs.size == 0 or ys.size == 0:
        return False
    return bool(np.nanmax(np.abs(xs)) > 180.0 or np.nanmax(np.abs(ys)) > 90.0)


# ---------------------------------------------------------------------------
# 1. Import boundaries
# ---------------------------------------------------------------------------


def _remove_ring_loops(ring: list[int]) -> list[int]:
    """Remove self-touching loops from a ring of node IDs.

    After coordinate deduplication, a ring may visit the same node twice
    (non-consecutively), creating a "lollipop" self-intersection.  This
    function finds such duplicates (excluding the closing node) and
    collapses the loop between the two occurrences.
    """
    # Exclude closing node from duplicate detection
    is_closed = len(ring) >= 2 and ring[0] == ring[-1]
    body = ring[:-1] if is_closed else ring

    changed = True
    while changed:
        changed = False
        seen: dict[int, int] = {}
        new_body: list[int] = []
        for nid in body:
            if nid in seen:
                # Found a loop: remove everything from the first occurrence
                # to here, keeping the node once
                new_body = new_body[: seen[nid] + 1]
                # Rebuild 'seen' for the truncated list
                seen = {n: i for i, n in enumerate(new_body)}
                changed = True
            else:
                seen[nid] = len(new_body)
                new_body.append(nid)
        body = new_body

    if is_closed and body:
        body.append(body[0])
    return body


def import_boundaries(file_path: Path) -> GrdFile:
    """Import boundary lines from GeoJSON, Shapefile, or GeoPackage.

    Each polygon exterior ring becomes a boundary line (line_type=1),
    each hole becomes a separate line (line_type=2).

    Args:
        file_path: Path to a GeoJSON, .shp, or .gpkg file.

    Returns:
        GrdFile with nodes and boundary lines (no elements).
    """
    grd = GrdFile()
    node_id = 1
    line_id = 1
    coord_to_node: dict[tuple[float, float], int] = {}

    def _add_ring(coords, ltype):
        nonlocal node_id, line_id
        ring_nodes: list[int] = []
        # Close the ring if not already closed
        coord_list = list(coords)
        if coord_list[0] != coord_list[-1]:
            coord_list.append(coord_list[0])
        for x, y, *_ in coord_list:
            key = (round(x, 10), round(y, 10))
            if key not in coord_to_node:
                grd.nodes[node_id] = Node(id=node_id, node_type=0, x=x, y=y)
                coord_to_node[key] = node_id
                node_id += 1
            nid = coord_to_node[key]
            # Skip consecutive duplicates (from near-coincident coords that
            # round to the same key — these create zero-length segments)
            if ring_nodes and ring_nodes[-1] == nid:
                continue
            ring_nodes.append(nid)
        # Remove lollipop loops: if a node appears twice (non-consecutively,
        # excluding the closing node), the ring self-touches. Collapse the
        # loop by removing the nodes between the two occurrences.
        ring_nodes = _remove_ring_loops(ring_nodes)
        # Ensure the ring is still closed after cleanup
        if len(ring_nodes) >= 2 and ring_nodes[0] != ring_nodes[-1]:
            ring_nodes.append(ring_nodes[0])
        grd.lines[line_id] = Line(id=line_id, line_type=ltype, nodes=ring_nodes)
        line_id += 1

    with fiona.open(str(file_path)) as src:
        # Reproject to WGS84 if source CRS is projected (e.g. UTM, LKS94)
        transformer_obj = _wgs84_transformer(src.crs, context=f"boundary {file_path}")
        transformer = transformer_obj.transform if transformer_obj is not None else None

        for feature in src:
            geom = shapely.geometry.shape(feature["geometry"])
            if geom.is_empty:
                continue
            if transformer is not None:
                geom = shapely.ops.transform(transformer, geom)
            polygons = []
            if geom.geom_type == "Polygon":
                polygons = [geom]
            elif geom.geom_type == "MultiPolygon":
                polygons = list(geom.geoms)
            elif geom.geom_type in ("LineString", "MultiLineString"):
                lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
                for line in lines:
                    _add_ring(line.coords, 1)
                continue
            else:
                grd.parse_warnings.append(f"Skipped unsupported geometry type: {geom.geom_type}")
                continue

            for poly in polygons:
                _add_ring(poly.exterior.coords, 1)
                for interior in poly.interiors:
                    _add_ring(interior.coords, 2)

    if not grd.nodes:
        grd.parse_warnings.append("No geometries found in file")

    # No reprojection happened (geographic or missing CRS). If the coordinates
    # can't be WGS84 lon/lat, the source was almost certainly projected but
    # untagged — warn instead of silently tagging it epsg=4326 (mis-projected).
    if transformer is None and grd.nodes:
        xs = [n.x for n in grd.nodes.values()]
        ys = [n.y for n in grd.nodes.values()]
        if _coords_exceed_wgs84_bounds(xs, ys):
            grd.parse_warnings.append(
                "Coordinates exceed WGS84 bounds (|lon|>180 or |lat|>90) but the "
                "source has no projected CRS; treating as epsg=4326 may be wrong. "
                "Set the correct CRS on the source dataset before importing."
            )

    # Boundaries are always in WGS84 after reprojection
    grd.epsg = 4326
    return grd


# ---------------------------------------------------------------------------
# 2. Smooth boundary
# ---------------------------------------------------------------------------


def smooth_boundary(
    grd: GrdFile,
    line_id: int,
    method: str = "chaikin",
    iterations: int = 2,
    sigma: float = 1.0,
) -> GrdFile:
    """Smooth a boundary line in the grid.

    Args:
        grd: Input grid.
        line_id: ID of the line to smooth.
        method: ``"chaikin"`` (corner-cutting) or ``"gaussian"`` (1D filter).
        iterations: Number of smoothing passes.
        sigma: Gaussian sigma (only used for ``method="gaussian"``).

    Returns:
        New GrdFile with the smoothed line.
    """
    if line_id not in grd.lines:
        raise ValueError(f"Line {line_id} not found in grid")

    if method == "chaikin":

        def process(coords: np.ndarray, closed: bool) -> np.ndarray:
            return _chaikin_smooth(coords, iterations, closed=closed)

    elif method == "gaussian":

        def process(coords: np.ndarray, closed: bool) -> np.ndarray:
            return _gaussian_smooth(coords, iterations, sigma, closed=closed)

    else:
        raise ValueError(f"Unknown smoothing method: {method}")

    return _rework_line(grd, line_id, process)


def _chaikin_smooth(coords: np.ndarray, iterations: int, closed: bool | None = None) -> np.ndarray:
    """Chaikin corner-cutting subdivision.

    ``closed=None`` treats the curve as a ring when its ends coincide;
    ``closed=False`` keeps both end points fixed even then.
    """
    pts = coords.copy()
    for _ in range(iterations):
        if len(pts) < 3:
            break
        new_pts = []
        is_closed = np.allclose(pts[0], pts[-1]) if closed is None else closed
        n = len(pts) - 1 if is_closed else len(pts) - 1
        for i in range(n):
            p0 = pts[i]
            p1 = pts[(i + 1) % len(pts)] if is_closed else pts[i + 1]
            new_pts.append(0.75 * p0 + 0.25 * p1)
            new_pts.append(0.25 * p0 + 0.75 * p1)
        if is_closed:
            new_pts.append(new_pts[0].copy())
        else:
            new_pts.insert(0, pts[0].copy())
            new_pts.append(pts[-1].copy())
        pts = np.array(new_pts)
    return pts


def _gaussian_smooth(
    coords: np.ndarray, iterations: int, sigma: float, closed: bool | None = None
) -> np.ndarray:
    """1D Gaussian smoothing of boundary coordinates.

    ``closed`` as for :func:`_chaikin_smooth`; an open curve keeps its two
    end points where they are.
    """
    from scipy.ndimage import gaussian_filter1d

    pts = coords.copy()
    is_closed = np.allclose(pts[0], pts[-1]) if closed is None else closed
    for _ in range(iterations):
        if is_closed:
            # Smooth x and y independently, wrap mode for closed ring
            pts[:-1, 0] = gaussian_filter1d(pts[:-1, 0], sigma, mode="wrap")
            pts[:-1, 1] = gaussian_filter1d(pts[:-1, 1], sigma, mode="wrap")
            pts[-1] = pts[0]
        else:
            pts[:, 0] = gaussian_filter1d(pts[:, 0], sigma, mode="nearest")
            pts[:, 1] = gaussian_filter1d(pts[:, 1], sigma, mode="nearest")
            pts[0], pts[-1] = coords[0], coords[-1]
    return pts


def _rework_line(grd: GrdFile, line_id: int, process) -> GrdFile:
    """Apply ``process(coords, closed) -> coords`` to one line of ``grd``.

    A node the line shares with another line (import_boundaries gives
    adjacent polygons one node where they touch) is pinned: the line is cut
    into open runs at its shared nodes, each run is processed with its ends
    held, and the shared nodes keep their ids and positions. The sibling
    lines are left exactly as they were. Rebuilding the whole line used to
    delete the shared nodes and silently drop them from the siblings,
    leaving them shortened and unclosed (M-08).
    """
    line = grd.lines[line_id]
    others: set[int] = set()
    for lid, other in grd.lines.items():
        if lid != line_id:
            others.update(other.nodes)
    shared = others.intersection(line.nodes)

    def _xy(nids) -> np.ndarray:
        return np.array([(grd.nodes[n].x, grd.nodes[n].y) for n in nids], dtype=float)

    if not shared:
        closed = len(line.nodes) >= 3 and line.nodes[0] == line.nodes[-1]
        return _rebuild_grd_with_new_line(
            grd, line_id, process(_xy(line.nodes), None if closed else False)
        )

    seq = list(line.nodes)
    if len(seq) >= 2 and seq[0] == seq[-1]:
        # Ring: start it at a shared node, so every run ends on one.
        body = seq[:-1]
        start = next(i for i, n in enumerate(body) if n in shared)
        body = body[start:] + body[:start]
        seq = body + [body[0]]
    cuts = sorted({0, len(seq) - 1} | {i for i, n in enumerate(seq) if n in shared})

    new_grd = GrdFile()
    dropped = set(line.nodes) - others
    for nid, node in grd.nodes.items():
        if nid not in dropped:
            new_grd.nodes[nid] = _dc_replace(node)
    next_id = max(grd.nodes) + 1
    new_line = [seq[0]]
    for a, b in zip(cuts, cuts[1:], strict=False):
        run = seq[a : b + 1]
        if len(run) > 2:
            for x, y in process(_xy(run), False)[1:-1]:
                new_grd.nodes[next_id] = Node(id=next_id, node_type=0, x=float(x), y=float(y))
                new_line.append(next_id)
                next_id += 1
        new_line.append(seq[b])

    for lid, other in grd.lines.items():
        if lid == line_id:
            new_grd.lines[lid] = Line(id=lid, line_type=other.line_type, nodes=new_line)
        else:
            new_grd.lines[lid] = Line(id=lid, line_type=other.line_type, nodes=list(other.nodes))
    new_grd.elements = dict(grd.elements)
    return new_grd


def _rebuild_grd_with_new_line(grd: GrdFile, line_id: int, new_coords: np.ndarray) -> GrdFile:
    """Create a new GrdFile replacing one line's nodes with new coordinates."""
    new_grd = GrdFile()
    old_line = grd.lines[line_id]
    old_nodes_in_line = set(old_line.nodes)

    # Copy nodes not in the target line
    for nid, node in grd.nodes.items():
        if nid not in old_nodes_in_line:
            new_grd.nodes[nid] = Node(
                id=nid, node_type=node.node_type, x=node.x, y=node.y, depth=node.depth
            )

    # Assign new node IDs for the smoothed line.
    # If closed ring (last coord ≈ first coord), reuse the first node ID
    # for the closing position to avoid duplicate vertices that crash Triangle.
    is_closed = len(new_coords) >= 3 and np.allclose(new_coords[0], new_coords[-1], atol=1e-8)
    max_id = max(grd.nodes.keys()) if grd.nodes else 0
    new_node_ids = []
    n_unique = len(new_coords) - 1 if is_closed else len(new_coords)
    for i in range(n_unique):
        x, y = new_coords[i]
        nid = max_id + 1 + i
        new_grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))
        new_node_ids.append(nid)
    if is_closed:
        new_node_ids.append(new_node_ids[0])  # close with first node ID

    # Copy all lines, replacing the target
    for lid, line in grd.lines.items():
        if lid == line_id:
            new_grd.lines[lid] = Line(id=lid, line_type=line.line_type, nodes=new_node_ids)
        else:
            # Remap nodes for other lines if they shared nodes with the target
            new_grd.lines[lid] = Line(
                id=lid,
                line_type=line.line_type,
                nodes=[n for n in line.nodes if n in new_grd.nodes],
            )

    # Copy elements (should be empty at this stage)
    new_grd.elements = dict(grd.elements)
    return new_grd


# ---------------------------------------------------------------------------
# 3. Reduce boundary (Douglas-Peucker)
# ---------------------------------------------------------------------------


def reduce_boundary(grd: GrdFile, line_id: int, tolerance: float) -> GrdFile:
    """Reduce boundary points using Douglas-Peucker simplification.

    Args:
        grd: Input grid.
        line_id: ID of the line to simplify.
        tolerance: Simplification tolerance (coordinate units).

    Returns:
        New GrdFile with the simplified line.
    """
    if line_id not in grd.lines:
        raise ValueError(f"Line {line_id} not found in grid")

    def process(coords: np.ndarray, closed: bool | None) -> np.ndarray:
        # Shapely keeps the two ends of an open LineString.
        geom = (
            shapely.geometry.LineString(coords)
            if closed is False
            else shapely.geometry.LinearRing(coords)
        )
        return np.array(geom.simplify(tolerance, preserve_topology=True).coords)

    return _rework_line(grd, line_id, process)


# ---------------------------------------------------------------------------
# 4. Resolution / area constraints
# ---------------------------------------------------------------------------


def set_resolution(
    grd: GrdFile,
    global_area: float | None = None,
    refinement_zones: list[dict] | None = None,
) -> dict:
    """Build Triangle-compatible area constraints.

    Args:
        grd: Grid with boundary lines.
        global_area: Global maximum triangle area.
        refinement_zones: List of ``{"polygon": [(x,y),...], "max_area": float}``.

    Returns:
        Dict with ``max_area`` and ``regions`` for Triangle.
    """
    result: dict = {"max_area": global_area, "regions": []}

    if refinement_zones:
        for zone in refinement_zones:
            poly = shapely.geometry.Polygon(zone["polygon"])
            centroid = poly.centroid
            # Triangle region format: [x, y, region_id, max_area]
            result["regions"].append(
                [centroid.x, centroid.y, len(result["regions"]) + 1, zone["max_area"]]
            )

    return result


def estimate_element_count(grd: GrdFile, max_area: float) -> int:
    """Estimate the number of triangles for given area constraint.

    Args:
        grd: Grid with boundary lines.
        max_area: Maximum triangle area.

    Returns:
        Estimated element count.
    """
    if max_area <= 0:
        return 0

    boundary_poly = _boundary_to_polygon(grd)
    if boundary_poly is None or boundary_poly.is_empty:
        return 0

    return max(1, int(boundary_poly.area / max_area))


def suggest_max_area_for_limit(
    grd: GrdFile, max_elements: int, safety: float = 1.5
) -> float | None:
    """Inverse of estimate_element_count — pick a max_area that respects an
    element-count cap.

    The naive ``boundary_area / max_area`` estimator is roughly the floor of
    actual element count: Triangle's quality refinement (when ``min_angle``
    is set) splits triangles further to honor the angle constraint, typically
    inflating the count by 30-60%. The default ``safety=1.5`` accounts for
    that — it is a hint, not a guarantee, and very irregular boundaries can
    still exceed the cap.

    Args:
        grd: Grid with boundary lines.
        max_elements: Desired upper bound on element count (must be > 0).
        safety: Multiplier applied to the suggested area to leave headroom
                for refinement-induced inflation (default 1.5).

    Returns:
        Suggested max_area, or None if the boundary has no area.
    """
    if max_elements <= 0:
        return None
    boundary_poly = _boundary_to_polygon(grd)
    if boundary_poly is None or boundary_poly.is_empty:
        return None
    return safety * boundary_poly.area / max_elements


def count_below_area(grd: GrdFile, threshold: float) -> int:
    """Count triangles whose area is strictly less than ``threshold``.

    Used to warn users that their mesh contains slivers below the requested
    Min Triangle Area. Triangle (the library) cannot enforce a minimum area
    constraint, so we report after the fact.

    Args:
        grd: Grid produced by :func:`triangulate`.
        threshold: Minimum acceptable triangle area (must be > 0).

    Returns:
        Number of triangles below the threshold (0 if threshold <= 0 or no
        triangle elements exist).
    """
    if threshold <= 0 or not grd.elements:
        return 0
    count = 0
    for elem in grd.elements.values():
        nodes = [grd.nodes[n] for n in elem.nodes if n in grd.nodes]
        if len(nodes) < 3:
            continue
        # Shoelace area for a triangle (works for the first 3 nodes).
        x1, y1 = nodes[0].x, nodes[0].y
        x2, y2 = nodes[1].x, nodes[1].y
        x3, y3 = nodes[2].x, nodes[2].y
        area = abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0
        if area < threshold:
            count += 1
    return count


def warn_if_min_geq_max_area(min_area: float | None, max_area: float | None) -> str | None:
    """Return a warning string if both bounds are set and min >= max."""
    if min_area is None or max_area is None:
        return None
    if min_area <= 0 or max_area <= 0:
        return None
    if min_area >= max_area:
        return (
            f"Min Triangle Area ({min_area:g}) is ≥ Max Triangle Area "
            f"({max_area:g}); every triangle will be flagged as a sliver."
        )
    return None


def warn_if_minimal_with_cap(method: str, max_elements: int | None) -> str | None:
    """Warn the user that Max Elements has no effect in minimal mode."""
    if method == "delaunay_minimal" and max_elements:
        return (
            "Max Elements is ignored for Delaunay (minimal) — the element "
            "count depends only on the boundary geometry. Switch to a quality "
            "method if you want the cap to be enforced."
        )
    return None


# ---------------------------------------------------------------------------
# 5. Triangulate
# ---------------------------------------------------------------------------


def check_element_ceiling(grd: GrdFile, max_area: float | None, ceiling: int | None) -> str | None:
    """Return why ``max_area`` would give a mesh over ``ceiling``, else None.

    The estimate (boundary area / max area) is a floor — Triangle's angle
    refinement adds 30-60 % — so this guards against the runaway request
    (a Max Triangle Area typed far too small) rather than promising the
    final count (M-12).
    """
    if not ceiling or ceiling <= 0 or not max_area or max_area <= 0:
        return None
    estimate = estimate_element_count(grd, max_area)
    if estimate <= ceiling:
        return None
    msg = (
        f"Estimated {estimate:,} elements is over this server's limit of "
        f"{ceiling:,} elements per mesh."
    )
    suggested = suggest_max_area_for_limit(grd, ceiling)
    if suggested is not None:
        msg += f" Use a Max Triangle Area of at least {suggested:.4g}."
    return msg


def triangulate(
    grd: GrdFile,
    max_area: float | None = None,
    min_angle: float = 20.0,
    refinement_zones: list[dict] | None = None,
    max_elements: int | None = None,
) -> GrdFile:
    """Generate a constrained Delaunay triangulation from boundary lines.

    Args:
        grd: Grid with boundary lines (from import or smoothing step).
        max_area: Maximum triangle area constraint.
        min_angle: Minimum interior angle (degrees, default 20).
        refinement_zones: Optional regional area constraints.
        max_elements: Server ceiling; refuse (``ValueError``) when the
            estimated element count for ``max_area`` is above it.

    Returns:
        New GrdFile with nodes, elements, and preserved boundary lines.
    """
    if max_area is not None and max_area <= 0:
        raise ValueError(
            f"max_area must be positive (got {max_area!r}); pass None for no constraint"
        )
    too_big = check_element_ceiling(grd, max_area, max_elements)
    if too_big:
        raise ValueError(too_big)
    if min_angle > 34.0:
        raise ValueError(
            f"min_angle must be <= 34 degrees (got {min_angle!r}); "
            "Triangle's quality refinement may not converge above 34"
        )
    pslg = _build_pslg(grd)

    opts = "p"  # PSLG mode
    if min_angle > 0:
        opts += f"q{min_angle}"
    if max_area is not None and max_area > 0:
        opts += f"a{max_area}"

    if refinement_zones and "regions" not in pslg:
        regions = []
        for zone in refinement_zones:
            poly = shapely.geometry.Polygon(zone["polygon"])
            centroid = poly.centroid
            regions.append([centroid.x, centroid.y, len(regions) + 1, zone["max_area"]])
        if regions:
            pslg["regions"] = np.array(regions)
            opts += "A"

    result = triangle.triangulate(pslg, opts)

    return _triangle_result_to_grd(result, grd)


def _build_pslg(grd: GrdFile) -> dict:
    """Convert GrdFile boundary lines into Triangle PSLG format.

    Returns dict with 'vertices', 'segments', and optionally 'holes'.
    Deduplicates near-coincident vertices to prevent Triangle segfaults.
    """
    vertices = []
    segments = []
    holes = []
    node_map: dict[int, int] = {}  # grd node ID → vertex index
    coord_to_idx: dict[tuple[float, float], int] = {}  # dedup by coords

    for nid in sorted(grd.nodes.keys()):
        node = grd.nodes[nid]
        key = (round(node.x, 6), round(node.y, 6))
        if key in coord_to_idx:
            # Reuse existing vertex index for near-coincident node
            node_map[nid] = coord_to_idx[key]
        else:
            idx = len(vertices)
            node_map[nid] = idx
            coord_to_idx[key] = idx
            vertices.append([node.x, node.y])

    for line in grd.lines.values():
        nids = line.nodes
        for i in range(len(nids) - 1):
            if nids[i] in node_map and nids[i + 1] in node_map:
                vi = node_map[nids[i]]
                vj = node_map[nids[i + 1]]
                if vi != vj:  # skip zero-length segments
                    segments.append([vi, vj])

        # If this is a hole boundary, compute an interior point
        if line.line_type == 2:
            coords = [(grd.nodes[nid].x, grd.nodes[nid].y) for nid in nids]
            if len(coords) >= 3:
                poly = shapely.geometry.Polygon(coords)
                interior_pt = poly.representative_point()
                holes.append([interior_pt.x, interior_pt.y])

    pslg: dict = {
        "vertices": np.array(vertices, dtype=np.float64),
        "segments": np.array(segments, dtype=np.int32),
    }
    if holes:
        pslg["holes"] = np.array(holes, dtype=np.float64)

    return pslg


def _triangle_result_to_grd(result: dict, original_grd: GrdFile) -> GrdFile:
    """Convert Triangle library output back to GrdFile."""
    new_grd = GrdFile()

    vertices = result["vertices"]
    triangles = result["triangles"]

    # Create nodes
    for i, (x, y) in enumerate(vertices):
        nid = i + 1
        new_grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))

    # Create elements (Triangle library uses 0-indexed; convert to 1-indexed)
    for i, tri in enumerate(triangles):
        eid = i + 1
        n1, n2, n3 = int(tri[0]) + 1, int(tri[1]) + 1, int(tri[2]) + 1
        new_grd.elements[eid] = Element(id=eid, elem_type=0, nodes=[n1, n2, n3])

    # Rebuild boundary lines from segment markers if available
    # Otherwise preserve original line structure with new node mapping
    _rebuild_boundary_lines(new_grd, original_grd, vertices)

    return new_grd


def _rebuild_boundary_lines(new_grd: GrdFile, original_grd: GrdFile, vertices: np.ndarray) -> None:
    """Map original boundary lines onto new mesh nodes using nearest-neighbor."""
    if not original_grd.lines:
        return

    tree = cKDTree(vertices)

    for lid, line in original_grd.lines.items():
        new_node_ids = []
        for nid in line.nodes:
            if nid in original_grd.nodes:
                node = original_grd.nodes[nid]
                _, idx = tree.query([node.x, node.y])
                new_nid = int(idx) + 1  # 1-indexed
                new_node_ids.append(new_nid)
        if new_node_ids:
            new_grd.lines[lid] = Line(id=lid, line_type=line.line_type, nodes=new_node_ids)


# ---------------------------------------------------------------------------
# 6. Bathymetry interpolation
# ---------------------------------------------------------------------------

# Upper bound on raster pixel count before we refuse to read the band into
# memory. A DEM band is read in full (src.read(1)) and then expanded into
# float64 x/y/value arrays for the valid pixels, so peak memory is several
# bytes per pixel; on the shared laguna worker an unbounded read can OOM the
# process. 100 megapixels (~10000x10000) keeps a single import well under a
# gigabyte while still admitting any realistic lagoon/coastal DEM.
MAX_RASTER_PIXELS = 100_000_000


def load_bathymetry_file(file_path: Path) -> np.ndarray:
    """Load bathymetry data from CSV/XYZ file (x y z per line).

    Supports space, tab, and comma-separated formats.

    Args:
        file_path: Path to bathymetry file.

    Returns:
        Nx3 numpy array of (x, y, depth).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Bathymetry file not found: {path}")

    # Vector formats must use load_bathymetry_contours() instead
    vector_exts = {".gpkg", ".geojson", ".json", ".shp"}
    if path.suffix.lower() in vector_exts:
        raise ValueError(
            f"'{path.name}' is a vector file ({path.suffix}). "
            f"Please select 'Contour Isobaths' as the bathymetry data type."
        )

    # Try GeoTIFF via rasterio
    if path.suffix.lower() in (".tif", ".tiff"):
        return _load_bathymetry_raster(path)

    # Text-based formats
    points = []
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            # Try comma, then whitespace
            for sep in [",", None]:
                parts = line.split(sep)
                if len(parts) >= 3:
                    try:
                        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                        points.append([x, y, z])
                        break
                    except ValueError:
                        continue

    if not points:
        raise ValueError(f"No valid x,y,z points found in {path}")

    return np.array(points)


def load_bathymetry_contours(
    file_path: Path,
    depth_attr: str = "depth",
    sample_distance: float | None = None,
    max_points: int | None = None,
) -> np.ndarray:
    """Load bathymetry from contour isobath lines (vector file).

    Reads a GeoJSON, Shapefile, or GeoPackage containing LineString
    features where each feature has a depth attribute.  Extracts vertex
    coordinates along each line and assigns the feature's depth value
    to every vertex.

    Args:
        file_path: Path to vector file with isobath lines.
        depth_attr: Name of the numeric depth/elevation attribute.
            Common names are tried automatically if the given name is
            not found: depth, DEPTH, z, Z, elev, ELEV, elevation,
            CONTOUR, contour.
        sample_distance: If set, resample each line at this interval
            (coordinate units) to add extra points between vertices.
            Useful for sparse contours with long straight segments.
        max_points: If set, refuse (``ValueError``) before extracting more
            than this many points, so a tiny ``sample_distance`` cannot
            exhaust the worker's memory (M-12).

    Returns:
        Nx3 numpy array of (x, y, depth).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Contour file not found: {path}")

    # Common depth attribute names to try
    depth_candidates = [
        depth_attr,
        "depth",
        "DEPTH",
        "Depth",
        "z",
        "Z",
        "elev",
        "ELEV",
        "elevation",
        "ELEVATION",
        "Elevation",
        "contour",
        "CONTOUR",
        "Contour",
        "value",
        "VALUE",
        "Value",
        "level",
        "LEVEL",
        "Level",
    ]

    # Attribute names that are almost certainly not depth values
    _NON_DEPTH_NAMES = frozenset(
        {
            "count",
            "fid",
            "id",
            "gid",
            "oid",
            "objectid",
            "shape_length",
            "shape_len",
            "shape_area",
            "perimeter",
            "area",
            "length",
        }
    )

    points = []
    with fiona.open(str(path)) as src:
        # Detect the depth attribute from the first feature
        resolved_attr = None
        feat = None
        for feat in src:
            props = feat["properties"]
            # Pass 1: try known candidate names
            for candidate in depth_candidates:
                if candidate in props and props[candidate] is not None:
                    try:
                        float(props[candidate])
                        resolved_attr = candidate
                        break
                    except (ValueError, TypeError):
                        continue
            # Pass 2: fallback — scan all properties, skip obvious non-depth names
            if resolved_attr is None:
                for attr_name, attr_val in props.items():
                    if attr_name.lower() in _NON_DEPTH_NAMES:
                        continue
                    if attr_val is not None:
                        try:
                            float(attr_val)
                            resolved_attr = attr_name
                            logger.info(
                                "Auto-detected depth attribute %r "
                                "(set 'Depth attribute name' explicitly to suppress this)",
                                attr_name,
                            )
                            break
                        except (ValueError, TypeError):
                            continue
            break  # only check first feature
        src.close()

    if resolved_attr is None:
        available = list(feat["properties"].keys()) if feat else []
        raise ValueError(
            f"No numeric depth attribute found. Tried: {depth_candidates[:6]}. "
            f"Available attributes: {available}. "
            f"Set the 'Depth attribute name' field to one of: {available}"
        )

    with fiona.open(str(path)) as src:
        # Reproject to WGS84 if source CRS is projected
        transformer_obj = _wgs84_transformer(src.crs, context=f"bathymetry contours {path}")
        transformer = transformer_obj.transform if transformer_obj is not None else None

        for feat in src:
            props = feat["properties"]
            z_val = props.get(resolved_attr)
            if z_val is None:
                continue
            try:
                z = float(z_val)
            except (ValueError, TypeError):
                continue

            geom = shapely.geometry.shape(feat["geometry"])
            if transformer is not None:
                geom = shapely.ops.transform(transformer, geom)
            lines = []
            if geom.geom_type == "LineString":
                lines = [geom]
            elif geom.geom_type == "MultiLineString":
                lines = list(geom.geoms)
            else:
                continue

            for line in lines:
                resample = bool(sample_distance and sample_distance > 0 and line.length > 0)
                if max_points is not None:
                    # Count before allocating: the resample loop is unbounded.
                    n_line = (
                        int(line.length // sample_distance) + 2 if resample else len(line.coords)
                    )
                    if len(points) + n_line > max_points:
                        raise ValueError(
                            f"Contours in {path.name} would give more than "
                            f"{max_points:,} bathymetry points"
                            + (
                                f" at a resample distance of {sample_distance:g}"
                                if resample
                                else ""
                            )
                            + ". Use a larger resample distance (or 0 to keep "
                            "only the contour vertices), or thin the contours."
                        )
                if resample:
                    # Resample at regular intervals
                    dist = 0.0
                    while dist <= line.length:
                        pt = line.interpolate(dist)
                        points.append([pt.x, pt.y, z])
                        dist += sample_distance
                    # Always include the endpoint
                    pt = line.interpolate(line.length)
                    points.append([pt.x, pt.y, z])
                else:
                    # Use original vertices
                    for x, y, *_ in line.coords:
                        points.append([x, y, z])

    if not points:
        raise ValueError(f"No valid contour points extracted from {path}")

    pts = np.array(points)
    # No reprojection happened and the coords can't be WGS84 lon/lat: the source
    # is almost certainly projected but untagged. Warn (don't fail) — a workflow
    # may legitimately use consistent untagged projected coords (e.g. the Mar
    # Menor sample, whose boundary + isobaths are both untagged UTM), so surface
    # the risk in the logs rather than silently assuming WGS84 or breaking it.
    if transformer is None and _coords_exceed_wgs84_bounds(pts[:, 0], pts[:, 1]):
        logger.warning(
            "Bathymetry contours in %s exceed WGS84 bounds (|lon|>180 or |lat|>90) "
            "but the source has no projected CRS; coordinates are used as-is. Set "
            "the correct CRS on the dataset if this is unexpected.",
            path,
        )

    logger.info("Loaded %d points from %s (attr=%s)", len(points), path.name, resolved_attr)
    return pts


def _load_bathymetry_raster(path: Path) -> np.ndarray:
    """Sample points from a GeoTIFF raster, reprojecting to WGS84 if needed.

    Vectorized: builds the valid-pixel index arrays once and computes pixel
    centres + reprojection in batch, instead of a per-pixel Python loop (which
    is O(rows*cols) and hangs on large DEMs). Produces the same points, in the
    same row-major order, as the original loop.
    """
    import rasterio
    from rasterio.transform import xy as rio_xy

    with rasterio.open(path) as src:
        # Guard against an unbounded read OOMing the shared worker: reject
        # oversized rasters from the cheap header dimensions, before read(1).
        n_pixels = int(src.width) * int(src.height)
        if n_pixels > MAX_RASTER_PIXELS:
            raise ValueError(
                f"Raster {path} is too large: {src.width}x{src.height} = "
                f"{n_pixels:,} pixels exceeds the {MAX_RASTER_PIXELS:,}-pixel "
                "limit. Crop or downsample the DEM before importing."
            )

        band = src.read(1)
        nodata = src.nodata

        # Build reprojection transformer if raster is projected.
        transformer = _wgs84_transformer(src.crs, context=f"raster bathymetry {path}")

        # Valid-pixel mask. Start from the nodata skip, then drop any
        # non-finite pixels: a NaN sentinel makes `band != nodata` True
        # everywhere (NaN != NaN), so NaN/inf would otherwise leak through and
        # poison the IDW interpolation. np.nonzero yields row-major (C-order)
        # indices, preserving point order.
        if nodata is not None:
            valid = band != nodata
        else:
            valid = np.ones(band.shape, dtype=bool)
        if np.issubdtype(band.dtype, np.floating):
            valid &= np.isfinite(band)
        rows_idx, cols_idx = np.nonzero(valid)

        if rows_idx.size == 0:
            raise ValueError(f"No valid data in raster {path}")

        vals = band[rows_idx, cols_idx].astype(float)
        # Pixel centres (rio_xy defaults to offset='center', like src.xy).
        xs, ys = rio_xy(src.transform, rows_idx, cols_idx)
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        if transformer is not None:
            xs, ys = transformer.transform(xs, ys)
            xs = np.asarray(xs, dtype=float)
            ys = np.asarray(ys, dtype=float)
        elif _coords_exceed_wgs84_bounds(xs, ys):
            # No reprojection happened and the coords can't be WGS84 lon/lat: the
            # raster is projected but untagged. Warn (don't fail) so a consistent
            # untagged-projected workflow keeps working while a genuine
            # mis-projection is still surfaced in the logs.
            logger.warning(
                "Raster %s coordinates exceed WGS84 bounds (|lon|>180 or |lat|>90) "
                "but it has no projected CRS; coordinates are used as-is. Set the "
                "correct CRS on the raster if this is unexpected.",
                path,
            )

    return np.column_stack([xs, ys, vals])


def drop_nonfinite_points(points: np.ndarray) -> tuple[np.ndarray, int]:
    """Drop the rows of an ``(N, 3)`` x/y/depth array holding a NaN or inf.

    A single ``nan`` in an XYZ survey (a blank cell exported by a spreadsheet,
    a "no data" marker) used to travel into the interpolation and come out as
    a ``nan`` node depth in the exported GRD (M-05). ``float()`` accepts
    "nan" and "inf", so the text loaders cannot catch it while parsing.

    Returns:
        ``(finite_points, number_dropped)``.

    Raises:
        ValueError: no row is finite.
    """
    pts = np.asarray(points, dtype=float)
    if pts.size == 0:
        return pts, 0
    keep = np.isfinite(pts[:, :3]).all(axis=1)
    dropped = int(len(pts) - int(keep.sum()))
    if not keep.any():
        raise ValueError("No bathymetry point has a finite x, y and depth")
    return (pts[keep] if dropped else pts), dropped


def extract_boundary_zero_points(grd: GrdFile) -> np.ndarray:
    """Extract boundary line vertices as depth=0 constraint points.

    Sampling the coastline boundary at zero depth prevents interpolation
    from producing unrealistic values near shore.

    Args:
        grd: Grid with boundary lines.

    Returns:
        Nx3 numpy array of (x, y, 0.0) for every boundary node.
    """
    points = []
    seen: set[int] = set()
    for line in grd.lines.values():
        for nid in line.nodes:
            if nid not in seen and nid in grd.nodes:
                node = grd.nodes[nid]
                points.append([node.x, node.y, 0.0])
                seen.add(nid)
    if not points:
        return np.empty((0, 3))
    return np.array(points)


def interpolate_bathymetry_scipy(
    grd: GrdFile,
    bathy_points: np.ndarray,
    method: str = "linear",
    use_boundary_zero: bool = False,
) -> GrdFile:
    """Interpolate bathymetry onto mesh nodes using scipy.

    Args:
        grd: Mesh with nodes (from triangulation step).
        bathy_points: Nx3 array of (x, y, depth).
        method: One of ``"nearest"``, ``"linear"``, ``"cubic"``, ``"idw"``,
            ``"rbf"`` (thin-plate spline), or ``"cloughtocher"`` (C1 cubic).
        use_boundary_zero: If True, automatically inject boundary nodes as
            depth=0 constraints before interpolating. This forces the
            coastline to zero depth and improves near-shore results.

    Returns:
        New GrdFile with depth values set on all nodes.
    """
    node_ids, depths = _compute_depths_only(grd, bathy_points, method, use_boundary_zero)
    return _build_grd_from_depths(grd, node_ids, depths)


def _compute_depths_only(
    grd: GrdFile,
    bathy_points: np.ndarray,
    method: str,
    use_boundary_zero: bool = False,
) -> tuple[list[int], np.ndarray]:
    """Compute interpolated depth values for all mesh nodes.

    Runs entirely as a pure computation — no Shiny state. Intended to be
    called via ``asyncio.to_thread`` from the page handler.

    Args:
        grd: Mesh with nodes (from triangulation step).
        bathy_points: Nx3 array of (x, y, depth).
        method: One of ``"nearest"``, ``"linear"``, ``"cubic"``, ``"idw"``,
            ``"rbf"``, or ``"cloughtocher"``.
        use_boundary_zero: If True, inject boundary nodes as depth=0 before
            interpolating.

    Returns:
        Tuple of (node_ids, depths) where depths[i] is the depth for node_ids[i].
    """
    if len(bathy_points) == 0:
        raise ValueError("No bathymetry points provided")
    # Backstop for callers that skipped the load-time filter (M-05): a NaN
    # survey point poisons every node it reaches (IDW averages it in).
    bathy_points, dropped = drop_nonfinite_points(bathy_points)
    if dropped:
        logger.warning("Ignored %d bathymetry point(s) with a non-finite value", dropped)

    if use_boundary_zero:
        zero_pts = extract_boundary_zero_points(grd)
        if len(zero_pts) > 0:
            bathy_points = np.vstack([zero_pts, bathy_points])
            logger.info(
                "Injected %d boundary-zero points (total: %d)",
                len(zero_pts),
                len(bathy_points),
            )

    bathy_xy = bathy_points[:, :2]
    bathy_z = bathy_points[:, 2]

    node_ids = sorted(grd.nodes.keys())
    mesh_xy = np.array([[grd.nodes[nid].x, grd.nodes[nid].y] for nid in node_ids])

    if method == "idw":
        depths = _idw_interpolate(bathy_xy, bathy_z, mesh_xy, k=8, power=2.0)
    elif method in ("nearest", "linear", "cubic"):
        depths = griddata(bathy_xy, bathy_z, mesh_xy, method=method)
        if np.any(np.isnan(depths)):
            nearest = griddata(bathy_xy, bathy_z, mesh_xy, method="nearest")
            depths = np.where(np.isnan(depths), nearest, depths)
    elif method == "rbf":
        depths = _rbf_interpolate(bathy_xy, bathy_z, mesh_xy)
    elif method == "cloughtocher":
        depths = _cloughtocher_interpolate(bathy_xy, bathy_z, mesh_xy)
    else:
        raise ValueError(f"Unknown interpolation method: {method}")

    return node_ids, depths


def _build_grd_from_depths(grd: GrdFile, node_ids: list[int], depths: np.ndarray) -> GrdFile:
    """Build a new GrdFile from precomputed depth values.

    Args:
        grd: Original mesh (elements and lines are shallow-copied).
        node_ids: Ordered list of node IDs matching the depths array.
        depths: 1-D array of float depth values, one per node_id.

    Returns:
        New GrdFile with depth set on all nodes.
    """
    new_grd = GrdFile()
    for i, nid in enumerate(node_ids):
        node = grd.nodes[nid]
        new_grd.nodes[nid] = Node(
            id=nid,
            node_type=node.node_type,
            x=node.x,
            y=node.y,
            depth=float(depths[i]),
        )
    new_grd.elements = dict(grd.elements)
    new_grd.lines = dict(grd.lines)
    return new_grd


def _idw_interpolate(
    src_xy: np.ndarray,
    src_z: np.ndarray,
    query_xy: np.ndarray,
    k: int = 8,
    power: float = 2.0,
) -> np.ndarray:
    """Inverse distance weighting using KD-tree."""
    tree = cKDTree(src_xy)
    distances, indices = tree.query(query_xy, k=min(k, len(src_xy)))

    if k == 1 or len(src_xy) == 1:
        return src_z[indices]

    # Avoid division by zero for exact matches
    weights = 1.0 / np.maximum(distances**power, 1e-12)
    weight_sum = weights.sum(axis=1, keepdims=True)
    values = (weights * src_z[indices]).sum(axis=1, keepdims=True) / weight_sum
    return values.ravel()


def _deduplicate_points(
    xy: np.ndarray, z: np.ndarray, rel_tol: float = 1e-7
) -> tuple[np.ndarray, np.ndarray]:
    """Drop near-identical XY points, keeping the first occurrence.

    Dense isobath data can repeat a point (or put two within millimetres),
    which makes RBF / Clough-Tocher singular. "Near-identical" is relative to
    the data's extent (``rel_tol`` of it: millimetres for a lagoon in degrees
    or in metres). It used to round to 2 decimals, which for the degree
    coordinates Step 4 always uses is a ~1 km lattice that thinned a dense
    isobath to a handful of points (M-04).
    """
    if len(xy) == 0:
        return xy, z
    extent = float(np.max(np.ptp(xy, axis=0)))
    tol = max(extent * rel_tol, np.finfo(float).tiny)
    # 1. One point per tol-sized cell (O(n log n), whatever the number of
    #    copies of a point: a pair search alone is quadratic in that number).
    keys = np.floor((xy - xy.min(axis=0)) / tol).astype(np.int64)
    _, first = np.unique(keys, axis=0, return_index=True)
    first.sort()  # preserve original order
    # 2. Merge the pairs a cell boundary split. With one point per cell each
    #    point has only a few neighbours within tol, so this stays O(n).
    pairs = cKDTree(xy[first]).query_pairs(tol, output_type="ndarray")
    keep = np.ones(len(first), dtype=bool)
    keep[pairs[:, 1]] = False  # i < j: drop the later point of each pair
    idx = first[keep]
    return xy[idx], z[idx]


def _rbf_interpolate(
    src_xy: np.ndarray,
    src_z: np.ndarray,
    query_xy: np.ndarray,
    kernel: str = "thin_plate_spline",
    neighbors: int | None = None,
) -> np.ndarray:
    """Radial Basis Function interpolation (thin-plate spline by default).

    RBF naturally extrapolates beyond the convex hull of data points,
    producing smooth surfaces suitable for bathymetry.  For large point
    sets (>10k), pass ``neighbors=32`` for a local approximation.
    """
    src_xy, src_z = _deduplicate_points(src_xy, src_z)
    n_pts = len(src_xy)
    if neighbors is None and n_pts > 10_000:
        neighbors = min(32, n_pts)
    rbf = RBFInterpolator(src_xy, src_z, kernel=kernel, neighbors=neighbors)
    return rbf(query_xy)


def _cloughtocher_interpolate(
    src_xy: np.ndarray,
    src_z: np.ndarray,
    query_xy: np.ndarray,
) -> np.ndarray:
    """Clough-Tocher C1-smooth cubic interpolation on data triangulation.

    Produces a piecewise-cubic surface with continuous first derivatives.
    Smoother than ``griddata(method='cubic')`` with less overshoot.
    Falls back to nearest-neighbor for points outside the convex hull.
    """
    src_xy, src_z = _deduplicate_points(src_xy, src_z)
    interp = CloughTocher2DInterpolator(src_xy, src_z)
    depths = interp(query_xy)
    # Fill NaN outside hull with nearest
    if np.any(np.isnan(depths)):
        nearest = griddata(src_xy, src_z, query_xy, method="nearest")
        depths = np.where(np.isnan(depths), nearest, depths)
    return depths


async def interpolate_bathymetry_shybas(grd: GrdFile, points: np.ndarray, wrapper) -> GrdFile:
    """Interpolate node depths with ``shybas -bfile`` (M-03).

    shybas's contract, checked on the real binary:

    * the bathymetry must be a GRD of depth points (``1 id 0 x y z``); a
      plain xyz file, or any comment line, is a "Read error" reported with
      exit 0 and no output;
    * ``-node`` interpolates on nodes, and refuses a mesh whose elements
      carry depths ("depth values on elements not allowed", exit 0);
    * the result is always ``basbathy.grd`` in the working folder.

    It runs in a private temporary folder (the old shared work folder let
    users overwrite each other's files) and raises instead of returning the
    mesh unchanged when shybas wrote nothing.

    Args:
        grd: The mesh to give depths to.
        points: ``(N, 3)`` array of x, y, depth.
        wrapper: ShyfemWrapper instance.

    Returns:
        A copy of ``grd`` with node depths from shybas.

    Raises:
        RuntimeError: shybas failed or wrote no result.
    """
    import tempfile

    # A "nan" in bathy.grd is a shybas "Read error" (M-05).
    pts, _ = drop_nonfinite_points(np.asarray(points, dtype=float))
    with tempfile.TemporaryDirectory(prefix="shybas_") as tmp:
        work = Path(tmp)
        mesh = GrdFile(
            nodes={k: _dc_replace(n, depth=None) for k, n in grd.nodes.items()},
            elements={k: _dc_replace(e, depth=None) for k, e in grd.elements.items()},
            lines=dict(grd.lines),
        )
        GrdParser.save(mesh, work / "mesh.grd")
        with open(work / "bathy.grd", "w") as fh:
            for i, (x, y, z) in enumerate(pts[:, :3].tolist(), start=1):
                fh.write(f"1 {i} 0 {x!r} {y!r} {z!r}\n")  # plain floats, full precision

        result = await wrapper.run_command(
            "shybas", ["-bfile", "bathy.grd", "-node", "mesh.grd"], work
        )
        out = work / "basbathy.grd"
        if not result.success or not out.is_file():
            said = [
                line.strip()
                for line in (result.stdout or "").splitlines() + (result.stderr or "").splitlines()
                if line.strip()
            ]
            raise RuntimeError(
                "shybas did not interpolate the bathymetry" + (f": {said[-1]}" if said else "")
            )
        interpolated = GrdParser.parse_file(out)

    depth = {k: n.depth for k, n in interpolated.nodes.items()}
    return GrdFile(
        nodes={k: _dc_replace(n, depth=depth.get(k)) for k, n in grd.nodes.items()},
        elements=dict(grd.elements),
        lines=dict(grd.lines),
    )


# ---------------------------------------------------------------------------
# 6b. Depth adjustments
# ---------------------------------------------------------------------------


def adjust_depths(
    grd: GrdFile,
    min_clamp: float | None = None,
    max_clamp: float | None = None,
    fill_value: float | None = None,
) -> GrdFile:
    """Return a new GrdFile with depth values adjusted.

    - min_clamp: nodes with depth < min_clamp are set to min_clamp
    - max_clamp: nodes with depth > max_clamp are set to max_clamp
    - fill_value: nodes where depth is None receive this value
    Each parameter is independent; all are optional.
    Pure function — does not mutate the input GrdFile.
    """
    new_nodes = {}
    for nid, node in grd.nodes.items():
        depth = node.depth
        if depth is None and fill_value is not None:
            depth = fill_value
        if depth is not None:
            if min_clamp is not None and depth < min_clamp:
                depth = min_clamp
            if max_clamp is not None and depth > max_clamp:
                depth = max_clamp
        new_nodes[nid] = _dc_replace(node, depth=depth)
    return _dc_replace(grd, nodes=new_nodes)


# ---------------------------------------------------------------------------
# 7. Export
# ---------------------------------------------------------------------------


def export_grd(grd: GrdFile, output_path: Path) -> None:
    """Save grid to .grd file.

    Args:
        grd: Grid to save.
        output_path: Destination path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    GrdParser.save(grd, output_path)


# ---------------------------------------------------------------------------
# 8. Validation and statistics
# ---------------------------------------------------------------------------


def validate_boundary(grd: GrdFile) -> list[str]:
    """Validate boundary geometry.

    Returns list of warning/error strings (empty = all good).
    """
    issues: list[str] = []

    if not grd.lines:
        issues.append("ERROR: No boundary lines found")
        return issues

    has_exterior = False
    for lid, line in grd.lines.items():
        if len(line.nodes) < 3:
            issues.append(f"ERROR: Line {lid} has fewer than 3 nodes")
            continue

        coords = []
        for nid in line.nodes:
            if nid in grd.nodes:
                node = grd.nodes[nid]
                coords.append((node.x, node.y))

        if len(coords) < 3:
            issues.append(f"ERROR: Line {lid} references missing nodes")
            continue

        # Check if ring is closed
        if coords[0] != coords[-1]:
            issues.append(f"WARNING: Line {lid} is not a closed ring")

        # Check for self-intersection
        if len(coords) >= 4:
            ring = shapely.geometry.LinearRing(coords)
            if not ring.is_simple:
                issues.append(f"WARNING: Line {lid} has self-intersections")

        if line.line_type == 1:
            has_exterior = True

    if not has_exterior:
        issues.append("WARNING: No exterior boundary found (line_type=1)")

    return issues


def _check_boundary_gates(grd: GrdFile) -> tuple[bool, str | None]:
    """Decide whether ``grd`` is safe to hand to Triangle.

    Returns ``(True, None)`` if the boundary is mesh-ready. Otherwise returns
    ``(False, reason)`` where ``reason`` is a human-readable explanation.

    Blocks on:
    - any ERROR-prefixed issue from :func:`validate_boundary`
    - self-intersecting lines (Triangle can hang or segfault)
    - missing exterior boundary (line_type=1)

    Allows:
    - unclosed rings (Triangle closes them automatically)
    """
    issues = validate_boundary(grd)
    blocking: list[str] = []
    for issue in issues:
        if issue.startswith("ERROR"):
            blocking.append(issue)
        elif "self-intersect" in issue.lower():
            blocking.append(issue)
        elif "no exterior boundary" in issue.lower():
            blocking.append(issue)
    if blocking:
        return False, "; ".join(blocking)
    return True, None


# ---------------------------------------------------------------------------
# Pure geometry helpers (no Shiny / UI dependencies)
# ---------------------------------------------------------------------------


def _get_triangle_vertices(elem, nodes_dict) -> list[int] | None:
    """Extract 3 vertex node IDs from an element, handling the parser quirk.

    The .grd format is ``2 id type num_nodes n1 n2 n3 [depth]``, but the
    parser consumes ``num_nodes`` as a node ID.  Triangles thus arrive with
    ``nodes=[3, n1, n2, n3]`` (length 4) instead of ``[n1, n2, n3]``.

    Returns:
        List of 3 node IDs, or None if the element is not a triangle.
    """
    nids = elem.nodes
    if len(nids) == 3:
        return list(nids)
    if len(nids) == 4 and nids[0] == 3:
        return list(nids[1:4])
    return None


def compute_element_quality(grd) -> dict:
    """Compute min-side / max-side quality ratio for each triangle.

    Returns:
        Dict with ``qualities``, ``elem_ids``, and ``stats`` sub-dict
        (min, max, mean, median, std, count, below_03, below_05).
    """
    qualities = []
    elem_ids = []
    for eid, elem in grd.elements.items():
        verts = _get_triangle_vertices(elem, grd.nodes)
        if verts is None:
            continue
        coords = []
        for nid in verts:
            node = grd.nodes.get(nid)
            if node is None:
                break
            coords.append((node.x, node.y))
        if len(coords) != 3:
            continue
        sides = [
            math.sqrt(
                (coords[(i + 1) % 3][0] - coords[i][0]) ** 2
                + (coords[(i + 1) % 3][1] - coords[i][1]) ** 2
            )
            for i in range(3)
        ]
        max_s = max(sides)
        q = min(sides) / max_s if max_s > 0 else 0.0
        qualities.append(q)
        elem_ids.append(eid)

    if not qualities:
        return {"qualities": [], "elem_ids": [], "stats": None}

    arr = np.array(qualities)
    stats = {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std()),
        "count": len(arr),
        "below_03": int(np.sum(arr < 0.3)),
        "below_05": int(np.sum(arr < 0.5)),
    }
    return {"qualities": qualities, "elem_ids": elem_ids, "stats": stats}


def compute_element_areas(grd) -> dict:
    """Compute triangle areas using the shoelace formula.

    Returns:
        Dict with ``areas``, ``elem_ids``, and ``stats`` sub-dict
        (min, max, mean, median, std, count, area_ratio).
    """
    areas = []
    elem_ids = []
    for eid, elem in grd.elements.items():
        verts = _get_triangle_vertices(elem, grd.nodes)
        if verts is None:
            continue
        coords = []
        for nid in verts:
            node = grd.nodes.get(nid)
            if node is None:
                break
            coords.append((node.x, node.y))
        if len(coords) != 3:
            continue
        x1, y1 = coords[0]
        x2, y2 = coords[1]
        x3, y3 = coords[2]
        area = 0.5 * abs(x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        areas.append(area)
        elem_ids.append(eid)

    if not areas:
        return {"areas": [], "elem_ids": [], "stats": None}

    arr = np.array(areas)
    stats = {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std()),
        "count": len(arr),
        "area_ratio": float(arr.max() / arr.min()) if arr.min() > 0 else float("inf"),
    }
    return {"areas": areas, "elem_ids": elem_ids, "stats": stats}


def compute_min_angles(grd) -> dict:
    """Compute the minimum interior angle (degrees) for each triangle.

    Uses the law of cosines to find all three angles.

    Returns:
        Dict with ``min_angles``, ``elem_ids``, and ``stats`` sub-dict
        (min, max, mean, median, count, below_20).
    """
    min_angles = []
    elem_ids = []
    for eid, elem in grd.elements.items():
        verts = _get_triangle_vertices(elem, grd.nodes)
        if verts is None:
            continue
        coords = []
        for nid in verts:
            node = grd.nodes.get(nid)
            if node is None:
                break
            coords.append((node.x, node.y))
        if len(coords) != 3:
            continue
        # Side lengths squared
        sides_sq = []
        sides = []
        for i in range(3):
            dx = coords[(i + 1) % 3][0] - coords[i][0]
            dy = coords[(i + 1) % 3][1] - coords[i][1]
            s2 = dx * dx + dy * dy
            sides_sq.append(s2)
            sides.append(math.sqrt(s2))
        # Angles via law of cosines: angle at vertex i is opposite side i
        # side opposite vertex 0 is sides[1] (vertex 1→2), etc.
        # Actually: side[i] connects vertex i to vertex (i+1)
        # Angle at vertex 0: opposite side connects vertex 1 to vertex 2 = sides[1]
        # Adjacent sides: sides[2] (vertex 2→0) and sides[0] (vertex 0→1)
        angles = []
        # a = side opposite vertex, b,c = adjacent sides
        # side[0] = v0→v1, side[1] = v1→v2, side[2] = v2→v0
        # angle at v0: opposite = side[1], adjacent = side[0], side[2]
        # angle at v1: opposite = side[2], adjacent = side[0], side[1]
        # angle at v2: opposite = side[0], adjacent = side[1], side[2]
        for i in range(3):
            a = sides[(i + 1) % 3]  # opposite side
            b = sides[i]
            c = sides[(i + 2) % 3]
            if b > 0 and c > 0:
                cos_angle = (b * b + c * c - a * a) / (2 * b * c)
                cos_angle = max(-1.0, min(1.0, cos_angle))
                angles.append(math.degrees(math.acos(cos_angle)))
        if angles:
            min_angles.append(min(angles))
            elem_ids.append(eid)

    if not min_angles:
        return {"min_angles": [], "elem_ids": [], "stats": None}

    arr = np.array(min_angles)
    stats = {
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "count": len(arr),
        "below_20": int(np.sum(arr < 20.0)),
    }
    return {"min_angles": min_angles, "elem_ids": elem_ids, "stats": stats}


def compute_mesh_stats(grd: GrdFile) -> dict:
    """Compute mesh quality statistics.

    Returns:
        Dict with node_count, elem_count, line_count, quality, areas,
        min_angles sub-dicts.
    """

    stats = {
        "node_count": len(grd.nodes),
        "elem_count": len(grd.elements),
        "line_count": len(grd.lines),
    }

    if grd.elements:
        quality = compute_element_quality(grd)
        areas = compute_element_areas(grd)
        angles = compute_min_angles(grd)
        stats["quality"] = quality.get("stats")
        stats["areas"] = areas.get("stats")
        stats["min_angles"] = angles.get("stats")

    # Depth stats
    depths = [n.depth for n in grd.nodes.values() if n.depth is not None]
    if depths:
        darr = np.array(depths)
        stats["depth"] = {
            "min": float(darr.min()),
            "max": float(darr.max()),
            "mean": float(darr.mean()),
        }

    return stats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _boundary_to_polygon(grd: GrdFile) -> shapely.geometry.Polygon | None:
    """Convert exterior boundary lines to a Shapely polygon."""
    for line in grd.lines.values():
        if line.line_type == 1:
            coords = [
                (grd.nodes[nid].x, grd.nodes[nid].y) for nid in line.nodes if nid in grd.nodes
            ]
            if len(coords) >= 3:
                return shapely.geometry.Polygon(coords)
    return None


def check_bathy_extent(grd: GrdFile, bathy: np.ndarray) -> str | None:
    """Return a warning if bathymetry points fall outside the mesh bbox.

    The check is bbox-vs-bbox (cheap). Disjoint bboxes almost certainly
    indicate a CRS mismatch (e.g. UTM-meter XYZ for a WGS84-degree mesh).

    Returns ``None`` if extents overlap or the boundary has no exterior.
    """
    if bathy.size == 0:
        return None
    poly = _boundary_to_polygon(grd)
    if poly is None or poly.is_empty:
        return None
    min_x, min_y, max_x, max_y = poly.bounds
    bx_min, by_min = float(bathy[:, 0].min()), float(bathy[:, 1].min())
    bx_max, by_max = float(bathy[:, 0].max()), float(bathy[:, 1].max())
    disjoint = bx_max < min_x or bx_min > max_x or by_max < min_y or by_min > max_y
    if disjoint:
        return (
            f"Bathymetry extent [{bx_min:.3g}, {by_min:.3g}] – "
            f"[{bx_max:.3g}, {by_max:.3g}] does not overlap mesh boundary "
            f"[{min_x:.3g}, {min_y:.3g}] – [{max_x:.3g}, {max_y:.3g}]. "
            "Likely cause: CRS mismatch — re-export bathymetry in the mesh's "
            "coordinate system (mesh is in WGS84 lon/lat after import)."
        )
    return None


def summarize_depth_stats(bathy: np.ndarray) -> str:
    """Return a one-line min/max/mean summary of bathymetry depths.

    NaN-aware: NaN values are excluded from min/max/mean (so partial-NaN
    arrays still report meaningful stats); the count of NaN-stripped
    points is appended when non-zero.
    """
    if bathy.size == 0:
        return "Bathymetry: empty"
    z = bathy[:, 2]
    valid = z[~np.isnan(z)]
    if valid.size == 0:
        return "Bathymetry: all depths are NaN"
    nan_count = z.size - valid.size
    nan_note = f" ({nan_count} NaN excluded)" if nan_count else ""
    return (
        f"Depth: min={float(valid.min()):.2f}, max={float(valid.max()):.2f}, "
        f"mean={float(valid.mean()):.2f}{nan_note} "
        f"(SHYFEM convention: depth>0 below surface)"
    )


def warn_if_degenerate_bathy(bathy: np.ndarray) -> str | None:
    """Return a warning if depths are obviously broken; otherwise None."""
    if bathy.size == 0:
        return None
    z = bathy[:, 2]
    if np.all(np.isnan(z)):
        return "All bathymetry values are NaN — interpolation will fail."
    valid = z[~np.isnan(z)]
    if valid.size == 0:
        return None
    if np.all(valid == 0):
        return "All bathymetry depths are 0 — likely missing depth data."
    if np.all(valid == valid[0]):
        return (
            f"All bathymetry depths are identical ({float(valid[0]):.2f}); "
            "interpolation will produce a flat bottom."
        )
    return None
