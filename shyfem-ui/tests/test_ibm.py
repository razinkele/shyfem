"""Tests for IBM page module."""

import inspect
import math

import pytest
from shiny.ui import Tag

from shyfem_ui.pages import ibm
from shyfem_ui.pages.ibm import _haversine_km, compute_track_stats
from shyfem_ui.services.lgr_service import ParticleTrack

pytest.importorskip("shiny_deckgl")


def test_ibm_ui_renders():
    """ibm_ui() returns a non-None Shiny Tag."""
    tag = ibm.ibm_ui("ibm_test")
    assert tag is not None
    assert isinstance(tag, Tag)


def test_no_demo_constants():
    """_DEMO_PARTICLES and _DEMO_TRACKS must not exist in ibm.py."""
    source = inspect.getsource(ibm)
    assert "_DEMO_PARTICLES" not in source, "Remove _DEMO_PARTICLES from ibm.py"
    assert "_DEMO_TRACKS" not in source, "Remove _DEMO_TRACKS from ibm.py"


def test_no_coming_soon_notification():
    """The demo 'coming soon' notification text must be removed."""
    source = inspect.getsource(ibm)
    assert "full simulation integration coming soon" not in source


def test_ibm_status_not_hardcoded_demo():
    """ibm_status must not contain the hardcoded 'Demo mode' badge text."""
    source = inspect.getsource(ibm)
    assert '"Demo mode"' not in source
    assert "'Demo mode'" not in source


def test_lgr_path_input_present():
    """UI must include a .lgr file path input."""
    source = inspect.getsource(ibm)
    assert '"lgr_path"' in source or "'lgr_path'" in source


def test_load_btn_present():
    """UI must include a load trajectories button."""
    source = inspect.getsource(ibm)
    assert '"load_btn"' in source or "'load_btn'" in source


def test_stats_panel_output_present():
    """UI must include the stats panel output."""
    source = inspect.getsource(ibm)
    assert "ibm_stats_panel" in source


class TestHaversine:
    """Tests for haversine distance helper."""

    def test_same_point_zero(self):
        assert _haversine_km(12.0, 45.0, 12.0, 45.0) == 0.0

    def test_known_distance(self):
        # London (51.5074, -0.1278) to Paris (48.8566, 2.3522) ~ 343 km
        d = _haversine_km(-0.1278, 51.5074, 2.3522, 48.8566)
        assert 340 < d < 350

    def test_symmetry(self):
        d1 = _haversine_km(0, 0, 1, 1)
        d2 = _haversine_km(1, 1, 0, 0)
        assert abs(d1 - d2) < 0.001


class TestComputeTrackStats:
    """Tests for per-type particle statistics."""

    def _make_track(self, type_id=1, n=5):
        return ParticleTrack(
            type_id=type_id,
            path=[[12.0 + i * 0.01, 45.0 + i * 0.01] for i in range(n)],
            times=[f"2026-01-01 0{i}:00:00" for i in range(n)],
            depths=[float(i) for i in range(n)],
            ages=[float(i * 100) for i in range(n)],
        )

    def test_empty_tracks(self):
        assert compute_track_stats([]) == []

    def test_single_point_track_excluded(self):
        t = ParticleTrack(type_id=1, path=[[12.0, 45.0]], times=["t0"], depths=[0], ages=[0])
        assert compute_track_stats([t]) == []

    def test_basic_stats(self):
        stats = compute_track_stats([self._make_track()])
        assert len(stats) == 1
        s = stats[0]
        assert s["type_id"] == 1
        assert s["steps"] == 5
        assert s["displacement_km"] > 0
        assert s["mean_depth"] == 2.0  # mean of 0,1,2,3,4
        assert s["max_depth"] == 4.0
        assert s["mean_age"] == 200.0  # mean of 0,100,200,300,400

    def test_multiple_types(self):
        stats = compute_track_stats([self._make_track(1), self._make_track(2)])
        assert len(stats) == 2
        assert stats[0]["type_id"] == 1
        assert stats[1]["type_id"] == 2

    def test_duration_format(self):
        stats = compute_track_stats([self._make_track()])
        assert "→" in stats[0]["duration"]
        assert "2026-01-01" in stats[0]["duration"]
