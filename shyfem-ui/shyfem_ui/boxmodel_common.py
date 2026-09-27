"""Helpers shared by the box-model cache CLI and the cache service.

This module is deliberately **stdlib-only** and lives at the package root:
``shyfem_ui/boxmodel_cache_cli.py`` runs as a subprocess (``python -m``) and
must never import anything under ``shyfem_ui.services`` -- that package's
``__init__`` pulls in the ORM. Both the CLI and
``shyfem_ui/services/boxmodel_cache.py`` import from here so the run-id
grammar, the atomic JSON writer and the symlink guard cannot drift apart.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# Same shape as the CLI's own --out slug component and boxmodel_manifest's
# run id slug: [a-z0-9_-]{1,64}. run_id reaches glob()/mkdir() unvalidated
# otherwise -- a run_id of "../../victim" would let a caller escape the
# cache root entirely.
RUN_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


def check_run_id(run_id: str) -> None:
    """Raise ``ValueError`` unless ``run_id`` is a plain ``[a-z0-9_-]{1,64}`` slug."""
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run_id: must match [a-z0-9_-]{1,64}")


def atomic_json(path: Path, payload: dict, *, indent: int | None = None) -> None:
    """Write ``payload`` as JSON to ``path`` atomically.

    The bytes go to a ``mkstemp`` file in ``path.parent`` and are moved into
    place with ``os.replace``, so a reader never sees a half-written file;
    on any failure the temp file is unlinked and the error re-raised, so a
    failed dump leaves the previous ``path`` (if any) untouched.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh, indent=indent, ensure_ascii=False)
            if indent is not None:
                fh.write("\n")  # a file people edit by hand ends in a newline
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def no_symlink_components(p: Path) -> bool:
    """True when no component of ``p`` (from its anchor down to the leaf) is a symlink."""
    cur = Path(p.anchor)
    for part in p.relative_to(p.anchor).parts:
        cur = cur / part
        if cur.is_symlink():
            return False
    return True
