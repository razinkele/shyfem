def test_shy_option_removed():
    """'shy' must not be a data type option — it falls through to an error.
    Users should use Post-Process to convert .shy → NetCDF first."""
    import inspect
    from shyfem_ui.pages import visualize
    source = inspect.getsource(visualize)
    assert '"shy": "SHYFEM Output (.shy)"' not in source, (
        "Remove the .shy option from visualize data_type choices — "
        "it is not implemented and shows an error to users"
    )
