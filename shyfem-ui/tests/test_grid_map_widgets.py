"""Tests for grid_map deck.gl widget integration (layer_legend_widget, screenshot_widget)."""

import re
from unittest.mock import MagicMock

import pytest


def test_screenshot_widget_importable():
    """screenshot_widget is available from shiny_deckgl."""
    from shiny_deckgl import screenshot_widget
    assert screenshot_widget is not None


def test_layer_legend_widget_importable():
    """layer_legend_widget is available from shiny_deckgl."""
    from shiny_deckgl import layer_legend_widget
    assert layer_legend_widget is not None


def test_grid_map_ui_no_manual_toggle_checkboxes():
    """grid_map_ui output must not contain show_emodnet/show_boundaries/show_nodes checkboxes."""
    from shyfem_ui.components.grid_map import grid_map_ui
    html = str(grid_map_ui("test_map"))
    assert "show_emodnet" not in html, "show_emodnet checkbox should be removed"
    assert "show_boundaries" not in html, "show_boundaries checkbox should be removed"
    assert "show_nodes" not in html, "show_nodes checkbox should be removed"


def test_grid_map_ui_fallback_without_deckgl():
    """When MapWidget is None, grid_map_ui returns an alert div."""
    from unittest.mock import patch
    import shyfem_ui.components.grid_map as gm

    with patch.object(gm, "MapWidget", None):
        html = str(gm.grid_map_ui("test_fallback"))
    assert "shiny_deckgl" in html


def test_build_label_map_static_entries():
    """_build_label_map returns friendly names for known layer IDs."""
    from shyfem_ui.components.grid_map import _build_label_map

    layers = [
        {"id": "emodnet"},
        {"id": "wireframe"},
        {"id": "triangles"},
        {"id": "nodes"},
    ]
    label_map = _build_label_map(layers, mode="depth")
    assert label_map["emodnet"] == "EMODnet Bathy"
    assert label_map["wireframe"] == "Wireframe"
    assert label_map["triangles"] == "Depth"  # mode-dependent
    assert label_map["nodes"] == "Nodes"


def test_build_label_map_mode_dependent_triangles():
    """_build_label_map triangles label reflects the active view mode."""
    from shyfem_ui.components.grid_map import _build_label_map

    layers = [{"id": "triangles"}]
    assert _build_label_map(layers, mode="quality")["triangles"] == "Quality"
    assert _build_label_map(layers, mode="depth_3d")["triangles"] == "Depth 3D"
    assert _build_label_map(layers, mode="mesh")["triangles"] == "Triangles"


def test_build_label_map_dynamic_boundaries():
    """_build_label_map generates entries for boundary layer IDs."""
    from shyfem_ui.components.grid_map import _build_label_map

    layers = [
        {"id": "boundary_coastline"},
        {"id": "boundary_island"},
    ]
    label_map = _build_label_map(layers)
    assert "boundary_coastline" in label_map
    assert "boundary_island" in label_map
    assert "coastline" in label_map["boundary_coastline"].lower()


def test_build_layers_no_toggle_params():
    """build_layers no longer accepts show_emodnet/show_boundaries/show_nodes params."""
    import inspect
    from shyfem_ui.components.grid_map import build_layers

    sig = inspect.signature(build_layers)
    params = set(sig.parameters.keys())
    assert "show_emodnet" not in params, "show_emodnet param should be removed"
    assert "show_boundaries" not in params, "show_boundaries param should be removed"
    assert "show_nodes" not in params, "show_nodes param should be removed"
