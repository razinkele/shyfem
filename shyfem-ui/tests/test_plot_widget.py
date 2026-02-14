"""Tests for plot_widget pure plotting functions."""

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest

from shyfem_ui.components.plot_widget import (
    plot_boundaries,
    plot_depth_contour,
    plot_element_quality,
    plot_mesh,
)
from shyfem_ui.services.parser_grd import Element, GrdFile, Line, Node


@pytest.fixture
def sample_grd():
    """Build a minimal 4-node, 2-triangle grid with depths and a boundary."""
    nodes = {
        1: Node(id=1, node_type=0, x=0.0, y=0.0, depth=1.0),
        2: Node(id=2, node_type=0, x=1.0, y=0.0, depth=2.0),
        3: Node(id=3, node_type=0, x=0.0, y=1.0, depth=3.0),
        4: Node(id=4, node_type=0, x=1.0, y=1.0, depth=4.0),
    }
    elements = {
        1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),
        2: Element(id=2, elem_type=0, nodes=[2, 4, 3]),
    }
    lines = {
        1: Line(id=1, line_type=1, nodes=[1, 2]),
    }
    return GrdFile(nodes=nodes, elements=elements, lines=lines)


@pytest.fixture(autouse=True)
def close_figures():
    """Close all matplotlib figures after each test to prevent memory leaks."""
    yield
    plt.close("all")


# ── plot_mesh ────────────────────────────────────────────────────


def test_plot_mesh_returns_figure(sample_grd):
    fig = plot_mesh(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_mesh_title(sample_grd):
    fig = plot_mesh(sample_grd)
    ax = fig.axes[0]
    assert "4" in ax.get_title()
    assert "2" in ax.get_title()


def test_plot_mesh_show_nodes(sample_grd):
    fig = plot_mesh(sample_grd, show_nodes=True)
    assert isinstance(fig, plt.Figure)


def test_plot_mesh_show_labels(sample_grd):
    fig = plot_mesh(sample_grd, show_labels=True)
    assert isinstance(fig, plt.Figure)


# ── plot_depth_contour ───────────────────────────────────────────


def test_plot_depth_contour_returns_figure(sample_grd):
    fig = plot_depth_contour(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_depth_contour_title(sample_grd):
    fig = plot_depth_contour(sample_grd)
    ax = fig.axes[0]
    assert "Depth" in ax.get_title()


def test_plot_depth_contour_no_depth():
    """Grid with all None depths shows 'No depth data' message."""
    nodes = {
        1: Node(id=1, node_type=0, x=0.0, y=0.0, depth=None),
        2: Node(id=2, node_type=0, x=1.0, y=0.0, depth=None),
        3: Node(id=3, node_type=0, x=0.0, y=1.0, depth=None),
    }
    elements = {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])}
    grd = GrdFile(nodes=nodes, elements=elements)
    fig = plot_depth_contour(grd)
    assert isinstance(fig, plt.Figure)


# ── plot_boundaries ──────────────────────────────────────────────


def test_plot_boundaries_returns_figure(sample_grd):
    fig = plot_boundaries(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_boundaries_title(sample_grd):
    fig = plot_boundaries(sample_grd)
    ax = fig.axes[0]
    assert "Boundaries" in ax.get_title()


# ── plot_element_quality ─────────────────────────────────────────


def test_plot_element_quality_returns_figure(sample_grd):
    fig = plot_element_quality(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_element_quality_title(sample_grd):
    fig = plot_element_quality(sample_grd)
    ax = fig.axes[0]
    assert "Quality" in ax.get_title()
    assert "2" in ax.get_title()  # 2 triangles
