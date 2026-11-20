"""Tests for grid_map deck.gl widget integration (layer_legend_widget, screenshot_widget)."""

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


# --- Basemaps that follow the app's light/dark theme --------------------------


def test_basemap_style_auto_follows_the_theme():
    from shyfem_ui.components import grid_map as gm

    if gm.CARTO_POSITRON is None:
        pytest.skip("shiny_deckgl not installed")
    assert gm.basemap_style("positron", dark=False) == gm.CARTO_POSITRON
    assert gm.basemap_style("positron", dark=True) == gm.CARTO_DARK
    assert gm.basemap_style(None, dark=True) == gm.CARTO_DARK  # a map without a picker
    for dark in (False, True):  # the fixed choices ignore the theme
        assert gm.basemap_style("dark", dark=dark) == gm.CARTO_DARK
        assert gm.basemap_style("osm", dark=dark) == gm.OSM_LIBERTY
    assert gm._BASEMAP_CHOICES["positron"] == "Auto"


def test_session_dark_mode_reads_the_root_input():
    from shiny.types import SilentException

    from shyfem_ui.components.grid_map import session_dark_mode

    class _Input(dict):
        def __getitem__(self, key):
            if key not in self.keys():
                raise SilentException()
            return lambda: dict.__getitem__(self, key)

    class _Session:
        def __init__(self, values):
            self.input = _Input(values)

        def root_scope(self):
            return self

    assert session_dark_mode(_Session({"_dark_mode": True})) is True
    assert session_dark_mode(_Session({"_dark_mode": False})) is False
    assert session_dark_mode(_Session({})) is False  # never reported: light


async def test_apply_map_theme_sets_the_widgets_theme_then_the_basemap():
    from shyfem_ui.components import grid_map as gm

    if gm.CARTO_POSITRON is None:
        pytest.skip("shiny_deckgl not installed")
    calls = []

    class _Map:
        async def set_dark_mode(self, session, dark):
            calls.append(("dark", dark))

        async def set_style(self, session, style):
            calls.append(("style", style))

    await gm.apply_map_theme(_Map(), object(), "positron", True)
    await gm.apply_map_theme(_Map(), object(), "osm", False)
    assert calls == [
        ("dark", True),
        ("style", gm.CARTO_DARK),
        ("dark", False),
        ("style", gm.OSM_LIBERTY),
    ]


def test_every_map_restyles_on_the_theme():
    """The three maps read the theme reactively and restyle through one helper."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "shyfem_ui"
    expected = {
        "components/grid_map.py": ("_set_basemap", "input.map_basemap()"),
        "pages/ibm.py": ("_set_basemap", "input.ibm_basemap()"),
        "components/results_map.py": ("_theme", "None"),
    }
    for rel, (name, choice) in expected.items():
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
        assert len(fns) == 1, rel
        src = ast.unparse(fns[0])
        assert f"apply_map_theme(_map, session, {choice}, session_dark_mode(session))" in src, rel


def test_ibm_layer_rebuild_does_not_read_the_basemap():
    """A basemap change restyles the IBM map; it no longer rebuilds every layer."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "shyfem_ui/pages/ibm.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    update = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_update_ibm_map"
    )
    body = ast.unparse(update)
    assert "ibm_basemap" not in body and "set_style" not in body
