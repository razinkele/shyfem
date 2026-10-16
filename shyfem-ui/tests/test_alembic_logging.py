"""Running Alembic must never disable the application's loggers.

``migrations/env.py`` applies alembic.ini's ``[loggers]`` section through
``logging.config.fileConfig``. Its default ``disable_existing_loggers=True``
permanently disables every logger that already exists -- i.e. every
module-level ``logging.getLogger(__name__)`` in this app -- the first time a
migration or stamp runs in-process. ``init_db`` sidesteps env.py's fileConfig
by nulling ``config_file_name`` (db/base.py), but that guard lives at ONE call
site; any other caller (a test helper, a maintenance script, a future
``command.upgrade`` elsewhere) that leaves ``config_file_name`` set would
silently kill app logging. The guard therefore also lives in env.py itself.

These run in a subprocess: fileConfig resets the root logger and shuts down
handlers process-wide, which would pollute pytest's own handlers.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

UI_ROOT = Path(__file__).resolve().parents[1]
INI_PATH = UI_ROOT / "alembic.ini"

_SCRIPT = r"""
import io, json, logging, sys
from alembic import command
from alembic.config import Config

ini_path, db_url = sys.argv[1], sys.argv[2]

# An application logger that exists BEFORE the migration runs, exactly like a
# module-level logger created at import time.
app_logger = logging.getLogger("shyfem_ui.services.some_module")
stream = io.StringIO()
handler = logging.StreamHandler(stream)
app_logger.addHandler(handler)
app_logger.setLevel(logging.INFO)

cfg = Config(ini_path)  # config_file_name deliberately left SET
cfg.set_main_option("sqlalchemy.url", db_url)
command.upgrade(cfg, "head")

app_logger.info("still alive after migration")
print(json.dumps({
    "disabled": app_logger.disabled,
    "enabled_info": app_logger.isEnabledFor(logging.INFO),
    "captured": stream.getvalue(),
}))
"""


def _run_migration(tmp_path: Path) -> dict:
    db_url = f"sqlite:///{tmp_path / 'migrate.db'}"
    proc = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(INI_PATH), db_url],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "PYTHONPATH": str(UI_ROOT),
            "SHYFEM_UI_DATABASE_URL": db_url,
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_migration_with_config_file_name_set_keeps_app_loggers_alive(tmp_path):
    result = _run_migration(tmp_path)
    assert result["disabled"] is False, (
        "migrations/env.py's fileConfig disabled a pre-existing app logger "
        "(disable_existing_loggers must be False)"
    )
    assert result["enabled_info"] is True
    assert "still alive after migration" in result["captured"]


def test_init_db_keeps_app_loggers_alive(tmp_path):
    """The production path (init_db) must also leave app loggers enabled."""
    db_url = f"sqlite:///{tmp_path / 'init.db'}"
    script = r"""
import json, logging
app_logger = logging.getLogger("shyfem_ui.services.some_module")
from shyfem_ui.db.base import init_db
init_db()
print(json.dumps({"disabled": app_logger.disabled}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(tmp_path),
        env={
            **os.environ,
            "PYTHONPATH": str(UI_ROOT),
            "SHYFEM_UI_DATABASE_URL": db_url,
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "init.db").exists(), "init_db did not use the temp DB"
    assert json.loads(proc.stdout.strip().splitlines()[-1])["disabled"] is False
