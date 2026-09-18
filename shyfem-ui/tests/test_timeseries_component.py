"""Tests for the shared time-series component helpers."""

import plotly.graph_objects as go

from shyfem_ui.components.timeseries import _scatter_mode


def test_scatter_mode_maps_ui_style_to_valid_plotly_mode():
    # "line"/"scatter" must not leak through as Plotly modes (they raise).
    assert _scatter_mode("line") == "lines"
    assert _scatter_mode("scatter") == "markers"
    assert _scatter_mode("area") == "lines"
    assert _scatter_mode("anything-else") == "lines"


def test_scatter_mode_values_are_accepted_by_plotly():
    # Regression: go.Scattergl(mode="line") raised
    # "Invalid value ... 'line' ... for the 'mode' property".
    for style in ("line", "scatter", "area"):
        trace = go.Scattergl(x=[0, 1], y=[0, 1], mode=_scatter_mode(style))
        assert trace.mode == _scatter_mode(style)
