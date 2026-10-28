"""D-02: init_db stamps an unversioned database as head only when its schema
is head's. A database built by ``create_all`` from an older release has no
``alembic_version``; stamping it head skipped every migration it lacked, and
the app then failed on the missing columns. It now stops, naming them."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]

_SCRIPT = r"""
import json, sys
from sqlalchemy import text
from shyfem_ui.db.base import Base, get_engine, init_db
from shyfem_ui.models import audit_log, feedback, project, user, workflow  # noqa: F401
mode = sys.argv[1]
if mode != "empty":
    Base.metadata.create_all(bind=get_engine())  # an unversioned, create_all DB
if mode == "old":
    with get_engine().begin() as c:
        c.execute(text("DROP TABLE feedbacks"))
        c.execute(text("ALTER TABLE jobs DROP COLUMN output_files"))
try:
    init_db()
    print(json.dumps({"ok": True}))
except RuntimeError as e:
    print(json.dumps({"ok": False, "error": str(e)}))
"""


def _run(tmp_path: Path, mode: str) -> tuple[dict, list]:
    db = tmp_path / "d.db"
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, mode],
        cwd=str(tmp_path),
        env={**os.environ, "PYTHONPATH": str(UI_ROOT), "SHYFEM_UI_DATABASE_URL": f"sqlite:///{db}"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    stamp = (
        con.execute("select * from alembic_version").fetchall()
        if "alembic_version" in tables
        else None
    )
    return out, stamp


def _head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config(str(UI_ROOT / "alembic.ini"))).get_current_head()


def test_an_unversioned_head_schema_is_stamped_head(tmp_path):
    out, stamp = _run(tmp_path, "head")
    assert out["ok"] is True
    assert stamp == [(_head(),)]


def test_an_unversioned_older_schema_is_not_stamped(tmp_path):
    out, stamp = _run(tmp_path, "old")
    assert out["ok"] is False
    assert "feedbacks" in out["error"] and "jobs.output_files" in out["error"]
    assert "alembic stamp" in out["error"]
    assert not stamp, "an older schema must not be stamped head"


def test_an_empty_database_is_migrated_to_head(tmp_path):
    out, stamp = _run(tmp_path, "empty")
    assert out["ok"] is True
    assert stamp == [(_head(),)]
