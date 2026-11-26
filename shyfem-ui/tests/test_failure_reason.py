"""#335: a run that exited non-zero shows its ``error stop`` line as the reason.

Since #331 and #332 the tools and the model end many errors with exit status
7 (``mod_error_stop``) or 33 (``shympi_abort_internal``) and print
``error stop ROUTINE: TEXT`` to **stdout**; stderr is empty or only the
MPI_ABORT banner. Every consumer showed ``result.stderr``: an empty reason,
"Unknown error", or the banner. The fixtures are the real output of the
cf7ec26b binaries (``tests/fixtures/tool_stdout/<case>.{stdout,stderr,exit}``).
"""

import asyncio
import shlex
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from shyfem_ui.services.lgr_service import LgrService
from shyfem_ui.services.shyfem_wrapper import (
    CommandResult,
    ShyfemWrapper,
    failed_run_text,
    failure_reason,
    tool_failure,
)

FIX = Path(__file__).parent / "fixtures" / "tool_stdout"

# case -> (exit status, expected reason)
CASES = {
    "tool_exit7_option": (7, "error stop clo_parse_options: no such option: -bogus"),
    "tool_exit7_missing": (7, "error stop rst_info: cannot open rst file"),
    "model_exit33_serial": (33, "error stop convert_date_d: cannot parse itanf"),
    "model_exit33_np2": (33, "error stop convert_date_d: cannot parse itanf"),
    # mpirun turns the bare stop into exit 1; the line is on stderr, among the banner
    "model_exit1_stop_np2": (1, "STOP error stop date2j: day"),
    # shympi_abort_internal with a message that has no "error stop" prefix (#338):
    # rstinf on a truncated restart file; stderr is empty
    "tool_exit33_noprefix": (33, "restart: truncated/failed read of date/time"),
}


def _case(name: str) -> tuple[int, str, str]:
    code = int((FIX / f"{name}.exit").read_text())
    return code, (FIX / f"{name}.stdout").read_text(), (FIX / f"{name}.stderr").read_text()


@pytest.mark.parametrize("name", CASES)
def test_reason_of_each_captured_case(name):
    code, stdout, stderr = _case(name)
    assert code == CASES[name][0]
    assert failure_reason(stdout, stderr) == CASES[name][1]


def test_the_banner_is_never_the_reason():
    _, stdout, stderr = _case("model_exit33_np2")
    assert "MPI_ABORT" in stderr
    assert "MPI_ABORT" not in failure_reason(stdout, stderr)


def test_stdout_line_wins_over_a_stderr_line():
    assert failure_reason("error stop a: out\n", "STOP error stop b: err\n") == "error stop a: out"


def test_the_last_stdout_line_wins():
    assert failure_reason("error stop a: 1\nerror stop b: 2\n", "") == "error stop b: 2"


def test_gfortran_error_stop_forms():
    assert failure_reason("", "ERROR STOP bad thing\n") == "ERROR STOP bad thing"
    assert failure_reason("", "STOP error stop x: y\n") == "STOP error stop x: y"


def test_a_specific_line_beats_a_usage_stop():
    out = " *** no such option: -x\n Usage: shyparts [-h]\n"
    assert failure_reason(out, "STOP clo_usage: usage displayed\n") == "*** no such option: -x"
    # only the usage stop: it is still better than nothing
    assert failure_reason("", "STOP clo_usage: usage displayed\n") == (
        "STOP clo_usage: usage displayed"
    )


def test_no_prefix_abort_takes_the_last_stdout_line_when_stderr_is_only_the_banner():
    _, stdout, _ = _case("tool_exit33_noprefix")
    for banner in ("model_exit33_serial", "model_exit33_np2", "model_exit1_stop_np2"):
        _, _, stderr = _case(banner)
        stderr = stderr.replace("STOP error stop date2j: day\n", "")
        assert failure_reason(stdout, stderr) == "restart: truncated/failed read of date/time"
    host_only = "[laguna:551613] 1 more process has sent help message help-mpi-api.txt\n"
    assert failure_reason(stdout, host_only) == "restart: truncated/failed read of date/time"


def test_other_stderr_keeps_the_stderr_fallback():
    _, stdout, _ = _case("tool_exit33_noprefix")
    assert failure_reason(stdout, "Segmentation fault\n") is None
    _, _, banner = _case("model_exit33_np2")
    assert failure_reason(stdout, banner + "Backtrace for this error:\n") is None


def test_no_line_means_no_reason():
    assert failure_reason("step 1\nstep 2\n", "Segmentation fault\n") is None
    assert failure_reason("", "") is None


def test_failure_text_falls_back_to_stderr_then_unknown():
    def res(stderr, reason=""):
        return CommandResult(False, 1, "", stderr, "x", ".", reason=reason)

    assert res("banner", "error stop a: b").failure_text() == "error stop a: b"
    assert res("Segmentation fault\n").failure_text() == "Segmentation fault"
    assert res("").failure_text() == "Unknown error"
    assert res("", "error stop " + "x" * 50).failure_text(20) == "error stop xxxxxxxxx"


# --- verdicts do not change ---------------------------------------------------


def test_an_exit_0_run_printing_a_bare_error_stop_line_keeps_its_verdict():
    # A model log may quote such a line and still end well: only the exit 0
    # branch's patterns (_FATAL_LINE) judge it, and the bare form is not one.
    footer = " simulation end:     2026-07-21::22:08:44\n"
    assert tool_failure("shyfem", 0, "error stop x: quoted\n" + footer, "") is None
    assert tool_failure("shyelab", 0, "error stop x: quoted\n", "") is None
    # ... and the real captured exit-0 stop is still a failure, with its old text
    _, stdout, stderr = _case("tool_exit0_stop")
    assert tool_failure("shypre", 0, stdout, stderr) == (
        "Stopped on an error (exit status 0): STOP error stop grd_internal_init: cannot open file"
    )
    _, stdout, stderr = _case("model_exit0_stop_serial")
    assert tool_failure("shyfem", 0, stdout, stderr) == (
        "Stopped on an error (exit status 0): STOP error stop date2j: day"
    )


def test_a_nonzero_exit_is_still_left_to_the_exit_status():
    assert tool_failure("shyfem", 7, "error stop a: b\n", "") is None


# --- through the real wrapper ---------------------------------------------------


@pytest.fixture
def wrapper(tmp_path):
    d = tmp_path / "shyfem"
    (d / "bin").mkdir(parents=True)
    return ShyfemWrapper(d)


def _tool(wrapper: ShyfemWrapper, name: str, body: str) -> None:
    exe = wrapper.bin_dir / name
    exe.write_text("#!/bin/bash\n" + body)
    exe.chmod(0o755)


def _replay(wrapper: ShyfemWrapper, name: str, case: str) -> None:
    """A tool that prints a captured case's stdout and stderr and exits with its status."""
    code = int((FIX / f"{case}.exit").read_text())
    _tool(
        wrapper,
        name,
        f"cat {shlex.quote(str(FIX / (case + '.stdout')))}\n"
        f"cat {shlex.quote(str(FIX / (case + '.stderr')))} >&2\n"
        f"exit {code}\n",
    )


FAKE = "error stop basin_get_par: not a bas file"


@pytest.mark.asyncio
async def test_fake_tool_from_the_issue(wrapper, tmp_path):
    _tool(wrapper, "shybas", f"echo '{FAKE}'\nexit 7\n")
    result = await wrapper.run_command("shybas", ["x.bas"], tmp_path / "w")
    assert result.success is False and result.return_code == 7
    assert result.stderr == ""  # the line is on stdout only
    assert result.reason == FAKE
    assert result.failure_text() == FAKE


@pytest.mark.asyncio
@pytest.mark.parametrize("capture", [True, False])
async def test_run_command_gives_the_reason_of_each_captured_case(wrapper, tmp_path, capture):
    for case, (code, reason) in CASES.items():
        _replay(wrapper, "shyfem", case)
        result = await wrapper.run_command(
            "shyfem", ["a.str"], tmp_path / "w", capture_stdout=capture
        )
        assert result.return_code == code, case
        assert result.success is False
        assert result.reason == reason, case
        assert result.failure_text() == reason, case


@pytest.mark.asyncio
async def test_a_failure_without_such_a_line_shows_stderr(wrapper, tmp_path):
    _tool(wrapper, "shybas", "echo step\necho 'Segmentation fault' >&2\nexit 139\n")
    result = await wrapper.run_command("shybas", ["x.bas"], tmp_path / "w")
    assert result.reason == ""
    assert result.failure_text() == "Segmentation fault"


# --- the consumers ------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["shypre", "shybas"])
async def test_grid_prep_notification_and_log_show_the_reason(wrapper, tmp_path, tool):
    _tool(wrapper, tool, f"echo '{FAKE}'\nexit 7\n")
    result = await wrapper.run_command(tool, ["x.grd"], tmp_path / "w")
    log, notice = failed_run_text(tool, result)
    assert notice == f"{tool} failed (exit code 7): {FAKE}"
    assert FAKE in log
    assert "Unknown error" not in notice


def test_grid_prep_uses_failed_run_text_for_both_tools():
    src = (Path(__file__).parents[1] / "shyfem_ui" / "pages" / "grid_prep.py").read_text()
    assert 'failed_run_text("shypre", result)' in src
    assert 'failed_run_text("shybas", result)' in src
    assert "Unknown error" not in src


@pytest.mark.asyncio
async def test_lgr_service_error_names_the_reason(wrapper, tmp_path):
    _replay(wrapper, "lgrelab", "model_exit33_np2")
    lgr = tmp_path / "a.lgr"
    lgr.touch()
    with pytest.raises(RuntimeError) as exc:
        await LgrService(wrapper).load(lgr)
    assert str(exc.value) == (
        "lgrelab failed (code 33): error stop convert_date_d: cannot parse itanf"
    )


def test_lgr_service_with_a_bare_result_keeps_stderr(tmp_path):
    lgr = tmp_path / "a.lgr"
    lgr.touch()
    mock = MagicMock()
    mock.run_command = AsyncMock(
        return_value=CommandResult(False, 1, "", "lgrelab error: bad file", "lgrelab", ".")
    )
    with pytest.raises(RuntimeError, match="lgrelab failed .code 1.: lgrelab error: bad file"):
        asyncio.run(LgrService(mock).load(lgr))


# --- detached runs (watch_detached, job_runner, the queue) ------------------------


@pytest.fixture
def db(tmp_path, monkeypatch):
    import shyfem_ui.config as cfg
    import shyfem_ui.db.base as dbb

    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", f"sqlite:///{tmp_path / 'jobs.db'}")
    monkeypatch.setattr(cfg, "_config", None)
    monkeypatch.setattr(dbb, "_engine", None)
    monkeypatch.setattr(dbb, "_SessionLocal", None)
    dbb.init_db()
    yield
    monkeypatch.setattr(dbb, "_engine", None)
    monkeypatch.setattr(dbb, "_SessionLocal", None)
    monkeypatch.setattr(cfg, "_config", None)


@pytest.mark.asyncio
async def test_watch_detached_reports_the_reason(tmp_path):
    from shyfem_ui.services.job_detached import JobFiles, write_json_atomic
    from shyfem_ui.services.shyfem_wrapper import DetachedRun

    code, stdout, stderr = _case("model_exit33_np2")
    work = tmp_path / "work"
    work.mkdir()
    job_id = "21111111-2222-3333-4444-555555555555"
    files = JobFiles.for_stdout(work / f"{job_id}.stdout")
    files.stdout.write_text(stdout)
    files.stderr.write_text(stderr)
    write_json_atomic(files.spec, {"job_id": job_id, "tool_name": "shyfem", "before_snapshot": {}})
    write_json_atomic(files.exit, {"return_code": code, "timed_out": False})
    result = await ShyfemWrapper(tmp_path).watch_detached(
        "shyfem",
        files.stdout,
        DetachedRun(job_id=job_id, stdout_file=str(files.stdout), kill_on_cancel=lambda: False),
        None,
        working_dir=work,
    )
    assert result.success is False and result.return_code == 33
    assert result.reason == "error stop convert_date_d: cannot parse itanf"
    assert result.failure_text() == "error stop convert_date_d: cannot parse itanf"


async def _until(predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


@pytest.mark.asyncio
async def test_queued_job_error_is_the_error_stop_line(db, tmp_path):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Job
    from shyfem_ui.services.job_local import LocalJobQueue
    from shyfem_ui.services.job_queue import JobSpec

    shyfem_dir = tmp_path / "shyfem"
    (shyfem_dir / "bin").mkdir(parents=True)
    _replay(ShyfemWrapper(shyfem_dir), "shypre", "model_exit33_np2")
    queue = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    queue._history_loaded = True
    job_id = await queue.submit(
        JobSpec(name="j", tool_name="shypre", args=[], working_dir=tmp_path / "work")
    )
    job = await _until(lambda: (j := queue._jobs[job_id]) and not j.is_active and j)
    want = "error stop convert_date_d: cannot parse itanf"
    assert job.error_message == want

    def row_error():
        with db_session() as s:
            row = s.query(Job).filter(Job.job_uuid == job_id).one()
            return row.error_message if row.status.value == "failed" else None

    # the supervisor wrote the row itself (job_runner.result_fields)
    assert await _until(row_error) == want


def test_result_fields_without_a_line_keep_the_stderr_tail(tmp_path):
    from shyfem_ui.job_runner import result_fields
    from shyfem_ui.services.job_detached import JobFiles

    files = JobFiles.for_stdout(tmp_path / "j.stdout")
    files.stdout.write_text("step\n")
    files.stderr.write_text("Segmentation fault\n")
    spec = {"tool_name": "shyfem", "cwd": str(tmp_path), "before_snapshot": {}}
    assert result_fields(spec, files, 139, False)["error_message"] == "Segmentation fault"


# --- review round 1: every consumer, the two writers of the job row ------------------

from tests._tool_replay import case as _real_case  # noqa: E402
from tests._tool_replay import make_wrapper, replay  # noqa: E402

WANT33 = "error stop convert_date_d: cannot parse itanf"
WANT_NOPREFIX = "restart: truncated/failed read of date/time"


def _job_files(tmp_path, name):
    from shyfem_ui.services.job_detached import JobFiles

    code, stdout, stderr = _real_case(name)
    files = JobFiles.for_stdout(tmp_path / "j.stdout")
    files.stdout.write_text(stdout)
    files.stderr.write_text(stderr)
    return code, files


@pytest.mark.parametrize(
    "name, want",
    [("model_exit33_np2", WANT33), ("tool_exit33_noprefix", WANT_NOPREFIX)],
)
def test_result_fields_error_message_is_the_reason(tmp_path, name, want):
    """The supervisor's own writer of the job row, with no race with the queue."""
    from shyfem_ui.job_runner import result_fields

    code, files = _job_files(tmp_path, name)
    spec = {"tool_name": "shyfem", "cwd": str(tmp_path), "before_snapshot": {}}
    fields = result_fields(spec, files, code, False)
    assert fields["status"].value == "failed"
    assert fields["error_message"] == want


def test_an_exit_0_failure_keeps_stderr_in_every_writer(tmp_path):
    """tool_failure's line is appended to stderr, not substituted for it."""
    from shyfem_ui.job_runner import result_fields
    from shyfem_ui.services.job_detached import JobFiles

    files = JobFiles.for_stdout(tmp_path / "j.stdout")
    files.stdout.write_text(" reading basin\n")
    files.stderr.write_text("some warning\nSTOP error stop setup_time: dtend\n")
    spec = {"tool_name": "shyfem", "cwd": str(tmp_path), "before_snapshot": {}}
    error = result_fields(spec, files, 0, False)["error_message"]
    assert "some warning" in error and error.endswith("setup_time: dtend")

    result = CommandResult(False, 0, "", "some warning\nline", "x", ".")
    assert result.reason == ""
    assert result.failure_text().startswith("some warning")


@pytest.mark.asyncio
async def test_run_command_exit_0_stop_has_no_reason_but_keeps_stderr(tmp_path):
    w = make_wrapper(tmp_path)
    replay(w, "shypre", "tool_exit0_stop")
    result = await w.run_command("shypre", ["missing.grd"], tmp_path / "w")
    assert result.success is False and result.return_code == 0
    assert result.reason == ""
    assert "STOP error stop grd_internal_init: cannot open file" in result.failure_text()
    assert result.stderr.startswith("STOP error stop grd_internal_init")


def test_partitioning_shows_the_reason_in_its_log():
    import shyfem_ui.pages.partitioning as part_mod
    from tests._test_helpers import get_server_source

    src = get_server_source(part_mod, "partitioning_server")
    assert 'failed_run_text("shyparts", result)[0]' in src
    assert "result.stderr" not in src


@pytest.mark.asyncio
async def test_partitioning_log_text_of_a_failed_shyparts(tmp_path):
    w = make_wrapper(tmp_path)
    replay(w, "shyparts", "model_exit33_np2")
    result = await w.run_command("shyparts", ["-np", "2", "x.grd"], tmp_path / "w")
    log = failed_run_text("shyparts", result)[0]
    assert "*** shyparts failed (code 33) ***" in log
    assert log.rstrip().endswith(WANT33)


def test_celery_worker_records_the_reason_as_the_job_error(tmp_path):
    import json
    from unittest.mock import patch

    from shyfem_ui.services.job_celery import _load_job_info, execute_shyfem_job
    from shyfem_ui.services.job_queue import JobStatus
    from tests.test_job_celery import _DictRedis, _make_job_info, _store_job_info

    code, stdout, stderr = _real_case("model_exit33_np2")
    store = _DictRedis()
    _store_job_info(
        store,
        _make_job_info(
            job_id="j", status=JobStatus.QUEUED, tool_name="shybas", working_dir=str(tmp_path)
        ),
    )
    failed = CommandResult(
        False,
        code,
        "",
        stderr,
        "shybas",
        str(tmp_path),
        reason=failure_reason(stdout, stderr) or "",
    )
    wrapper = MagicMock()
    wrapper.run_command = AsyncMock(return_value=failed)
    with (
        patch("shyfem_ui.services.job_celery._get_redis_client", return_value=store),
        patch("shyfem_ui.services.shyfem_wrapper.ShyfemWrapper", return_value=wrapper),
        patch("shyfem_ui.services.job_celery._persist_job_to_db"),
    ):
        execute_shyfem_job("j", "redis://x", str(tmp_path), hostname="celery@w7")
    info = _load_job_info(store, "j")
    assert info.status == JobStatus.FAILED
    assert info.error_message == WANT33
    assert json.dumps(info.error_message)  # plain text


def test_results_cache_conversion_error_names_the_reason(tmp_path):
    from shyfem_ui.services.results_cache import ConversionError
    from tests.test_results_cache import _cfg, _go, _src

    for name, want in [("model_exit33_np2", WANT33), ("tool_exit33_noprefix", WANT_NOPREFIX)]:
        w = make_wrapper(tmp_path / name)
        replay(w, "shyelab", name)
        with pytest.raises(ConversionError) as e:
            _go(_src(tmp_path), _cfg(tmp_path / name), w)
        assert str(e.value).endswith(f": {want}"), str(e.value)


@pytest.mark.asyncio
async def test_mesh_builder_error_names_the_reason(tmp_path):
    import numpy as np

    from shyfem_ui.services.mesh_builder import interpolate_bathymetry_shybas
    from tests.test_mesh_builder_nonfinite_depth import _square_mesh

    for name, want in [("model_exit33_np2", WANT33), ("tool_exit33_noprefix", WANT_NOPREFIX)]:
        w = make_wrapper(tmp_path / name)
        replay(w, "shybas", name)
        pts = np.array([[0, 0, 1.0], [10, 0, 2.0], [10, 10, 3.0], [0, 10, 4.0], [5, 5, 5.0]])
        with pytest.raises(RuntimeError) as e:
            await interpolate_bathymetry_shybas(_square_mesh(), pts, w)
        assert str(e.value) == f"shybas did not interpolate the bathymetry: {want}"
