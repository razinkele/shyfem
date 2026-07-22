"""Smoke tests for the About/Changelog/Feedback topbar module."""

from shiny import ui

from shyfem_ui.pages import about


def _render(tag) -> str:
    return str(ui.div(tag).tagify())


def test_about_topbar_has_three_buttons():
    html = _render(about.about_topbar_ui("about"))
    # Module-namespaced ids still contain the base id.
    for input_id in ("show_about", "show_changelog", "show_feedback"):
        assert input_id in html
    # Icon classes and accessible labels.
    for icon in ("bi-info-circle", "bi-journal-text", "bi-chat-dots"):
        assert icon in html
    for label in ("About SHYFEM Workbench", "Changelog", "Send feedback"):
        assert label in html


def test_feedback_form_has_expected_fields():
    html = _render(about._feedback_form())
    for field in ("fb_type", "fb_title", "fb_desc", "fb_submit", "fb_status"):
        assert field in html
