"""Tests for CacheHeaderMiddleware ASGI middleware."""

import pytest

from shyfem_ui.config import Config


class TestCacheHeaderConfig:
    """Config field for static_cache_max_age."""

    def test_default_max_age_is_86400(self):
        config = Config(shyfem_dir="/tmp/fake")
        assert config.static_cache_max_age == 86400

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SHYFEM_UI_STATIC_CACHE_MAX_AGE", "3600")
        config = Config(shyfem_dir="/tmp/fake")
        assert config.static_cache_max_age == 3600

    def test_zero_disables(self):
        config = Config(shyfem_dir="/tmp/fake", static_cache_max_age=0)
        assert config.static_cache_max_age == 0
