"""Playwright tests for postprocess file-picker session-driven behaviour."""

import pytest


@pytest.mark.e2e
class TestPostprocessPickerNoProject:
    @pytest.fixture(autouse=True)
    def _reset_active_project(self, pw_page):
        """Reset session-scoped state."""
        pw_page.evaluate("""
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project("");
            }
        """)
        pw_page.wait_for_timeout(200)
        yield

    def test_picker_shows_no_files_available_when_no_project(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(1000)
        select = pw_page.locator('#postprocess-fp_shy-file_select')
        select.wait_for(state="attached", timeout=5000)
        option_texts = pw_page.locator(
            '#postprocess-fp_shy-file_select option'
        ).all_inner_texts()
        assert any("No files available" in t for t in option_texts)

    def test_typing_into_shy_path_is_not_clobbered(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(800)
        shy_input = pw_page.locator('#postprocess-shy_path')
        shy_input.wait_for(state="attached", timeout=5000)
        shy_input.fill("/tmp/manual-typed.shy")
        pw_page.wait_for_timeout(800)
        assert shy_input.input_value() == "/tmp/manual-typed.shy"

    def test_empty_guard_preserves_user_input(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(800)
        shy_input = pw_page.locator('#postprocess-shy_path')
        shy_input.fill("/tmp/preset-value.shy")
        pw_page.wait_for_timeout(300)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: '/tmp/different-workdir',
                description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip("test_app.py does not expose __test_set_active_project")
        pw_page.wait_for_timeout(800)
        assert shy_input.input_value() == "/tmp/preset-value.shy"

    def test_picker_callback_warns_on_traversal(self, pw_page, live_server):
        pw_page.locator(".sf-nav-item[data-nav='Post-Process']").click(force=True)
        pw_page.wait_for_timeout(800)

        # Reset the field in case prior test left a value (see Task 4 finding)
        shy_input = pw_page.locator('#postprocess-shy_path')
        shy_input.wait_for(state="attached", timeout=5000)
        shy_input.fill("")
        pw_page.wait_for_timeout(200)

        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: '/tmp/p',
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
                'postprocess-fp_shy-file_select', '/etc/passwd',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(800)

        warnings = pw_page.locator(
            '.shiny-notification.shiny-notification-warning'
        ).count()
        assert warnings >= 1
