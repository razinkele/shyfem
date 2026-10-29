"""Uploads are saved and parsed off the event loop (F-05).

The Files page used to read, checksum and write an upload of up to 500 MB
inside a synchronous effect, and Grid Prep parsed an uploaded GRD there:
every session in the worker froze until it finished. The file browser now
awaits an async callback, and both callbacks do the work in a thread.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


def _function(path: str, name: str) -> ast.AST:
    tree = ast.parse((SRC / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path}")


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return getattr(node, "id", "")


@pytest.mark.parametrize(
    "path, handler, blocking",
    [
        ("pages/files.py", "_handle_upload", "persist_upload"),
        ("pages/grid_prep.py", "_handle_file_upload", "GrdParser.parse_file"),
    ],
)
def test_upload_work_runs_in_a_thread(path, handler, blocking):
    fn = _function(path, handler)
    assert isinstance(fn, ast.AsyncFunctionDef), f"{handler} must be async"
    in_thread, direct = 0, 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if _dotted(node.func) == "asyncio.to_thread":
            if node.args and _dotted(node.args[0]) == blocking:
                in_thread += 1
        elif _dotted(node.func) == blocking:
            direct += 1
    assert in_thread == 1 and direct == 0, (in_thread, direct)


def test_file_browser_awaits_an_async_callback():
    fn = _function("components/file_browser.py", "_handle_file_selection")
    assert isinstance(fn, ast.AsyncFunctionDef)
    assert any(isinstance(n, ast.Await) for n in ast.walk(fn))
