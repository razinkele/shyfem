# SHYFEM UI Visual Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the generic Bootstrap/Shinyswatch UI with a custom ocean-themed design system featuring sidebar navigation, rich dashboard, and adaptive Plotly themes.

**Architecture:** CSS custom properties define the entire color/spacing system in one file. The Shiny `navset_tab` is replaced with a custom sidebar+content flex layout using JavaScript↔Shiny input binding for navigation. Plotly figures get a shared template module. No build tooling — pure CSS + Python.

**Tech Stack:** Shiny for Python, Bootstrap 5 (no Shinyswatch), CSS custom properties, Plotly, Google Fonts (Inter, JetBrains Mono)

**Design doc:** `docs/plans/2026-02-24-ui-overhaul-design.md`

---

### Task 1: Create CSS Design System

**Files:**
- Create: `shyfem_ui/www/css/shyfem.css`
- Test: Visual inspection (no unit test — pure CSS)

**Step 1: Create the CSS file**

Create `shyfem_ui/www/css/shyfem.css` with the full design system. This is the single source of truth for all visual styling.

The CSS must contain these sections in order:

1. **CSS Custom Properties (`:root`)** — All ocean palette colors from the design doc (light mode defaults)
2. **Dark mode overrides (`[data-bs-theme="dark"]`)** — Dark palette
3. **Base resets** — `html, body` background/color using variables, font-family Inter, smooth color transitions (300ms)
4. **Typography** — Headings use Inter 600, body Inter 400, `code/pre` use JetBrains Mono 13px
5. **Sidebar layout** — `.sf-layout` (flex row, 100vh), `.sf-sidebar` (240px fixed, ocean-deep bg, flex column), `.sf-sidebar-collapsed` (60px), `.sf-content` (flex-grow, sand bg, overflow-y auto, 24px padding)
6. **Sidebar navigation** — `.sf-nav-group-header` (11px uppercase, letter-spacing 0.05em, muted text), `.sf-nav-item` (flex row, icon+label, 40px height, ghost hover, cursor pointer), `.sf-nav-item.active` (left 3px ocean-light border, lighter bg), `.sf-sidebar-collapsed .sf-nav-label` (display none), `.sf-sidebar-collapsed .sf-nav-group-header` (display none)
7. **Top bar** — `.sf-topbar` (48px height, ocean-deep bg slightly lighter, flex row, justify between, align center, px-3)
8. **Cards** — Override `.card` (foam bg, 12px radius, ocean-tinted shadow, 1px border rgba, transition shadow 200ms), `.card:hover` (deeper shadow), `.sf-card-header` (border-bottom, flex between)
9. **Buttons** — Override `.btn-primary` (ocean-mid bg, 8px radius, 500 weight), `.btn-primary:hover` (ocean-deep), `.btn-outline-primary` (ocean-mid border), `.btn-success` (teal), `.btn-danger` (coral). Active press: `transform: scale(0.98)`
10. **Badges** — Override `.badge` (pill 999px radius, 11px, uppercase, 600 weight). `.bg-success` → teal, `.bg-danger` → coral, `.bg-primary` → ocean-mid, `.bg-info` → ocean-light, `.bg-warning` → amber, `.bg-secondary` → sand-dark with dark text
11. **Form inputs** — `.form-control` (8px radius, sand-dark border), `.form-control:focus` (ocean-tinted focus ring 3px rgba(26,107,138,0.15))
12. **Progress bars** — `.progress` (sand-dark track, 6px height, 999px radius), `.progress-bar` (gradient ocean-mid→teal, transition width 500ms)
13. **Loading skeleton** — `.sf-skeleton` (background shimmer gradient animation)
14. **Page transitions** — `.sf-page-enter` (opacity 0→1, 200ms ease-out via @keyframes)
15. **Status animations** — `.sf-pulse` (box-shadow pulse keyframes 2s infinite for running badges)
16. **Metric cards** — `.sf-metric-card` (flex row, icon left 48px circle bg, number 24px semibold, label 12px muted)
17. **Project cards** — `.sf-project-card` (inline-block, 200px wide, hover translateY -2px + shadow), `.sf-project-card.active` (2px ocean-light border)
18. **Activity timeline** — `.sf-timeline-item` (flex row, colored dot left, text right, relative timestamp muted)
19. **Scrollbar styling** — Thin custom scrollbar for sidebar (8px, ocean-deep track, ocean-mid thumb)
20. **Shiny busy indicator override** — `.recalculating` spinner color → ocean-mid

**Step 2: Commit**

```bash
git add shyfem_ui/www/css/shyfem.css
git commit -m "feat(ui): add ocean-themed CSS design system"
```

---

### Task 2: Create Plotly Theme Module

**Files:**
- Create: `shyfem_ui/plotly_theme.py`
- Test: `tests/test_plotly_theme.py`

**Step 1: Write the failing tests**

Create `tests/test_plotly_theme.py`:

```python
"""Tests for the custom Plotly theme module."""

from shyfem_ui.plotly_theme import (
    SHYFEM_CATEGORICAL_COLORS,
    SHYFEM_OCEAN_COLORSCALE,
    get_plotly_template,
)


class TestGetPlotlyTemplate:
    def test_returns_dict(self):
        result = get_plotly_template(dark=False)
        assert isinstance(result, dict)

    def test_light_has_white_plot_bg(self):
        t = get_plotly_template(dark=False)
        assert t["layout"]["plot_bgcolor"] == "#FFFFFF"

    def test_light_has_sand_paper_bg(self):
        t = get_plotly_template(dark=False)
        assert t["layout"]["paper_bgcolor"] == "#F5F0E8"

    def test_dark_has_dark_plot_bg(self):
        t = get_plotly_template(dark=True)
        assert t["layout"]["plot_bgcolor"] == "#1A2332"

    def test_dark_has_dark_paper_bg(self):
        t = get_plotly_template(dark=True)
        assert t["layout"]["paper_bgcolor"] == "#2A3545"

    def test_font_family_is_inter(self):
        t = get_plotly_template(dark=False)
        assert "Inter" in t["layout"]["font"]["family"]

    def test_colorway_set(self):
        t = get_plotly_template(dark=False)
        assert t["layout"]["colorway"] == SHYFEM_CATEGORICAL_COLORS

    def test_margins_tight(self):
        t = get_plotly_template(dark=False)
        m = t["layout"]["margin"]
        assert m["l"] == 60
        assert m["r"] == 20
        assert m["t"] == 40
        assert m["b"] == 50


class TestColorscale:
    def test_ocean_colorscale_has_entries(self):
        assert len(SHYFEM_OCEAN_COLORSCALE) >= 6

    def test_ocean_colorscale_starts_at_zero(self):
        assert SHYFEM_OCEAN_COLORSCALE[0][0] == 0.0

    def test_ocean_colorscale_ends_at_one(self):
        assert SHYFEM_OCEAN_COLORSCALE[-1][0] == 1.0


class TestCategoricalColors:
    def test_has_six_colors(self):
        assert len(SHYFEM_CATEGORICAL_COLORS) == 6

    def test_all_are_hex(self):
        for c in SHYFEM_CATEGORICAL_COLORS:
            assert c.startswith("#") and len(c) == 7
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_plotly_theme.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write the implementation**

Create `shyfem_ui/plotly_theme.py`:

```python
"""Custom Plotly theme for SHYFEM UI — ocean/environmental palette.

Provides light and dark templates matching the SHYFEM CSS design system.
Usage: fig.update_layout(template=get_plotly_template(dark=is_dark))
"""

SHYFEM_OCEAN_COLORSCALE = [
    [0.0, "#0B3D5B"],
    [0.2, "#1A6B8A"],
    [0.4, "#2D9CBA"],
    [0.6, "#3DB8A0"],
    [0.8, "#E6A641"],
    [1.0, "#E8725A"],
]

SHYFEM_CATEGORICAL_COLORS = [
    "#1A6B8A",
    "#3DB8A0",
    "#E8725A",
    "#E6A641",
    "#7B6CB5",
    "#4ECDC4",
]

_SHARED = {
    "font": {
        "family": "Inter, -apple-system, BlinkMacSystemFont, sans-serif",
        "size": 13,
    },
    "colorway": SHYFEM_CATEGORICAL_COLORS,
    "colorscale": {"sequential": SHYFEM_OCEAN_COLORSCALE},
    "margin": {"l": 60, "r": 20, "t": 40, "b": 50},
    "hoverlabel": {"font_size": 12},
    "modebar": {
        "orientation": "v",
        "bgcolor": "rgba(0,0,0,0)",
    },
}


def get_plotly_template(dark: bool = False) -> dict:
    """Return a Plotly layout template dict for the SHYFEM ocean theme.

    Args:
        dark: If True, return the dark-mode variant.

    Returns:
        Dict suitable for plotly fig.update_layout(template=...).
    """
    if dark:
        theme = {
            "paper_bgcolor": "#2A3545",
            "plot_bgcolor": "#1A2332",
            "xaxis": {
                "gridcolor": "rgba(255,255,255,0.08)",
                "zerolinecolor": "rgba(255,255,255,0.08)",
                "color": "#E0E8F0",
            },
            "yaxis": {
                "gridcolor": "rgba(255,255,255,0.08)",
                "zerolinecolor": "rgba(255,255,255,0.08)",
                "color": "#E0E8F0",
            },
            "title": {"font": {"color": "#2D9CBA", "size": 16}},
            "font": {"color": "#E0E8F0"},
        }
    else:
        theme = {
            "paper_bgcolor": "#F5F0E8",
            "plot_bgcolor": "#FFFFFF",
            "xaxis": {
                "gridcolor": "rgba(0,0,0,0.06)",
                "zerolinecolor": "rgba(0,0,0,0.06)",
                "color": "#2C3E50",
            },
            "yaxis": {
                "gridcolor": "rgba(0,0,0,0.06)",
                "zerolinecolor": "rgba(0,0,0,0.06)",
                "color": "#2C3E50",
            },
            "title": {"font": {"color": "#0B3D5B", "size": 16}},
            "font": {"color": "#2C3E50"},
        }

    layout = {**_SHARED, **theme}
    # Merge font dicts (shared base + theme-specific color)
    layout["font"] = {**_SHARED["font"], **theme.get("font", {})}

    return {"layout": layout}
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_plotly_theme.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add shyfem_ui/plotly_theme.py tests/test_plotly_theme.py
git commit -m "feat(ui): add Plotly ocean theme module with light/dark variants"
```

---

### Task 3: Rewrite App Layout — Sidebar Navigation

**Files:**
- Modify: `shyfem_ui/app.py` (lines 1-17 imports, 460-563 `_HEAD_EXTRAS` and `_build_ui`, 566-631 `_build_server`)
- Test: `tests/test_app_layout.py` (new)

This is the core architectural change. We replace `navset_tab` with a sidebar+content flex layout.

**Step 1: Write failing tests**

Create `tests/test_app_layout.py`:

```python
"""Tests for the sidebar layout structure."""

import pytest

from shyfem_ui.app import _build_sidebar_nav, SIDEBAR_GROUPS


class TestSidebarGroups:
    def test_has_five_groups(self):
        assert len(SIDEBAR_GROUPS) == 5

    def test_all_twelve_pages_present(self):
        all_pages = []
        for group in SIDEBAR_GROUPS:
            all_pages.extend(item["label"] for item in group["items"])
        assert len(all_pages) == 12

    def test_group_names(self):
        names = [g["name"] for g in SIDEBAR_GROUPS]
        assert names == ["Overview", "Prepare", "Simulate", "Analyze", "Manage"]


class TestBuildSidebarNav:
    def test_returns_tag(self):
        from shiny import ui

        result = _build_sidebar_nav()
        # Should return a ui.Tag or TagList (has tagify or __str__)
        assert result is not None
        html = str(result)
        assert "sf-sidebar" in html

    def test_contains_all_nav_items(self):
        html = str(_build_sidebar_nav())
        for group in SIDEBAR_GROUPS:
            for item in group["items"]:
                assert item["label"] in html, f"Missing nav item: {item['label']}"

    def test_contains_group_headers(self):
        html = str(_build_sidebar_nav())
        for group in SIDEBAR_GROUPS:
            assert group["name"] in html, f"Missing group header: {group['name']}"
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_app_layout.py -v`
Expected: FAIL with `ImportError`

**Step 3: Implement the sidebar layout**

Modify `shyfem_ui/app.py`:

**3a. Update imports** (top of file, line 14-15): Remove `import shinyswatch`. Add no new imports (Shiny's `ui` already imported).

**3b. Add SIDEBAR_GROUPS constant** (after line 38, before `_check_db_health`):

```python
SIDEBAR_GROUPS = [
    {
        "name": "Overview",
        "items": [
            {"label": "Dashboard", "icon": "bi-house", "value": "Dashboard"},
            {"label": "Tutorial", "icon": "bi-mortarboard", "value": "Tutorial"},
        ],
    },
    {
        "name": "Prepare",
        "items": [
            {"label": "Grid Prep", "icon": "bi-grid-3x3", "value": "Grid Prep"},
            {"label": "Partitioning", "icon": "bi-diagram-3", "value": "Partitioning"},
        ],
    },
    {
        "name": "Simulate",
        "items": [
            {"label": "Configuration", "icon": "bi-sliders", "value": "Simulation"},
            {"label": "Run", "icon": "bi-play-circle", "value": "Run"},
        ],
    },
    {
        "name": "Analyze",
        "items": [
            {"label": "Post-Process", "icon": "bi-gear", "value": "Post-Process"},
            {"label": "Visualize", "icon": "bi-graph-up", "value": "Visualize"},
            {"label": "Compare", "icon": "bi-layout-split", "value": "Compare"},
            {"label": "Ensemble", "icon": "bi-collection", "value": "Ensemble"},
        ],
    },
    {
        "name": "Manage",
        "items": [
            {"label": "Files", "icon": "bi-folder", "value": "Files"},
            {"label": "Admin", "icon": "bi-shield-lock", "value": "Admin"},
        ],
    },
]


def _build_sidebar_nav() -> ui.Tag:
    """Build the sidebar navigation HTML."""
    nav_items = []
    for group in SIDEBAR_GROUPS:
        nav_items.append(
            ui.div(
                ui.span(group["name"], class_="sf-nav-group-header"),
            )
        )
        for item in group["items"]:
            active_class = " active" if item["value"] == "Dashboard" else ""
            nav_items.append(
                ui.div(
                    ui.tags.i(class_=f"bi {item['icon']} sf-nav-icon"),
                    ui.span(item["label"], class_="sf-nav-label"),
                    class_=f"sf-nav-item{active_class}",
                    data_nav=item["value"],
                    onclick=f"shyfemNavTo('{item['value']}')",
                )
            )

    return ui.div(
        ui.div(*nav_items, class_="sf-nav-items"),
        ui.div(
            ui.tags.i(class_="bi bi-chevron-bar-left sf-nav-icon"),
            ui.span("Collapse", class_="sf-nav-label"),
            class_="sf-nav-item sf-collapse-btn",
            onclick="shyfemToggleSidebar()",
        ),
        class_="sf-sidebar",
        id="sf-sidebar",
    )
```

**3c. Replace `_HEAD_EXTRAS`** (lines 460-518). Keep existing WebSocket reconnection and meta tags. Add:
- Google Fonts link for Inter and JetBrains Mono
- Link to `shyfem.css`
- Updated dark mode JS that also sends `Shiny.setInputValue("_dark_mode", isDark)`
- New sidebar navigation JS (`shyfemNavTo`, `shyfemToggleSidebar`)
- Sidebar collapse state from localStorage

The full replacement for `_HEAD_EXTRAS`:

```python
_HEAD_EXTRAS = ui.TagList(
    # Bootstrap 5 (standalone, no Shinyswatch)
    ui.tags.link(
        rel="stylesheet",
        href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    ),
    ui.tags.script(
        src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    ),
    # Bootstrap Icons
    ui.tags.link(
        rel="stylesheet",
        href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    ),
    # Google Fonts
    ui.tags.link(rel="preconnect", href="https://fonts.googleapis.com"),
    ui.tags.link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
    ui.tags.link(
        rel="stylesheet",
        href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap",
    ),
    # Custom SHYFEM theme
    ui.tags.link(rel="stylesheet", href="css/shyfem.css"),
    # WebSocket reconnection with exponential backoff
    ui.tags.script("""
(function() {
  var maxRetries = 5, retryDelay = 2000;
  var origWS = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    var ws = protocols ? new origWS(url, protocols) : new origWS(url);
    var retries = 0;
    ws.addEventListener('close', function(e) {
      if (e.code !== 1000 && e.code !== 1001 && retries < maxRetries) {
        retries++;
        var delay = retryDelay * retries;
        console.log('[SHYFEM] WebSocket closed (' + e.code + '), reconnecting in ' + delay + 'ms...');
        setTimeout(function() { window.location.reload(); }, delay);
      }
    });
    return ws;
  };
  window.WebSocket.prototype = origWS.prototype;
})();
"""),
    # Dark mode + Sidebar + Navigation JS
    ui.tags.script("""
document.addEventListener('DOMContentLoaded', function() {
  // Dark mode init
  var saved = localStorage.getItem('shyfem-dark-mode');
  if (saved === 'true') {
    document.documentElement.setAttribute('data-bs-theme', 'dark');
  }
  // Sidebar collapse init
  var collapsed = localStorage.getItem('shyfem-sidebar-collapsed');
  if (collapsed === 'true') {
    var sb = document.getElementById('sf-sidebar');
    if (sb) sb.classList.add('sf-sidebar-collapsed');
  }
});

function shyfemToggleDark() {
  var html = document.documentElement;
  var isDark = html.getAttribute('data-bs-theme') === 'dark';
  html.setAttribute('data-bs-theme', isDark ? 'light' : 'dark');
  localStorage.setItem('shyfem-dark-mode', String(!isDark));
  var btn = document.getElementById('dark-mode-toggle');
  if (btn) {
    var icon = btn.querySelector('i');
    if (icon) icon.className = isDark ? 'bi bi-moon' : 'bi bi-sun';
  }
  // Notify Shiny so Plotly themes can react
  if (window.Shiny && Shiny.setInputValue) {
    Shiny.setInputValue('_dark_mode', !isDark);
  }
}

function shyfemNavTo(name) {
  // Update active class
  document.querySelectorAll('.sf-nav-item').forEach(function(el) {
    el.classList.remove('active');
  });
  var clicked = document.querySelector('.sf-nav-item[data-nav=\"' + name + '\"]');
  if (clicked) clicked.classList.add('active');

  // Tell Shiny to switch page
  if (window.Shiny && Shiny.setInputValue) {
    Shiny.setInputValue('_active_nav', name, {priority: 'event'});
  }
}

function shyfemToggleSidebar() {
  var sb = document.getElementById('sf-sidebar');
  if (!sb) return;
  sb.classList.toggle('sf-sidebar-collapsed');
  var isCollapsed = sb.classList.contains('sf-sidebar-collapsed');
  localStorage.setItem('shyfem-sidebar-collapsed', String(isCollapsed));
  // Update the collapse button icon
  var icon = sb.querySelector('.sf-collapse-btn i');
  if (icon) {
    icon.className = isCollapsed ? 'bi bi-chevron-bar-right sf-nav-icon' : 'bi bi-chevron-bar-left sf-nav-icon';
  }
}
"""),
    # Meta tags
    ui.tags.meta(
        name="description",
        content="SHYFEM Workbench — finite element hydrodynamic simulation interface",
    ),
    ui.tags.meta(name="viewport", content="width=device-width, initial-scale=1"),
    # Inline SVG favicon (water wave icon)
    ui.tags.link(
        rel="icon",
        type="image/svg+xml",
        href="data:image/svg+xml,"
        "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
        "%3Ctext y='28' font-size='28'%3E%F0%9F%8C%8A%3C/text%3E%3C/svg%3E",
    ),
)
```

**3d. Replace `_build_ui`** (lines 521-563):

```python
def _build_ui(config: Config) -> ui.Tag:
    """Build the application UI with sidebar navigation."""
    sidebar = _build_sidebar_nav()

    # Top bar
    topbar = ui.div(
        ui.div(
            ui.tags.i(class_="bi bi-tsunami me-2", style="font-size:1.3rem"),
            ui.span("SHYFEM Workbench", style="font-weight:600;font-size:1rem"),
            class_="d-flex align-items-center",
        ),
        ui.div(
            ui.tags.button(
                ui.tags.i(class_="bi bi-moon"),
                id="dark-mode-toggle",
                class_="btn btn-sm sf-topbar-btn me-2",
                onclick="shyfemToggleDark()",
                title="Toggle dark mode",
            ),
            ui.tags.a(
                ui.tags.i(class_="bi bi-box-arrow-right"),
                " Logout",
                href="/logout",
                class_="btn btn-sm sf-topbar-btn",
                id="logout-btn",
            ),
            class_="d-flex align-items-center",
        ),
        class_="sf-topbar",
    )

    # Content panels — one div per page, toggled by JS/reactive
    content_panels = ui.div(
        ui.div(home.home_ui("home"), id="sf-page-Dashboard", class_="sf-page active"),
        ui.div(tutorial.tutorial_ui("tutorial"), id="sf-page-Tutorial", class_="sf-page"),
        ui.div(grid_prep.grid_prep_ui("grid_prep"), id="sf-page-Grid Prep", class_="sf-page"),
        ui.div(partitioning.partitioning_ui("partitioning"), id="sf-page-Partitioning", class_="sf-page"),
        ui.div(simulation.simulation_ui("simulation"), id="sf-page-Simulation", class_="sf-page"),
        ui.div(run.run_ui("run"), id="sf-page-Run", class_="sf-page"),
        ui.div(postprocess.postprocess_ui("postprocess"), id="sf-page-Post-Process", class_="sf-page"),
        ui.div(visualize.visualize_ui("visualize"), id="sf-page-Visualize", class_="sf-page"),
        ui.div(compare.compare_ui("compare"), id="sf-page-Compare", class_="sf-page"),
        ui.div(ensemble.ensemble_ui("ensemble"), id="sf-page-Ensemble", class_="sf-page"),
        ui.div(files.files_ui("files"), id="sf-page-Files", class_="sf-page"),
        ui.div(admin.admin_ui("admin"), id="sf-page-Admin", class_="sf-page"),
        class_="sf-content",
    )

    return ui.page_fillable(
        ui.head_content(_HEAD_EXTRAS),
        ui.busy_indicators.use(spinners=True, pulse=True),
        topbar,
        ui.div(
            sidebar,
            content_panels,
            class_="sf-layout",
        ),
        title="SHYFEM Workbench",
    )
```

Note: the `theme=` parameter is removed (no more Shinyswatch theme). Bootstrap 5 is loaded via CDN in `_HEAD_EXTRAS`.

**3e. Add page-switching JavaScript to the `_HEAD_EXTRAS` script block** (already included in 3c above). The `shyfemNavTo` function handles CSS class toggling for `.sf-page.active`. Add this to the end of the script block from 3c:

```javascript
// Page visibility — show/hide content panels
function shyfemNavTo(name) {
  // Update active sidebar item
  document.querySelectorAll('.sf-nav-item').forEach(function(el) {
    el.classList.remove('active');
  });
  var clicked = document.querySelector('.sf-nav-item[data-nav="' + name + '"]');
  if (clicked) clicked.classList.add('active');

  // Show/hide pages
  document.querySelectorAll('.sf-page').forEach(function(el) {
    el.classList.remove('active');
  });
  var page = document.getElementById('sf-page-' + name);
  if (page) {
    page.classList.add('active');
    page.classList.add('sf-page-enter');
    setTimeout(function() { page.classList.remove('sf-page-enter'); }, 200);
  }

  // Notify Shiny
  if (window.Shiny && Shiny.setInputValue) {
    Shiny.setInputValue('_active_nav', name, {priority: 'event'});
  }
}
```

(This replaces the simpler `shyfemNavTo` already in the 3c script — merge them into one.)

**3f. Update `_build_server`** (lines 566-576): Add a reactive handler for `input._active_nav()` so the `nav_to` callback works for cross-page navigation (e.g., tutorial → grid prep):

After `def nav_to(tab_name: str):` on line 578, add client-side navigation:

```python
    def nav_to(tab_name: str):
        """Navigate to a tab by injecting JS to call shyfemNavTo."""
        import shiny

        session.send_custom_message("shyfem_nav", {"tab": tab_name})
```

And add a corresponding `ui.tags.script` in `_HEAD_EXTRAS` to listen:

```javascript
// Server-initiated navigation
Shiny.addCustomMessageHandler('shyfem_nav', function(msg) {
  shyfemNavTo(msg.tab);
});
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_app_layout.py -v`
Expected: all PASS

**Step 5: Run existing unit tests to check for regressions**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --ignore-glob='*playwright*' -x -q`
Expected: all PASS (or identify failures from removing shinyswatch)

**Step 6: Commit**

```bash
git add shyfem_ui/app.py tests/test_app_layout.py
git commit -m "feat(ui): replace navset_tab with sidebar navigation layout"
```

---

### Task 4: Redesign Dashboard

**Files:**
- Modify: `shyfem_ui/pages/home.py` (lines 86-167 `home_ui` function)
- Test: Existing tests + visual inspection

**Step 1: Run existing home tests to establish baseline**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -k "home" -v --ignore-glob='*playwright*'`
Expected: all PASS

**Step 2: Rewrite `home_ui()`**

Replace lines 86-167 of `shyfem_ui/pages/home.py` with the new dashboard layout:

```python
@module.ui
def home_ui():
    """Dashboard page UI — rich metrics, project cards, activity timeline."""
    return ui.div(
        # Welcome header
        ui.div(
            ui.h4("Welcome to SHYFEM Workbench", class_="mb-1"),
            ui.p(
                "Finite Element Hydrodynamic Model — Web Interface",
                class_="text-muted mb-0",
                style="font-size:0.9rem",
            ),
            class_="mb-4",
        ),
        # Main two-column layout
        ui.row(
            # Left column (8/12) — metrics + projects
            ui.column(
                8,
                # Metric cards row
                ui.row(
                    ui.column(
                        4,
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.tags.i(
                                        class_="bi bi-folder",
                                        style="font-size:1.4rem",
                                    ),
                                    class_="sf-metric-icon",
                                    style="background:rgba(26,107,138,0.1);color:var(--sf-ocean-mid)",
                                ),
                                ui.div(
                                    ui.output_ui("project_count"),
                                    ui.span("Projects", class_="sf-metric-label"),
                                    class_="sf-metric-text",
                                ),
                                class_="d-flex align-items-center gap-3",
                            ),
                            class_="card p-3",
                        ),
                    ),
                    ui.column(
                        4,
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.tags.i(
                                        class_="bi bi-activity",
                                        style="font-size:1.4rem",
                                    ),
                                    class_="sf-metric-icon",
                                    style="background:rgba(61,184,160,0.1);color:var(--sf-teal)",
                                ),
                                ui.div(
                                    ui.output_ui("active_job_count"),
                                    ui.span("Active Jobs", class_="sf-metric-label"),
                                    class_="sf-metric-text",
                                ),
                                class_="d-flex align-items-center gap-3",
                            ),
                            class_="card p-3",
                        ),
                    ),
                    ui.column(
                        4,
                        ui.div(
                            ui.div(
                                ui.div(
                                    ui.tags.i(
                                        class_="bi bi-cpu",
                                        style="font-size:1.4rem",
                                    ),
                                    class_="sf-metric-icon",
                                    style="background:rgba(61,184,160,0.1);color:var(--sf-teal)",
                                ),
                                ui.div(
                                    ui.output_ui("system_health_count"),
                                    ui.span("Tools Ready", class_="sf-metric-label"),
                                    class_="sf-metric-text",
                                ),
                                class_="d-flex align-items-center gap-3",
                            ),
                            class_="card p-3",
                        ),
                    ),
                    class_="mb-3",
                ),
                # Projects section
                ui.div(
                    ui.div(
                        ui.h5("Projects", class_="mb-0"),
                        class_="sf-card-header",
                    ),
                    ui.output_ui("projects_list"),
                    class_="card p-3",
                ),
            ),
            # Right column (4/12) — activity + quick start
            ui.column(
                4,
                # Recent activity
                ui.div(
                    ui.div(
                        ui.h5("Recent Activity", class_="mb-0"),
                        ui.output_ui("show_all_toggle_ui"),
                        class_="sf-card-header",
                    ),
                    ui.output_ui("recent_jobs"),
                    class_="card p-3 mb-3",
                ),
                # Quick start
                ui.div(
                    ui.div(
                        ui.h5("Quick Start", class_="mb-0"),
                        class_="sf-card-header",
                    ),
                    ui.input_action_button(
                        "new_project_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-plus-lg me-2"), "New Project"),
                        class_="btn-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "open_project_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-folder2-open me-2"), "Open Project"),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "import_grid_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-upload me-2"), "Import Grid"),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.input_action_button(
                        "import_project_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-box-arrow-in-down me-2"), "Import Project"),
                        class_="btn-outline-primary w-100 mb-2",
                    ),
                    ui.hr(),
                    ui.input_action_button(
                        "tutorial_btn",
                        ui.TagList(ui.tags.i(class_="bi bi-mortarboard me-2"), "Mar Menor Tutorial"),
                        class_="btn-success w-100",
                    ),
                    class_="card p-3",
                ),
            ),
        ),
    )
```

**Step 3: Add metric render functions to `home_server`**

In `home_server()` (after the existing `system_status` render), add:

```python
    @render.ui
    def project_count():
        count = len(projects.get())
        return ui.span(str(count), class_="sf-metric-number")

    @render.ui
    def active_job_count():
        jobs = recent_jobs_list.get()
        active = sum(1 for j in jobs if j.status in (JobStatus.RUNNING, JobStatus.QUEUED))
        pulse = " sf-pulse" if active > 0 else ""
        return ui.span(str(active), class_=f"sf-metric-number{pulse}")

    @render.ui
    def system_health_count():
        from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

        wrapper = ShyfemWrapper(config.shyfem_dir)
        tools = ["shypre", "shybas", "shyparts", "shyfem", "shyelab", "shyplot"]
        available = sum(1 for t in tools if wrapper.check_available(t))
        color = "var(--sf-teal)" if available == len(tools) else "var(--sf-coral)"
        return ui.span(
            f"{available}/{len(tools)}",
            class_="sf-metric-number",
            style=f"color:{color}",
        )
```

**Step 4: Re-run home tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -k "home" -v --ignore-glob='*playwright*'`
Expected: all PASS. Note: if any test asserts on specific HTML structure from the old `home_ui`, update the assertion.

**Step 5: Commit**

```bash
git add shyfem_ui/pages/home.py
git commit -m "feat(ui): redesign dashboard with metric cards, activity timeline, quick start"
```

---

### Task 5: Apply Plotly Theme to All Figures

**Files:**
- Modify: `shyfem_ui/components/grid_map.py` (lines 90, 106)
- Modify: `shyfem_ui/components/timeseries.py` (lines 147, 166, 192, 194)
- Modify: `shyfem_ui/pages/visualize.py` (all `go.Figure()` calls)
- Modify: `shyfem_ui/pages/run.py` (lines 787, 812, 848)
- Modify: `shyfem_ui/pages/compare.py` (lines 359, 373)
- Modify: `shyfem_ui/pages/partitioning.py` (lines 287, 303, 322)
- Modify: `shyfem_ui/pages/ensemble.py` (lines 726, 742, 930, 964)

**Approach:** The simplest integration is to set the Plotly default template globally at app startup, rather than modifying all 42 figure calls individually.

**Step 1: Write a test for global template registration**

Add to `tests/test_plotly_theme.py`:

```python
class TestRegisterTemplate:
    def test_register_sets_default(self):
        from shyfem_ui.plotly_theme import register_shyfem_template

        register_shyfem_template(dark=False)

        import plotly.io as pio

        assert pio.templates.default == "shyfem"
        assert "shyfem" in pio.templates

    def test_register_dark_sets_default(self):
        from shyfem_ui.plotly_theme import register_shyfem_template

        register_shyfem_template(dark=True)

        import plotly.io as pio

        assert pio.templates.default == "shyfem"
```

**Step 2: Run to verify fails**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_plotly_theme.py::TestRegisterTemplate -v`
Expected: FAIL with `ImportError`

**Step 3: Add `register_shyfem_template` to `plotly_theme.py`**

Append to `shyfem_ui/plotly_theme.py`:

```python
def register_shyfem_template(dark: bool = False) -> None:
    """Register the SHYFEM template as the Plotly default.

    Call once at app startup. All subsequent go.Figure() calls
    will use this template automatically.

    Args:
        dark: If True, register the dark-mode variant.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    template_dict = get_plotly_template(dark=dark)
    pio.templates["shyfem"] = go.layout.Template(layout=template_dict["layout"])
    pio.templates.default = "shyfem"
```

**Step 4: Run tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_plotly_theme.py -v`
Expected: all PASS

**Step 5: Call `register_shyfem_template` at app startup**

In `shyfem_ui/app.py`, in `create_app()` (after line 72 `init_db()`), add:

```python
    # Register Plotly theme
    from shyfem_ui.plotly_theme import register_shyfem_template

    register_shyfem_template(dark=False)
```

**Step 6: Add dark-mode reactive re-registration in `_build_server`**

In `_build_server()`, after the session cleanup setup, add:

```python
    @reactive.effect
    @reactive.event(input._dark_mode)
    def _update_plotly_theme():
        from shyfem_ui.plotly_theme import register_shyfem_template

        is_dark = input._dark_mode()
        register_shyfem_template(dark=bool(is_dark))
```

**Step 7: Update `build_mesh_figure` default wireframe color**

In `shyfem_ui/components/grid_map.py`, line 114, change the wireframe color from `"#4a90d9"` to the ocean-light color that will come from the template. Since the template handles backgrounds, just update the hardcoded mesh line color:

```python
line=dict(color="#2D9CBA", width=0.5),  # --sf-ocean-light
```

**Step 8: Commit**

```bash
git add shyfem_ui/plotly_theme.py shyfem_ui/app.py shyfem_ui/components/grid_map.py tests/test_plotly_theme.py
git commit -m "feat(ui): register ocean Plotly theme globally, add dark-mode reactivity"
```

---

### Task 6: Update E2E Test Selectors

**Files:**
- Modify: `tests/test_playwright_navigation.py`
- Modify: `tests/test_playwright_dashboard.py`
- Modify: `tests/test_playwright_new_tabs.py`
- Modify: `tests/test_playwright_auth.py`
- Modify: `tests/test_playwright_pages.py`
- Modify: `tests/test_playwright_workflows.py`
- Modify: `tests/test_playwright_interactions.py`
- Modify: `tests/test_playwright_active_project.py`

**Step 1: Update the `_TAB` selector in all 8 files**

The old selector:
```python
_TAB = "#main_navbar > li > a[data-value='{name}']"
```

The new selector (sidebar nav items use `data-nav` attribute):
```python
_TAB = ".sf-nav-item[data-nav='{name}']"
```

Replace `_TAB` in all 8 files.

**Step 2: Update `test_playwright_navigation.py` specific assertions**

- `test_navbar_visible`: Change `pw_page.locator("#main_navbar")` → `pw_page.locator("#sf-sidebar")`
- `test_all_tabs_present`: Keep logic, new selector works
- `test_dashboard_is_default_tab`: Change active check from `aria-selected` to class check:
  ```python
  assert "active" in (tab.get_attribute("class") or "")
  ```
- `test_switch_to_tab`: Same active class check (remove `aria-selected` fallback)
- `test_rapid_tab_switching`: Same logic, new selector
- `test_page_does_not_crash_on_navigation`: Same logic, new selector
- `test_main_navbar_visible` (in auth tests): Change `#main_navbar` → `#sf-sidebar`

**Step 3: Update `TAB_NAMES` if needed**

The sidebar renames "Simulation" to display as "Configuration" but the `data-nav` value remains `"Simulation"`. So `TAB_NAMES` stays the same. Verify all `data-nav` values match the existing tab names.

**Step 4: Run E2E tests**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_navigation.py -v --timeout=60`

Note: E2E tests require the app to be running. If they can't run in CI, verify locally.

**Step 5: Commit**

```bash
git add tests/test_playwright_*.py
git commit -m "test(ui): update E2E selectors for sidebar navigation"
```

---

### Task 7: Write the CSS File (Full Implementation)

**Files:**
- Create: `shyfem_ui/www/css/shyfem.css`

This is the actual CSS content from Task 1, written as its own task because it's the largest single file.

**Step 1: Create the file**

Create `shyfem_ui/www/css/shyfem.css` with the full design system. The CSS must implement every section from the design doc:

- `:root` variables (light mode ocean palette)
- `[data-bs-theme="dark"]` overrides (dark palette)
- Base `html, body` resets (font-family, bg, color, transitions)
- `.sf-layout` (display flex, height calc(100vh - 48px))
- `.sf-topbar` (height 48px, bg, flex, z-index 1000)
- `.sf-topbar-btn` (ghost button style for topbar icons)
- `.sf-sidebar` (width 240px, bg ocean-deep, flex-shrink 0, transition width 250ms, overflow hidden, flex column, justify between)
- `.sf-sidebar-collapsed` (width 60px)
- `.sf-nav-items` (flex-grow, overflow-y auto, padding 12px 0)
- `.sf-nav-group-header` (11px uppercase, letter-spacing 0.05em, padding, color rgba white 0.5)
- `.sf-nav-item` (display flex, align center, padding, cursor pointer, transition bg 150ms, color white, gap 12px, margin 2px 8px, border-radius 6px)
- `.sf-nav-item:hover` (bg rgba white 0.08)
- `.sf-nav-item.active` (border-left 3px ocean-light, bg rgba white 0.1)
- `.sf-nav-icon` (width 20px, text-align center, flex-shrink 0)
- `.sf-nav-label` (white-space nowrap, overflow hidden)
- `.sf-sidebar-collapsed .sf-nav-label, .sf-sidebar-collapsed .sf-nav-group-header` (display none)
- `.sf-sidebar-collapsed .sf-nav-item` (justify-content center, padding-left/right adjusted)
- `.sf-collapse-btn` (border-top rgba white 0.1, margin-top auto)
- `.sf-content` (flex-grow 1, bg var(--sf-sand), padding 24px, overflow-y auto)
- `.sf-page` (display none)
- `.sf-page.active` (display block)
- `.sf-page-enter` (animation sfPageEnter 200ms ease-out)
- `@keyframes sfPageEnter` (from opacity 0 translateY 8px, to opacity 1 translateY 0)
- `.card` override (bg var(--sf-foam), border-radius 12px, border 1px solid rgba, box-shadow ocean-tinted, transition shadow 200ms)
- `.card:hover` (box-shadow deeper)
- `.sf-card-header` (display flex, justify-content space-between, align-items center, padding-bottom 12px, margin-bottom 12px, border-bottom 1px solid rgba)
- `.btn` override (border-radius 8px, font-weight 500, transition 150ms)
- `.btn:active` (transform scale 0.98)
- `.btn-primary` (bg var(--sf-ocean-mid), border-color var(--sf-ocean-mid))
- `.btn-primary:hover` (bg var(--sf-ocean-deep))
- `.btn-outline-primary` (color var(--sf-ocean-mid), border-color var(--sf-ocean-mid))
- `.btn-outline-primary:hover` (bg var(--sf-ocean-mid), color white)
- `.btn-success` (bg var(--sf-teal), border-color var(--sf-teal))
- `.btn-danger` (bg var(--sf-coral), border-color var(--sf-coral))
- `.badge` (border-radius 999px, font-size 11px, text-transform uppercase, font-weight 600, padding 2px 10px)
- `.bg-success` (bg var(--sf-teal) !important)
- `.bg-danger` (bg var(--sf-coral) !important)
- `.bg-primary` (bg var(--sf-ocean-mid) !important)
- `.bg-info` (bg var(--sf-ocean-light) !important)
- `.bg-warning` (bg var(--sf-amber) !important, color var(--sf-text) !important)
- `.bg-secondary` (bg var(--sf-sand-dark) !important, color var(--sf-text) !important)
- `.form-control` (border-radius 8px, border-color var(--sf-sand-dark), bg var(--sf-foam), color var(--sf-text))
- `.form-control:focus` (box-shadow 0 0 0 3px rgba(26,107,138,0.15), border-color var(--sf-ocean-light))
- `.form-select` (same as form-control overrides)
- `.progress` (height 6px, border-radius 999px, bg var(--sf-sand-dark))
- `.progress-bar` (background linear-gradient 90deg ocean-mid to teal, transition width 500ms ease)
- `.sf-skeleton` (bg var(--sf-sand-dark), border-radius 8px, animation sfShimmer 1.5s infinite)
- `@keyframes sfShimmer` (background-position -200% to 200%)
- `.sf-pulse` (animation sfPulse 2s infinite)
- `@keyframes sfPulse` (box-shadow pulse on ocean-mid rgba)
- `.sf-metric-icon` (width 48px, height 48px, border-radius 12px, display flex, align-items center, justify-content center)
- `.sf-metric-number` (font-size 24px, font-weight 600, line-height 1.2)
- `.sf-metric-label` (font-size 12px, color var(--sf-text-muted), display block)
- `.sf-metric-text` (display flex, flex-direction column)
- `.sf-project-card` (display inline-block, width 200px, transition transform 200ms, cursor pointer)
- `.sf-project-card:hover` (transform translateY(-2px))
- `.sf-project-card.active` (border 2px solid var(--sf-ocean-light))
- `.sf-timeline-item` (display flex, gap 12px, padding 8px 0, font-size 13px)
- `.sf-timeline-dot` (width 8px, height 8px, border-radius 50%, flex-shrink 0, margin-top 6px)
- Custom scrollbar for `.sf-sidebar` (::-webkit-scrollbar 8px, thumb ocean-mid rounded, track transparent)
- `.recalculating` override (opacity 0.7 — use Shiny's pulse/spinner but override color)
- Dark mode specifics: `.card` in dark mode gets different border

**Step 2: Verify the CSS loads**

Start the app locally and confirm:
1. Sand background visible
2. Sidebar renders with ocean-deep background
3. Cards have rounded corners and ocean-tinted shadows
4. Dark mode toggle works (colors transition smoothly)

**Step 3: Commit**

```bash
git add shyfem_ui/www/css/shyfem.css
git commit -m "feat(ui): add complete ocean-themed CSS design system"
```

---

### Task 8: Integration Verification

**Step 1: Run all unit tests**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest --ignore-glob='*playwright*' -x -q
```

Expected: 1004+ tests pass

**Step 2: Start the app and verify visually**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m shyfem_ui.app
```

Verify:
- [ ] Sidebar renders with 5 groups, all 12 pages accessible
- [ ] Sidebar collapse/expand works, state persists on reload
- [ ] Dashboard shows metric cards, project cards, activity timeline
- [ ] Dark mode toggle switches all colors including Plotly plots
- [ ] Page transitions have subtle fade-in animation
- [ ] Cards have 12px radius, ocean-tinted shadows
- [ ] Buttons use ocean color palette
- [ ] Status badges are pill-shaped with correct colors
- [ ] Progress bars show gradient fill
- [ ] Form inputs have ocean focus ring
- [ ] Grid/mesh visualizations use ocean wireframe color
- [ ] No console JS errors
- [ ] No broken layout on window resize

**Step 3: Run E2E tests if available**

```bash
cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_navigation.py -v
```

**Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(ui): integration fixes from visual testing"
```

---

## Task Dependency Order

```
Task 7 (CSS) ─────────────────────────────┐
Task 2 (Plotly theme) ───┐                 │
                         ├─ Task 5 (apply) │
                         │                 │
Task 3 (sidebar layout) ─┤                 ├─ Task 8 (verify)
                         │                 │
Task 4 (dashboard) ──────┘                 │
Task 6 (E2E tests) ───────────────────────┘
```

**Parallelizable:** Tasks 2, 3, 4, 7 can be done in parallel (no dependencies between them). Task 5 depends on Task 2. Task 6 depends on Task 3. Task 8 depends on all.

**Recommended execution order:** 7 → 2 → 3 → 4 → 5 → 6 → 8
