"""Parser for SHYFEM .grd (grid) files.

.grd file format:
- Lines starting with 0 are comments
- Type 1: Nodes - "1 node_id type x y [depth]"
- Type 2: Elements - "2 elem_id type node1 node2 node3 [node4...]"
- Type 3: Lines/Boundaries - "3 line_id type node1 node2 [node3...]"
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class Node:
    """A grid node."""

    id: int
    node_type: int
    x: float
    y: float
    depth: Optional[float] = None


@dataclass
class Element:
    """A grid element (triangle or quad)."""

    id: int
    elem_type: int
    nodes: list[int] = field(default_factory=list)

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


@dataclass
class GrdFile:
    """Parsed representation of a .grd file."""

    nodes: dict[int, Node] = field(default_factory=dict)
    elements: dict[int, Element] = field(default_factory=dict)
    lines: dict[int, Line] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    file_path: Optional[Path] = None

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

    def get_depth_range(self) -> tuple[Optional[float], Optional[float]]:
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

    def get_nodes_array(self) -> np.ndarray:
        """Get node coordinates as numpy array (N x 2 or N x 3)."""
        if not self.nodes:
            return np.array([])
        has_depth = any(n.depth is not None for n in self.nodes.values())
        if has_depth:
            return np.array(
                [[n.x, n.y, n.depth or 0.0] for n in self.nodes.values()]
            )
        return np.array([[n.x, n.y] for n in self.nodes.values()])

    def get_elements_array(self) -> np.ndarray:
        """Get element connectivity as numpy array (padded with -1 for mixed meshes)."""
        if not self.elements:
            return np.array([])
        max_nodes = max(len(e.nodes) for e in self.elements.values())
        result = np.full((len(self.elements), max_nodes), -1, dtype=np.int32)
        for i, elem in enumerate(self.elements.values()):
            result[i, : len(elem.nodes)] = elem.nodes
        return result


class GrdParser:
    """Parser for SHYFEM .grd grid files."""

    @classmethod
    def parse(cls, content: str) -> GrdFile:
        """Parse .grd file content into structured data."""
        result = GrdFile()

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            parts = stripped.split()
            if not parts:
                continue

            try:
                record_type = int(parts[0])
            except ValueError:
                # Invalid line, skip
                continue

            if record_type == 0:
                # Comment line
                result.comments.append(" ".join(parts[1:]))

            elif record_type == 1:
                # Node: 1 id type x y [depth]
                if len(parts) >= 5:
                    node_id = int(parts[1])
                    node_type = int(parts[2])
                    x = float(parts[3])
                    y = float(parts[4])
                    depth = float(parts[5]) if len(parts) > 5 else None
                    result.nodes[node_id] = Node(
                        id=node_id, node_type=node_type, x=x, y=y, depth=depth
                    )

            elif record_type == 2:
                # Element: 2 id type node1 node2 node3 [node4...]
                if len(parts) >= 6:
                    elem_id = int(parts[1])
                    elem_type = int(parts[2])
                    nodes = [int(p) for p in parts[3:]]
                    result.elements[elem_id] = Element(
                        id=elem_id, elem_type=elem_type, nodes=nodes
                    )

            elif record_type == 3:
                # Line: 3 id type node1 node2 [node3...]
                if len(parts) >= 5:
                    line_id = int(parts[1])
                    line_type = int(parts[2])
                    nodes = [int(p) for p in parts[3:]]
                    result.lines[line_id] = Line(
                        id=line_id, line_type=line_type, nodes=nodes
                    )

        return result

    @classmethod
    def parse_file(cls, file_path: Path | str) -> GrdFile:
        """Parse a .grd file from disk."""
        file_path = Path(file_path)
        content = file_path.read_text(encoding="utf-8", errors="replace")
        result = cls.parse(content)
        result.file_path = file_path
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
                lines.append(
                    f"1 {node.id} {node.node_type} {node.x:.6f} {node.y:.6f}"
                )

        # Elements
        for elem in sorted(grd_file.elements.values(), key=lambda e: e.id):
            nodes_str = " ".join(str(n) for n in elem.nodes)
            lines.append(f"2 {elem.id} {elem.elem_type} {nodes_str}")

        # Lines
        for ln in sorted(grd_file.lines.values(), key=lambda l: l.id):
            nodes_str = " ".join(str(n) for n in ln.nodes)
            lines.append(f"3 {ln.id} {ln.line_type} {nodes_str}")

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
        }
