"""Playwright tests for partitioning file-picker session-driven behaviour.

These tests require a running Shiny app -- shiny 1.5.1 has no public
API for invoking @module.server-decorated functions outside an active
session, so all wiring/effect/wrapper tests live here.

Run with:

    pytest tests/test_playwright_partitioning_picker.py \\
        --override-ini="addopts="

(default pytest config excludes test_playwright_*.py via
addopts = "--ignore-glob=tests/test_playwright_*.py").
"""

import pytest


@pytest.mark.e2e
class TestPartitioningPickerNoProject:
    """Behaviour when no active project is set (the default for the
    test app at session startup). Covers spec tests 7 (placeholder),
    10 (isolate regression), and 11(c) (no-project branch).
    """

    def test_picker_shows_no_files_available_when_no_project(
        self, pw_page, live_server,
    ):
        """Spec test 7 / partial: project_id=None branch of file_picker
        renders the 'No files available' placeholder.
        """
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(1000)

        # Shiny's input_select uses Selectize.js by default -- it hides
        # the native <select> (display:none) and renders a custom widget.
        # The <option> children are still in the DOM though, so query
        # them directly to be Selectize-agnostic.
        select = pw_page.locator('#partitioning-fp_bas-file_select')
        select.wait_for(state="attached", timeout=5000)
        option_texts = pw_page.locator(
            '#partitioning-fp_bas-file_select option'
        ).all_inner_texts()
        assert any("No files available" in t for t in option_texts), (
            f"expected 'No files available' placeholder, got options: {option_texts!r}"
        )

    def test_typing_into_bas_path_is_not_clobbered_by_reactive_effect(
        self, pw_page, live_server,
    ):
        """Spec test 10: reactive.isolate guard regression.

        Without reactive.isolate(), typing into bas_path would re-fire
        _on_project_changed every keystroke. The isolate + empty-guard
        together must let the typed value survive.
        """
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(800)

        bas_input = pw_page.locator('#partitioning-bas_path')
        bas_input.wait_for(state="attached", timeout=5000)
        bas_input.fill("/tmp/manual-typed.bas")
        pw_page.wait_for_timeout(800)

        actual = bas_input.input_value()
        assert actual == "/tmp/manual-typed.bas", (
            f"bas_path was clobbered by a re-fired reactive effect: {actual!r}"
        )

    def test_empty_guard_preserves_user_input_across_navigation(
        self, pw_page, live_server,
    ):
        """Spec test 9: empty-guard regression.

        After typing a value into bas_path, set active_project to a
        project with bas_file. The empty-guard inside _on_project_changed
        must protect the user's input from being clobbered.
        """
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(800)

        bas_input = pw_page.locator('#partitioning-bas_path')
        bas_input.fill("/tmp/preset-value.bas")
        pw_page.wait_for_timeout(300)

        # Set active_project via the test app's debug hook
        result = pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project !== 'function') {
                return 'no-hook';
            }
            window.__test_set_active_project({
                id: 1, name: 'p',
                work_dir: '/tmp/p',
                description: null,
                grids: [{name: 'g', grd_file: 'g.grd', bas_file: 'g.bas'}],
                simulations: [],
                files: [],
            });
            return 'set';
        }""")
        if result == "no-hook":
            pytest.skip(
                "test_app.py does not expose __test_set_active_project; "
                "empty-guard regression cannot be exercised."
            )
        pw_page.wait_for_timeout(800)

        actual = bas_input.input_value()
        assert actual == "/tmp/preset-value.bas", (
            f"empty-guard failed; bas_path was overwritten to {actual!r}"
        )

    def test_picker_callback_silent_on_no_project(
        self, pw_page, live_server,
    ):
        """Spec test 11(c): _fill_bas with no project returns silently.

        Use Shiny.setInputValue (not native change event) because
        Selectize.js hides the native <select> and swallows native
        change events on the hidden element. Routing through Shiny's
        input pipeline reliably fires @reactive.event(input.file_select).
        """
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(800)

        bas_input = pw_page.locator('#partitioning-bas_path')
        bas_input.wait_for(state="attached", timeout=5000)

        # Reset bas_path to empty so this test is independent of others
        bas_input.fill("")
        pw_page.wait_for_timeout(300)

        # Reset active_project to None (the wrapper's no-project branch)
        pw_page.evaluate("""() => {
            if (typeof window.__test_set_active_project === 'function') {
                window.__test_set_active_project(null);
            }
        }""")
        pw_page.wait_for_timeout(500)

        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'partitioning-fp_bas-file_select', '',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(500)

        # bas_path stays empty; no notification toast appeared
        assert bas_input.input_value() == ""
        notifications = pw_page.locator('.shiny-notification').count()
        assert notifications == 0, (
            f"expected 0 notifications, found {notifications}"
        )

    def test_picker_callback_warns_on_traversal(
        self, pw_page, live_server,
    ):
        """Spec test 11(b): _fill_bas with active project + traversal
        rel_path triggers logger.warning + ui.notification_show.
        """
        pw_page.locator(".sf-nav-item[data-nav='Partitioning']").click(force=True)
        pw_page.wait_for_timeout(800)

        # Seed active_project via the test app's debug hook
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
            pytest.skip(
                "test_app.py does not expose __test_set_active_project; "
                "wrapper traversal-failure branch cannot be exercised."
            )
        pw_page.wait_for_timeout(500)

        # Send a traversal rel_path through Shiny's input pipeline
        pw_page.evaluate("""() => {
            Shiny.setInputValue(
                'partitioning-fp_bas-file_select', '/etc/passwd',
                {priority: 'event'}
            );
        }""")
        pw_page.wait_for_timeout(800)

        # The user-visible side-effect -- toast notification -- confirms
        # the wrapper's traversal branch fired.
        notifications = pw_page.locator('.shiny-notification')
        count = notifications.count()
        assert count >= 1, (
            f"expected >= 1 .shiny-notification toast, found {count}"
        )
        warning_toasts = pw_page.locator(
            '.shiny-notification.shiny-notification-warning'
        ).count()
        assert warning_toasts >= 1, (
            f"expected at least 1 warning-class notification, "
            f"found {warning_toasts}"
        )

        # bas_path was NOT updated -- the wrapper short-circuited
        bas_input = pw_page.locator('#partitioning-bas_path')
        assert bas_input.input_value() == "", (
            f"expected bas_path empty (wrapper rejected the selection), "
            f"got {bas_input.input_value()!r}"
        )
