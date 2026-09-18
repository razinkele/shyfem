"""Box polygons for the map, in WGS84 lon/lat (spec sec4, sec9).

One polygon per box, keyed by box id, coming from either:

- ``load_box_polygons``: a user-supplied GeoPackage or GeoJSON file named in
  the project manifest. Validated: driver allowlist, file-size / feature /
  vertex caps, an integer, unique id field on every feature, reprojection to
  WGS84, one outer ring per box.
- ``dissolve_boxes_from_grid``: dissolved from the SHYFEM grid's element
  triangles using the element -> box mapping the cache builder stores in
  ``meta["element_box"]``.

Every user-facing failure is a ``PolygonError`` naming the file and, where
relevant, the box id.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

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

from shyfem_ui.services.parser_grd import GrdFile, GrdParser

MAX_POLYGON_BYTES = 50 * 1024 * 1024
MAX_FEATURES = 1000
MAX_VERTICES = 200_000
ALLOWED_DRIVERS = ("GPKG", "GeoJSON")


class PolygonError(ValueError):
    """User-facing polygon-file problem."""


def _require_geospatial_stack() -> None:
    if fiona is None or pyproj is None or shapely is None:
        raise PolygonError("geospatial stack (fiona/pyproj/shapely) is not installed")


def _to_wgs84(crs) -> Callable[[float, float], tuple[float, float]]:
    """Build an (x, y) -> (lon, lat) transform for the given source CRS.

    ``crs`` may be falsy (no CRS on the source, e.g. a bare GeoJSON, which is
    assumed to already be WGS84 lon/lat per RFC 7946).
    """
    src = pyproj.CRS.from_user_input(crs) if crs else pyproj.CRS.from_epsg(4326)
    if src.to_epsg() == 4326:
        return lambda x, y: (x, y)
    transformer = pyproj.Transformer.from_crs(src, pyproj.CRS.from_epsg(4326), always_xy=True)
    return lambda x, y: transformer.transform(x, y)


def _out_of_wgs84_bounds(x: float, y: float) -> bool:
    """True if (x, y) is non-finite, or outside valid WGS84 lon/lat bounds.

    pyproj returns inf/nan for out-of-domain input instead of raising, so
    every transform result must be checked explicitly rather than trusted.
    """
    return not math.isfinite(x) or not math.isfinite(y) or abs(x) > 180.0 or abs(y) > 90.0


def _count_vertices(geom: dict) -> int:
    """Total vertex count over every ring of every part of a raw Polygon or
    MultiPolygon geometry (outer rings AND holes, ALL MultiPolygon parts).

    Counted on the geometry as fiona/OGR parsed it, before ``_outer_ring``
    selects the largest part or drops holes, so ``MAX_VERTICES`` bounds the
    cost of parsing a feature rather than just the size of the ring we end
    up keeping.
    """
    geom_type = geom.get("type")
    if geom_type == "Polygon":
        return sum(len(ring) for ring in geom.get("coordinates", []))
    if geom_type == "MultiPolygon":
        return sum(len(ring) for part in geom.get("coordinates", []) for ring in part)
    return 0


def _outer_ring(geom: dict, path: Path, box: int) -> list[list[float]]:
    """The outer ring's coordinates (as [x, y] pairs, source CRS) for one feature."""
    geom_type = geom.get("type")
    if geom_type == "Polygon":
        return [list(p[:2]) for p in geom["coordinates"][0]]
    if geom_type == "MultiPolygon":
        # Largest part by vertex count of its outer ring.
        part = max(geom["coordinates"], key=lambda poly: len(poly[0]))
        return [list(p[:2]) for p in part[0]]
    raise PolygonError(f"{path}: box {box} has unsupported geometry type {geom_type!r}")


def load_box_polygons(
    path: Path,
    layer: str | None,
    id_field: str,
    *,
    expected_boxes: set[int] | None = None,
) -> dict[int, list[list[float]]]:
    """Load one outer-ring polygon per box from a GeoPackage/GeoJSON file.

    Returns ``{box_id: [[lon, lat], ...]}`` with each ring closed (first point
    repeated as the last) and coordinates reprojected to WGS84.

    Raises ``PolygonError`` for anything the UI must surface to the user:
    the geospatial stack not being installed, a missing/oversized/symlinked
    file, a disallowed driver, too many features or vertices, a
    missing/non-integer/duplicate id field, a geometry that reprojects to
    non-finite or out-of-WGS84-bounds coordinates, or (when
    ``expected_boxes`` is given) a box-id set that does not match it
    exactly.
    """
    _require_geospatial_stack()

    path = Path(path)
    try:
        is_symlink = path.is_symlink()
        is_file = path.is_file()
    except OSError as exc:
        raise PolygonError(f"{path}: cannot stat polygon file ({exc})") from exc
    if is_symlink:
        raise PolygonError(f"{path}: polygon file must be a regular file, not a symlink")
    if not is_file:
        raise PolygonError(f"{path}: polygon file not found")
    size = path.stat().st_size
    if size > MAX_POLYGON_BYTES:
        raise PolygonError(f"{path}: polygon file exceeds {MAX_POLYGON_BYTES} bytes ({size})")

    try:
        src = fiona.open(str(path), layer=layer) if layer else fiona.open(str(path))
    except Exception as exc:  # fiona raises driver-specific exception types
        raise PolygonError(f"{path}: cannot open polygon file ({exc})") from exc

    with src:
        if src.driver not in ALLOWED_DRIVERS:
            raise PolygonError(
                f"{path}: driver {src.driver!r} is not allowed (expected one of {ALLOWED_DRIVERS})"
            )
        schema_props = (src.schema or {}).get("properties", {})
        if id_field not in schema_props:
            raise PolygonError(
                f"{path}: field {id_field!r} not found (available fields: {sorted(schema_props)})"
            )
        # OGR's GeoJSON driver resolves a field holding inconsistent types across
        # features (e.g. an int on one feature, a string on another) to an
        # ambiguous "json" schema type. Reject up front: even where a particular
        # mixed-in value happens to be JSON-parseable back to an int (e.g. "2"),
        # the field still cannot be trusted to be a plain integer on every
        # feature, and some values (e.g. a non-numeric string) would otherwise
        # raise a raw JSONDecodeError while fiona *builds* that feature, before
        # we ever get to read it.
        if schema_props[id_field] == "json":
            raise PolygonError(
                f"{path}: field {id_field!r} has inconsistent types across features "
                "(must be a plain integer on every feature)"
            )
        try:
            to_wgs84 = _to_wgs84(src.crs)
        except Exception as exc:
            raise PolygonError(f"{path}: cannot reproject polygons to WGS84 ({exc})") from exc

        out: dict[int, list[list[float]]] = {}
        vertex_count = 0
        iterator = iter(src)
        index = 0
        while True:
            # Check the cap before fetching, so at most MAX_FEATURES records
            # are ever read from the driver (never one more to "peek" ahead).
            if index >= MAX_FEATURES:
                raise PolygonError(f"{path}: more than {MAX_FEATURES} features")
            try:
                feature = next(iterator)
            except StopIteration:
                break
            except Exception as exc:
                raise PolygonError(f"{path}: cannot read feature {index} ({exc})") from exc
            index += 1

            props = dict(feature["properties"])
            raw_id = props.get(id_field)
            if (
                raw_id is None
                or isinstance(raw_id, bool)
                or not isinstance(raw_id, (int, float))
                or (isinstance(raw_id, float) and not raw_id.is_integer())
            ):
                raise PolygonError(
                    f"{path}: field {id_field!r} must be an integer on every feature "
                    f"(got {raw_id!r})"
                )
            box = int(raw_id)
            if box in out:
                raise PolygonError(f"{path}: {id_field!r} values must be unique (duplicate {box})")

            geometry = feature["geometry"]
            if geometry is None:
                raise PolygonError(f"{path}: box {box} has no geometry")
            geometry = dict(geometry)

            # Count vertices over the WHOLE raw geometry (all rings, all parts)
            # before selecting the outer ring, so the cap bounds parse cost.
            vertex_count += _count_vertices(geometry)
            if vertex_count > MAX_VERTICES:
                raise PolygonError(f"{path}: more than {MAX_VERTICES} total vertices")

            ring = _outer_ring(geometry, path, box)
            wgs_ring = [list(to_wgs84(x, y)) for x, y in ring]
            for gx, gy in wgs_ring:
                if _out_of_wgs84_bounds(gx, gy):
                    raise PolygonError(
                        f"{path}: box {box} reprojected to invalid coordinates ({gx}, {gy})"
                    )
            if wgs_ring[0] != wgs_ring[-1]:
                wgs_ring.append(list(wgs_ring[0]))
            out[box] = [[round(x, 7), round(y, 7)] for x, y in wgs_ring]

    if expected_boxes is not None and set(out) != set(expected_boxes):
        missing = sorted(set(expected_boxes) - set(out))
        extra = sorted(set(out) - set(expected_boxes))
        raise PolygonError(
            f"{path}: polygon box ids do not match the expected boxes "
            f"(missing={missing}, extra={extra})"
        )

    return out


def _resolve_grid_epsg(grd: GrdFile, epsg: int | None) -> int | None:
    """Resolve the source EPSG code for a grid's coordinates, in priority order:

    1. the ``epsg`` argument;
    2. ``grd.epsg`` (set by a caller that already tagged the parsed grid);
    3. the grid's own coordinates, treated as WGS84 if every value looks
       geographic (``|x| <= 180`` and ``|y| <= 90`` everywhere);
    4. ``grd.detect_coordinate_system()`` (``parser_grd.py``), if it resolves
       a usable UTM zone + hemisphere;
    5. otherwise ``None`` (the caller raises).
    """
    if epsg is not None:
        return epsg
    if grd.epsg is not None:
        return grd.epsg
    xmin, ymin, xmax, ymax = grd.get_bounds()
    if abs(xmin) <= 180 and abs(xmax) <= 180 and abs(ymin) <= 90 and abs(ymax) <= 90:
        return 4326
    cs = grd.detect_coordinate_system()
    if cs.is_utm and cs.utm_zone:
        return (32600 if cs.utm_hemisphere == "N" else 32700) + cs.utm_zone
    return None


def dissolve_boxes_from_grid(
    grd_path: Path,
    element_box: list[list[int]],
    *,
    epsg: int | None = None,
) -> dict[int, list[list[float]]]:
    """Dissolve each box's element triangles from the .grd into one outer ring.

    ``element_box`` is a list of ``[element_id, box_id]`` pairs, as stored in
    the cache builder's ``meta["element_box"]``.

    The grid's source CRS is resolved via ``_resolve_grid_epsg`` (``epsg``
    argument -> ``grd.epsg`` -> geographic-looking bounds -> a detected UTM
    zone -> unresolvable). Nothing defaults silently to WGS84 for coordinates
    that are not actually geographic and have no known EPSG: mis-projecting a
    grid without telling the user is worse than refusing.

    Raises ``PolygonError`` (naming the grid file and, where known, the
    element/box) for: the geospatial stack not being installed, an
    unparseable grid, an unresolvable source CRS, an element referenced in
    ``element_box`` that is absent from the grid (one error listing the
    count and up to five example element ids), an element referencing a node
    absent from the grid, coordinates that reproject to non-finite or
    out-of-WGS84-bounds values, or a box that ends up with no contributing
    elements.
    """
    _require_geospatial_stack()
    grd_path = Path(grd_path)

    try:
        grd = GrdParser.parse_file(grd_path)
    except Exception as exc:
        raise PolygonError(f"{grd_path.name}: cannot parse grid ({exc})") from exc

    resolved_epsg = _resolve_grid_epsg(grd, epsg)
    if resolved_epsg is None:
        raise PolygonError(
            f"{grd_path.name}: grid is not in geographic coordinates and no EPSG is "
            "known; pass epsg= or provide boxes.polygons in the manifest"
        )
    to_wgs84 = (
        (lambda x, y: (x, y)) if resolved_epsg == 4326 else _to_wgs84(f"EPSG:{resolved_epsg}")
    )

    groups: dict[int, list] = {}
    contributed: dict[int, bool] = {}
    missing_elements: list[int] = []

    for raw_elem_id, raw_box_id in element_box:
        elem_id = int(raw_elem_id)
        box_id = int(raw_box_id)
        contributed.setdefault(box_id, False)

        element = grd.elements.get(elem_id)
        if element is None:
            missing_elements.append(elem_id)
            continue

        points: list[tuple[float, float]] = []
        for node_id in element.nodes:
            node = grd.nodes.get(node_id)
            if node is None:
                raise PolygonError(
                    f"{grd_path.name}: element {elem_id} (box {box_id}) references node "
                    f"{node_id}, which is absent from the grid"
                )
            x, y = to_wgs84(node.x, node.y)
            if _out_of_wgs84_bounds(x, y):
                raise PolygonError(
                    f"{grd_path.name}: element {elem_id} (box {box_id}) reprojected to "
                    f"invalid coordinates ({x}, {y})"
                )
            points.append((x, y))

        try:
            polygon = shapely.geometry.Polygon(points)
        except Exception as exc:
            raise PolygonError(
                f"{grd_path.name}: element {elem_id} (box {box_id}) could not be built "
                f"into a polygon ({exc})"
            ) from exc

        groups.setdefault(box_id, []).append(polygon)
        contributed[box_id] = True

    if missing_elements:
        examples = missing_elements[:5]
        raise PolygonError(
            f"{grd_path.name}: {len(missing_elements)} element(s) in element_box are "
            f"absent from the grid (examples: {examples})"
        )

    empty_boxes = sorted(box_id for box_id, has in contributed.items() if not has)
    if empty_boxes:
        raise PolygonError(f"{grd_path.name}: box(es) {empty_boxes} have no elements")

    out: dict[int, list[list[float]]] = {}
    for box_id, polygons in groups.items():
        try:
            union = shapely.ops.unary_union(polygons)
        except Exception as exc:
            raise PolygonError(
                f"{grd_path.name}: box {box_id} could not be dissolved ({exc})"
            ) from exc
        if union.geom_type == "MultiPolygon":
            # Disjoint parts (e.g. a box split by the grid): keep the largest by area.
            union = max(union.geoms, key=lambda g: g.area)
        if union.is_empty or union.geom_type != "Polygon":
            raise PolygonError(f"{grd_path.name}: box {box_id} dissolved to an empty shape")
        out[box_id] = [[round(x, 7), round(y, 7)] for x, y in union.exterior.coords]
    return out
