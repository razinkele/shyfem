"""Smoke tests for the About page module."""

from shiny import ui

from shyfem_ui.pages import about


def _render(tag) -> str:
    # The page returns a NavSetCard; wrap as the app does (ui.div) and tagify
    # so we get rendered HTML rather than the object repr.
    return str(ui.div(tag).tagify())


def test_about_ui_has_tabs_and_feedback_form():
    html = _render(about.about_ui("about"))
    for label in ("About", "Changelog", "Feedback"):
        assert label in html
    # Feedback form fields (module-namespaced ids still contain the base id).
    for field in ("fb_type", "fb_title", "fb_desc", "fb_submit"):
        assert field in html
