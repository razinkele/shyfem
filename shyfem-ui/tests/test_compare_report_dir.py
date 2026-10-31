"""V-08: the Compare page's "Generate Comparison Report" wrote the HTML into
the shared ``config.work_dir``. In server mode that is outside every user's
home, so the owner could not reach the report, and every user's reports
landed in the same folder. The report now goes in the active project's
folder; only local mode (no project, single user) falls back to the work
dir."""

from pathlib import Path

import shyfem_ui.pages.compare as compare_page
from tests._test_helpers import get_server_source


def test_report_goes_in_the_active_project_folder(tmp_path):
    proj = {"id": 3, "name": "P", "work_dir": str(tmp_path / "users" / "alice" / "p")}
    out = compare_page._comparison_report_dir(proj, tmp_path / "work")
    assert out == Path(proj["work_dir"])


def test_no_project_falls_back_to_the_work_dir(tmp_path):
    assert compare_page._comparison_report_dir(None, tmp_path / "work") == tmp_path / "work"


def test_handler_does_not_write_into_the_shared_work_dir():
    src = get_server_source(compare_page, "compare_server")
    start = src.index("def _generate_comparison_report(")
    end = src.index("\n    return {}", start)
    body = src[start:end]
    assert "Path(config.work_dir)" not in body, "report still written to the shared work_dir"
    assert "_comparison_report_dir(" in body
    assert "asyncio.to_thread(" in body, "the report is written on the event loop"
