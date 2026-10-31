"""B-05: two publishers of the same finished build must not destroy the cache.

``_run_build`` (this worker) and ``reconcile_tmp_dirs`` (another worker's page
load, or -- once the readers run on threads -- another session of this one)
can both reach ``publish`` for the same ``<run>.tmp-*`` directory. Without
mutual exclusion the second can rename the freshly published cache away to
``.old-<token>`` and then find no tmp dir to put in its place.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from shyfem_ui.services import boxmodel_cache as bc
from shyfem_ui.services.file_service import _cache_bytes


def _build(root: Path, run_id: str, token: str, tag: str) -> Path:
    d = root / f"{run_id}.tmp-{token}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(f'{{"tag": "{tag}"}}')
    return d


def test_two_concurrent_publishes_of_one_build_keep_the_cache(tmp_path, monkeypatch):
    root = tmp_path / bc.CACHE_DIRNAME
    root.mkdir()
    published = root / "r1"
    published.mkdir()
    (published / "meta.json").write_text('{"tag": "old"}')
    tmp = _build(root, "r1", "abcd", "new")

    real_rename = os.rename
    a_moved_target = threading.Event()
    release_a = threading.Event()
    a_thread: list[threading.Thread] = []

    def rename(src, dst):
        real_rename(src, dst)
        # Publisher A pauses right after moving the old build aside.
        if threading.current_thread() in a_thread and str(dst).endswith(".old-abcd"):
            a_moved_target.set()
            release_a.wait(timeout=5)

    monkeypatch.setattr(bc.os, "rename", rename)
    errors: list[BaseException] = []

    def run_a():
        try:
            bc.publish(tmp, "r1")
        except BaseException as exc:  # noqa: BLE001 - recorded for the assert
            errors.append(exc)

    a = threading.Thread(target=run_a)
    a_thread.append(a)
    a.start()
    a_moved_target.wait(timeout=5)

    def run_b():
        try:
            bc.publish(tmp, "r1")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    b = threading.Thread(target=run_b)
    b.start()
    b.join(timeout=0.5)  # B either finishes its racing publish or waits for A
    release_a.set()
    a.join(timeout=5)
    b.join(timeout=5)

    assert not errors, errors
    assert (published / "meta.json").read_text() == '{"tag": "new"}'
    assert not tmp.exists()
    assert not list(root.glob("r1.old-*"))


def test_the_lock_file_is_invisible_to_the_cache_tools(tmp_path):
    """The lock lives in the cache root: reconcile, status and the quota charge
    must all ignore it."""
    work = tmp_path
    root = work / bc.CACHE_DIRNAME
    tmp = _build(root, "r1", "abcd", "new")
    bc.publish(tmp, "r1")
    assert bc.reconcile_tmp_dirs(work) == []
    assert (root / "r1" / "meta.json").is_file()
    names = {p.name for p in root.iterdir()}
    assert names - {"r1"} <= {bc.PUBLISH_LOCK_NAME}
    assert _cache_bytes(work) == len('{"tag": "new"}')


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores the 0o444 mode, so the test would pass without the fix",
)
def test_a_lock_file_without_write_permission_still_locks(tmp_path):
    """Another account may create the lock without group write; flock needs
    only a readable descriptor, and O_RDWR failed every later publish."""
    from shyfem_ui.services.boxmodel_cache import PUBLISH_LOCK_NAME, _publish_lock

    lock = tmp_path / PUBLISH_LOCK_NAME
    lock.touch()
    os.chmod(lock, 0o444)
    try:
        with _publish_lock(tmp_path):
            pass
    finally:
        os.chmod(lock, 0o644)
