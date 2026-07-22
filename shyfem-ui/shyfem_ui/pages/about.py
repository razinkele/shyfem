"""About / Changelog / Feedback -- topbar dropdowns + button that open modals.

Rendered in the top bar (left of the theme toggle):
  * About ▾      -- SHYFEM (repo README.md) / SHYFEM UI (shyfem-ui/README.md)
  * Changelog ▾  -- SHYFEM / SHYFEM UI views of the shared CHANGELOG.md,
                    split by section label (``[shyfem-ui X.Y.Z]`` vs core)
  * Feedback     -- a bug-report / suggestion form (stored via FeedbackService)

The form submits server-side for logged-in users; anonymous / external
submission goes through the rate-limited ``POST /api/feedback`` endpoint.

Modal content is built at show-time (plain ``ui.markdown``, no output_ui),
so nothing here depends on hidden-output scheduling. Inputs created inside
the modals are namespaced automatically: effects run under the module's
session context, which activates the module namespace for UI creation.
"""

from __future__ import annotations

import logging

from shiny import module, reactive, render, ui

from shyfem_ui import __version__
from shyfem_ui.changelog import core_version, filter_changelog, read_repo_markdown
from shyfem_ui.services.feedback_service import FeedbackService

logger = logging.getLogger(__name__)

# Scroll long markdown inside the modal body instead of the whole dialog.
_SCROLL_STYLE = "max-height: 70vh; overflow-y: auto;"


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
    )


def _topbar_button(input_id: str, icon: str, label: str) -> ui.Tag:
    """A compact icon-only topbar action button with a tooltip/aria label."""
    return ui.input_action_button(
        input_id,
        None,
        icon=ui.tags.i(class_=f"bi {icon}"),
        class_="btn btn-sm sf-topbar-btn me-2",
        title=label,
        aria_label=label,
    )


def _menu_item(input_id: str, label: str) -> ui.Tag:
    """A dropdown-menu entry that fires a Shiny action input.

    ``dropdown-item`` is defined after ``.btn`` in Bootstrap's CSS, so it
    wins the text-align/border conflict with the action-button classes.
    """
    return ui.input_action_button(input_id, label, class_="dropdown-item")


def _topbar_dropdown(toggle_id: str, icon: str, label: str, *items: ui.Tag) -> ui.Tag:
    """A topbar Bootstrap dropdown. ``toggle_id`` is a raw DOM id (module
    instances of this UI exist once per app), used by E2E selectors."""
    return ui.tags.div(
        ui.tags.button(
            ui.tags.i(class_=f"bi {icon} me-1"),
            label,
            type="button",
            id=toggle_id,
            class_="btn btn-sm sf-topbar-btn dropdown-toggle me-2",
            **{"data-bs-toggle": "dropdown", "aria-expanded": "false"},
        ),
        ui.tags.ul(
            *[ui.tags.li(item) for item in items],
            class_="dropdown-menu dropdown-menu-end",
        ),
        class_="dropdown d-inline-block",
    )


@module.ui
def about_topbar_ui() -> ui.Tag:
    """Topbar cluster: About ▾ / Changelog ▾ dropdowns + Feedback button."""
    return ui.span(
        _topbar_dropdown(
            "sf-about-menu",
            "bi-info-circle",
            "About",
            _menu_item("show_about_core", "SHYFEM"),
            _menu_item("show_about_ui", "SHYFEM UI"),
        ),
        _topbar_dropdown(
            "sf-changelog-menu",
            "bi-journal-text",
            "Changelog",
            _menu_item("show_changelog_core", "SHYFEM"),
            _menu_item("show_changelog_ui", "SHYFEM UI"),
        ),
        _topbar_button("show_feedback", "bi-chat-dots", "Send feedback"),
        class_="d-inline-flex align-items-center",
    )


def _markdown_modal(md: str, title: str) -> None:
    ui.modal_show(
        ui.modal(
            ui.div(ui.markdown(md), style=_SCROLL_STYLE),
            title=title,
            size="xl",
            easy_close=True,
            footer=ui.modal_button("Close"),
        )
    )


@module.server
def about_server(input, output, session, config, current_user=None) -> None:
    """Open the About / Changelog / Feedback modals + handle feedback submission."""
    _submit_msg: reactive.Value[tuple[str, str] | None] = reactive.value(None)

    @reactive.effect
    @reactive.event(input.show_about_core)
    def _show_about_core_modal():
        version = core_version()
        title = f"About SHYFEM — v{version}" if version else "About SHYFEM"
        _markdown_modal(read_repo_markdown("README.md"), title)

    @reactive.effect
    @reactive.event(input.show_about_ui)
    def _show_about_ui_modal():
        _markdown_modal(
            read_repo_markdown("shyfem-ui/README.md"),
            f"About SHYFEM Workbench (UI) — v{__version__}",
        )

    @reactive.effect
    @reactive.event(input.show_changelog_core)
    def _show_changelog_core_modal():
        _markdown_modal(
            filter_changelog(read_repo_markdown("CHANGELOG.md"), "core"),
            "Changelog — SHYFEM",
        )

    @reactive.effect
    @reactive.event(input.show_changelog_ui)
    def _show_changelog_ui_modal():
        _markdown_modal(
            filter_changelog(read_repo_markdown("CHANGELOG.md"), "ui"),
            "Changelog — SHYFEM UI",
        )

    @reactive.effect
    @reactive.event(input.show_feedback)
    def _show_feedback_modal():
        _submit_msg.set(None)
        ui.modal_show(
            ui.modal(
                _feedback_form(),
                title="Feedback",
                size="l",
                easy_close=True,
                footer=ui.modal_button("Close"),
            )
        )

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
