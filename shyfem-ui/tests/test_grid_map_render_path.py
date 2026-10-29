"""The grid map renders off the loop and keeps the user's view (V-06).

A palette, mode or basemap change used to rebuild every layer on the event
loop (seconds on a large grid) and re-centre the map; a basemap change now
only restyles it, the build runs in a thread, and the view is re-fitted
only for a new grid, EPSG or a 2-D/3-D switch.
"""

import ast
import pathlib

from shyfem_ui.components import grid_map as gm
from shyfem_ui.services.parser_grd import GrdFile


def _inner(name: str) -> ast.AST:
    tree = ast.parse(pathlib.Path(gm.__file__).read_text())
    server = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "grid_map_server"
    )
    for node in ast.walk(server):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def _calls(fn: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)]


def _name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")


def test_layers_are_built_in_a_thread():
    calls = _calls(_inner("_update_map"))
    assert not [
        c for c in calls if _name(c) in ("build_layers", "_build_map", "_compute_view_state")
    ]
    threaded = [c for c in calls if _name(c) == "to_thread"]
    assert len(threaded) == 1 and threaded[0].args[0].id == "_build_map"


def test_basemap_change_does_not_rebuild_layers():
    update = _inner("_update_map")
    assert "map_basemap" not in ast.unparse(update)
    assert "set_style" not in [_name(c) for c in _calls(update)]
    basemap = _inner("_set_basemap")
    assert [_name(c) for c in _calls(basemap) if _name(c) in ("set_style", "update")] == [
        "set_style"
    ]


def test_view_is_refitted_only_for_a_new_grid_epsg_or_3d():
    g1, g2 = GrdFile(), GrdFile()
    first = gm._fit_key(g1, None, False)
    assert gm._needs_refit(None, first)
    assert not gm._needs_refit(first, gm._fit_key(g1, None, False))  # palette/mode change
    assert gm._needs_refit(first, gm._fit_key(g2, None, False))  # another grid
    assert gm._needs_refit(first, gm._fit_key(g1, 32633, False))  # EPSG
    assert gm._needs_refit(first, gm._fit_key(g1, None, True))  # 3-D tilt


def test_an_equal_but_new_grid_is_refitted():
    """Identity, not equality: a reloaded grid equal to the last one (or one
    that reuses a freed id) still re-centres the map."""
    g1, g2 = GrdFile(), GrdFile()
    assert g1 == g2
    assert gm._needs_refit(gm._fit_key(g1, None, False), gm._fit_key(g2, None, False))


def test_view_state_and_fit_bounds_are_gated():
    src = ast.unparse(_inner("_update_map"))
    assert "view_state=vs if refit else None" in src
    assert "if refit and bounds:" in src
