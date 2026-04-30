"""Tests for pure helpers extracted from pages/partitioning.py."""
import pytest

from shyfem_ui.services.partitioning_logic import (
    analyze_partitions,
    compute_load_balance,
    parse_par_file,
    validate_partition_files,
)


class TestParseParFile:

    def test_returns_empty_for_missing_file(self, tmp_path):
        assert parse_par_file(tmp_path / "missing.par") == []

    def test_parses_one_id_per_line(self, tmp_path):
        f = tmp_path / "p.par"
        f.write_text("1\n42\n7\n")
        assert parse_par_file(f) == [1, 42, 7]

    def test_takes_first_token_per_line(self, tmp_path):
        f = tmp_path / "p.par"
        f.write_text("1 some_metadata\n2  more\n3\n")
        assert parse_par_file(f) == [1, 2, 3]

    def test_skips_blank_lines(self, tmp_path):
        f = tmp_path / "p.par"
        f.write_text("1\n\n\n2\n")
        assert parse_par_file(f) == [1, 2]

    def test_skips_malformed_lines(self, tmp_path):
        f = tmp_path / "p.par"
        f.write_text("1\nfoo\n2\n# comment\n3\n")
        assert parse_par_file(f) == [1, 2, 3]


class TestAnalyzePartitions:

    def test_happy_path_4_parts(self, tmp_path):
        # Create 4 partition files
        # Partition i gets element IDs: 10*i .. 10*i+4  (5 elements each)
        # P0: [0..4], P1: [10..14], P2: [20..24], P3: [30..34]
        for i in range(4):
            (tmp_path / f"partition.{i:04d}.par").write_text(
                "\n".join(str(j) for j in range(10 * i, 10 * i + 5)) + "\n"
            )
        stats, pmap = analyze_partitions(tmp_path, 4)
        assert stats["num_partitions"] == 4
        assert len(stats["partition_files"]) == 4
        assert stats["elements_per_partition"] == [5, 5, 5, 5]
        assert pmap[0] == 0
        assert pmap[14] == 1
        assert pmap[34] == 3

    def test_missing_files_skipped(self, tmp_path):
        # Only 2 of 4 files exist
        (tmp_path / "partition.0000.par").write_text("1\n2\n")
        (tmp_path / "partition.0002.par").write_text("3\n4\n")
        stats, pmap = analyze_partitions(tmp_path, 4)
        assert stats["num_partitions"] == 4
        assert len(stats["partition_files"]) == 2
        assert stats["elements_per_partition"] == [2, 2]
        assert pmap == {1: 0, 2: 0, 3: 2, 4: 2}

    def test_empty_dir_returns_empty_stats(self, tmp_path):
        stats, pmap = analyze_partitions(tmp_path, 4)
        assert stats["num_partitions"] == 4
        assert stats["partition_files"] == []
        assert stats["elements_per_partition"] == []
        assert pmap == {}


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
