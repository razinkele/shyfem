"""Tests for the cached per-project summary service."""

import json

from shyfem_ui.services.project_summary import SUMMARY_NAME, build_summary, load_summary


def _grd(tmp_path):
    # minimal 3-node, 1-element .grd (ASCII SHYFEM grid format)
    grd = tmp_path / "mesh.grd"
    grd.write_text(
        "1 1 0 0.0 0.0 1.0\n" "1 2 0 1.0 0.0 2.0\n" "1 3 0 0.0 1.0 3.0\n" "2 4 0 3 1 2 3\n"
    )
    return grd


def test_build_summary_files_grid_forcing_observations(tmp_path):
    _grd(tmp_path)
    (tmp_path / "forcing").mkdir()
    (tmp_path / "forcing" / "river.txt").write_text(
        "1990-01-03::06:00:00   10.0\n1990-01-04::06:00:00   20.0\n"
    )
    (tmp_path / "observations.csv").write_text(
        "date,site,variable,value\n2001-01-01,Nida,level,516.0\n2001-01-02,Nida,level,518.0\n"
    )
    (tmp_path / "boxmodel.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "forcing": {"dir": "forcing"},
                "observations": {"file": "observations.csv"},
                "runs": [{"id": "run_a", "label": "Run A", "dir": "/x/run_a"}],
            }
        )
    )

    s = build_summary(tmp_path)
    assert s["schema"] == 1
    assert any(g["file"] == "mesh.grd" and g["nodes"] == 3 for g in s["grids"])
    assert any(f["file"] == "forcing/river.txt" for f in s["forcing"])
    fs = s["forcing"][0]["series"][0]
    assert fs["n"] == 2 and fs["min"] == 10.0 and fs["max"] == 20.0
    assert any(
        o["site"] == "Nida" and o["variable"] == "level" and o["n"] == 2 for o in s["observations"]
    )
    assert s["runs"][0]["label"] == "Run A" and s["runs"][0]["cache"] == "not built"


def test_load_summary_caches_and_reuses_until_stale(tmp_path):
    _grd(tmp_path)
    s1 = load_summary(tmp_path)
    assert (tmp_path / SUMMARY_NAME).is_file()
    # unchanged -> same built_at (served from cache, not rebuilt)
    s2 = load_summary(tmp_path)
    assert s1["built_at"] == s2["built_at"]
    # change a source grid -> stale -> rebuild
    import time

    time.sleep(0.01)
    (tmp_path / "mesh.grd").write_text(
        "1 1 0 0.0 0.0 5.0\n1 2 0 1.0 0.0 5.0\n1 3 0 0.0 1.0 5.0\n2 4 0 3 1 2 3\n"
    )
    s3 = load_summary(tmp_path)
    assert s3["built_at"] >= s2["built_at"]
    assert s3["grids"][0]["depth_max"] == 5.0
