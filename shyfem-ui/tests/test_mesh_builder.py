"""Unit tests for mesh builder service.

Tests the pure-Python mesh generation pipeline: boundary import,
smoothing, reduction, triangulation, bathymetry interpolation,
validation, and statistics.
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from shyfem_ui.services.mesh_builder import (
    compute_mesh_stats,
    estimate_element_count,
    export_grd,
    extract_boundary_zero_points,
    import_boundaries,
    interpolate_bathymetry_scipy,
    load_bathymetry_contours,
    load_bathymetry_file,
    reduce_boundary,
    set_resolution,
    smooth_boundary,
    triangulate,
    validate_boundary,
)
from shyfem_ui.services.parser_grd import (
    Element,
    GrdFile,
    GrdParser,
    Line,
    Node,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_square_boundary(x0=0.0, y0=0.0, size=10.0) -> GrdFile:
    """Create a GrdFile with a simple square boundary."""
    grd = GrdFile()
    grd.nodes[1] = Node(id=1, node_type=0, x=x0, y=y0)
    grd.nodes[2] = Node(id=2, node_type=0, x=x0 + size, y=y0)
    grd.nodes[3] = Node(id=3, node_type=0, x=x0 + size, y=y0 + size)
    grd.nodes[4] = Node(id=4, node_type=0, x=x0, y=y0 + size)
    grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1])
    return grd


def _make_square_with_hole() -> GrdFile:
    """Square boundary with a smaller square hole inside."""
    grd = _make_square_boundary(size=10.0)
    # Inner hole (type 2)
    grd.nodes[5] = Node(id=5, node_type=0, x=3.0, y=3.0)
    grd.nodes[6] = Node(id=6, node_type=0, x=7.0, y=3.0)
    grd.nodes[7] = Node(id=7, node_type=0, x=7.0, y=7.0)
    grd.nodes[8] = Node(id=8, node_type=0, x=3.0, y=7.0)
    grd.lines[2] = Line(id=2, line_type=2, nodes=[5, 6, 7, 8, 5])
    return grd


def _make_geojson_polygon(coords, path: Path) -> Path:
    """Write a GeoJSON Polygon file."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords],
                },
                "properties": {},
            }
        ],
    }
    path.write_text(json.dumps(geojson))
    return path


def _make_geojson_multipolygon_with_hole(path: Path) -> Path:
    """Write a GeoJSON MultiPolygon with one hole."""
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [
                            # Exterior ring
                            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
                            # Hole
                            [[3, 3], [7, 3], [7, 7], [3, 7], [3, 3]],
                        ]
                    ],
                },
                "properties": {},
            }
        ],
    }
    path.write_text(json.dumps(geojson))
    return path


def _make_simple_mesh() -> GrdFile:
    """Create a simple mesh with 2 triangles for testing."""
    grd = GrdFile()
    grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0, depth=1.0)
    grd.nodes[2] = Node(id=2, node_type=0, x=10.0, y=0.0, depth=2.0)
    grd.nodes[3] = Node(id=3, node_type=0, x=10.0, y=10.0, depth=3.0)
    grd.nodes[4] = Node(id=4, node_type=0, x=0.0, y=10.0, depth=4.0)
    # Triangles in .grd format: [3, n1, n2, n3]
    grd.elements[1] = Element(id=1, elem_type=0, nodes=[3, 1, 2, 3])
    grd.elements[2] = Element(id=2, elem_type=0, nodes=[3, 1, 3, 4])
    grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1])
    return grd


# ---------------------------------------------------------------------------
# TestImportBoundaries
# ---------------------------------------------------------------------------


class TestImportBoundaries:
    """Tests for import_boundaries()."""

    def test_geojson_polygon(self, tmp_path):
        """Simple polygon imports as one exterior boundary line."""
        coords = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        path = _make_geojson_polygon(coords, tmp_path / "test.geojson")
        grd = import_boundaries(path)
        assert len(grd.nodes) >= 4
        assert len(grd.lines) == 1
        assert grd.lines[1].line_type == 1

    def test_multipolygon_with_hole(self, tmp_path):
        """MultiPolygon with hole creates exterior + hole boundary."""
        path = _make_geojson_multipolygon_with_hole(tmp_path / "test.geojson")
        grd = import_boundaries(path)
        assert len(grd.lines) == 2
        line_types = {line.line_type for line in grd.lines.values()}
        assert 1 in line_types  # exterior
        assert 2 in line_types  # hole

    def test_empty_geometry_warning(self, tmp_path):
        """Empty FeatureCollection produces a warning."""
        geojson = {"type": "FeatureCollection", "features": []}
        path = tmp_path / "empty.geojson"
        path.write_text(json.dumps(geojson))
        grd = import_boundaries(path)
        assert len(grd.nodes) == 0
        assert any("No geometries" in w for w in grd.parse_warnings)

    def test_shapefile_import(self, tmp_path):
        """Import from Shapefile (written via fiona)."""
        import fiona
        from fiona.crs import CRS

        schema = {"geometry": "Polygon", "properties": {"name": "str"}}
        path = tmp_path / "test.shp"
        with fiona.open(str(path), "w", driver="ESRI Shapefile", schema=schema, crs=CRS.from_epsg(4326)) as dst:
            dst.write({
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]],
                },
                "properties": {"name": "test"},
            })
        grd = import_boundaries(path)
        assert len(grd.nodes) >= 4
        assert len(grd.lines) == 1

    def test_unsupported_geometry_type(self, tmp_path):
        """Point geometry produces a warning."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [1, 2]},
                    "properties": {},
                }
            ],
        }
        path = tmp_path / "point.geojson"
        path.write_text(json.dumps(geojson))
        grd = import_boundaries(path)
        assert any("unsupported" in w.lower() or "Skipped" in w for w in grd.parse_warnings)


# ---------------------------------------------------------------------------
# TestSmoothBoundary
# ---------------------------------------------------------------------------


class TestSmoothBoundary:
    """Tests for smooth_boundary()."""

    def test_chaikin_increases_points(self):
        """Chaikin smoothing roughly doubles points per iteration."""
        grd = _make_square_boundary()
        original_count = len(grd.lines[1].nodes)
        smoothed = smooth_boundary(grd, line_id=1, method="chaikin", iterations=1)
        new_count = len(smoothed.lines[1].nodes)
        assert new_count > original_count

    def test_gaussian_preserves_point_count(self):
        """Gaussian smoothing keeps the same number of points."""
        grd = _make_square_boundary()
        original_count = len(grd.lines[1].nodes)
        smoothed = smooth_boundary(grd, line_id=1, method="gaussian", iterations=1, sigma=0.5)
        new_count = len(smoothed.lines[1].nodes)
        assert new_count == original_count

    def test_invalid_line_id_raises(self):
        """Non-existent line ID raises ValueError."""
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="Line 99"):
            smooth_boundary(grd, line_id=99)


# ---------------------------------------------------------------------------
# TestReduceBoundary
# ---------------------------------------------------------------------------


class TestReduceBoundary:
    """Tests for reduce_boundary()."""

    def test_reduces_point_count(self):
        """Douglas-Peucker with non-zero tolerance reduces points."""
        # Create a boundary with many points (circle approximation)
        grd = GrdFile()
        n = 50
        nodes = []
        for i in range(n):
            angle = 2 * np.pi * i / n
            nid = i + 1
            grd.nodes[nid] = Node(id=nid, node_type=0, x=np.cos(angle) * 10, y=np.sin(angle) * 10)
            nodes.append(nid)
        nodes.append(1)  # close ring
        grd.lines[1] = Line(id=1, line_type=1, nodes=nodes)

        reduced = reduce_boundary(grd, line_id=1, tolerance=1.0)
        assert len(reduced.lines[1].nodes) < len(grd.lines[1].nodes)

    def test_preserves_topology(self):
        """Reduced boundary still forms a closed ring."""
        grd = _make_square_boundary()
        reduced = reduce_boundary(grd, line_id=1, tolerance=0.1)
        nodes = reduced.lines[1].nodes
        # Should still be at least a triangle
        assert len(nodes) >= 4  # 3 points + closing

    def test_zero_tolerance_preserves(self):
        """Zero tolerance keeps all points."""
        grd = _make_square_boundary()
        original_count = len(grd.lines[1].nodes)
        reduced = reduce_boundary(grd, line_id=1, tolerance=0.0)
        # Shapely may or may not dedup exactly, but count should be >= original
        assert len(reduced.lines[1].nodes) >= original_count - 1


# ---------------------------------------------------------------------------
# TestTriangulate
# ---------------------------------------------------------------------------


class TestTriangulate:
    """Tests for triangulate()."""

    def test_simple_square(self):
        """Square boundary produces triangulated mesh."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=50.0)
        assert len(mesh.elements) >= 2
        assert len(mesh.nodes) >= 4

    def test_with_hole(self):
        """Domain with hole excludes hole interior from mesh."""
        grd = _make_square_with_hole()
        mesh = triangulate(grd, max_area=5.0)
        assert len(mesh.elements) > 0
        # All element centroids should be outside the hole
        for elem in mesh.elements.values():
            nids = elem.nodes
            if len(nids) == 4 and nids[0] == 3:
                nids = nids[1:]
            coords = [(mesh.nodes[nid].x, mesh.nodes[nid].y) for nid in nids if nid in mesh.nodes]
            if len(coords) == 3:
                cx = sum(c[0] for c in coords) / 3
                cy = sum(c[1] for c in coords) / 3
                # Centroid should not be inside the hole (3,3)-(7,7)
                in_hole = 3.5 < cx < 6.5 and 3.5 < cy < 6.5
                assert not in_hole, f"Element centroid ({cx}, {cy}) is inside hole"

    def test_min_angle_constraint(self):
        """min_angle produces higher quality triangles."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0, min_angle=25.0)
        assert len(mesh.elements) >= 2

    def test_max_area_produces_more_elements(self):
        """Smaller max_area produces more elements."""
        grd = _make_square_boundary()
        mesh_coarse = triangulate(grd, max_area=50.0)
        mesh_fine = triangulate(grd, max_area=5.0)
        assert len(mesh_fine.elements) > len(mesh_coarse.elements)

    def test_empty_boundary_raises(self):
        """Grid with no lines raises error."""
        grd = GrdFile()
        with pytest.raises(Exception):
            triangulate(grd)


# ---------------------------------------------------------------------------
# TestInterpolateScipy
# ---------------------------------------------------------------------------


class TestInterpolateScipy:
    """Tests for interpolate_bathymetry_scipy()."""

    def _make_mesh_and_bathy(self):
        """Create a mesh + known bathymetry grid."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        # Bathymetry: z = x + y (linear, easy to verify)
        bathy = np.array([
            [0, 0, 0], [10, 0, 10], [0, 10, 10], [10, 10, 20],
            [5, 5, 10], [5, 0, 5], [0, 5, 5],
        ])
        return mesh, bathy

    def test_linear_interpolation(self):
        """Linear method produces reasonable depth values."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="linear")
        for node in result.nodes.values():
            assert node.depth is not None
            # z = x + y, so depth should be close to x + y
            expected = node.x + node.y
            assert abs(node.depth - expected) < 3.0  # allow some tolerance

    def test_nearest_interpolation(self):
        """Nearest method sets all depths."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="nearest")
        for node in result.nodes.values():
            assert node.depth is not None

    def test_idw_interpolation(self):
        """IDW method produces weighted average depths."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="idw")
        for node in result.nodes.values():
            assert node.depth is not None

    def test_cubic_interpolation(self):
        """Cubic method interpolates all nodes."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="cubic")
        for node in result.nodes.values():
            assert node.depth is not None


# ---------------------------------------------------------------------------
# TestRBFInterpolation
# ---------------------------------------------------------------------------


class TestRBFInterpolation:
    """Tests for RBF (thin-plate spline) interpolation method."""

    def _make_mesh_and_bathy(self):
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        bathy = np.array([
            [0, 0, 0], [10, 0, 10], [0, 10, 10], [10, 10, 20],
            [5, 5, 10], [5, 0, 5], [0, 5, 5],
        ])
        return mesh, bathy

    def test_rbf_sets_all_depths(self):
        """RBF method assigns depth to every node."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="rbf")
        for node in result.nodes.values():
            assert node.depth is not None
            assert not np.isnan(node.depth)

    def test_rbf_extrapolates_beyond_hull(self):
        """RBF naturally extrapolates — no NaN outside convex hull."""
        grd = _make_square_boundary(size=20.0)
        mesh = triangulate(grd, max_area=20.0)
        # Bathy covers only center 5x5 area
        bathy = np.array([
            [8, 8, 5], [12, 8, 5], [8, 12, 5], [12, 12, 10],
        ])
        result = interpolate_bathymetry_scipy(mesh, bathy, method="rbf")
        depths = [n.depth for n in result.nodes.values()]
        assert all(d is not None for d in depths)
        assert not any(np.isnan(d) for d in depths)

    def test_rbf_smooth_surface(self):
        """RBF on z=x+y produces smooth, reasonable values."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="rbf")
        for node in result.nodes.values():
            expected = node.x + node.y
            assert abs(node.depth - expected) < 5.0


# ---------------------------------------------------------------------------
# TestCloughTocherInterpolation
# ---------------------------------------------------------------------------


class TestCloughTocherInterpolation:
    """Tests for CloughTocher C1 cubic interpolation."""

    def _make_mesh_and_bathy(self):
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        bathy = np.array([
            [0, 0, 0], [10, 0, 10], [0, 10, 10], [10, 10, 20],
            [5, 5, 10], [5, 0, 5], [0, 5, 5],
        ])
        return mesh, bathy

    def test_cloughtocher_sets_all_depths(self):
        """CloughTocher assigns depth to every node."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="cloughtocher")
        for node in result.nodes.values():
            assert node.depth is not None
            assert not np.isnan(node.depth)

    def test_cloughtocher_smooth_surface(self):
        """CloughTocher on z=x+y produces smooth, reasonable values."""
        mesh, bathy = self._make_mesh_and_bathy()
        result = interpolate_bathymetry_scipy(mesh, bathy, method="cloughtocher")
        for node in result.nodes.values():
            expected = node.x + node.y
            assert abs(node.depth - expected) < 5.0

    def test_cloughtocher_fills_outside_hull(self):
        """Nodes outside hull get nearest-neighbor fallback, not NaN."""
        grd = _make_square_boundary(size=20.0)
        mesh = triangulate(grd, max_area=20.0)
        bathy = np.array([
            [8, 8, 5], [12, 8, 5], [8, 12, 5], [12, 12, 10],
        ])
        result = interpolate_bathymetry_scipy(mesh, bathy, method="cloughtocher")
        depths = [n.depth for n in result.nodes.values()]
        assert all(d is not None for d in depths)
        assert not any(np.isnan(d) for d in depths)


# ---------------------------------------------------------------------------
# TestBoundaryZeroInjection
# ---------------------------------------------------------------------------


class TestBoundaryZeroInjection:
    """Tests for extract_boundary_zero_points and use_boundary_zero flag."""

    def test_extract_boundary_zero_points(self):
        """Boundary nodes produce depth=0 points."""
        grd = _make_square_boundary()
        pts = extract_boundary_zero_points(grd)
        assert pts.shape[1] == 3
        assert len(pts) == 4  # 4 unique nodes (closing node is duplicate)
        np.testing.assert_allclose(pts[:, 2], 0.0)

    def test_boundary_zero_with_linear(self):
        """use_boundary_zero forces boundary nodes to near-zero depth."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        # Bathy: constant depth=10 everywhere
        bathy = np.array([
            [2, 2, 10], [8, 2, 10], [2, 8, 10], [8, 8, 10], [5, 5, 10],
        ])
        # Without boundary zero: all nodes ~10
        result_no_bz = interpolate_bathymetry_scipy(
            mesh, bathy, method="linear", use_boundary_zero=False
        )
        # With boundary zero: boundary nodes pulled toward 0
        result_bz = interpolate_bathymetry_scipy(
            mesh, bathy, method="linear", use_boundary_zero=True
        )
        # Some boundary-adjacent nodes should have lower depth with boundary=0
        depths_no_bz = [n.depth for n in result_no_bz.nodes.values()]
        depths_bz = [n.depth for n in result_bz.nodes.values()]
        assert min(depths_bz) < min(depths_no_bz)

    def test_boundary_zero_with_rbf(self):
        """RBF + boundary_zero produces zero at coastline."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        bathy = np.array([
            [5, 5, 20], [3, 3, 15], [7, 7, 15],
        ])
        result = interpolate_bathymetry_scipy(
            mesh, bathy, method="rbf", use_boundary_zero=True
        )
        # Interior should have high depth, edges should be near zero
        boundary_nids = set()
        for line in mesh.lines.values():
            boundary_nids.update(line.nodes)
        boundary_depths = [
            result.nodes[nid].depth for nid in boundary_nids if nid in result.nodes
        ]
        interior_depths = [
            n.depth for nid, n in result.nodes.items() if nid not in boundary_nids
        ]
        if boundary_depths and interior_depths:
            assert np.mean(boundary_depths) < np.mean(interior_depths)

    def test_empty_boundary_no_crash(self):
        """Grid with no lines returns empty array."""
        grd = GrdFile()
        pts = extract_boundary_zero_points(grd)
        assert pts.shape == (0, 3)


# ---------------------------------------------------------------------------
# TestLoadBathymetry
# ---------------------------------------------------------------------------


class TestLoadBathymetry:
    """Tests for load_bathymetry_file()."""

    def test_csv_xyz(self, tmp_path):
        """Comma-separated x,y,z file loads correctly."""
        path = tmp_path / "bathy.csv"
        path.write_text("1.0,2.0,3.0\n4.0,5.0,6.0\n7.0,8.0,9.0\n")
        data = load_bathymetry_file(path)
        assert data.shape == (3, 3)
        np.testing.assert_allclose(data[0], [1.0, 2.0, 3.0])

    def test_space_separated(self, tmp_path):
        """Space-separated file loads correctly."""
        path = tmp_path / "bathy.xyz"
        path.write_text("1.0 2.0 3.0\n4.0 5.0 6.0\n")
        data = load_bathymetry_file(path)
        assert data.shape == (2, 3)

    def test_missing_file_raises(self):
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_bathymetry_file(Path("/nonexistent/bathy.xyz"))

    def test_skips_comments(self, tmp_path):
        """Lines starting with # or ! are skipped."""
        path = tmp_path / "bathy.xyz"
        path.write_text("# header\n! comment\n1 2 3\n4 5 6\n")
        data = load_bathymetry_file(path)
        assert data.shape == (2, 3)


# ---------------------------------------------------------------------------
# TestLoadBathymetryContours
# ---------------------------------------------------------------------------


class TestLoadBathymetryContours:
    """Tests for load_bathymetry_contours()."""

    def test_geojson_linestring_contours(self, tmp_path):
        """LineString features with depth attribute produce points."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0], [5, 0], [10, 0]],
                    },
                    "properties": {"depth": 10.0},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 5], [5, 5], [10, 5]],
                    },
                    "properties": {"depth": 20.0},
                },
            ],
        }
        path = tmp_path / "isobaths.geojson"
        path.write_text(json.dumps(geojson))
        data = load_bathymetry_contours(path)
        assert data.shape == (6, 3)
        # First 3 points should have depth=10
        np.testing.assert_allclose(data[:3, 2], 10.0)
        # Last 3 points should have depth=20
        np.testing.assert_allclose(data[3:, 2], 20.0)

    def test_auto_detects_depth_attribute(self, tmp_path):
        """Finds depth under alternate attribute names like 'elev'."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0], [1, 1]],
                    },
                    "properties": {"ELEV": 5.5},
                },
            ],
        }
        path = tmp_path / "contours.geojson"
        path.write_text(json.dumps(geojson))
        data = load_bathymetry_contours(path, depth_attr="ELEV")
        assert data.shape == (2, 3)
        np.testing.assert_allclose(data[:, 2], 5.5)

    def test_resample_distance(self, tmp_path):
        """sample_distance adds points along long segments."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0], [100, 0]],
                    },
                    "properties": {"depth": 15.0},
                },
            ],
        }
        path = tmp_path / "sparse.geojson"
        path.write_text(json.dumps(geojson))
        # Without resampling: 2 vertices
        data_raw = load_bathymetry_contours(path)
        assert len(data_raw) == 2
        # With resampling at 10-unit intervals: ~11 points
        data_resampled = load_bathymetry_contours(path, sample_distance=10.0)
        assert len(data_resampled) > len(data_raw)

    def test_no_depth_attribute_raises(self, tmp_path):
        """Missing depth attribute raises ValueError."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 0], [1, 1]],
                    },
                    "properties": {"name": "contour_1"},
                },
            ],
        }
        path = tmp_path / "no_depth.geojson"
        path.write_text(json.dumps(geojson))
        with pytest.raises(ValueError, match="No numeric depth attribute"):
            load_bathymetry_contours(path)


# ---------------------------------------------------------------------------
# TestValidateBoundary
# ---------------------------------------------------------------------------


class TestValidateBoundary:
    """Tests for validate_boundary()."""

    def test_valid_closed_ring(self):
        """Valid square boundary produces no issues."""
        grd = _make_square_boundary()
        issues = validate_boundary(grd)
        errors = [i for i in issues if i.startswith("ERROR")]
        assert len(errors) == 0

    def test_open_ring_warning(self):
        """Open ring (not closed) produces warning."""
        grd = GrdFile()
        grd.nodes[1] = Node(id=1, node_type=0, x=0, y=0)
        grd.nodes[2] = Node(id=2, node_type=0, x=10, y=0)
        grd.nodes[3] = Node(id=3, node_type=0, x=10, y=10)
        grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3])  # not closed
        issues = validate_boundary(grd)
        assert any("not a closed ring" in i for i in issues)

    def test_no_boundaries_error(self):
        """Grid with no lines produces error."""
        grd = GrdFile()
        issues = validate_boundary(grd)
        assert any("No boundary" in i for i in issues)


# ---------------------------------------------------------------------------
# TestEstimateElementCount
# ---------------------------------------------------------------------------


class TestEstimateElementCount:
    """Tests for estimate_element_count()."""

    def test_square_domain(self):
        """10x10 square with area 5 → ~20 elements."""
        grd = _make_square_boundary()
        count = estimate_element_count(grd, max_area=5.0)
        assert 15 <= count <= 25

    def test_zero_area_returns_zero(self):
        """Zero max_area returns 0."""
        grd = _make_square_boundary()
        assert estimate_element_count(grd, max_area=0.0) == 0


# ---------------------------------------------------------------------------
# TestComputeMeshStats
# ---------------------------------------------------------------------------


class TestComputeMeshStats:
    """Tests for compute_mesh_stats()."""

    def test_mesh_with_elements(self):
        """Stats include quality, areas, angles for mesh with elements."""
        grd = _make_simple_mesh()
        stats = compute_mesh_stats(grd)
        assert stats["node_count"] == 4
        assert stats["elem_count"] == 2
        assert stats["quality"] is not None
        assert stats["areas"] is not None

    def test_empty_grid(self):
        """Empty grid returns zero counts, no quality stats."""
        grd = GrdFile()
        stats = compute_mesh_stats(grd)
        assert stats["node_count"] == 0
        assert stats["elem_count"] == 0
        assert "quality" not in stats

    def test_depth_stats(self):
        """Depth statistics computed when nodes have depth."""
        grd = _make_simple_mesh()
        stats = compute_mesh_stats(grd)
        assert "depth" in stats
        assert stats["depth"]["min"] == 1.0
        assert stats["depth"]["max"] == 4.0


# ---------------------------------------------------------------------------
# TestExportGrd
# ---------------------------------------------------------------------------


class TestExportGrd:
    """Tests for export_grd()."""

    def test_round_trip(self, tmp_path):
        """Save and reload produces equivalent grid."""
        grd = _make_simple_mesh()
        path = tmp_path / "output.grd"
        export_grd(grd, path)
        assert path.exists()
        loaded = GrdParser.parse_file(path)
        assert len(loaded.nodes) == len(grd.nodes)
        assert len(loaded.elements) == len(grd.elements)

    def test_creates_parent_dirs(self, tmp_path):
        """Creates parent directories if they don't exist."""
        path = tmp_path / "subdir" / "nested" / "output.grd"
        grd = _make_simple_mesh()
        export_grd(grd, path)
        assert path.exists()


# ---------------------------------------------------------------------------
# TestSetResolution
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TestMarMenorIntegration — end-to-end with real sample data
# ---------------------------------------------------------------------------

_MAR_MENOR_DIR = Path(__file__).resolve().parent.parent.parent / "testcases" / "examples" / "mar_menor"

_HAS_MAR_MENOR = (
    (_MAR_MENOR_DIR / "mar_menor_boundary.geojson").exists()
    and (_MAR_MENOR_DIR / "mar_menor_bathymetry.xyz").exists()
    and (_MAR_MENOR_DIR / "mar_menor_isobaths.geojson").exists()
)


@pytest.mark.skipif(not _HAS_MAR_MENOR, reason="Mar Menor sample data not found")
class TestMarMenorIntegration:
    """Full pipeline integration tests with real Mar Menor data."""

    def test_import_boundary(self):
        grd = import_boundaries(_MAR_MENOR_DIR / "mar_menor_boundary.geojson")
        assert grd.num_nodes > 100
        assert grd.num_lines >= 1
        issues = validate_boundary(grd)
        errors = [i for i in issues if i.startswith("ERROR")]
        assert len(errors) == 0

    def test_smooth_and_triangulate(self):
        """Chaikin-smoothed boundary triangulates without segfault."""
        grd = import_boundaries(_MAR_MENOR_DIR / "mar_menor_boundary.geojson")
        smoothed = smooth_boundary(grd, line_id=1, method="chaikin", iterations=1)
        mesh = triangulate(smoothed, max_area=100000.0, min_angle=20.0)
        assert mesh.num_elements > 100
        assert mesh.num_nodes > 100

    def test_reduce_and_triangulate(self):
        """Reduced boundary also triangulates cleanly."""
        grd = import_boundaries(_MAR_MENOR_DIR / "mar_menor_boundary.geojson")
        reduced = reduce_boundary(grd, line_id=1, tolerance=100.0)
        mesh = triangulate(reduced, max_area=200000.0, min_angle=20.0)
        assert mesh.num_elements > 10

    def test_interpolate_point_cloud(self):
        """All scipy methods produce valid depths from XYZ point cloud."""
        grd = import_boundaries(_MAR_MENOR_DIR / "mar_menor_boundary.geojson")
        mesh = triangulate(grd, max_area=200000.0, min_angle=20.0)
        bathy = load_bathymetry_file(_MAR_MENOR_DIR / "mar_menor_bathymetry.xyz")
        for method in ["linear", "nearest", "idw", "rbf", "cloughtocher"]:
            result = interpolate_bathymetry_scipy(mesh, bathy, method=method)
            depths = [n.depth for n in result.nodes.values()]
            assert all(d is not None for d in depths), f"{method} has None depths"
            assert not any(np.isnan(d) for d in depths), f"{method} has NaN depths"

    def test_interpolate_contours_with_boundary_zero(self):
        """RBF + boundary_zero on contour isobaths produces valid depths."""
        grd = import_boundaries(_MAR_MENOR_DIR / "mar_menor_boundary.geojson")
        mesh = triangulate(grd, max_area=200000.0, min_angle=20.0)
        contours = load_bathymetry_contours(_MAR_MENOR_DIR / "mar_menor_isobaths.geojson")
        result = interpolate_bathymetry_scipy(
            mesh, contours, method="rbf", use_boundary_zero=True
        )
        depths = [n.depth for n in result.nodes.values()]
        assert all(d is not None for d in depths)
        assert min(depths) >= -1.0  # boundary zero should keep near-shore close to 0

    def test_export_round_trip(self, tmp_path):
        """Full pipeline: import -> mesh -> bathy -> export -> reload."""
        grd = import_boundaries(_MAR_MENOR_DIR / "mar_menor_boundary.geojson")
        mesh = triangulate(grd, max_area=200000.0, min_angle=20.0)
        bathy = load_bathymetry_file(_MAR_MENOR_DIR / "mar_menor_bathymetry.xyz")
        result = interpolate_bathymetry_scipy(mesh, bathy, method="linear", use_boundary_zero=True)
        out = tmp_path / "test_output.grd"
        export_grd(result, out)
        reloaded = GrdParser.parse_file(out)
        assert len(reloaded.nodes) == len(result.nodes)
        assert len(reloaded.elements) == len(result.elements)


class TestSetResolution:
    """Tests for set_resolution()."""

    def test_global_area_only(self):
        """Global area constraint returned correctly."""
        grd = _make_square_boundary()
        result = set_resolution(grd, global_area=5.0)
        assert result["max_area"] == 5.0
        assert result["regions"] == []

    def test_with_refinement_zones(self):
        """Refinement zones produce region entries."""
        grd = _make_square_boundary()
        zones = [
            {"polygon": [(2, 2), (4, 2), (4, 4), (2, 4)], "max_area": 1.0},
        ]
        result = set_resolution(grd, global_area=10.0, refinement_zones=zones)
        assert len(result["regions"]) == 1
        assert result["regions"][0][3] == 1.0  # max_area


# ---------------------------------------------------------------------------
# TestCuronianIntegration — end-to-end with real Curonian Lagoon data
# ---------------------------------------------------------------------------

_CURONIAN_DIR = Path(__file__).resolve().parent.parent.parent / "testcases" / "examples" / "curoninan"

_HAS_CURONIAN = (
    (_CURONIAN_DIR / "curonian_boundary.gpkg").exists()
    and (_CURONIAN_DIR / "depth_isobates.gpkg").exists()
)


@pytest.mark.skipif(not _HAS_CURONIAN, reason="Curonian lagoon sample data not found")
class TestCuronianIntegration:
    """Full pipeline integration tests with real Curonian Lagoon GPKG data.

    The Curonian data is more complex than Mar Menor: MultiPolygon boundary
    with 21 interior holes (islands), 5136-point coastline, and 435 isobath
    contours with 251k points spanning depths 0–95m.
    """

    def test_import_boundary(self):
        """Import GPKG MultiPolygon with exterior + interior rings."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        assert grd.num_nodes > 5000
        assert grd.num_lines >= 20  # outer rings + holes
        # Check we have both exterior (type 1) and hole (type 2) lines
        types = {l.line_type for l in grd.lines.values()}
        assert 1 in types, "Should have exterior boundaries"
        assert 2 in types, "Should have interior holes (islands)"
        issues = validate_boundary(grd)
        errors = [i for i in issues if i.startswith("ERROR")]
        assert len(errors) == 0

    def test_reduce_all_lines(self):
        """Douglas-Peucker reduction works across all 31 lines."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        original_nodes = grd.num_nodes
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=500.0)
        assert grd.num_nodes < original_nodes / 10  # significant reduction
        # Main coastline should still have meaningful detail
        main_line = max(grd.lines.values(), key=lambda l: len(l.nodes))
        assert len(main_line.nodes) > 50

    def test_reduce_and_triangulate(self):
        """Reduced boundary with holes triangulates cleanly."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=500.0)
        mesh = triangulate(grd, max_area=1000000.0, min_angle=20.0)
        assert mesh.num_elements > 100
        assert mesh.num_nodes > 100
        stats = compute_mesh_stats(mesh)
        assert stats["quality"]["mean"] > 0.3

    def test_all_triangulation_methods(self):
        """Quality, conforming, and minimal triangulation all succeed."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=500.0)

        # Quality: area + angle constraints → most elements
        quality = triangulate(grd, max_area=1000000.0, min_angle=20.0)
        assert quality.num_elements > 1000
        assert quality.num_nodes > 500

        # Conforming: angle constraint only, no area limit → fewer elements
        conforming = triangulate(grd, max_area=None, min_angle=20.0)
        assert conforming.num_elements > 100
        assert conforming.num_elements < quality.num_elements

        # Minimal: no constraints → fewest triangles
        minimal = triangulate(grd, max_area=None, min_angle=0.0)
        assert minimal.num_elements > 10
        assert minimal.num_elements <= conforming.num_elements

    def test_smooth_main_coastline_and_triangulate(self):
        """Chaikin-smoothed main coastline triangulates without segfault."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        # Reduce first (5136 pts too many for smoothing)
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=500.0)
        # Find the main coastline (largest line)
        main_lid = max(grd.lines, key=lambda lid: len(grd.lines[lid].nodes))
        smoothed = smooth_boundary(grd, line_id=main_lid, method="chaikin", iterations=1)
        mesh = triangulate(smoothed, max_area=1000000.0, min_angle=20.0)
        assert mesh.num_elements > 100

    def test_load_isobath_contours(self):
        """Load 435 isobath contours from GPKG with depth attribute."""
        data = load_bathymetry_contours(_CURONIAN_DIR / "depth_isobates.gpkg")
        assert data.shape[1] == 3  # x, y, depth
        assert len(data) > 100_000  # ~251k points
        assert data[:, 2].min() == pytest.approx(0.0)
        assert data[:, 2].max() >= 90.0  # up to 95m

    def test_interpolate_isobaths_all_methods(self):
        """All scipy methods produce valid depths from Curonian isobaths."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=500.0)
        mesh = triangulate(grd, max_area=1000000.0, min_angle=20.0)
        data = load_bathymetry_contours(_CURONIAN_DIR / "depth_isobates.gpkg")
        # Subsample for speed (251k points is too many for test)
        sub = data[::10]
        for method in ["linear", "nearest", "idw", "rbf", "cloughtocher"]:
            result = interpolate_bathymetry_scipy(
                mesh, sub, method=method, use_boundary_zero=True
            )
            depths = [n.depth for n in result.nodes.values()]
            assert all(d is not None for d in depths), f"{method} has None depths"
            assert not any(np.isnan(d) for d in depths), f"{method} has NaN depths"

    def test_export_round_trip(self, tmp_path):
        """Full pipeline: import -> reduce -> mesh -> bathy -> export -> reload."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=500.0)
        mesh = triangulate(grd, max_area=1000000.0, min_angle=20.0)
        data = load_bathymetry_contours(_CURONIAN_DIR / "depth_isobates.gpkg")
        sub = data[::20]
        result = interpolate_bathymetry_scipy(
            mesh, sub, method="linear", use_boundary_zero=True
        )
        out = tmp_path / "curonian_output.grd"
        export_grd(result, out)
        reloaded = GrdParser.parse_file(out)
        assert len(reloaded.nodes) == len(result.nodes)
        assert len(reloaded.elements) == len(result.elements)
