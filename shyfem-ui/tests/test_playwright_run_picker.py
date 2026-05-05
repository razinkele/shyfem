"""Playwright tests for run file-picker session-driven behaviour.

Coverage via _stub_run_server (see Section M.1 followup) — auto-fill
semantics are NOT tested here (the stub doesn't replicate them; they're
covered by the unit-test wiring assertion). Picker UI wiring,
no-project placeholder, and traversal-warning toast ARE tested.
"""

import pytest


@pytest.mark.e2e
class TestRunPickerNoProject:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project(null);
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_picker_shows_no_files_available_when_no_project(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Run']").click(force=True)
        pw_page.wait_for_timeout(1000)
        select = pw_page.locator('#run-fp_input-file_select')
        select.wait_for(state="attached", timeout=5000)
        option_texts = pw_page.locator(
            '#run-fp_input-file_select option'
        ).all_inner_texts()
        assert any("No files available" in t for t in option_texts)

    def test_picker_callback_warns_on_traversal(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Run']").click(force=True)
        pw_page.wait_for_timeout(800)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p',
                work_dir: '/tmp/p',
                description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.wait_for_timeout(500)

        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'run-fp_input-file_select', '/etc/passwd',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(800)

        warning_toasts = pw_page.locator(
            '.shiny-notification.shiny-notification-warning'
        ).count()
        assert warning_toasts >= 1
