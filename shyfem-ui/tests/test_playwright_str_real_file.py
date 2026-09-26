"""E2E: a real-shaped SHYFEM STR loads, and the UI shows what is in it.

The point of issue #86, end to end. Before the parser widening this exact
file lost `&para` (so the Physics page showed no `itanf`/`itend`/`idt` at
all) and every decorated `$boundN` header (so the Boundaries panel said "No
boundaries defined"); the node runs were then truncated to their first token.
The list values that replaced that truncation render through
`format_param_display` -- `str()` would put "[1547, 1548, ...]" in the Nodes
field, which the panel writes straight back into the file.

Runs against the real live server (`pw_page` drives Chromium against the
Shiny app started by `_app_server`/`_test_app.py`), so the STR is parsed by
the app subprocess, off disk, through `StrParser.parse_file`.

Default pytest config excludes `test_playwright_*.py`
(`--ignore-glob="tests/test_playwright_*.py"` in `addopts`); run this file
directly or via `--override-ini="addopts="`.
"""

import re

import pytest
from playwright.sync_api import expect

from tests.test_parser_str import CURONIAN_STR

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

# The unnumbered `$bound` block the Physics page's Boundary Conditions panel
# reads (COMMON_SECTIONS: "Boundary conditions ... defaults for all
# boundaries"); the numbered blocks live in CURONIAN_STR and are what the
# Simulation page's Boundaries panel lists.
BOUND_DEFAULTS_STR = """$title
        bound defaults
        grid
$end

$bound
        kbound = 1855 1856 1882 1883
        ibtyp = 1
$end
"""


@pytest.fixture
def str_project(app_work_dir):
    """A project holding the Curonian-shaped STR, under the LIVE APP's own
    work_dir -- the load path runs `config.confine_path(..., must_exist=True)`
    inside the app subprocess, which is configured with this directory."""
    work = app_work_dir / "e2e_str_real_file"
    work.mkdir(parents=True, exist_ok=True)
    (work / "curonian29.str").write_text(CURONIAN_STR)
    (work / "bound_defaults.str").write_text(BOUND_DEFAULTS_STR)
    return {
        "id": 9101,
        "name": "e2e_str_real_file",
        "work_dir": str(work),
        "description": None,
        "grids": [],
        "simulations": [],
        "files": [],
    }


@pytest.fixture(autouse=True)
def _back_to_dashboard(pw_page):
    """`pw_page` is one session-scoped page shared by the whole file, so each
    test leaves the app where the next one finds it (the fixture's own
    contract). Clearing the active project also stops a later picker test
    from inheriting this one's."""
    yield
    pw_page.evaluate("""
        if (typeof window.__test_set_active_project === 'function') {
            window.__test_set_active_project("");
        }
        if (typeof shyfemNavTo === 'function') { shyfemNavTo('Dashboard'); }
    """)
    pw_page.wait_for_timeout(200)


def _expand_panel(pw_page, label: str):
    """Expand one physics accordion panel, whatever state it is in.

    Each panel body is a Shiny output and Shiny suspends hidden outputs, so
    with the accordion built `open=False` nothing inside it exists until it is
    expanded. Clicking unconditionally would *collapse* a panel an earlier
    test left open (the page is shared), so check first. No force=True either:
    a force click dispatches at the element's centre without scrolling it into
    view, and every header below the fold misses.
    """
    button = pw_page.locator("#physics-physics_accordion .accordion-button", has_text=label).first
    button.wait_for(state="attached", timeout=15000)
    if button.get_attribute("aria-expanded") != "true":
        button.click()
    expect(button).to_have_attribute("aria-expanded", "true", timeout=10000)


def _open_project(pw_page, project):
    pw_page.evaluate("(proj) => window.__test_set_active_project(proj)", project)
    pw_page.wait_for_timeout(300)


def _load_on_page(pw_page, module: str, page_name: str, filename: str):
    """Navigate to *page_name*, pick *filename* in its STR dropdown, Load."""
    pw_page.evaluate("(name) => shyfemNavTo(name)", page_name)
    select = pw_page.locator(f"select#{module}-str_path")
    select.wait_for(state="attached", timeout=15000)
    # The dropdown is rebuilt from the active project over the websocket, so
    # the option lands a moment after the <select> itself; poll for it.
    expect(select.locator(f"option[value$='{filename}']")).to_have_count(1, timeout=15000)
    select.select_option(
        value=select.locator(f"option[value$='{filename}']").first.get_attribute("value")
    )
    pw_page.locator(f"#{module}-load_btn").click(force=True)


def test_curonian_str_populates_physics_timing_and_boundaries(pw_page, str_project):
    _open_project(pw_page, str_project)
    _load_on_page(pw_page, "physics", "Physics", "curonian29.str")

    _expand_panel(pw_page, "Simulation Timing")
    itanf = pw_page.locator("#physics-itanf")
    itanf.wait_for(state="attached", timeout=15000)
    # From `&para` -- the section that was dropped entirely. The decoy
    # `itanf = 347068800` in the prose above it is inter-section text and
    # must not be what lands here.
    expect(itanf).to_have_value("1993-01-01", timeout=15000)
    expect(pw_page.locator("#physics-itend")).to_have_value("2016-12-31")
    expect(pw_page.locator("#physics-idt")).to_have_value("5m")

    # --- the numbered boundaries, on the Simulation page's Boundaries panel
    _load_on_page(pw_page, "simulation", "Simulation", "curonian29.str")
    # Shiny suspends outputs in a hidden tab pane, so the Boundaries sub-tab
    # has to be selected explicitly (it persists on the session-scoped page).
    # Plain click, not force: force does not scroll the tab into view.
    tab = pw_page.locator("#sf-page-Simulation a.nav-link", has_text="Boundaries").first
    tab.wait_for(state="visible", timeout=15000)
    tab.click()
    expect(tab).to_have_class(re.compile(r"\bactive\b"), timeout=10000)

    nodes1 = pw_page.locator("#simulation-boundary_editor-bound_nodes_1")
    nodes1.wait_for(state="attached", timeout=15000)
    # $bound1's run spans a continuation line; $bound2's is one line. Neither
    # may show a Python repr, and both must be complete -- the first token
    # alone ("1547", "1855") was the old, plausible-looking truncation.
    expect(nodes1).to_have_value("1547 1548 1549 1550 1554 1555", timeout=15000)
    expect(pw_page.locator("#simulation-boundary_editor-bound_nodes_2")).to_have_value(
        "1855 1856 1882 1883"
    )
    # The decorated headers named the sections; without them there would be
    # no cards at all.
    panel = pw_page.locator("#simulation-boundary_editor-boundary_list")
    # The card badges are CSS-uppercased, so compare case-insensitively.
    panel_text = panel.inner_text()
    lowered = panel_text.lower()
    assert "$bound1" in lowered and "$bound2" in lowered, panel_text
    assert "[" not in panel_text, panel_text


def test_physics_boundary_panel_shows_a_node_run_space_separated(pw_page, str_project):
    """The Physics page's own kbound field (the second render site): an
    unnumbered `$bound` block's node run, shown as the file spells it."""
    _open_project(pw_page, str_project)
    _load_on_page(pw_page, "physics", "Physics", "bound_defaults.str")

    _expand_panel(pw_page, "Boundary Conditions")
    kbound = pw_page.locator("#physics-kbound")
    kbound.wait_for(state="attached", timeout=15000)
    expect(kbound).to_have_value("1855 1856 1882 1883", timeout=15000)
