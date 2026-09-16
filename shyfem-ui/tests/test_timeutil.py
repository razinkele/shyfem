"""shyfem_ui.timeutil.utcnow -- the one sanctioned UTC clock."""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from shyfem_ui.timeutil import utcnow


def test_utcnow_is_naive_utc():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    value = utcnow()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert value.tzinfo is None
    assert before <= value <= after < before + timedelta(seconds=5)


def test_package_never_calls_datetime_utcnow():
    """Static guard for paths the runtime warning filter cannot reach.

    AST-based so docstrings and comments that *mention* the deprecated names
    (like the one in timeutil itself) do not count; only real attribute
    references do, including bare ``default=datetime.utcnow`` callables.
    """
    pkg = Path(__file__).parent.parent / "shyfem_ui"
    offenders = []
    for f in sorted(pkg.rglob("*.py")):
        tree = ast.parse(f.read_text(), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"utcnow", "utcfromtimestamp"}:
                offenders.append(f"{f.relative_to(pkg.parent)}:{node.lineno}")
    assert offenders == [], offenders
