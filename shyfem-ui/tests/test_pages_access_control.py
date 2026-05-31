"""Verify that every write-path page calls editor_denied_reason in
its handler body (static AST analysis, not source-string regex).

This is the negative-control for the WS trusted-identity fix: each write
handler must route its authorization through the fail-CLOSED
``editor_denied_reason`` guard (services/access_control.py). If a guard is
deleted, the matching parametrized case fails immediately. The guard's own
fail-closed semantics (deny when the WS identity is unresolved in server mode)
are unit-tested in test_access_control.py::TestEditorDeniedReason."""

import ast
import pathlib

import pytest

# Resolve the pages directory relative to this test file, so the tests work
# regardless of the working directory from which pytest is invoked.
_PAGES_DIR = pathlib.Path(__file__).parent.parent / "shyfem_ui" / "pages"


# (page_module_name, write_handler_name, expected_min_role)
# All 9 names verified against source by code inspection (2026-05-31).
WRITE_HANDLERS = [
    ("simulation", "_confirm_save", "editor"),  # saves .str to filesystem
    ("partitioning", "_run_shyparts", "editor"),  # runs shyparts external process
    ("compare", "_generate_comparison_report", "editor"),  # writes HTML report to disk
    ("physics", "save_file", "editor"),  # saves .str to filesystem
    ("grid_prep", "_run_shypre", "editor"),  # runs shypre external process
    ("postprocess", "_run_shyelab", "editor"),  # runs shyelab external process
    ("visualize", "_load_data", "viewer"),  # reads project data
    ("ensemble", "_submit_ensemble", "editor"),  # submits jobs to queue
    ("ibm", "_load_trajectories", "editor"),  # runs lgrelab external process
    ("run", "_submit_job", "editor"),  # submits shyfem jobs to queue
    ("files", "_handle_upload", "editor"),  # writes uploaded files to disk
    ("files", "_seed_tutorial", "editor"),  # seeds files into the project
    ("files", "_download", "viewer"),  # reads a project file
    ("files", "_do_delete", "editor"),  # deletes a project file
]

_PLACEHOLDER_PREFIX = "<TODO"


def _find_function_def(tree: ast.AST, name: str) -> "ast.FunctionDef | ast.AsyncFunctionDef | None":
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


class _DirectCallCollector(ast.NodeVisitor):
    """Collect Call nodes from a function body without descending into
    nested function/lambda definitions. Avoids false-positives where the
    guard sits in an unreachable inner helper."""

    def __init__(self):
        self.calls: list[ast.Call] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # don't recurse — stop at nested definitions

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append(node)
        self.generic_visit(node)  # still walk arg expressions for nested calls


def _find_guard_call(func_def: ast.AST) -> "ast.Call | None":
    """Return the ``editor_denied_reason`` Call in func_def's direct body
    (excluding nested closures), or None if absent."""
    visitor = _DirectCallCollector()
    for stmt in func_def.body:
        visitor.visit(stmt)
    for node in visitor.calls:
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id == "editor_denied_reason":
            return node
        if isinstance(callee, ast.Attribute) and callee.attr == "editor_denied_reason":
            return node
    return None


def _guard_min_role(call: ast.Call) -> "str | None":
    """Extract the literal min_role keyword passed to the guard call, if any."""
    for kw in call.keywords:
        if kw.arg == "min_role" and isinstance(kw.value, ast.Constant):
            return kw.value.value
    return None


@pytest.mark.parametrize("page,handler,role", WRITE_HANDLERS)
def test_handler_calls_editor_denied_reason(page, handler, role):
    """Static AST check: the named handler must call the fail-closed
    ``editor_denied_reason`` guard with the expected min_role. Catches missing
    or weakened guards reliably regardless of indentation / closure nesting."""
    if handler.startswith(_PLACEHOLDER_PREFIX):
        pytest.skip(
            f"Handler name for {page} is still a Step-2 placeholder — "
            f"fill in the real handler name in WRITE_HANDLERS, then re-run."
        )
    path = _PAGES_DIR / f"{page}.py"
    tree = ast.parse(path.read_text())
    fn = _find_function_def(tree, handler)
    assert fn is not None, f"Handler {handler!r} not found in {path}"
    call = _find_guard_call(fn)
    assert call is not None, (
        f"{path}::{handler} (line {fn.lineno}) does not call "
        f"editor_denied_reason — add the fail-closed guard before the mutation"
    )
    assert _guard_min_role(call) == role, (
        f"{path}::{handler} guards with min_role={_guard_min_role(call)!r}, " f"expected {role!r}"
    )


def test_step2_handler_table_is_complete():
    """Sentinel test: fail loudly if Step 2 was skipped. Prevents the
    parametrized tests above from silently skipping all 9 rows."""
    placeholders = [page for page, h, _ in WRITE_HANDLERS if h.startswith(_PLACEHOLDER_PREFIX)]
    assert not placeholders, (
        f"WRITE_HANDLERS still has {len(placeholders)} placeholder rows: "
        f"{placeholders}. Fill in the real handler names from Step 2 "
        "before declaring Task 8 complete."
    )
