"""Playwright: a Physics-page save writes only what the user changed.

Unit tests feed the save loop hand-built input values; these drive the real
renders, so they also catch a render that shows something other than the
file's value (S-01) and inputs left over from a panel rendered earlier.
"""

import re

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from shyfem_ui.pages.physics import PHYSICS_PANELS

# The render stamp of every panel the browser has bound (a panel that failed
# to render has no stamp). Bound = its value has reached the server.
_STAMPS_JS = """() => [...document.querySelectorAll("[id^='physics-panel_']")]
    .filter(o => !o.querySelector('.physics-panel-failed'))
    .map(o => {
        const s = o.querySelector("input[id^='physics-render_stamp_']");
        return s && s.classList.contains('shiny-bound-input') ? s.value : null;
    })"""

_A = """$title
        save test
        sim_a
        grid
$end
$para
        itanf = 0       itend = 3600    idt = 60
        ilin = 0
        aapar = 0.
        iclin = 1.
        idtcon = 600
$end
$sedtr
        sedgrs = 0.1 0.2 0.3
$end
"""

_B = _A.replace("sim_a", "sim_b").replace("ilin = 0", "ilin = 1")
# vismol with a Fortran d exponent: the Turbulence panel cannot render it
_D = _A.replace("sim_a", "sim_d").replace("ilin = 0", "ilin = 0\n        vismol = 1.d-6")
# idtsyn as an interval string, as in mm_hyd_22a.str and venlag.str
_C = _A.replace("sim_a", "sim_c").replace("ilin = 0", "ilin = 1\n        idtsyn = '1h'")


@pytest.mark.e2e
class TestPhysicsSave:
    @pytest.fixture
    def project(self, pw_page, live_server, app_work_dir):
        wd = app_work_dir / "physics_save"
        wd.mkdir(exist_ok=True)
        (wd / "a.str").write_text(_A)
        (wd / "b.str").write_text(_B)
        (wd / "c.str").write_text(_C)
        (wd / "d.str").write_text(_D)
        result = pw_page.evaluate(
            """(wd) => {
                if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
                window.__test_set_active_project({
                    id: 1, name: 'p', work_dir: wd, description: null,
                    grids: [], simulations: [{name: 's', str_file: 'a.str'}], files: [],
                });
                return 'set';
            }""",
            str(wd),
        )
        if result == "no-hook":
            pytest.skip("test app does not expose __test_set_active_project")
        pw_page.locator(".sf-nav-item[data-nav='Physics']").click(force=True)
        pw_page.locator("select#physics-str_path").wait_for(state="attached", timeout=5000)
        yield wd
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)

    def _stamps(self, page):
        return page.evaluate(_STAMPS_JS)

    def _wait_rendered(self, page, before, timeout=15000):
        """Wait until every panel shows one new render (the notice comes earlier)."""
        page.wait_for_function(
            f"""(before) => {{
                const v = ({_STAMPS_JS})();
                return v.length > 0 && v.every(x => x !== null && x === v[0])
                    && !before.includes(v[0]);
            }}""",
            arg=before,
            timeout=timeout,
        )

    def _load(self, page, wd, name):
        before = self._stamps(page)
        page.locator("select#physics-str_path").select_option(str(wd / name))
        page.locator("#physics-load_btn").click()
        page.get_by_text(f"Loaded {name}").first.wait_for(timeout=5000)
        self._wait_rendered(page, before)

    def _set_open(self, page, label, want_open):
        """Open or collapse a panel; the shared page keeps earlier tests' state."""
        button = page.locator("#physics-physics_accordion .accordion-button").filter(
            has_text=re.compile(rf"^\s*{re.escape(label)}\s*$")
        )
        if (button.get_attribute("aria-expanded") == "true") != want_open:
            button.click()
            page.wait_for_timeout(600)

    def _save(self, page, wd, name):
        before = (wd / name).stat().st_mtime_ns
        stamps = self._stamps(page)
        page.locator("#physics-save_btn").click()
        try:
            # A save sets a new file state, so the panels render again; the
            # next action must not land before they have.
            self._wait_rendered(page, stamps, timeout=10000)
        except PlaywrightTimeoutError:
            pass  # nothing was saved; the mtime check below says so
        return (wd / name).stat().st_mtime_ns != before

    def test_every_panel_opened_and_no_edit_leaves_the_file_unchanged(self, pw_page, project):
        self._load(pw_page, project, "a.str")
        for panel in PHYSICS_PANELS.values():
            self._set_open(pw_page, panel["label"], True)
        assert pw_page.locator("select#physics-ilin").input_value() == "0"
        assert self._save(pw_page, project, "a.str"), "save did not write"
        assert (project / "a.str").read_text() == _A

    def test_a_panel_rendered_for_another_file_does_not_leak_into_the_next(self, pw_page, project):
        self._load(pw_page, project, "a.str")
        self._set_open(pw_page, "Hydrodynamics", True)  # renders ilin = 0
        self._set_open(pw_page, "Hydrodynamics", False)  # rendered for a.str, now hidden
        self._load(pw_page, project, "b.str")
        assert self._save(pw_page, project, "b.str"), "save did not write"
        assert "ilin = 1\n" in (project / "b.str").read_text()

    def test_a_second_save_keeps_an_edit_to_a_param_shown_twice(self, pw_page, project):
        """idtcon is in two panels; after a save the hidden copy must follow the file."""
        self._load(pw_page, project, "a.str")
        self._set_open(pw_page, "Temperature & Salinity", True)
        self._set_open(pw_page, "Output & Restart", True)
        self._set_open(pw_page, "Output & Restart", False)  # its copy is now hidden
        pw_page.locator("#physics-idtcon").fill("1200")
        pw_page.locator("#physics-idtcon").blur()
        pw_page.wait_for_timeout(500)
        assert self._save(pw_page, project, "a.str"), "first save did not write"
        assert "idtcon = 1200\n" in (project / "a.str").read_text()
        assert self._save(pw_page, project, "a.str"), "second save did not write"
        assert "idtcon = 1200\n" in (project / "a.str").read_text()

    def test_a_file_with_interval_strings_takes_no_values_from_the_previous_one(
        self, pw_page, project
    ):
        self._load(pw_page, project, "a.str")
        self._set_open(pw_page, "Hydrodynamics", True)
        self._load(pw_page, project, "c.str")
        assert self._save(pw_page, project, "c.str"), "save did not write"
        assert (project / "c.str").read_text() == _C

    def test_a_save_sent_before_the_panels_show_the_loaded_file_writes_nothing(
        self, pw_page, project
    ):
        self._load(pw_page, project, "a.str")
        self._set_open(pw_page, "Hydrodynamics", True)
        before = (project / "c.str").stat().st_mtime_ns
        stamps = self._stamps(pw_page)
        pw_page.locator("select#physics-str_path").select_option(str(project / "c.str"))
        # Load and Save in one browser task: the Save reaches the server
        # before the browser can have bound the panels rendered for c.str,
        # so the server still holds a.str's input values (ilin = 0).
        pw_page.evaluate("""() => {
                document.querySelector('#physics-load_btn').click();
                document.querySelector('#physics-save_btn').click();
            }""")
        expect(pw_page.get_by_text("still showing the previous file").first).to_be_visible(
            timeout=10000
        )
        self._wait_rendered(pw_page, stamps)
        assert (project / "c.str").stat().st_mtime_ns == before, "the early save wrote"
        assert (project / "c.str").read_text() == _C
        # Once the panels show c.str, the save writes it unchanged.
        assert self._save(pw_page, project, "c.str"), "save did not write"
        assert (project / "c.str").read_text() == _C

    def test_every_panel_renders_its_inputs(self, pw_page, project):
        for name in ("a.str", "c.str"):
            self._load(pw_page, project, name)
            for panel_id in PHYSICS_PANELS:
                out = pw_page.locator(f"#physics-panel_{panel_id}")
                assert out.locator(".shiny-output-error").count() == 0, (name, panel_id)
                assert out.locator("input, select").count() > 0, (name, panel_id)

    def test_a_panel_that_cannot_render_saves_none_of_its_stale_inputs(self, pw_page, project):
        self._load(pw_page, project, "a.str")
        self._set_open(pw_page, "Turbulence & Mixing", True)
        self._load(pw_page, project, "d.str")
        assert (
            "cannot show the loaded file"
            in pw_page.locator("#physics-panel_turbulence").inner_text()
        )
        assert self._save(pw_page, project, "d.str"), "save did not write"
        assert (project / "d.str").read_text() == _D
