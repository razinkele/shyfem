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
import textwrap

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
    ("mesh_builder", "_on_save", "editor"),  # exports .grd into the project dir
    ("home", "_do_import_grid", "editor"),  # writes a Grid into an existing project
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


def _name_is_negated_in_test(test: ast.AST, name: str) -> bool:
    """True if ``name`` appears in ``test`` under a logical negation — i.e.
    ``not name`` or ``name is None`` / ``name == None``. Such a test, when used
    as an early-exit guard (``if <test>: return``), returns on the ALLOW case
    (denial reason falsy/None) and falls through on the DENY case, inverting the
    guard's polarity. Used to reject backwards guards in the enforcement check.
    """
    for node in ast.walk(test):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(node.operand)):
                return True
        if isinstance(node, ast.Compare):
            left_is_name = any(
                isinstance(n, ast.Name) and n.id == name for n in ast.walk(node.left)
            )
            none_cmp = any(isinstance(op, (ast.Is, ast.Eq)) for op in node.ops) and any(
                isinstance(c, ast.Constant) and c.value is None for c in node.comparators
            )
            if left_is_name and none_cmp:
                return True
    return False


# Call names that mutate state in a write handler (disk write, subprocess,
# job submission). Used to assert the fail-closed guard runs BEFORE the side
# effect, not after — mirrors _AUTH_SERVICE_MUTATIONS for the admin panel.
_WRITE_MUTATION_CALLS = {
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "rmtree",
    "rename",
    "replace",
    "run",
    "Popen",
    "check_call",
    "check_output",
    "submit",
    "enqueue",
    "add_job",
    "export_grd",
    "copy2",
    "copyfile",
    "copytree",
}


def _stmt_has_write_mutation(stmt: ast.stmt) -> bool:
    """True if ``stmt`` (not descending into nested defs) contains a call whose
    name is in _WRITE_MUTATION_CALLS."""
    for node in ast.walk(stmt):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Call):
            callee = node.func
            name = (
                callee.attr
                if isinstance(callee, ast.Attribute)
                else (callee.id if isinstance(callee, ast.Name) else "")
            )
            if name in _WRITE_MUTATION_CALLS:
                return True
    return False


def _guard_precedes_mutation(func_def: ast.AST) -> bool:
    """True if a fail-closed ``editor_denied_reason`` guard is assigned, enforced
    with DENIAL-truthy polarity (``if _denied: ...; return``), and that
    enforcement appears BEFORE the first write-mutation call in the body.

    Closes the latent false-assurance hole where a mutation-first body
    (``path.write_text(...); _denied = editor_denied_reason(...); if _denied:
    return``) passed the call-presence + enforcement + unconditional checks while
    running the side effect unguarded. Mirrors _admin_guard_precedes_mutation.
    """
    guard_vars: set[str] = set()
    saw_enforced_guard = False
    for stmt in func_def.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(stmt, ast.Assign) and _is_guard_call(stmt.value):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    guard_vars.add(tgt.id)
        if isinstance(stmt, ast.If):
            then_exits = any(
                isinstance(s, (ast.Return, ast.Raise)) for b in stmt.body for s in ast.walk(b)
            )
            hit = {n.id for n in ast.walk(stmt.test) if isinstance(n, ast.Name)} & guard_vars
            if then_exits and any(not _name_is_negated_in_test(stmt.test, v) for v in hit):
                saw_enforced_guard = True
                continue
        if _stmt_has_write_mutation(stmt):
            return saw_enforced_guard  # mutation reached — guard must already hold
    return saw_enforced_guard


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
        then_exits = any(
            isinstance(s, (ast.Return, ast.Raise)) for stmt in node.body for s in ast.walk(stmt)
        )
        if then_exits:
            # Only count names tested with DENIAL-truthy polarity. `if not
            # _denied: return` / `if _denied is None: return` return on ALLOW
            # and fall through on DENY — a backwards guard — so the negated
            # name must NOT be recorded as enforced.
            for name in {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}:
                if not _name_is_negated_in_test(node.test, name):
                    self.enforced_vars.add(name)
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
    if role != "viewer":
        assert _guard_precedes_mutation(fn), (
            f"{path}::{handler} (line {fn.lineno}) performs a write-mutation "
            f"(disk write / subprocess / job submit) BEFORE the fail-closed "
            f"guard returns — the side effect runs unguarded. Move the "
            f"`_denied = editor_denied_reason(...); if _denied: ...; return` "
            f"above the first mutating call (and keep denial-truthy polarity)."
        )


def _call_index(stmts: "list[ast.stmt]", callee_attr: str) -> "int | None":
    """Index of the first top-level statement (no descent into nested defs)
    containing a call whose Name.id or Attribute.attr equals ``callee_attr``."""
    for i, stmt in enumerate(stmts):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Call):
                c = node.func
                name = (
                    c.attr
                    if isinstance(c, ast.Attribute)
                    else (c.id if isinstance(c, ast.Name) else "")
                )
                if name == callee_attr:
                    return i
    return None


# Handlers that persist a user-supplied path/filename to disk. Each must route
# the target through config.validate_save_path (rejects traversal outside
# work_dir + null bytes) BEFORE the write call — otherwise an editor can write
# outside the project tree via an absolute path or '..' segments.
# (page, handler, write_call_name)
PATH_SAVE_HANDLERS = [
    ("simulation", "_confirm_save", "save"),
    ("physics", "save_file", "save"),
    ("mesh_builder", "_on_save", "export_grd"),
]


@pytest.mark.parametrize("page,handler,write_call", PATH_SAVE_HANDLERS)
def test_save_validates_path_before_write(page, handler, write_call):
    path = _PAGES_DIR / f"{page}.py"
    fn = _find_function_def(ast.parse(path.read_text()), handler)
    assert fn is not None, f"{handler!r} not found in {path}"
    vidx = _call_index(fn.body, "validate_save_path")
    sidx = _call_index(fn.body, write_call)
    assert vidx is not None, (
        f"{path}::{handler} (line {fn.lineno}) writes a user-supplied path "
        f"without config.validate_save_path — a traversal path (e.g. "
        f"'../../other/x' or '/etc/x') escapes the work dir. Validate first."
    )
    assert (
        sidx is not None and vidx < sidx
    ), f"{path}::{handler}: validate_save_path must precede {write_call}()"


# Job-cancel handlers must authorize (job_cancel_denied_reason for per-job
# cancels; editor_denied_reason for the ensemble stop) BEFORE the cancel sink —
# the job id / ensemble state is client-addressable, so an unauthorized client
# could otherwise cancel a collaborator's job.
# (page, handler, guard_call, cancel_sink)
# Ensemble stop authorizes per-job INSIDE _cancel_jobs (behaviorally covered by
# tests/test_ensemble_helpers.py), so it is not an AST row here.
CANCEL_HANDLERS = [
    ("run", "_cancel_active_job", "job_cancel_denied_reason", "cancel"),
    ("run", "_cancel_selected_job", "job_cancel_denied_reason", "cancel"),
]


def _call_name(node: ast.AST) -> "str | None":
    if not isinstance(node, ast.Call):
        return None
    c = node.func
    return c.attr if isinstance(c, ast.Attribute) else (c.id if isinstance(c, ast.Name) else None)


def _guard_enforced_by_name(func_def: ast.AST, guard_name: str) -> bool:
    """True if a name assigned from a call to ``guard_name`` is tested with
    DENIAL-truthy polarity in an if-block that returns/raises — i.e. the denial
    is actually consumed (not computed and ignored, not inverted). Generalizes
    _guard_is_enforced to an arbitrary guard function name."""
    guard_vars: set[str] = set()
    enforced: set[str] = set()
    for stmt in func_def.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(stmt, ast.Assign) and any(
            _call_name(n) == guard_name for n in ast.walk(stmt.value)
        ):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    guard_vars.add(tgt.id)
        if isinstance(stmt, ast.If):
            then_exits = any(
                isinstance(s, (ast.Return, ast.Raise)) for b in stmt.body for s in ast.walk(b)
            )
            if then_exits:
                for nm in {n.id for n in ast.walk(stmt.test) if isinstance(n, ast.Name)}:
                    if not _name_is_negated_in_test(stmt.test, nm):
                        enforced.add(nm)
    return bool(guard_vars & enforced)


@pytest.mark.parametrize("page,handler,guard,sink", CANCEL_HANDLERS)
def test_cancel_handler_authorizes_before_cancel(page, handler, guard, sink):
    path = _PAGES_DIR / f"{page}.py"
    fn = _find_function_def(ast.parse(path.read_text()), handler)
    assert fn is not None, f"{handler!r} not found in {path}"
    gidx = _call_index(fn.body, guard)
    sidx = _call_index(fn.body, sink)
    assert gidx is not None, (
        f"{path}::{handler} (line {fn.lineno}) cancels a job without calling "
        f"{guard} — an unauthorized client could cancel a collaborator's job."
    )
    assert (
        sidx is not None and gidx < sidx
    ), f"{path}::{handler}: {guard} must precede the cancel ({sink})"
    assert _guard_enforced_by_name(fn, guard), (
        f"{path}::{handler}: the {guard} result must be assigned and acted on "
        f"(`if _denied: ...; return`, denial-truthy polarity) before the cancel — "
        f"computing it and ignoring/inverting it re-opens the bypass."
    )


# Project create/clone/import handlers must fail closed via identity_denied_reason
# BEFORE constructing the Project — both to avoid an owner_id=None orphan on an
# unresolved identity and to enforce tutorial read-only on the create-class path.
# _do_clone additionally reads its source via load_project_context (viewer gate)
# but still needs identity_denied_reason because cloning WRITES a new project.
CREATE_HANDLERS = [
    "_create_project",
    "_create_tutorial_project",
    "_do_import_project",
    "_do_clone",
]


@pytest.mark.parametrize("handler", CREATE_HANDLERS)
def test_create_handler_requires_identity(handler):
    path = _PAGES_DIR / "home.py"
    fn = _find_function_def(ast.parse(path.read_text()), handler)
    assert fn is not None, f"{handler!r} not found in {path}"
    gidx = _call_index(fn.body, "identity_denied_reason")
    sidx = _call_index(fn.body, "Project")
    assert gidx is not None, (
        f"home.py::{handler} (line {fn.lineno}) creates a Project without "
        f"identity_denied_reason — in server mode an unresolved identity would "
        f"create an owner_id=None orphan. Add the fail-closed identity guard."
    )
    assert _guard_enforced_by_name(fn, "identity_denied_reason"), (
        f"home.py::{handler}: the identity_denied_reason result must be acted on "
        f"(`if _denied: ...; return`) before creating the Project."
    )
    assert (
        sidx is not None and gidx < sidx
    ), f"home.py::{handler}: identity_denied_reason must precede Project(...)"


def test_submit_job_stamps_ws_resolved_owner():
    """run._submit_job must stamp the job OWNER from the WS-validated identity
    (_usr = current_user()), not the HTTP-scope _user_id.

    get_current_user() (the source of _user_id) returns None in the proxied
    Shiny WebSocket scope, so stamping user_id=_user_id persists owner=None for
    every server-mode job — killing the owner-cancel branch of
    job_cancel_denied_reason. The project_id stamp already uses _proj (WS); the
    owner must come from the same WS identity (mirrors ensemble.py)."""
    fn = _find_function_def(ast.parse((_PAGES_DIR / "run.py").read_text()), "_submit_job")
    assert fn is not None
    call = next(
        (n for n in ast.walk(fn) if _call_name(n) == "build_job_spec"),
        None,
    )
    assert call is not None, "_submit_job must build the job spec via build_job_spec"
    uid_kw = next((k for k in call.keywords if k.arg == "user_id"), None)
    assert uid_kw is not None, "build_job_spec must receive a user_id"
    names = {n.id for n in ast.walk(uid_kw.value) if isinstance(n, ast.Name)}
    assert "_usr" in names and "_user_id" not in names, (
        "job owner (user_id) must be sourced from the WS-resolved identity "
        "(_usr = current_user()), not the HTTP-scope _user_id (None behind the "
        "Shiny proxy WS, which kills the owner-cancel right)."
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
    assert _guard_precedes_mutation(fn), (
        f"{path}::_handle_save writes to disk BEFORE the fail-closed guard returns "
        f"— move the guard above path.write_text"
    )


ADMIN_MUTATION_HANDLERS = [
    "_do_reset_pw",
    "_toggle_active",
    "_toggle_role",
    "_do_delete_user",
    "_do_create_user",
    "_send_test_email",  # sends SMTP mail — admin-only side effect
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
            # Require the NEGATED form `if not _is_admin(): ...; return`. The
            # un-negated `if _is_admin(): return` returns for admins and falls
            # through to the mutation for everyone else — the inverse of a guard.
            test_checks_not_admin = any(
                isinstance(n, ast.UnaryOp)
                and isinstance(n.op, ast.Not)
                and any(
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Name)
                    and c.func.id == "_is_admin"
                    for c in ast.walk(n.operand)
                )
                for n in ast.walk(stmt.test)
            )
            body_returns = any(isinstance(s, ast.Return) for b in stmt.body for s in ast.walk(b))
            if test_checks_not_admin and body_returns:
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


def _fn_from_src(src: str, name: str) -> ast.AST:
    """Parse a dedented source snippet and return the named function def."""
    fn = _find_function_def(ast.parse(textwrap.dedent(src)), name)
    assert fn is not None, f"{name!r} not found in snippet"
    return fn


# --- Polarity: the enforcing `if` must test the denial truthy, not negated ---
# Latent false-assurance defect (review #3): `if not _denied: return` returns on
# ALLOW and proceeds on DENY — a backwards guard. The enforcement check must
# reject it, not certify it.


def test_enforcement_accepts_denial_truthy_polarity():
    fn = _fn_from_src(
        """
        def _h():
            _denied = editor_denied_reason(1, u, min_role="editor")
            if _denied:
                notify(_denied)
                return
            do_mutation()
        """,
        "_h",
    )
    assert _guard_is_enforced(fn)


def test_enforcement_rejects_inverted_not_polarity():
    fn = _fn_from_src(
        """
        def _h():
            _denied = editor_denied_reason(1, u, min_role="editor")
            if not _denied:
                return
            do_mutation()
        """,
        "_h",
    )
    assert not _guard_is_enforced(fn)


def test_enforcement_rejects_inverted_is_none_polarity():
    fn = _fn_from_src(
        """
        def _h():
            _denied = editor_denied_reason(1, u, min_role="editor")
            if _denied is None:
                return
            do_mutation()
        """,
        "_h",
    )
    assert not _guard_is_enforced(fn)


# --- Ordering: the enforced guard must precede the first mutating call ---
# Latent false-assurance defect (review #3): a mutation-first body
# (write_text(); _denied = ...; if _denied: return) passed every assertion.


def test_ordering_accepts_guard_before_mutation():
    fn = _fn_from_src(
        """
        def _h():
            _denied = editor_denied_reason(1, u, min_role="editor")
            if _denied:
                return
            path.write_text(text)
        """,
        "_h",
    )
    assert _guard_precedes_mutation(fn)


def test_ordering_rejects_mutation_before_guard():
    fn = _fn_from_src(
        """
        def _h():
            path.write_text(text)
            _denied = editor_denied_reason(1, u, min_role="editor")
            if _denied:
                return
        """,
        "_h",
    )
    assert not _guard_precedes_mutation(fn)


def test_ordering_rejects_subprocess_before_guard():
    fn = _fn_from_src(
        """
        def _h():
            subprocess.run([prog])
            _denied = editor_denied_reason(1, u, min_role="editor")
            if _denied:
                return
        """,
        "_h",
    )
    assert not _guard_precedes_mutation(fn)


# --- Admin polarity: the recheck must be `if not _is_admin(): return` ---
# Review #3: `if _is_admin(): return` (returns when admin, proceeds otherwise)
# was accepted — the inverse of a guard. Only the negated form is a real gate.


def test_admin_guard_accepts_negated_isadmin():
    fn = _fn_from_src(
        """
        def _do_delete_user():
            if not _is_admin():
                return
            auth_service.delete_user(1)
        """,
        "_do_delete_user",
    )
    assert _admin_guard_precedes_mutation(fn)


def test_admin_guard_rejects_unnegated_isadmin():
    fn = _fn_from_src(
        """
        def _do_delete_user():
            if _is_admin():
                return
            auth_service.delete_user(1)
        """,
        "_do_delete_user",
    )
    assert not _admin_guard_precedes_mutation(fn)


def test_step2_handler_table_is_complete():
    """Sentinel test: fail loudly if Step 2 was skipped. Prevents the
    parametrized tests above from silently skipping all 9 rows."""
    placeholders = [page for page, h, _ in WRITE_HANDLERS if h.startswith(_PLACEHOLDER_PREFIX)]
    assert not placeholders, (
        f"WRITE_HANDLERS still has {len(placeholders)} placeholder rows: "
        f"{placeholders}. Fill in the real handler names from Step 2 "
        "before declaring Task 8 complete."
    )
