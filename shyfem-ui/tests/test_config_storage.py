"""Tests for project storage config."""



class TestStorageConfig:

    def test_default_max_project_storage(self):
        from shyfem_ui.config import Config
        c = Config(shyfem_dir="/tmp/sf", work_dir="/tmp/w")
        assert c.max_project_storage_mb == 5000

    def test_override_via_env(self, monkeypatch):
        monkeypatch.setenv("SHYFEM_UI_MAX_PROJECT_STORAGE_MB", "2000")
        from shyfem_ui.config import Config
        c = Config(shyfem_dir="/tmp/sf", work_dir="/tmp/w")
        assert c.max_project_storage_mb == 2000
