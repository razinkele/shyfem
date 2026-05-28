"""Guard test for the Alembic env.py model-import policy.

Background: ``migrations/env.py`` must import every model module so that
``Base.metadata`` is fully populated before ``--autogenerate`` compares
metadata against the live DB. A missing import causes autogenerate to
silently propose dropping that module's tables — a high-severity trap
(see ``docs/followups/2026-05-28-alembic-env-missing-audit-log-import.md``).

This file is the policy itself: every model submodule must appear in
env.py's import list. If you add a new model module under
``shyfem_ui/models/``, you must also add ``from shyfem_ui.models import
<module>  # noqa: F401`` to ``migrations/env.py``.
"""

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_MODELS_DIR = _REPO_ROOT / "shyfem_ui" / "models"
_ENV_PY = _REPO_ROOT / "migrations" / "env.py"


def _discover_model_submodules() -> set[str]:
    """Return the bare module names under shyfem_ui.models (no __init__)."""
    return {
        p.stem
        for p in _MODELS_DIR.glob("*.py")
        if p.stem != "__init__" and not p.stem.startswith("_")
    }


def _imported_model_submodules() -> set[str]:
    """Return the model submodule names that env.py explicitly imports.

    Matches ``from shyfem_ui.models import <name>`` and
    ``from shyfem_ui.models.<name> import ...`` variants.
    """
    src = _ENV_PY.read_text(encoding="utf-8")
    imported: set[str] = set()
    for m in re.finditer(r"from shyfem_ui\.models import (\w+)", src):
        imported.add(m.group(1))
    for m in re.finditer(r"from shyfem_ui\.models\.(\w+) import", src):
        imported.add(m.group(1))
    return imported


def test_every_model_submodule_is_imported_by_env_py():
    """Each model file under shyfem_ui/models/ must be imported by env.py
    so its tables register with Base.metadata before autogenerate."""
    discovered = _discover_model_submodules()
    imported = _imported_model_submodules()
    missing = discovered - imported
    assert not missing, (
        f"migrations/env.py is missing imports for model module(s): "
        f"{sorted(missing)}. Without these imports, alembic "
        f"`revision --autogenerate` will silently propose dropping those "
        f"modules' tables. Add `from shyfem_ui.models import <name>  "
        f"# noqa: F401` to migrations/env.py."
    )


def test_env_py_imports_audit_log_explicitly():
    """Regression guard for the 2026-05-28 audit_log incident.

    Even if ``project`` transitively pulls in some user tables via FK
    relationships, ``audit_log`` has no such back-reference and MUST be
    imported by name."""
    assert "audit_log" in _imported_model_submodules(), (
        "migrations/env.py must explicitly import shyfem_ui.models.audit_log; "
        "see docs/followups/2026-05-28-alembic-env-missing-audit-log-import.md"
    )
