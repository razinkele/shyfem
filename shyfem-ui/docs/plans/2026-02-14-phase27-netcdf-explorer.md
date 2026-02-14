# Phase 27: NetCDF Variable Explorer — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add variable info table, coordinate labels on dimension sliders, and variable metadata panel to the Visualize page's NetCDF support.

**Architecture:** Three pure functions added to `visualize.py` — `build_variable_table(ds)`, `get_dim_label(ds, dim, idx)`, `get_variable_attrs(ds, var)`. Each is testable with synthetic xarray Datasets. UI wiring is minimal: one table in Data Info tab, text outputs under sliders, one info div under the variable selector.

**Tech Stack:** xarray, numpy, Shiny reactive UI, pandas (for timestamp formatting)

---

### Task 1: Pure functions and tests

**Files:**
- Modify: `shyfem_ui/pages/visualize.py` (add functions after line ~48, before `visualize_ui()`)
- Create: `tests/test_netcdf_explorer.py`

**Step 1: Write tests**

Create `tests/test_netcdf_explorer.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_netcdf_explorer.py -v`
Expected: FAIL (ImportError — functions don't exist yet)

**Step 3: Implement the three pure functions**

In `shyfem_ui/pages/visualize.py`, add these functions after the imports and `PLOTLY_CONFIG`/`_with_export_config` but before `visualize_ui()`. Find the right insertion point by reading the file.

```python
def build_variable_table(ds) -> list[dict]:
    """Build a summary table of all variables in a NetCDF Dataset.

    Args:
        ds: xarray.Dataset

    Returns:
        List of dicts with keys: name, dims, dtype, units, long_name, min, max
    """
    rows = []
    for var_name in ds.data_vars:
        try:
            var = ds[var_name]
            values = var.values.flatten()
            valid = values[~np.isnan(values)] if np.issubdtype(values.dtype, np.floating) else values
            rows.append({
                "name": var_name,
                "dims": " × ".join(var.dims),
                "dtype": str(var.dtype),
                "units": str(var.attrs.get("units", "-")),
                "long_name": str(var.attrs.get("long_name", "-")),
                "min": float(np.min(valid)) if len(valid) > 0 else None,
                "max": float(np.max(valid)) if len(valid) > 0 else None,
            })
        except Exception:
            continue
    return rows


def get_dim_label(ds, dim_name: str, index: int) -> str:
    """Get a human-readable label for a dimension index.

    Args:
        ds: xarray.Dataset
        dim_name: Name of the dimension
        index: Integer index into the dimension

    Returns:
        Formatted string label (timestamp, depth value, or plain index)
    """
    try:
        if dim_name not in ds.coords:
            return str(index)
        coord = ds.coords[dim_name]
        if index < 0 or index >= len(coord):
            return str(index)
        value = coord.values[index]

        # Time dimensions: format as datetime
        if np.issubdtype(coord.dtype, np.datetime64):
            import pandas as pd
            return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")

        # Numeric: show value
        if np.issubdtype(coord.dtype, np.number):
            units = coord.attrs.get("units", "")
            formatted = f"{float(value):.4g}"
            return f"{formatted} {units}".strip()

        return str(value)
    except Exception:
        return str(index)


def get_variable_attrs(ds, var_name: str) -> dict:
    """Extract key metadata attributes for a NetCDF variable.

    Args:
        ds: xarray.Dataset
        var_name: Name of the variable

    Returns:
        Dict with keys: long_name, standard_name, units, valid_range, _FillValue.
        Values are None if attribute is missing.
    """
    keys = ["long_name", "standard_name", "units", "valid_range", "_FillValue"]
    try:
        var = ds[var_name]
        return {k: var.attrs.get(k) for k in keys}
    except (KeyError, AttributeError):
        return {k: None for k in keys}
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_netcdf_explorer.py -v`
Expected: 14 passed

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 460+ passed, 0 failed

**Step 6: Commit**

```bash
git add shyfem_ui/pages/visualize.py tests/test_netcdf_explorer.py
git commit -m "feat: add NetCDF variable explorer pure functions with tests"
```

---

### Task 2: Wire UI — variable info table, coordinate labels, metadata panel

**Files:**
- Modify: `shyfem_ui/pages/visualize.py` (lines 224-268 for `netcdf_controls()`, data info rendering)

**Step 1: Add coordinate labels to dimension sliders**

In `shyfem_ui/pages/visualize.py`, find `netcdf_controls()` (line 224). Currently each dimension slider is added like:

```python
            if dim_size > 1:
                controls.append(
                    ui.input_slider(
                        f"nc_dim_{dim_name}",
                        dim_name,
                        min=0, max=dim_size - 1, value=0, step=1,
                    ),
                )
```

After each slider, add a text output that shows the coordinate label. Replace the slider block with:

```python
            if dim_size > 1:
                controls.append(
                    ui.input_slider(
                        f"nc_dim_{dim_name}",
                        dim_name,
                        min=0, max=dim_size - 1, value=0, step=1,
                    ),
                )
                controls.append(
                    ui.output_text(f"nc_dim_label_{dim_name}"),
                )
```

**Step 2: Add coordinate label render functions**

In the server function `visualize_server()`, after the `netcdf_controls()` render function, add dynamic renderers for each dimension. Since dimensions are dynamic, use a reactive approach:

```python
    @reactive.effect
    def _register_dim_labels():
        """Register text renderers for dimension coordinate labels."""
        dims = nc_dimensions.get()
        ds = loaded_data.get()
        if not dims or ds is None or data_type.get() != "netcdf":
            return

        for dim_name in dims:
            if dims[dim_name] <= 1:
                continue
            # Capture dim_name in closure
            _dim = dim_name

            @output(id=f"nc_dim_label_{_dim}")
            @render.text
            def _label_text(_d=_dim):
                try:
                    idx = input[f"nc_dim_{_d}"]()
                    ds_val = loaded_data.get()
                    if ds_val is None:
                        return ""
                    return get_dim_label(ds_val, _d, int(idx))
                except Exception:
                    return ""
```

**Step 3: Add variable metadata panel below variable selector**

In `netcdf_controls()`, after the variable `input_select` (line 241), add a metadata output:

```python
        controls = [
            ui.input_select(
                "nc_variable",
                "Variable",
                choices={v: v for v in variables},
            ),
            ui.output_ui("nc_var_metadata"),
        ]
```

Then add the renderer in the server function:

```python
    @render.ui
    def nc_var_metadata():
        """Show metadata for the selected NetCDF variable."""
        ds = loaded_data.get()
        if ds is None or data_type.get() != "netcdf":
            return None
        try:
            var_name = input.nc_variable()
        except Exception:
            return None
        if not var_name:
            return None

        attrs = get_variable_attrs(ds, var_name)
        parts = []
        if attrs.get("long_name"):
            parts.append(ui.p(ui.em(str(attrs["long_name"])), class_="small mb-1"))
        meta_items = []
        if attrs.get("units"):
            meta_items.append(f"Units: {attrs['units']}")
        if attrs.get("standard_name"):
            meta_items.append(f"CF: {attrs['standard_name']}")
        if attrs.get("valid_range"):
            meta_items.append(f"Range: {attrs['valid_range']}")
        if attrs.get("_FillValue") is not None:
            meta_items.append(f"Fill: {attrs['_FillValue']}")
        if meta_items:
            parts.append(ui.p(" | ".join(meta_items), class_="small text-muted mb-1"))

        if not parts:
            return None
        return ui.div(*parts, class_="mb-2")
```

**Step 4: Add variable info table to Data Info tab**

Find where `data_info_val` is rendered (look for a `@render.ui` or `@render.text` that displays `data_info_val`). When the data type is "netcdf", add a variable summary table using `build_variable_table()`.

Search for how `data_info_val` is displayed. If it's a simple text output, replace/extend it with a conditional that shows a table for NetCDF. Add after the existing data_info renderer:

```python
    @render.ui
    def nc_variable_table():
        """Show variable summary table for NetCDF datasets."""
        ds = loaded_data.get()
        if ds is None or data_type.get() != "netcdf":
            return None

        rows_data = build_variable_table(ds)
        if not rows_data:
            return ui.p("No variables found", class_="text-muted")

        table_rows = [
            ui.tags.tr(
                ui.tags.td(r["name"]),
                ui.tags.td(r["dims"]),
                ui.tags.td(r["dtype"]),
                ui.tags.td(r["units"]),
                ui.tags.td(r["long_name"]),
                ui.tags.td(f"{r['min']:.4g}" if r["min"] is not None else "-"),
                ui.tags.td(f"{r['max']:.4g}" if r["max"] is not None else "-"),
            )
            for r in rows_data
        ]

        return ui.div(
            ui.h6("Variable Summary"),
            ui.tags.table(
                ui.tags.thead(
                    ui.tags.tr(
                        ui.tags.th("Name"),
                        ui.tags.th("Dimensions"),
                        ui.tags.th("Type"),
                        ui.tags.th("Units"),
                        ui.tags.th("Description"),
                        ui.tags.th("Min"),
                        ui.tags.th("Max"),
                    ),
                ),
                ui.tags.tbody(*table_rows),
                class_="table table-sm table-bordered",
            ),
        )
```

Also add `ui.output_ui("nc_variable_table")` to the Data Info tab in the UI layout. Find the Data Info nav_panel and add it.

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 460+ passed, 0 failed

**Step 6: Commit**

```bash
git add shyfem_ui/pages/visualize.py
git commit -m "feat: wire NetCDF variable explorer UI — metadata, labels, info table"
```

---

### Task 3: Final verification and TODO update

**Step 1: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v 2>&1 | tail -10`
Expected: 460+ passed, 0 failed

**Step 2: Update TODO_NEXT.md**

Mark Phase 27 items as complete.

**Step 3: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 27 NetCDF variable explorer complete in TODO_NEXT.md"
```
