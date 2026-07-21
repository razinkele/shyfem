"""Tests for project export/import/clone service."""

import json
import zipfile
from io import BytesIO

import pytest

from shyfem_ui.services.project_export import (
    MANIFEST_VERSION,
    MAX_IMPORT_COMPRESSION_RATIO,
    MAX_IMPORT_FILES,
    MAX_IMPORT_UNCOMPRESSED_BYTES,
    clone_project,
    export_project,
    import_project,
)


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

    def test_manifest_includes_file_inventory(self, project_dir, project_meta):
        project_meta["files"] = [
            {"filename": "wind.txt", "rel_path": "INPUT/wind.txt",
             "file_type": "forcing", "size_bytes": 9},
        ]
        result = export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert "files" in manifest
            assert len(manifest["files"]) == 1
            assert manifest["files"][0]["filename"] == "wind.txt"

    def test_empty_project_dir(self, tmp_path, project_meta):
        empty = tmp_path / "empty"
        empty.mkdir()
        project_meta["grids"] = []
        project_meta["simulations"] = []
        result = export_project(empty, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()

    def test_export_skips_symlink_escape(self, tmp_path, project_meta):
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        (project / "link.txt").symlink_to(outside)

        result = export_project(project, project_meta)

        with zipfile.ZipFile(result) as zf:
            assert "link.txt" not in zf.namelist()


@pytest.fixture
def exported_zip(project_dir, project_meta):
    """Create an exported ZIP for import tests."""
    return export_project(project_dir, project_meta)


class TestImportProject:

    def test_import_creates_directory(self, exported_zip, tmp_path):
        result = import_project(exported_zip, tmp_path)
        assert result["work_dir"].is_dir()

    def test_import_extracts_files(self, exported_zip, tmp_path):
        result = import_project(exported_zip, tmp_path)
        wd = result["work_dir"]
        assert (wd / "GRID" / "mesh.grd").exists()
        assert (wd / "sim.str").exists()

    def test_import_returns_manifest_data(self, exported_zip, tmp_path):
        result = import_project(exported_zip, tmp_path)
        assert result["name"] == "Test Project"
        assert len(result["grids"]) == 1
        assert len(result["simulations"]) == 1

    def test_import_name_collision_appends_suffix(self, exported_zip, tmp_path):
        import_project(exported_zip, tmp_path)
        exported_zip.seek(0)
        result = import_project(exported_zip, tmp_path)
        assert result["name"] != "Test Project"
        assert result["name"].startswith("Test Project_")

    def test_import_rejects_missing_manifest(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("file.txt", "hello")
        buf.seek(0)
        with pytest.raises(ValueError, match="manifest.json"):
            import_project(buf, tmp_path)

    def test_import_rejects_bad_json(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", "not json")
        buf.seek(0)
        with pytest.raises(ValueError, match="manifest"):
            import_project(buf, tmp_path)

    def test_import_rejects_path_traversal(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            manifest = {
                "version": "1.0",
                "exported_at": "2026-01-01T00:00:00Z",
                "project": {"name": "evil", "description": None},
                "grids": [],
                "simulations": [],
            }
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("../../../etc/passwd", "pwned")
        buf.seek(0)
        with pytest.raises(ValueError, match="path traversal"):
            import_project(buf, tmp_path)

    def test_import_rejects_path_traversal_outside_project_dir(self, tmp_path):
        buf = BytesIO()
        base_name = tmp_path.name
        with zipfile.ZipFile(buf, "w") as zf:
            manifest = {
                "version": "1.0",
                "exported_at": "2026-01-01T00:00:00Z",
                "project": {"name": "project", "description": None},
                "grids": [],
                "simulations": [],
            }
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr(f"../{base_name}/escaped.txt", "pwned")
        buf.seek(0)

        with pytest.raises(ValueError, match="path traversal"):
            import_project(buf, tmp_path)
        assert not (tmp_path / base_name / "escaped.txt").exists()

    def test_import_rejects_missing_version(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            manifest = {
                "project": {"name": "test", "description": None},
                "grids": [],
                "simulations": [],
            }
            zf.writestr("manifest.json", json.dumps(manifest))
        buf.seek(0)
        with pytest.raises(ValueError, match="version"):
            import_project(buf, tmp_path)

    def test_import_rejects_too_many_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MAX_IMPORT_FILES",
            1,
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "version": "1.0",
                        "project": {"name": "many", "description": None},
                        "grids": [],
                        "simulations": [],
                    }
                ),
            )
            zf.writestr("a.txt", "a")
            zf.writestr("b.txt", "b")
        buf.seek(0)

        with pytest.raises(ValueError, match="too many files"):
            import_project(buf, tmp_path)

    def test_import_rejects_uncompressed_size_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MAX_IMPORT_UNCOMPRESSED_BYTES",
            5,
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "version": "1.0",
                        "project": {"name": "large", "description": None},
                        "grids": [],
                        "simulations": [],
                    }
                ),
            )
            zf.writestr("large.txt", "123456")
        buf.seek(0)

        with pytest.raises(ValueError, match="uncompressed size"):
            import_project(buf, tmp_path)

    def test_import_rejects_oversized_manifest_before_json_parse(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MAX_IMPORT_UNCOMPRESSED_BYTES",
            10,
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", "{" + " " * 1000)
        buf.seek(0)

        with pytest.raises(ValueError, match="uncompressed size"):
            import_project(buf, tmp_path)

    def test_import_rejects_suspicious_compression_ratio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MAX_IMPORT_COMPRESSION_RATIO",
            2,
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "version": "1.0",
                        "project": {"name": "bomb", "description": None},
                        "grids": [],
                        "simulations": [],
                    }
                ),
            )
            zf.writestr("zeros.txt", "0" * 1000)
        buf.seek(0)

        with pytest.raises(ValueError, match="compression ratio"):
            import_project(buf, tmp_path)

    def test_import_streams_extracted_members(self, exported_zip, tmp_path, monkeypatch):
        original_read = zipfile.ZipExtFile.read

        def guarded_read(self, size=-1):
            if self.name != "manifest.json":
                assert size not in (-1, None)
            return original_read(self, size)

        monkeypatch.setattr(zipfile.ZipExtFile, "read", guarded_read)

        result = import_project(exported_zip, tmp_path)
        assert (result["work_dir"] / "GRID" / "mesh.grd").exists()

    def test_import_limit_defaults_are_reasonable(self):
        assert MAX_IMPORT_FILES > 100
        assert MAX_IMPORT_UNCOMPRESSED_BYTES > 100 * 1024 * 1024
        assert MAX_IMPORT_COMPRESSION_RATIO > 10


class TestCloneProject:

    def test_clone_creates_new_directory(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        assert result["work_dir"].is_dir()
        assert result["work_dir"] != project_dir

    def test_clone_copies_files(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        wd = result["work_dir"]
        assert (wd / "GRID" / "mesh.grd").exists()
        assert (wd / "sim.str").exists()

    def test_clone_default_name(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        assert result["name"] == "Test Project (Copy)"

    def test_clone_custom_name(self, project_dir, project_meta):
        result = clone_project(
            project_dir, project_meta, project_dir.parent, new_name="My Clone"
        )
        assert result["name"] == "My Clone"

    def test_clone_returns_metadata(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        assert len(result["grids"]) == 1
        assert len(result["simulations"]) == 1

    def test_clone_excludes_logs(self, project_dir, project_meta):
        result = clone_project(project_dir, project_meta, project_dir.parent)
        wd = result["work_dir"]
        assert not list(wd.glob("*.stdout"))
        assert not list(wd.glob("*.stderr"))
