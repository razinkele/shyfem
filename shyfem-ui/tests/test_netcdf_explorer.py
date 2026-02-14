"""Tests for NetCDF variable explorer pure functions."""

import numpy as np
import pytest
import xarray as xr


def _make_dataset():
    """Create a synthetic xarray Dataset for testing."""
    time = np.array(["2024-01-01", "2024-01-02", "2024-01-03"], dtype="datetime64")
    depth = np.array([0.0, 5.0, 10.0, 20.0])
    y = np.arange(3)
    x = np.arange(4)

    temp = np.random.rand(3, 4, 3, 4).astype(np.float32)
    salt = np.random.rand(3, 4, 3, 4).astype(np.float32) * 35

    ds = xr.Dataset(
        {
            "temperature": (["time", "depth", "y", "x"], temp, {
                "units": "degC",
                "long_name": "Sea Water Temperature",
                "standard_name": "sea_water_temperature",
                "valid_range": [0.0, 40.0],
            }),
            "salinity": (["time", "depth", "y", "x"], salt, {
                "units": "PSU",
                "long_name": "Sea Water Salinity",
                "_FillValue": -999.0,
            }),
        },
        coords={
            "time": time,
            "depth": depth,
            "y": y,
            "x": x,
        },
        attrs={"title": "Test Dataset"},
    )
    return ds


class TestBuildVariableTable:
    """Tests for build_variable_table()."""

    def test_returns_list_of_dicts(self):
        from shyfem_ui.pages.visualize import build_variable_table

        ds = _make_dataset()
        result = build_variable_table(ds)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(r, dict) for r in result)

    def test_variable_fields(self):
        from shyfem_ui.pages.visualize import build_variable_table

        ds = _make_dataset()
        result = build_variable_table(ds)
        temp = next(r for r in result if r["name"] == "temperature")
        assert temp["dtype"] == "float32"
        assert temp["units"] == "degC"
        assert temp["long_name"] == "Sea Water Temperature"
        assert "time" in temp["dims"]

    def test_min_max_computed(self):
        from shyfem_ui.pages.visualize import build_variable_table

        ds = _make_dataset()
        result = build_variable_table(ds)
        temp = next(r for r in result if r["name"] == "temperature")
        assert isinstance(temp["min"], float)
        assert isinstance(temp["max"], float)
        assert temp["min"] >= 0.0
        assert temp["max"] <= 1.0  # random rand is [0, 1)

    def test_empty_dataset(self):
        from shyfem_ui.pages.visualize import build_variable_table

        ds = xr.Dataset()
        result = build_variable_table(ds)
        assert result == []

    def test_missing_attrs(self):
        from shyfem_ui.pages.visualize import build_variable_table

        ds = xr.Dataset({"v": (["x"], [1.0, 2.0, 3.0])})
        result = build_variable_table(ds)
        assert result[0]["units"] == "-"
        assert result[0]["long_name"] == "-"


class TestGetDimLabel:
    """Tests for get_dim_label()."""

    def test_time_dimension(self):
        from shyfem_ui.pages.visualize import get_dim_label

        ds = _make_dataset()
        label = get_dim_label(ds, "time", 0)
        assert "2024" in label
        assert "01" in label

    def test_depth_dimension(self):
        from shyfem_ui.pages.visualize import get_dim_label

        ds = _make_dataset()
        label = get_dim_label(ds, "depth", 2)
        assert "10" in label

    def test_plain_dimension(self):
        from shyfem_ui.pages.visualize import get_dim_label

        ds = _make_dataset()
        label = get_dim_label(ds, "x", 1)
        # For plain integer coords, should show the value
        assert "1" in label

    def test_missing_coord(self):
        from shyfem_ui.pages.visualize import get_dim_label

        ds = xr.Dataset({"v": (["a"], [1.0, 2.0])})
        label = get_dim_label(ds, "a", 0)
        # "a" is not a coordinate, so should return plain index
        assert label == "0"

    def test_index_out_of_range(self):
        from shyfem_ui.pages.visualize import get_dim_label

        ds = _make_dataset()
        label = get_dim_label(ds, "time", 999)
        assert label == "999"


class TestGetVariableAttrs:
    """Tests for get_variable_attrs()."""

    def test_all_attrs_present(self):
        from shyfem_ui.pages.visualize import get_variable_attrs

        ds = _make_dataset()
        attrs = get_variable_attrs(ds, "temperature")
        assert attrs["long_name"] == "Sea Water Temperature"
        assert attrs["standard_name"] == "sea_water_temperature"
        assert attrs["units"] == "degC"
        assert attrs["valid_range"] == [0.0, 40.0]

    def test_partial_attrs(self):
        from shyfem_ui.pages.visualize import get_variable_attrs

        ds = _make_dataset()
        attrs = get_variable_attrs(ds, "salinity")
        assert attrs["long_name"] == "Sea Water Salinity"
        assert attrs["standard_name"] is None
        assert attrs["_FillValue"] == -999.0

    def test_no_attrs(self):
        from shyfem_ui.pages.visualize import get_variable_attrs

        ds = xr.Dataset({"v": (["x"], [1.0, 2.0])})
        attrs = get_variable_attrs(ds, "v")
        assert attrs["long_name"] is None
        assert attrs["units"] is None

    def test_missing_variable(self):
        from shyfem_ui.pages.visualize import get_variable_attrs

        ds = _make_dataset()
        attrs = get_variable_attrs(ds, "nonexistent")
        assert all(v is None for v in attrs.values())
