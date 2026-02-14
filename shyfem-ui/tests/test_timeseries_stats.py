"""Tests for compute_statistics() in components/timeseries.py."""

import numpy as np
import pytest

from shyfem_ui.components.timeseries import compute_statistics


class TestComputeStatistics:
    """Tests for compute_statistics()."""

    def test_basic_stats(self):
        values = [1, 2, 3, 4, 5]
        stats = compute_statistics(values)
        assert stats["min"] == 1.0
        assert stats["max"] == 5.0
        assert stats["mean"] == 3.0
        assert stats["count"] == 5
        assert stats["range"] == 4.0

    def test_std_deviation(self):
        values = [2, 4, 4, 4, 5, 5, 7, 9]
        stats = compute_statistics(values)
        assert stats["std"] == pytest.approx(2.0, abs=0.01)

    def test_percentiles(self):
        values = list(range(1, 101))  # 1..100
        stats = compute_statistics(values)
        assert stats["p25"] == pytest.approx(25.75, abs=0.1)
        assert stats["p50"] == pytest.approx(50.5, abs=0.1)
        assert stats["p75"] == pytest.approx(75.25, abs=0.1)

    def test_single_value(self):
        stats = compute_statistics([42.0])
        assert stats["min"] == 42.0
        assert stats["max"] == 42.0
        assert stats["mean"] == 42.0
        assert stats["std"] == 0.0
        assert stats["range"] == 0.0
        assert stats["count"] == 1

    def test_empty_input(self):
        stats = compute_statistics([])
        assert stats["min"] is None
        assert stats["max"] is None
        assert stats["mean"] is None
        assert stats["count"] == 0

    def test_nan_values_filtered(self):
        values = [1, 2, float("nan"), 4, float("nan")]
        stats = compute_statistics(values)
        assert stats["count"] == 3
        assert stats["min"] == 1.0
        assert stats["max"] == 4.0

    def test_all_nan(self):
        stats = compute_statistics([float("nan"), float("nan")])
        assert stats["min"] is None
        assert stats["count"] == 0

    def test_numpy_array_input(self):
        arr = np.array([10.0, 20.0, 30.0])
        stats = compute_statistics(arr)
        assert stats["mean"] == 20.0
        assert stats["count"] == 3

    def test_negative_values(self):
        values = [-5, -3, -1, 0, 2]
        stats = compute_statistics(values)
        assert stats["min"] == -5.0
        assert stats["max"] == 2.0
        assert stats["range"] == 7.0
