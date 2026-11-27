"""``extra_dirs`` read back from a job's launch record stays in the working folder.

#352 made a ``shypre`` job also list the ``.bas`` next to its input grid, and
stored that folder in the launch record. Every reader of the record (the
watcher, the supervisor's finalize, the reconcile of a job that ended with no
worker watching) must filter it against the TRUSTED working folder (the job
row's, never the record's own ``cwd``): the user can write a job's directory,
so a value outside the working folder must not add that folder's files to the
job's outputs.
"""

import asyncio
from pathlib import Path

import pytest

from shyfem_ui.job_runner import result_fields
from shyfem_ui.services.job_detached import JobFiles, write_json_atomic
from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.job_queue import JobStatus
from shyfem_ui.services.shyfem_wrapper import DetachedRun, ShyfemWrapper

from .test_job_detached import db  # noqa: F401  (fixture)

JOB_ID = "31111111-2222-3333-4444-555555555555"


def _case(tmp_path: Path, extra_dirs, tool: str = "shypre", record_cwd=None):
    """A finished job: working folder, an outside folder holding a new .bas,
    and a launch record that names ``extra_dirs``."""
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "stolen.bas").write_text("x")
    (work / "inside.bas").write_text("x")
    files = JobFiles.for_stdout(work / f"{JOB_ID}.stdout")
    files.stdout.write_text("done\n")
    spec = {
        "job_id": JOB_ID,
        "cmd": [tool],
        "cwd": str(record_cwd or work),
        "stdout_file": str(files.stdout),
        "tool_name": tool,
        "before_snapshot": {},
    }
    if extra_dirs is not ...:
        spec["extra_dirs"] = extra_dirs(outside) if callable(extra_dirs) else extra_dirs
    write_json_atomic(files.spec, spec)
    write_json_atomic(files.exit, {"return_code": 0, "timed_out": False})
    return work, outside, files, spec


def _names(paths) -> list[str]:
    return sorted(Path(p).name for p in paths)


def _watch(files, work, tool="shypre"):
    wrapper = ShyfemWrapper(".")
    detached = DetachedRun(
        job_id=JOB_ID, stdout_file=str(files.stdout), kill_on_cancel=lambda: False
    )
    return asyncio.run(wrapper.watch_detached(tool, files.stdout, detached, working_dir=work))


def _fields(work, files, spec):
    # What the supervisor's stdin carries / what the reconcile builds.
    return result_fields({**spec, "cwd": str(work)}, files, 0, False)


def _reconcile(tmp_path, work, files, spec):
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Job

    with db_session() as s:
        s.add(
            Job(
                job_uuid=JOB_ID,
                name="j",
                job_type=spec["tool_name"],
                working_dir=str(work),
                status=JobStatus.RUNNING,
                stdout_file=str(files.stdout),
            )
        )
        s.flush()
        row = s.query(Job).filter(Job.job_uuid == JOB_ID).first()
        queue = LocalJobQueue(shyfem_dir=tmp_path, max_workers=1)
        state, payload = queue._reconcile_active_row(row)
    assert state == "finished"
    return payload[1]["output_files"]


# --- RED on 9e619eb3: a folder outside the working folder is ignored ----------


def test_watcher_ignores_a_folder_outside_the_working_folder(tmp_path):
    work, outside, files, _ = _case(tmp_path, lambda o: [str(o)])
    result = _watch(files, work)
    assert _names(result.output_files) == ["inside.bas"]


def test_result_fields_ignores_a_folder_outside_the_working_folder(tmp_path):
    work, outside, files, spec = _case(tmp_path, lambda o: [str(o)])
    assert _names(_fields(work, files, spec)["output_files"]) == ["inside.bas"]


def test_reconcile_ignores_a_folder_outside_the_working_folder(db, tmp_path):  # noqa: F811
    work, outside, files, spec = _case(tmp_path, lambda o: [str(o)])
    assert _names(_reconcile(tmp_path, work, files, spec)) == ["inside.bas"]


# --- GREEN guards --------------------------------------------------------------


def test_an_inside_subfolder_is_still_listed(tmp_path):
    work, _, files, spec = _case(tmp_path, ...)
    sub = work / "grids"
    sub.mkdir()
    (sub / "g.bas").write_text("x")
    write_json_atomic(files.spec, {**spec, "extra_dirs": [str(sub)]})
    assert _names(_watch(files, work).output_files) == ["g.bas", "inside.bas"]
    spec["extra_dirs"] = [str(sub)]
    assert _names(_fields(work, files, spec)["output_files"]) == ["g.bas", "inside.bas"]


@pytest.mark.parametrize("bad", ["somewhere", 7, {"a": 1}, None, [3, None, {"a": 1}]])
def test_a_malformed_value_reads_as_empty(tmp_path, bad):
    work, _, files, spec = _case(tmp_path, bad)
    assert _names(_watch(files, work).output_files) == ["inside.bas"]
    assert _names(_fields(work, files, spec)["output_files"]) == ["inside.bas"]


def test_a_record_without_extra_dirs_reads_as_empty(tmp_path):
    work, _, files, spec = _case(tmp_path, ...)
    assert "extra_dirs" not in spec
    assert _names(_watch(files, work).output_files) == ["inside.bas"]
    assert _names(_fields(work, files, spec)["output_files"]) == ["inside.bas"]


def test_another_tool_ignores_the_field(tmp_path):
    work, _, files, spec = _case(tmp_path, lambda o: [str(o)], tool="shybas")
    sub = work / "grids"
    sub.mkdir()
    assert ShyfemWrapper.spec_extra_dirs("shybas", spec, work) == []


def test_a_symlink_inside_pointing_outside_is_dropped(tmp_path):
    work, outside, files, spec = _case(tmp_path, ...)
    link = work / "link"
    link.symlink_to(outside, target_is_directory=True)
    write_json_atomic(files.spec, {**spec, "extra_dirs": [str(link)]})
    assert _names(_watch(files, work).output_files) == ["inside.bas"]
    spec["extra_dirs"] = [str(link)]
    assert _names(_fields(work, files, spec)["output_files"]) == ["inside.bas"]


def test_the_working_folder_itself_and_no_working_folder_give_nothing(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    spec = {"extra_dirs": [str(work)]}
    assert ShyfemWrapper.spec_extra_dirs("shypre", spec, work) == []
    assert ShyfemWrapper.spec_extra_dirs("shypre", spec, None) == []


def test_extra_output_dirs_inside_and_outside(tmp_path):
    work = tmp_path / "w"
    (work / "grids").mkdir(parents=True)
    out = tmp_path / "o"
    out.mkdir()
    f = ShyfemWrapper.extra_output_dirs
    assert f("shypre", [str(out / "g.grd")], work) == []
    assert f("shypre", ["../o/g.grd"], work) == []
    assert f("shypre", ["grids/g.grd"], work) == [work / "grids"]
    (work / "ln").symlink_to(out, target_is_directory=True)
    assert f("shypre", ["ln/g.grd"], work) == []
