"""Parser for SHYFEM .grd (grid) files.

.grd file format:
- Lines starting with 0 are comments
- Type 1: Nodes  - "1 node_id type x y [depth]"
- Type 2: Elements   - "2 elem_id type nvert node1 node2 ... [depth]"
- Type 3: Lines      - "3 line_id type nvert node1 node2 ..."

nvert is the vertex count (3 for triangles, 4 for quads).
For line records with many nodes, IDs may continue on subsequent
file lines (multi-line continuation).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class GridParseError(Exception):
    """Raised when a .grd file cannot be parsed at all.

    Individual malformed lines produce warnings (accumulated in
    ``GrdFile.parse_warnings``) rather than raising this exception.
    This exception is reserved for catastrophic failures such as
    file-not-found or completely unreadable content.
    """


@dataclass
class Node:
    """A grid node."""

    id: int
    node_type: int
    x: float
    y: float
    depth: float | None = None


@dataclass
class Element:
    """A grid element (triangle or quad)."""

    id: int
    elem_type: int
    nodes: list[int] = field(default_factory=list)
    depth: float | None = None

    @property
    def is_triangle(self) -> bool:
        return len(self.nodes) == 3

    @property
    def is_quad(self) -> bool:
        return len(self.nodes) == 4


@dataclass
class Line:
    """A grid line (boundary)."""

    id: int
    line_type: int
    nodes: list[int] = field(default_factory=list)


class CoordinateSystem:
    """Detected coordinate system information for a grid."""

    GEOGRAPHIC = "geographic"  # lat/lon (degrees)
    CARTESIAN = "cartesian"  # meters or unknown units
    UTM = "utm"  # UTM projection (meters, known zone)

    def __init__(
        self, crs_type: str = "cartesian", utm_zone: int | None = None, utm_hemisphere: str = "N"
    ):
        self.crs_type = crs_type
        self.utm_zone = utm_zone
        self.utm_hemisphere = utm_hemisphere

    @property
    def is_geographic(self) -> bool:
        return self.crs_type == self.GEOGRAPHIC

    @property
    def is_utm(self) -> bool:
        return self.crs_type == self.UTM

    def __repr__(self) -> str:
        if self.crs_type == self.UTM:
            return f"UTM zone {self.utm_zone}{self.utm_hemisphere}"
        return self.crs_type


@dataclass
class GrdFile:
    """Parsed representation of a .grd file."""

    nodes: dict[int, Node] = field(default_factory=dict)
    elements: dict[int, Element] = field(default_factory=dict)
    lines: dict[int, Line] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    file_path: Path | None = None
    coordinate_system: CoordinateSystem | None = None
    epsg: int | None = None  # Source EPSG code (e.g. 32630 for UTM 30N)

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    @property
    def num_elements(self) -> int:
        return len(self.elements)

    @property
    def num_lines(self) -> int:
        return len(self.lines)

    @property
    def num_triangles(self) -> int:
        return sum(1 for e in self.elements.values() if e.is_triangle)

    @property
    def num_quads(self) -> int:
        return sum(1 for e in self.elements.values() if e.is_quad)

    def get_bounds(self) -> tuple[float, float, float, float]:
        """Get bounding box (xmin, ymin, xmax, ymax)."""
        if not self.nodes:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [n.x for n in self.nodes.values()]
        ys = [n.y for n in self.nodes.values()]
        return (min(xs), min(ys), max(xs), max(ys))

    def get_depth_range(self) -> tuple[float | None, float | None]:
        """Get depth range (min, max)."""
        depths = [n.depth for n in self.nodes.values() if n.depth is not None]
        if not depths:
            return (None, None)
        return (min(depths), max(depths))

    def get_node_types(self) -> set[int]:
        """Get all unique node types."""
        return {n.node_type for n in self.nodes.values()}

    def get_element_types(self) -> set[int]:
        """Get all unique element types."""
        return {e.elem_type for e in self.elements.values()}

    def get_line_types(self) -> set[int]:
        """Get all unique line types."""
        return {ln.line_type for ln in self.lines.values()}

    def detect_coordinate_system(self) -> CoordinateSystem:
        """Detect whether coordinates are geographic (lat/lon) or Cartesian.

        Heuristics:
        - Geographic: x in [-180, 360], y in [-90, 90]
        - UTM: x in [100_000, 900_000], y in [0, 10_000_000]
        - Otherwise: Cartesian (unknown units)

        Returns the detected CoordinateSystem (also stored in self.coordinate_system).
        """
        if not self.nodes:
            cs = CoordinateSystem()
            self.coordinate_system = cs
            return cs

        bounds = self.get_bounds()
        xmin, ymin, xmax, ymax = bounds

        # Check geographic (lon/lat in degrees)
        if -180 <= xmin and xmax <= 360 and -90 <= ymin and ymax <= 90:
            cs = CoordinateSystem(CoordinateSystem.GEOGRAPHIC)
            self.coordinate_system = cs
            return cs

        # Check UTM-like ranges (meters)
        if 100_000 <= xmin and xmax <= 900_000 and 0 <= ymin and ymax <= 10_000_000:
            # Estimate UTM zone from centroid longitude if possible
            # UTM easting is typically 166,000-834,000 in a single zone
            cs = CoordinateSystem(CoordinateSystem.UTM)
            # Hemisphere from y: southern if y < 10,000,000 isn't definitive,
            # but y > 5,000,000 for northern is more common in SHYFEM usage
            self.coordinate_system = cs
            return cs

        # Default: Cartesian
        cs = CoordinateSystem(CoordinateSystem.CARTESIAN)
        self.coordinate_system = cs
        return cs


def _utm_to_latlon(
    easting: float, northing: float, zone: int, northern: bool
) -> tuple[float, float]:
    """Convert UTM coordinates to latitude/longitude (WGS84).

    Simplified conversion without pyproj. Accurate to ~1 meter for
    typical coastal/lagoon applications.

    Args:
        easting: UTM easting in meters
        northing: UTM northing in meters
        zone: UTM zone number (1-60)
        northern: True for northern hemisphere

    Returns:
        (latitude, longitude) in decimal degrees
    """
    # WGS84 ellipsoid parameters
    a = 6378137.0  # semi-major axis
    f = 1 / 298.257223563  # flattening
    e = np.sqrt(2 * f - f**2)  # eccentricity
    e_prime = e / np.sqrt(1 - e**2)

    k0 = 0.9996  # scale factor
    x = easting - 500_000.0  # remove false easting
    y = northing
    if not northern:
        y -= 10_000_000.0  # remove false northing for southern hemisphere

    # Central meridian of the zone
    lon0 = np.radians((zone - 1) * 6 - 180 + 3)

    M = y / k0
    mu = M / (a * (1 - e**2 / 4 - 3 * e**4 / 64 - 5 * e**6 / 256))

    e1 = (1 - np.sqrt(1 - e**2)) / (1 + np.sqrt(1 - e**2))

    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * np.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * np.sin(4 * mu)
        + (151 * e1**3 / 96) * np.sin(6 * mu)
        + (1097 * e1**4 / 512) * np.sin(8 * mu)
    )

    sin_phi = np.sin(phi1)
    cos_phi = np.cos(phi1)
    tan_phi = np.tan(phi1)

    N1 = a / np.sqrt(1 - e**2 * sin_phi**2)
    T1 = tan_phi**2
    C1 = e_prime**2 * cos_phi**2
    R1 = a * (1 - e**2) / (1 - e**2 * sin_phi**2) ** 1.5
    D = x / (N1 * k0)

    lat = phi1 - (N1 * tan_phi / R1) * (
        D**2 / 2
        - (5 + 3 * T1 + 10 * C1 - 4 * C1**2 - 9 * e_prime**2) * D**4 / 24
        + (61 + 90 * T1 + 298 * C1 + 45 * T1**2 - 252 * e_prime**2 - 3 * C1**2) * D**6 / 720
    )

    lon = (
        lon0
        + (
            D
            - (1 + 2 * T1 + C1) * D**3 / 6
            + (5 - 2 * C1 + 28 * T1 - 3 * C1**2 + 8 * e_prime**2 + 24 * T1**2) * D**5 / 120
        )
        / cos_phi
    )

    return (np.degrees(lat), np.degrees(lon))


class GrdParser:
    """Parser for SHYFEM .grd grid files."""

    @classmethod
    def parse(cls, content: str) -> GrdFile:
        """Parse .grd file content into structured data.

        Handles malformed lines gracefully: individual bad fields are skipped
        with a warning rather than aborting the entire parse.
        """
        result = GrdFile()

        # State for multi-line continuation (line records with many nodes)
        pending_line: tuple | None = None  # (line_id, line_type, nvert, nodes, start_line)

        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue

            parts = stripped.split()
            if not parts:
                continue

            try:
                record_type = int(parts[0])
            except ValueError:
                result.parse_warnings.append(
                    f"Line {line_num}: skipped (invalid record type: {parts[0]!r})"
                )
                continue

            # Handle continuation lines for line records (record_type > 3
            # means this isn't a record header — it's continuation data)
            if pending_line is not None:
                if record_type > 3:
                    # Continuation: all fields are node IDs
                    pl_id, pl_type, pl_nvert, pl_nodes, pl_start = pending_line
                    for p in parts:
                        try:
                            pl_nodes.append(int(float(p)))
                        except ValueError:
                            pass
                    if len(pl_nodes) >= pl_nvert:
                        result.lines[pl_id] = Line(
                            id=pl_id, line_type=pl_type, nodes=pl_nodes[:pl_nvert]
                        )
                        pending_line = None
                    else:
                        pending_line = (pl_id, pl_type, pl_nvert, pl_nodes, pl_start)
                    continue
                else:
                    # New record header encountered — finalize pending line
                    pl_id, pl_type, pl_nvert, pl_nodes, pl_start = pending_line
                    if len(pl_nodes) >= 2:
                        result.lines[pl_id] = Line(id=pl_id, line_type=pl_type, nodes=pl_nodes)
                    else:
                        result.parse_warnings.append(
                            f"Line {pl_start}: line {pl_id} expected {pl_nvert} nodes, "
                            f"got {len(pl_nodes)}"
                        )
                    pending_line = None

            try:
                if record_type == 0:
                    # Comment line
                    result.comments.append(" ".join(parts[1:]))

                elif record_type == 1:
                    # Node: 1 id type x y [depth]
                    if len(parts) < 5:
                        result.parse_warnings.append(
                            f"Line {line_num}: node record has {len(parts)} fields (need >= 5)"
                        )
                        continue
                    node_id = int(parts[1])
                    node_type = int(parts[2])
                    x = float(parts[3])
                    y = float(parts[4])
                    depth = None
                    if len(parts) > 5:
                        try:
                            depth = float(parts[5])
                        except ValueError:
                            result.parse_warnings.append(
                                f"Line {line_num}: invalid depth value {parts[5]!r}, ignoring"
                            )
                    result.nodes[node_id] = Node(
                        id=node_id, node_type=node_type, x=x, y=y, depth=depth
                    )

                elif record_type == 2:
                    # Element: 2 id type nvert node1 node2 ... [depth]
                    # nvert = vertex count (3 for triangles, 4 for quads)
                    if len(parts) < 7:
                        result.parse_warnings.append(
                            f"Line {line_num}: element record has {len(parts)} fields (need >= 7)"
                        )
                        continue
                    elem_id = int(parts[1])
                    elem_type = int(parts[2])
                    nvert = int(parts[3])
                    node_ids = [int(parts[4 + i]) for i in range(nvert)]
                    # Optional depth after the last node
                    depth = None
                    depth_idx = 4 + nvert
                    if depth_idx < len(parts):
                        try:
                            depth = float(parts[depth_idx])
                        except ValueError:
                            pass
                    if len(node_ids) < 3:
                        result.parse_warnings.append(
                            f"Line {line_num}: element {elem_id} has {len(node_ids)} valid nodes (need >= 3)"
                        )
                        continue
                    result.elements[elem_id] = Element(
                        id=elem_id, elem_type=elem_type, nodes=node_ids, depth=depth
                    )

                elif record_type == 3:
                    # Line: 3 id type nvert node1 node2 ...
                    # nvert = vertex count; nodes may continue on subsequent lines
                    if len(parts) < 4:
                        result.parse_warnings.append(
                            f"Line {line_num}: line record has {len(parts)} fields (need >= 4)"
                        )
                        continue
                    line_id = int(parts[1])
                    line_type = int(parts[2])
                    nvert = int(parts[3])
                    # Read any nodes present on the same line after nvert
                    node_ids = []
                    for p in parts[4:]:
                        try:
                            node_ids.append(int(float(p)))
                        except ValueError:
                            break
                    if len(node_ids) < nvert:
                        # Remaining nodes will come on continuation lines;
                        # store partial state and collect in subsequent iterations
                        pending_line = (line_id, line_type, nvert, node_ids, line_num)
                        continue
                    if len(node_ids) < 2:
                        result.parse_warnings.append(
                            f"Line {line_num}: line {line_id} has {len(node_ids)} valid nodes (need >= 2)"
                        )
                        continue
                    result.lines[line_id] = Line(
                        id=line_id, line_type=line_type, nodes=node_ids[:nvert]
                    )

            except (ValueError, IndexError) as e:
                result.parse_warnings.append(f"Line {line_num}: skipped ({e})")
                continue

        # Finalize any pending line record at end of file
        if pending_line is not None:
            pl_id, pl_type, pl_nvert, pl_nodes, pl_start = pending_line
            if len(pl_nodes) >= 2:
                result.lines[pl_id] = Line(id=pl_id, line_type=pl_type, nodes=pl_nodes)
            else:
                result.parse_warnings.append(
                    f"Line {pl_start}: line {pl_id} expected {pl_nvert} nodes, "
                    f"got {len(pl_nodes)}"
                )

        return result

    # File-level cache: (resolved_path, mtime_ns, size) -> GrdFile
    _file_cache: dict[tuple, "GrdFile"] = {}
    _FILE_CACHE_MAX = 8

    @classmethod
    def parse_file(cls, file_path: Path | str) -> GrdFile:
        """Parse a .grd file from disk, with caching by path+mtime+size.

        Returns a cached result if the file hasn't changed since last parse.

        Raises:
            GridParseError: If the file cannot be read.
        """
        file_path = Path(file_path)
        try:
            stat = file_path.stat()
        except FileNotFoundError as exc:
            raise GridParseError(f"Grid file not found: {file_path}") from exc
        except OSError as exc:
            raise GridParseError(f"Cannot read grid file {file_path}: {exc}") from exc

        cache_key = (str(file_path.resolve()), stat.st_mtime_ns, stat.st_size)
        if cache_key in cls._file_cache:
            logger.debug("Grid cache hit: %s", file_path)
            return cls._file_cache[cache_key]

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise GridParseError(f"Cannot read grid file {file_path}: {exc}") from exc

        result = cls.parse(content)
        result.file_path = file_path

        # Evict oldest entries if cache is full
        if len(cls._file_cache) >= cls._FILE_CACHE_MAX:
            oldest_key = next(iter(cls._file_cache))
            del cls._file_cache[oldest_key]
        cls._file_cache[cache_key] = result
        logger.debug("Grid cached: %s (%d nodes)", file_path, result.num_nodes)
        return result

    @classmethod
    def generate(cls, grd_file: GrdFile) -> str:
        """Generate .grd file content from structured data."""
        lines = []

        # Comments
        for comment in grd_file.comments:
            lines.append(f"0 {comment}")

        # Nodes
        for node in sorted(grd_file.nodes.values(), key=lambda n: n.id):
            if node.depth is not None:
                lines.append(
                    f"1 {node.id} {node.node_type} {node.x:.6f} {node.y:.6f} {node.depth:.6f}"
                )
            else:
                lines.append(f"1 {node.id} {node.node_type} {node.x:.6f} {node.y:.6f}")

        # Elements: 2 id type nvert node1 node2 ... [depth]
        for elem in sorted(grd_file.elements.values(), key=lambda e: e.id):
            nodes_str = " ".join(str(n) for n in elem.nodes)
            depth_str = f" {elem.depth:.6f}" if elem.depth is not None else ""
            lines.append(f"2 {elem.id} {elem.elem_type} {len(elem.nodes)} {nodes_str}{depth_str}")

        # Lines: 3 id type nvert node1 node2 ...
        for ln in sorted(grd_file.lines.values(), key=lambda ln_: ln_.id):
            nodes_str = " ".join(str(n) for n in ln.nodes)
            lines.append(f"3 {ln.id} {ln.line_type} {len(ln.nodes)} {nodes_str}")

        return "\n".join(lines)

    @classmethod
    def save(cls, grd_file: GrdFile, file_path: Path | str) -> None:
        """Save .grd file to disk."""
        file_path = Path(file_path)
        content = cls.generate(grd_file)
        file_path.write_text(content, encoding="utf-8")

    @classmethod
    def get_statistics(cls, grd_file: GrdFile) -> dict:
        """Get comprehensive statistics about the grid."""
        bounds = grd_file.get_bounds()
        depth_range = grd_file.get_depth_range()

        # Auto-detect coordinate system if not already set
        cs = grd_file.coordinate_system
        if cs is None:
            cs = grd_file.detect_coordinate_system()

        return {
            "num_nodes": grd_file.num_nodes,
            "num_elements": grd_file.num_elements,
            "num_triangles": grd_file.num_triangles,
            "num_quads": grd_file.num_quads,
            "num_lines": grd_file.num_lines,
            "bounds": {
                "xmin": bounds[0],
                "ymin": bounds[1],
                "xmax": bounds[2],
                "ymax": bounds[3],
                "width": bounds[2] - bounds[0],
                "height": bounds[3] - bounds[1],
            },
            "depth": {
                "min": depth_range[0],
                "max": depth_range[1],
            },
            "node_types": sorted(grd_file.get_node_types()),
            "element_types": sorted(grd_file.get_element_types()),
            "line_types": sorted(grd_file.get_line_types()),
            "coordinate_system": str(cs),
        }
