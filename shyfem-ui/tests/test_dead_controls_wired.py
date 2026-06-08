"""P2 of the 2026-06-08 unwired audit: the two dead UI controls are now wired.

- physics "Preview STR" button (input.preview_btn) had no server reader.
- visualize "Equal Aspect Ratio" checkbox (input.equal_aspect) was never read.
"""

import inspect


def test_equal_aspect_helper_sets_scaleanchor_when_enabled():
    import plotly.graph_objects as go

    from shyfem_ui.pages.visualize import _apply_equal_aspect

    fig = go.Figure()
    _apply_equal_aspect(fig, True)
    assert fig.layout.yaxis.scaleanchor == "x"
    assert fig.layout.yaxis.scaleratio == 1


def test_equal_aspect_helper_noop_when_disabled():
    import plotly.graph_objects as go

    from shyfem_ui.pages.visualize import _apply_equal_aspect

    fig = go.Figure()
    _apply_equal_aspect(fig, False)
    assert fig.layout.yaxis.scaleanchor is None


def test_visualize_main_plot_reads_equal_aspect():
    """The checkbox must actually be consumed (regression lock against re-orphaning)."""
    from shyfem_ui.pages import visualize

    src = inspect.getsource(visualize)
    assert "input.equal_aspect()" in src, "equal_aspect checkbox is not read"
    assert "_apply_equal_aspect(" in src, "equal_aspect not applied to any plot"


def test_physics_preview_button_is_wired():
    """The 'Preview STR' button must have a reactive reader."""
    from shyfem_ui.pages import physics

    src = inspect.getsource(physics)
    assert "@reactive.event(input.preview_btn)" in src, "preview_btn has no handler"
    assert "StrParser.generate(" in src, "preview does not render generated STR"
