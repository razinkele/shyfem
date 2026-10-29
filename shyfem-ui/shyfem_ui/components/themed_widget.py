"""``render_widget`` that draws Plotly figures in the viewer's own theme (H-05).

The dark-mode toggle used to re-register Plotly's default template, which is
one object for the whole worker process, so one user's toggle switched the
plots of every other session to dark (or back). The process default now
stays the light SHYFEM template, set once at startup, and each figure a page
renders takes the template of the session that renders it.
"""

from __future__ import annotations

import functools
import inspect
import logging

from shiny import reactive
from shiny.session import get_current_session
from shinywidgets import render_widget as _render_widget

from shyfem_ui.plotly_theme import get_plotly_template

logger = logging.getLogger(__name__)


def session_is_dark() -> bool:
    """True when the current session's browser reported dark mode.

    The browser sets the top-level ``_dark_mode`` input; page modules see a
    namespaced input, so it is read from the root scope. Read in isolation:
    a toggle applies to the next figure drawn, it does not redraw every plot.
    """
    session = get_current_session()
    if session is None:
        return False
    try:
        with reactive.isolate():
            return bool(session.root_scope().input["_dark_mode"]())
    except Exception:
        # Not reported yet (the toggle was never used in this browser).
        return False


def apply_session_theme(value):
    """Give a Plotly figure the current session's template; pass others on."""
    try:
        from plotly.basedatatypes import BaseFigure
    except ImportError:  # pragma: no cover - plotly is a hard dependency
        return value
    if isinstance(value, BaseFigure):
        import plotly.graph_objects as go

        layout = get_plotly_template(dark=session_is_dark())["layout"]
        value.update_layout(template=go.layout.Template(layout=layout))
    return value


def render_widget(fn):
    """Drop-in for ``shinywidgets.render_widget`` that themes per session."""
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def themed_async():
            return apply_session_theme(await fn())

        return _render_widget(themed_async)

    @functools.wraps(fn)
    def themed():
        return apply_session_theme(fn())

    return _render_widget(themed)
