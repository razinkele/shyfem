# Phase 23: Page Logic Tests — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add unit tests for 11 module-level pure functions across compare.py, ensemble.py, and visualize.py pages (~30 new tests).

**Architecture:** Pure function testing — no Shiny session, no ASGI mocking. Use real dataclass instances (StrFile/StrSection, GrdFile, JobInfo) for fixtures. `tmp_path` for I/O tests. Plotly `go.Figure` type + trace count assertions.

**Tech Stack:** pytest, plotly, pandas (for _load_timeseries), parser_str/parser_grd/job_queue dataclasses

---

### Task 1: Test `pages/compare.py` pure functions

**Files:**
- Create: `tests/test_page_compare.py`
- Reference: `shyfem_ui/pages/compare.py` (lines 429–473)
- Reference: `shyfem_ui/services/parser_str.py` (StrFile, StrSection)

**Step 1: Write the test file**

```python
"""Tests for compare page pure functions."""

from pathlib import Path

import pytest

from shyfem_ui.pages.compare import _compute_param_diff, _load_ts
from shyfem_ui.services.parser_str import StrFile, StrSection


# ── helpers ──────────────────────────────────────────────────────


def _make_str_file(sections_dict: dict[str, dict]) -> StrFile:
    """Build a StrFile from a dict of {section_name: {param: value}}."""
    sf = StrFile()
    for sec_name, params in sections_dict.items():
        section = StrSection(name=sec_name, parameters=dict(params))
        sf.sections[sec_name] = section
    return sf


# ── _compute_param_diff ─────────────────────────────────────────


def test_param_diff_identical():
    a = _make_str_file({"para": {"dt": 10, "itrans": 1}})
    b = _make_str_file({"para": {"dt": 10, "itrans": 1}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 0
    assert result["rows"] == []


def test_param_diff_different_values():
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 20}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["param"] == "dt"
    assert result["rows"][0]["value_a"] == "10"
    assert result["rows"][0]["value_b"] == "20"


def test_param_diff_extra_section():
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 10}, "wind": {"itypw": 1}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["section"] == "wind"
    assert result["rows"][0]["value_a"] == "-"


def test_param_diff_empty_inputs():
    a = _make_str_file({})
    b = _make_str_file({})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 0
    assert result["name_a"] == "A"
    assert result["name_b"] == "B"


def test_param_diff_names_preserved():
    a = _make_str_file({"para": {"dt": 1}})
    b = _make_str_file({"para": {"dt": 2}})
    result = _compute_param_diff(a, b, "run_01", "run_02")
    assert result["name_a"] == "run_01"
    assert result["name_b"] == "run_02"


# ── _load_ts ─────────────────────────────────────────────────────


def test_load_ts_valid(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("0.0 1.0 2.0\n1.0 3.0 4.0\n")
    result = _load_ts(f)
    assert len(result) == 2
    assert result[0] == [0.0, 1.0, 2.0]


def test_load_ts_skips_non_numeric(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("time col1 col2\n0.0 1.0 2.0\n")
    result = _load_ts(f)
    assert len(result) == 1
    assert result[0] == [0.0, 1.0, 2.0]


def test_load_ts_empty_file(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("")
    result = _load_ts(f)
    assert result == []
```

**Step 2: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_page_compare.py -v`
Expected: 8 tests PASS

**Step 3: Commit**

```bash
git add tests/test_page_compare.py
git commit -m "test: add 8 unit tests for compare page pure functions"
```

---

### Task 2: Test `pages/ensemble.py` pure functions

**Files:**
- Create: `tests/test_page_ensemble.py`
- Reference: `shyfem_ui/pages/ensemble.py` (lines 791–948)
- Reference: `shyfem_ui/services/job_queue.py` (JobInfo, JobStatus)

**Step 1: Write the test file**

```python
"""Tests for ensemble page pure functions."""

from datetime import datetime, timedelta
from pathlib import Path

import plotly.graph_objects as go
import pytest

from shyfem_ui.pages.ensemble import (
    _build_duration_chart,
    _build_ensemble_ts_plot,
    _combo_label,
    _load_ts,
    _try_convert,
)
from shyfem_ui.services.job_queue import JobInfo, JobStatus


# ── _try_convert ─────────────────────────────────────────────────


def test_try_convert_int():
    assert _try_convert("42") == 42
    assert isinstance(_try_convert("42"), int)


def test_try_convert_float():
    assert _try_convert("3.14") == pytest.approx(3.14)
    assert isinstance(_try_convert("3.14"), float)


def test_try_convert_string():
    assert _try_convert("hello") == "hello"
    assert isinstance(_try_convert("hello"), str)


def test_try_convert_negative():
    assert _try_convert("-5") == -5


# ── _combo_label ─────────────────────────────────────────────────


def test_combo_label_empty():
    assert _combo_label({}, 0) == "run_000"
    assert _combo_label({}, 7) == "run_007"


def test_combo_label_single():
    combo = {("para", "dt"): "10"}
    result = _combo_label(combo, 0)
    assert "dt" in result
    assert "10" in result


def test_combo_label_sanitized():
    combo = {("para", "dt"): "0.5"}
    result = _combo_label(combo, 0)
    assert "." not in result  # replaced with 'p'
    assert "p" in result


def test_combo_label_truncation():
    # Create a very long label
    combo = {("sec", f"param_{i}"): f"value_{i}" for i in range(20)}
    result = _combo_label(combo, 5)
    assert len(result) <= 60


# ── _load_ts (ensemble version) ─────────────────────────────────


def test_load_ts_valid(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("0.0 1.0\n1.0 2.0\n2.0 3.0\n")
    result = _load_ts(f)
    assert len(result) == 3
    assert result[0] == [0.0, 1.0]


def test_load_ts_missing_file(tmp_path):
    f = tmp_path / "nonexistent.dat"
    result = _load_ts(f)
    assert result == []


def test_load_ts_empty_file(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("")
    result = _load_ts(f)
    assert result == []


# ── _build_duration_chart ────────────────────────────────────────


def _make_job(name="test", status=JobStatus.COMPLETED, duration_s=60.0, combo=None):
    now = datetime(2026, 2, 14, 12, 0, 0)
    return JobInfo(
        id="j1", name=name, tool_name="shyfem", args=[], working_dir="/tmp",
        status=status, progress=1.0, created_at=now,
        started_at=now, completed_at=now + timedelta(seconds=duration_s),
        metadata={"param_combo": combo or {}},
    )


def test_duration_chart_returns_figure():
    jobs = [_make_job(name="Run 1")]
    fig = _build_duration_chart(jobs)
    assert isinstance(fig, go.Figure)


def test_duration_chart_has_traces():
    jobs = [_make_job(name="A"), _make_job(name="B")]
    fig = _build_duration_chart(jobs)
    assert len(fig.data) >= 1  # At least one bar trace


def test_duration_chart_title():
    fig = _build_duration_chart([_make_job()])
    assert "Duration" in fig.layout.title.text


# ── _build_ensemble_ts_plot ──────────────────────────────────────


def _make_run_data(label, rows):
    return {"label": label, "data": rows}


def test_ensemble_ts_single_run():
    run = _make_run_data("run1", [[0, 1], [1, 2], [2, 3]])
    fig = _build_ensemble_ts_plot([run])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1  # Just the line, no envelope


def test_ensemble_ts_multiple_runs_has_envelope():
    runs = [
        _make_run_data("run1", [[0, 1], [1, 2], [2, 3]]),
        _make_run_data("run2", [[0, 2], [1, 3], [2, 4]]),
    ]
    fig = _build_ensemble_ts_plot(runs)
    assert isinstance(fig, go.Figure)
    # 2 individual + 1 envelope + 1 mean = 4 traces
    assert len(fig.data) == 4


def test_ensemble_ts_empty():
    fig = _build_ensemble_ts_plot([])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0
```

**Step 2: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_page_ensemble.py -v`
Expected: 16 tests PASS

**Step 3: Commit**

```bash
git add tests/test_page_ensemble.py
git commit -m "test: add 16 unit tests for ensemble page pure functions"
```

---

### Task 3: Test `pages/visualize.py` pure functions

**Files:**
- Create: `tests/test_page_visualize.py`
- Reference: `shyfem_ui/pages/visualize.py` (lines 543–641, 1058–1134)
- Reference: `shyfem_ui/services/parser_grd.py` (GrdFile, Node, Element)

**Step 1: Write the test file**

```python
"""Tests for visualize page pure functions."""

from pathlib import Path

import plotly.graph_objects as go
import pytest

from shyfem_ui.pages.visualize import (
    _compare_grids,
    _compare_timeseries,
    _load_timeseries,
    _plotly_timeseries,
)
from shyfem_ui.services.parser_grd import Element, GrdFile, Line, Node


# ── fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def sample_grd():
    """Minimal 4-node, 2-triangle grid with depths."""
    nodes = {
        1: Node(id=1, node_type=0, x=0.0, y=0.0, depth=1.0),
        2: Node(id=2, node_type=0, x=1.0, y=0.0, depth=2.0),
        3: Node(id=3, node_type=0, x=0.0, y=1.0, depth=3.0),
        4: Node(id=4, node_type=0, x=1.0, y=1.0, depth=4.0),
    }
    elements = {
        1: Element(id=1, elem_type=0, nodes=[1, 2, 3]),
        2: Element(id=2, elem_type=0, nodes=[2, 4, 3]),
    }
    return GrdFile(nodes=nodes, elements=elements)


def _make_ts_data(with_df=False):
    """Create a synthetic time series data dict."""
    data = [[0, 1.0, 2.0], [1, 1.5, 2.5], [2, 2.0, 3.0]]
    columns = ["time", "col1", "col2"]
    result = {"columns": columns, "data": data, "df": None}
    if with_df:
        import pandas as pd
        result["df"] = pd.DataFrame(data, columns=columns)
    return result


# ── _load_timeseries ─────────────────────────────────────────────


def test_load_timeseries_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("time,col1,col2\n0,1.0,2.0\n1,1.5,2.5\n")
    result = _load_timeseries(f)
    assert "columns" in result
    assert "data" in result
    assert len(result["columns"]) == 3


def test_load_timeseries_whitespace(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("time col1 col2\n0 1.0 2.0\n1 1.5 2.5\n")
    result = _load_timeseries(f)
    assert len(result["data"]) >= 1 or result["df"] is not None


def test_load_timeseries_empty(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("")
    result = _load_timeseries(f)
    assert "columns" in result


# ── _plotly_timeseries ───────────────────────────────────────────


def test_plotly_timeseries_line():
    data = _make_ts_data(with_df=True)
    fig = _plotly_timeseries(data, "line", show_grid=False)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2  # col1, col2


def test_plotly_timeseries_scatter():
    data = _make_ts_data(with_df=True)
    fig = _plotly_timeseries(data, "scatter", show_grid=False)
    assert isinstance(fig, go.Figure)


def test_plotly_timeseries_area():
    data = _make_ts_data(with_df=True)
    fig = _plotly_timeseries(data, "area", show_grid=True)
    assert isinstance(fig, go.Figure)


def test_plotly_timeseries_raw_data():
    data = _make_ts_data(with_df=False)
    fig = _plotly_timeseries(data, "line", show_grid=False)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


# ── _compare_grids ───────────────────────────────────────────────


def test_compare_grids_returns_figure(sample_grd):
    fig = _compare_grids(sample_grd, sample_grd, "Viridis")
    assert isinstance(fig, go.Figure)


def test_compare_grids_title(sample_grd):
    fig = _compare_grids(sample_grd, sample_grd, "Viridis")
    assert "Comparison" in fig.layout.title.text


# ── _compare_timeseries ─────────────────────────────────────────


def test_compare_timeseries_returns_figure():
    ts1 = _make_ts_data(with_df=True)
    ts2 = _make_ts_data(with_df=True)
    fig = _compare_timeseries(ts1, ts2)
    assert isinstance(fig, go.Figure)


def test_compare_timeseries_has_traces():
    ts1 = _make_ts_data(with_df=True)
    ts2 = _make_ts_data(with_df=True)
    fig = _compare_timeseries(ts1, ts2)
    # 2 columns x 2 datasets = 4 traces
    assert len(fig.data) == 4
```

**Step 2: Run tests**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_page_visualize.py -v`
Expected: 11 tests PASS

**Step 3: Commit**

```bash
git add tests/test_page_visualize.py
git commit -m "test: add 11 unit tests for visualize page pure functions"
```

---

### Task 4: Final Verification and TODO_NEXT.md Update

**Step 1: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py --ignore=tests/test_playwright_interactions.py`

Expected: 428+ tests pass (393 baseline + ~35 new), 0 new failures.

**Step 2: Update TODO_NEXT.md**

Mark Phase 23 items:
- [x] 23.1 — 8 tests for compare.py (_compute_param_diff, _load_ts)
- [x] 23.2 — 16 tests for ensemble.py (_try_convert, _combo_label, _load_ts, _build_duration_chart, _build_ensemble_ts_plot)
- [x] 23.3 — 11 tests for visualize.py (_load_timeseries, _plotly_timeseries, _compare_grids, _compare_timeseries)

**Step 3: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 23 page logic tests complete in TODO_NEXT.md"
```
