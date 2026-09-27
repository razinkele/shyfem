"""E2E: import the fixture project, build the cache, see the map and the
skill table.

Runs against the real live server -- `pw_page` drives Chromium against the
Shiny app started by `_app_server`/`_test_app.py`, and clicking "Build cache"
spawns a REAL `python -m shyfem_ui.boxmodel_cache_cli` child process (see
`shyfem_ui/services/boxmodel_cache.py::start_build`). This is therefore the
only place in the suite that exercises that child end to end.

Default pytest config excludes `test_playwright_*.py`
(`--ignore-glob="tests/test_playwright_*.py"` in `addopts`); run this file
directly or via `--override-ini="addopts="`.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests._boxmodel_fixture import make_box_project, make_box_run
from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]


@pytest.fixture
def box_project(app_work_dir):
    """A real box-model project on disk, under the LIVE APP's own work_dir.

    See `app_work_dir`'s docstring (tests/conftest.py) for why the project
    must live there rather than under `get_config().work_dir` (a different
    process's config) or pytest's own `tmp_path` (under `/tmp`, which the
    cache-build child's `--trusted-base` allowlist does not include).

    No DB `Project` row is created: `editor_denied_reason`'s DB-backed
    `check_project_access` path is only reached when `user is not None`, and
    `_test_app.py` never passes `current_user` to `boxmodel_server`, so
    `user` is always `None` for this page in the test app -- the DB is never
    consulted for this project id. (A row created here would land in the
    wrong database anyway: `_isolate_env` points the pytest process's own
    `SHYFEM_UI_DATABASE_URL` at a session-temp db, while the live app
    subprocess was started against its own separate `test.db`.)

    40 observation days (`obs_days=40`) so the skill table has >= 30 matched
    days for salinity/temperature/level at site A (box 1) -- the default of
    10 would yield no skill row at all (`MIN_N_SKILL = 30` in
    `services/boxmodel_skill.py`).
    """
    work = app_work_dir / "e2e_boxmodel"
    run_dir = work / "run"
    run_b = work / "run_b"
    make_box_run(run_dir, days=40)
    # A second run, 1.5 warmer/saltier, so the Compare tab has a non-zero
    # B - A difference map and two columns in the side-by-side table.
    make_box_run(run_b, days=40, offset=1.5)
    make_box_project(
        work,
        run_dir,
        obs_days=40,
        extra_runs=[("b", "run B", run_b)],
        str_file=True,
        forcing=True,
    )
    return {
        "id": 9001,
        "name": "e2e_boxmodel",
        "work_dir": str(work),
        "description": None,
        "grids": [],
        "simulations": [],
        "files": [],
    }


def test_boxmodel_page_builds_cache_and_renders(pw_page, box_project):
    """Pick the run, build the cache for real, and see the map + skill row."""
    # The hook takes the active_project DICT (matching every other picker
    # E2E test's `__test_set_active_project({...})` calls and how
    # `_test_active_project_hook` in _test_app.py stores it verbatim) --
    # not a bare project id string.
    pw_page.evaluate("(proj) => window.__test_set_active_project(proj)", box_project)
    pw_page.wait_for_timeout(300)
    pw_page.evaluate("shyfemNavTo('Box-model')")

    run_select = pw_page.locator("#boxmodel-run")
    run_select.wait_for(state="visible", timeout=15000)
    # The manifest loads asynchronously over the websocket after the page
    # becomes visible, so the run choices land a moment after the <select>
    # itself is visible -- poll for the value rather than reading it once.
    expect(run_select).to_have_value("fix", timeout=15000)

    # Ask for the raw output-step frame as well: this is the only check that
    # the checkbox reaches the child's command line, which is where --hourly
    # decides whether the frame is written at all.
    pw_page.locator("#boxmodel-hourly").check()
    pw_page.locator("#boxmodel-build").click()
    # Real child process (shyfem_ui.boxmodel_cache_cli) parsing 40 days x 3
    # boxes; 60s is generous headroom over local run time.
    expect(pw_page.locator("#boxmodel-cache_state")).to_contain_text("ready", timeout=60000)
    cache_dir = Path(box_project["work_dir"]) / ".boxmodel_cache" / "fix"
    assert (
        cache_dir / "state_hourly.parquet"
    ).is_file(), "the hourly checkbox did not reach start_build"
    # The window rule that decides whether the page USES it is unit-tested;
    # this fixture's 40-day period is deliberately wider than the cap.
    pw_page.locator("#boxmodel-hourly").uncheck()
    # Two canvases live inside the widget (maplibre's own + deck.gl's
    # overlay) once WebGL initializes; either proves the map rendered.
    expect(pw_page.locator("#boxmodel-boxmap-deckgl_map canvas").first).to_be_visible(timeout=15000)

    pw_page.get_by_role("tab", name="Time series").click()
    expect(pw_page.locator("#boxmodel-skill_table table tbody tr").first).to_be_visible(
        timeout=30000
    )
    assert "salinity" in pw_page.locator("#boxmodel-skill_table").inner_text()
    # The band-amplitude block renders beside the skill table. The fixture has
    # only 10 observation days, far short of the 120 gap-free days
    # band_amplitude_ratios needs, so the "needs" row is the expected content
    # -- and asserting on it proves the render itself did not error (a render
    # exception would leave a shiny-output-error div here instead).
    band = pw_page.locator("#boxmodel-band_ratios")
    expect(band).to_contain_text("gap-free days", timeout=15000)
    assert "shiny-output-error" not in (band.get_attribute("class") or "")

    # --- Compare tab: build the second run for real, then compare ---------
    pw_page.locator("#boxmodel-run").select_option("b")
    expect(pw_page.locator("#boxmodel-cache_state")).not_to_contain_text("ready", timeout=15000)
    pw_page.locator("#boxmodel-build").click()
    expect(pw_page.locator("#boxmodel-cache_state")).to_contain_text("ready", timeout=60000)

    pw_page.get_by_role("tab", name="Compare").click()
    # The selectors render once two caches are ready; first two runs are
    # preselected (A = fix, B = b), so nothing needs driving.
    expect(pw_page.locator("#boxmodel-cmp_runs")).to_be_attached(timeout=30000)
    # Diverging legend around B - A = +1.5 (temp): a negative and a positive
    # bound, and the central bin straddling zero.
    legend = pw_page.locator("#boxmodel-cmp_legend")
    expect(legend).to_contain_text("B − A", timeout=30000)
    legend_text = legend.inner_text()
    assert "-1.5" in legend_text and "+1.5" in legend_text, legend_text
    assert "shiny-output-error" not in (legend.get_attribute("class") or "")
    # Side by side: one column per run label (A first) and populated rows.
    skill = pw_page.locator("#boxmodel-cmp_skill")
    expect(skill.locator("table tbody tr").first).to_be_visible(timeout=30000)
    head = skill.locator("table thead").inner_text()
    assert "fixture run" in head and "run B" in head, head
    assert head.index("fixture run") < head.index("run B")
    assert "salinity" in skill.inner_text()
    # 40-day fixture: per-year needs 60 matched days -> the explanatory message.
    expect(pw_page.locator("#boxmodel-cmp_per_year")).to_contain_text(
        "60 matched days", timeout=15000
    )
    # No canvas assertion for the second map on purpose (the one WebGL check
    # above is the suite's single local flake).

    # --- Setup tab: STR-derived boundaries, summary, river and meteo widgets --
    pw_page.get_by_role("tab", name="Setup").click()
    bounds = pw_page.locator("#boxmodel-setup_boundaries")
    expect(bounds.locator("table tbody tr")).to_have_count(2, timeout=30000)
    bounds_text = bounds.inner_text()
    assert "Fixture river" in bounds_text and "0.25" in bounds_text, bounds_text
    assert "fem_forcing/river.txt" in bounds_text and "not read (.fem)" in bounds_text
    summary = pw_page.locator("#boxmodel-setup_summary")
    expect(summary).to_contain_text("idtbox", timeout=15000)
    assert "nsigma" in summary.inner_text()  # orphan key outside any section
    for oid in ("setup_rivers", "setup_meteo", "setup_message", "setup_summary"):
        el = pw_page.locator(f"#boxmodel-{oid}")
        expect(el).to_be_attached(timeout=15000)
        assert "shiny-output-error" not in (el.get_attribute("class") or ""), oid
    # A ready cache is loaded for the header run, so meteo has a variable select.
    expect(pw_page.locator("#boxmodel-setup_meteo_var")).to_be_attached(timeout=15000)
    # Picking a boundary must not error (selection is shown on the map only).
    pw_page.locator("#boxmodel-setup_pick_2").click()
    pw_page.wait_for_timeout(500)
    assert "shiny-output-error" not in (bounds.get_attribute("class") or "")

    # Leave the shared session page clean for the next test file: pw_page is
    # session-scoped, so a lingering non-Dashboard tab / modal would leak.
    _dismiss_modals(pw_page)
    pw_page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
    pw_page.wait_for_timeout(300)


def test_boxmodel_manifest_tab_saves_an_edit(pw_page, box_project):
    """Edit boxmodel.json through the form and see it persist.

    The whole chain in one test: render the form from the file, collect the
    inputs, overlay them on the raw document, validate, write, and re-read --
    the alternative to editing this file by hand, which is what the page
    required until now.
    """
    import json

    pw_page.evaluate("(proj) => window.__test_set_active_project(proj)", box_project)
    pw_page.wait_for_timeout(300)
    pw_page.evaluate("shyfemNavTo('Box-model')")

    manifest_path = Path(box_project["work_dir"]) / "boxmodel.json"
    before = json.loads(manifest_path.read_text())

    pw_page.get_by_role("tab", name="Manifest").click()
    title = pw_page.locator("#boxmodel-mf_title")
    expect(title).to_be_visible(timeout=15000)
    expect(title).to_have_value(before["title"], timeout=15000)

    title.fill("Edited from the form")
    pw_page.locator("#boxmodel-mf_save").click()

    # The file is the assertion: the save validated and wrote.
    for _ in range(40):
        after = json.loads(manifest_path.read_text())
        if after["title"] == "Edited from the form":
            break
        pw_page.wait_for_timeout(500)
    assert after["title"] == "Edited from the form"
    # A relative path stays relative and stays itself -- this is what breaks if
    # the form is ever filled from the RESOLVED manifest instead of the file.
    assert after["grid"]["grd"] == before["grid"]["grd"]
    assert {r["id"] for r in after["runs"]} == {r["id"] for r in before["runs"]}
    # The run dirs in this fixture are absolute but inside the project, so the
    # save normalises them to relative on purpose (a manifest that names its
    # own project by absolute path is not portable). Same directories either
    # way, which is what has to hold.
    project_dir = Path(box_project["work_dir"])

    def _resolved(doc):
        return sorted(str((project_dir / Path(r["dir"])).resolve()) for r in doc["runs"])

    assert _resolved(after) == _resolved(before)
    assert all(not Path(r["dir"]).is_absolute() for r in after["runs"])
    # Nothing the user did not touch may disappear. A save used to delete every
    # optional path whose picker could not offer its stored value -- forcing.dir
    # on every project that had one -- and this test passed while writing that
    # damaged file, because it only checked the fields it had edited.
    for key in ("forcing", "str", "observations", "boxes"):
        if before.get(key):
            assert after.get(key), f"the save dropped {key!r}"
