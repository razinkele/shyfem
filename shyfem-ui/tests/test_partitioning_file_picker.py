"""Unit tests for partitioning page file-picker UI rendering.

Only contains tests that don't need a Shiny session. Session-driven
tests (wiring, reactive effects, wrapper branches) live in
tests/test_playwright_partitioning_picker.py because @module.server
in shiny 1.5.1 cannot be invoked outside an active session
(verified -- no shiny.testing module exists in this version).
"""


class TestPickerUiRenders:
    def test_picker_ui_renders_for_bas_and_grd(self):
        """Test 6: the picker <select>s appear above the text inputs.

        Renders partitioning_ui('test') (the namespace argument is
        required -- partitioning_ui is decorated with @module.ui).
        Asserts exactly one <select id='test-fp_bas-...'> and one
        <select id='test-fp_grd-...'> appear, AND that each precedes
        the corresponding text-input id in the rendered HTML.
        """
        from shyfem_ui.pages.partitioning import partitioning_ui

        tag = partitioning_ui("test")
        html = str(tag)

        # Picker selects exist, namespaced under the module ID
        assert 'id="test-fp_bas-file_select"' in html, (
            "expected picker <select id='test-fp_bas-file_select'>"
        )
        assert 'id="test-fp_grd-file_select"' in html, (
            "expected picker <select id='test-fp_grd-file_select'>"
        )

        # bas picker appears before bas_path text input
        bas_picker_pos = html.find('id="test-fp_bas-file_select"')
        bas_input_pos = html.find('id="test-bas_path"')
        assert bas_picker_pos != -1 and bas_input_pos != -1
        assert bas_picker_pos < bas_input_pos, (
            "fp_bas picker must render before bas_path text input"
        )

        # grd picker appears before grd_path text input
        grd_picker_pos = html.find('id="test-fp_grd-file_select"')
        grd_input_pos = html.find('id="test-grd_path"')
        assert grd_picker_pos != -1 and grd_input_pos != -1
        assert grd_picker_pos < grd_input_pos, (
            "fp_grd picker must render before grd_path text input"
        )


class TestModuleImports:
    """Defensive guard + wiring assertion for the file picker integration.

    `hasattr(part_mod, 'file_picker_server')` alone is too weak -- it
    passes if the symbol is rebound to None, aliased internally, or
    even left unused. The Playwright tests would silently pass too
    (they just check dropdown contents). This test verifies BOTH:
    (a) the symbol on the page module is the same callable from the
        component module (no aliasing / shadowing);
    (b) `partitioning_server`'s source actually CALLS file_picker_server
        twice with the right `file_types` filters -- equivalent to spec
        test 7's wiring assertion, just done via source inspection
        since shiny 1.5.1 has no in-process @module.server invocation.
    """

    def test_partitioning_imports_and_wires_file_picker_server(self):
        import shyfem_ui.pages.partitioning as part_mod
        from shyfem_ui.components import file_picker as fp_mod
        from tests._test_helpers import get_server_source

        # Identity check -- the page's symbol IS the component's function
        assert hasattr(part_mod, "file_picker_server"), (
            "partitioning.py must do `from ...file_picker import "
            "file_picker_server` (no aliasing, no deferred import)"
        )
        assert part_mod.file_picker_server is fp_mod.file_picker_server, (
            "partitioning.file_picker_server must be the SAME object as "
            "components.file_picker.file_picker_server (no shadowing)"
        )
        assert hasattr(part_mod, "file_picker_ui")

        # Wiring assertion -- partitioning_server source contains the
        # right two file_picker_server calls with the right file_types.
        # `@module.server` wraps the function in a session-scoping
        # closure, so we use the shared get_server_source helper to
        # unwrap and read the inner function's source.
        src = get_server_source(part_mod, "partitioning_server")
        assert src.count("file_picker_server(") >= 2, (
            "expected at least 2 file_picker_server calls "
            "(fp_bas + fp_grd) in partitioning_server"
        )
        assert 'file_types=["basin"]' in src, (
            "expected file_types=['basin'] for the .bas picker"
        )
        assert 'file_types=["grid"]' in src, (
            "expected file_types=['grid'] for the .grd picker"
        )

        # After Section M extraction: per-page wrappers are gone; the
        # page now delegates via lambdas to the shared
        # fill_picker_input helper.
        assert hasattr(part_mod, "fill_picker_input"), (
            "partitioning.py must do `from ...file_picker import "
            "fill_picker_input`"
        )
        assert part_mod.fill_picker_input is fp_mod.fill_picker_input, (
            "partitioning.fill_picker_input must be the SAME object as "
            "components.file_picker.fill_picker_input"
        )
        assert "fill_picker_input(" in src, (
            "partitioning_server must call fill_picker_input(...) "
            "in its on_selected= lambdas"
        )
