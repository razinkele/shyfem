"""E2E on the REAL app: a job that ends raises the cross-page toast, by push.

The cross-page "job ended" toast is wired in ``app._build_server``, which the
local E2E app (``tests/_test_app.py``) does not use, so no browser test had
covered it. The server-mode app (``tests/_test_auth_app.py``) is the real
``create_app()``, logged in as admin, with the local job queue: push mode, and
server-mode scoping (only the user's own jobs are announced).

The job is built to end at once in any environment (``shypre`` handed an STR
file stops on "error reading grd file"; in CI the tool is missing). The toast is
the only pushed signal checked here; no page is refreshed.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e]

_MODAL = ".modal.show"
_PROJECT = "ToastProject"


def _switch_tab(page, name):
    page.locator(f".sf-nav-item[data-nav='{name}']").click(force=True)
    page.wait_for_timeout(800)


def _user_root(auth_proc) -> Path:
    args = list(auth_proc.args)
    return Path(args[args.index("--workdir") + 1]) / "user_data" / "admin"


def test_a_finished_job_raises_the_toast_on_the_real_app(pw_auth_page, _auth_app_server):
    page = pw_auth_page
    root = _user_root(_auth_app_server)
    before = {p.name for p in root.iterdir()} if root.exists() else set()

    _switch_tab(page, "Dashboard")
    page.locator("#home-new_project_btn").click(force=True)
    page.locator(_MODAL).wait_for(state="visible", timeout=10000)
    page.locator("#home-project_name").fill(_PROJECT)
    page.wait_for_function(
        "(v) => window.Shiny && Shiny.shinyapp && Shiny.shinyapp.$inputValues"
        " && Shiny.shinyapp.$inputValues['home-project_name'] === v",
        arg=_PROJECT,
        timeout=10000,
    )
    page.locator("#home-create_project_btn").click(force=True)
    expect(page.locator(".shiny-notification").filter(has_text="created")).to_be_visible(
        timeout=15000
    )
    _dismiss_modals(page)

    new = [p for p in root.iterdir() if p.is_dir() and p.name not in before]
    assert len(new) == 1, (sorted(before), sorted(p.name for p in root.iterdir()))
    (new[0] / "toast_probe.str").write_text("$title\n  toast\n  toast_probe\n  nobasin\n$end\n")

    # Open the project from its dashboard link (dispatch: cards can overlay it).
    page.locator("a[id^='home-project_']", has_text=_PROJECT).first.dispatch_event("click")
    page.wait_for_timeout(1500)

    _switch_tab(page, "Run")
    sel = page.locator("select#run-input_file")
    expect(sel.locator("option", has_text="toast_probe.str")).to_have_count(1, timeout=15000)
    sel.select_option(str(new[0] / "toast_probe.str"))
    page.locator("select#run-tool_select").select_option("shypre")
    page.locator("input#run-job_name").fill("toast_probe_job")
    page.locator("#run-submit_btn").click()

    toast = page.locator(".shiny-notification").filter(has_text="toast_probe_job")
    expect(toast.first).to_be_visible(timeout=30000)
    expect(toast.first).to_contain_text("failed")
