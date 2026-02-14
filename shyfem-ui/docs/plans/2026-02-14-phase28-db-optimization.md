# Phase 28: Database Query Optimization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add configurable SQLAlchemy connection pool settings for PostgreSQL production deployments.

**Architecture:** Add 3 config fields (pool_size, pool_overflow, pool_recycle) to Config class, then pass them to `create_engine()` in `db/base.py` only when the database URL is not SQLite. TDD with mock-based tests.

**Tech Stack:** Pydantic settings, SQLAlchemy engine kwargs, unittest.mock

---

### Task 1: Add config fields and engine pool logic

**Files:**
- Modify: `shyfem_ui/config.py` (add 3 fields after `database_url`)
- Modify: `shyfem_ui/db/base.py` (pass pool kwargs in `get_engine()`)
- Create: `tests/test_db_pool.py`

**Step 1: Write tests**

Create `tests/test_db_pool.py`:

```python
"""Tests for database connection pool configuration."""

from unittest.mock import patch

import pytest


class TestPoolConfig:
    """Tests for pool-related config fields."""

    def test_default_pool_size(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")
        assert cfg.db_pool_size == 5

    def test_default_pool_overflow(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")
        assert cfg.db_pool_overflow == 10

    def test_default_pool_recycle(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")
        assert cfg.db_pool_recycle == 3600

    def test_custom_pool_size(self):
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test", db_pool_size=20)
        assert cfg.db_pool_size == 20


class TestEnginePoolArgs:
    """Tests for pool args passed to create_engine."""

    def test_sqlite_no_pool_args(self):
        """SQLite engine should NOT receive pool args."""
        from shyfem_ui.config import Config
        cfg = Config(database_url="sqlite:///./test.db")

        with patch("shyfem_ui.db.base.get_config", return_value=cfg), \
             patch("shyfem_ui.db.base.create_engine") as mock_engine:
            import shyfem_ui.db.base as db_mod
            db_mod._engine = None  # reset cached engine
            try:
                db_mod.get_engine()
                _, kwargs = mock_engine.call_args
                assert "pool_size" not in kwargs
                assert "pool_pre_ping" not in kwargs
                assert kwargs["connect_args"] == {"check_same_thread": False}
            finally:
                db_mod._engine = None

    def test_postgresql_gets_pool_args(self):
        """PostgreSQL engine should receive pool args."""
        from shyfem_ui.config import Config
        cfg = Config(
            database_url="postgresql://localhost/test",
            db_pool_size=10,
            db_pool_overflow=20,
            db_pool_recycle=1800,
        )

        with patch("shyfem_ui.db.base.get_config", return_value=cfg), \
             patch("shyfem_ui.db.base.create_engine") as mock_engine:
            import shyfem_ui.db.base as db_mod
            db_mod._engine = None
            try:
                db_mod.get_engine()
                _, kwargs = mock_engine.call_args
                assert kwargs["pool_size"] == 10
                assert kwargs["max_overflow"] == 20
                assert kwargs["pool_recycle"] == 1800
                assert kwargs["pool_pre_ping"] is True
                assert "connect_args" not in kwargs
            finally:
                db_mod._engine = None

    def test_postgresql_default_pool_args(self):
        """PostgreSQL with default config values."""
        from shyfem_ui.config import Config
        cfg = Config(database_url="postgresql://localhost/test")

        with patch("shyfem_ui.db.base.get_config", return_value=cfg), \
             patch("shyfem_ui.db.base.create_engine") as mock_engine:
            import shyfem_ui.db.base as db_mod
            db_mod._engine = None
            try:
                db_mod.get_engine()
                _, kwargs = mock_engine.call_args
                assert kwargs["pool_size"] == 5
                assert kwargs["max_overflow"] == 10
                assert kwargs["pool_recycle"] == 3600
                assert kwargs["pool_pre_ping"] is True
            finally:
                db_mod._engine = None
```

**Step 2: Run tests to verify they fail**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_db_pool.py -v`
Expected: FAIL (AttributeError — `db_pool_size` doesn't exist yet)

**Step 3: Add config fields to `config.py`**

In `shyfem_ui/config.py`, after the `database_url` field (line 46), add:

```python
    db_pool_size: int = Field(
        default=5,
        description="SQLAlchemy connection pool size (PostgreSQL only)"
    )
    db_pool_overflow: int = Field(
        default=10,
        description="Max overflow connections beyond pool_size (PostgreSQL only)"
    )
    db_pool_recycle: int = Field(
        default=3600,
        description="Seconds before recycling idle connections (PostgreSQL only)"
    )
```

**Step 4: Update `get_engine()` in `db/base.py`**

Replace the current `get_engine()` function (lines 25-35) with:

```python
def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        is_sqlite = "sqlite" in config.database_url

        if is_sqlite:
            _engine = create_engine(
                config.database_url,
                connect_args={"check_same_thread": False},
                echo=False,
            )
        else:
            _engine = create_engine(
                config.database_url,
                pool_size=config.db_pool_size,
                max_overflow=config.db_pool_overflow,
                pool_recycle=config.db_pool_recycle,
                pool_pre_ping=True,
                echo=False,
            )
    return _engine
```

**Step 5: Run tests to verify they pass**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/test_db_pool.py -v`
Expected: 7 passed

**Step 6: Run full test suite**

Run: `/opt/micromamba/envs/shiny/bin/python -m pytest tests/ -q`
Expected: 467+ passed, 0 failed

**Step 7: Update TODO_NEXT.md**

Mark 28.1 and 28.2 as skipped with reasons. Mark 28.3 as complete.

**Step 8: Commit**

```bash
git add shyfem_ui/config.py shyfem_ui/db/base.py tests/test_db_pool.py TODO_NEXT.md
git commit -m "feat: phase 28 — add connection pool config for PostgreSQL deployments"
```
