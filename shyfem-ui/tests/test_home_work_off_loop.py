"""Clone, the project summary and the admin test mail run off the event loop (H-07).

Each blocked every session in the worker while it ran: clone copied the
whole project, the summary scans it, and SMTP can wait for a timeout.
"""

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return getattr(node, "id", "")


def _functions(path: str) -> dict[str, ast.AST]:
    tree = ast.parse((SRC / path).read_text())
    return {
        n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


@pytest.mark.parametrize(
    "path, handler, blocking",
    [
        ("pages/home.py", "_do_clone", "clone_project"),
        ("pages/home.py", "_activate_project", "load_summary"),
        ("pages/home.py", "_show_details", "load_summary"),
        ("pages/admin.py", "_send_test_email", "svc.notify_job_success"),
    ],
)
def test_blocking_work_runs_in_a_thread(path, handler, blocking):
    fn = _functions(path)[handler]
    assert isinstance(fn, ast.AsyncFunctionDef), f"{handler} must be async"
    in_thread = direct = 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        if _dotted(node.func) == "asyncio.to_thread":
            in_thread += bool(node.args) and _dotted(node.args[0]) == blocking
        elif _dotted(node.func) == blocking:
            direct += 1
    assert (in_thread, direct) == (1, 0)


def test_every_activate_project_call_is_awaited():
    tree = ast.parse((SRC / "pages/home.py").read_text())
    awaited = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Await)}
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and _dotted(n.func) in ("_activate_project", "_do_clone")
    ]
    assert calls and all(id(c) in awaited for c in calls)
