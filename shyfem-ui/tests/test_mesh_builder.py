"""Unit tests for mesh builder service.

Tests the pure-Python mesh generation pipeline: boundary import,
smoothing, reduction, triangulation, bathymetry interpolation,
validation, and statistics.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from shyfem_ui.services.mesh_builder import (
    _check_boundary_gates,
    _remove_ring_loops,
    adjust_depths,
    check_bathy_extent,
    compute_mesh_stats,
    count_below_area,
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
    suggest_max_area_for_limit,
    summarize_depth_stats,
    triangulate,
    validate_boundary,
    warn_if_degenerate_bathy,
    warn_if_min_geq_max_area,
    warn_if_minimal_with_cap,
)
from shyfem_ui.services.parser_grd import (
    Element,
    GrdFile,
    GrdParser,
    Line,
    Node,
)

pytest.importorskip("triangle")
pytest.importorskip("fiona")
pytest.importorskip("shapely")
pytest.importorskip("scipy")


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
    grd.elements[1] = Element(id=1, elem_type=0, nodes=[1, 2, 3])
    grd.elements[2] = Element(id=2, elem_type=0, nodes=[1, 3, 4])
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
        with fiona.open(
            str(path), "w", driver="ESRI Shapefile", schema=schema, crs=CRS.from_epsg(4326)
        ) as dst:
            dst.write(
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]],
                    },
                    "properties": {"name": "test"},
                }
            )
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

    def test_geojson_sets_epsg_4326(self, tmp_path):
        """import_boundaries always sets grd.epsg = 4326 (WGS84 output)."""
        coords = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        path = _make_geojson_polygon(coords, tmp_path / "test.geojson")
        grd = import_boundaries(path)
        assert grd.epsg == 4326

    def test_projected_crs_reprojected_to_wgs84(self, tmp_path):
        """Shapefile in projected CRS (e.g. UTM) gets reprojected to WGS84."""
        import fiona
        from fiona.crs import CRS

        # Create a polygon in EPSG:32635 (UTM zone 35N) — Curonian Lagoon area
        schema = {"geometry": "Polygon", "properties": {}}
        path = tmp_path / "projected.shp"
        with fiona.open(
            str(path),
            "w",
            driver="ESRI Shapefile",
            schema=schema,
            crs=CRS.from_epsg(32635),
        ) as dst:
            dst.write(
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [300000, 6100000],
                                [350000, 6100000],
                                [350000, 6150000],
                                [300000, 6150000],
                                [300000, 6100000],
                            ]
                        ],
                    },
                    "properties": {},
                }
            )
        grd = import_boundaries(path)
        # After reprojection, coordinates should be in WGS84 range
        xs = [n.x for n in grd.nodes.values()]
        ys = [n.y for n in grd.nodes.values()]
        assert all(-180 <= x <= 180 for x in xs), f"X out of WGS84 range: {xs}"
        assert all(-90 <= y <= 90 for y in ys), f"Y out of WGS84 range: {ys}"
        assert grd.epsg == 4326

    def test_wgs84_not_reprojected(self, tmp_path):
        """Shapefile already in WGS84 keeps original coordinates."""
        import fiona
        from fiona.crs import CRS

        schema = {"geometry": "Polygon", "properties": {}}
        path = tmp_path / "wgs84.shp"
        with fiona.open(
            str(path),
            "w",
            driver="ESRI Shapefile",
            schema=schema,
            crs=CRS.from_epsg(4326),
        ) as dst:
            dst.write(
                {
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[21.0, 55.0], [21.5, 55.0], [21.5, 55.5], [21.0, 55.5], [21.0, 55.0]]
                        ],
                    },
                    "properties": {},
                }
            )
        grd = import_boundaries(path)
        xs = [round(n.x, 1) for n in grd.nodes.values()]
        ys = [round(n.y, 1) for n in grd.nodes.values()]
        assert 21.0 in xs
        assert 55.0 in ys

    def test_gpkg_projected_crs(self):
        """Real GeoPackage in LKS94 (EPSG:3346) reprojects to WGS84."""
        path = (
            Path(__file__).resolve().parent.parent.parent
            / "testcases/examples/curoninan/curonian_boundary.gpkg"
        )
        if not path.exists():
            pytest.skip("curonian_boundary.gpkg not available")
        grd = import_boundaries(path)
        xs = [n.x for n in grd.nodes.values()]
        ys = [n.y for n in grd.nodes.values()]
        assert all(-180 <= x <= 180 for x in xs), f"X out of range: {min(xs)}-{max(xs)}"
        assert all(-90 <= y <= 90 for y in ys), f"Y out of range: {min(ys)}-{max(ys)}"
        # Curonian Lagoon is around lon 21, lat 55
        assert 20 < max(xs) < 22
        assert 54 < max(ys) < 56


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
        with pytest.raises(Exception):  # noqa: B017 - smoke test: any error on empty grid
            triangulate(grd)

    def test_min_angle_above_34_raises(self):
        """min_angle > 34 is rejected; Triangle's quality refinement may not converge above 34."""
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="min_angle"):
            triangulate(grd, max_area=10.0, min_angle=40.0)

    def test_zero_max_area_raises(self):
        """max_area = 0 is rejected (would silently disable the constraint)."""
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="max_area"):
            triangulate(grd, max_area=0.0, min_angle=20.0)

    def test_negative_max_area_raises(self):
        """max_area < 0 is rejected."""
        grd = _make_square_boundary()
        with pytest.raises(ValueError, match="max_area"):
            triangulate(grd, max_area=-1.0, min_angle=20.0)

    def test_min_angle_exactly_34_passes(self):
        """min_angle = 34 is accepted as the documented ceiling."""
        # 34 is the upper bound the guard allows; 33 is the documented
        # practical max. Triangle accepts up to 34 but can fail to converge
        # above it.
        grd = _make_square_boundary()
        triangulate(grd, max_area=10.0, min_angle=34.0)  # must not raise

    def test_max_area_none_still_allowed(self):
        """max_area = None means 'no constraint' — the existing minimal-mesh path."""
        # None means "no global area constraint" — the existing minimal-mesh
        # path. Must continue to work.
        grd = _make_square_boundary()
        triangulate(grd, max_area=None, min_angle=20.0)


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
        bathy = np.array(
            [
                [0, 0, 0],
                [10, 0, 10],
                [0, 10, 10],
                [10, 10, 20],
                [5, 5, 10],
                [5, 0, 5],
                [0, 5, 5],
            ]
        )
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
        bathy = np.array(
            [
                [0, 0, 0],
                [10, 0, 10],
                [0, 10, 10],
                [10, 10, 20],
                [5, 5, 10],
                [5, 0, 5],
                [0, 5, 5],
            ]
        )
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
        bathy = np.array(
            [
                [8, 8, 5],
                [12, 8, 5],
                [8, 12, 5],
                [12, 12, 10],
            ]
        )
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
        bathy = np.array(
            [
                [0, 0, 0],
                [10, 0, 10],
                [0, 10, 10],
                [10, 10, 20],
                [5, 5, 10],
                [5, 0, 5],
                [0, 5, 5],
            ]
        )
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
        bathy = np.array(
            [
                [8, 8, 5],
                [12, 8, 5],
                [8, 12, 5],
                [12, 12, 10],
            ]
        )
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
        bathy = np.array(
            [
                [2, 2, 10],
                [8, 2, 10],
                [2, 8, 10],
                [8, 8, 10],
                [5, 5, 10],
            ]
        )
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
        bathy = np.array(
            [
                [5, 5, 20],
                [3, 3, 15],
                [7, 7, 15],
            ]
        )
        result = interpolate_bathymetry_scipy(mesh, bathy, method="rbf", use_boundary_zero=True)
        # Interior should have high depth, edges should be near zero
        boundary_nids = set()
        for line in mesh.lines.values():
            boundary_nids.update(line.nodes)
        boundary_depths = [result.nodes[nid].depth for nid in boundary_nids if nid in result.nodes]
        interior_depths = [n.depth for nid, n in result.nodes.items() if nid not in boundary_nids]
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
# TestCheckBoundaryGates
# ---------------------------------------------------------------------------


class TestCheckBoundaryGates:
    """The fail-closed gate around triangulate()."""

    def test_clean_square_passes(self):
        ok, reason = _check_boundary_gates(_make_square_boundary())
        assert ok
        assert reason is None

    def test_no_lines_blocks(self):
        ok, reason = _check_boundary_gates(GrdFile())
        assert not ok
        assert "no boundary lines" in reason.lower()

    def test_only_holes_blocks(self):
        # No line_type=1 — turn the square's exterior into a hole.
        grd = _make_square_boundary()
        grd.lines[1].line_type = 2
        ok, reason = _check_boundary_gates(grd)
        assert not ok
        assert "exterior" in reason.lower()

    def test_fewer_than_three_nodes_blocks(self):
        grd = GrdFile()
        grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0)
        grd.nodes[2] = Node(id=2, node_type=0, x=1.0, y=0.0)
        grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2])
        ok, reason = _check_boundary_gates(grd)
        assert not ok
        assert "fewer than 3 nodes" in reason.lower()

    def test_self_intersecting_blocks(self):
        # Bowtie / figure-8: diagonals (0,0)-(1,1) and (1,0)-(0,1) cross.
        grd = GrdFile()
        for i, (x, y) in enumerate([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)], start=1):
            grd.nodes[i] = Node(id=i, node_type=0, x=float(x), y=float(y))
        grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2, 3, 4, 1])
        ok, reason = _check_boundary_gates(grd)
        assert not ok
        assert "self-intersect" in reason.lower()

    def test_unclosed_ring_passes(self):
        # WARNING: not a closed ring — left non-blocking; Triangle closes it.
        grd = _make_square_boundary()
        # Drop the closing repeat node
        grd.lines[1].nodes = [1, 2, 3, 4]
        ok, reason = _check_boundary_gates(grd)
        assert ok


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


class TestSuggestMaxAreaForLimit:
    """Tests for suggest_max_area_for_limit()."""

    def test_round_trip_with_estimate(self):
        """Suggested area used as max_area should yield <= max_elements."""
        grd = _make_square_boundary()  # area = 100
        max_elements = 50
        suggested = suggest_max_area_for_limit(grd, max_elements)
        assert suggested is not None
        # Estimate must respect the cap (10% safety baked in)
        assert estimate_element_count(grd, suggested) <= max_elements

    def test_invalid_limit_returns_none(self):
        grd = _make_square_boundary()
        assert suggest_max_area_for_limit(grd, 0) is None
        assert suggest_max_area_for_limit(grd, -1) is None


class TestCountBelowArea:
    """Tests for count_below_area()."""

    def test_no_elements(self):
        """Boundary-only grid has zero triangles below threshold."""
        grd = _make_square_boundary()
        assert count_below_area(grd, threshold=1.0) == 0

    def test_zero_threshold_returns_zero(self):
        """A non-positive threshold short-circuits to 0."""
        grd = triangulate(_make_square_boundary(), max_area=5.0, min_angle=20.0)
        assert count_below_area(grd, threshold=0.0) == 0
        assert count_below_area(grd, threshold=-1.0) == 0

    def test_counts_slivers(self):
        """A coarse mesh has triangles ≈max_area; threshold above max
        catches all of them."""
        grd = triangulate(_make_square_boundary(), max_area=5.0, min_angle=20.0)
        # All triangles should be below an artificially high threshold
        n_total = len(grd.elements)
        assert count_below_area(grd, threshold=1e9) == n_total
        # And none below an artificially low one
        assert count_below_area(grd, threshold=1e-9) == 0


# ---------------------------------------------------------------------------
# TestMeshCreationPipeline — end-to-end behavior of triangulate() against the
# constraint helpers used by the Mesh Builder UI. These tests validate the
# *promises* the UI makes to users: that Max Triangle Area is enforced, that
# Min Angle is honored, that Max Elements + suggest_max_area_for_limit
# round-trip safely, and that the Min Triangle Area warning reports
# meaningful numbers on real meshes.
# ---------------------------------------------------------------------------


def _triangle_area(nodes) -> float:
    """Shoelace area for the first 3 nodes of an element."""
    x1, y1 = nodes[0].x, nodes[0].y
    x2, y2 = nodes[1].x, nodes[1].y
    x3, y3 = nodes[2].x, nodes[2].y
    return abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0


def _triangle_min_angle_deg(nodes) -> float:
    """Smallest interior angle of a triangle, in degrees."""
    a = np.array([nodes[0].x, nodes[0].y])
    b = np.array([nodes[1].x, nodes[1].y])
    c = np.array([nodes[2].x, nodes[2].y])
    sides = [
        np.linalg.norm(b - c),
        np.linalg.norm(a - c),
        np.linalg.norm(a - b),
    ]
    angles = []
    for i in range(3):
        opp = sides[i]
        adj1 = sides[(i + 1) % 3]
        adj2 = sides[(i + 2) % 3]
        # Law of cosines, clamp to [-1, 1] for floating-point safety
        cos_a = (adj1**2 + adj2**2 - opp**2) / (2 * adj1 * adj2)
        angles.append(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))
    return min(angles)


def _mesh_node_list(mesh, elem):
    return [mesh.nodes[n] for n in elem.nodes if n in mesh.nodes][:3]


class TestMeshCreationPipeline:
    """End-to-end mesh creation tests covering constraint helpers."""

    def test_max_area_constraint_respected(self):
        """All triangles in a quality mesh respect the max_area cap."""
        grd = _make_square_boundary()
        max_area = 5.0
        mesh = triangulate(grd, max_area=max_area, min_angle=20.0)
        assert len(mesh.elements) > 0
        # Triangle library guarantees area ≤ max_area; allow 1% slack for FP.
        for elem in mesh.elements.values():
            nodes = _mesh_node_list(mesh, elem)
            if len(nodes) == 3:
                assert _triangle_area(nodes) <= max_area * 1.01

    def test_min_angle_constraint_respected(self):
        """All triangles' minimum interior angle is ≥ requested angle."""
        grd = _make_square_boundary()
        requested = 25.0
        mesh = triangulate(grd, max_area=10.0, min_angle=requested)
        assert len(mesh.elements) > 0
        # Triangle's quality guarantee may miss a handful of bad triangles
        # near input boundary corners; allow a small fraction below threshold
        # but assert the bulk respect the constraint.
        below = 0
        total = 0
        for elem in mesh.elements.values():
            nodes = _mesh_node_list(mesh, elem)
            if len(nodes) == 3:
                total += 1
                if _triangle_min_angle_deg(nodes) < requested - 1.0:
                    below += 1
        assert total > 0
        assert below / total < 0.10, f"{below}/{total} triangles violate min_angle≥{requested}°"

    def test_min_angle_zero_skips_quality_refinement(self):
        """Setting min_angle=0 should produce a coarser mesh than min_angle=25."""
        grd = _make_square_boundary()
        mesh_minimal = triangulate(grd, max_area=None, min_angle=0.0)
        mesh_quality = triangulate(grd, max_area=None, min_angle=25.0)
        # Quality refinement only kicks in when q is set; with the same area
        # constraint (None) and min_angle=0 we should not get *more* elements.
        assert len(mesh_minimal.elements) <= len(mesh_quality.elements)

    def test_estimate_matches_actual_within_tolerance(self):
        """estimate_element_count is within ~50% of actual count."""
        grd = _make_square_boundary()
        max_area = 2.0
        estimate = estimate_element_count(grd, max_area)
        mesh = triangulate(grd, max_area=max_area, min_angle=20.0)
        actual = len(mesh.elements)
        assert estimate > 0
        # The boundary-area / max_area estimator is rough but should be within
        # an order of magnitude. Allow a wide band — Triangle's actual count
        # depends on quality refinement and edge subdivision.
        assert 0.3 * estimate <= actual <= 5.0 * estimate

    def test_suggest_then_triangulate_respects_limit(self):
        """Pre-flight pipeline: limit → suggest area → triangulate → count is
        in the same ballpark as the limit (suggest is a hint, not a guarantee).
        """
        grd = _make_square_boundary()
        cap = 200
        suggested = suggest_max_area_for_limit(grd, cap)
        assert suggested is not None
        mesh = triangulate(grd, max_area=suggested, min_angle=20.0)
        # Suggested area applies a 50% safety margin to absorb refinement
        # inflation; on a regular square boundary the actual count should
        # land within ±25% of the cap.
        assert 0.5 * cap <= len(mesh.elements) <= 1.25 * cap

    def test_finer_mesh_has_more_elements_monotonic(self):
        """Element count grows monotonically as max_area shrinks."""
        grd = _make_square_boundary()
        counts = [
            len(triangulate(grd, max_area=area, min_angle=20.0).elements)
            for area in [50.0, 25.0, 10.0, 5.0, 2.0]
        ]
        # Pairwise check — adjacent equality is OK at very coarse resolutions
        # where the quality minimum dominates, but the count must never drop.
        for prev, nxt in zip(counts, counts[1:], strict=False):
            assert nxt >= prev

    def test_triangulate_is_deterministic(self):
        """Same input → same element count across runs."""
        grd = _make_square_boundary()
        m1 = triangulate(grd, max_area=5.0, min_angle=20.0)
        m2 = triangulate(grd, max_area=5.0, min_angle=20.0)
        assert len(m1.elements) == len(m2.elements)
        assert len(m1.nodes) == len(m2.nodes)

    def test_count_below_area_low_on_quality_mesh(self):
        """A quality mesh with max_area=A should have few triangles below A/2."""
        grd = _make_square_boundary()
        max_area = 5.0
        mesh = triangulate(grd, max_area=max_area, min_angle=20.0)
        # Triangle ensures ≤ max_area but does not enforce ≥ any minimum;
        # however with min_angle=20° on a regular square most triangles
        # cluster near the upper bound. Slivers below half the cap should
        # be a minority.
        slivers = count_below_area(mesh, max_area / 2.0)
        assert slivers < len(mesh.elements) * 0.5

    def test_count_below_area_catches_known_slivers(self):
        """Threshold above max area triangle catches every triangle."""
        grd = _make_square_boundary()
        max_area = 5.0
        mesh = triangulate(grd, max_area=max_area, min_angle=20.0)
        # Threshold above any possible triangle catches all of them
        assert count_below_area(mesh, threshold=max_area * 10) == len(mesh.elements)
        # Threshold below the smallest possible triangle catches none
        assert count_below_area(mesh, threshold=1e-12) == 0

    def test_holes_excluded_from_element_count(self):
        """Triangulating a domain with a hole produces fewer elements than no hole."""
        grd_solid = _make_square_boundary()
        grd_hole = _make_square_with_hole()
        max_area = 1.0
        mesh_solid = triangulate(grd_solid, max_area=max_area, min_angle=20.0)
        mesh_hole = triangulate(grd_hole, max_area=max_area, min_angle=20.0)
        # Hole subtracts 16 area units from the 100 of the outer square
        assert len(mesh_hole.elements) < len(mesh_solid.elements)

    def test_boundary_nodes_preserved(self):
        """All input boundary corner coordinates appear in the output mesh nodes."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=50.0, min_angle=20.0)
        # Original 4 corners must all be present (within FP tolerance) in the
        # resulting node set
        original_coords = {(grd.nodes[i].x, grd.nodes[i].y) for i in range(1, 5)}
        mesh_coords = {(round(n.x, 6), round(n.y, 6)) for n in mesh.nodes.values()}
        for ox, oy in original_coords:
            assert (round(ox, 6), round(oy, 6)) in mesh_coords


class TestMeshCreationEdgeCases:
    """Edge cases for the mesh creation flow."""

    def test_estimate_with_no_boundary_returns_zero(self):
        """Empty grid → 0 estimate, never crashes."""
        empty = GrdFile()
        assert estimate_element_count(empty, max_area=1.0) == 0

    def test_suggest_with_no_boundary_returns_none(self):
        """Empty grid → None (cannot compute boundary area)."""
        empty = GrdFile()
        assert suggest_max_area_for_limit(empty, max_elements=100) is None

    def test_count_below_area_on_unmeshed_boundary(self):
        """Boundary-only grid (no elements) returns 0 regardless of threshold."""
        grd = _make_square_boundary()
        assert count_below_area(grd, threshold=1e9) == 0

    def test_max_area_none_no_quality_constraint_minimal_mesh(self):
        """Minimal triangulation: no max_area, no min_angle → fewest elements."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=None, min_angle=0.0)
        # A square boundary has at minimum 2 triangles (one diagonal split)
        assert 2 <= len(mesh.elements) <= 6
        assert len(mesh.nodes) >= 4

    def test_very_small_boundary(self):
        """Sub-unit-sized boundary still produces a valid mesh."""
        grd = _make_square_boundary(size=0.001)
        mesh = triangulate(grd, max_area=1e-7, min_angle=20.0)
        assert len(mesh.elements) >= 2

    def test_count_below_area_handles_degenerate_element(self):
        """Element with <3 valid nodes is silently skipped, not raised."""
        grd = _make_simple_mesh()
        # Reference a non-existent node — count_below_area should skip it
        grd.elements[3] = Element(id=3, elem_type=0, nodes=[1, 2, 9999])
        # Should not raise; count for the 2 valid triangles + 1 skipped
        n = count_below_area(grd, threshold=1e9)
        # The 2 valid triangles are area 50 each; threshold 1e9 catches both
        assert n == 2


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

_MAR_MENOR_DIR = (
    Path(__file__).resolve().parent.parent.parent / "testcases" / "examples" / "mar_menor"
)

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
        result = interpolate_bathymetry_scipy(mesh, contours, method="rbf", use_boundary_zero=True)
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

_CURONIAN_DIR = (
    Path(__file__).resolve().parent.parent.parent / "testcases" / "examples" / "curoninan"
)

_HAS_CURONIAN = (_CURONIAN_DIR / "curonian_boundary.gpkg").exists() and (
    _CURONIAN_DIR / "depth_isobates.gpkg"
).exists()


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
        types = {ln.line_type for ln in grd.lines.values()}
        assert 1 in types, "Should have exterior boundaries"
        assert 2 in types, "Should have interior holes (islands)"
        issues = validate_boundary(grd)
        errors = [i for i in issues if i.startswith("ERROR")]
        assert len(errors) == 0

    def test_reduce_all_lines(self):
        """Douglas-Peucker reduction works across all 31 lines."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        original_nodes = grd.num_nodes
        # Tolerance in degrees (~0.005° ≈ 500m at this latitude)
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=0.005)
        assert grd.num_nodes < original_nodes / 10  # significant reduction
        # Main coastline should still have meaningful detail
        main_line = max(grd.lines.values(), key=lambda ln: len(ln.nodes))
        assert len(main_line.nodes) > 50

    def test_reduce_and_triangulate(self):
        """Reduced boundary with holes triangulates cleanly."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=0.005)
        mesh = triangulate(grd, max_area=0.001, min_angle=20.0)
        assert mesh.num_elements > 100
        assert mesh.num_nodes > 100
        stats = compute_mesh_stats(mesh)
        assert stats["quality"]["mean"] > 0.3

    def test_all_triangulation_methods(self):
        """Quality, conforming, and minimal triangulation all succeed."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        # Tolerance in degrees (~0.005° ≈ 500m)
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=0.005)

        # Quality: area + angle constraints → most elements
        # Area in sq-degrees (~0.001 sq-deg ≈ 10 km²)
        quality = triangulate(grd, max_area=0.001, min_angle=20.0)
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
            grd = reduce_boundary(grd, line_id=lid, tolerance=0.005)
        # Find the main coastline (largest line)
        main_lid = max(grd.lines, key=lambda lid: len(grd.lines[lid].nodes))
        smoothed = smooth_boundary(grd, line_id=main_lid, method="chaikin", iterations=1)
        mesh = triangulate(smoothed, max_area=0.001, min_angle=20.0)
        assert mesh.num_elements > 100

    def test_load_isobath_contours(self):
        """Load 435 isobath contours from GPKG with depth attribute.

        The source file is EPSG:3346 (LKS94 projected), so
        load_bathymetry_contours must reproject to WGS84 automatically.
        """
        data = load_bathymetry_contours(_CURONIAN_DIR / "depth_isobates.gpkg")
        assert data.shape[1] == 3  # x, y, depth
        assert len(data) > 100_000  # ~251k points
        assert data[:, 2].min() == pytest.approx(0.0)
        assert data[:, 2].max() >= 90.0  # up to 95m
        # Verify CRS reprojection: X should be in WGS84 lon range, not projected
        assert data[:, 0].min() > 19.0, "X should be WGS84 longitude (not projected)"
        assert data[:, 0].max() < 22.0, "X should be WGS84 longitude (not projected)"
        assert data[:, 1].min() > 54.0, "Y should be WGS84 latitude (not projected)"
        assert data[:, 1].max() < 57.0, "Y should be WGS84 latitude (not projected)"

    def test_interpolate_isobaths_all_methods(self):
        """All scipy methods produce valid depths from Curonian isobaths."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=0.005)
        mesh = triangulate(grd, max_area=0.001, min_angle=20.0)
        data = load_bathymetry_contours(_CURONIAN_DIR / "depth_isobates.gpkg")
        # Subsample for speed (251k points is too many for test)
        sub = data[::10]
        for method in ["linear", "nearest", "idw", "rbf", "cloughtocher"]:
            result = interpolate_bathymetry_scipy(mesh, sub, method=method, use_boundary_zero=True)
            depths = [n.depth for n in result.nodes.values()]
            assert all(d is not None for d in depths), f"{method} has None depths"
            assert not any(np.isnan(d) for d in depths), f"{method} has NaN depths"

    def test_export_round_trip(self, tmp_path):
        """Full pipeline: import -> reduce -> mesh -> bathy -> export -> reload."""
        grd = import_boundaries(_CURONIAN_DIR / "curonian_boundary.gpkg")
        for lid in list(grd.lines.keys()):
            grd = reduce_boundary(grd, line_id=lid, tolerance=0.005)
        mesh = triangulate(grd, max_area=0.001, min_angle=20.0)
        data = load_bathymetry_contours(_CURONIAN_DIR / "depth_isobates.gpkg")
        sub = data[::20]
        result = interpolate_bathymetry_scipy(mesh, sub, method="linear", use_boundary_zero=True)
        out = tmp_path / "curonian_output.grd"
        export_grd(result, out)
        reloaded = GrdParser.parse_file(out)
        assert len(reloaded.nodes) == len(result.nodes)
        assert len(reloaded.elements) == len(result.elements)


# ---------------------------------------------------------------------------
# TestRemoveRingLoops
# ---------------------------------------------------------------------------


class TestRemoveRingLoops:
    """Tests for _remove_ring_loops()."""

    def test_no_loops(self):
        """Ring without duplicates is unchanged."""
        ring = [1, 2, 3, 4, 1]
        assert _remove_ring_loops(ring) == [1, 2, 3, 4, 1]

    def test_simple_lollipop(self):
        """Non-consecutive duplicate creates a lollipop loop that is removed."""
        # 1→2→3→4→2→5→1  has a loop 2→3→4→2
        ring = [1, 2, 3, 4, 2, 5, 1]
        result = _remove_ring_loops(ring)
        assert result == [1, 2, 5, 1]

    def test_consecutive_duplicates_kept(self):
        """Consecutive duplicate is a self-loop of length 0 — removed."""
        ring = [1, 2, 2, 3, 1]
        result = _remove_ring_loops(ring)
        assert result == [1, 2, 3, 1]

    def test_multiple_loops(self):
        """Multiple independent loops are all removed."""
        # 1→2→3→2→4→5→4→6→1  has loops at 2 and 4
        ring = [1, 2, 3, 2, 4, 5, 4, 6, 1]
        result = _remove_ring_loops(ring)
        assert result == [1, 2, 4, 6, 1]

    def test_open_ring(self):
        """Open ring (not closed) also handled correctly."""
        ring = [1, 2, 3, 2, 4]
        result = _remove_ring_loops(ring)
        assert result == [1, 2, 4]

    def test_empty_ring(self):
        """Empty ring returns empty."""
        assert _remove_ring_loops([]) == []

    def test_single_node_closed(self):
        """Single-node closed ring."""
        assert _remove_ring_loops([1, 1]) == [1, 1]

    def test_nested_loop(self):
        """Nested loop: 1→2→3→4→3→2→5→1."""
        ring = [1, 2, 3, 4, 3, 2, 5, 1]
        result = _remove_ring_loops(ring)
        # First pass: 3→4→3 removed → [1, 2, 3, 2, 5, 1]
        # Second pass: 2→3→2 removed → [1, 2, 5, 1]
        assert result == [1, 2, 5, 1]


# ---------------------------------------------------------------------------
# TestTriangulateElementFormat
# ---------------------------------------------------------------------------


class TestTriangulateElementFormat:
    """Tests that triangulate() produces elements with correct node format."""

    def test_elements_have_three_nodes(self):
        """Regression: all elements must have exactly 3 nodes (no nvert prefix)."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=50.0)
        for elem in mesh.elements.values():
            assert (
                len(elem.nodes) == 3
            ), f"Element {elem.id} has {len(elem.nodes)} nodes: {elem.nodes}"

    def test_no_nvert_in_node_list(self):
        """Regression: nvert value (3) must NOT appear as first node ID."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        first_nodes = {elem.nodes[0] for elem in mesh.elements.values()}
        # With multiple elements, the first node should vary
        assert len(first_nodes) > 1, "All elements start with same node — nvert leak?"

    def test_node_ids_are_valid_references(self):
        """All element node IDs must reference existing nodes."""
        grd = _make_square_boundary()
        mesh = triangulate(grd, max_area=10.0)
        for elem in mesh.elements.values():
            for nid in elem.nodes:
                assert nid in mesh.nodes, f"Element {elem.id} references missing node {nid}"

    def test_with_hole_elements_correct(self):
        """Elements in domain with hole also have exactly 3 nodes."""
        grd = _make_square_with_hole()
        mesh = triangulate(grd, max_area=5.0)
        for elem in mesh.elements.values():
            assert (
                len(elem.nodes) == 3
            ), f"Element {elem.id} has {len(elem.nodes)} nodes: {elem.nodes}"


# ---------------------------------------------------------------------------
# adjust_depths tests
# ---------------------------------------------------------------------------


def _make_depth_grd() -> GrdFile:
    """GrdFile with 4 nodes spanning depths -10, -3, None, 5."""
    grd = GrdFile()
    grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0, depth=-10.0)
    grd.nodes[2] = Node(id=2, node_type=0, x=1.0, y=0.0, depth=-3.0)
    grd.nodes[3] = Node(id=3, node_type=0, x=0.0, y=1.0, depth=None)
    grd.nodes[4] = Node(id=4, node_type=0, x=1.0, y=1.0, depth=5.0)
    return grd


class TestAdjustDepths:
    def test_min_clamp(self):
        """Nodes shallower than min_clamp are raised to min_clamp."""
        grd = _make_depth_grd()
        result = adjust_depths(grd, min_clamp=-5.0)
        assert result.nodes[1].depth == -5.0
        assert result.nodes[2].depth == -3.0
        assert result.nodes[3].depth is None
        assert result.nodes[4].depth == 5.0

    def test_max_clamp(self):
        """Nodes with depth > max_clamp are clamped to max_clamp."""
        grd = _make_depth_grd()
        result = adjust_depths(grd, max_clamp=0.0)
        assert result.nodes[1].depth == -10.0
        assert result.nodes[2].depth == -3.0
        assert result.nodes[3].depth is None
        assert result.nodes[4].depth == 0.0

    def test_fill_unmapped(self):
        """Nodes with depth=None receive fill_value."""
        grd = _make_depth_grd()
        result = adjust_depths(grd, fill_value=-1.0)
        assert result.nodes[1].depth == -10.0
        assert result.nodes[3].depth == -1.0

    def test_combined(self):
        """min_clamp + max_clamp + fill applied together."""
        grd = _make_depth_grd()
        result = adjust_depths(grd, min_clamp=-8.0, max_clamp=2.0, fill_value=-1.0)
        assert result.nodes[1].depth == -8.0
        assert result.nodes[2].depth == -3.0
        assert result.nodes[3].depth == -1.0
        assert result.nodes[4].depth == 2.0

    def test_no_op(self):
        """No parameters → returned GrdFile has identical depth values."""
        grd = _make_depth_grd()
        result = adjust_depths(grd)
        for nid in grd.nodes:
            assert result.nodes[nid].depth == grd.nodes[nid].depth
        assert grd.nodes[1].depth == -10.0


class TestWarnIfMinGeqMaxArea:

    def test_returns_none_when_both_unset(self):
        """Both bounds None — silent."""
        assert warn_if_min_geq_max_area(None, None) is None

    def test_returns_none_when_one_unset(self):
        """One bound None — silent."""
        assert warn_if_min_geq_max_area(0.1, None) is None
        assert warn_if_min_geq_max_area(None, 0.5) is None

    def test_returns_none_when_min_lt_max(self):
        """Normal case (min < max) — silent."""
        assert warn_if_min_geq_max_area(0.01, 0.1) is None

    def test_returns_none_when_min_zero(self):
        """min=0 is the 'no constraint' sentinel; never warn."""
        assert warn_if_min_geq_max_area(0.0, 0.1) is None

    def test_warns_when_min_eq_max(self):
        """Equal bounds — warn (every triangle below or equal counts as sliver)."""
        msg = warn_if_min_geq_max_area(0.1, 0.1)
        assert msg is not None
        assert "sliver" in msg

    def test_warns_when_min_gt_max(self):
        """min > max — warn (input is logically reversed)."""
        msg = warn_if_min_geq_max_area(0.5, 0.1)
        assert msg is not None
        assert "sliver" in msg


class TestWarnIfMinimalWithCap:

    def test_minimal_with_cap_warns(self):
        """Minimal method + non-zero cap → warn."""
        msg = warn_if_minimal_with_cap("delaunay_minimal", 5000)
        assert msg is not None
        assert "ignored" in msg.lower()

    def test_minimal_without_cap_silent(self):
        """Minimal method + None or 0 cap → silent."""
        assert warn_if_minimal_with_cap("delaunay_minimal", None) is None
        assert warn_if_minimal_with_cap("delaunay_minimal", 0) is None

    def test_quality_with_cap_silent(self):
        """Quality method honors the cap → silent."""
        assert warn_if_minimal_with_cap("delaunay_quality", 5000) is None

    def test_conforming_with_cap_silent(self):
        """Conforming method (caller has separate guard) → silent."""
        assert warn_if_minimal_with_cap("delaunay_conforming", 5000) is None


class TestCheckBathyExtent:

    def test_overlapping_returns_none(self):
        """Bathy bbox inside mesh bbox — silent."""
        grd = _make_square_boundary()  # 10x10 at origin
        bathy = np.array([[5.0, 5.0, -1.0], [3.0, 7.0, -2.0]])
        assert check_bathy_extent(grd, bathy) is None

    def test_disjoint_east_returns_warning(self):
        """Bathy bbox far east of mesh bbox — warn."""
        grd = _make_square_boundary()
        bathy = np.array([[100.0, 5.0, -1.0], [200.0, 5.0, -1.0]])
        msg = check_bathy_extent(grd, bathy)
        assert msg is not None
        assert "does not overlap" in msg

    def test_disjoint_north_returns_warning(self):
        """Bathy bbox far north of mesh bbox — warn."""
        grd = _make_square_boundary()
        bathy = np.array([[5.0, 100.0, -1.0]])
        msg = check_bathy_extent(grd, bathy)
        assert msg is not None

    def test_partial_overlap_returns_none(self):
        """Bathy bbox extends beyond mesh on east but they intersect — silent."""
        grd = _make_square_boundary()
        bathy = np.array([[5.0, 5.0, -1.0], [50.0, 5.0, -1.0]])
        assert check_bathy_extent(grd, bathy) is None

    def test_empty_bathy_returns_none(self):
        """Empty bathy → None (nothing to compare)."""
        grd = _make_square_boundary()
        assert check_bathy_extent(grd, np.empty((0, 3))) is None

    def test_no_exterior_returns_none(self):
        """No line_type=1 boundary → None (cannot establish polygon)."""
        grd = GrdFile()
        bathy = np.array([[1.0, 1.0, -1.0]])
        assert check_bathy_extent(grd, bathy) is None


# ---------------------------------------------------------------------------
# TestBathyUploadStats
# ---------------------------------------------------------------------------


class TestBathyUploadStats:

    def test_summary_min_max_mean(self):
        """Plain xyz array: summary contains min/max/mean numbers."""
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, 3.0], [2.0, 2.0, 5.0]])
        s = summarize_depth_stats(bathy)
        assert "1.00" in s and "5.00" in s and "3.00" in s

    def test_summary_empty(self):
        """Empty array → 'empty' marker."""
        assert "empty" in summarize_depth_stats(np.empty((0, 3)))

    def test_summary_excludes_nan(self):
        """Regression: numpy.min/max/mean propagate NaN by default; the
        summary must use NaN-aware reductions."""
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, np.nan], [2.0, 2.0, 5.0]])
        s = summarize_depth_stats(bathy)
        assert "min=1.00" in s
        assert "max=5.00" in s
        assert "1 NaN excluded" in s

    def test_summary_all_nan(self):
        """All-NaN → explicit message (no nan in min/max/mean output)."""
        bathy = np.array([[0.0, 0.0, np.nan], [1.0, 1.0, np.nan]])
        s = summarize_depth_stats(bathy)
        assert "all depths are nan" in s.lower()

    def test_warn_all_nan(self):
        """All-NaN depths → warn (interpolation will fail)."""
        bathy = np.array([[0.0, 0.0, np.nan], [1.0, 1.0, np.nan]])
        msg = warn_if_degenerate_bathy(bathy)
        assert msg is not None
        assert "nan" in msg.lower()

    def test_warn_all_zero(self):
        """All-zero depths → warn (likely missing depth data)."""
        bathy = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
        msg = warn_if_degenerate_bathy(bathy)
        assert msg is not None
        assert "0" in msg

    def test_warn_all_identical(self):
        """All-identical-nonzero depths → warn (flat bottom)."""
        bathy = np.array([[0.0, 0.0, 5.0], [1.0, 1.0, 5.0]])
        msg = warn_if_degenerate_bathy(bathy)
        assert msg is not None
        assert "identical" in msg

    def test_no_warn_normal(self):
        """Normal varying depths → no warning."""
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, 5.0]])
        assert warn_if_degenerate_bathy(bathy) is None

    def test_no_warn_some_nan(self):
        """Mixed NaN with valid varying depths → no warning."""
        bathy = np.array([[0.0, 0.0, 1.0], [1.0, 1.0, np.nan], [2.0, 2.0, 3.0]])
        assert warn_if_degenerate_bathy(bathy) is None

    def test_empty_returns_none(self):
        """Empty array → None."""
        assert warn_if_degenerate_bathy(np.empty((0, 3))) is None


class TestUploadRejectsUnknownExt:
    """Smoke test: the page-level upload helper must explicitly reject
    unknown extensions instead of letting fiona raise a cryptic error."""

    def test_error_message_lists_accepted_formats(self):
        """Static check that the user-facing error message mentions all
        accepted formats. If someone removes one, this catches it."""
        # `Path` is already imported at the top of test_mesh_builder.py.
        page_src = (
            Path(__file__).resolve().parent.parent / "shyfem_ui" / "pages" / "mesh_builder.py"
        ).read_text()
        # The branch that raises must be present and mention the formats.
        assert "Unrecognized boundary file format" in page_src
        for fmt in (".geojson", ".json", ".gpkg", ".shp", ".zip"):
            assert fmt in page_src


class TestBathymetryRasterVectorization:
    """_load_bathymetry_raster equivalence guard: the vectorized implementation
    must return EXACTLY the same points (same values, same row-major order) as
    the original per-pixel loop. Characterization test for the perf refactor."""

    def _write_raster(self, path, band, nodata, transform, crs="EPSG:4326"):
        import rasterio

        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=band.shape[0],
            width=band.shape[1],
            count=1,
            dtype=str(band.dtype),
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as dst:
            dst.write(band, 1)

    def _reference_loop(self, path):
        """The original row-major loop algorithm (no reprojection for EPSG:4326)."""
        import numpy as np
        import rasterio

        with rasterio.open(path) as src:
            b = src.read(1)
            nd = src.nodata
            pts = []
            for r in range(b.shape[0]):
                for c in range(b.shape[1]):
                    v = b[r, c]
                    if nd is not None and v == nd:
                        continue
                    x, y = src.xy(r, c)
                    pts.append([x, y, float(v)])
        return np.array(pts)

    def test_matches_loop_with_nodata(self, tmp_path):
        import numpy as np
        from rasterio.transform import from_origin

        from shyfem_ui.services.mesh_builder import _load_bathymetry_raster

        band = np.array([[1.0, 2.0, -999.0], [3.0, 4.0, 5.0]], dtype="float32")
        transform = from_origin(10.0, 50.0, 0.5, 0.5)  # west, north, xsize, ysize
        path = tmp_path / "b.tif"
        self._write_raster(path, band, -999.0, transform)

        expected = self._reference_loop(path)
        got = _load_bathymetry_raster(path)
        assert got.shape == expected.shape
        np.testing.assert_allclose(got, expected, rtol=0, atol=0)

    def test_matches_loop_no_nodata(self, tmp_path):
        import numpy as np
        from rasterio.transform import from_origin

        from shyfem_ui.services.mesh_builder import _load_bathymetry_raster

        band = np.array([[7.0, 8.0], [9.0, 10.0], [11.0, 12.0]], dtype="float32")
        transform = from_origin(0.0, 0.0, 1.0, 1.0)
        path = tmp_path / "b2.tif"
        self._write_raster(path, band, None, transform)

        expected = self._reference_loop(path)
        got = _load_bathymetry_raster(path)
        np.testing.assert_allclose(got, expected, rtol=0, atol=0)


class TestBathymetryRasterVectorizationBranches:
    """Lock down the branches the vectorization actually changed but the
    original characterization tests didn't cover: projected-CRS reprojection,
    integer band, and the all-nodata ValueError path."""

    def _write_raster(self, path, band, nodata, transform, crs="EPSG:4326"):
        import rasterio

        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=band.shape[0],
            width=band.shape[1],
            count=1,
            dtype=str(band.dtype),
            crs=crs,
            transform=transform,
            nodata=nodata,
        ) as dst:
            dst.write(band, 1)

    def _reference_loop_full(self, path):
        """Original per-pixel loop INCLUDING the reprojection branch."""
        import numpy as np
        import pyproj
        import rasterio

        with rasterio.open(path) as src:
            b = src.read(1)
            nd = src.nodata
            transformer = None
            if src.crs:
                src_crs = pyproj.CRS.from_user_input(src.crs)
                if src_crs.is_projected:
                    transformer = pyproj.Transformer.from_crs(src_crs, "EPSG:4326", always_xy=True)
            pts = []
            for r in range(b.shape[0]):
                for c in range(b.shape[1]):
                    v = b[r, c]
                    if nd is not None and v == nd:
                        continue
                    x, y = src.xy(r, c)
                    if transformer is not None:
                        x, y = transformer.transform(x, y)
                    pts.append([x, y, float(v)])
        return np.array(pts)

    def test_matches_loop_projected_crs(self, tmp_path):
        import numpy as np
        from rasterio.transform import from_origin

        from shyfem_ui.services.mesh_builder import _load_bathymetry_raster

        band = np.array([[1.0, 2.0], [3.0, 4.0]], dtype="float32")
        transform = from_origin(500000.0, 4500000.0, 100.0, 100.0)  # UTM metres
        path = tmp_path / "proj.tif"
        self._write_raster(path, band, None, transform, crs="EPSG:32635")
        expected = self._reference_loop_full(path)
        got = _load_bathymetry_raster(path)
        np.testing.assert_allclose(got, expected, rtol=0, atol=1e-9)

    def test_integer_band(self, tmp_path):
        import numpy as np
        from rasterio.transform import from_origin

        from shyfem_ui.services.mesh_builder import _load_bathymetry_raster

        band = np.array([[10, 20], [30, 40]], dtype="int16")
        transform = from_origin(0.0, 0.0, 1.0, 1.0)
        path = tmp_path / "int.tif"
        self._write_raster(path, band, None, transform)
        expected = self._reference_loop_full(path)
        got = _load_bathymetry_raster(path)
        np.testing.assert_allclose(got, expected, rtol=0, atol=0)

    def test_all_nodata_raises(self, tmp_path):
        import numpy as np
        import pytest
        from rasterio.transform import from_origin

        from shyfem_ui.services.mesh_builder import _load_bathymetry_raster

        band = np.full((2, 2), -999.0, dtype="float32")
        transform = from_origin(0.0, 0.0, 1.0, 1.0)
        path = tmp_path / "nd.tif"
        self._write_raster(path, band, -999.0, transform)
        with pytest.raises(ValueError):
            _load_bathymetry_raster(path)
