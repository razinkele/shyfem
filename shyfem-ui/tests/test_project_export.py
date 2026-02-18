"""Tests for project export/import/clone service."""

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from shyfem_ui.services.project_export import export_project, MANIFEST_VERSION


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project directory with grid and str files."""
    d = tmp_path / "test_project"
    d.mkdir()
    (d / "GRID").mkdir()
    (d / "GRID" / "mesh.grd").write_text("grid data")
    (d / "GRID" / "mesh.bas").write_text("bas data")
    (d / "INPUT").mkdir()
    (d / "INPUT" / "wind.txt").write_text("wind data")
    (d / "sim.str").write_text("$title\nTest\n$end\n")
    # Job log files that should be excluded
    (d / "abc-123.stdout").write_text("stdout log")
    (d / "abc-123.stderr").write_text("stderr log")
    return d


@pytest.fixture
def project_meta():
    """Project metadata dict (mimics DB query result)."""
    return {
        "name": "Test Project",
        "description": "A test project",
        "grids": [
            {
                "name": "mesh",
                "description": None,
                "grd_file": "GRID/mesh.grd",
                "bas_file": "GRID/mesh.bas",
                "num_nodes": 100,
                "num_elements": 200,
                "num_layers": None,
                "min_depth": 0.5,
                "max_depth": 20.0,
            }
        ],
        "simulations": [
            {
                "name": "sim",
                "description": None,
                "str_file": "sim.str",
                "grid_name": "mesh",
                "start_time": "2020-01-01",
                "end_time": "2020-01-02",
                "time_step": 300.0,
                "mpi_enabled": False,
                "mpi_np": 1,
            }
        ],
    }


class TestExportProject:

    def test_returns_valid_zip(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        assert isinstance(result, BytesIO)
        with zipfile.ZipFile(result) as zf:
            assert zf.testzip() is None  # no corrupt files

    def test_zip_contains_manifest(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == MANIFEST_VERSION
            assert manifest["project"]["name"] == "Test Project"

    def test_zip_contains_project_files(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "GRID/mesh.grd" in names
            assert "GRID/mesh.bas" in names
            assert "INPUT/wind.txt" in names
            assert "sim.str" in names

    def test_zip_excludes_log_files(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert not any(n.endswith(".stdout") for n in names)
            assert not any(n.endswith(".stderr") for n in names)

    def test_manifest_has_grids_and_simulations(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert len(manifest["grids"]) == 1
            assert manifest["grids"][0]["name"] == "mesh"
            assert len(manifest["simulations"]) == 1
            assert manifest["simulations"][0]["name"] == "sim"

    def test_manifest_has_exported_at(self, project_dir, project_meta):
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert "exported_at" in manifest

    def test_empty_project_dir(self, tmp_path, project_meta):
        empty = tmp_path / "empty"
        empty.mkdir()
        project_meta["grids"] = []
        project_meta["simulations"] = []
        result = export_project(empty, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()
