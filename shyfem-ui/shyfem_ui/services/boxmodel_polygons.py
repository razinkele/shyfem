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

from collections.abc import Callable
from pathlib import Path

MAX_POLYGON_BYTES = 50 * 1024 * 1024
MAX_FEATURES = 1000
MAX_VERTICES = 200_000
ALLOWED_DRIVERS = ("GPKG", "GeoJSON")


class PolygonError(ValueError):
    """User-facing polygon-file problem."""


def _to_wgs84(crs) -> Callable[[float, float], tuple[float, float]]:
    """Build an (x, y) -> (lon, lat) transform for the given source CRS.

    ``crs`` may be falsy (no CRS on the source, e.g. a bare GeoJSON, which is
    assumed to already be WGS84 lon/lat per RFC 7946).
    """
    from pyproj import CRS, Transformer

    src = CRS.from_user_input(crs) if crs else CRS.from_epsg(4326)
    if src.to_epsg() == 4326:
        return lambda x, y: (x, y)
    transformer = Transformer.from_crs(src, CRS.from_epsg(4326), always_xy=True)
    return lambda x, y: transformer.transform(x, y)


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
    a missing/oversized/symlinked file, a disallowed driver, too many
    features or vertices, a missing/non-integer/duplicate id field, a
    geometry that cannot be reprojected, or (when ``expected_boxes`` is
    given) a box-id set that does not match it exactly.
    """
    import fiona

    path = Path(path)
    try:
        is_symlink = path.is_symlink()
        is_file = path.is_file()
    except OSError as exc:
        raise PolygonError(f"{path}: cannot stat polygon file ({exc})") from exc
    if is_symlink or not is_file:
        raise PolygonError(f"{path}: polygon file must be a regular file, not a symlink")
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
        # ambiguous "json" schema type; fiona then raises while *building* that
        # feature (not later, when the field is read), so we route the id-field
        # message through this flag rather than a generic message.
        ambiguous_id_type = schema_props[id_field] == "json"
        try:
            to_wgs84 = _to_wgs84(src.crs)
        except Exception as exc:
            raise PolygonError(f"{path}: cannot reproject polygons to WGS84 ({exc})") from exc

        out: dict[int, list[list[float]]] = {}
        vertex_count = 0
        iterator = iter(src)
        index = 0
        while True:
            try:
                feature = next(iterator)
            except StopIteration:
                break
            except Exception as exc:
                if ambiguous_id_type:
                    raise PolygonError(
                        f"{path}: field {id_field!r} must be an integer on every feature "
                        f"(inconsistent types across features: {exc})"
                    ) from exc
                raise PolygonError(f"{path}: cannot read feature {index} ({exc})") from exc

            if index >= MAX_FEATURES:
                raise PolygonError(f"{path}: more than {MAX_FEATURES} features")
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
            ring = _outer_ring(dict(geometry), path, box)

            vertex_count += len(ring)
            if vertex_count > MAX_VERTICES:
                raise PolygonError(f"{path}: more than {MAX_VERTICES} total vertices")

            wgs_ring = [list(to_wgs84(x, y)) for x, y in ring]
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


def dissolve_boxes_from_grid(
    grd_path: Path, element_box: list[list[int]]
) -> dict[int, list[list[float]]]:
    """Dissolve each box's element triangles from the .grd into one outer ring.

    ``element_box`` is a list of ``[element_id, box_id]`` pairs, as stored in
    the cache builder's ``meta["element_box"]``. Coordinates are reprojected
    to WGS84 when the grid carries a non-WGS84 EPSG code.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    from shyfem_ui.services.parser_grd import GrdParser

    grd = GrdParser.parse_file(grd_path)
    to_wgs84 = (
        _to_wgs84(f"EPSG:{grd.epsg}") if grd.epsg and grd.epsg != 4326 else (lambda x, y: (x, y))
    )

    groups: dict[int, list[Polygon]] = {}
    for elem_id, box_id in element_box:
        element = grd.elements.get(int(elem_id))
        if element is None:
            continue
        points = [to_wgs84(grd.nodes[n].x, grd.nodes[n].y) for n in element.nodes]
        groups.setdefault(int(box_id), []).append(Polygon(points))

    out: dict[int, list[list[float]]] = {}
    for box_id, polygons in groups.items():
        union = unary_union(polygons)
        if union.geom_type == "MultiPolygon":
            # Disjoint parts (e.g. a box split by the grid): keep the largest by area.
            union = max(union.geoms, key=lambda g: g.area)
        out[box_id] = [[round(x, 7), round(y, 7)] for x, y in union.exterior.coords]
    return out
