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
    ("run", "_launch_workflow", "editor"),  # queues a chained tool workflow
    ("files", "_handle_upload", "editor"),  # writes uploaded files to disk
    ("files", "_seed_tutorial", "editor"),  # seeds files into the project
    ("files", "_download", "viewer"),  # reads a project file
    ("files", "_do_delete", "editor"),  # deletes a project file
    ("grid_prep", "_run_shybas", "editor"),  # runs shybas external process
    ("postprocess", "_batch_run", "editor"),  # runs shyelab on a batch of paths
    ("postprocess", "_batch_convert", "editor"),  # converts a batch to NetCDF
    ("postprocess", "_run_preset", "editor"),  # runs a preset shyelab pipeline
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


def _is_guard_call(node: ast.AST) -> bool:
    """True if node is a Call to editor_denied_reason."""
    if not isinstance(node, ast.Call):
        return False
    callee = node.func
    return (isinstance(callee, ast.Name) and callee.id == "editor_denied_reason") or (
        isinstance(callee, ast.Attribute) and callee.attr == "editor_denied_reason"
    )


class _GuardEnforcementVisitor(ast.NodeVisitor):
    """Within a function body (excluding nested defs), record which names are
    assigned the result of ``editor_denied_reason`` and which names are tested
    in an ``if`` whose then-branch short-circuits with ``return``/``raise``.

    The intersection proves the guard's verdict is actually *consumed* — not
    computed and ignored. Without this, a refactor that kept the call but
    dropped ``if _denied: ... return`` would silently re-open the fail-open
    write bypass while the call-presence assertion stayed green.
    """

    def __init__(self):
        self.guard_vars: set[str] = set()
        self.enforced_vars: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # stop at nested definitions

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Assign(self, node: ast.Assign) -> None:
        if _is_guard_call(node.value):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    self.guard_vars.add(tgt.id)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        test_names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        then_exits = any(
            isinstance(s, (ast.Return, ast.Raise)) for stmt in node.body for s in ast.walk(stmt)
        )
        if then_exits:
            self.enforced_vars |= test_names
        self.generic_visit(node)


def _guard_is_enforced(func_def: ast.AST) -> bool:
    """True if a name assigned from editor_denied_reason is tested in an
    if-block that returns/raises — i.e. the denial is acted upon."""
    visitor = _GuardEnforcementVisitor()
    for stmt in func_def.body:
        visitor.visit(stmt)
    return bool(visitor.guard_vars & visitor.enforced_vars)


def _stmt_directly_calls_guard(stmt: ast.stmt) -> bool:
    """True if a *simple* statement (assign/expr/return — no nested statement
    bodies) contains an editor_denied_reason call. Compound statements
    (If/For/While/Try/With/def) are handled by the caller, so we never descend
    into a conditional here."""
    if isinstance(
        stmt,
        (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Try,
            ast.With,
            ast.AsyncWith,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
        ),
    ):
        return False
    return any(_is_guard_call(node) for node in ast.walk(stmt))


def _guard_call_is_unconditional(stmts: "list[ast.stmt]") -> bool:
    """True if an editor_denied_reason call is reachable on EVERY path through
    ``stmts`` — i.e. it is a direct statement of the body (or of a Try/With body
    or a Try.finalbody, which also always execute), and NOT nested only inside
    an ``if active_project`` / ``if _proj`` conditional.

    This is the negative-control that catches the double-nesting bypass: a guard
    placed inside ``if active_project is not None: if _proj is not None:`` is
    silently skipped when no project is active, so the mutation runs unguarded
    in production. Such a guard is *conditional* and must fail this check.
    """
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue  # don't descend into nested closures
        if _stmt_directly_calls_guard(stmt):
            return True
        if isinstance(stmt, ast.Try):
            if _guard_call_is_unconditional(stmt.body) or _guard_call_is_unconditional(
                stmt.finalbody
            ):
                return True
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            if _guard_call_is_unconditional(stmt.body):
                return True
    return False


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
    assert _guard_is_enforced(fn), (
        f"{path}::{handler} (line {fn.lineno}) calls editor_denied_reason but "
        f"never acts on the result — the denial must be assigned and checked in "
        f"an `if <reason>: ...; return` before the mutation, else the guard is a no-op"
    )
    assert _guard_call_is_unconditional(fn.body), (
        f"{path}::{handler} (line {fn.lineno}) calls editor_denied_reason only "
        f"inside a conditional (e.g. `if active_project is not None: if _proj is "
        f"not None:`) — the guard is skipped when no project is active, so the "
        f"mutation runs unguarded in production. Hoist the guard to the function "
        f"body and pass project_id=None through it (the gate denies a None "
        f"project in server mode)."
    )


def test_str_editor_inline_save_is_guarded():
    """The str_editor component's inline Save handler writes the .str to disk
    directly (``path.write_text``). It must route through the fail-closed
    ``editor_denied_reason`` gate before the write, unconditionally — otherwise a
    server-mode client with no resolved identity can overwrite any file the
    worker can reach. The component lives outside pages/, so it is checked here
    explicitly rather than via the parametrized pages table."""
    path = pathlib.Path(__file__).parent.parent / "shyfem_ui" / "components" / "str_editor.py"
    tree = ast.parse(path.read_text())
    fn = _find_function_def(tree, "_handle_save")
    assert fn is not None, f"_handle_save not found in {path}"
    call = _find_guard_call(fn)
    assert call is not None, (
        f"{path}::_handle_save (line {fn.lineno}) does not call editor_denied_reason "
        f"— add the fail-closed guard before path.write_text"
    )
    assert (
        _guard_min_role(call) == "editor"
    ), f"{path}::_handle_save guards with min_role={_guard_min_role(call)!r}, expected 'editor'"
    assert _guard_is_enforced(
        fn
    ), f"{path}::_handle_save calls editor_denied_reason but never acts on the result"
    assert _guard_call_is_unconditional(fn.body), (
        f"{path}::_handle_save calls editor_denied_reason only inside a conditional "
        f"— the guard must run on every path before the disk write"
    )


ADMIN_MUTATION_HANDLERS = [
    "_do_reset_pw",
    "_toggle_active",
    "_toggle_role",
    "_do_delete_user",
    "_do_create_user",
]

_AUTH_SERVICE_MUTATIONS = {"reset_password", "update_user", "delete_user", "create_user"}


def _admin_guard_precedes_mutation(func_def: ast.AST) -> bool:
    """True if the handler checks ``_is_admin()`` and returns BEFORE the first
    auth_service mutating call, at unconditional depth.

    The admin panel's privilege boundary cannot rely on ``_is_admin()`` being
    consulted only by the renderer or by ``user_role()`` (a client-spoofable
    signal): every mutation handler must independently re-check the
    server-validated admin identity, or a console
    ``Shiny.setInputValue('current_user_role','admin')`` (or an unresolved WS
    session) reaches the mutation unchecked.
    """
    saw_guard = False
    for stmt in func_def.body:
        if isinstance(stmt, ast.If):
            test_checks_admin = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_is_admin"
                for n in ast.walk(stmt.test)
            )
            body_returns = any(isinstance(s, ast.Return) for s in ast.walk(stmt))
            if test_checks_admin and body_returns:
                saw_guard = True
                continue
        for n in ast.walk(stmt):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "auth_service"
                and n.func.attr in _AUTH_SERVICE_MUTATIONS
            ):
                return saw_guard  # mutation reached — guard must already be seen
    return saw_guard


@pytest.mark.parametrize("handler", ADMIN_MUTATION_HANDLERS)
def test_admin_mutation_rechecks_server_validated_admin(handler):
    """Each admin mutation handler must re-check ``_is_admin()`` (backed by the
    server-validated WS identity, not input.current_user_role()) and return
    before mutating any user, closing the admin privilege-escalation bypass."""
    path = _PAGES_DIR / "admin.py"
    tree = ast.parse(path.read_text())
    fn = _find_function_def(tree, handler)
    assert fn is not None, f"admin handler {handler!r} not found in {path}"
    assert _admin_guard_precedes_mutation(fn), (
        f"{path}::{handler} (line {fn.lineno}) calls auth_service to mutate a "
        f"user without first checking `_is_admin()` and returning — add "
        f"`if not _is_admin(): notify; return` at the top of the handler"
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
