def test_shy_option_removed():
    """'shy' must not be an option in the data_type select widget.

    Renders the actual visualize UI and asserts the rendered HTML does not
    contain a 'shy' option value — the only reliable guard against it being
    re-added to the choices dict.
    """
    from shyfem_ui.pages.visualize import visualize_ui

    html = str(visualize_ui("viz_test"))
    # The select element for data_type must not have a 'shy' option value.
    assert 'value="shy"' not in html, (
        "Remove the .shy option from visualize data_type choices — "
        "it is not implemented and shows an error to users"
    )
