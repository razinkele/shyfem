"""The Run page showed no progress and an unreadable log (2026-10-26).

* R-05: shyfem prints one line per time step, ``<date> <seconds> <dt>
  <it> / <nits> <pct> %``; the parser looked for an invented
  ``time = X of Y`` and never matched, so progress sat at 0 % until the end.
* R-04: ``LocalJobQueue.list_jobs`` handed out the live ``JobInfo`` objects
  the runner mutates, so the page's compare-before-set compared each job with
  itself and never pushed a change (status, progress, history all frozen).
* J-07: once the list refreshes, the "Continue from job" select must keep the
  user's pick instead of snapping back to "Fresh start" every poll.
* Log colours: Bootstrap gives ``<pre>`` the emphasis colour (black in the
  light theme), so plain log lines were black on the viewer's #1e1e1e.
"""

import asyncio
import inspect
from datetime import datetime

import pytest

from shyfem_ui.services.job_queue import JobInfo, JobStatus
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

# Verbatim from a production run (Curonian 29-box, 1993-01, 8928 steps).
REAL_STEP = " 1993-01-02::04:10:00        101400.00   300       338 /      8928     3.786 %"
REAL_FIRST = " 1993-01-01::00:00:00             0.00   300         0 /      8928     0.000 %"
REAL_LAST = " 1993-01-31::23:55:00       2678100.00   300      8927 /      8928    99.989 %"


@pytest.fixture
def wrapper(tmp_path):
    return ShyfemWrapper(tmp_path)


def test_shyfem_progress_is_read_from_the_real_step_line(wrapper):
    assert wrapper._parse_progress("shyfem", REAL_STEP) == pytest.approx(338 / 8928)
    assert wrapper._parse_progress("shyfem", REAL_FIRST) == pytest.approx(0.0)
    assert wrapper._parse_progress("shyfem", REAL_LAST) == pytest.approx(8927 / 8928)


@pytest.mark.parametrize(
    "line",
    [
        "      time step  =      300.000000    ",
        " opening wind file...",
        " simulation end:     2026-10-26::17:33:06",
        " Number of non-zeros 2d:         7993       10472",
        "",
    ],
)
def test_other_shyfem_lines_are_not_progress(wrapper, line):
    assert wrapper._parse_progress("shyfem", line) is None


def _queue(tmp_path):
    from shyfem_ui.services.job_local import LocalJobQueue

    q = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)

    async def _loaded():
        return None

    q._ensure_history_loaded = _loaded
    job = JobInfo(
        id="j1",
        name="run",
        tool_name="shyfem",
        args=[],
        working_dir=str(tmp_path),
        status=JobStatus.RUNNING,
        created_at=datetime.now(),
        metadata={"user_id": 8},
    )
    q._jobs[job.id] = job
    return q, job


def test_listed_jobs_are_snapshots_so_a_change_is_visible(tmp_path):
    q, live = _queue(tmp_path)
    before = asyncio.run(q.list_jobs())
    live.progress = 0.5
    live.status = JobStatus.COMPLETED
    after = asyncio.run(q.list_jobs())
    assert before[0] is not live
    assert before[0].progress == 0.0 and before[0].status == JobStatus.RUNNING
    assert before != after, "the page compares these lists; a change must show"


def test_get_status_is_a_snapshot_too(tmp_path):
    q, live = _queue(tmp_path)
    snap = asyncio.run(q.get_status("j1"))
    live.progress = 0.7
    live.metadata["x"] = 1
    assert snap is not live and snap.progress == 0.0 and "x" not in snap.metadata
    assert asyncio.run(q.get_status("j1")).progress == 0.7
    assert asyncio.run(q.get_status("missing")) is None


def test_log_pre_inherits_the_viewer_colours():
    from shyfem_ui.components import log_viewer

    src = inspect.getsource(log_viewer)
    body = src[src.index("def _render_lines") : src.index("@render.ui")]
    pres = body.count("ui.pre(")
    assert pres == 2
    assert body.count("color: inherit") + body.count("color: #808080") >= pres
    assert body.count("background: transparent") == pres, "Bootstrap tints <pre> too"
    assert "color: inherit" in body.split("ui.HTML(")[1], "the log text itself must inherit"


def test_restart_select_keeps_the_users_pick_across_refreshes():
    from shyfem_ui.pages import run

    src = inspect.getsource(run)
    body = src[src.index("def restart_section") : src.index("def restart_info")]
    assert "selected=" in body, "a rebuilt select without selected= resets the pick"
    assert (
        "all_jobs_data.get()" not in body
    ), "depend on the restart choices only, not on every job progress tick"
    upd = src[src.index("def _update_job_lists") : src.index("def _submit_job")]
    assert "compute_restart_choices(" in upd and "restart_choices.set(" in upd
