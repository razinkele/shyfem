"""Mesh builder service — pure Python mesh generation pipeline.

Converts GeoJSON/Shapefile coastlines into simulation-ready .grd meshes
using constrained Delaunay triangulation (Triangle library) with optional
bathymetry interpolation via scipy or shybas.
"""

import logging
import math
from pathlib import Path

import fiona
import numpy as np
import shapely.geometry
import triangle
from scipy.interpolate import griddata
from scipy.spatial import cKDTree

from shyfem_ui.services.parser_grd import (
    Element,
    GrdFile,
    GrdParser,
    Line,
    Node,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Import boundaries
# ---------------------------------------------------------------------------


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
        ring_nodes = []
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
            ring_nodes.append(coord_to_node[key])
        grd.lines[line_id] = Line(id=line_id, line_type=ltype, nodes=ring_nodes)
        line_id += 1

    with fiona.open(str(file_path)) as src:
        for feature in src:
            geom = shapely.geometry.shape(feature["geometry"])
            if geom.is_empty:
                continue
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
                grd.parse_warnings.append(
                    f"Skipped unsupported geometry type: {geom.geom_type}"
                )
                continue

            for poly in polygons:
                _add_ring(poly.exterior.coords, 1)
                for interior in poly.interiors:
                    _add_ring(interior.coords, 2)

    if not grd.nodes:
        grd.parse_warnings.append("No geometries found in file")

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

    line = grd.lines[line_id]
    coords = [(grd.nodes[nid].x, grd.nodes[nid].y) for nid in line.nodes]
    coords_arr = np.array(coords)

    if method == "chaikin":
        smoothed = _chaikin_smooth(coords_arr, iterations)
    elif method == "gaussian":
        smoothed = _gaussian_smooth(coords_arr, iterations, sigma)
    else:
        raise ValueError(f"Unknown smoothing method: {method}")

    return _rebuild_grd_with_new_line(grd, line_id, smoothed)


def _chaikin_smooth(coords: np.ndarray, iterations: int) -> np.ndarray:
    """Chaikin corner-cutting subdivision."""
    pts = coords.copy()
    for _ in range(iterations):
        if len(pts) < 3:
            break
        new_pts = []
        is_closed = np.allclose(pts[0], pts[-1])
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


def _gaussian_smooth(coords: np.ndarray, iterations: int, sigma: float) -> np.ndarray:
    """1D Gaussian smoothing of boundary coordinates."""
    from scipy.ndimage import gaussian_filter1d

    pts = coords.copy()
    is_closed = np.allclose(pts[0], pts[-1])
    for _ in range(iterations):
        if is_closed:
            # Smooth x and y independently, wrap mode for closed ring
            pts[:-1, 0] = gaussian_filter1d(pts[:-1, 0], sigma, mode="wrap")
            pts[:-1, 1] = gaussian_filter1d(pts[:-1, 1], sigma, mode="wrap")
            pts[-1] = pts[0]
        else:
            pts[:, 0] = gaussian_filter1d(pts[:, 0], sigma, mode="nearest")
            pts[:, 1] = gaussian_filter1d(pts[:, 1], sigma, mode="nearest")
    return pts


def _rebuild_grd_with_new_line(
    grd: GrdFile, line_id: int, new_coords: np.ndarray
) -> GrdFile:
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

    # Assign new node IDs for the smoothed line
    max_id = max(grd.nodes.keys()) if grd.nodes else 0
    new_node_ids = []
    for i, (x, y) in enumerate(new_coords):
        nid = max_id + 1 + i
        new_grd.nodes[nid] = Node(id=nid, node_type=0, x=float(x), y=float(y))
        new_node_ids.append(nid)

    # Copy all lines, replacing the target
    for lid, line in grd.lines.items():
        if lid == line_id:
            new_grd.lines[lid] = Line(
                id=lid, line_type=line.line_type, nodes=new_node_ids
            )
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

    line = grd.lines[line_id]
    coords = [(grd.nodes[nid].x, grd.nodes[nid].y) for nid in line.nodes]

    # Use Shapely for simplification
    ring = shapely.geometry.LinearRing(coords)
    simplified = ring.simplify(tolerance, preserve_topology=True)
    new_coords = np.array(simplified.coords)

    return _rebuild_grd_with_new_line(grd, line_id, new_coords)


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


# ---------------------------------------------------------------------------
# 5. Triangulate
# ---------------------------------------------------------------------------


def triangulate(
    grd: GrdFile,
    max_area: float | None = None,
    min_angle: float = 20.0,
    refinement_zones: list[dict] | None = None,
) -> GrdFile:
    """Generate a constrained Delaunay triangulation from boundary lines.

    Args:
        grd: Grid with boundary lines (from import or smoothing step).
        max_area: Maximum triangle area constraint.
        min_angle: Minimum interior angle (degrees, default 20).
        refinement_zones: Optional regional area constraints.

    Returns:
        New GrdFile with nodes, elements, and preserved boundary lines.
    """
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
    """
    vertices = []
    segments = []
    holes = []
    node_map: dict[int, int] = {}  # grd node ID → vertex index

    for nid in sorted(grd.nodes.keys()):
        node = grd.nodes[nid]
        node_map[nid] = len(vertices)
        vertices.append([node.x, node.y])

    for line in grd.lines.values():
        nids = line.nodes
        for i in range(len(nids) - 1):
            if nids[i] in node_map and nids[i + 1] in node_map:
                segments.append([node_map[nids[i]], node_map[nids[i + 1]]])

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

    # Create elements — store as [3, n1, n2, n3] matching .grd format convention
    for i, tri in enumerate(triangles):
        eid = i + 1
        # Triangle uses 0-indexed, convert to 1-indexed node IDs
        n1, n2, n3 = int(tri[0]) + 1, int(tri[1]) + 1, int(tri[2]) + 1
        new_grd.elements[eid] = Element(id=eid, elem_type=0, nodes=[3, n1, n2, n3])

    # Rebuild boundary lines from segment markers if available
    # Otherwise preserve original line structure with new node mapping
    _rebuild_boundary_lines(new_grd, original_grd, vertices)

    return new_grd


def _rebuild_boundary_lines(
    new_grd: GrdFile, original_grd: GrdFile, vertices: np.ndarray
) -> None:
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
            new_grd.lines[lid] = Line(
                id=lid, line_type=line.line_type, nodes=new_node_ids
            )


# ---------------------------------------------------------------------------
# 6. Bathymetry interpolation
# ---------------------------------------------------------------------------


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

    # Try GeoTIFF via rasterio
    if path.suffix.lower() in (".tif", ".tiff"):
        return _load_bathymetry_raster(path)

    # Text-based formats
    points = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
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

    Returns:
        Nx3 numpy array of (x, y, depth).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Contour file not found: {path}")

    # Common depth attribute names to try
    depth_candidates = [
        depth_attr,
        "depth", "DEPTH", "Depth",
        "z", "Z",
        "elev", "ELEV", "elevation", "ELEVATION", "Elevation",
        "contour", "CONTOUR", "Contour",
        "value", "VALUE", "Value",
        "level", "LEVEL", "Level",
    ]

    points = []
    with fiona.open(str(path)) as src:
        # Detect the depth attribute from the first feature
        resolved_attr = None
        for feat in src:
            props = feat["properties"]
            for candidate in depth_candidates:
                if candidate in props and props[candidate] is not None:
                    try:
                        float(props[candidate])
                        resolved_attr = candidate
                        break
                    except (ValueError, TypeError):
                        continue
            break  # only check first feature
        src.close()

    if resolved_attr is None:
        raise ValueError(
            f"No numeric depth attribute found. Tried: {depth_candidates[:6]}. "
            f"Available attributes: {list(feat['properties'].keys()) if feat else []}"
        )

    with fiona.open(str(path)) as src:
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
            lines = []
            if geom.geom_type == "LineString":
                lines = [geom]
            elif geom.geom_type == "MultiLineString":
                lines = list(geom.geoms)
            else:
                continue

            for line in lines:
                if sample_distance and sample_distance > 0 and line.length > 0:
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

    logger.info("Loaded %d points from %s (attr=%s)", len(points), path.name, resolved_attr)
    return np.array(points)


def _load_bathymetry_raster(path: Path) -> np.ndarray:
    """Sample points from a GeoTIFF raster."""
    import rasterio

    with rasterio.open(path) as src:
        band = src.read(1)
        nodata = src.nodata
        points = []
        for row in range(band.shape[0]):
            for col in range(band.shape[1]):
                val = band[row, col]
                if nodata is not None and val == nodata:
                    continue
                x, y = src.xy(row, col)
                points.append([x, y, float(val)])

    if not points:
        raise ValueError(f"No valid data in raster {path}")

    return np.array(points)


def interpolate_bathymetry_scipy(
    grd: GrdFile, bathy_points: np.ndarray, method: str = "linear"
) -> GrdFile:
    """Interpolate bathymetry onto mesh nodes using scipy.

    Args:
        grd: Mesh with nodes (from triangulation step).
        bathy_points: Nx3 array of (x, y, depth).
        method: One of ``"nearest"``, ``"linear"``, ``"cubic"``, ``"idw"``.

    Returns:
        New GrdFile with depth values set on all nodes.
    """
    if len(bathy_points) == 0:
        raise ValueError("No bathymetry points provided")

    bathy_xy = bathy_points[:, :2]
    bathy_z = bathy_points[:, 2]

    node_ids = sorted(grd.nodes.keys())
    mesh_xy = np.array([[grd.nodes[nid].x, grd.nodes[nid].y] for nid in node_ids])

    if method == "idw":
        depths = _idw_interpolate(bathy_xy, bathy_z, mesh_xy, k=8, power=2.0)
    elif method in ("nearest", "linear", "cubic"):
        depths = griddata(bathy_xy, bathy_z, mesh_xy, method=method)
        # Fill NaN with nearest for edge nodes
        if np.any(np.isnan(depths)):
            nearest = griddata(bathy_xy, bathy_z, mesh_xy, method="nearest")
            depths = np.where(np.isnan(depths), nearest, depths)
    else:
        raise ValueError(f"Unknown interpolation method: {method}")

    # Build new GrdFile with depths
    new_grd = GrdFile()
    for i, nid in enumerate(node_ids):
        node = grd.nodes[nid]
        new_grd.nodes[nid] = Node(
            id=nid, node_type=node.node_type, x=node.x, y=node.y,
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


async def interpolate_bathymetry_shybas(
    grd: GrdFile,
    bathy_path: Path,
    work_dir: Path,
    wrapper,
) -> GrdFile:
    """Interpolate bathymetry using shybas -bfile.

    Args:
        grd: Mesh grid (from triangulation step).
        bathy_path: Path to bathymetry xyz file.
        work_dir: Working directory for temp files.
        wrapper: ShyfemWrapper instance.

    Returns:
        GrdFile with interpolated depths.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Save grid to temp file
    temp_grd = work_dir / "_mesh_temp.grd"
    GrdParser.save(grd, temp_grd)

    # Run shybas with bathymetry file
    result = await wrapper.run_command(
        "shybas",
        ["-bfile", str(bathy_path), str(temp_grd)],
        work_dir,
    )

    if not result.success:
        raise RuntimeError(f"shybas failed: {result.stderr}")

    # shybas writes output to the same filename or with .bas extension
    output_path = temp_grd
    if not output_path.exists():
        output_path = work_dir / "_mesh_temp.bas"

    return GrdParser.parse_file(output_path)


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


def compute_mesh_stats(grd: GrdFile) -> dict:
    """Compute mesh quality statistics.

    Reuses quality metrics from grid_prep page functions.

    Returns:
        Dict with node_count, elem_count, line_count, quality, areas,
        min_angles sub-dicts.
    """
    from shyfem_ui.pages.grid_prep import (
        compute_element_areas,
        compute_element_quality,
        compute_min_angles,
    )

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
                (grd.nodes[nid].x, grd.nodes[nid].y)
                for nid in line.nodes
                if nid in grd.nodes
            ]
            if len(coords) >= 3:
                return shapely.geometry.Polygon(coords)
    return None
