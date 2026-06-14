"""About page -- renders README / CHANGELOG and hosts the feedback form.

Three tabs:
  * About      -- README.md rendered as markdown
  * Changelog  -- CHANGELOG.md rendered as markdown
  * Feedback   -- a bug-report / suggestion form (stored via FeedbackService)

The form submits server-side for logged-in users; anonymous / external
submission goes through the rate-limited ``POST /api/feedback`` endpoint.
"""

from __future__ import annotations

import logging

from shiny import module, reactive, render, ui

from shyfem_ui import __version__
from shyfem_ui.changelog import read_repo_markdown
from shyfem_ui.services.feedback_service import FeedbackService

logger = logging.getLogger(__name__)


def _feedback_form() -> ui.Tag:
    return ui.div(
        ui.markdown(
            "Found a bug or have an idea? Let us know — reports are stored for the "
            "maintainers. A contact email is optional (only if you'd like a reply)."
        ),
        ui.input_select("fb_type", "Type", {"bug": "Bug report", "suggestion": "Suggestion"}),
        ui.input_text("fb_title", "Title", placeholder="Short summary"),
        ui.input_text_area(
            "fb_desc", "Description", placeholder="What happened, or what you'd like", rows=5
        ),
        ui.input_select(
            "fb_severity",
            "Severity (optional)",
            {"": "—", "low": "Low", "medium": "Medium", "high": "High"},
            selected="",
        ),
        ui.input_text("fb_email", "Contact email (optional)", placeholder="you@example.org"),
        ui.input_action_button("fb_submit", "Submit feedback", class_="btn-primary mt-2"),
        ui.output_ui("fb_status"),
        class_="p-2",
        style="max-width: 640px;",
    )


@module.ui
def about_ui() -> ui.Tag:
    """About page UI -- tabbed README / Changelog / Feedback."""
    return ui.navset_card_tab(
        ui.nav_panel("About", ui.div(ui.output_ui("about_md"), class_="p-2")),
        ui.nav_panel("Changelog", ui.div(ui.output_ui("changelog_md"), class_="p-2")),
        ui.nav_panel("Feedback", _feedback_form()),
        title="About SHYFEM Workbench",
    )


@module.server
def about_server(input, output, session, config, current_user=None) -> None:
    """About page server -- render docs + handle feedback submission."""
    _submit_msg: reactive.Value[tuple[str, str] | None] = reactive.value(None)

    @render.ui
    def about_md():
        return ui.markdown(read_repo_markdown("README.md"))

    @render.ui
    def changelog_md():
        return ui.markdown(read_repo_markdown("CHANGELOG.md"))

    @reactive.effect
    @reactive.event(input.fb_submit)
    def _submit_feedback():
        try:
            rec = FeedbackService().create(
                feedback_type=input.fb_type(),
                title=input.fb_title(),
                description=input.fb_desc(),
                severity=(input.fb_severity() or None),
                contact_email=(input.fb_email() or None),
                page="About",
                app_version=__version__,
            )
        except ValueError as exc:
            _submit_msg.set(("danger", str(exc)))
            return
        except Exception:
            logger.exception("Feedback submission failed")
            _submit_msg.set(("danger", "Could not submit feedback. Please try again."))
            return
        _submit_msg.set(
            ("success", f"Thanks! Your {rec['feedback_type']} was recorded (#{rec['id']}).")
        )
        # Clear the fields so a second submission starts fresh.
        ui.update_select("fb_type", selected="bug")
        ui.update_text("fb_title", value="")
        ui.update_text_area("fb_desc", value="")
        ui.update_select("fb_severity", selected="")
        ui.update_text("fb_email", value="")

    @render.ui
    def fb_status():
        msg = _submit_msg.get()
        if not msg:
            return None
        level, text = msg
        return ui.div(text, class_=f"alert alert-{level} mt-2", role="status")
