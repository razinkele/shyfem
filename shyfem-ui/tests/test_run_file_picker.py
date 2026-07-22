"""Unit tests for run page file-picker UI rendering and wiring.

NOTE: the browser test app (_test_app.py) now mounts the REAL run_server;
the old _stub_run_server workaround (event-loop deadlock in run_server's
poll effects, tracked as Section M.1) is gone — the deadlock was fixed in
run.py by deduplicating reactive writes in _update_job_lists. Playwright
coverage of the picker lives in test_playwright_run_picker.py.
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
        import re

        assert re.search(r'fill_picker_input\(\s*"input_file"', src)
        # Both effects must be isolate-guarded
        isolate_count = src.count("reactive.isolate()")
        assert isolate_count >= 2, (
            f"expected reactive.isolate() in both _on_project_changed "
            f"AND _on_tutorial_context (found {isolate_count})"
        )


class TestRestartWiring:
    """N42: 'Continue from job' must actually be applied to the STR, not
    just recorded in job metadata. Locks that _submit_job calls
    write_restart_str, and that the call sits after both the editor gate and
    the confine_path(working_dir) validation -- i.e. only after every
    access/sandbox guard has already cleared (repo rule: guards fire before
    any disk mutation)."""

    def test_submit_job_calls_write_restart_str(self):
        import shyfem_ui.pages.run as page_mod
        from shyfem_ui.services import run_logic
        from tests._test_helpers import get_server_source

        assert page_mod.write_restart_str is run_logic.write_restart_str

        src = get_server_source(page_mod, "run_server")
        assert "write_restart_str(" in src, (
            "_submit_job must apply the restart selection via write_restart_str "
            "-- otherwise 'Continue from job' is recorded in metadata only and "
            "the run silently starts fresh (N42)"
        )
        # A no-op call (result discarded) would still leave build_job_spec
        # pointed at the original STR -- the derived path must be assigned
        # back to validated_input, the name build_job_spec's args= uses.
        assert "validated_input = write_restart_str(" in src, (
            "write_restart_str's result must be assigned back to "
            "validated_input, or build_job_spec still submits the original "
            "(non-restarted) STR"
        )

    def test_write_restart_str_call_is_ordered_after_guards(self):
        """String-order proxy for the guard-before-mutation rule: the
        write_restart_str call must appear after editor_denied_reason and
        after the working-dir confine_path validation in source order."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        guard_idx = src.index("editor_denied_reason(")
        workdir_confine_idx = src.index("confine_path(working_dir, _usr, for_write=True)")
        restart_idx = src.index("write_restart_str(")

        assert guard_idx < restart_idx, (
            "write_restart_str runs before the editor_denied_reason gate has " "even been checked"
        )
        assert workdir_confine_idx < restart_idx, (
            "write_restart_str must only run after validated_workdir has been "
            "confined (it writes the derived STR into that directory)"
        )

    def test_build_job_spec_still_receives_restart_from_for_metadata(self):
        """The metadata record (restart_file) must be kept alongside the
        actual STR wiring, not replaced by it -- both the audit trail and
        the real behavior must agree."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        assert "restart_from=restart_from or None" in src


class TestRestartAllowlistWiring:
    """N42 IDOR follow-up: restart_from is a client-controlled input value
    that write_restart_str (above) actually opens and folds into the STR
    the SHYFEM worker executes. A crafted WS message can set it to any
    path, bypassing the restart_section dropdown entirely -- it must be
    re-validated server-side against the SAME scoped choice set the
    dropdown was built from, BEFORE write_restart_str ever touches it."""

    def test_submit_job_calls_restart_selection_denied_reason(self):
        import shyfem_ui.pages.run as page_mod
        from shyfem_ui.services import run_logic
        from tests._test_helpers import get_server_source

        assert page_mod.restart_selection_denied_reason is run_logic.restart_selection_denied_reason

        src = get_server_source(page_mod, "run_server")
        assert "restart_selection_denied_reason(" in src, (
            "_submit_job must re-validate restart_from against a server-"
            "recomputed allowlist -- otherwise a spoofed WS value bypasses "
            "the restart_section dropdown entirely (IDOR)"
        )

    def test_allowlist_check_precedes_write_restart_str(self):
        """The allowlist verdict must be consumed (checked + returned-on-
        deny) before write_restart_str runs, or a denied restart_from would
        still get opened and folded into the submitted STR."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        denied_idx = src.index("restart_selection_denied_reason(")
        write_idx = src.index("write_restart_str(")

        assert denied_idx < write_idx, (
            "restart_selection_denied_reason must be checked before "
            "write_restart_str opens the (possibly spoofed) restart_from path"
        )

    def test_allowlist_denial_is_enforced_with_a_return(self):
        """The denial result must actually short-circuit the handler, not
        just be computed and discarded."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        assert "if _restart_denied:" in src
        # The guarded block must return before falling through.
        guard_pos = src.index("if _restart_denied:")
        guard_block = src[guard_pos : guard_pos + 200]
        assert "return" in guard_block

    def test_allowlist_is_recomputed_server_side_not_reused_from_stale_cache(self):
        """The allowlist must come from a fresh, server-side job query
        (_list_scoped_jobs), not the reactive all_jobs_data cache the
        dropdown itself renders from -- the whole point is not to trust
        client-observable/cacheable state for a security decision."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        assert "_allowed_jobs = await _list_scoped_jobs()" in src

    def test_restart_section_and_submit_job_share_compute_restart_choices(self):
        """Locks that the dropdown (restart_section) and the server-side
        validation (restart_selection_denied_reason) are built from the
        SAME compute_restart_choices function, so they can never silently
        drift apart and reopen the bypass."""
        import shyfem_ui.pages.run as page_mod
        from shyfem_ui.services import run_logic
        from tests._test_helpers import get_server_source

        assert page_mod.compute_restart_choices is run_logic.compute_restart_choices

        src = get_server_source(page_mod, "run_server")
        assert "compute_restart_choices(" in src

    def test_list_scoped_jobs_shared_by_refresh_and_restart_check(self):
        """_refresh_jobs and _submit_job's allowlist check must use the
        SAME scoping function (_list_scoped_jobs), not two independently
        maintained copies of the non-admin/admin/local-mode scoping rules
        that could drift apart."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        assert src.count("await _list_scoped_jobs()") >= 2


class TestRestartInfoAllowlistWiring:
    """Final security review, Finding 2: restart_info previously did a raw
    Path(input.restart_from()).exists()/.stat() with no allowlist -- a
    filesystem-wide existence/size oracle over anything the shiny process
    can stat. It must gate on restart_info_text (which itself gates on
    restart_selection_denied_reason) before touching the filesystem, using
    the SAME server-recomputed scoped jobs list as the submit-path guard."""

    def test_restart_info_is_async(self):
        """restart_info must await _list_scoped_jobs() for a fresh,
        server-side scoped jobs list -- it cannot be a sync render."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        assert "async def restart_info(" in src

    def test_restart_info_calls_restart_info_text(self):
        import shyfem_ui.pages.run as page_mod
        from shyfem_ui.services import run_logic
        from tests._test_helpers import get_server_source

        assert page_mod.restart_info_text is run_logic.restart_info_text

        src = get_server_source(page_mod, "run_server")
        # Isolate restart_info's own body (up to the next top-level def) so
        # this doesn't just match write_restart_str's unrelated usage
        # elsewhere in the module.
        start = src.index("async def restart_info(")
        end = src.index("\n    @", start)
        body = src[start:end]

        assert "restart_info_text(" in body
        assert "await _list_scoped_jobs()" in body

    def test_restart_info_does_not_call_path_exists_directly(self):
        """The raw Path(...).exists()/.stat() calls must be gone from
        restart_info's own body -- that logic now lives behind the
        allowlist gate inside restart_info_text."""
        import shyfem_ui.pages.run as page_mod
        from tests._test_helpers import get_server_source

        src = get_server_source(page_mod, "run_server")
        start = src.index("async def restart_info(")
        end = src.index("\n    @", start)
        body = src[start:end]

        assert ".exists()" not in body
        assert ".stat()" not in body
