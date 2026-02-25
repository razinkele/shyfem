"""Tests for ensemble page."""


def test_duration_chart_uses_ocean_colors():
    """Ensure duration bar chart uses ocean theme colors, not Bootstrap hex."""
    import inspect
    from shyfem_ui.pages import ensemble

    source = inspect.getsource(ensemble)
    assert "#198754" not in source, "Found Bootstrap green hex — use ocean teal (#3DB8A0)"
    assert "#dc3545" not in source, "Found Bootstrap red hex — use ocean coral (#E8725A)"
