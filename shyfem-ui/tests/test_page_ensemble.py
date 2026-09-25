"""Tests for ensemble page pure functions."""

from datetime import datetime, timedelta

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
    # Code truncates to label[:57] + f"_{index:03d}" = 61 chars max
    assert len(result) <= 61


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
        id="j1",
        name=name,
        tool_name="shyfem",
        args=[],
        working_dir="/tmp",
        status=status,
        progress=1.0,
        created_at=now,
        started_at=now,
        completed_at=now + timedelta(seconds=duration_s),
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


# ── project-file dropdowns (base STR / working dir) ──────────────


class TestPickerUiRenders:
    def test_dropdown_placeholders_present_and_no_text_boxes(self):
        from shyfem_ui.pages.ensemble import ensemble_ui

        html = str(ensemble_ui("test"))
        # Base STR and working directory are rendered dropdown placeholders ...
        assert 'id="test-base_str_file_picker"' in html
        assert 'id="test-working_dir_picker"' in html
        # ... not free-text path boxes (the closing quote keeps the
        # ``_picker`` ids from matching here).
        assert 'id="test-base_str_file"' not in html
        assert 'id="test-working_dir"' not in html
        # The ensemble name stays a text box.
        assert 'id="test-ensemble_name"' in html


class TestModuleWiring:
    def test_ensemble_renders_project_file_dropdowns(self):
        import shyfem_ui.pages.ensemble as ens_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(ens_mod, "ensemble_server")
        # Two render.ui dropdowns backed by a project-dir scan ...
        assert "def base_str_file_picker(" in src
        assert "def working_dir_picker(" in src
        # ... built on the shared project_select helpers, preselecting the
        # project's first simulation STR like the old text box auto-filled ...
        assert 'project_file_select(\n            "base_str_file"' in src
        assert 'default_project_file(proj, "str")' in src
        # ... and an empty working-dir default keeps the submit handler's
        # "<base STR dir>/<ensemble name>" fallback.
        assert 'project_dir_select(\n            "working_dir"' in src
        assert 'default_label="— next to the base STR file, named after the ensemble —"' in src
        # The old update_text auto-fill effect is gone.
        assert "def _on_project_changed(" not in src
        assert "update_text(" not in src
        # The handlers still read the same input ids (option values are
        # absolute paths, so their confinement is unchanged).
        assert "input.base_str_file()" in src
        assert "input.working_dir()" in src
