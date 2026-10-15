"""Wiring for the Run page's workflow history scoping.

The workflow history listed every user's workflows (IDs and names) to
everyone: create_workflow recorded no owner and wf_history called
list_workflows() unscoped. The scoping rules are covered behaviourally by
tests/test_run_logic.py::TestListScopedWorkflows; these pin that the Run
page actually goes through them (source inspection -- the established
pattern for @module.server functions, see tests/_test_helpers).
"""

import shyfem_ui.pages.run as run_page
from tests._test_helpers import get_server_source


def _block(src: str, start_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index("\n    @", start + 1)
    return src[start:end]


def test_history_lists_through_the_scoping_helper():
    src = get_server_source(run_page, "run_server")
    body = _block(src, "def wf_history(")
    assert "list_scoped_workflows(" in body
    assert "workflow_engine.list_workflows(" not in body


def test_launch_records_the_owner_and_project():
    src = get_server_source(run_page, "run_server")
    start = src.index("workflow_engine.create_workflow(")
    call = src[start : src.index(")\n", start)]
    assert 'user_id=_usr["id"]' in call
    assert "project_id=" in call
