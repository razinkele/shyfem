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
