"""Playwright: a Physics-page save writes only what the user changed.

Unit tests feed the save loop hand-built input values; these drive the real
renders, so they also catch a render that shows something other than the
file's value (S-01) and inputs left over from a panel rendered earlier.
"""

import re

import pytest

_A = """$title
        save test
        sim_a
        grid
$end
$para
        itanf = 0       itend = 3600    idt = 60
        ilin = 0
        aapar = 0.
$end
"""

_B = _A.replace("sim_a", "sim_b").replace("ilin = 0", "ilin = 1")


@pytest.mark.e2e
class TestPhysicsSave:
    @pytest.fixture
    def project(self, pw_page, live_server, app_work_dir):
        wd = app_work_dir / "physics_save"
        wd.mkdir(exist_ok=True)
        (wd / "a.str").write_text(_A)
        (wd / "b.str").write_text(_B)
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

    def _load(self, page, wd, name):
        page.locator("select#physics-str_path").select_option(str(wd / name))
        page.locator("#physics-load_btn").click()
        page.get_by_text(f"Loaded {name}").first.wait_for(timeout=5000)

    def _toggle(self, page, label):
        page.locator("#physics-physics_accordion .accordion-button").filter(
            has_text=re.compile(rf"^\s*{label}\s*$")
        ).click()
        page.wait_for_timeout(600)

    def _save(self, page, wd, name):
        before = (wd / name).stat().st_mtime_ns
        page.locator("#physics-save_btn").click()
        page.wait_for_timeout(1500)
        return (wd / name).stat().st_mtime_ns != before

    def test_opened_panels_and_no_edit_leave_the_file_unchanged(self, pw_page, project):
        self._load(pw_page, project, "a.str")
        for label in ("Hydrodynamics", "Vertical Structure", "Boundary Conditions"):
            self._toggle(pw_page, label)
        assert pw_page.locator("select#physics-ilin").input_value() == "0"
        assert self._save(pw_page, project, "a.str"), "save did not write"
        text = (project / "a.str").read_text()
        assert "ilin = 0\n" in text
        assert "aapar = 0.\n" in text
        assert "$bound" not in text
        assert "dlat" not in text

    def test_a_panel_rendered_for_another_file_does_not_leak_into_the_next(
        self, pw_page, project
    ):
        self._load(pw_page, project, "a.str")
        self._toggle(pw_page, "Hydrodynamics")  # open: renders ilin = 0
        self._toggle(pw_page, "Hydrodynamics")  # collapse: stays rendered for a.str
        self._load(pw_page, project, "b.str")
        assert self._save(pw_page, project, "b.str"), "save did not write"
        assert "ilin = 1\n" in (project / "b.str").read_text()
