"""Unit tests for run page file-picker UI rendering and wiring.

NOTE: run.py uses _stub_run_server in tests (search _test_app.py for
_stub_run_server) to work around an event-loop deadlock in run_server's
job-queue effects. The stub mirrors the picker's wiring (project_id_val
+ file_picker_server) so Playwright tests CAN exercise the picker —
see test_playwright_run_picker.py. The deadlock itself remains tracked
as Section M.1 in the followups doc.
"""


class TestPickerUiRenders:
    def test_picker_renders_above_input_file(self):
        from shyfem_ui.pages.run import run_ui

        tag = run_ui("test")
        html = str(tag)

        assert 'id="test-fp_input-file_select"' in html
        picker_pos = html.find('id="test-fp_input-file_select"')
        input_pos = html.find('id="test-input_file"')
        assert picker_pos != -1 and input_pos != -1
        assert picker_pos < input_pos


class TestModuleImports:
    def test_run_wires_file_picker_server(self):
        import shyfem_ui.pages.run as page_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        assert page_mod.file_picker_server is fp_mod.file_picker_server
        assert page_mod.fill_picker_input is fp_mod.fill_picker_input

        src = get_server_source(page_mod, "run_server")
        assert src.count("file_picker_server(") >= 1
        assert 'file_types=["str"]' in src
        assert 'fill_picker_input("input_file"' in src
        # Both effects must be isolate-guarded
        isolate_count = src.count("reactive.isolate()")
        assert isolate_count >= 2, (
            f"expected reactive.isolate() in both _on_project_changed "
            f"AND _on_tutorial_context (found {isolate_count})"
        )
