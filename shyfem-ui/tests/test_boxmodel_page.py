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
from datetime import date, timedelta

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
    for ident in (
        "boxmodel-run",
        "boxmodel-build",
        "boxmodel-cache_state",
        "boxmodel-skill_table",
        # PR 2: the Compare tab
        "boxmodel-cmp_controls",
        "boxmodel-cmpmap",
        "boxmodel-cmp_legend",
        "boxmodel-cmp_plot",
        "boxmodel-cmp_skill",
        "boxmodel-cmp_per_year",
        "boxmodel-cmp_download",
        # PR 3: the Setup tab
        "boxmodel-setup_message",
        "boxmodel-setupmap",
        "boxmodel-setup_boundaries",
        "boxmodel-setup_summary",
        "boxmodel-setup_rivers",
        "boxmodel-setup_meteo_controls",
        "boxmodel-setup_meteo",
    ):
        assert ident in html, f"missing input/output id: {ident}"
    # The old "Run comparison" tab IS the skill half of Compare; it was renamed,
    # not duplicated.
    assert "Run comparison" not in html
    assert "run_comparison_table" not in html
    assert ">Compare<" in html
    assert ">Setup<" in html


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
    # (B-06: the read runs in _load_cached_run, off the loop; cached_result
    # hands out what it stored, keyed by _cached_key.)
    cached_body = code("_load_cached_run")
    assert "_cached_key()" in cached_body
    assert "cache_generation.get()" in code("_cached_key")
    for name in ("_load_cached_run", "_cached_key", "cached_result"):
        assert "status_tick" not in code(name), name
        assert "status()" not in code(name).replace("_status_now()", ""), name
    # ... and it probes status non-reactively instead
    assert "_status_now()" in cached_body
    # the poller writes both and reads neither (no self-write loop)
    poll_body = code("_poll")
    assert "_bump_status()" in poll_body and "_bump_cache_generation()" in poll_body
    assert "status_tick.get()" not in poll_body and "cache_generation.get()" not in poll_body
    # PR 2: the Compare chain hangs off all_run_states() (cache_generation),
    # never off the badge tick either.
    for name in (
        "cmp_runs_selected",
        "cmp_days",
        "cmp_days_result",
        "cmp_diff",
        "cmp_skill_frames",
        "_cmp_layers",
    ):
        body = code(name)
        assert "status_tick" not in body, name
        assert "status()" not in body, name
    assert "all_run_states()" in code("cmp_runs_selected")
    # PR 3: the Setup chain hangs off manifest()/cached() (cache_generation),
    # never off the badge tick.
    for name in ("str_setup_result", "rivers_result", "interfaces_calc", "_setup_layers"):
        body = code(name)
        assert "status_tick" not in body, name
        assert "status()" not in body, name
    assert "manifest()" in code("str_setup_result")
    assert "cached()" in code("interfaces_calc")


class _GateConfig:
    """Config stub whose confine_path refuses writes but allows reads."""

    def __init__(self, *, deny_write: bool, command_timeout_seconds: int | None = None):
        self.deny_write = deny_write
        self.calls: list[bool] = []
        # _reconcile_cache_dir derives the reaper's age cap from the build
        # timeout, so the stub has to carry it like the real Config does.
        self.command_timeout_seconds = command_timeout_seconds

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


def test_reconcile_passes_a_cap_derived_from_the_build_timeout(monkeypatch, tmp_path):
    """The reaper's absolute age cap must reach the page load, and must come
    from the timeout that actually bounds a build here.

    With the cap left on its own floor, a deployment whose operator raised
    command_timeout_seconds above it would reap a HEALTHY build's output
    directory hours before the parent would have killed it -- the user loses
    the run. Configured cap plumbing that reaches no call site is decoration,
    so this asserts the value, not the signature.
    """
    from shyfem_ui.pages import boxmodel
    from shyfem_ui.services import boxmodel_cache as bc

    seen: dict = {}
    monkeypatch.setattr(boxmodel, "reconcile_tmp_dirs", lambda wd, **kw: seen.update(kw) or [])

    generous = 8 * 3600
    config = _GateConfig(deny_write=False, command_timeout_seconds=generous)
    boxmodel._reconcile_cache_dir(config, {"username": "editor"}, tmp_path, "proj", 7)
    assert seen["max_tmp_age"] == bc.tmp_age_cap_seconds(generous)
    assert seen["max_tmp_age"] > generous, "the cap must outlast the build timeout"

    # With no timeout configured, the page's own build bound is the one used.
    seen.clear()
    boxmodel._reconcile_cache_dir(
        _GateConfig(deny_write=False), {"username": "editor"}, tmp_path, "proj", 7
    )
    assert seen["max_tmp_age"] == bc.tmp_age_cap_seconds(boxmodel.BUILD_TIMEOUT_SECONDS)


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
    from shyfem_ui.services.boxmodel_cache import get_registry

    assert kwargs["registry"] is get_registry()
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

    # PR 2: the Compare map's layers effect has the same shape.
    start = src.index("def _cmp_layers(")
    body = src[start : src.index("cmp_layers.set(", start)]
    assert body.index("try:") < body.index("polygons()")
    assert body.index("try:") < body.index("cmp_diff()")
    assert "extra_layers.set(" not in body and "legend_bins.set(" not in body.replace(
        "cmp_legend_bins.set(", ""
    )

    # PR 3: the Setup map's layers effect -- same shape, writes setup_layers only.
    start = src.index("def _setup_layers(")
    body = src[start : src.index("setup_layers.set(", start)]
    assert body.index("try:") < body.index("polygons()")
    assert body.index("try:") < body.index("interfaces_calc()")
    assert body.index("try:") < body.index("boundary_points_calc()")
    for other in (
        "extra_layers.set(",
        "legend_bins.set(",
        "cmp_layers.set(",
        "cmp_legend_bins.set(",
    ):
        assert other not in body, other


# --- band amplitude ratios (spec §7, shown beside the skill table) --------


def _level_run(days=130, gain=2.0):
    """A CachedRun whose act_eta is ``gain`` x a multi-band synthetic signal.

    The signal sums periods of ~3, 7, 20 and 100 days so every one of the
    2-4 / 4-10 / 10-30 / 30-400 d bands carries real power (a band whose
    observed power is zero is dropped by ``band_amplitude_ratios``), and the
    model is an exact scalar multiple of the observations so every band ratio
    must come out at ``gain``.
    """
    import numpy as np
    import pandas as pd

    from shyfem_ui.services.boxmodel_cache import CachedRun

    dates = pd.date_range("2009-01-01", periods=days, freq="D")
    t = np.arange(days, dtype=float)
    signal = (
        np.sin(2 * np.pi * t / 3.0)
        + np.sin(2 * np.pi * t / 7.0)
        + np.sin(2 * np.pi * t / 20.0)
        + np.sin(2 * np.pi * t / 100.0)
    )
    rows = [
        {
            "date": d,
            "box": 1,
            "salt": 1.0,
            "temp": 5.0,
            "act_eta": gain * signal[i],
            "cur_speed": 0.0,
            "aver_eta": 0.0,
            "bstress": 0.0,
            "volume": 1.0,
        }
        for i, d in enumerate(dates)
    ]
    obs = pd.DataFrame(
        {
            "date": dates,
            "site": "A",
            "variable": "level",
            "value": signal,
        }
    )
    sites = pd.DataFrame(
        {"site": ["A"], "lat": [0.0], "lon": [0.0], "box": pd.array([1], dtype="Int64")}
    )
    run = CachedRun(
        "a",
        {"period": {"start": str(dates[0]), "end": str(dates[-1])}},
        pd.DataFrame(rows),
        pd.DataFrame(),
        pd.DataFrame(),
        None,
    )
    return run, obs, sites, dates[0].date(), dates[-1].date()


def test_band_ratio_rows_reports_every_band_for_a_level_target():
    from shyfem_ui.pages import boxmodel

    run, obs, sites, start, end = _level_run(gain=2.0)
    rows = boxmodel._band_ratio_rows(run, obs, sites, start, end)

    assert [r["site"] for r in rows] == ["A"]
    ratios = rows[0]["ratios"]
    assert ratios is not None
    assert set(ratios) == set(boxmodel.BAND_COLUMNS)
    for column, value in ratios.items():
        assert value == pytest.approx(2.0, rel=1e-6), column


def test_band_ratio_rows_returns_none_below_the_gap_free_minimum():
    """120 gap-free common days is a much stronger requirement than the skill
    table's 30 matched days, so a run can have a skill row and no ratios."""
    from shyfem_ui.pages import boxmodel

    run, obs, sites, start, end = _level_run(days=119)
    rows = boxmodel._band_ratio_rows(run, obs, sites, start, end)
    assert rows and rows[0]["ratios"] is None


def test_band_ratio_rows_skips_sites_without_a_box_or_level_observations():
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    run, obs, sites, start, end = _level_run()
    unmapped = pd.concat(
        [sites, pd.DataFrame({"site": ["B"], "lat": [1.0], "lon": [1.0], "box": [pd.NA]})],
        ignore_index=True,
    )
    unmapped["box"] = unmapped["box"].astype("Int64")
    assert [r["site"] for r in boxmodel._band_ratio_rows(run, obs, unmapped, start, end)] == ["A"]

    # a mapped site with only salinity observations is not a level target
    salt_only = obs.assign(variable="salinity")
    assert boxmodel._band_ratio_rows(run, salt_only, sites, start, end) == []


def test_band_ratios_is_wired_to_the_cache_not_the_poll_tick():
    """Spec §7 says the ratios are shown beside the skill table; the render
    must hang off ``cached()`` (i.e. ``cache_generation``) like
    ``skill_table`` does, never off the 2 s badge tick."""
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    body = code("band_ratios")
    assert "_band_ratio_rows(" in body
    assert "cached()" in body
    assert "status_tick" not in body and "status()" not in body

    html = str(boxmodel.boxmodel_ui("boxmodel"))
    assert "boxmodel-band_ratios" in html


# --- no box outlines at all (Review Important 6) --------------------------


class _Manifest:
    def __init__(self, polygons=None):
        self.polygons = polygons


class _Cached:
    def __init__(self, meta):
        self.meta = meta


def test_no_polygons_message_when_neither_source_exists():
    from shyfem_ui.pages import boxmodel

    message = boxmodel._no_polygons_message(_Manifest(), _Cached({"element_box": []}))
    assert message == boxmodel.NO_POLYGONS_MESSAGE
    assert "boxes.polygons" in message and "boxes_geom.txt" in message
    # element_box absent entirely (an older meta.json) reads the same way
    assert boxmodel._no_polygons_message(_Manifest(), _Cached({})) == boxmodel.NO_POLYGONS_MESSAGE


def test_no_polygons_message_is_silent_when_outlines_are_available():
    from shyfem_ui.pages import boxmodel

    # manifest polygons present
    assert boxmodel._no_polygons_message(_Manifest("boxes.gpkg"), _Cached({})) is None
    # or the run carries an element->box map to dissolve from
    assert boxmodel._no_polygons_message(_Manifest(), _Cached({"element_box": [[1, 1]]})) is None
    # no cache yet is "not known yet", not "no outlines"
    assert boxmodel._no_polygons_message(_Manifest(), None) is None
    assert boxmodel._no_polygons_message(None, _Cached({})) is None


def test_polygons_result_returns_the_no_outlines_message():
    from shyfem_ui.pages import boxmodel

    body = _code_of(boxmodel, "boxmodel_server")("polygons_result")
    assert "_no_polygons_message(manifest_obj, cached_run)" in body


def test_polygons_result_hands_over_the_grid_it_already_parsed():
    """Item 3: ``polygons_result`` holds the parsed ``GrdFile`` (it needs it for
    the EPSG decision), so it must hand that object to
    ``dissolve_boxes_from_grid`` rather than the path, so the outlines and the
    map always describe the same grid (the service-level test pins the
    no-re-parse behaviour). With no parsed grid, a grid that failed to parse,
    the manifest path stays the fallback, so the page still works."""
    from shyfem_ui.pages import boxmodel

    body = _code_of(boxmodel, "boxmodel_server")("polygons_result")
    assert "dissolve_boxes_from_grid(grd if grd is not None else manifest_obj.grd" in body


# --- download file name (Minor 9) ----------------------------------------


def test_series_filename_uses_the_validated_variable_and_box():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._series_filename({"box": 3, "variable": "salt"}) == "box3_salt.csv"
    assert boxmodel._series_filename(None) == "box_series.csv"
    # nothing outside [A-Za-z0-9_-] survives, whatever reached the dict
    name = boxmodel._series_filename({"box": '1"; rm -rf /', "variable": "../../etc/passwd"})
    assert name == "box1rm-rf_etcpasswd.csv"
    assert all(c.isalnum() or c in "_-." for c in name)


def test_download_name_is_built_from_series_not_the_raw_inputs():
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    assert "filename=lambda: _series_filename(series())" in src
    assert 'f"box{input.box()' not in src, "the raw client input must not reach the file name"


# --- PR 2: Compare tab ----------------------------------------------------


def test_page_uses_the_shared_registry_accessor():
    """PR 2 follow-up: the registry moved into the cache service. The page must
    not construct its own (two registries = two per-worker semaphores)."""
    from shyfem_ui.pages import boxmodel

    src = inspect.getsource(boxmodel)
    assert "REGISTRY = BuildRegistry()" not in src
    assert not hasattr(boxmodel, "REGISTRY")
    assert "get_registry()" in src
    server = get_server_source(boxmodel, "boxmodel_server")
    assert "REGISTRY" not in server.replace("get_registry", "")


def test_cmp_controls_read_current_choices_under_isolate_and_never_update_from_an_effect():
    """The Compare selectors are rendered by ``render.ui`` (so they re-render
    whenever the ready-run set changes). Pushing ``update_selectize`` from an
    effect as well would be a second writer of the same input; and reading the
    current choice reactively inside the render would re-render the selectize
    on every user change -- the self-write loop. So: the renders read the
    current inputs under ``reactive.isolate()``, and nothing in the server
    updates ``cmp_runs``/``cmp_b`` from an effect."""
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    runs_body = code("cmp_controls")
    assert "reactive.isolate()" in runs_body
    assert "input.cmp_runs()" in runs_body
    assert "input_selectize('cmp_runs'" in runs_body or 'input_selectize("cmp_runs"' in runs_body
    assert "'maxItems': 4" in runs_body or '"maxItems": 4' in runs_body
    b_body = code("cmp_b_control")
    assert "reactive.isolate()" in b_body
    assert "input.cmp_b()" in b_body
    assert "input_select('cmp_b'" in b_body or 'input_select("cmp_b"' in b_body
    # the runs render must not depend on its own output reactively
    assert "all_run_states()" in runs_body

    src = get_server_source(boxmodel, "boxmodel_server")
    assert "update_selectize(" not in src
    assert 'update_select("cmp_' not in src and "update_select('cmp_" not in src


def test_compare_filename_is_built_from_validated_inputs():
    from shyfem_ui.pages import boxmodel

    assert boxmodel._compare_filename("salt", "run_a", "run-b") == "compare_salt_run_a_vs_run-b.csv"
    assert boxmodel._compare_filename(None, None, None) == "compare.csv"
    name = boxmodel._compare_filename("../etc", 'a"; rm', "b/c")
    assert name == "compare_etc_arm_vs_bc.csv"
    assert all(c.isalnum() or c in "_-." for c in name)

    src = get_server_source(boxmodel, "boxmodel_server")
    assert "_compare_filename(" in src
    assert 'f"compare_{input.' not in src, "the raw client input must not reach the file name"


def test_validate_compare_runs_orders_a_first_and_picks_b():
    from shyfem_ui.pages import boxmodel

    states = {"a": object(), "b": object(), "c": object(), "d": object(), "e": object()}
    # selection order is A first; B = input if in the set else the second run
    assert boxmodel._validate_compare_runs(("b", "a"), "a", states) == (["b", "a"], "a")
    assert boxmodel._validate_compare_runs(("b", "a"), None, states) == (["b", "a"], "a")
    assert boxmodel._validate_compare_runs(("b", "a", "c"), "c", states) == (["b", "a", "c"], "c")
    # B may not be A
    assert boxmodel._validate_compare_runs(("b", "a"), "b", states) == (["b", "a"], "a")
    # unknown ids (a run whose cache went away) are dropped, not fatal
    assert boxmodel._validate_compare_runs(("a", "zzz", "b"), "zzz", states) == (["a", "b"], "b")
    # fewer than two, more than four, nothing at all -> None
    assert boxmodel._validate_compare_runs(("a",), None, states) is None
    assert boxmodel._validate_compare_runs(("a", "b", "c", "d", "e"), None, states) is None
    assert boxmodel._validate_compare_runs(None, None, states) is None
    assert boxmodel._validate_compare_runs(("a", "b"), None, {}) is None
    # a duplicate id (a re-sent selection) does not count twice
    assert boxmodel._validate_compare_runs(("a", "a", "b"), None, states) == (["a", "b"], "b")


def test_compare_bounds_clamp_the_header_period_like_the_time_series_tab():
    """``input_date_range`` reads (today, today) until the header run's cache
    fills it; that run need not be one of the compared runs (or ready at all).
    So the header period is clamped to the compared runs' span and, when the
    clamp leaves nothing, the full span is used -- exactly what ``_period()``
    does for the Time-series tab."""
    import datetime as dt

    import pandas as pd

    from shyfem_ui.pages import boxmodel
    from shyfem_ui.services.boxmodel_cache import CachedRun

    def run(run_id, start, days):
        dates = pd.date_range(start, periods=days, freq="D")
        return CachedRun(
            run_id,
            {},
            pd.DataFrame({"date": dates, "box": 1, "salt": 1.0}),
            pd.DataFrame(),
            pd.DataFrame(),
            None,
        )

    states = {"a": run("a", "2009-01-01", 10), "b": run("b", "2009-01-05", 40)}
    span = (pd.Timestamp("2009-01-01"), pd.Timestamp("2009-02-13"))
    assert boxmodel._compare_bounds(states, None) == span
    assert boxmodel._compare_bounds(states, (None, dt.date(2009, 1, 8))) == span
    assert boxmodel._compare_bounds(states, (dt.date(2009, 1, 3), dt.date(2009, 1, 8))) == (
        pd.Timestamp("2009-01-03"),
        pd.Timestamp("2009-01-08"),
    )
    # partly outside -> clamped
    assert boxmodel._compare_bounds(states, (dt.date(2008, 12, 1), dt.date(2009, 1, 8))) == (
        pd.Timestamp("2009-01-01"),
        pd.Timestamp("2009-01-08"),
    )
    # entirely outside (today/today before the header effect lands) -> full span
    assert boxmodel._compare_bounds(states, (dt.date(2026, 9, 26), dt.date(2026, 9, 26))) == span
    assert boxmodel._compare_bounds({}, None) is None


def test_compare_day_set_turns_a_broken_cache_into_a_page_message():
    """Item 5: ``state_daily`` comes off disk and nothing validates it beyond
    the ``date`` normalisation in ``load_cache_state``, so a foreign or
    hand-edited cache can reach the Compare day set without a usable ``date``
    column. That must become a page message, the way ``cached_result`` does it,
    not an exception raised inside a reactive calc."""
    import pandas as pd

    from shyfem_ui.pages import boxmodel
    from shyfem_ui.services.boxmodel_cache import CachedRun

    def run(run_id, frame):
        return CachedRun(run_id, {}, frame, pd.DataFrame(), pd.DataFrame(), None)

    good = pd.DataFrame({"date": pd.date_range("2009-01-01", periods=5, freq="D"), "box": 1})
    states = {"a": run("a", good), "b": run("b", good)}
    days, error = boxmodel._compare_day_set(states, None, str)
    assert error is None and len(days) == 5

    # no 'date' column at all
    broken = {"a": run("a", good), "b": run("b", pd.DataFrame({"box": [1, 2]}))}
    days, error = boxmodel._compare_day_set(broken, None, str)
    assert len(days) == 0
    assert error and error.startswith("Compare:") and "date" in error

    # a 'date' column pandas cannot compare (Minor: a hand-written parquet)
    odd = {"a": run("a", good), "b": run("b", pd.DataFrame({"date": [object()], "box": [1]}))}
    days, error = boxmodel._compare_day_set(odd, None, str)
    assert len(days) == 0 and error and error.startswith("Compare:")

    # no runs at all is not an error, just an empty day set
    days, error = boxmodel._compare_day_set({}, None, str)
    assert len(days) == 0 and error is None
    assert len(boxmodel._empty_day_set()) == 0


def test_compare_chain_guards_every_off_disk_frame_read():
    """The guard is wired where the reads happen: the day set goes through the
    guarded ``_compare_day_set``, ``_cmp_message`` says what went wrong, and
    ``all_run_states`` validates the ``box`` column the rest of the tab assumes
    (``load_cache_state`` normalises ``date`` but checks nothing else) and
    catches the ``TypeError`` ``pd.to_datetime`` raises on an odd column."""
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    assert "_compare_day_set(" in code("cmp_days_result")
    assert "cmp_days_result()" in code("cmp_days")
    message = code("_cmp_message")
    assert "cmp_days_result()" in message
    assert message.index("cmp_days_result()") < message.index("CMP_NO_COMMON_DAYS_MESSAGE")
    assert "_read_run_states" in code("_load_run_states")
    assert "_load_compare_state(" in inspect.getsource(boxmodel._read_run_states)
    assert "run_states_store.get()" in code("all_run_states_result")
    assert "all_run_states_result()" in code("all_run_states")
    # A run dropped for an unreadable cache must not be reported as "pick two
    # runs", which blames the user for it.
    assert "run_state_problems()" in message
    assert message.index("run_state_problems()") < message.index("CMP_NEED_TWO_MESSAGE")
    # The box-column check and the TypeError clause themselves are pinned
    # behaviourally, not by source text: see the _load_compare_state tests.


def test_setup_meteo_frame_read_is_guarded():
    """Item 5 (Setup): ``meteo_daily`` comes off disk too -- a cache whose
    frame has data columns but no ``box``/``date`` must leave the plot with a
    message instead of raising out of the render."""
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    start = src.index("frame = cached_run.meteo_daily")
    slice_ = src[start : src.index("if not len(rows)", start)]
    assert "try:" in slice_, "the meteo_daily read is not inside a try"
    assert slice_.index("try:") < slice_.index('frame["box"]')
    assert "_empty(" in slice_, "a failed read must become the plot's message"
    # The VALUES are read in there too: _meteo_variables offers every non-key
    # column with no dtype filter, so .astype(float) on a string column would
    # otherwise raise straight out of the render.
    assert slice_.index("try:") < slice_.index("astype(float)")


def test_compare_int_cell_renders_side_by_side_n():
    """``side_by_side`` pivots ``n`` into a float column (NaN for a missing
    cell); the table shows it as an integer or an empty cell."""
    from shyfem_ui.pages import boxmodel

    assert boxmodel._int_cell(40.0) == "40"
    assert boxmodel._int_cell(float("nan")) == ""
    assert boxmodel._int_cell(None) == ""


def test_compare_messages_are_muted_paragraphs_and_the_map_is_never_bare():
    """Every Compare state message is a ``ui.tags.p(..., class_="text-muted")``,
    and the legend beside the map shows the state message when there are no
    layers, so the map is never a bare mesh with nothing said."""
    from shyfem_ui.pages import boxmodel

    for text in (
        boxmodel.CMP_NEED_TWO_MESSAGE,
        boxmodel.CMP_SELECT_RUNS_MESSAGE,
        boxmodel.CMP_NO_COMMON_DAYS_MESSAGE,
        boxmodel.CMP_PER_YEAR_EMPTY_MESSAGE,
        boxmodel.CMP_NO_OBSERVATIONS_MESSAGE,
    ):
        assert isinstance(text, str) and text
    assert "60 matched days" in boxmodel.CMP_PER_YEAR_EMPTY_MESSAGE

    code = _code_of(boxmodel, "boxmodel_server")
    # "build a cache" and "pick more runs" are different remedies
    message = code("_cmp_message")
    assert "CMP_NEED_TWO_MESSAGE" in message and "CMP_SELECT_RUNS_MESSAGE" in message
    assert message.index("CMP_NEED_TWO_MESSAGE") < message.index("CMP_SELECT_RUNS_MESSAGE")
    legend = code("cmp_legend")
    assert "cmp_legend_bins.get()" in legend
    assert "_cmp_message()" in legend
    assert "grid_map_server('cmpmap'" in get_server_source(boxmodel, "boxmodel_server").replace(
        '"', "'"
    )
    # the shared day set is computed once and handed to map, overlay and tables
    assert "cmp_days()" in code("cmp_diff")
    assert "cmp_days()" in code("cmp_overlay")
    assert "cmp_days()" in code("cmp_skill_frames")
    assert "common_days(" in inspect.getsource(boxmodel._compare_day_set)
    assert "_compare_day_set(" in code("cmp_days_result")


# --- PR 3: Setup tab ------------------------------------------------------


def test_rivers_are_read_only_through_the_resolver():
    """Global Constraint (PR 3): ``boundn`` is run-relative user text out of the
    STR. The page never opens it -- it goes through ``resolve_forcing_file``
    (basename under ``forcing_dir``, no symlinks, re-confined) and then
    ``read_forcing_series`` on the path the resolver returned."""
    from shyfem_ui.pages import boxmodel

    body = _code_of(boxmodel, "boxmodel_server")("rivers_result")
    assert "resolve_forcing_file(" in body
    assert "read_forcing_series(" in body
    assert "open(" not in body
    assert "read_text(" not in body
    assert "read_bytes(" not in body
    assert "pd.read_csv(" not in body and "read_csv(" not in body
    # the discharge filter and the error types the read can raise
    assert "kind(" in body
    assert "StrSetupError" in body


def test_setup_renders_never_reference_resolved_paths():
    """Spec §4 / Global Constraint: resolved paths are never rendered -- the
    table shows ``boundn`` as written and a resolver note, never
    ``manifest.forcing_dir`` or ``manifest.str_path``."""
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    for name in (
        "setup_message",
        "setup_summary",
        "setup_boundaries",
        "setup_rivers",
        "setup_meteo_controls",
        "setup_meteo",
    ):
        body = code(name)
        assert "forcing_dir" not in body, name
        assert "str_path" not in body, name
        assert "ui.HTML(" not in body, name
    # the file column shows boundn as written, sanitised, next to the note
    boundaries_body = code("setup_boundaries")
    assert "rivers_result()" in boundaries_body
    assert "_boundary_rows(" in boundaries_body
    # the summary passes every value through _text and shows orphans as ONE row
    summary_body = code("setup_summary")
    assert "_text(" in summary_body
    assert "SETUP_ORPHANS_LABEL" in summary_body


def test_setup_pick_handlers_are_registered_once_per_boundary():
    """One action link per boundary row selects it for the map; handlers are
    registered from the render body behind a session-scoped set, the project's
    dedup idiom (tests/test_handler_dedup.py), so a re-render never stacks
    listeners."""
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server")
    assert "_setup_pick_registered" in src
    code = _code_of(boxmodel, "boxmodel_server")
    reg = code("_register_setup_pick")
    assert "if number in _setup_pick_registered:" in reg
    assert "_setup_pick_registered.add(number)" in reg
    assert reg.index("if number in _setup_pick_registered:") < reg.index(
        "_setup_pick_registered.add(number)"
    )
    assert "setup_selected_boundary.set(" in reg
    assert "_register_setup_pick(" in code("setup_boundaries")
    table = code("setup_boundaries").replace('"', "'")
    assert "input_action_link(f'setup_pick_{" in table


def test_setup_meteo_controls_read_their_own_value_under_isolate():
    """Same shape as ``cmp_controls``: the select is rendered (so the cache's
    column set is the only thing that re-renders it) and its current value is
    read under ``reactive.isolate()`` -- reading it reactively would re-render
    the dropdown on every pick."""
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    body = code("setup_meteo_controls")
    assert "reactive.isolate()" in body
    assert "input.setup_meteo_var()" in body
    assert "input_select('setup_meteo_var'" in body
    assert "_meteo_variables(" in body
    assert "cached()" in body
    src = get_server_source(boxmodel, "boxmodel_server")
    assert (
        'update_select("setup_meteo_var"' not in src
        and "update_select('setup_meteo_var'" not in src
    )
    plot = code("setup_meteo")
    assert "'setup_meteo_var' in input" in plot
    assert "_period()" in plot
    assert "input.box()" in plot


def test_setup_map_is_mounted_with_its_own_layers():
    from shyfem_ui.pages import boxmodel

    src = get_server_source(boxmodel, "boxmodel_server").replace('"', "'")
    assert "grid_map_server('setupmap', grd_file, extra_layers=setup_layers" in src
    assert "on_box_click=_on_box" in src.split("grid_map_server('setupmap'")[1][:200]
    code = _code_of(boxmodel, "boxmodel_server")
    body = code("_setup_layers")
    assert "build_setup_layers(" in body
    assert "build_box_layers(" in body
    assert "setup_selected_boundary.get()" in body
    # boundary node positions come from the grid the polygons path uses
    points = code("boundary_points_calc")
    assert "node_positions(" in points
    assert "grd_file.get()" in points


def test_meteo_variables_lists_the_meteo_columns_with_tair_first():
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2009-01-01"]),
            "box": [1],
            "srad": [1.0],
            "tair": [2.0],
            "rhum": [3.0],
            "wspeed": [4.0],
        }
    )
    choices = boxmodel._meteo_variables(frame)
    assert list(choices) == ["tair", "srad", "rhum", "wspeed"]
    assert "date" not in choices and "box" not in choices
    assert boxmodel._meteo_variables(pd.DataFrame({"date": [], "box": []})) == {}
    assert boxmodel._meteo_variables(None) == {}
    # no tair: file order, nothing invented
    assert list(boxmodel._meteo_variables(frame.drop(columns=["tair"]))) == [
        "srad",
        "rhum",
        "wspeed",
    ]


def test_boundary_rows_show_boundn_as_written_and_the_resolver_note():
    from shyfem_ui.pages import boxmodel
    from shyfem_ui.services.boxmodel_setup import Boundary

    bounds = [
        Boundary(
            1, "Baltic sea", 1, 1.0, [1, 2, 3, 4], "fem_forcing/sea_level.fem", {"saltn": "s.fem"}
        ),
        Boundary(2, "Fixture river", 2, 0.25, [5, 6], "fem_forcing/river.txt", {}),
        Boundary(3, "", None, 1.0, [], None, {}),
    ]
    notes = {1: (None, "not read (.fem)"), 2: (object(), None)}
    rows = boxmodel._boundary_rows(bounds, notes)
    assert [r["number"] for r in rows] == [1, 2, 3]
    assert rows[0]["boundn"] == "fem_forcing/sea_level.fem"
    assert rows[0]["note"] == "not read (.fem)"
    assert rows[0]["kind"] == "level" and rows[0]["ibtyp"] == "1"
    assert rows[0]["nodes"] == 4
    assert rows[0]["other_files"] == "saltn: s.fem"
    assert rows[1]["zfact"] == "0.25" and rows[0]["zfact"] == "1"
    assert rows[1]["note"] == "" and rows[1]["kind"] == "discharge"
    # a boundary the resolver never saw (no boundn) has an empty file cell
    assert rows[2]["boundn"] == "" and rows[2]["note"] == "" and rows[2]["ibtyp"] == ""
    assert rows[2]["kind"] == "unknown"
    # no row carries anything path-like from the resolver
    assert all("path" not in r for r in rows)


def test_restrict_series_is_inclusive_through_the_end_day():
    """A date-only ``itend`` ('2009-01-11') stamps midnight; the forcing rows
    sit at 06:00. The restriction treats a date-only end as the whole end day,
    and a timed end ('::06:00') as exact."""
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    idx = pd.to_datetime(
        ["2008-12-31 06:00", "2009-01-01 06:00", "2009-01-11 06:00", "2009-01-12 06:00"]
    )
    series = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)
    out = boxmodel._restrict_series(
        series, (pd.Timestamp("2009-01-01"), pd.Timestamp("2009-01-11"))
    )
    assert out.tolist() == [2.0, 3.0]
    exact = boxmodel._restrict_series(
        series, (pd.Timestamp("2009-01-01"), pd.Timestamp("2009-01-11 03:00"))
    )
    assert exact.tolist() == [2.0]
    assert boxmodel._restrict_series(series, None) is series
    # date objects (the cache period) are accepted too
    import datetime as dt

    out2 = boxmodel._restrict_series(series, (dt.date(2009, 1, 1), dt.date(2009, 1, 11)))
    assert out2.tolist() == [2.0, 3.0]


def test_setup_messages_are_constants():
    from shyfem_ui.pages import boxmodel

    for text in (
        boxmodel.SETUP_NO_STR_MESSAGE,
        boxmodel.SETUP_NEEDS_CACHE_MESSAGE,
        boxmodel.SETUP_ORPHANS_LABEL,
        boxmodel.SETUP_NO_RIVERS_MESSAGE,
        boxmodel.SETUP_NO_METEO_MESSAGE,
    ):
        assert isinstance(text, str) and text
    assert "ignored by SHYFEM" in boxmodel.SETUP_ORPHANS_LABEL
    assert "ready cache" in boxmodel.SETUP_NEEDS_CACHE_MESSAGE
    assert boxmodel._missing_nodes_message([]) is None
    assert boxmodel._missing_nodes_message([9, 3, 9]) == "STR boundary nodes not in the grid: 3, 9"


def _state_daily_run(frame):
    """A CachedRun carrying just this state_daily frame."""
    from shyfem_ui.services.boxmodel_cache import CachedRun

    return CachedRun(
        run_id="run9316", meta={}, state_daily=frame, flux_daily=None, meteo_daily=None
    )


def test_load_compare_state_rejects_a_frame_with_no_box_column(monkeypatch, tmp_path):
    """The whole Compare chain indexes by box. load_cache_state normalises the
    'date' column and validates nothing else, so a foreign or hand-edited
    cache used to reach _cmp_box/period_mean_diff without a 'box' column."""
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    frame = pd.DataFrame({"date": pd.to_datetime(["2009-01-01"]), "temp": [1.0]})
    monkeypatch.setattr(boxmodel, "load_cache_state", lambda d, r: _state_daily_run(frame))

    state, problem = boxmodel._load_compare_state(tmp_path, "run9316", str)
    assert state is None
    assert problem is not None
    assert problem.startswith("run9316: ")
    assert "box" in problem


def test_load_compare_state_reports_a_typeerror_from_the_date_column(monkeypatch, tmp_path):
    """pd.to_datetime raises TypeError, not ValueError, on a column of the
    wrong kind altogether -- the clause the old tuple was missing."""
    from shyfem_ui.pages import boxmodel

    def boom(cache_dir, run_id):
        raise TypeError("cannot convert object to datetime")

    monkeypatch.setattr(boxmodel, "load_cache_state", boom)
    state, problem = boxmodel._load_compare_state(tmp_path, "run9316", str)
    assert state is None
    assert "datetime" in problem


def test_load_compare_state_returns_a_readable_run_unchanged(monkeypatch, tmp_path):
    """The control: a well-formed cache passes through with no message."""
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    frame = pd.DataFrame({"date": pd.to_datetime(["2009-01-01"]), "box": [1], "temp": [1.0]})
    run = _state_daily_run(frame)
    monkeypatch.setattr(boxmodel, "load_cache_state", lambda d, r: run)

    state, problem = boxmodel._load_compare_state(tmp_path, "run9316", str)
    assert state is run
    assert problem is None


# --- hourly detail (spec sec8) -----------------------------------------------


def test_hourly_is_unusable_without_an_hourly_cache():
    """A daily-only cache is the normal case: the page falls back to daily
    rather than showing an error or an hourly-looking control with no data."""
    from shyfem_ui.pages import boxmodel

    period = (date(2009, 1, 1), date(2009, 1, 5))
    assert boxmodel._hourly_usable({"hourly": False, "step_seconds": 3600}, period) is False
    assert boxmodel._hourly_usable({}, period) is False


def test_hourly_is_usable_only_inside_the_window_cap():
    """Spec sec246: hourly when the cache has it AND the window is short.

    Absolute dates and the literal 31, deliberately: deriving the edge from
    HOURLY_WINDOW_DAYS made this pass with the cap set to 3650.
    """
    from shyfem_ui.pages import boxmodel

    assert boxmodel.HOURLY_WINDOW_DAYS == 31
    meta = {"hourly": True, "step_seconds": 3600, "boxes": [{}] * 29}
    assert boxmodel._hourly_usable(meta, (date(2009, 1, 1), date(2009, 1, 31))) is True
    assert boxmodel._hourly_usable(meta, (date(2009, 1, 1), date(2009, 2, 1))) is False
    assert boxmodel._hourly_usable(meta, (date(2009, 1, 1), date(2009, 1, 1))) is True
    assert boxmodel._hourly_usable(meta, None) is False
    assert boxmodel._hourly_usable(meta, (None, None)) is False


def test_a_fine_output_step_is_refused_even_in_a_short_window():
    """Days do not bound the work: rows are days x boxes x 86400/step. A run
    with idtbox = 60 puts 1.29M rows and 44,640 slider ticks inside a 31-day
    window, which is exactly what the day cap alone was supposed to prevent."""
    from shyfem_ui.pages import boxmodel

    month = (date(2009, 1, 1), date(2009, 1, 31))
    coarse = {"hourly": True, "step_seconds": 3600, "boxes": [{}] * 29}
    fine = {"hourly": True, "step_seconds": 60, "boxes": [{}] * 29}
    assert boxmodel._hourly_usable(coarse, month) is True
    assert boxmodel._hourly_usable(fine, month) is False
    # ...but a short enough window of the same fine run is fine again.
    assert boxmodel._hourly_usable(fine, (date(2009, 1, 1), date(2009, 1, 5))) is True


def _hourly_frame():
    """Two boxes, four stamps an hour apart."""
    import pandas as pd

    stamps = pd.to_datetime(
        ["2009-01-01 00:00", "2009-01-01 01:00", "2009-01-01 02:00", "2009-01-01 03:00"]
    )
    rows = []
    for i, stamp in enumerate(stamps):
        for box in (1, 2):
            rows.append({"stamp": stamp, "box": box, "salt": 10.0 + i + box, "temp": 5.0})
    # Deliberately out of order: a parquet window is not promised sorted, and a
    # pre-sorted fixture would let a dropped .sort_index() pass.
    return pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)


def test_the_map_snaps_to_a_stamp_that_exists():
    """The slider value can land between records after a period change, and an
    exact match would select nothing and blank the map."""
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    frame = _hourly_frame()
    assert boxmodel._snap_to_stamp(frame, pd.Timestamp("2009-01-01 01:29")) == pd.Timestamp(
        "2009-01-01 01:00"
    )
    assert boxmodel._snap_to_stamp(frame, pd.Timestamp("2009-01-01 01:31")) == pd.Timestamp(
        "2009-01-01 02:00"
    )
    # Outside the frame entirely: the nearest end, not an error.
    assert boxmodel._snap_to_stamp(frame, pd.Timestamp("2008-06-01")) == pd.Timestamp(
        "2009-01-01 00:00"
    )


def test_the_map_values_come_from_the_snapped_stamp():
    import pandas as pd

    from shyfem_ui.pages import boxmodel

    values, label = boxmodel._hourly_box_values(
        _hourly_frame(), pd.Timestamp("2009-01-01 02:10"), "salt"
    )
    assert values == {1: 13.0, 2: 14.0}, "one row per box at 02:00"
    assert "02:00" in label and "Salinity" in label


def test_the_hourly_series_is_one_box_in_time_order():
    from shyfem_ui.pages import boxmodel

    series = boxmodel._hourly_series(_hourly_frame(), 2, "salt")
    assert list(series) == [12.0, 13.0, 14.0, 15.0]
    assert series.index.is_monotonic_increasing
    assert len(series) == 4, "the other box must not leak in"


def test_the_slider_step_comes_from_the_run_not_from_the_name():
    """ "Hourly" is the file's name, not a promise: the frame holds the model's
    output records at meta['step_seconds']. A hardcoded hour would land between
    stamps on any run with a different step and select nothing."""
    from shyfem_ui.pages import boxmodel

    assert boxmodel._hourly_step({"step_seconds": 3600}) == timedelta(hours=1)
    assert boxmodel._hourly_step({"step_seconds": 21600}) == timedelta(hours=6)
    assert boxmodel._hourly_step({}) is None
    assert boxmodel._hourly_step({"step_seconds": 0}) is None


def test_the_build_request_carries_the_hourly_checkbox():
    """The knob has to reach the decision: start_build's hourly argument is what
    puts --hourly on the child's command line."""
    from shyfem_ui.pages import boxmodel

    body = _code_of(boxmodel, "boxmodel_server")("_build")
    assert "hourly=" in body, "the build call must pass the hourly flag"
    assert "input.hourly()" in body or "_hourly_requested()" in body


def test_the_map_and_the_series_share_one_hourly_window():
    """One rule, one place: if the map and the series decided separately they
    could describe different data under the same period."""
    from shyfem_ui.pages import boxmodel

    code = _code_of(boxmodel, "boxmodel_server")
    assert "hourly_window()" in code("box_values")
    assert "hourly_window()" in code("series")
    assert "hourly_window()" in code("day_slider")
    assert "_read_hourly_window_checked" in code("_load_hourly_window")
    assert "read_hourly_window(" in inspect.getsource(boxmodel._read_hourly_window_checked)
    assert "hourly_store.get()" in code("hourly_window_result")
    # A cache that HAS the file and cannot be read is a broken cache, not a
    # daily one: it must reach the page's message block, not vanish.
    assert "hourly_window_result()[1]" in code("manifest_error")
    # The daily min/max band describes what a daily mean hides, so it has no
    # meaning over raw records: the hourly branch must not draw one.
    body = code("series")
    assert "low = high = None" in body
