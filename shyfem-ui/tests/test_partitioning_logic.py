"""Tests for pure helpers extracted from pages/partitioning.py."""

import pytest

from shyfem_ui.services.partitioning_logic import (
    compute_load_balance,
    validate_partition_files,
)


class TestComputeLoadBalance:

    def test_perfect_balance(self):
        result = compute_load_balance([100, 100, 100, 100])
        assert result["n_parts"] == 4
        assert result["avg"] == 100.0
        assert result["min"] == 100
        assert result["max"] == 100
        assert result["imbalance_pct"] == 0.0
        assert result["is_empty"] is False
        assert result["labels"] == ["P0", "P1", "P2", "P3"]

    def test_imbalanced(self):
        result = compute_load_balance([100, 50])
        assert result["avg"] == 75.0
        assert result["imbalance_pct"] == pytest.approx(50 / 75 * 100)

    def test_single_partition(self):
        result = compute_load_balance([42])
        assert result["n_parts"] == 1
        assert result["avg"] == 42.0
        assert result["imbalance_pct"] == 0.0

    def test_empty_input(self):
        result = compute_load_balance([])
        assert result["n_parts"] == 0
        assert result["is_empty"] is True
        assert result["imbalance_pct"] == 0.0

    def test_all_zero_elements(self):
        result = compute_load_balance([0, 0, 0])
        assert result["is_empty"] is True
        assert result["imbalance_pct"] == 0.0


class TestValidatePartitionFiles:

    def test_all_exist(self, tmp_path):
        f1 = tmp_path / "a.par"
        f2 = tmp_path / "b.par"
        f1.write_text("hello")
        f2.write_text("world!!")
        results = validate_partition_files([f1, f2])
        assert results[0][0] == "a.par"
        assert "5 bytes - OK" in results[0][1]
        assert results[1][0] == "b.par"
        assert "7 bytes - OK" in results[1][1]

    def test_missing_marked(self, tmp_path):
        f1 = tmp_path / "exists.par"
        f1.write_text("ok")
        f2 = tmp_path / "missing.par"  # not created
        results = validate_partition_files([f1, f2])
        assert results[0][1].endswith("OK")
        assert results[1] == ("missing.par", "MISSING")

    def test_accepts_string_paths(self, tmp_path):
        f1 = tmp_path / "x.par"
        f1.write_text("z")
        results = validate_partition_files([str(f1)])
        assert results[0][0] == "x.par"
