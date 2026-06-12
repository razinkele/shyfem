"""Tests for LgrService and trajectory parsing helpers."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from shyfem_ui.services.lgr_service import (
    LgrService,
    ParticleTrack,
    _parse_traj_file,
    filter_by_time,
)
from shyfem_ui.services.shyfem_wrapper import CommandResult


def _make_traj_content(rows: list[tuple]) -> str:
    """Build fake lagrange_mean_traj file content.
    rows: list of (date_str, lon, lat, depth, age)
    """
    lines = []
    for date, lon, lat, depth, age in rows:
        lines.append(
            f"{date:20s}{lon:14.5f}{lat:14.5f}{depth:10.3f}{age:10.3f}   1.000\n"
        )
    return "".join(lines)


def _make_ok_result(tmp_path: Path) -> CommandResult:
    return CommandResult(
        success=True,
        return_code=0,
        stdout="",
        stderr="",
        command="lgrelab",
        working_dir=str(tmp_path),
    )


def _make_fail_result(tmp_path: Path) -> CommandResult:
    return CommandResult(
        success=False,
        return_code=1,
        stdout="",
        stderr="lgrelab error: bad file",
        command="lgrelab",
        working_dir=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# _parse_traj_file
# ---------------------------------------------------------------------------


def test_parse_empty_file(tmp_path):
    """Empty file returns empty list without error."""
    f = tmp_path / "lagrange_mean_traj.1"
    f.write_text("")
    assert _parse_traj_file(f) == []


def test_parse_single_particle_three_steps(tmp_path):
    """Single particle, 3 timesteps → correct lon/lat/date."""
    content = _make_traj_content([
        ("2020-01-01 00:00:00", -0.82, 37.73, 0.0, 0.0),
        ("2020-01-01 01:00:00", -0.81, 37.74, 1.0, 3600.0),
        ("2020-01-01 02:00:00", -0.80, 37.75, 2.0, 7200.0),
    ])
    f = tmp_path / "lagrange_mean_traj.1"
    f.write_text(content)

    rows = _parse_traj_file(f)

    assert len(rows) == 3
    assert rows[0]["lon"] == pytest.approx(-0.82, abs=1e-4)
    assert rows[0]["lat"] == pytest.approx(37.73, abs=1e-4)
    assert rows[1]["date"] == "2020-01-01 01:00:00"
    assert rows[2]["depth"] == pytest.approx(2.0, abs=1e-3)


def test_parse_skips_malformed_lines(tmp_path):
    """Lines with too few tokens or non-numeric values are skipped."""
    content = "not enough tokens\n"
    content += _make_traj_content([("2020-01-01 00:00:00", 0.0, 0.0, 0.0, 0.0)])
    f = tmp_path / "lagrange_mean_traj.1"
    f.write_text(content)

    rows = _parse_traj_file(f)
    assert len(rows) == 1  # only the valid line


def test_parse_real_lgrelab_double_colon_dates(tmp_path):
    """lgrelab (dts_format_abs_time) writes the 20-char date field as
    "YYYY-MM-DD::HH:MM:SS" — a SINGLE whitespace token, not the two-token
    "date time" form this parser originally assumed. The parser must accept
    it and normalize to "YYYY-MM-DD HH:MM:SS" (what filter_by_time compares
    and datetime.fromisoformat in the trips layer consumes).

    Lines are verbatim from a real `lgrelab -lgmean` run (SHYFEM 8.1.1,
    mar_menor lagrangian test case)."""
    content = (
        "2009-01-01::01:00:00      -0.77950      37.68294"
        "     2.751     0.045     0.000     0.000\n"
        "2009-01-01::02:00:00      -0.77848      37.68182"
        "     2.773     0.087     0.000     0.000\n"
    )
    f = tmp_path / "lagrange_mean_traj.1"
    f.write_text(content)

    rows = _parse_traj_file(f)

    assert len(rows) == 2
    assert rows[0]["date"] == "2009-01-01 01:00:00"
    assert rows[0]["lon"] == pytest.approx(-0.77950, abs=1e-5)
    assert rows[0]["lat"] == pytest.approx(37.68294, abs=1e-5)
    assert rows[1]["date"] == "2009-01-01 02:00:00"
    assert rows[1]["depth"] == pytest.approx(2.773, abs=1e-3)
    assert rows[1]["age"] == pytest.approx(0.087, abs=1e-3)


# ---------------------------------------------------------------------------
# filter_by_time
# ---------------------------------------------------------------------------


def _make_track() -> ParticleTrack:
    return ParticleTrack(
        type_id=1,
        path=[[-0.82, 37.73], [-0.81, 37.74], [-0.80, 37.75]],
        times=["2020-01-01 00:00:00", "2020-01-01 01:00:00", "2020-01-01 02:00:00"],
        depths=[0.0, 1.0, 2.0],
        ages=[0.0, 3600.0, 7200.0],
    )


def test_filter_no_range_returns_all_steps():
    """No tmin/tmax → all timesteps retained."""
    track = _make_track()
    result = filter_by_time([track], None, None)
    assert len(result) == 1
    assert len(result[0].path) == 3


def test_filter_tmin_trims_early_steps():
    """tmin removes steps before the cutoff."""
    track = _make_track()
    result = filter_by_time([track], tmin="2020-01-01 01:00:00", tmax=None)
    assert len(result[0].path) == 2
    assert result[0].times[0] == "2020-01-01 01:00:00"


def test_filter_removes_track_with_no_matching_steps():
    """Track with all steps outside range is dropped entirely."""
    track = _make_track()
    result = filter_by_time([track], tmin="2020-01-02 00:00:00", tmax=None)
    assert result == []


def test_filter_empty_string_treated_as_no_bound():
    """Empty string tmax should behave like None, not filter everything out."""
    track = _make_track()
    result = filter_by_time([track], tmin="2020-01-01 01:00:00", tmax="")
    assert len(result[0].path) == 2  # same result as tmax=None


def test_filter_tmax_trims_late_steps():
    """tmax removes steps after the cutoff (inclusive bound)."""
    track = _make_track()
    result = filter_by_time([track], tmin=None, tmax="2020-01-01 01:00:00")
    assert len(result) == 1
    assert len(result[0].path) == 2
    assert result[0].times[-1] == "2020-01-01 01:00:00"


# ---------------------------------------------------------------------------
# LgrService.load
# ---------------------------------------------------------------------------


def test_lgr_service_file_not_found(tmp_path):
    """FileNotFoundError raised for missing .lgr file."""
    mock_wrapper = MagicMock()
    svc = LgrService(mock_wrapper)
    with pytest.raises(FileNotFoundError):
        asyncio.run(svc.load(tmp_path / "missing.lgr"))


def test_lgr_service_lgrelab_failure_raises(tmp_path):
    """RuntimeError raised when lgrelab returns non-zero exit code."""
    lgr = tmp_path / "test.lgr"
    lgr.touch()

    mock_wrapper = MagicMock()
    mock_wrapper.run_command = AsyncMock(return_value=_make_fail_result(tmp_path))
    svc = LgrService(mock_wrapper)

    with pytest.raises(RuntimeError, match="lgrelab failed"):
        asyncio.run(svc.load(lgr))


def test_lgr_service_no_output_files_returns_empty(tmp_path):
    """Empty result when lgrelab succeeds but writes no traj files."""
    lgr = tmp_path / "test.lgr"
    lgr.touch()

    # lgrelab succeeds but doesn't write any files (e.g. empty lgr)
    mock_wrapper = MagicMock()
    mock_wrapper.run_command = AsyncMock(return_value=_make_ok_result(tmp_path))
    svc = LgrService(mock_wrapper)

    # The mock returns success but lgrelab never runs, so no lagrange_mean_traj.*
    # files are written to the internal tmpdir created by LgrService.load → returns []
    result = asyncio.run(svc.load(lgr))
    assert result == []
