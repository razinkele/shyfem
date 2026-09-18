"""Tests for the Projects 'Details' popup helpers (home page)."""

from shyfem_ui.pages.home import _human_size, _project_files_block, _project_runs_block


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


def test_project_runs_block_lists_manifest_runs(tmp_path):
    import json

    (tmp_path / "boxmodel.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "runs": [
                    {"id": "run_a", "label": "Run A 1993-2016", "dir": "/x/run_a"},
                    {"id": "run_b", "label": "Run B", "dir": "/x/run_b"},
                ],
            }
        )
    )
    # a ready cache for run_a only
    cache = tmp_path / ".boxmodel_cache" / "run_a"
    cache.mkdir(parents=True)
    (cache / "meta.json").write_text(
        json.dumps({"period": {"start": "1993-01-01T00:00:00", "end": "2016-12-31T00:00:00"}})
    )

    html = str(_project_runs_block(str(tmp_path)))
    assert "Run A 1993-2016" in html
    assert "1993-01-01 → 2016-12-31" in html
    assert "ready" in html and "not built" in html  # run_b has no cache


def test_project_runs_block_none_without_manifest(tmp_path):
    assert _project_runs_block(str(tmp_path)) is None
