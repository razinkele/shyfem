"""The Grid Prep map keeps the user's view across mode and basemap changes (V-06).

A mode, palette or basemap change used to rebuild everything and re-centre
the map, throwing away the user's zoom. Runs against the real
grid_prep_server; skips without WebGL (no map instance to inspect).
"""

from pathlib import Path

import pytest

MAP_ID = "grid_prep-grid_map-deckgl_map"
_GRD = Path(__file__).resolve().parents[2] / "testcases/examples/mar_menor/GRID/MM_coarse.grd"
_T = 20000


def _has_layer(page, layer_id: str) -> None:
    page.wait_for_function(
        """([mid, lid]) => {
            const inst = window.__deckgl_instances && window.__deckgl_instances[mid];
            return !!inst && (inst.lastLayers || []).some(l => l.id === lid);
        }""",
        arg=[MAP_ID, layer_id],
        timeout=_T,
    )


def _zoom(page) -> float:
    return page.evaluate("(mid) => window.__deckgl_instances[mid].map.getZoom()", MAP_ID)


def _select(page, input_id: str, value: str) -> None:
    page.evaluate(
        """([id, v]) => {
            const el = document.getElementById(id);
            if (el.selectize) { el.selectize.setValue(v); return; }
            el.value = v;
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        [input_id, value],
    )


@pytest.mark.e2e
def test_mode_and_basemap_changes_keep_the_zoom(pw_page, live_server):
    if not _GRD.is_file():
        pytest.skip(f"sample grid missing: {_GRD}")
    page = pw_page
    page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
    page.locator("#sf-page-Grid-Prep a[role='tab']:has-text('Interactive Map')").click()
    page.locator("#grid_prep-grd_file-file_input").set_input_files(str(_GRD))
    has_map = page.evaluate(
        """(mid) => !!document.createElement('canvas').getContext('webgl2')
            && !!(window.__deckgl_instances && window.__deckgl_instances[mid])""",
        MAP_ID,
    )
    if not has_map:
        pytest.skip("no WebGL: map instance not created")
    _has_layer(page, "wireframe")
    page.wait_for_timeout(1500)  # let the initial fit animation finish

    zoom = _zoom(page) + 1.5
    page.evaluate(
        "([mid, z]) => window.__deckgl_instances[mid].map.jumpTo({zoom: z})", [MAP_ID, zoom]
    )

    _select(page, "grid_prep-grid_map-map_mode", "depth")
    _has_layer(page, "triangles")
    page.wait_for_timeout(1500)
    assert _zoom(page) == pytest.approx(zoom, abs=0.01), "a mode change re-centred the map"

    _select(page, "grid_prep-grid_map-map_basemap", "dark")
    page.wait_for_timeout(1500)
    assert _zoom(page) == pytest.approx(zoom, abs=0.01), "a basemap change re-centred the map"
    _has_layer(page, "triangles")

    _select(page, "grid_prep-grid_map-map_mode", "mesh")
    _select(page, "grid_prep-grid_map-map_basemap", "positron")


def _style(page) -> str:
    return page.evaluate(
        "(mid) => (window.__deckgl_instances[mid] || {}).currentStyle || ''", MAP_ID
    )


def _set_theme(page, dark: bool) -> None:
    # What the top bar's theme toggle does (shyfemToggleDark in app.py).
    page.evaluate(
        """(dark) => {
            document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
            Shiny.setInputValue('_dark_mode', dark);
        }""",
        dark,
    )


def _wait_style(page, fragment: str) -> None:
    page.wait_for_function(
        """([mid, frag]) => {
            const inst = window.__deckgl_instances && window.__deckgl_instances[mid];
            return !!inst && (inst.currentStyle || '').includes(frag);
        }""",
        arg=[MAP_ID, fragment],
        timeout=_T,
    )


@pytest.mark.e2e
def test_auto_basemap_follows_the_dark_theme(pw_page, live_server):
    """The "Auto" basemap turns dark with the app, and the mesh stays on the map."""
    if not _GRD.is_file():
        pytest.skip(f"sample grid missing: {_GRD}")
    page = pw_page
    page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
    page.locator("#sf-page-Grid-Prep a[role='tab']:has-text('Interactive Map')").click()
    page.locator("#grid_prep-grd_file-file_input").set_input_files(str(_GRD))
    has_map = page.evaluate(
        """(mid) => !!document.createElement('canvas').getContext('webgl2')
            && !!(window.__deckgl_instances && window.__deckgl_instances[mid])""",
        MAP_ID,
    )
    if not has_map:
        pytest.skip("no WebGL: map instance not created")
    _select(page, "grid_prep-grid_map-map_mode", "mesh")
    _select(page, "grid_prep-grid_map-map_basemap", "positron")
    _has_layer(page, "wireframe")
    _wait_style(page, "positron")
    try:
        _set_theme(page, True)
        _wait_style(page, "dark-matter")
        assert "deckgl-dark" in (page.get_attribute(f"#{MAP_ID}", "class") or "")
        _has_layer(page, "wireframe")

        # A fixed choice ignores the theme.
        _select(page, "grid_prep-grid_map-map_basemap", "osm")
        _wait_style(page, "openfreemap")
        _select(page, "grid_prep-grid_map-map_basemap", "positron")
        _wait_style(page, "dark-matter")
    finally:
        _set_theme(page, False)  # the page is shared with the other E2E tests
    _wait_style(page, "positron")
    assert "deckgl-dark" not in (page.get_attribute(f"#{MAP_ID}", "class") or "")
    _has_layer(page, "wireframe")
