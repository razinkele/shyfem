"""Every map follows the dark theme, including maps on pages not opened yet.

shiny-deckgl builds each map when the page loads, hidden pages included, so
a user who keeps the dark theme gets maps that start light and must turn dark
when the browser reports the theme (app.py sends ``_dark_mode`` right after
Shiny starts). Uses a session of its own, so every basemap picker is at its
default, "Auto". Skips without WebGL (no map instances to inspect).
"""

import pytest

IBM_MAP = "ibm-ibm_map"
RESULTS_MAP = "visualize-results_map-deckgl_map"
GRID_PREP_MAP = "grid_prep-grid_map-deckgl_map"
_T = 20000


@pytest.fixture
def new_session_page(pw_browser, live_server):
    """A second Shiny session, so no basemap picker has been touched."""
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.goto(live_server, wait_until="networkidle", timeout=30000)
    page.wait_for_function(
        "() => { const el = document.getElementById('home-system_health_count');"
        " return el && !el.classList.contains('recalculating') && el.children.length > 0; }",
        timeout=30000,
    )
    page.evaluate("document.querySelectorAll('.modal.show .btn-close').forEach(b => b.click())")
    yield page
    page.close()
    ctx.close()


def _set_theme(page, dark: bool) -> None:
    # What the top bar's theme toggle does (shyfemToggleDark in app.py).
    page.evaluate(
        """(dark) => {
            document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
            Shiny.setInputValue('_dark_mode', dark);
        }""",
        dark,
    )


def _wait_all(page, ids: list[str], fragment: str) -> None:
    page.wait_for_function(
        """([ids, frag]) => ids.every(id => {
            const inst = window.__deckgl_instances[id];
            return !!inst && (inst.currentStyle || '').includes(frag);
        })""",
        arg=[ids, fragment],
        timeout=_T,
    )


@pytest.mark.e2e
def test_every_map_turns_dark_with_the_theme_unopened_pages_too(new_session_page):
    page = new_session_page
    if not page.evaluate("() => !!document.createElement('canvas').getContext('webgl2')"):
        pytest.skip("no WebGL: map instances not created")
    page.wait_for_function(
        "(ids) => ids.every(id => !!(window.__deckgl_instances || {})[id])",
        arg=[IBM_MAP, GRID_PREP_MAP],
        timeout=_T,
    )
    ids = page.evaluate("() => Object.keys(window.__deckgl_instances)")
    assert IBM_MAP in ids and GRID_PREP_MAP in ids, ids
    _wait_all(page, ids, "positron")

    _set_theme(page, True)
    _wait_all(page, ids, "dark-matter")
    for mid in ids:
        assert "deckgl-dark" in (page.get_attribute(f"#{mid}", "class") or ""), mid

    _set_theme(page, False)
    _wait_all(page, ids, "positron")
    for mid in ids:
        assert "deckgl-dark" not in (page.get_attribute(f"#{mid}", "class") or ""), mid
    # Which maps this covered (shown with -rP): the results map is one of them
    # only when the Visualize page builds it at load.
    print("maps:", sorted(ids), "results map included:", RESULTS_MAP in ids)
