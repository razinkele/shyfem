"""E2E: a job's end reaches the Run page by push, with no refresh.

The local job queue publishes every status change and each session is woken
through Shiny 1.9's ``run_once_when_idle`` (``components/job_feed.py``). Until
this test nothing exercised that path through a real browser: the unit tests
stub the session, and no E2E submitted a job. (The cross-page toast lives in
``app._build_server``, which the E2E app does not use, so it is not checked
here; the Run page's own feed is.)

The job is built to end at once whatever the environment: ``shypre`` handed an
STR file is not a grid, and where no SHYFEM binary is built (CI) the tool is
missing; either way the job ends FAILED within seconds. No Refresh button is
clicked: only a pushed event can update the history table and raise the toast.

Named to sort after test_playwright_run_picker.py; it leaves the Run page open.
"""

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]


def _set_project(pw_page, work_dir) -> None:
    result = pw_page.evaluate(
        """(wd) => {
            if (typeof window.__test_set_active_project !== 'function') return 'no-hook';
            window.__test_set_active_project({
                id: 1, name: 'p', work_dir: wd, description: null,
                grids: [], simulations: [], files: [],
            });
            return 'set';
        }""",
        str(work_dir),
    )
    if result == "no-hook":
        pytest.skip("test_app.py does not expose __test_set_active_project")


def test_a_finished_job_reaches_the_history_without_refresh(pw_page, tmp_path):
    (tmp_path / "push_probe.str").write_text(
        "$title\n  push probe\n  push_probe\n  nobasin\n$end\n"
    )
    _set_project(pw_page, tmp_path)
    pw_page.locator(".sf-nav-item[data-nav='Run']").click(force=True)

    sel = pw_page.locator("select#run-input_file")
    expect(sel).to_be_attached(timeout=10000)
    expect(sel.locator("option", has_text="push_probe.str")).to_have_count(1, timeout=10000)
    sel.select_option(str(tmp_path / "push_probe.str"))
    pw_page.locator("select#run-tool_select").select_option("shypre")
    pw_page.locator("input#run-job_name").fill("push_probe_job")
    pw_page.locator("#run-submit_btn").click()

    # Open the Job History tab first: a hidden output is suspended by Shiny
    # (shown as "recalculating") and only recomputes once visible.
    pw_page.locator("a[role='tab']:has-text('Job History')").click()
    # Pushed: the history row appears without any Refresh click (the Run page
    # has no poll when the queue publishes events). 30 s covers a slow CI
    # runner; the push itself is sub-second once the tool exits.
    history = pw_page.locator("#run-job_history")
    expect(history).to_contain_text("push_probe_job", timeout=30000)
    expect(history).to_contain_text("failed", ignore_case=True)
