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


def test_workflow_cancel_is_surfaced():
    """P5: WorkflowEngine.cancel_workflow existed with no UI path. The run page
    must render a cancel control for an active workflow and wire it (with the
    same editor gate as launch — cancelling is as privileged as submitting)."""
    from shyfem_ui.pages import run

    src = inspect.getsource(run)
    assert "@reactive.event(input.wf_cancel_btn)" in src, "no cancel handler"
    assert "cancel_workflow(" in src, "handler does not call the engine"
    assert 'input_action_button(\n                "wf_cancel_btn"' in src or (
        '"wf_cancel_btn"' in src
    ), "no cancel button rendered"


def test_active_nav_dead_signal_removed():
    """P6: the _active_nav JS setter had no server reader — removed."""
    from pathlib import Path

    import shyfem_ui

    app_src = (Path(shyfem_ui.__file__).parent / "app.py").read_text()
    assert "_active_nav" not in app_src


def test_run_shyplot_wrapper_removed():
    """P5 decision (2026-06-12): shyplot stays available as a generic tool
    (run page + job dispatch via run_command); the dedicated wrapper method
    had no caller and was removed."""
    from shyfem_ui.services import shyfem_wrapper

    src = inspect.getsource(shyfem_wrapper)
    assert "def run_shyplot" not in src


def test_run_page_uses_template_accessor():
    """P5: pages must go through WorkflowEngine.list_templates, not read
    the WORKFLOW_TEMPLATES module constant directly."""
    from shyfem_ui.pages import run

    src = inspect.getsource(run)
    assert "WORKFLOW_TEMPLATES" not in src
    assert "list_templates()" in src


def test_ibm_time_filter_is_wired():
    """P5: lgr_service.filter_by_time had no UI caller. The IBM page must
    read the time-range inputs and cut tracks through filter_by_time
    (behavior of the filter itself is covered in test_lgr_service.py)."""
    from shyfem_ui.pages import ibm

    src = inspect.getsource(ibm)
    assert "filter_by_time(" in src, "filter_by_time is not called"
    assert "input.time_min()" in src, "time_min input is not read"
    assert "input.time_max()" in src, "time_max input is not read"
