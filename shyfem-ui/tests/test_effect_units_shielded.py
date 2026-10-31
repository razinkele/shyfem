"""Shiny 1.9 cancels a session's in-progress async effects when the session
ends (a closed tab), raising CancelledError at the effect's current ``await``.

An effect whose awaited step has side effects beyond the session must not be
cut mid-step: a shyelab run killed half-way leaves a partial, un-renamed
output file; an ensemble submit stopped between members leaves prepared
folders no job owns; a project import whose records were never written
leaves an extracted folder no project row points at. Each of these effects
therefore awaits its unit of work through ``asyncio.shield``: the unit runs
to completion even when the session is gone, and the only cancellation point
is between units.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

SHIELDED_EFFECTS = {
    "pages/postprocess.py": ["_batch_run", "_batch_convert", "_run_preset"],
    "pages/ensemble.py": ["_submit_ensemble"],
    "pages/home.py": ["_do_import_project"],
}


def _async_def(tree: ast.AST, name: str) -> ast.AsyncFunctionDef:
    found = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
    assert len(found) == 1, (name, len(found))
    return found[0]


def _own_awaits(fn: ast.AsyncFunctionDef) -> list[ast.Await]:
    """The awaits of ``fn`` itself, not of async closures defined inside it."""
    out: list[ast.Await] = []

    def visit(node: ast.AST, inner: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Await) and not inner:
                out.append(child)
            visit(child, inner)

    visit(fn, False)
    return out


@pytest.mark.parametrize(
    "rel, name",
    [(rel, name) for rel, names in SHIELDED_EFFECTS.items() for name in names],
)
def test_every_await_of_the_effect_is_a_shield(rel, name):
    src = (Path(__file__).parent.parent / "shyfem_ui" / rel).read_text(encoding="utf-8")
    fn = _async_def(ast.parse(src), name)
    awaits = _own_awaits(fn)
    assert awaits, f"{rel}::{name} has no await; the guard is pointless here"
    unshielded = [
        ast.unparse(a)
        for a in awaits
        if not (
            isinstance(a.value, ast.Call)
            and isinstance(a.value.func, ast.Attribute)
            and a.value.func.attr == "shield"
        )
    ]
    assert unshielded == [], f"{rel}::{name} awaits outside asyncio.shield: {unshielded}"


class _FakeWrapper:
    """run_shyelab that blocks until released, then reports one output file."""

    def __init__(self, output_dir: Path):
        self.release = asyncio.Event()
        self.finished = False
        self.output_dir = output_dir

    async def run_shyelab(self, path, output_path, options):
        await self.release.wait()
        out = self.output_dir / "out.nc"
        out.write_text("data")
        self.finished = True
        return SimpleNamespace(success=True, return_code=0, duration=0.1, output_files=[str(out)])


async def test_a_cancelled_caller_still_gets_the_run_finished_and_renamed(tmp_path):
    from shyfem_ui.services.postprocess_logic import run_shyelab_and_name

    wrapper = _FakeWrapper(tmp_path)
    input_file = tmp_path / "basin.shy"
    input_file.write_text("")
    done: list = []

    async def caller():
        result = await asyncio.shield(
            run_shyelab_and_name(wrapper, input_file, tmp_path, [], "extract_nc")
        )
        done.append(result)

    task = asyncio.create_task(caller())
    await asyncio.sleep(0)  # the caller is now waiting inside the shield
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert done == []  # the caller itself was cancelled ...
    wrapper.release.set()
    await asyncio.sleep(0.05)  # ... but the unit ran on
    assert wrapper.finished
    assert not (tmp_path / "out.nc").exists(), "the output was left under shyelab's name"
    assert (tmp_path / "basin.extract_nc.nc").exists()  # name_outputs: <input>.<operation>.<ext>


async def test_import_and_register_writes_the_records_even_if_the_caller_is_cancelled(
    tmp_path, monkeypatch
):
    from shyfem_ui.services import project_export

    release = asyncio.Event()
    recorded: list = []

    async def fake_import(zip_data, base_dir):
        await release.wait()
        return {"name": "p", "work_dir": str(tmp_path / "p")}

    monkeypatch.setattr(project_export, "import_project", fake_import)
    monkeypatch.setattr(
        project_export, "create_project_records", lambda result, owner_id: recorded.append(owner_id)
    )

    async def caller():
        await asyncio.shield(project_export.import_and_register(b"", tmp_path, owner_id=7))

    task = asyncio.create_task(caller())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.sleep(0.05)
    assert recorded == [7]


def test_import_and_register_removes_the_folder_when_the_records_fail(tmp_path, monkeypatch):
    from shyfem_ui.services import project_export

    work_dir = tmp_path / "p"
    work_dir.mkdir()

    async def fake_import(zip_data, base_dir):
        return {"name": "p", "work_dir": str(work_dir)}

    def failing_records(result, owner_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(project_export, "import_project", fake_import)
    monkeypatch.setattr(project_export, "create_project_records", failing_records)
    with pytest.raises(RuntimeError, match="db down"):
        asyncio.run(project_export.import_and_register(b"", tmp_path, owner_id=None))
    assert not work_dir.exists()


def test_the_unit_functions_are_what_the_pages_call():
    from shyfem_ui.pages import home, postprocess

    assert "run_shyelab_and_name(" in inspect.getsource(postprocess)
    assert "import_and_register(" in inspect.getsource(home)
