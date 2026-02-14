# Phase 22: Component Test Coverage — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add unit tests for pure functions in job_status, log_viewer, and plot_widget components (~25 new tests).

**Architecture:** Pure function testing — no Shiny session, no ASGI mocking. Synthetic `GrdFile` fixtures for plot tests. Each test file is independent and can be implemented in parallel.

**Tech Stack:** pytest, matplotlib (Agg backend), html module (for XSS assertions)

---

### Task 1: Test `components/job_status.py`

**Files:**
- Create: `tests/test_job_status.py`
- Reference: `shyfem_ui/components/job_status.py` (lines 10–191)
- Reference: `shyfem_ui/services/job_queue.py` (lines 13–73)

**Step 1: Write the test file**

```python
"""Tests for job_status component pure functions."""

from datetime import datetime

import pytest

from shyfem_ui.components.job_status import (
    format_datetime,
    format_duration,
    get_status_badge,
    job_list_table,
)
from shyfem_ui.services.job_queue import JobInfo, JobStatus


# ── format_duration ──────────────────────────────────────────────


def test_format_duration_none():
    assert format_duration(None) == "-"


def test_format_duration_zero():
    assert format_duration(0) == "0.0s"


def test_format_duration_seconds():
    assert format_duration(30) == "30.0s"


def test_format_duration_minutes():
    assert format_duration(90) == "1m 30s"


def test_format_duration_hours():
    assert format_duration(3661) == "1h 1m"


def test_format_duration_fractional():
    assert format_duration(5.7) == "5.7s"


# ── format_datetime ──────────────────────────────────────────────


def test_format_datetime_none():
    assert format_datetime(None) == "-"


def test_format_datetime_value():
    dt = datetime(2026, 2, 14, 10, 30, 45)
    assert format_datetime(dt) == "2026-02-14 10:30:45"


# ── get_status_badge ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,expected_class",
    [
        (JobStatus.PENDING, "bg-secondary"),
        (JobStatus.QUEUED, "bg-info"),
        (JobStatus.RUNNING, "bg-primary"),
        (JobStatus.COMPLETED, "bg-success"),
        (JobStatus.FAILED, "bg-danger"),
        (JobStatus.CANCELLED, "bg-warning"),
    ],
)
def test_get_status_badge(status, expected_class):
    badge = get_status_badge(status)
    rendered = str(badge)
    assert expected_class in rendered
    assert status.value.upper() in rendered


# ── job_list_table ───────────────────────────────────────────────


def _make_job(name="test", status=JobStatus.COMPLETED, progress=1.0):
    return JobInfo(
        id="job-1",
        name=name,
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=status,
        progress=progress,
        created_at=datetime(2026, 2, 14, 12, 0, 0),
    )


def test_job_list_table_empty():
    result = str(job_list_table([]))
    assert "No jobs found" in result


def test_job_list_table_single():
    table = str(job_list_table([_make_job(name="Run 1")]))
    assert "Run 1" in table
    assert "shyfem" in table


def test_job_list_table_multiple():
    jobs = [_make_job(name="A"), _make_job(name="B")]
    table = str(job_list_table(jobs))
    assert "A" in table
    assert "B" in table
```

**Step 2: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_job_status.py -v`
Expected: all 13 tests PASS

**Step 3: Commit**

```bash
git add tests/test_job_status.py
git commit -m "test: add 13 unit tests for job_status pure functions"
```

---

### Task 2: Test `components/log_viewer.py`

**Files:**
- Create: `tests/test_log_viewer.py`
- Reference: `shyfem_ui/components/log_viewer.py` (lines 265–289)

**Step 1: Write the test file**

```python
"""Tests for log_viewer format_log_line function."""

import pytest

from shyfem_ui.components.log_viewer import LINE_TRUNCATE_LEN, format_log_line


# ── Plain text ───────────────────────────────────────────────────


def test_plain_text_passthrough():
    result = format_log_line("hello world")
    assert result == "hello world"


def test_empty_string():
    result = format_log_line("")
    assert result == ""


# ── HTML escaping / XSS ─────────────────────────────────────────


def test_xss_script_escaped():
    result = format_log_line("<script>alert('xss')</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_html_entities_escaped():
    result = format_log_line('a < b && c > "d"')
    assert "&lt;" in result
    assert "&amp;" in result
    assert "&gt;" in result
    assert "&quot;" in result


# ── Color highlighting ───────────────────────────────────────────


def test_error_line_red():
    result = format_log_line("ERROR: something failed")
    assert 'color: #f44747' in result
    assert "ERROR: something failed" in result


def test_warning_line_yellow():
    result = format_log_line("WARNING: low memory")
    assert 'color: #cca700' in result


def test_success_line_green():
    result = format_log_line("Task completed successfully")
    assert 'color: #4ec9b0' in result


def test_header_line_blue():
    result = format_log_line(">>> Starting phase 1")
    # ">>>" becomes "&gt;&gt;&gt;" after escaping, which triggers blue
    assert 'color: #569cd6' in result


def test_time_line_highlighted():
    result = format_log_line("time = 3600.0")
    assert 'color: #9cdcfe' in result


# ── Truncation ───────────────────────────────────────────────────


def test_short_line_not_truncated():
    line = "x" * 100
    result = format_log_line(line)
    assert "[truncated]" not in result


def test_long_line_truncated():
    line = "x" * (LINE_TRUNCATE_LEN + 100)
    result = format_log_line(line)
    assert "[truncated]" in result
    # Truncated output should not exceed original limit + marker length
    assert len(result) < LINE_TRUNCATE_LEN + 100


# ── Non-string input ────────────────────────────────────────────


def test_non_string_coerced():
    result = format_log_line(42)
    assert "42" in result


def test_none_coerced():
    result = format_log_line(None)
    assert "None" in result
```

**Step 2: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_log_viewer.py -v`
Expected: all 13 tests PASS

**Step 3: Commit**

```bash
git add tests/test_log_viewer.py
git commit -m "test: add 13 unit tests for log_viewer format_log_line"
```

---

### Task 3: Test `components/plot_widget.py`

**Files:**
- Create: `tests/test_plot_widget.py`
- Reference: `shyfem_ui/components/plot_widget.py` (lines 136–354)
- Reference: `shyfem_ui/services/parser_grd.py` (lines 29–63, 95–151)

Build a synthetic `GrdFile` with 4 nodes forming a square, 2 triangular elements,
and 1 boundary line. This is the minimal mesh that exercises all 4 plot functions.

```
Node layout:       Elements:        Line:
 3───4             [1,2,3]          [1,2] (type 1)
 |\ /|             [2,4,3]
 | X |
 |/ \|
 1───2
```

**Step 1: Write the test file**

```python
"""Tests for plot_widget pure plotting functions."""

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest

from shyfem_ui.components.plot_widget import (
    plot_boundaries,
    plot_depth_contour,
    plot_element_quality,
    plot_mesh,
)
from shyfem_ui.services.parser_grd import Element, GrdFile, Line, Node


@pytest.fixture
def sample_grd():
    """Build a minimal 4-node, 2-triangle grid with depths and a boundary."""
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
    lines = {
        1: Line(id=1, line_type=1, nodes=[1, 2]),
    }
    return GrdFile(nodes=nodes, elements=elements, lines=lines)


@pytest.fixture(autouse=True)
def close_figures():
    """Close all matplotlib figures after each test to prevent memory leaks."""
    yield
    plt.close("all")


# ── plot_mesh ────────────────────────────────────────────────────


def test_plot_mesh_returns_figure(sample_grd):
    fig = plot_mesh(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_mesh_title(sample_grd):
    fig = plot_mesh(sample_grd)
    ax = fig.axes[0]
    assert "4" in ax.get_title()
    assert "2" in ax.get_title()


def test_plot_mesh_show_nodes(sample_grd):
    fig = plot_mesh(sample_grd, show_nodes=True)
    assert isinstance(fig, plt.Figure)


def test_plot_mesh_show_labels(sample_grd):
    fig = plot_mesh(sample_grd, show_labels=True)
    assert isinstance(fig, plt.Figure)


# ── plot_depth_contour ───────────────────────────────────────────


def test_plot_depth_contour_returns_figure(sample_grd):
    fig = plot_depth_contour(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_depth_contour_title(sample_grd):
    fig = plot_depth_contour(sample_grd)
    ax = fig.axes[0]
    assert "Depth" in ax.get_title()


def test_plot_depth_contour_no_depth():
    """Grid with all None depths shows 'No depth data' message."""
    nodes = {
        1: Node(id=1, node_type=0, x=0.0, y=0.0, depth=None),
        2: Node(id=2, node_type=0, x=1.0, y=0.0, depth=None),
        3: Node(id=3, node_type=0, x=0.0, y=1.0, depth=None),
    }
    elements = {1: Element(id=1, elem_type=0, nodes=[1, 2, 3])}
    grd = GrdFile(nodes=nodes, elements=elements)
    fig = plot_depth_contour(grd)
    assert isinstance(fig, plt.Figure)


# ── plot_boundaries ──────────────────────────────────────────────


def test_plot_boundaries_returns_figure(sample_grd):
    fig = plot_boundaries(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_boundaries_title(sample_grd):
    fig = plot_boundaries(sample_grd)
    ax = fig.axes[0]
    assert "Boundaries" in ax.get_title()


# ── plot_element_quality ─────────────────────────────────────────


def test_plot_element_quality_returns_figure(sample_grd):
    fig = plot_element_quality(sample_grd)
    assert isinstance(fig, plt.Figure)


def test_plot_element_quality_title(sample_grd):
    fig = plot_element_quality(sample_grd)
    ax = fig.axes[0]
    assert "Quality" in ax.get_title()
    assert "2" in ax.get_title()  # 2 triangles
```

**Step 2: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_plot_widget.py -v`
Expected: all 11 tests PASS

**Step 3: Commit**

```bash
git add tests/test_plot_widget.py
git commit -m "test: add 11 unit tests for plot_widget pure functions"
```

---

### Task 4: Final Verification and TODO_NEXT.md Update

**Step 1: Run full test suite**

Run: `cd /home/razinka/shyfem/shyfem-ui && /opt/micromamba/envs/shiny/bin/python -m pytest tests/ -x -q --ignore=tests/test_playwright_dashboard.py --ignore=tests/test_playwright_navigation.py --ignore=tests/test_playwright_pages.py --ignore=tests/test_playwright_interactions.py`

Expected: 389+ tests pass (352 baseline + ~37 new), 0 new failures.

**Step 2: Update TODO_NEXT.md**

Mark Phase 22 items:
- [x] 22.1 — 13 tests for job_status pure functions
- 22.2 — Already has 9 tests from Phase 19 (no change needed)
- [x] 22.3 — 13 tests for log_viewer format_log_line
- [x] 22.4 — 11 tests for plot_widget pure functions

**Step 3: Commit**

```bash
git add TODO_NEXT.md
git commit -m "docs: mark Phase 22 component tests complete in TODO_NEXT.md"
```
