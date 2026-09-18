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


def test_project_file_choices_filters_by_data_type(tmp_path):
    """The picker lists only files the Data Type can plot, skips hidden trees,
    and always leads with an empty placeholder."""
    from shyfem_ui.pages.visualize import _project_file_choices

    (tmp_path / "grid.grd").write_text("x")
    (tmp_path / "mesh.bas").write_text("x")
    (tmp_path / "series.ts").write_text("x")
    (tmp_path / "field.nc").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    cache = tmp_path / ".boxmodel_cache" / "run1"
    cache.mkdir(parents=True)
    (cache / "state.grd").write_text("x")  # hidden tree -> excluded
    sub = tmp_path / "GRID"
    sub.mkdir()
    (sub / "nested.grd").write_text("x")  # recursive -> included

    grid = _project_file_choices(tmp_path, "grid")
    assert grid[""] == "— select a file —"
    # .bas is a binary basin file with no Python reader -> not offered
    assert set(grid) == {"", "grid.grd", "GRID/nested.grd"}

    assert set(_project_file_choices(tmp_path, "timeseries")) == {"", "series.ts"}
    assert set(_project_file_choices(tmp_path, "netcdf")) == {"", "field.nc"}
    # unknown data type -> placeholder only
    assert _project_file_choices(tmp_path, "bogus") == {"": "— select a file —"}
