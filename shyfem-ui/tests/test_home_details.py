"""Tests for the Projects 'Details' popup helpers (home page)."""

from shyfem_ui.pages.home import _human_size, _project_files_block


def test_human_size_units():
    assert _human_size(0) == "0 B"
    assert _human_size(512) == "512 B"
    assert _human_size(1536) == "1.5 KB"
    assert _human_size(1_500_000) == "1.4 MB"


def test_project_files_block_lists_disk_files_and_skips_hidden(tmp_path):
    (tmp_path / "a.grd").write_text("x" * 10)
    sub = tmp_path / "forcing"
    sub.mkdir()
    (sub / "river.txt").write_text("y" * 20)
    hidden = tmp_path / ".boxmodel_cache"
    hidden.mkdir()
    (hidden / "cache.parquet").write_text("z" * 5)

    html = str(_project_files_block(str(tmp_path)))
    assert "a.grd" in html
    assert "forcing/river.txt" in html
    assert "cache.parquet" not in html  # hidden tree skipped


def test_project_files_block_empty(tmp_path):
    assert "No files on disk" in str(_project_files_block(str(tmp_path)))
