"""D-01: init_db hands Alembic the real database URL, password included.

``str(engine.url)`` masks the password as ``***``, so Alembic connected to
PostgreSQL with the literal password ``***`` and the documented PostgreSQL
setup could not start (SQLite has no password, so prod was unaffected). A
percent-encoded password (``%40`` for ``@``) must also survive the
ConfigParser interpolation of ``set_main_option``. The password must still
never reach the logs.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

import shyfem_ui.db.base as base

PASSWORD = "p@ss%w0rd"
URL = make_url("postgresql://shyfem:placeholder@db.example:5432/shyfem").set(password=PASSWORD)


class _FakeEngine:
    url = URL


class _FakeInspector:
    def get_table_names(self):
        return []  # a new database: init_db runs `upgrade head`


def test_alembic_gets_the_unmasked_url_and_logs_stay_masked(monkeypatch, caplog):
    seen = {}

    def fake_upgrade(cfg, rev):
        seen["url"] = cfg.get_main_option("sqlalchemy.url")

    monkeypatch.setattr(base, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(base, "inspect", lambda engine: _FakeInspector())
    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)

    with caplog.at_level(logging.DEBUG):
        base.init_db()

    assert "url" in seen, "init_db did not reach Alembic's upgrade"
    assert make_url(seen["url"]).password == PASSWORD
    assert seen["url"] == URL.render_as_string(hide_password=False)
    assert PASSWORD not in caplog.text
    assert "p%40ss%25w0rd" not in caplog.text


def test_the_alembic_cli_accepts_a_url_with_a_percent(tmp_path):
    """migrations/env.py's own fallback (the `alembic` CLI) read the app's
    database URL into the ini unescaped: any "%" raised ValueError."""
    ui_root = Path(__file__).resolve().parents[1]
    db = tmp_path / "a%b.db"
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ui_root),
        env={**os.environ, "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db}"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert db.exists()
