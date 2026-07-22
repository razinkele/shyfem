"""Smoke tests for the About/Changelog/Feedback topbar module."""

from shiny import ui

from shyfem_ui.pages import about


def _render(tag) -> str:
    return str(ui.div(tag).tagify())


def test_about_topbar_has_dropdowns_and_feedback():
    html = _render(about.about_topbar_ui("about"))
    # Per-package menu entries (module-namespaced ids contain the base id).
    for input_id in (
        "show_about_core",
        "show_about_ui",
        "show_changelog_core",
        "show_changelog_ui",
        "show_feedback",
    ):
        assert input_id in html
    # Dropdown toggles with stable DOM ids for E2E.
    for toggle_id in ("sf-about-menu", "sf-changelog-menu"):
        assert toggle_id in html
    assert 'data-bs-toggle="dropdown"' in html
    # Icons and labels.
    for icon in ("bi-info-circle", "bi-journal-text", "bi-chat-dots"):
        assert icon in html
    for label in ("About", "Changelog", "SHYFEM UI", "Send feedback"):
        assert label in html


def test_feedback_form_has_expected_fields():
    html = _render(about._feedback_form())
    for field in ("fb_type", "fb_title", "fb_desc", "fb_submit", "fb_status"):
        assert field in html
