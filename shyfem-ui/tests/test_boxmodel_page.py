"""Wiring and page-discipline tests for the Box-model page (spec §8).

The page itself is exercised end to end by the Playwright test (Task 13);
what is asserted here is the wiring Task 13 drives (module id, nav value,
page div, server mount) plus the page-level invariants that are cheap to
check statically or as pure functions: every write handler re-checks
``editor_denied_reason``, the poller exists, ``reconcile_tmp_dirs`` runs at
page load, manifest text never reaches the browser as raw HTML, and no
user-facing message carries a raw absolute host path.
"""

import inspect
import re

import pytest

from tests._test_helpers import get_server_source


def _code_of(page_module, server_name: str):
    """Return ``name -> source of that nested function with its docstring
    removed``, for assertions about what a function *does* rather than what its
    documentation happens to mention."""
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(get_server_source(page_module, server_name)))

    def body(name: str) -> str:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                stripped = list(node.body)
                if (
                    stripped
                    and isinstance(stripped[0], ast.Expr)
                    and isinstance(stripped[0].value, ast.Constant)
                    and isinstance(stripped[0].value.value, str)
                ):
                    stripped = stripped[1:]
                return "\n".join(ast.unparse(n) for n in stripped)
        raise AssertionError(f"nested function {name!r} not found in {server_name}")

    return body


def test_page_is_registered():
    import shyfem_ui.pages as pages

    assert "boxmodel" in pages.__all__
    from shyfem_ui.pages import boxmodel

    assert callable(boxmodel.boxmodel_ui) and callable(boxmodel.boxmodel_server)


def test_app_wiring():
    import shyfem_ui.app as app

    src = inspect.getsource(app)
    assert '"value": "Box-model"' in src and 'id="sf-page-Box-model"' in src
    assert re.search(r'boxmodel\.boxmodel_server\(\s*"boxmodel",\s*config,', src)
    assert "active_project=active_project" in src.split("boxmodel.boxmodel_server(")[1][:400]


def test_server_wiring_gates_and_polling():
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    assert src.count("editor_denied_reason(") >= 2  # build + cancel
    assert "start_build(" in src and "cancel_build(" in src and "load_manifest(" in src
    assert "invalidate_later" in src
    assert "ui.HTML(" not in src  # manifest text via ui.tags only
    assert "grid_map_server(" in src and "on_box_click" in src
    # The reconcile now lives in the module-level _reconcile_cache_dir (so its
    # write gate is testable without a live session), and the page server calls
    # it at manifest-load time. Assert the same wiring across both halves,
    # rather than for the call literal that used to sit in the server body.
    assert "_reconcile_cache_dir(" in src, "the page must reconcile at page load"
    assert "reconcile_tmp_dirs(" in inspect.getsource(boxmodel)


def test_download_uses_non_deprecated_renderer():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._render_download is not None


# --- obligation-driven helpers -------------------------------------------


class _StubConfig:
    """Minimal stand-in for Config.display_path in server mode."""

    def display_path(self, path, user):
        return f"~/{str(path).rsplit('/', 1)[-1]}"


def test_safe_error_strips_absolute_host_paths():
    """Obligation (Task 4 review): ManifestError/confine_path text may embed
    raw host paths; nothing user-facing may leak the host layout."""
    from shyfem_ui.pages import boxmodel

    exc = ValueError(
        "runs[0].dir: Save path '/home/alice/projects/lagoon/run' must be "
        "within work directory: /srv/shyfem/work"
    )
    out = boxmodel._safe_error(exc, _StubConfig(), {"username": "alice"})
    assert "/home/alice" not in out
    assert "/srv/shyfem" not in out
    assert "~/run" in out and "~/work" in out
    assert out.startswith("runs[0].dir:")


def test_safe_error_strips_single_segment_roots():
    """A one-segment absolute path ("/etc", "/tmp") is still an absolute path."""
    from shyfem_ui.pages import boxmodel

    out = boxmodel._safe_error(
        ValueError("runs[0].dir: Path '/etc' is outside allowed directories: /tmp"),
        _StubConfig(),
        None,
    )
    # The stub rewrites to "~/<basename>", so check the *raw* tokens are gone
    # rather than a substring that the replacement itself contains.
    assert "'/etc'" not in out
    assert not out.endswith(": /tmp")
    assert "'~/etc'" in out and out.endswith(": ~/tmp")


def test_safe_error_leaves_non_path_text_alone():
    from shyfem_ui.pages import boxmodel

    exc = ValueError("observations: 3/24 rows dropped; speed in m/s")
    assert boxmodel._safe_error(exc, _StubConfig(), None) == (
        "observations: 3/24 rows dropped; speed in m/s"
    )


def test_bounded_timeout_config_replaces_none_without_mutating():
    """Obligation (Task 6 review): builds must run with a bounded timeout, and
    the shared Config every session holds must not be mutated to get one."""
    from shyfem_ui.config import Config
    from shyfem_ui.pages import boxmodel

    # Pass None explicitly rather than relying on the default: a dev .env with
    # SHYFEM_UI_COMMAND_TIMEOUT_SECONDS set would otherwise fail this test for
    # a reason that has nothing to do with the function under test.
    config = Config(command_timeout_seconds=None)
    assert config.command_timeout_seconds is None
    bounded = boxmodel._bounded_timeout_config(config)
    assert bounded.command_timeout_seconds == boxmodel.BUILD_TIMEOUT_SECONDS
    assert bounded.command_timeout_seconds is not None
    assert config.command_timeout_seconds is None  # original untouched
    assert bounded is not config


def test_bounded_timeout_config_keeps_an_operator_set_timeout():
    from shyfem_ui.config import Config
    from shyfem_ui.pages import boxmodel

    config = Config(command_timeout_seconds=60)
    assert boxmodel._bounded_timeout_config(config) is config


def test_level_bias_renders_as_em_dash():
    """Obligation (Task 7 review): level rows compare anomalies, so their bias
    is structurally ~0 and must not be shown as if it were a real bias."""
    from shyfem_ui.pages import boxmodel

    assert boxmodel._bias_cell("level", 1e-17) == "—"
    assert boxmodel._bias_cell("salinity", 0.125) == "0.125"


def test_cache_period_rejects_a_meta_without_a_period():
    """``cache_status`` calls any parseable meta.json "ready", so a foreign or
    hand-edited cache dir can reach the page without a period. The page must
    turn that into a message, not a KeyError out of an effect/render -- so
    ``_cache_period`` has to raise a type ``cached_result`` catches."""
    from shyfem_ui.pages import boxmodel

    class _Run:
        meta: dict = {"records": 3}

    with pytest.raises((KeyError, TypeError)):
        boxmodel._cache_period(_Run())


def test_fmt_handles_missing_values():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._fmt(None) == ""
    assert boxmodel._fmt(float("nan")) == ""
    assert boxmodel._fmt(1.23456) == "1.235"
    assert boxmodel._fmt(1.23456, 1) == "1.2"


def test_ui_builds_without_a_session():
    """Import-time/UI-construction smoke: a bad kwarg to grid_map_ui or a
    malformed tag only shows up when the UI is actually built."""
    from shyfem_ui.pages import boxmodel

    html = str(boxmodel.boxmodel_ui("boxmodel"))
    for ident in ("boxmodel-run", "boxmodel-build", "boxmodel-cache_state", "boxmodel-skill_table"):
        assert ident in html, f"missing input/output id: {ident}"


def test_safe_text_sanitises_a_service_message():
    """Review Important 1: the cache badge's tooltip is ``CacheStatus.message``,
    which for a failed build is the child process's own error text and can name
    the absolute run directory. It is not an exception, so it needs the
    text-flavoured sanitiser rather than ``_safe_error``."""
    from shyfem_ui.pages import boxmodel

    msg = "build failed: [Errno 2] No such file or directory: '/home/alice/proj/runs/fix'"
    out = boxmodel._safe_text(msg, _StubConfig(), {"username": "alice"})
    assert "/home/alice" not in out
    assert "~/fix" in out
    assert out.startswith("build failed:")


def test_cache_badge_title_is_sanitised_not_raw():
    """The badge must render the message through the sanitiser. Asserted at the
    source, because the render needs a live session."""
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    assert "title=_text(current.message" in src, "badge tooltip must go through _safe_text"
    assert "title=current.message" not in src, "raw CacheStatus.message reaches the browser"


def test_posts_pass_site_names_through_raw_and_the_sink_escapes():
    """Review Important 2 + the double-escaping ruling.

    ``posts()`` hands site names to ``build_box_layers``, whose ``tooltip_html``
    deck.gl renders as innerHTML. The escaping belongs to the code that builds
    that HTML, not to this page: escaping in both places double-escapes, so a
    site legitimately named "Smith & Co" would show as "Smith &amp; Co". So the
    page passes the name through raw -- and the end-to-end guarantee still
    holds, because the sink escapes it.
    """
    from shyfem_ui.components.grid_map import build_box_layers
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    posts_body = code("posts")
    assert "str(site['site'])" in posts_body or 'str(site["site"])' in posts_body
    assert "html.escape" not in posts_body, "the page must not escape -- the sink does"

    # ... and what the page hands over is still safe once the sink builds the HTML
    evil = "<img src=x onerror=alert(1)>"
    layers, _bins = build_box_layers(
        {1: [[21.0, 55.5], [21.01, 55.5], [21.01, 55.51], [21.0, 55.5]]},
        {1: 0.2},
        label="Salinity (psu)",
        posts=[{"site": evil, "lon": 21.005, "lat": 55.505, "value": 0.25}],
    )
    tooltip = layers[1]["data"][0]["tooltip_html"]
    assert "<img" not in tooltip
    assert "&lt;img src=x onerror=alert(1)&gt;" in tooltip


def test_expensive_chain_hangs_off_cache_generation_not_the_poll_tick():
    """Review Important 3: the poller ticks every 2 s during a build. Only the
    badge may depend on that tick -- if ``cached_result`` did, every tick would
    re-read the parquet and re-open the polygons with fiona on the event loop,
    and the map would flicker for the whole rebuild."""
    from shyfem_ui.pages import boxmodel

    # Compare CODE, not prose: these functions' docstrings name the very
    # reactives the assertions are about, so a substring check over the raw
    # source would pass or fail on documentation.
    code = _code_of(boxmodel, "boxmodel_server")

    # status() is the tick-driven calc, and only the badge reads it
    assert "status_tick.get()" in code("status")
    assert "status()" in code("cache_state")
    # the head of the expensive chain reads the generation, never the tick
    cached_body = code("cached_result")
    assert "cache_generation.get()" in cached_body
    assert "status_tick" not in cached_body
    assert "status()" not in cached_body
    # ... and it probes status non-reactively instead
    assert "_status_now()" in cached_body
    # the poller writes both and reads neither (no self-write loop)
    poll_body = code("_poll")
    assert "_bump_status()" in poll_body and "_bump_cache_generation()" in poll_body
    assert "status_tick.get()" not in poll_body and "cache_generation.get()" not in poll_body


class _GateConfig:
    """Config stub whose confine_path refuses writes but allows reads."""

    def __init__(self, *, deny_write: bool):
        self.deny_write = deny_write
        self.calls: list[bool] = []

    def confine_path(self, path, user, *, must_exist=False, for_write=False):
        self.calls.append(for_write)
        if for_write and self.deny_write:
            raise ValueError(f"Path '{path}' is outside allowed directories")
        return path

    def display_path(self, path, user):
        return str(path)


def test_reconcile_is_skipped_without_write_access(monkeypatch, tmp_path):
    """Review Important 4: ``reconcile_tmp_dirs`` renames and deletes inside the
    project, but the confinement the manifest load uses is ``for_write=False``,
    which also admits a shared-project viewer and an analysis-root reader -- and
    this page server is mounted for every session. A viewer must not trigger the
    mutation, and must not be shown an error they cannot act on."""
    from shyfem_ui.pages import boxmodel

    called = []
    monkeypatch.setattr(boxmodel, "reconcile_tmp_dirs", lambda wd, **kw: called.append(wd) or [])

    config = _GateConfig(deny_write=True)
    notice = boxmodel._reconcile_cache_dir(config, {"username": "viewer"}, tmp_path, "proj", 7)

    assert called == [], "reconcile must not run without write access"
    assert notice is None, "a viewer has nothing actionable to be told"
    assert config.calls == [True], "the write confinement must be the one checked"


def test_reconcile_runs_once_with_write_access(monkeypatch, tmp_path):
    from shyfem_ui.pages import boxmodel

    called = []
    monkeypatch.setattr(
        boxmodel,
        "reconcile_tmp_dirs",
        lambda wd, **kw: called.append((wd, kw)) or ["published fix"],
    )

    config = _GateConfig(deny_write=False)
    notice = boxmodel._reconcile_cache_dir(config, {"username": "editor"}, tmp_path, "proj", 7)

    assert len(called) == 1, "reconcile must run exactly once for a writer"
    work_dir, kwargs = called[0]
    assert work_dir == tmp_path
    # Review Important 1: without the registry AND the project id the
    # reconcile decides on progress.json's age alone and can delete the tmp
    # dir of a build running in this very worker.
    assert kwargs["registry"] is boxmodel.REGISTRY
    assert kwargs["project_id"] == 7
    assert notice is None


def test_reconcile_failure_becomes_a_page_notice(monkeypatch, tmp_path):
    """A genuine simultaneous publish race hands the loser an OSError; page load
    must survive it and say so."""
    from shyfem_ui.pages import boxmodel

    def _boom(_wd, **_kw):
        raise FileNotFoundError("lost the publish race")

    monkeypatch.setattr(boxmodel, "reconcile_tmp_dirs", _boom)
    notice = boxmodel._reconcile_cache_dir(_GateConfig(deny_write=False), None, tmp_path, "proj", 7)
    assert notice and "cache directory" in notice


def test_reconcile_helper_returns_manifest_when_write_access_denied(monkeypatch, tmp_path):
    """The write gate must not stop a viewer seeing the page: the read
    confinement the manifest load uses still passes, and the helper returns
    ``None`` (no notice) instead of raising or mutating anything."""
    from shyfem_ui.pages import boxmodel

    monkeypatch.setattr(
        boxmodel,
        "reconcile_tmp_dirs",
        lambda wd, **kw: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    config = _GateConfig(deny_write=True)
    # the read confinement (for_write=False) is what the manifest load uses
    assert config.confine_path(tmp_path, None, must_exist=True, for_write=False) == tmp_path
    assert boxmodel._reconcile_cache_dir(config, None, tmp_path, "proj", 7) is None


def test_live_fallback_is_keyed_to_the_selected_run():
    """Re-review Important: the "keep showing the last good run during a
    rebuild" slot must be keyed, or this plain sequence silently shows the wrong
    data -- run A ready, Build A, switch to ready run B (B is loaded and
    remembered), switch back to A while A is still building: the live branch
    would hand back B's frame while the Run select and the badge both say A."""
    from shyfem_ui.pages import boxmodel

    last: dict = {"good": None}
    run_b = object()
    boxmodel._remember_good(last, 1, "runB", run_b)

    # same project, different run -> must NOT fall back to B
    assert boxmodel._pick_live_fallback(last, 1, "runA") is None
    # same run -> the remembered frame
    assert boxmodel._pick_live_fallback(last, 1, "runB") is run_b
    # same run id in a different project -> also not a match
    assert boxmodel._pick_live_fallback(last, 2, "runB") is None


def test_live_fallback_is_empty_before_anything_loaded():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._pick_live_fallback({}, 1, "runA") is None
    assert boxmodel._pick_live_fallback({"good": None}, 1, "runA") is None


def test_project_change_clears_the_remembered_run():
    """Keying already makes the fallback correct; clearing on a project change is
    so a session that moves on stops holding the old project's DataFrames."""
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    start = src.index("def _forget_cached_run_on_project_change(")
    body = src[start : src.index("\n    @", start)]
    assert 'last["good"] = None' in body and 'last["project"]' in body


def test_layers_effect_wraps_its_upstream_calls():
    """Minor: an exception escaping a ``reactive.effect`` ends the session, so
    ``polygons()``/``box_values()`` must be inside the effect's try, not before
    it."""
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    start = src.index("def _layers(")
    body = src[start : src.index("extra_layers.set(", start)]
    assert body.index("try:") < body.index("polygons()")
    assert body.index("try:") < body.index("box_values()")
