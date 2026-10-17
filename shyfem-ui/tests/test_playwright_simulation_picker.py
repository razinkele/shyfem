"""Playwright tests for the Simulation page's project-file STR dropdown."""

import re

import pytest
from playwright.sync_api import expect


@pytest.mark.e2e
class TestSimulationStrDropdown:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_prompts_to_open_project_and_has_no_free_text_box(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(1000)
        picker = pw_page.locator("#simulation-str_path_picker")
        picker.wait_for(state="attached", timeout=5000)
        assert "Open a project" in picker.inner_text()
        assert pw_page.locator("input#simulation-str_path").count() == 0
        assert pw_page.locator("#simulation-fp_str-file_select").count() == 0

    def test_lists_and_preselects_project_str_when_project_active(
        self, pw_page, live_server, tmp_path
    ):
        (tmp_path / "sim.str").write_text("$title\n$end\n")
        result = pw_page.evaluate(
            """(wd) => {
                if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
                window.__test_set_active_project({
                    id: 1, name: 'p', work_dir: wd, description: null,
                    grids: [], simulations: [{name: 's', str_file: 'sim.str'}], files: [],
                });
                return 'set';
            }""",
            str(tmp_path),
        )
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(1000)
        select = pw_page.locator("select#simulation-str_path")
        select.wait_for(state="attached", timeout=5000)
        assert any("sim.str" in t for t in select.locator("option").all_inner_texts())
        assert select.input_value().endswith("sim.str")

    def test_sample_load_injects_and_preselects_sample_option(self, pw_page, live_server):
        """The bundled Mar Menor sample lives outside any project; loading it
        must still show up in the dropdown as an injected, preselected option."""
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(800)
        btn = pw_page.locator("#simulation-load_sample_btn")
        if btn.count() == 0:
            pytest.skip("sample-data card not rendered")
        btn.click(force=True)
        pw_page.wait_for_timeout(1500)
        select = pw_page.locator("select#simulation-str_path")
        select.wait_for(state="attached", timeout=5000)
        texts = select.locator("option").all_inner_texts()
        assert any(t.startswith("Sample:") for t in texts), texts
        assert select.input_value().endswith(".str")


@pytest.mark.e2e
class TestStrEditorFileFieldSelectize:
    """A file parameter in the STR editor's Form view is a selectize with
    create: a typed name survives blur + Apply and lands in the STR text."""

    def test_typed_file_name_round_trips_into_editor_text(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Simulation']").click(force=True)
        pw_page.wait_for_timeout(800)
        btn = pw_page.locator("#simulation-load_sample_btn")
        if btn.count() == 0:
            pytest.skip("sample-data card not rendered")
        btn.click(force=True)
        pw_page.wait_for_timeout(1500)
        # The editor lives in the "Editor" sub-tab; an earlier file may have
        # left the page on another sub-tab, and Shiny suspends outputs in
        # hidden tab panes (no form fields would render). Select it, and the
        # Split view, explicitly: both persist on the session-scoped page.
        editor_tab = pw_page.locator("#sf-page-Simulation a.nav-link:has-text('Editor')").first
        if editor_tab.count():
            editor_tab.click(force=True)
            pw_page.wait_for_timeout(500)
        pw_page.locator("#simulation-str_editor-view_mode input[value='split']").check(force=True)
        pw_page.wait_for_timeout(800)
        area = pw_page.locator("#simulation-str_editor-editor_content")
        area.wait_for(state="attached", timeout=10000)
        # Loading a file must fill the raw pane, not only the form.
        expect(area).to_have_value(re.compile(r"\$title"), timeout=10000)
        # The sample STR has a $name section with file params; pick the first
        # selectize-backed form field whose id names a known file param.
        field = pw_page.locator("select[id^='simulation-str_editor-form_name_']").first
        try:
            field.wait_for(state="attached", timeout=10000)
        except Exception:
            info = pw_page.evaluate("""() => ({
                    sample: (document.getElementById('simulation-sample_str_select')||{}).value,
                    form_selects: [...document.querySelectorAll("select[id^='simulation-str_editor-form_']")].map(e=>e.id).slice(0,8),
                    form_inputs: [...document.querySelectorAll("input[id^='simulation-str_editor-form_']")].map(e=>e.id).slice(0,8),
                    view: [...document.querySelectorAll("#simulation-str_editor-view_mode input")].filter(e=>e.checked).map(e=>e.value),
                    text: ((document.getElementById('simulation-str_editor-editor_content')||{}).value||'').slice(0,200),
                    toasts: [...document.querySelectorAll('.shiny-notification')].map(e=>e.innerText.slice(0,80)),
                })""")
            raise AssertionError(f"no $name file field rendered; state={info!r}") from None
        field_id = field.get_attribute("id")
        control = pw_page.locator(
            f"#{field_id} + .selectize-control input, "
            f"[id='{field_id}'] ~ .selectize-control input"
        ).first
        if control.count() == 0:
            control = pw_page.locator(
                f".selectize-control:has(+ script[data-for='{field_id}']) input"
            ).first
        assert control.count() > 0, "selectize control not initialised"
        control.click()
        control.fill("INPUT/typed_by_test.dat")
        control.press("Enter")
        pw_page.wait_for_timeout(300)
        pw_page.locator("#simulation-str_editor-apply_form_btn").click(force=True)
        try:
            expect(area).to_have_value(re.compile("typed_by_test"), timeout=10000)
            # The applied text must stay: the textarea used to live in a
            # render that re-ran on every re-parse, so Apply's own echo
            # replaced it with an empty one ~40 ms later.
            pw_page.wait_for_timeout(1500)
            expect(area).to_have_value(re.compile("typed_by_test"), timeout=100)
        except AssertionError:
            # Diagnostics: what did the field hold, and what is the textarea now?
            val = pw_page.evaluate(
                "(id) => { const el = document.getElementById(id); return el ? el.value : null; }",
                field_id,
            )
            raise AssertionError(
                f"field {field_id} value={val!r}; textarea head={area.input_value()[:300]!r}"
            ) from None
