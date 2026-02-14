"""Tests for visualize page pure functions."""

from pathlib import Path

import plotly.graph_objects as go
import pytest

from shyfem_ui.pages.visualize import (
    _compare_grids,
    _compare_timeseries,
    _load_timeseries,
    _plotly_timeseries,
)
from shyfem_ui.services.parser_grd import Element, GrdFile, Line, Node


# ── fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def sample_grd():
    """Minimal 4-node, 2-triangle grid with depths."""
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
    return GrdFile(nodes=nodes, elements=elements)


def _make_ts_data(with_df=False):
    """Create a synthetic time series data dict."""
    data = [[0, 1.0, 2.0], [1, 1.5, 2.5], [2, 2.0, 3.0]]
    columns = ["time", "col1", "col2"]
    result = {"columns": columns, "data": data, "df": None}
    if with_df:
        import pandas as pd
        result["df"] = pd.DataFrame(data, columns=columns)
    return result


# ── _load_timeseries ─────────────────────────────────────────────


def test_load_timeseries_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("time,col1,col2\n0,1.0,2.0\n1,1.5,2.5\n")
    result = _load_timeseries(f)
    assert "columns" in result
    assert "data" in result
    assert len(result["columns"]) == 3


def test_load_timeseries_whitespace(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("time col1 col2\n0 1.0 2.0\n1 1.5 2.5\n")
    result = _load_timeseries(f)
    assert len(result["data"]) >= 1 or result["df"] is not None


def test_load_timeseries_empty(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("")
    result = _load_timeseries(f)
    assert "columns" in result


# ── _plotly_timeseries ───────────────────────────────────────────


def test_plotly_timeseries_line():
    data = _make_ts_data(with_df=True)
    fig = _plotly_timeseries(data, "line", show_grid=False)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2  # col1, col2


def test_plotly_timeseries_scatter():
    data = _make_ts_data(with_df=True)
    fig = _plotly_timeseries(data, "scatter", show_grid=False)
    assert isinstance(fig, go.Figure)


def test_plotly_timeseries_area():
    data = _make_ts_data(with_df=True)
    fig = _plotly_timeseries(data, "area", show_grid=True)
    assert isinstance(fig, go.Figure)


def test_plotly_timeseries_raw_data():
    data = _make_ts_data(with_df=False)
    fig = _plotly_timeseries(data, "line", show_grid=False)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


# ── _compare_grids ───────────────────────────────────────────────


def test_compare_grids_returns_figure(sample_grd):
    fig = _compare_grids(sample_grd, sample_grd, "Viridis")
    assert isinstance(fig, go.Figure)


def test_compare_grids_title(sample_grd):
    fig = _compare_grids(sample_grd, sample_grd, "Viridis")
    assert "Comparison" in fig.layout.title.text


# ── _compare_timeseries ─────────────────────────────────────────


def test_compare_timeseries_returns_figure():
    ts1 = _make_ts_data(with_df=True)
    ts2 = _make_ts_data(with_df=True)
    fig = _compare_timeseries(ts1, ts2)
    assert isinstance(fig, go.Figure)


def test_compare_timeseries_has_traces():
    ts1 = _make_ts_data(with_df=True)
    ts2 = _make_ts_data(with_df=True)
    fig = _compare_timeseries(ts1, ts2)
    # 2 columns x 2 datasets = 4 traces
    assert len(fig.data) == 4
