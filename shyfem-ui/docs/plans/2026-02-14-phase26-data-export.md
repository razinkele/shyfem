# Phase 26: Data Export — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add grid statistics JSON export and enhanced Plotly modebar config (SVG, filenames, no logo).

**Architecture:** Two independent tasks. Task 1 adds a pure function `grid_stats_to_json()` with tests, then wires an "Export Stats JSON" button into the Grid Prep page using the established base64 data URI download pattern. Task 2 adds a Plotly config constant and applies it to all `@render_widget` figure returns in the Visualize page.

**Tech Stack:** Python json module, Shiny reactive effects, Plotly config dict, base64 data URI

---

### Task 1: Grid statistics JSON export

**Files:**
- Modify: `shyfem_ui/pages/grid_prep.py` (lines 80-83 for UI, lines 283-348 for handler)
- Create: `tests/test_grid_export.py`

**Step 1: Write tests**

Create `tests/test_grid_export.py`:

```python
"""Tests for grid statistics JSON export."""

import json


def _make_stats():
    """Create a realistic stats dict matching GrdParser.get_statistics() output."""
    return {
        "num_nodes": 1234,
        "num_elements": 2345,
        "num_triangles": 2000,
        "num_quads": 345,
        "num_lines": 50,
        "bounds": {
            "xmin": 0.0,
            "xmax": 100.5,
            "ymin": 10.0,
            "ymax": 55.3,
            "width": 100.5,
            "height": 45.3,
        },
        "depth": {"min": -2.5, "max": 30.0, "mean": 12.4},
        "node_types": [1, 2, 3],
        "element_types": [3, 4],
        "line_types": [1],
    }


class TestGridStatsToJson:
    """Tests for grid_stats_to_json()."""

    def test_valid_stats(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        stats = _make_stats()
        result = grid_stats_to_json(stats, "test_grid")
        parsed = json.loads(result)
        assert parsed["grid_name"] == "test_grid"
        assert parsed["statistics"]["num_nodes"] == 1234
        assert parsed["statistics"]["bounds"]["xmax"] == 100.5

    def test_empty_stats(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        result = grid_stats_to_json({}, "empty")
        parsed = json.loads(result)
        assert parsed["grid_name"] == "empty"
        assert parsed["statistics"] == {}

    def test_none_depth_values(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        stats = _make_stats()
        stats["depth"] = {"min": None, "max": None, "mean": None}
        result = grid_stats_to_json(stats, "no_depth")
        parsed = json.loads(result)
        assert parsed["statistics"]["depth"]["min"] is None

    def test_output_is_indented(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        result = grid_stats_to_json(_make_stats(), "test")
        assert "\n    " in result  # 4-space indent

    def test_sets_converted_to_lists(self):
        from shyfem_ui.pages.grid_prep import grid_stats_to_json

        stats = _make_stats()
        stats["node_types"] = {1, 2, 3}  # set instead of list
        result = grid_stats_to_json(stats, "set_test")
        parsed = json.loads(result)
        assert sorted(parsed["statistics"]["node_types"]) == [1, 2, 3]
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_export.py -v`
Expected: FAIL (ImportError — `grid_stats_to_json` doesn't exist yet)

**Step 3: Add `grid_stats_to_json()` function to `grid_prep.py`**

Add this function near the top of `shyfem_ui/pages/grid_prep.py`, after the imports but before `grid_prep_ui()`. It's a pure function with no Shiny dependencies:

```python
def grid_stats_to_json(stats: dict, grid_name: str) -> str:
    """Serialize grid statistics to formatted JSON.

    Args:
        stats: Dictionary from GrdParser.get_statistics().
        grid_name: Name of the grid file for metadata.

    Returns:
        Formatted JSON string.
    """
    import json

    def _default(obj):
        if isinstance(obj, set):
            return sorted(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    payload = {
        "grid_name": grid_name,
        "statistics": stats,
    }
    return json.dumps(payload, indent=4, default=_default)
```

**Step 4: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_grid_export.py -v`
Expected: 5 passed

**Step 5: Add "Export Stats JSON" button to grid_prep UI**

In `shyfem_ui/pages/grid_prep.py`, find the Statistics nav_panel (line 80-83):

```python
            ui.nav_panel(
                "Statistics",
                ui.output_ui("grid_stats"),
            ),
```

Replace with:

```python
            ui.nav_panel(
                "Statistics",
                ui.output_ui("grid_stats"),
                ui.input_action_button(
                    "export_stats_btn",
                    "Export Stats JSON",
                    class_="btn-outline-secondary btn-sm mt-2",
                ),
            ),
```

**Step 6: Add the export handler in the server function**

In `shyfem_ui/pages/grid_prep.py`, after the `grid_stats()` render function (after line 348), add:

```python
    @reactive.effect
    @reactive.event(input.export_stats_btn)
    async def _export_stats():
        grd = current_grd.get()
        if grd is None:
            ui.notification_show("No grid loaded", type="warning")
            return

        stats = GrdParser.get_statistics(grd)
        grid_name = getattr(grd, "filename", "grid") or "grid"
        # Strip path and extension for clean name
        grid_name = Path(grid_name).stem if "/" in grid_name or "\\" in grid_name else grid_name

        json_str = grid_stats_to_json(stats, grid_name)

        import base64
        b64 = base64.b64encode(json_str.encode("utf-8")).decode("ascii")
        filename = f"grid_stats_{grid_name}.json"
        js = (
            f"var a=document.createElement('a');"
            f"a.href='data:application/json;base64,{b64}';"
            f"a.download='{filename}';"
            f"a.click();"
        )
        await session.send_custom_message("eval_js", js)
        ui.notification_show(f"Exported {filename}", type="message", duration=3)
```

Note: `Path` is likely already imported. If not, add `from pathlib import Path` at the top.

**Step 7: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 446+ passed, 0 failed

**Step 8: Commit**

```bash
git add shyfem_ui/pages/grid_prep.py tests/test_grid_export.py
git commit -m "feat: add grid statistics JSON export to Grid Prep page"
```

---

### Task 2: Enhanced Plotly modebar configuration

**Files:**
- Modify: `shyfem_ui/pages/visualize.py` (lines 343-420+ — all `@render_widget` functions)

**Step 1: Add PLOTLY_CONFIG constant**

In `shyfem_ui/pages/visualize.py`, after the imports (around line 20), add:

```python
# Plotly modebar config for all figures — enables SVG export, better filenames
PLOTLY_CONFIG = {
    "displaylogo": False,
    "toImageButtonOptions": {
        "format": "svg",
        "filename": "shyfem_plot",
        "scale": 1,
    },
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}
```

**Step 2: Apply config to `main_plot` render_widget**

Find the `main_plot()` function (line 343). It returns `fig` in several places. The config needs to be returned alongside the figure. With shinywidgets `@render_widget`, the config is set via `fig.update_layout()` or by wrapping in `go.FigureWidget`.

The simplest approach: add a helper that applies config to any figure. Add after PLOTLY_CONFIG:

```python
def _with_export_config(fig: go.Figure, filename: str = "shyfem_plot") -> go.Figure:
    """Apply standard export config to a Plotly figure."""
    fig.update_layout(
        modebar=dict(
            orientation="v",
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    # Store config for template; shinywidgets reads _config if present
    fig._config = {**PLOTLY_CONFIG, "toImageButtonOptions": {
        **PLOTLY_CONFIG["toImageButtonOptions"],
        "filename": filename,
    }}
    return fig
```

**Important note:** `shinywidgets.render_widget` may not support Plotly config directly. If `fig._config` doesn't work, an alternative is to use `plotly.graph_objects.FigureWidget` which supports `.update_layout()` for modebar settings. Check by reading how `@render_widget` works in the existing code — it simply returns a `go.Figure` or `go.FigureWidget`.

If `_config` doesn't work, the modebar settings via `update_layout(modebar=...)` still apply to logo removal and button filtering. The `toImageButtonOptions` can be set via Plotly's built-in modebar which is already functional.

**Step 3: Apply to all figure returns in `main_plot()`**

In the `main_plot()` function, before each `return fig`, wrap with:
```python
return _with_export_config(fig, "shyfem_main_plot")
```

Apply to all return paths (empty placeholder fig excluded — only apply to real plots).

**Step 4: Apply to `profile_plot()` and `compare_plot()`**

Same pattern — find the `@render_widget` functions for `profile_plot` (line 421) and `compare_plot` (line 504), wrap returns:
```python
return _with_export_config(fig, "shyfem_profile")
return _with_export_config(fig, "shyfem_comparison")
```

**Step 5: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 446+ passed, 0 failed (no new tests — config is declarative)

**Step 6: Commit**

```bash
git add shyfem_ui/pages/visualize.py
git commit -m "feat: enhance Plotly modebar with SVG export and clean config"
```

---

### Task 3: Final verification and TODO update

**Step 1: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -v 2>&1 | tail -10`
Expected: 446+ passed, 0 failed

**Step 2: Update TODO_NEXT.md**

Mark Phase 26 items as complete. Note which items were skipped (already exist).

**Step 3: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 26 data export complete in TODO_NEXT.md"
```
