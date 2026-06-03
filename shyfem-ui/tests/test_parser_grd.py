"""Tests for .grd file parser."""

import pytest

from shyfem_ui.services.parser_grd import (
    CoordinateSystem,
    Element,
    GrdFile,
    GrdParser,
    Line,
    Node,
    _utm_to_latlon,
)


class TestGrdParser:
    """Tests for GrdParser class."""

    def test_parse_nodes(self):
        """Test parsing node records."""
        content = """
0 Comment line
1 1 0 100.0 200.0
1 2 0 150.0 200.0
1 3 0 125.0 250.0
"""
        result = GrdParser.parse(content)

        assert result.num_nodes == 3
        assert 1 in result.nodes
        assert 2 in result.nodes
        assert 3 in result.nodes

        node1 = result.nodes[1]
        assert node1.id == 1
        assert node1.node_type == 0
        assert node1.x == pytest.approx(100.0)
        assert node1.y == pytest.approx(200.0)
        assert node1.depth is None

    def test_parse_nodes_with_depth(self):
        """Test parsing nodes with depth values."""
        content = """
1 1 0 100.0 200.0 5.5
1 2 0 150.0 200.0 6.0
"""
        result = GrdParser.parse(content)

        assert result.nodes[1].depth == pytest.approx(5.5)
        assert result.nodes[2].depth == pytest.approx(6.0)

    def test_parse_elements(self):
        """Test parsing element records (format: 2 id type nvert n1 n2 n3)."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 200.0
1 3 0 125.0 250.0
2 1 0 3 1 2 3
"""
        result = GrdParser.parse(content)

        assert result.num_elements == 1
        assert 1 in result.elements

        elem = result.elements[1]
        assert elem.id == 1
        assert elem.elem_type == 0
        assert elem.nodes == [1, 2, 3]
        assert elem.is_triangle is True
        assert elem.is_quad is False
        assert elem.depth is None

    def test_parse_quad_elements(self):
        """Test parsing quadrilateral elements (nvert=4)."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 1.0 1.0
1 4 0 0.0 1.0
2 1 0 4 1 2 3 4
"""
        result = GrdParser.parse(content)

        elem = result.elements[1]
        assert elem.is_quad is True
        assert elem.is_triangle is False
        assert len(elem.nodes) == 4

    def test_parse_lines(self):
        """Test parsing line/boundary records (format: 3 id type nvert n1 n2)."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 200.0
3 1 1 2 1 2
"""
        result = GrdParser.parse(content)

        assert result.num_lines == 1
        assert 1 in result.lines

        line = result.lines[1]
        assert line.id == 1
        assert line.line_type == 1
        assert line.nodes == [1, 2]

    def test_parse_comments(self):
        """Test parsing comment lines."""
        content = """
0 This is a comment
0 Another comment
1 1 0 100.0 200.0
"""
        result = GrdParser.parse(content)

        assert len(result.comments) == 2
        assert "This is a comment" in result.comments[0]

    def test_get_bounds(self):
        """Test calculating bounding box."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 250.0
1 3 0 125.0 180.0
"""
        result = GrdParser.parse(content)
        xmin, ymin, xmax, ymax = result.get_bounds()

        assert xmin == pytest.approx(100.0)
        assert xmax == pytest.approx(150.0)
        assert ymin == pytest.approx(180.0)
        assert ymax == pytest.approx(250.0)

    def test_get_depth_range(self):
        """Test calculating depth range."""
        content = """
1 1 0 100.0 200.0 5.0
1 2 0 150.0 200.0 10.0
1 3 0 125.0 250.0 7.5
"""
        result = GrdParser.parse(content)
        min_depth, max_depth = result.get_depth_range()

        assert min_depth == pytest.approx(5.0)
        assert max_depth == pytest.approx(10.0)

    def test_get_depth_range_no_depth(self):
        """Test depth range when no depth data exists."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 200.0
"""
        result = GrdParser.parse(content)
        min_depth, max_depth = result.get_depth_range()

        assert min_depth is None
        assert max_depth is None

    def test_get_node_types(self):
        """Test getting unique node types."""
        content = """
1 1 0 100.0 200.0
1 2 1 150.0 200.0
1 3 2 125.0 250.0
"""
        result = GrdParser.parse(content)
        node_types = result.get_node_types()

        assert node_types == {0, 1, 2}

    def test_get_nodes_array(self):
        """Test getting nodes as numpy array."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 250.0
"""
        result = GrdParser.parse(content)
        arr = result.get_nodes_array()

        assert arr.shape == (2, 2)
        assert arr[0, 0] == pytest.approx(100.0)
        assert arr[0, 1] == pytest.approx(200.0)

    def test_get_nodes_array_with_depth(self):
        """Test getting nodes as numpy array with depth."""
        content = """
1 1 0 100.0 200.0 5.0
1 2 0 150.0 250.0 6.0
"""
        result = GrdParser.parse(content)
        arr = result.get_nodes_array()

        assert arr.shape == (2, 3)
        assert arr[0, 2] == pytest.approx(5.0)

    def test_get_statistics(self):
        """Test getting grid statistics."""
        content = """
0 Test grid
1 1 0 0.0 0.0 1.0
1 2 0 1.0 0.0 2.0
1 3 0 0.5 1.0 3.0
2 1 0 3 1 2 3
3 1 1 2 1 2
"""
        result = GrdParser.parse(content)
        stats = GrdParser.get_statistics(result)

        assert stats["num_nodes"] == 3
        assert stats["num_elements"] == 1
        assert stats["num_triangles"] == 1
        assert stats["num_quads"] == 0
        assert stats["num_lines"] == 1
        assert stats["bounds"]["xmin"] == pytest.approx(0.0)
        assert stats["bounds"]["xmax"] == pytest.approx(1.0)
        assert stats["depth"]["min"] == pytest.approx(1.0)
        assert stats["depth"]["max"] == pytest.approx(3.0)

    def test_generate_roundtrip(self):
        """Test that parse -> generate produces valid output."""
        original = """0 Test grid
1 1 0 100.000000 200.000000 5.000000
1 2 0 150.000000 200.000000 6.000000
1 3 0 125.000000 250.000000 7.000000
2 1 0 3 1 2 3
3 1 1 2 1 2"""

        parsed = GrdParser.parse(original)
        generated = GrdParser.generate(parsed)
        reparsed = GrdParser.parse(generated)

        assert reparsed.num_nodes == 3
        assert reparsed.num_elements == 1
        assert reparsed.num_lines == 1
        assert reparsed.nodes[1].x == pytest.approx(100.0)

    def test_empty_grid(self):
        """Test handling of empty grid."""
        content = """
0 Empty grid
"""
        result = GrdParser.parse(content)

        assert result.num_nodes == 0
        assert result.num_elements == 0
        assert result.num_lines == 0
        assert result.get_bounds() == (0.0, 0.0, 0.0, 0.0)


class TestGrdParserEdgeCases:
    """Tests for malformed files, mixed elements, and edge cases."""

    def test_parse_mixed_triangles_and_quads(self):
        """Test grid with both triangles and quads."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 1.0 1.0
1 4 0 0.0 1.0
1 5 0 2.0 0.5
2 1 0 3 1 2 3
2 2 0 3 1 3 4
2 3 0 4 1 2 5 3
"""
        result = GrdParser.parse(content)

        assert result.num_elements == 3
        assert result.num_triangles == 2
        assert result.num_quads == 1

    def test_parse_blank_lines(self):
        """Test that blank lines are handled gracefully."""
        content = """
1 1 0 100.0 200.0

1 2 0 150.0 200.0

2 1 0 3 1 2 1
"""
        result = GrdParser.parse(content)
        assert result.num_nodes == 2

    def test_parse_large_node_ids(self):
        """Test nodes with large IDs."""
        content = """
1 100000 0 10.0 20.0
1 100001 0 11.0 20.0
1 100002 0 10.5 21.0
2 50000 0 3 100000 100001 100002
"""
        result = GrdParser.parse(content)
        assert 100000 in result.nodes
        assert 50000 in result.elements
        assert result.elements[50000].nodes == [100000, 100001, 100002]

    def test_parse_multiple_line_types(self):
        """Test grid with multiple boundary line types."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 2.0 0.0
3 1 1 2 1 2
3 2 2 2 2 3
3 3 3 2 1 3
"""
        result = GrdParser.parse(content)
        assert result.num_lines == 3
        assert result.lines[1].line_type == 1
        assert result.lines[2].line_type == 2
        assert result.lines[3].line_type == 3
        assert result.lines[1].nodes == [1, 2]
        assert result.lines[2].nodes == [2, 3]
        assert result.lines[3].nodes == [1, 3]

    def test_parse_file_roundtrip(self, tmp_path):
        """Test parse_file and generate round-trip via disk."""
        content = """0 Test grid
1 1 0 100.000000 200.000000 5.000000
1 2 0 150.000000 200.000000 6.000000
2 1 0 3 1 2 1
"""
        f = tmp_path / "test.grd"
        f.write_text(content)

        parsed = GrdParser.parse_file(f)
        assert parsed.num_nodes == 2

        generated = GrdParser.generate(parsed)
        reparsed = GrdParser.parse(generated)
        assert reparsed.num_nodes == 2
        assert reparsed.nodes[1].x == pytest.approx(100.0)

    def test_statistics_depth_range(self):
        """Test get_statistics returns correct depth min/max."""
        content = """
1 1 0 0.0 0.0 2.0
1 2 0 1.0 0.0 4.0
1 3 0 0.5 1.0 6.0
"""
        result = GrdParser.parse(content)
        stats = GrdParser.get_statistics(result)
        assert stats["depth"]["min"] == pytest.approx(2.0)
        assert stats["depth"]["max"] == pytest.approx(6.0)


class TestCoordinateSystem:
    """Tests for coordinate system detection and conversion."""

    def test_coordinate_system_defaults(self):
        """Test default CoordinateSystem is cartesian."""
        cs = CoordinateSystem()
        assert cs.crs_type == "cartesian"
        assert not cs.is_geographic
        assert not cs.is_utm

    def test_coordinate_system_geographic(self):
        """Test geographic coordinate system."""
        cs = CoordinateSystem("geographic")
        assert cs.is_geographic
        assert not cs.is_utm

    def test_coordinate_system_utm(self):
        """Test UTM coordinate system."""
        cs = CoordinateSystem("utm", utm_zone=33, utm_hemisphere="N")
        assert cs.is_utm
        assert cs.utm_zone == 33
        assert "33N" in repr(cs)

    def test_detect_geographic(self):
        """Test detection of geographic coordinates."""
        content = """
1 1 0 12.5 45.3
1 2 0 12.7 45.5
1 3 0 12.6 45.4
"""
        grd = GrdParser.parse(content)
        cs = grd.detect_coordinate_system()
        assert cs.is_geographic

    def test_detect_utm(self):
        """Test detection of UTM coordinates."""
        content = """
1 1 0 500000.0 5000000.0
1 2 0 500100.0 5000100.0
1 3 0 500050.0 5000050.0
"""
        grd = GrdParser.parse(content)
        cs = grd.detect_coordinate_system()
        assert cs.is_utm

    def test_detect_cartesian(self):
        """Test detection of generic cartesian coordinates."""
        content = """
1 1 0 0.0 0.0
1 2 0 50000.0 50000.0
"""
        grd = GrdParser.parse(content)
        cs = grd.detect_coordinate_system()
        assert cs.crs_type == "cartesian"

    def test_detect_empty_grid(self):
        """Test coordinate detection on empty grid."""
        grd = GrdFile()
        cs = grd.detect_coordinate_system()
        assert cs.crs_type == "cartesian"

    def test_utm_to_latlon_basic(self):
        """Test basic UTM to lat/lon conversion."""
        # UTM zone 33N, roughly Venice area
        lat, lon = _utm_to_latlon(300000.0, 5000000.0, 33, True)
        # Should be in reasonable range for Europe
        assert 40.0 < lat < 50.0
        assert 10.0 < lon < 20.0

    def test_to_geographic_already_geographic(self):
        """Test to_geographic on already-geographic grid returns False."""
        content = """
1 1 0 12.5 45.3
1 2 0 12.7 45.5
"""
        grd = GrdParser.parse(content)
        grd.detect_coordinate_system()
        assert grd.to_geographic() is False

    def test_to_geographic_converts_utm(self):
        """Test to_geographic converts UTM nodes in place."""
        content = """
1 1 0 500000.0 5000000.0
1 2 0 500100.0 5000100.0
"""
        grd = GrdParser.parse(content)
        grd.detect_coordinate_system()
        result = grd.to_geographic(utm_zone=33, hemisphere="N")
        assert result is True
        # After conversion, coordinates should be in geographic range
        for node in grd.nodes.values():
            assert -180 <= node.x <= 360
            assert -90 <= node.y <= 90


class TestNvertFormat:
    """Tests for the correct nvert-based element/line parsing."""

    def test_element_depth_parsed(self):
        """Test that element depth (after node IDs) is correctly parsed."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 0.5 1.0
2 1 1 3 1 2 3 7.442161
"""
        grd = GrdParser.parse(content)
        elem = grd.elements[1]
        assert elem.nodes == [1, 2, 3]
        assert elem.depth == pytest.approx(7.442161)

    def test_element_no_depth(self):
        """Test element without depth field."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 0.5 1.0
2 1 0 3 1 2 3
"""
        grd = GrdParser.parse(content)
        assert grd.elements[1].depth is None

    def test_quad_element_with_depth(self):
        """Test quad element (nvert=4) with depth."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 1.0 1.0
1 4 0 0.0 1.0
2 1 0 4 1 2 3 4 5.5
"""
        grd = GrdParser.parse(content)
        elem = grd.elements[1]
        assert elem.is_quad
        assert elem.nodes == [1, 2, 3, 4]
        assert elem.depth == pytest.approx(5.5)

    def test_nvert_not_treated_as_node_id(self):
        """Regression test: nvert must NOT be included as a node ID."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 0.5 1.0
2 1 0 3 1 2 3
"""
        grd = GrdParser.parse(content)
        elem = grd.elements[1]
        # nvert=3 should NOT appear in node list
        assert len(elem.nodes) == 3
        assert elem.nodes == [1, 2, 3]

    def test_line_nvert_parsed(self):
        """Test that line records use nvert correctly."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 2.0 0.0
3 1 1 3 1 2 3
"""
        grd = GrdParser.parse(content)
        line = grd.lines[1]
        assert line.nodes == [1, 2, 3]

    def test_multiline_continuation(self):
        """Test line record with nodes on continuation lines."""
        content = """
1 10 0 0.0 0.0
1 20 0 1.0 0.0
1 30 0 2.0 0.0
1 40 0 3.0 0.0
1 50 0 4.0 0.0
3 1 2 5
 10 20 30 40 50
"""
        grd = GrdParser.parse(content)
        assert 1 in grd.lines
        line = grd.lines[1]
        assert line.nodes == [10, 20, 30, 40, 50]

    def test_multiline_continuation_split_across_lines(self):
        """Test continuation spanning multiple file lines."""
        content = """
1 10 0 0.0 0.0
1 20 0 1.0 0.0
1 30 0 2.0 0.0
1 40 0 3.0 0.0
1 50 0 4.0 0.0
1 60 0 5.0 0.0
3 1 2 6
 10 20 30
 40 50 60
"""
        grd = GrdParser.parse(content)
        line = grd.lines[1]
        assert line.nodes == [10, 20, 30, 40, 50, 60]

    def test_continuation_followed_by_new_record(self):
        """Test that a new record header finalizes a pending line."""
        content = """
1 10 0 0.0 0.0
1 20 0 1.0 0.0
1 30 0 2.0 0.0
3 1 2 3
 10 20 30
1 40 0 3.0 0.0
"""
        grd = GrdParser.parse(content)
        assert grd.lines[1].nodes == [10, 20, 30]
        assert 40 in grd.nodes

    def test_generate_includes_nvert_for_elements(self):
        """Test that generate writes nvert field for elements."""
        grd = GrdFile()
        grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0)
        grd.nodes[2] = Node(id=2, node_type=0, x=1.0, y=0.0)
        grd.nodes[3] = Node(id=3, node_type=0, x=0.5, y=1.0)
        grd.elements[1] = Element(id=1, elem_type=0, nodes=[1, 2, 3])

        output = GrdParser.generate(grd)
        # Element line should be: 2 1 0 3 1 2 3
        elem_line = [ln for ln in output.splitlines() if ln.startswith("2 ")][0]
        parts = elem_line.split()
        assert parts[3] == "3"  # nvert
        assert parts[4:7] == ["1", "2", "3"]  # node IDs

    def test_generate_includes_nvert_for_lines(self):
        """Test that generate writes nvert field for lines."""
        grd = GrdFile()
        grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0)
        grd.nodes[2] = Node(id=2, node_type=0, x=1.0, y=0.0)
        grd.lines[1] = Line(id=1, line_type=1, nodes=[1, 2])

        output = GrdParser.generate(grd)
        line = [ln for ln in output.splitlines() if ln.startswith("3 ")][0]
        parts = line.split()
        assert parts[3] == "2"  # nvert
        assert parts[4:6] == ["1", "2"]  # node IDs

    def test_generate_includes_element_depth(self):
        """Test that generate writes element depth when present."""
        grd = GrdFile()
        grd.nodes[1] = Node(id=1, node_type=0, x=0.0, y=0.0)
        grd.nodes[2] = Node(id=2, node_type=0, x=1.0, y=0.0)
        grd.nodes[3] = Node(id=3, node_type=0, x=0.5, y=1.0)
        grd.elements[1] = Element(id=1, elem_type=0, nodes=[1, 2, 3], depth=7.5)

        output = GrdParser.generate(grd)
        elem_line = [ln for ln in output.splitlines() if ln.startswith("2 ")][0]
        parts = elem_line.split()
        assert float(parts[7]) == pytest.approx(7.5)

    def test_roundtrip_with_depth(self):
        """Test full parse → generate → reparse roundtrip preserves depth."""
        content = """
1 1 0 0.000000 0.000000
1 2 0 1.000000 0.000000
1 3 0 0.500000 1.000000
2 1 1 3 1 2 3 7.442161
"""
        parsed = GrdParser.parse(content)
        generated = GrdParser.generate(parsed)
        reparsed = GrdParser.parse(generated)

        assert reparsed.elements[1].nodes == [1, 2, 3]
        assert reparsed.elements[1].depth == pytest.approx(7.442161)

    def test_real_shyfem_element_format(self):
        """Test parsing real SHYFEM element format (from MM_coarse.grd)."""
        content = """
1 334 0 699331.562500 4174489.000000 10.000000
1 828 0 699206.375000 4174600.500000 10.000000
1 335 0 699451.750000 4174606.500000 10.000000
2 1 1 3 334 828 335 7.442161
"""
        grd = GrdParser.parse(content)
        assert grd.num_elements == 1
        elem = grd.elements[1]
        assert elem.nodes == [334, 828, 335]
        assert elem.depth == pytest.approx(7.442161)
        assert elem.elem_type == 1
