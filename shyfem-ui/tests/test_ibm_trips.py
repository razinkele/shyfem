"""Tests for IBM page trips_layer animation integration."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from shyfem_ui.services.lgr_service import ParticleTrack


def _make_track(type_id=1, n=5):
    """Create a simple ParticleTrack for testing."""
    base = datetime(2026, 1, 1, 0, 0, 0)
    return ParticleTrack(
        type_id=type_id,
        path=[[12.0 + i * 0.01, 45.0 + i * 0.01] for i in range(n)],
        times=[(base.replace(hour=i)).isoformat(sep=" ") for i in range(n)],
        depths=[float(i) for i in range(n)],
        ages=[float(i * 3600) for i in range(n)],
    )


def test_ibm_ui_no_time_range_output():
    """IBM UI must not contain time_range_controls output."""
    from shyfem_ui.pages.ibm import ibm_ui
    html = str(ibm_ui("test_ibm"))
    assert "time_range_controls" not in html, "time_range_controls output should be removed"


def test_ibm_ui_contains_trips_animation():
    """IBM UI should contain trips animation controls."""
    from shyfem_ui.pages.ibm import ibm_ui
    html = str(ibm_ui("test_ibm2"))
    # trips_animation_ui generates a module with the given id
    assert "ibm_trips" in html, "trips_animation_ui module ID should be in the UI"


def test_tracks_to_trips_basic():
    """_tracks_to_trips converts ParticleTrack list to format_trips output."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    tracks = [_make_track(type_id=1, n=3)]
    result = _tracks_to_trips(tracks)
    assert isinstance(result, list)
    assert len(result) == 1
    assert "path" in result[0]
    assert "timestamps" in result[0]


def test_tracks_to_trips_empty():
    """Empty input produces empty output."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    result = _tracks_to_trips([])
    assert result == []


def test_tracks_to_trips_preserves_colors():
    """Per-type colors from _TRACK_COLORS are passed through."""
    from shyfem_ui.pages.ibm import _tracks_to_trips, _TRACK_COLORS
    tracks = [_make_track(type_id=1, n=3), _make_track(type_id=2, n=3)]
    result = _tracks_to_trips(tracks)
    assert result[0].get("color") == _TRACK_COLORS[0]
    assert result[1].get("color") == _TRACK_COLORS[1]


def test_tracks_to_trips_timestamps_are_floats():
    """Output timestamps are Unix epoch floats, not ISO strings."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    tracks = [_make_track(type_id=1, n=3)]
    result = _tracks_to_trips(tracks)
    ts = result[0]["timestamps"]
    assert all(isinstance(t, float) for t in ts)
    # First timestamp should be 2026-01-01 00:00:00
    assert ts[0] == pytest.approx(datetime(2026, 1, 1, 0, 0, 0).timestamp(), abs=1)


def test_tracks_to_trips_timestamps_monotonic():
    """Output timestamps are monotonically increasing per track."""
    from shyfem_ui.pages.ibm import _tracks_to_trips
    tracks = [_make_track(type_id=1, n=5)]
    result = _tracks_to_trips(tracks)
    ts = result[0]["timestamps"]
    for i in range(1, len(ts)):
        assert ts[i] > ts[i - 1], f"Timestamps not monotonic at index {i}"


def test_path_layer_not_imported():
    """ibm.py must not expose path_layer in its module namespace.

    trips_layer replaces path_layer; having path_layer in the namespace
    would mean it was imported (intentionally or accidentally).
    """
    import shyfem_ui.pages.ibm as ibm_mod

    assert not hasattr(ibm_mod, "path_layer"), (
        "path_layer is present in ibm module namespace — it should have been "
        "replaced by trips_layer"
    )
