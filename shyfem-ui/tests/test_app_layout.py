"""Tests for the sidebar layout structure."""

import pytest

from shyfem_ui.app import SIDEBAR_GROUPS, _build_sidebar_nav

pytest.importorskip("shiny_deckgl")


class TestSidebarGroups:
    def test_required_groups_present(self):
        """Required sidebar groups exist; extras are allowed (subset assertion)."""
        REQUIRED_GROUPS = {"Overview", "Simulate", "Analyze", "Manage"}
        actual_groups = {g["name"] for g in SIDEBAR_GROUPS}
        assert REQUIRED_GROUPS.issubset(actual_groups), (
            f"Missing required sidebar groups: {REQUIRED_GROUPS - actual_groups}"
        )

    def test_required_pages_present(self):
        """Required nav items exist; extras are allowed (subset assertion)."""
        REQUIRED_PAGES = {"Dashboard", "Run", "Visualize", "Admin"}
        all_pages = {
            item["value"]
            for group in SIDEBAR_GROUPS
            for item in group["items"]
        }
        assert REQUIRED_PAGES.issubset(all_pages), (
            f"Missing required nav pages: {REQUIRED_PAGES - all_pages}"
        )

    def test_group_names(self):
        names = [g["name"] for g in SIDEBAR_GROUPS]
        assert names == ["Overview", "Prepare", "Simulate", "Analyze", "Manage"]


class TestBuildSidebarNav:
    def test_returns_tag(self):
        result = _build_sidebar_nav()
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


def test_hamburger_button_in_topbar():
    """Topbar should contain a hamburger button for mobile."""
    from shyfem_ui.app import _build_ui
    from shyfem_ui.config import Config
    config = Config()
    html = str(_build_ui(config))
    assert "sf-hamburger" in html
    assert "bi-list" in html


def test_sidebar_backdrop_present():
    """Layout should contain a sidebar backdrop div for mobile overlay."""
    from shyfem_ui.app import _build_ui
    from shyfem_ui.config import Config
    config = Config()
    html = str(_build_ui(config))
    assert "sf-sidebar-backdrop" in html


class TestLandmarksAndKeyboard:
    """Accessibility: landmarks screen readers list, and a keyboard-usable menu."""

    def test_menu_is_a_labelled_navigation_landmark(self):
        html = str(_build_sidebar_nav())
        assert 'id="sf-sidebar" role="navigation" aria-label="Main"' in html

    def test_every_menu_item_is_a_focusable_button_with_key_activation(self):
        import re

        html = str(_build_sidebar_nav())
        items = re.findall(r'<div class="sf-nav-item(?: [^"]*)?"[^>]*>', html)
        assert items
        for tag in items:
            assert 'role="button"' in tag and 'tabindex="0"' in tag, tag
            assert "onkeydown=" in tag and "Enter" in tag, tag
        dashboard = [t for t in items if 'data-nav="Dashboard"' in t]
        assert dashboard and 'aria-current="page"' in dashboard[0]
        assert sum('aria-current="page"' in t for t in items) == 1

    def test_page_sidebars_are_named_form_landmarks(self):
        import re

        from shyfem_ui.pages import ibm, simulation

        for ui_fn, ns, label in (
            (ibm.ibm_ui, "ibm", "Trajectory controls"),
            (simulation.simulation_ui, "simulation", "Parameter file and quick settings"),
        ):
            html = ui_fn(ns).tagify().get_html_string()
            sidebar = re.findall(r'<div[^>]*class="sidebar"[^>]*>', html)
            assert len(sidebar) == 1, ns
            assert 'role="form"' in sidebar[0] and f'aria-label="{label}"' in sidebar[0], sidebar

    def test_empty_job_history_hides_the_grid_behind_the_note(self):
        from shyfem_ui.pages import run

        html = run.run_ui("run").tagify().get_html_string()
        assert ".sf-job-history:has(.sf-no-completed-jobs) .sf-job-history-grid" in html
        assert '<div class="sf-job-history-grid">' in html.replace("\n", "")
