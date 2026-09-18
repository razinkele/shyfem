"""Tests for the shared project-file listing helper."""

from shyfem_ui.services.project_files import list_project_files


def test_lists_matching_files_recursively_and_skips_hidden(tmp_path):
    (tmp_path / "a.csv").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "c.grd").write_text("x")  # wrong ext
    sub = tmp_path / "forcing"
    sub.mkdir()
    (sub / "river.txt").write_text("x")  # recursive
    hidden = tmp_path / ".boxmodel_cache"
    hidden.mkdir()
    (hidden / "d.csv").write_text("x")  # hidden tree -> skipped

    got = list_project_files(tmp_path, (".csv", ".txt"))
    assert set(got) == {"a.csv", "b.txt", "forcing/river.txt"}


def test_case_insensitive_and_empty_exts(tmp_path):
    (tmp_path / "UPPER.CSV").write_text("x")
    assert list_project_files(tmp_path, (".csv",)) == ["UPPER.CSV"]
    assert list_project_files(tmp_path, ()) == []


def test_respects_max_files_cap(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.csv").write_text("x")
    assert len(list_project_files(tmp_path, (".csv",), max_files=3)) == 3
