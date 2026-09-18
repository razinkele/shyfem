"""Tests for project export/import/clone service."""

import asyncio
import json
import time
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

    async def test_returns_valid_zip(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta)
        assert isinstance(result, BytesIO)
        with zipfile.ZipFile(result) as zf:
            assert zf.testzip() is None  # no corrupt files

    async def test_zip_contains_manifest(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["version"] == MANIFEST_VERSION
            assert manifest["project"]["name"] == "Test Project"

    async def test_zip_contains_project_files(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "GRID/mesh.grd" in names
            assert "GRID/mesh.bas" in names
            assert "INPUT/wind.txt" in names
            assert "sim.str" in names

    async def test_zip_excludes_the_boxmodel_cache(self, project_dir, project_meta):
        """Spec §9: the derived Parquet cache is rebuilt from the run output,
        so it must never be swept into an export (nor count toward its size
        cap). The whole subtree goes, not just the top-level entry."""
        cache = project_dir / ".boxmodel_cache" / "fix"
        cache.mkdir(parents=True)
        (cache / "meta.json").write_text('{"schema": 1}')
        (cache / "state_daily.parquet").write_bytes(b"parquet" * 100)
        (project_dir / ".boxmodel_cache" / "fix.tmp-abc").mkdir()
        (project_dir / ".boxmodel_cache" / "fix.tmp-abc" / "progress.json").write_text("{}")

        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert not any(".boxmodel_cache" in n for n in names), names
        # ... while the ordinary project files are still there
        assert "GRID/mesh.grd" in names and "sim.str" in names

    async def test_cache_bytes_do_not_count_toward_the_export_cap(self, project_dir, project_meta):
        """The exclusion happens before the size accounting, so a large cache
        cannot push a legitimately small project over max_export_bytes."""
        cache = project_dir / ".boxmodel_cache" / "fix"
        cache.mkdir(parents=True)
        (cache / "state_daily.parquet").write_bytes(b"x" * 100_000)

        result = await export_project(project_dir, project_meta, max_export_bytes=10_000)
        with zipfile.ZipFile(result) as zf:
            assert "sim.str" in zf.namelist()

    async def test_zip_excludes_log_files(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert not any(n.endswith(".stdout") for n in names)
            assert not any(n.endswith(".stderr") for n in names)

    async def test_manifest_has_grids_and_simulations(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert len(manifest["grids"]) == 1
            assert manifest["grids"][0]["name"] == "mesh"
            assert len(manifest["simulations"]) == 1
            assert manifest["simulations"][0]["name"] == "sim"

    async def test_manifest_has_exported_at(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert "exported_at" in manifest

    async def test_manifest_includes_file_inventory(self, project_dir, project_meta):
        project_meta["files"] = [
            {
                "filename": "wind.txt",
                "rel_path": "INPUT/wind.txt",
                "file_type": "forcing",
                "size_bytes": 9,
            },
        ]
        result = await export_project(project_dir, project_meta)
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert "files" in manifest
            assert len(manifest["files"]) == 1
            assert manifest["files"][0]["filename"] == "wind.txt"

    async def test_empty_project_dir(self, tmp_path, project_meta):
        empty = tmp_path / "empty"
        empty.mkdir()
        project_meta["grids"] = []
        project_meta["simulations"] = []
        result = await export_project(empty, project_meta)
        with zipfile.ZipFile(result) as zf:
            assert "manifest.json" in zf.namelist()

    async def test_export_skips_symlink_escape(self, tmp_path, project_meta):
        project = tmp_path / "project"
        project.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        (project / "link.txt").symlink_to(outside)

        result = await export_project(project, project_meta)

        with zipfile.ZipFile(result) as zf:
            assert "link.txt" not in zf.namelist()


class TestExportProjectAsync:
    """N47: export_project must not block the Shiny event loop."""

    async def test_export_does_not_block_event_loop(self, project_dir, project_meta, monkeypatch):
        """Monkeypatch the (private) sync zip-building body to sleep, then
        prove a concurrently-scheduled coroutine keeps ticking while the
        export runs -- i.e. the blocking work is off the event loop thread."""
        import shyfem_ui.services.project_export as pe

        original_sync = pe._export_project_sync

        def slow_sync(*args, **kwargs):
            time.sleep(0.5)
            return original_sync(*args, **kwargs)

        monkeypatch.setattr(pe, "_export_project_sync", slow_sync)

        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.05)
                ticks += 1

        ticker_task = asyncio.ensure_future(ticker())
        try:
            await export_project(project_dir, project_meta)
        finally:
            ticker_task.cancel()

        # 0.5s of blocking work with a 0.05s ticker should yield roughly 10
        # ticks if the loop was never blocked; require a healthy margin.
        assert ticks >= 5, (
            f"event loop only ticked {ticks} times during export -- "
            "export_project is blocking the loop instead of running in a thread"
        )

    async def test_export_uses_config_max_export_bytes_by_default(
        self, project_dir, project_meta, monkeypatch
    ):
        """The wrapper must resolve the cap from get_config() when the caller
        does not pass max_export_bytes explicitly -- pins the production wiring,
        not just the explicit-parameter path."""
        import shyfem_ui.services.project_export as pe
        from shyfem_ui.config import Config

        fake_config = Config(max_export_bytes=1)
        monkeypatch.setattr(pe, "get_config", lambda: fake_config)

        with pytest.raises(ValueError, match="exceeds"):
            await export_project(project_dir, project_meta)


class TestExportSizeCap:
    """N47: export refuses beyond max_export_bytes."""

    async def test_export_refuses_beyond_max_export_bytes(self, project_dir, project_meta):
        with pytest.raises(ValueError, match="exceeds"):
            await export_project(project_dir, project_meta, max_export_bytes=1)

    async def test_export_succeeds_within_max_export_bytes(self, project_dir, project_meta):
        result = await export_project(project_dir, project_meta, max_export_bytes=10**9)
        assert isinstance(result, BytesIO)

    def test_config_default_max_export_bytes_is_two_gib(self):
        from shyfem_ui.config import Config

        assert Config().max_export_bytes == 2 * 1024 * 1024 * 1024


@pytest.fixture
async def exported_zip(project_dir, project_meta):
    """Create an exported ZIP for import tests."""
    return await export_project(project_dir, project_meta)


class TestImportProject:

    async def test_import_creates_directory(self, exported_zip, tmp_path):
        result = await import_project(exported_zip, tmp_path)
        assert result["work_dir"].is_dir()

    async def test_import_extracts_files(self, exported_zip, tmp_path):
        result = await import_project(exported_zip, tmp_path)
        wd = result["work_dir"]
        assert (wd / "GRID" / "mesh.grd").exists()
        assert (wd / "sim.str").exists()

    async def test_import_returns_manifest_data(self, exported_zip, tmp_path):
        result = await import_project(exported_zip, tmp_path)
        assert result["name"] == "Test Project"
        assert len(result["grids"]) == 1
        assert len(result["simulations"]) == 1

    async def test_import_name_collision_appends_suffix(self, exported_zip, tmp_path):
        await import_project(exported_zip, tmp_path)
        exported_zip.seek(0)
        result = await import_project(exported_zip, tmp_path)
        assert result["name"] != "Test Project"
        assert result["name"].startswith("Test Project_")

    async def test_import_rejects_missing_manifest(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("file.txt", "hello")
        buf.seek(0)
        with pytest.raises(ValueError, match="manifest.json"):
            await import_project(buf, tmp_path)

    async def test_import_rejects_bad_json(self, tmp_path):
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("manifest.json", "not json")
        buf.seek(0)
        with pytest.raises(ValueError, match="manifest"):
            await import_project(buf, tmp_path)

    async def test_import_rejects_path_traversal(self, tmp_path):
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
            await import_project(buf, tmp_path)

    async def test_import_rejects_path_traversal_outside_project_dir(self, tmp_path):
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
            await import_project(buf, tmp_path)
        assert not (tmp_path / base_name / "escaped.txt").exists()

    async def test_import_rejects_missing_version(self, tmp_path):
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
            await import_project(buf, tmp_path)

    async def test_import_rejects_too_many_files(self, tmp_path, monkeypatch):
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
            await import_project(buf, tmp_path)

    async def test_import_rejects_uncompressed_size_limit(self, tmp_path, monkeypatch):
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
            await import_project(buf, tmp_path)

    async def test_import_rejects_oversized_manifest_before_json_parse(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MAX_IMPORT_UNCOMPRESSED_BYTES",
            10,
        )
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", "{" + " " * 1000)
        buf.seek(0)

        with pytest.raises(ValueError, match="uncompressed size"):
            await import_project(buf, tmp_path)

    async def test_import_rejects_suspicious_compression_ratio(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MAX_IMPORT_COMPRESSION_RATIO",
            2,
        )
        # Drop the size floor so the small (but highly compressible) test member
        # is still subject to the ratio check.
        monkeypatch.setattr(
            "shyfem_ui.services.project_export.MIN_RATIO_CHECK_BYTES",
            0,
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
            await import_project(buf, tmp_path)

    def test_small_highly_compressible_member_below_floor_passes(self):
        """L46: a legit small, highly compressible file (below the absolute size
        floor) must not trip the ratio check — the app's own weutro_box CSV
        deflates ~164:1 and previously broke its export->import round-trip."""
        from shyfem_ui.services.project_export import _validate_archive_limits

        info = zipfile.ZipInfo(filename="weutro_box.csv")
        info.file_size = 1024  # 1 KiB, well below MIN_RATIO_CHECK_BYTES
        info.compress_size = 6  # ratio ~170 -> would trip the old check
        # Must not raise.
        _validate_archive_limits([info])

    def test_large_member_over_floor_with_high_ratio_still_rejected(self, monkeypatch):
        """L46: the zip-bomb guard must remain for members that exceed the floor
        — a genuinely large member with an implausible ratio still rejects."""
        from shyfem_ui.services import project_export as pe

        monkeypatch.setattr(pe, "MIN_RATIO_CHECK_BYTES", 1000)
        info = zipfile.ZipInfo(filename="bomb.bin")
        info.file_size = 2000  # above the (patched) floor
        info.compress_size = 1  # ratio 2000 >> MAX_IMPORT_COMPRESSION_RATIO (100)
        with pytest.raises(ValueError, match="compression ratio"):
            pe._validate_archive_limits([info])

    async def test_import_streams_extracted_members(self, exported_zip, tmp_path, monkeypatch):
        original_read = zipfile.ZipExtFile.read

        def guarded_read(self, size=-1):
            if self.name != "manifest.json":
                assert size not in (-1, None)
            return original_read(self, size)

        monkeypatch.setattr(zipfile.ZipExtFile, "read", guarded_read)

        result = await import_project(exported_zip, tmp_path)
        assert (result["work_dir"] / "GRID" / "mesh.grd").exists()

    def test_import_limit_defaults_are_reasonable(self):
        assert MAX_IMPORT_FILES > 100
        assert MAX_IMPORT_UNCOMPRESSED_BYTES > 100 * 1024 * 1024
        assert MAX_IMPORT_COMPRESSION_RATIO > 10


class TestImportProjectAsync:
    """N47: import_project must not block the Shiny event loop."""

    async def test_import_does_not_block_event_loop(self, exported_zip, tmp_path, monkeypatch):
        import shyfem_ui.services.project_export as pe

        original_sync = pe._import_project_sync

        def slow_sync(*args, **kwargs):
            time.sleep(0.5)
            return original_sync(*args, **kwargs)

        monkeypatch.setattr(pe, "_import_project_sync", slow_sync)

        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.05)
                ticks += 1

        ticker_task = asyncio.ensure_future(ticker())
        try:
            await import_project(exported_zip, tmp_path)
        finally:
            ticker_task.cancel()

        assert ticks >= 5, (
            f"event loop only ticked {ticks} times during import -- "
            "import_project is blocking the loop instead of running in a thread"
        )


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
        result = clone_project(project_dir, project_meta, project_dir.parent, new_name="My Clone")
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
