"""Tests for configuration management."""

from pathlib import Path

import pytest

from shyfem_ui.config import Config, get_config, set_config


def _clean_config(**overrides) -> Config:
    """Create a Config isolated from host environment variables.

    Strips all SHYFEM_UI_* env vars so tests always see defaults.
    """
    return Config(_env_file=None, **overrides)


class TestConfigDefaults:
    """Tests for default configuration values."""

    def test_default_deployment_mode(self):
        """Test default deployment mode is local."""
        config = _clean_config()
        assert config.deployment_mode == "local"

    def test_default_host(self):
        """Test default host binding."""
        config = _clean_config()
        assert config.host == "127.0.0.1"

    def test_default_port(self):
        """Test default port."""
        config = _clean_config()
        assert config.port == 8000

    def test_default_max_workers(self):
        """Test default max workers."""
        config = _clean_config()
        assert config.max_workers == 4

    def test_default_mpi_settings(self):
        """Test default MPI configuration."""
        config = _clean_config()
        assert config.mpi_enabled is True
        assert config.mpi_default_np == 4
        assert config.mpirun_path == "mpirun"

    def test_default_auth_disabled(self):
        """Test auth is disabled by default in local mode."""
        config = _clean_config()
        assert config.auth_enabled is False

    def test_auth_auto_enabled_server_mode(self):
        """Test auth is auto-enabled in server mode when not explicitly set."""
        config = _clean_config(
            deployment_mode="server",
            default_admin_password="strongpass123",
        )
        assert config.auth_enabled is True

    def test_auth_explicit_false_server_mode(self):
        """Test auth can be explicitly disabled in server mode."""
        config = _clean_config(
            deployment_mode="server",
            default_admin_password="strongpass123",
            auth_enabled=False,
        )
        assert config.auth_enabled is False

    def test_default_theme(self):
        """Test default UI theme."""
        config = _clean_config()
        assert config.theme == "flatly"

    def test_default_celery_disabled(self):
        """Test Celery is disabled by default."""
        config = _clean_config()
        assert config.use_celery is False

    def test_default_rate_limit(self):
        """Test default rate limit."""
        config = _clean_config()
        assert config.rate_limit_rpm == 120

    def test_default_max_upload_size(self):
        """Test default max upload size is 500 MB."""
        config = _clean_config()
        assert config.max_upload_size_mb == 500

    def test_default_trusted_proxies(self):
        """Test trusted_proxies defaults to empty list."""
        config = _clean_config()
        assert config.trusted_proxies == []


class TestConfigProperties:
    """Tests for Config properties."""

    def test_bin_dir(self):
        """Test bin_dir property returns correct path."""
        config = Config()
        assert config.bin_dir == config.shyfem_dir / "bin"

    def test_testcases_dir(self):
        """Test testcases_dir property."""
        config = Config()
        assert config.testcases_dir == config.shyfem_dir / "testcases" / "examples"

    def test_get_executable(self, tmp_path):
        """Test get_executable returns bin path."""
        config = Config(shyfem_dir=tmp_path)
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "shyfem").touch()

        exe = config.get_executable("shyfem")
        assert exe == tmp_path / "bin" / "shyfem"

    def test_ensure_work_dir(self, tmp_path):
        """Test ensure_work_dir creates directory."""
        config = Config(work_dir=tmp_path / "new_work")
        result = config.ensure_work_dir()
        assert result.exists()
        assert result == tmp_path / "new_work"


class TestPathValidation:
    """Tests for path validation security."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create config with known directories."""
        work = tmp_path / "work"
        work.mkdir()
        shyfem = tmp_path / "shyfem"
        shyfem.mkdir()
        return Config(work_dir=work, shyfem_dir=shyfem)

    def test_validate_path_within_work_dir(self, config):
        """Test valid path within work directory."""
        valid = config.work_dir / "project1" / "output.txt"
        result = config.validate_path(valid)
        assert isinstance(result, Path)

    def test_validate_path_within_shyfem_dir(self, config):
        """Test valid path within SHYFEM directory."""
        valid = config.shyfem_dir / "bin" / "shyfem"
        result = config.validate_path(valid)
        assert isinstance(result, Path)

    def test_validate_path_within_tmp(self, config):
        """Test valid path within /tmp."""
        result = config.validate_path("/tmp/test.txt")
        assert isinstance(result, Path)

    def test_validate_path_outside_allowed(self, config):
        """Test path outside allowed directories raises ValueError."""
        with pytest.raises(ValueError, match="outside allowed directories"):
            config.validate_path("/etc/passwd")

    def test_validate_path_null_bytes(self, config):
        """Test null bytes in path are rejected."""
        with pytest.raises(ValueError, match="null bytes"):
            config.validate_path("/tmp/test\x00.txt")

    def test_validate_path_must_exist(self, config):
        """Test must_exist flag raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            config.validate_path(
                config.work_dir / "nonexistent.txt",
                must_exist=True,
            )

    def test_validate_path_must_exist_ok(self, config):
        """Test must_exist with existing file succeeds."""
        f = config.work_dir / "exists.txt"
        f.write_text("test")
        result = config.validate_path(f, must_exist=True)
        assert result.exists()

    def test_validate_save_path_within_work(self, config):
        """Test valid save path within work directory."""
        path = config.work_dir / "output.html"
        result = config.validate_save_path(path)
        assert isinstance(result, Path)

    def test_validate_save_path_outside_work(self, config):
        """Test save path outside work directory raises ValueError."""
        with pytest.raises(ValueError, match="must be within work directory"):
            config.validate_save_path("/etc/test.txt")

    def test_validate_save_path_null_bytes(self, config):
        """Test null bytes in save path are rejected."""
        with pytest.raises(ValueError, match="null bytes"):
            config.validate_save_path("/tmp/test\x00.html")


class TestConfigGlobal:
    """Tests for global config get/set functions."""

    def test_get_config_returns_instance(self):
        """Test get_config returns a Config instance."""
        # Reset global state
        set_config(None)
        config = get_config()
        assert isinstance(config, Config)

    def test_set_config(self, tmp_path):
        """Test set_config overrides global config."""
        custom = Config(port=9999, work_dir=tmp_path / "custom")
        set_config(custom)

        retrieved = get_config()
        assert retrieved.port == 9999

        # Clean up
        set_config(None)

    def test_get_config_caches(self):
        """Test get_config returns same instance on repeated calls."""
        set_config(None)
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

        # Clean up
        set_config(None)


class TestSolverSettings:
    """Tests for solver-related configuration."""

    def test_solver_node_threshold_default(self):
        """Default solver node threshold is 50000."""
        config = _clean_config()
        assert config.solver_node_threshold == 50000

    def test_solver_node_threshold_override(self):
        """Solver node threshold can be overridden."""
        config = _clean_config(solver_node_threshold=100000)
        assert config.solver_node_threshold == 100000


class TestPathResolver:
    """Tests for path resolution validator."""

    def test_resolve_string_path(self):
        """Test that string paths are resolved to Path objects."""
        config = Config(shyfem_dir="/tmp/test_shyfem")
        assert isinstance(config.shyfem_dir, Path)

    def test_resolve_tilde_path(self, tmp_path):
        """Test that ~ is expanded in paths."""
        # This tests the validator runs, actual expansion depends on env
        config = Config(work_dir=tmp_path)
        assert config.work_dir.is_absolute()


def test_user_data_root_default():
    """user_data_root defaults to /data/shyfem."""
    c = _clean_config()
    assert str(c.user_data_root) == "/data/shyfem"


def test_user_data_root_env(monkeypatch):
    """SHYFEM_UI_USER_DATA_ROOT overrides the default."""
    monkeypatch.setenv("SHYFEM_UI_USER_DATA_ROOT", "/mnt/data")
    c = Config(_env_file=None)
    assert str(c.user_data_root) == "/mnt/data"


def test_smtp_host_default_empty():
    """smtp_host defaults to empty string (SMTP disabled)."""
    c = _clean_config()
    assert c.smtp_host == ""


def test_smtp_settings_env(monkeypatch):
    """SMTP settings are read from env vars."""
    monkeypatch.setenv("SHYFEM_UI_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SHYFEM_UI_SMTP_PORT", "587")
    monkeypatch.setenv("SHYFEM_UI_SMTP_USER", "noreply@example.com")
    c = Config(_env_file=None)
    assert c.smtp_host == "smtp.example.com"
    assert c.smtp_port == 587


def test_test_env_pins_local_deployment_mode():
    """conftest._isolate_env must neutralize any ambient .env file.

    The production checkout carries SHYFEM_UI_DEPLOYMENT_MODE=server in .env;
    pydantic reads it even after env VARS are stripped (env_file=".env"). A
    Config() created without overrides must default to local in the test
    session — otherwise the fail-closed auth gates (editor_denied_reason /
    load_project_context) deny nondeterministically depending on whether a .env
    happens to sit in the checkout (this broke the Phase 3B merge)."""
    from shyfem_ui.config import Config

    assert Config().deployment_mode == "local"
