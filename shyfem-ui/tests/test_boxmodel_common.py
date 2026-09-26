"""Root-level helpers shared by the box-model CLI and the cache service.

``shyfem_ui.boxmodel_common`` is stdlib-only on purpose: the CLI imports it
and the CLI must never pull in ``shyfem_ui.services`` (its ``__init__``
drags in the ORM).
"""

import ast
import json
import sys
from pathlib import Path

import pytest

from shyfem_ui import boxmodel_common as bcm


def test_module_is_stdlib_only():
    src = Path(bcm.__file__).read_text()
    tops: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            tops.append((node.module or "").split(".")[0])
        elif isinstance(node, ast.Import):
            tops.extend(alias.name.split(".")[0] for alias in node.names)
    allowed = sys.stdlib_module_names | {"__future__"}
    assert tops and all(t in allowed for t in tops), tops


# -- check_run_id -----------------------------------------------------------


def test_check_run_id_accepts_a_slug():
    bcm.check_run_id("run9316")
    bcm.check_run_id("a")
    bcm.check_run_id("a" * 64)
    assert bcm.RUN_ID_RE.fullmatch("minija_fix-2014")


@pytest.mark.parametrize("bad", ["../x", "A", "a" * 65, "", "a/b", "a b", None, 7])
def test_check_run_id_rejects(bad):
    with pytest.raises(ValueError):
        bcm.check_run_id(bad)


# -- atomic_json ------------------------------------------------------------


def test_atomic_json_replaces_atomically_and_leaves_no_temp(tmp_path):
    target = tmp_path / "meta.json"
    bcm.atomic_json(target, {"v": 1})
    bcm.atomic_json(target, {"v": 2})
    assert json.loads(target.read_text()) == {"v": 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["meta.json"]


def test_atomic_json_failed_dump_leaves_nothing_behind(tmp_path):
    target = tmp_path / "meta.json"
    bcm.atomic_json(target, {"v": 1})
    with pytest.raises(TypeError):
        bcm.atomic_json(target, {"x": object()})
    # the previous content survives and no .tmp-* file is left over
    assert json.loads(target.read_text()) == {"v": 1}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["meta.json"]


# -- no_symlink_components --------------------------------------------------


def test_no_symlink_components(tmp_path):
    real = tmp_path / "a" / "b" / "c"
    real.mkdir(parents=True)
    assert bcm.no_symlink_components(real)

    link = tmp_path / "L"
    link.symlink_to(tmp_path / "a")
    # the symlink is a middle component, not the leaf
    assert not bcm.no_symlink_components(link / "b" / "c")
    # ... and the leaf itself
    leaf_link = tmp_path / "a" / "b" / "d"
    leaf_link.symlink_to(real)
    assert not bcm.no_symlink_components(leaf_link)
