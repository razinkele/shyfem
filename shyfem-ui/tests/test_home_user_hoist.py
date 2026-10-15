"""The Dashboard's project-list renders resolve the current user ONCE per
render, not once (or twice) per project row.

``current_user()`` is cheap today (a reactive read), but it is the
server-validated identity accessor and may grow per-call re-validation (DB
SELECTs); calling it inside the per-row loop multiplies that cost by the
number of projects for no behavioural gain -- every row of one render must
see the same user anyway.

Source inspection is the established pattern for @module.server internals in
this codebase (tests/_test_helpers.get_server_source; driving run_server
deadlocks under pytest).
"""

import pytest

import shyfem_ui.pages.home as home_page
from tests._test_helpers import get_server_source


def _function_body(src: str, header: str) -> str:
    start = src.index(header)
    end = src.find("\n    @", start)
    return src[start : end if end != -1 else None]


def _loop_body(fn_src: str) -> str:
    start = fn_src.index("for p in project_data:")
    end = fn_src.find("\n        m = ui.modal(", start)
    if end == -1:
        end = fn_src.index("\n        return ui.tags.table(", start)
    return fn_src[start:end]


@pytest.mark.parametrize("header", ["def projects_list():", "def _show_open_project_modal():"])
def test_current_user_resolved_once_per_render_not_per_row(header):
    src = get_server_source(home_page, "home_server")
    fn = _function_body(src, header)
    loop = _loop_body(fn)

    assert "_user()" not in loop, f"{header} calls _user() inside its per-project loop"
    assert fn.count("_user()") == 1, f"{header} must resolve the user exactly once per render"
