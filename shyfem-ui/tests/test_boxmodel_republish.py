"""A cache republished under a reader (B-04, B-05).

B-04: the page re-read the published cache only after this session's own
build, so a rebuild started anywhere else went unnoticed until the run was
re-selected. B-05: the loaders opened ``meta.json`` and the Parquet files one
by one, so a publish landing between two opens paired one build's meta with
another build's frames.
"""

import ast
import json
import pathlib
from pathlib import Path

import pandas as pd
import pytest

from shyfem_ui.pages import boxmodel as page
from shyfem_ui.services import boxmodel_cache as bc

SRC = pathlib.Path(page.__file__)
FRAMES = ("state_daily", "flux_daily", "meteo_daily")


def _write_build(d: Path, tag: str) -> Path:
    """A minimal published-cache directory whose every file names its build."""
    d.mkdir(parents=True)
    (d / "meta.json").write_text(
        json.dumps({"build": tag, "period": {"start": "2009-01-01", "end": "2009-01-02"}})
    )
    for name in FRAMES:
        pd.DataFrame(
            {"date": pd.to_datetime(["2009-01-01"]), "box": [1], "build": [tag]}
        ).to_parquet(d / f"{name}.parquet")
    return d


def _publish(root: Path, tag: str) -> Path:
    return bc.publish(_write_build(root / f"fix.tmp-{tag}", tag), "fix")


def test_a_republished_cache_changes_its_fingerprint(tmp_path):
    cache = _publish(tmp_path, "a")
    loaded = bc.load_cache(cache, "fix")
    assert loaded.fingerprint is not None
    assert bc.published_fingerprint(cache) == loaded.fingerprint
    _publish(tmp_path, "b")
    assert bc.published_fingerprint(cache) != loaded.fingerprint
    assert bc.load_cache(cache, "fix").meta["build"] == "b"


def test_nothing_published_has_no_fingerprint(tmp_path):
    assert bc.published_fingerprint(tmp_path / "fix") is None


@pytest.mark.parametrize("loader", [bc.load_cache, bc.load_cache_state])
def test_a_publish_mid_read_never_mixes_two_builds(tmp_path, monkeypatch, loader):
    cache = _publish(tmp_path, "a")
    real = pd.read_parquet
    calls = {"n": 0}

    def read_parquet(path, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            _publish(tmp_path, "b")  # lands after meta.json was read
        return real(path, *a, **k)

    monkeypatch.setattr(bc.pd, "read_parquet", read_parquet)
    run = loader(cache, "fix")
    frames = [run.state_daily] + [f for f in (run.flux_daily, run.meteo_daily) if not f.empty]
    assert {run.meta["build"]} | {f["build"].iloc[0] for f in frames} == {"b"}
    assert run.fingerprint == bc.published_fingerprint(cache)


def test_a_cache_that_keeps_changing_is_refused(tmp_path, monkeypatch):
    cache = _publish(tmp_path, "a")
    real = pd.read_parquet
    calls = {"n": 0}

    def read_parquet(path, *a, **k):
        calls["n"] += 1
        _publish(tmp_path, f"n{calls['n']}")
        return real(path, *a, **k)

    monkeypatch.setattr(bc.pd, "read_parquet", read_parquet)
    monkeypatch.setattr(bc, "LOAD_RETRY_SECONDS", 0)
    with pytest.raises(OSError, match="kept changing"):
        bc.load_cache_state(cache, "fix")


def test_a_broken_cache_is_raised_at_once_not_retried(tmp_path, monkeypatch):
    cache = _publish(tmp_path, "a")
    (cache / "state_daily.parquet").unlink()
    monkeypatch.setattr(bc, "LOAD_ATTEMPTS", 1000)  # a retry loop would hang here
    with pytest.raises(OSError):
        bc.load_cache_state(cache, "fix")
    with pytest.raises(OSError):
        bc.load_cache_state(tmp_path / "nothing", "fix")


# --- the page's watch ---------------------------------------------------------


def test_published_changed_measures_held_runs_against_what_they_hold():
    assert not page._published_changed({"a": 1}, [("a", 1)], {})
    assert page._published_changed({"a": 2}, [("a", 1)], {"a": 2})
    assert page._published_changed({"a": None}, [("a", 1)], {})  # deleted
    # The header run and its Compare copy are both checked.
    assert page._published_changed({"a": 2}, [("a", 2), ("a", 1)], {})


def test_published_changed_measures_other_runs_against_the_last_tick():
    assert not page._published_changed({"b": 5}, [], {})  # first sighting
    assert not page._published_changed({"b": 5}, [], {"b": 5})  # unreadable, unchanged
    assert page._published_changed({"b": 5}, [], {"b": None})  # built elsewhere
    assert page._published_changed({"b": 6}, [], {"b": 5})  # rebuilt elsewhere


def _function(name: str) -> ast.AST:
    for node in ast.walk(ast.parse(SRC.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(name)


def _calls(fn) -> set[str]:
    def dotted(n):
        if isinstance(n, ast.Attribute):
            return f"{dotted(n.value)}.{n.attr}"
        return getattr(n, "id", "")

    return {dotted(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}


def test_the_watch_rearms_and_reloads_on_a_change():
    calls = _calls(_function("_watch_published"))
    assert {"reactive.invalidate_later", "published_fingerprint", "_watch_decision"} <= calls
    assert "_bump_cache_generation" in calls
    # It must never read a reactive it writes.
    assert "cache_generation.get" not in calls


def test_the_hourly_window_is_checked_against_the_loaded_build():
    calls = _calls(_function("_read_hourly_window_checked"))
    assert "published_fingerprint" in calls


# --- _watch_decision: what the watch measures (B-04 review) -----------------


def _decide(**kw):
    from shyfem_ui.pages.boxmodel import _watch_decision

    base = dict(states=[], held_run=None, pending=False, seen={}, since_bump=None)
    base.update(kw)
    published = base.pop("published")
    return _watch_decision(published, **base)


def test_the_watch_skips_while_a_read_is_pending():
    assert _decide(published={"X": "F2"}, held_run=("X", "F1", False), pending=True) == "skip"


def test_a_held_published_build_is_measured_against_what_it_holds():
    assert _decide(published={"X": "F2"}, held_run=("X", "F1", False), seen={"X": "F2"}) == "bump"
    assert _decide(published={"X": "F1"}, held_run=("X", "F1", False), seen={"X": "F1"}) == "none"


def test_the_live_fallback_is_measured_tick_to_tick_only():
    # Shown during a rebuild, the fallback is by design the previous build:
    # measured against `published` it would differ for the whole build.
    assert _decide(published={"X": "F2"}, held_run=("X", "F1", True), seen={"X": "F2"}) == "none"
    # A publish between two ticks still reloads.
    assert _decide(published={"X": "F3"}, held_run=("X", "F1", True), seen={"X": "F2"}) == "bump"


def test_the_watch_bumps_at_most_once_per_tick_interval():
    from shyfem_ui.pages.boxmodel import WATCH_SECONDS

    kw = dict(published={"X": "F2"}, held_run=("X", "F1", False), seen={"X": "F2"})
    assert _decide(since_bump=WATCH_SECONDS / 3, **kw) == "skip"
    assert _decide(since_bump=WATCH_SECONDS + 1, **kw) == "bump"


def test_a_rebuild_over_a_republished_cache_does_not_loop():
    """The loop the review found: X is held at F1, another session publishes
    F2, and a new build of X starts before the next tick. The watch bumps;
    the loader, seeing "building", re-stores the F1 fallback under the new
    key; the store write re-runs the watch at once (no time passes). It used
    to bump again on every re-run for the whole build."""
    seen = {"X": "F1"}
    published = {"X": "F2"}
    held = ("X", "F1", False)  # the first tick: X really is the F1 build
    since_bump = None
    bumps = 0
    for _rerun in range(100):
        decision = _decide(published=published, held_run=held, seen=seen, since_bump=since_bump)
        if decision == "skip":
            continue
        seen = published
        if decision == "bump":
            bumps += 1
            since_bump = 0.0  # re-runs happen within the same flush
            held = ("X", "F1", True)  # the loader stores the live fallback
    assert bumps == 1
