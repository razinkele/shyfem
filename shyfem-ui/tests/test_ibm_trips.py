"""Tests for IBM page trips_layer animation integration."""

from datetime import datetime

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
    from shyfem_ui.pages.ibm import _TRACK_COLORS, _tracks_to_trips

    tracks = [_make_track(type_id=1, n=3), _make_track(type_id=2, n=3)]
    result = _tracks_to_trips(tracks)
    assert result[0].get("color") == _TRACK_COLORS[0]
    assert result[1].get("color") == _TRACK_COLORS[1]


def test_tracks_to_trips_timestamps_normalized_to_loop():
    """Timestamps are normalized to 0.._TRIPS_LOOP_LENGTH animation units.

    The JS trips animation drives currentTime in 0..loopLength (wall-clock
    seconds x speed, modulo loopLength). Raw Unix epoch values (~1.7e9)
    would never be <= currentTime, so no trail segment could ever draw —
    which is exactly the bug this replaces (the old test pinned epoch
    floats as the contract)."""
    from shyfem_ui.pages.ibm import _TRIPS_LOOP_LENGTH, _tracks_to_trips

    tracks = [_make_track(type_id=1, n=3)]
    result = _tracks_to_trips(tracks)
    ts = result[0]["timestamps"]
    assert all(isinstance(t, float) for t in ts)
    assert ts[0] == pytest.approx(0.0)
    assert ts[-1] == pytest.approx(_TRIPS_LOOP_LENGTH)
    assert all(0.0 <= t <= _TRIPS_LOOP_LENGTH for t in ts)


def test_tracks_to_trips_normalization_is_global_across_tracks():
    """All tracks share one t0/scale: a track covering the second half of
    the time span must start mid-loop, not at 0."""
    from shyfem_ui.pages.ibm import _TRIPS_LOOP_LENGTH, _tracks_to_trips

    early = _make_track(type_id=1, n=3)  # hours 0,1,2
    late = _make_track(type_id=2, n=3)
    base = datetime(2026, 1, 1, 0, 0, 0)
    late.times = [base.replace(hour=h).isoformat(sep=" ") for h in (2, 3, 4)]

    result = _tracks_to_trips([early, late])
    ts_early, ts_late = result[0]["timestamps"], result[1]["timestamps"]
    # Global span is hours 0..4 -> early covers the first half of the loop,
    # late the second half.
    assert ts_early[0] == pytest.approx(0.0)
    assert ts_early[-1] == pytest.approx(_TRIPS_LOOP_LENGTH / 2)
    assert ts_late[0] == pytest.approx(_TRIPS_LOOP_LENGTH / 2)
    assert ts_late[-1] == pytest.approx(_TRIPS_LOOP_LENGTH)


def test_tracks_to_trips_zero_span_does_not_crash():
    """A single timestep (zero time span) yields all-zero timestamps."""
    from shyfem_ui.pages.ibm import _tracks_to_trips

    track = _make_track(type_id=1, n=1)
    result = _tracks_to_trips([track])
    assert result[0]["timestamps"] == [0.0]


def test_trips_layer_carries_animation_config():
    """The trips_layer call must pass _tripsAnimation — without it the JS
    startTripsAnimation() finds no animatable layer and currentTime stays 0
    forever (trails never draw, Play/Pause/Reset are no-ops)."""
    import inspect

    from shyfem_ui.pages import ibm

    src = inspect.getsource(ibm)
    assert "_tripsAnimation" in src, "trips_layer is missing the _tripsAnimation config"
    assert "_TRIPS_LOOP_LENGTH" in src, "loop length constant not used"


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
