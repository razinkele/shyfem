"""Dark mode is per session, not per process (H-05).

The toggle re-registered Plotly's default template, a process-wide object,
so after one user switched to dark every other session's next figure was
dark too (``paper_bgcolor`` ``#2A3545``).
"""

import ast
import pathlib

import plotly.graph_objects as go
import plotly.io as pio
from shiny.session import session_context

from shyfem_ui.components.themed_widget import apply_session_theme, session_is_dark
from shyfem_ui.plotly_theme import get_plotly_template, register_shyfem_template

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"
DARK_BG = get_plotly_template(dark=True)["layout"]["paper_bgcolor"]
LIGHT_BG = get_plotly_template(dark=False)["layout"]["paper_bgcolor"]


class _Scope:
    ns = ""

    def __init__(self, inputs):
        self.input = inputs

    def root_scope(self):
        return self


def _session(dark=None):
    inputs = {} if dark is None else {"_dark_mode": lambda: dark}
    return _Scope(_Inputs(inputs))


class _Inputs(dict):
    def __getitem__(self, key):
        if key not in self:
            raise KeyError(key)  # an input the browser never set
        return dict.__getitem__(self, key)


def _paper_bg(fig) -> str:
    return fig.layout.template.layout.paper_bgcolor


def test_one_sessions_dark_mode_does_not_reach_another():
    register_shyfem_template(dark=False)
    with session_context(_session(dark=True)):
        dark_fig = apply_session_theme(go.Figure())
    with session_context(_session(dark=False)):
        light_fig = apply_session_theme(go.Figure())
    assert _paper_bg(dark_fig) == DARK_BG
    assert _paper_bg(light_fig) == LIGHT_BG
    # The process default was not touched by either session.
    assert pio.templates.default == "shyfem"
    assert pio.templates["shyfem"].layout.paper_bgcolor == LIGHT_BG


def test_unset_toggle_and_no_session_draw_light():
    with session_context(_session()):
        assert session_is_dark() is False
    assert session_is_dark() is False
    assert _paper_bg(apply_session_theme(go.Figure())) == LIGHT_BG


def test_non_figures_pass_through():
    marker = object()
    assert apply_session_theme(marker) is marker
    assert apply_session_theme(None) is None


def test_app_registers_the_template_only_at_startup():
    """The toggle handler must not re-register the process-wide template."""
    tree = ast.parse((SRC / "app.py").read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "register_shyfem_template"
    ]
    assert len(calls) == 1


def test_pages_use_the_session_themed_render_widget():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.name == "themed_widget.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module == "shinywidgets":
                if any(a.name == "render_widget" for a in node.names):
                    offenders.append(str(path.relative_to(SRC)))
    assert offenders == []
