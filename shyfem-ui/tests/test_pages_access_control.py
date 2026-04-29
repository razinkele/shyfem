"""Verify that every write-path page calls check_project_access in
its handler body (static AST analysis, not source-string regex)."""

import ast
import pathlib

import pytest

# Resolve the pages directory relative to this test file, so the tests work
# regardless of the working directory from which pytest is invoked.
_PAGES_DIR = pathlib.Path(__file__).parent.parent / "shyfem_ui" / "pages"


# (page_module_name, write_handler_name, expected_min_role)
# All 9 names verified against source by code inspection (2026-04-29).
WRITE_HANDLERS = [
    ("simulation", "_confirm_save", "editor"),              # saves .str to filesystem
    ("partitioning", "_run_shyparts", "editor"),             # runs shyparts external process
    ("compare", "_generate_comparison_report", "editor"),    # writes HTML report to disk
    ("physics", "save_file", "editor"),                     # saves .str to filesystem
    ("grid_prep", "_run_shypre", "editor"),                  # runs shypre external process
    ("postprocess", "_run_shyelab", "editor"),               # runs shyelab external process
    ("visualize", "_load_data", "viewer"),                   # reads project data
    ("ensemble", "_submit_ensemble", "editor"),              # submits jobs to queue
    ("ibm", "_load_trajectories", "editor"),                 # runs lgrelab external process
]

_PLACEHOLDER_PREFIX = "<TODO"


def _find_function_def(
    tree: ast.AST, name: str
) -> "ast.FunctionDef | ast.AsyncFunctionDef | None":
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


def _calls_check_project_access(func_def: ast.AST) -> bool:
    """Return True if func_def's direct body (excluding nested closures)
    contains a Call whose callable is named ``check_project_access``."""
    visitor = _DirectCallCollector()
    for stmt in func_def.body:
        visitor.visit(stmt)
    for node in visitor.calls:
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id == "check_project_access":
            return True
        if isinstance(callee, ast.Attribute) and callee.attr == "check_project_access":
            return True
    return False


@pytest.mark.parametrize("page,handler,role", WRITE_HANDLERS)
def test_handler_calls_check_project_access(page, handler, role):
    """Static AST check: the named handler must contain a call to
    check_project_access. Catches missing guards reliably regardless of
    indentation / closure nesting / inline-helper extraction."""
    if handler.startswith(_PLACEHOLDER_PREFIX):
        pytest.skip(
            f"Handler name for {page} is still a Step-2 placeholder — "
            f"fill in the real handler name in WRITE_HANDLERS, then re-run."
        )
    path = _PAGES_DIR / f"{page}.py"
    tree = ast.parse(path.read_text())
    fn = _find_function_def(tree, handler)
    assert fn is not None, f"Handler {handler!r} not found in {path}"
    assert _calls_check_project_access(fn), (
        f"{path}::{handler} (line {fn.lineno}) does not call "
        f"check_project_access — add the guard before the mutation"
    )


def test_step2_handler_table_is_complete():
    """Sentinel test: fail loudly if Step 2 was skipped. Prevents the
    parametrized tests above from silently skipping all 9 rows."""
    placeholders = [
        page for page, h, _ in WRITE_HANDLERS if h.startswith(_PLACEHOLDER_PREFIX)
    ]
    assert not placeholders, (
        f"WRITE_HANDLERS still has {len(placeholders)} placeholder rows: "
        f"{placeholders}. Fill in the real handler names from Step 2 "
        "before declaring Task 8 complete."
    )
