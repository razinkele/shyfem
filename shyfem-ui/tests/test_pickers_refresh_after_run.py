"""After a run, its new output files must appear in the Post-process and
Visualize pickers (2026-10-26, georg's Curonian run).

The pickers depended only on the active project and the user, so a picker
built before the run finished kept saying "no files" until a page reload.
The Run page now bumps a shared ``project_files_rev`` when a job leaves the
active set, the pickers read it, and a rebuilt picker keeps the user's pick.

Also: a shyfem build without NetCDF prints "NETCDF support has not been
enabled" for ``shyelab -outformat nc`` and exits 0, so "Convert to NetCDF"
reported success with no file written.
"""

import inspect

from shyfem_ui.services.shyfem_wrapper import tool_failure


def _src(mod):
    return inspect.getsource(mod)


def test_app_shares_one_project_files_rev_with_run_postprocess_and_visualize():
    from shyfem_ui import app

    src = _src(app)
    assert "project_files_rev = reactive.value(0)" in src
    for call in (
        "run.run_server(",
        "postprocess.postprocess_server(",
        "visualize.visualize_server(",
    ):
        body = src[src.index(call) : src.index(")\n", src.index(call))]
        assert "project_files_rev=project_files_rev" in body, call


def test_run_bumps_the_rev_when_a_job_finishes():
    from shyfem_ui.pages import run

    src = _src(run)
    upd = src[src.index("def _update_job_lists") : src.index("def _submit_job")]
    assert "project_files_rev.set(" in upd
    # Keyed on jobs leaving the active set, read without taking a dependency.
    assert "prev_active" in upd and "reactive.isolate()" in upd


def test_postprocess_pickers_follow_the_rev_and_keep_the_pick():
    from shyfem_ui.pages import postprocess

    src = _src(postprocess)
    for name, inp in (
        ("def shy_path_picker", "shy_path"),
        ("def batch_paths_picker", "batch_paths"),
    ):
        body = src[src.index(name) : src.index("@render", src.index(name) + 1)]
        assert "_files_rev()" in body, name
        assert f'selected=_kept("{inp}")' in body, name
    kept = src[src.index("def _kept") : src.index("@render", src.index("def _kept"))]
    assert "reactive.isolate()" in kept, "reading the pick must not make the picker depend on it"


def test_visualize_picker_follows_the_rev_and_keeps_the_pick():
    from shyfem_ui.pages import visualize

    src = _src(visualize)
    body = src[src.index("def _picker_ui") : src.index("def _resolve_selection")]
    assert "project_files_rev.get()" in body
    assert "selected=" in body and 'selected=""' not in body


def test_missing_netcdf_support_is_a_failure_not_a_success():
    out = (
        " NETCDF support has not been enabled\n"
        " Please enable NETCDF support in Rules.make\n"
        ' (set "NETCDF=true")\n'
    )
    why = tool_failure("shyelab", 0, out, "")
    assert why is not None and "NETCDF support has not been enabled" in why
