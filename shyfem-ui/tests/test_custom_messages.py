"""Every custom message the server sends must actually reach the browser.

``Session.send_custom_message`` is a coroutine. Calling it from a SYNCHRONOUS
reactive effect builds a coroutine that is never run: the browser receives
nothing, and the only trace is a ``RuntimeWarning: coroutine ... was never
awaited`` in the worker log -- which Shiny Server deletes when the worker exits
cleanly, so it is invisible in practice.

Two such calls shipped and survived: the what's-new dismissal (so the modal
came back for every user on every visit, and intercepted the first click on the
page) and ``nav_to`` (so the "go to this page" buttons on the Dashboard and the
Tutorial silently did nothing).
"""

import ast
import asyncio
import inspect
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "shyfem_ui"


def _send_call_sites(tree: ast.AST) -> list[tuple[ast.Call, bool]]:
    """``(call, is_delivered)`` for every ``*.send_custom_message(...)`` call.

    Delivered means the coroutine is awaited, or handed straight to
    ``create_task``/``ensure_future``. Anything else builds a coroutine nobody
    runs.
    """
    awaited: set[int] = set()
    scheduled: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            awaited.add(id(node.value))
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name in ("create_task", "ensure_future"):
                scheduled.update(id(a) for a in node.args if isinstance(a, ast.Call))
    sites = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_custom_message"
        ):
            sites.append((node, id(node) in awaited or id(node) in scheduled))
    return sites


def _all_sites():
    for path in sorted(SRC.rglob("*.py")):
        yield path, _send_call_sites(ast.parse(path.read_text()))


def test_no_custom_message_send_is_left_unawaited():
    offenders = [
        f"{path.relative_to(SRC.parent)}:{node.lineno}"
        for path, sites in _all_sites()
        for node, delivered in sites
        if not delivered
    ]
    assert not offenders, (
        "send_custom_message is a coroutine: these calls are neither awaited nor "
        "scheduled, so the browser never receives them -- " + ", ".join(offenders)
    )


def test_the_scanner_still_finds_the_call_sites():
    """Guard against the scan silently matching nothing (a green test that
    proves the matcher broke, not that the code is clean)."""
    total = sum(len(sites) for _path, sites in _all_sites())
    assert total >= 5, f"expected several send_custom_message calls, found {total}"


class _FakeSession:
    def __init__(self):
        self.sent = []

    async def send_custom_message(self, name, payload):
        self.sent.append((name, payload))


def test_send_message_soon_delivers_from_a_synchronous_caller():
    """``nav_to`` is handed to other page modules as a plain callback and is
    called from their sync effects, so it cannot await. Scheduling on the
    session's own loop is what makes the message actually go out."""
    from shyfem_ui import app as app_mod

    session = _FakeSession()

    async def go():
        task = app_mod._send_message_soon(session, "shyfem_nav", {"tab": "Grid Prep"})
        assert task in app_mod._PENDING_SENDS, "a pending task needs a strong reference"
        await task
        await asyncio.sleep(0)
        assert task not in app_mod._PENDING_SENDS, "finished tasks must be released"

    asyncio.run(go())
    assert session.sent == [("shyfem_nav", {"tab": "Grid Prep"})]


def test_send_message_soon_outside_a_loop_creates_no_orphan_coroutine():
    """With no running loop there is nothing to schedule on. The coroutine must
    not be built at all, or we would trade a silent miss for the same
    never-awaited warning this whole module exists to prevent."""
    from shyfem_ui import app as app_mod

    session = _FakeSession()
    assert app_mod._send_message_soon(session, "shyfem_nav", {"tab": "x"}) is None
    assert session.sent == []


def test_the_whats_new_dismissal_awaits_its_message():
    """This one CAN await -- a reactive effect may be async -- and awaiting is
    the plainer form, so it is not routed through the scheduler."""
    from shyfem_ui import app as app_mod

    src = inspect.getsource(app_mod._build_server)
    assert "async def _dismiss_whats_new" in src
    body = src[src.index("def _dismiss_whats_new") :][:400]
    assert "await session.send_custom_message" in body
