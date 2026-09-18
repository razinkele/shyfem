"""Tests for the Projects 'Details' popup render helpers (home page)."""

from shyfem_ui.pages.home import (
    _human_size,
    _summary_files_block,
    _summary_forcing_block,
    _summary_grids_block,
    _summary_obs_block,
    _summary_runs_block,
)


def test_human_size_units():
    assert _human_size(0) == "0 B"
    assert _human_size(512) == "512 B"
    assert _human_size(1536) == "1.5 KB"
    assert _human_size(1_500_000) == "1.4 MB"


def test_grids_block_shows_mesh_stats():
    s = {
        "grids": [
            {"file": "m.grd", "nodes": 1309, "elements": 2027, "depth_min": 0.5, "depth_max": 34.1}
        ]
    }
    html = str(_summary_grids_block(s))
    assert "m.grd" in html and "1309" in html and "2027" in html and "34.1" in html


def test_runs_block_and_none_when_empty():
    s = {"runs": [{"id": "r1", "label": "Run 1", "period": "1993 -> 2016", "cache": "ready"}]}
    html = str(_summary_runs_block(s))
    assert "Run 1" in html and "ready" in html
    assert _summary_runs_block({"runs": []}) is None


def test_forcing_block_stats():
    s = {
        "forcing": [
            {
                "file": "forcing/nemunas.txt",
                "series": [
                    {
                        "series": "value",
                        "n": 100,
                        "start": "1990-01-01",
                        "end": "2016-12-31",
                        "min": 1.0,
                        "max": 9.0,
                        "mean": 4.5,
                    }
                ],
            }
        ]
    }
    html = str(_summary_forcing_block(s))
    assert "forcing/nemunas.txt" in html and "100" in html and "4.50" in html


def test_obs_block_stats():
    s = {
        "observations": [
            {
                "site": "Nida",
                "variable": "level",
                "n": 50,
                "start": "2001",
                "end": "2014",
                "min": 3.0,
                "max": 6.0,
                "mean": 5.1,
            }
        ]
    }
    html = str(_summary_obs_block(s))
    assert "Nida" in html and "level" in html and "5.10" in html


def test_files_block_and_empty():
    html = str(_summary_files_block({"files": [{"path": "a.grd", "size": 1024}]}))
    assert "a.grd" in html and "1.0 KB" in html
    assert "No files on disk" in str(_summary_files_block({"files": []}))
