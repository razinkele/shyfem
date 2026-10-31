"""B-06: the box-model page reads its Parquet cache off the event loop.

The worker serves every session from one event loop, so a cache read inside a
``reactive.calc`` (``load_cache`` for the selected run, ``load_cache_state``
for every run of the Compare tab, ``read_hourly_window`` for the output-step
window) froze every other user's page for as long as it took. Each read now
runs in ``asyncio.to_thread`` from an async effect, and the calcs only look up
what that effect stored.
"""

from __future__ import annotations

import ast
import pathlib
import textwrap
from types import SimpleNamespace

import pandas as pd

from shyfem_ui.pages import boxmodel as page
from tests._test_helpers import get_server_source

#: Everything that opens cache files. None of it may be called directly from
#: the page server: only handed to ``asyncio.to_thread``.
BLOCKING = {
    "load_cache",
    "load_cache_state",
    "read_hourly_window",
    "_load_compare_state",
    "_read_cached_run",
    "_read_run_states",
    "_read_hourly_window_checked",
}


def _server_tree() -> ast.AST:
    return ast.parse(textwrap.dedent(get_server_source(page, "boxmodel_server")))


def _name(node) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return getattr(node, "id", "")


def test_the_page_server_never_reads_the_cache_on_the_loop():
    direct = sorted(
        {
            _name(c.func)
            for c in ast.walk(_server_tree())
            if isinstance(c, ast.Call) and _name(c.func) in BLOCKING
        }
    )
    assert direct == [], f"called on the event loop: {direct}"


def test_each_reader_is_handed_to_a_thread():
    threaded = {
        _name(c.args[0])
        for c in ast.walk(_server_tree())
        if isinstance(c, ast.Call) and _name(c.func) == "asyncio.to_thread" and c.args
    }
    assert {"_read_cached_run", "_read_run_states", "_read_hourly_window_checked"} <= threaded


def test_the_loaders_are_async_effects_that_never_read_what_they_write():
    tree = _server_tree()
    fns = {
        n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name, store in (
        ("_load_cached_run", "cached_store"),
        ("_load_run_states", "run_states_store"),
        ("_load_hourly_window", "hourly_store"),
    ):
        fn = fns[name]
        assert isinstance(fn, ast.AsyncFunctionDef), name
        calls = {_name(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
        assert f"{store}.set" in calls, name
        assert f"{store}.get" not in calls, name


# --- the module-level readers do what the calcs used to do -----------------


def _write_cache(d: pathlib.Path, *, box_column: bool = True) -> None:
    from tests.test_boxmodel_republish import _write_build

    _write_build(d, "a")
    if not box_column:
        pd.DataFrame({"date": pd.to_datetime(["2020-01-01"])}).to_parquet(d / "state_daily.parquet")


def test_read_cached_run_validates_what_downstream_assumes(tmp_path):
    good = tmp_path / "good"
    _write_cache(good)
    run = page._read_cached_run(good, "good")
    assert run.run_id == "good" and run.fingerprint is not None

    bad = tmp_path / "bad"
    _write_cache(bad, box_column=False)
    try:
        page._read_cached_run(bad, "bad")
    except KeyError as exc:
        assert "box" in str(exc)
    else:
        raise AssertionError("a state_daily without a box column must be refused")


def test_read_run_states_skips_unready_runs_and_reports_broken_ones(tmp_path, monkeypatch):
    statuses = {"a": "ready", "b": "missing", "c": "stale"}
    monkeypatch.setattr(
        page,
        "cache_status",
        lambda work, rid, rdir, reg, cap: SimpleNamespace(state=statuses[rid]),
    )

    def fake_load(cache_dir, run_id, err):
        if run_id == "c":
            return None, f"{run_id}: broken"
        return SimpleNamespace(run_id=run_id), None

    monkeypatch.setattr(page, "_load_compare_state", fake_load)
    runs = [SimpleNamespace(id=r, dir=tmp_path / r) for r in ("a", "b", "c")]
    states, problems = page._read_run_states(tmp_path, runs, None, 60.0, str)
    assert list(states) == ["a"]
    assert problems == ["c: broken"]


def test_read_hourly_window_checked_refuses_a_window_from_another_build(tmp_path):
    cache = tmp_path / "c"
    _write_cache(cache)
    period = (pd.Timestamp("2009-01-01"), pd.Timestamp("2009-01-01"))
    fingerprint = page.published_fingerprint(cache)
    # no state_hourly.parquet: the daily path, no message
    assert page._read_hourly_window_checked(cache, fingerprint, period) == (None, None)
    # the page holds another build than the one published now
    assert page._read_hourly_window_checked(cache, ("other",), period) == (
        None,
        page.CACHE_REPUBLISHED_MESSAGE,
    )


# --- the watch must not count a pending reload as "held" -------------------


def test_settled_result_is_none_while_a_newer_request_is_pending():
    assert page._settled_result(None, ("p", "r", 1)) is None
    assert page._settled_result((("p", "r", 1), ("run", None)), ("p", "r", 1)) == ("run", None)
    # the store still holds generation 1 while generation 2 is being read
    assert page._settled_result((("p", "r", 1), ("run", None)), ("p", "r", 2)) is None


def test_the_watch_measures_only_settled_loads():
    """While the reload it asked for is still being read, the calcs hand out
    the previous build (a stale-but-consistent fallback). Were the watch to
    measure that against the new fingerprint it would bump again, re-run at
    once, and spin until the read landed. It reads the settled accessors, and
    checks their keys without depending on ``cache_generation`` (which it
    writes)."""
    tree = _server_tree()
    fns = {
        n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    calls = {_name(c.func) for c in ast.walk(fns["_watch_published"]) if isinstance(c, ast.Call)}
    assert {"_settled_cached", "_settled_run_states"} <= calls
    assert not {"cached", "all_run_states", "cached_result", "all_run_states_result"} & calls
    for name in ("_settled_cached", "_settled_run_states"):
        src = ast.unparse(fns[name])
        assert "reactive.isolate()" in src, name
        assert "_settled_result(" in src, name
