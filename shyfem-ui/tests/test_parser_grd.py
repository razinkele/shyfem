"""Tests for .grd file parser."""

import numpy as np
import pytest
from shyfem_ui.services.parser_grd import Element, GrdFile, GrdParser, Line, Node


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
        """Test parsing element records."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 200.0
1 3 0 125.0 250.0
2 1 0 1 2 3
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

    def test_parse_quad_elements(self):
        """Test parsing quadrilateral elements."""
        content = """
1 1 0 0.0 0.0
1 2 0 1.0 0.0
1 3 0 1.0 1.0
1 4 0 0.0 1.0
2 1 0 1 2 3 4
"""
        result = GrdParser.parse(content)

        elem = result.elements[1]
        assert elem.is_quad is True
        assert elem.is_triangle is False
        assert len(elem.nodes) == 4

    def test_parse_lines(self):
        """Test parsing line/boundary records."""
        content = """
1 1 0 100.0 200.0
1 2 0 150.0 200.0
3 1 1 1 2
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
2 1 0 1 2 3
3 1 1 1 2
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
2 1 0 1 2 3
3 1 1 1 2"""

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
