"""Playwright tests for the Visualize "SHYFEM results" map (V-01).

Headless chromium on some machines has no WebGL: MapLibre then fails to
initialise, ``window.__deckgl_instances[...]`` is never created, and the
layer assertions (``lastLayers``) cannot run. Those assertions are skipped
when WebGL is missing; everything driven by the server (time label, Play
button, notifications) is still checked.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests._ugrid_fixture import write_ugrid

MAP_ID = "visualize-results_map-deckgl_map"
LABEL = "#visualize-results_map-time_label"
PLAY = "#visualize-results_map-play"
SAMPLES = Path(os.environ.get("SHYFEM_SAMPLES_DIR", "/home/razinka/shyfem/testcases/examples"))
_T = 15000


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _project(work: Path, name: str) -> Path:
    d = work / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _open_project(page, proj: Path) -> None:
    result = page.evaluate(
        """(wd) => {
            if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: wd, description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""",
        str(proj),
    )
    if result == "no-hook":
        pytest.skip("test_app.py does not expose __test_set_active_project")
    page.locator(".sf-nav-item[data-nav='Visualize']").click(force=True)
    page.wait_for_timeout(500)


def _set_select(page, input_id: str, value: str) -> None:
    """Set a select (selectize or plain) and let Shiny see the change."""
    page.wait_for_function(
        """([id, v]) => {
            const el = document.getElementById(id);
            return !!el && Array.from(el.options || []).some(o => o.value === v)
                || !!(el && el.selectize && el.selectize.options[v]);
        }""",
        arg=[input_id, value],
        timeout=_T,
    )
    page.evaluate(
        """([id, v]) => {
            const el = document.getElementById(id);
            if (el.selectize) { el.selectize.setValue(v); return; }
            el.value = v;
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }""",
        [input_id, value],
    )


def _choose_results(page) -> None:
    _set_select(page, "visualize-data_type", "netcdf")


def _load(page, rel: str) -> None:
    _set_select(page, "visualize-project_file", rel)
    page.wait_for_timeout(300)
    page.locator("#visualize-load_data_btn").click()


def _label(page) -> str:
    return page.locator(LABEL).inner_text().strip()


def _record(text: str) -> int:
    return int(text.split("record ")[1].split(" /")[0])


def _has_webgl(page) -> bool:
    return bool(
        page.evaluate(
            """(id) => !!document.createElement('canvas').getContext('webgl2')
                && !!(window.__deckgl_instances && window.__deckgl_instances[id])""",
            MAP_ID,
        )
    )


def _layer(page, layer_id: str):
    """The layer's props as last pushed to the map (``lastLayers``), or None."""
    return page.evaluate(
        """([mid, lid]) => {
            const inst = window.__deckgl_instances && window.__deckgl_instances[mid];
            if (!inst || !inst.lastLayers) return null;
            const l = inst.lastLayers.find(x => x.id === lid);
            if (!l) return null;
            const val = (p) => p == null ? null
                : JSON.stringify(p.value !== undefined ? p.value : p);
            return {
                colors: val(l._meshColors),
                positions: val(l._meshPositions),
                n_data: Array.isArray(l.data) ? l.data.length : null,
                visible: l.visible,
            };
        }""",
        [MAP_ID, layer_id],
    )


def _wait_layer(page, layer_id: str, pred: str = "true"):
    page.wait_for_function(
        f"""([mid, lid]) => {{
            const inst = window.__deckgl_instances && window.__deckgl_instances[mid];
            if (!inst || !inst.lastLayers) return false;
            const l = inst.lastLayers.find(x => x.id === lid);
            return !!l && ({pred});
        }}""",
        arg=[MAP_ID, layer_id],
        timeout=_T,
    )
    return _layer(page, layer_id)


def _no_output_errors(page) -> None:
    errors = page.locator(".shiny-output-error:visible")
    assert errors.count() == 0, errors.all_inner_texts()


def _reset_data_type(page) -> None:
    """Leave the page on the Grid type (closes any results file)."""
    try:
        _set_select(page, "visualize-data_type", "grid")
        page.wait_for_timeout(300)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
def test_results_map_load_step_play_switch_and_clear(pw_page, live_server, app_work_dir):
    page = pw_page
    proj = _project(app_work_dir, "results_map_e2e")
    write_ugrid(proj / "hydro.nc", n_time=6, kind="hydro")
    write_ugrid(proj / "ts.nc", n_time=3, kind="ts")
    _open_project(page, proj)
    try:
        _choose_results(page)
        _load(page, "hydro.nc")
        expect(page.locator(LABEL)).to_contain_text("record 1 / 6", timeout=_T)
        webgl = _has_webgl(page)

        # Load again: a no-op (nothing reopened, the record keeps advancing below)
        page.locator("#visualize-load_data_btn").click()
        expect(page.locator(".shiny-notification").last).to_contain_text("already open", timeout=_T)
        colors0 = None
        if webgl:
            colors0 = _wait_layer(page, "results-mesh", "!!l._meshColors")["colors"]

        page.locator("#visualize-results_map-step_fwd").click()
        expect(page.locator(LABEL)).to_contain_text("record 2 / 6", timeout=_T)
        if webgl:
            page.wait_for_timeout(500)
            assert _layer(page, "results-mesh")["colors"] != colors0, "a step patches colours"

        # Play: the record advances, no output error
        page.locator(PLAY).click()
        expect(page.locator(PLAY)).to_have_text("Pause", timeout=_T)
        page.wait_for_timeout(2000)
        assert _record(_label(page)) != 2, "playback advanced"
        _no_output_errors(page)

        # switch to the ts file while playing: the ticker survives the switch
        _load(page, "ts.nc")
        expect(page.locator(LABEL)).to_contain_text("/ 3", timeout=_T)
        first = _label(page)
        page.wait_for_function(
            "([sel, t]) => document.querySelector(sel).innerText.trim() !== t",
            arg=[LABEL, first],
            timeout=3000,
        )
        assert _label(page).endswith("/ 3")
        _no_output_errors(page)

        # Data Type away and back: the map is cleared and stopped
        _set_select(page, "visualize-data_type", "grid")
        page.wait_for_timeout(500)
        _choose_results(page)
        expect(page.locator(PLAY)).to_have_text("Play", timeout=_T)
        expect(page.locator(LABEL)).to_have_text("", timeout=_T)

        # a cleared map forgets what was open: the hydro file loads from record 1
        _load(page, "hydro.nc")
        expect(page.locator(LABEL)).to_contain_text("record 1 / 6", timeout=_T)
        page.wait_for_timeout(1000)
        assert "record 1 / 6" in _label(page), "not playing"
        _no_output_errors(page)
        if not webgl:
            pytest.skip("no WebGL in this browser: layer (lastLayers) assertions skipped")
    finally:
        _reset_data_type(page)


@pytest.fixture(scope="module")
def fresh_page(pw_browser, live_server):
    """A second Shiny session: a map that has shown nothing before."""
    ctx = pw_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    page.goto(live_server, wait_until="networkidle", timeout=30000)
    page.wait_for_function(
        "() => { const el = document.getElementById('home-system_health_count');"
        " return el && !el.classList.contains('recalculating') && el.children.length > 0; }",
        timeout=30000,
    )
    page.evaluate("document.querySelectorAll('.modal.show .btn-close').forEach(b => b.click())")
    yield page
    page.close()
    ctx.close()


@pytest.mark.e2e
def test_results_map_ts_file_first_on_a_fresh_page(fresh_page, app_work_dir):
    page = fresh_page
    proj = _project(app_work_dir, "results_map_e2e_ts")
    write_ugrid(proj / "ts.nc", n_time=3, kind="ts")
    _open_project(page, proj)
    try:
        _choose_results(page)
        _load(page, "ts.nc")
        expect(page.locator(LABEL)).to_contain_text("record 1 / 3", timeout=_T)
        _no_output_errors(page)
        if not _has_webgl(page):
            pytest.skip("no WebGL in this browser: layer (lastLayers) assertions skipped")
        layer = _wait_layer(page, "results-mesh", "!!l._meshColors")
        assert layer["colors"]
        assert _layer(page, "results-arrows") is None, "no currents: no arrows layer"
    finally:
        _reset_data_type(page)


@pytest.mark.e2e
def test_results_map_real_shy_converts_once(fresh_page, app_work_dir):
    sample = SAMPLES / "mar_menor" / "mm_lgr.hydro.shy"
    if shutil.which("shyelab") is None:
        pytest.skip("shyelab is not on PATH (put SHYFEM's bin/ on PATH to run this test)")
    if not sample.is_file():
        pytest.skip(f"{sample} not found (set SHYFEM_SAMPLES_DIR; .shy outputs are not in git)")
    page = fresh_page
    proj = _project(app_work_dir, "results_map_e2e_shy")
    shutil.copy2(sample, proj / "mm_lgr.hydro.shy")
    cache = app_work_dir / ".shyfem_viewer_cache"
    _open_project(page, proj)
    try:
        _choose_results(page)
        _load(page, "mm_lgr.hydro.shy")
        expect(page.locator(LABEL)).to_contain_text("/ 32", timeout=60000)
        entries = sorted(cache.glob("*.nc"))
        src = proj.joinpath("mm_lgr.hydro.shy").resolve()
        mine = [e for e in entries if e.with_suffix(".src").read_text() == str(src)]
        assert len(mine) == 1, f"one cache entry for the sample: {entries}"
        mtime = mine[0].stat().st_mtime_ns
        _no_output_errors(page)

        webgl = _has_webgl(page)
        positions = None
        if webgl:
            positions = _wait_layer(page, "results-mesh", "!!l._meshPositions")["positions"]
        # Current arrows
        arrows = page.locator("#visualize-results_map-arrows")
        arrows.wait_for(state="attached", timeout=_T)
        arrows.check(force=True)
        if webgl:
            layer = _wait_layer(
                page, "results-arrows", "Array.isArray(l.data) && l.data.length > 0"
            )
            assert layer["n_data"] > 0

        # Load again: no conversion (the cache entry is not even touched)
        page.locator("#visualize-load_data_btn").click()
        expect(page.locator(".shiny-notification").last).to_contain_text("already open", timeout=_T)
        page.wait_for_timeout(1000)
        assert mine[0].stat().st_mtime_ns == mtime, "no conversion, no cache touch"
        _no_output_errors(page)
        if not webgl:
            pytest.skip("no WebGL in this browser: layer (lastLayers) assertions skipped")
        assert _layer(page, "results-mesh")["positions"] == positions
    finally:
        _reset_data_type(page)
