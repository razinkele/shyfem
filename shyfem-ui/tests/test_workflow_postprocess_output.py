"""#353: post-process when the simulation writes no output, or several files.

SHYFEM writes field output only when the STR sets an output interval
(``idtout``, ``idtcon``).  Without one the simulation completes and lists no
output files, and the post-process step used to fail with the generic
"Unresolved workflow step reference(s)", which hid that the simulation
succeeded.  With several outputs, ``output_files[0]`` was whichever file the
directory listed first.

These run the REAL LocalJobQueue and the real wrapper with fake tools: the
fake ``shyfem`` writes the files a case needs into its working folder (or
none) and the fake ``shyelab`` records its args.
"""

import asyncio
import os
import stat
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.models import workflow as _wf_model  # noqa: F401 -- register models
from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.workflow import WorkflowEngine, WorkflowStatus

NO_OUTPUT_MESSAGE = (
    "Step 'simulation' completed but wrote no output files for this step to use. "
    "SHYFEM writes its .shy output only when the STR file sets an output interval, "
    "such as idtout (hydrodynamics) or idtcon (tracers) in $para."
)
SHYPRE = 'g="${@: -1}"\ncp "$g" "${g%.grd}.bas"\n'
SHYPARTS = "exit ${PARTS_EXIT:-0}\n"
SHYELAB = 'printf "%s\\n" "$@" > elab_args.txt\n'
GRID = "mm.grd"


def _tool(shyfem_dir, name, body):
    path = shyfem_dir / "bin" / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _shyfem_writing(shyfem_dir, *names):
    body = "echo '  simulation end: finished'\n" + "".join(f"echo data > {n}\n" for n in names)
    _tool(shyfem_dir, "shyfem", body)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A scratch database for the job rows the real queue writes."""
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


@pytest.fixture
def shyfem_dir(tmp_path, db):
    d = tmp_path / "shyfem"
    (d / "bin").mkdir(parents=True)
    _tool(d, "shyelab", SHYELAB)
    _tool(d, "shypre", SHYPRE)
    _tool(d, "shyparts", SHYPARTS)
    return d


@pytest.fixture
def session_factory():
    db = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=db)
    session = sessionmaker(bind=db)()
    yield lambda: session
    session.close()


@pytest.fixture
def work(tmp_path):
    w = tmp_path / "WORK"
    w.mkdir()
    (w / GRID).write_text("grid\n")
    (w / "run.str").write_text("$title\n$end\n")
    return w


async def _run(shyfem_dir, session_factory, work, template="simulation_postprocess"):
    queue = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    queue._history_loaded = True
    engine = WorkflowEngine(queue, session_factory=session_factory)
    wf_id = await engine.create_workflow(
        template,
        working_dir=work,
        params={
            "input_grd": str(work / GRID),
            "input_str": str(work / "run.str"),
            "mpi_np": 1,
        },  # 1: no mpirun,
    )
    task = engine._polling_tasks[wf_id]
    await asyncio.wait([task], timeout=30)
    assert task.done(), "workflow driver task did not finish"
    assert task.exception() is None
    return engine.get_workflow(wf_id), queue


def _elab_args(work):
    return (work / "elab_args.txt").read_text().split()


# --- the simulation writes nothing --------------------------------------------


@pytest.mark.asyncio
async def test_no_output_fails_with_the_specific_message(shyfem_dir, session_factory, work):
    _shyfem_writing(shyfem_dir)
    wf, queue = await _run(shyfem_dir, session_factory, work)

    assert wf.status == WorkflowStatus.FAILED
    assert wf.error_message == "Step 'postprocess' error: " + NO_OUTPUT_MESSAGE
    assert wf.step_results["simulation"]["status"] == "completed"
    assert wf.step_results["simulation"]["output_files"] == []
    assert [j.tool_name for j in queue._jobs.values()] == ["shyfem"]  # no shyelab job
    assert not (work / "elab_args.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("parts_exit", ["0", "9"])
async def test_full_simulation_without_output_gives_the_same_message(
    shyfem_dir, session_factory, work, monkeypatch, parts_exit
):
    monkeypatch.setenv("PARTS_EXIT", parts_exit)
    _shyfem_writing(shyfem_dir)
    wf, queue = await _run(shyfem_dir, session_factory, work, template="full_simulation")

    assert wf.status == WorkflowStatus.FAILED
    assert wf.step_results["partitioning"]["status"] == "completed"
    assert wf.error_message == "Step 'postprocess' error: " + NO_OUTPUT_MESSAGE
    assert "shyelab" not in [j.tool_name for j in queue._jobs.values()]


# --- the choice among several outputs -------------------------------------------


@pytest.mark.asyncio
async def test_several_outputs_post_process_the_hydro_file(shyfem_dir, session_factory, work):
    _shyfem_writing(shyfem_dir, "r.conz.shy", "r.hydro.shy", "r.ts.shy", "r.ext")
    wf, _ = await _run(shyfem_dir, session_factory, work)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert _elab_args(work) == ["-split", str(work / "r.hydro.shy")]


@pytest.mark.asyncio
async def test_without_a_hydro_file_the_first_shy_by_name_is_used(
    shyfem_dir, session_factory, work
):
    _shyfem_writing(shyfem_dir, "b.ts.shy", "a.conz.shy")
    wf, _ = await _run(shyfem_dir, session_factory, work)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert _elab_args(work) == ["-split", str(work / "a.conz.shy")]


@pytest.mark.asyncio
async def test_an_ext_only_run_is_post_processed(shyfem_dir, session_factory, work):
    _shyfem_writing(shyfem_dir, "r.ext")
    wf, _ = await _run(shyfem_dir, session_factory, work)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert _elab_args(work) == ["-split", str(work / "r.ext")]


@pytest.mark.asyncio
async def test_an_untouched_earlier_output_is_not_post_processed(shyfem_dir, session_factory, work):
    old = work / "old.hydro.shy"
    old.write_text("old\n")
    long_ago = time.time() - 86400
    os.utime(old, (long_ago, long_ago))
    _shyfem_writing(shyfem_dir, "new.conz.shy")
    wf, _ = await _run(shyfem_dir, session_factory, work)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert wf.step_results["simulation"]["output_files"] == [str(work / "new.conz.shy")]
    assert _elab_args(work) == ["-split", str(work / "new.conz.shy")]


# --- the wrapper's order ----------------------------------------------------------


def test_find_output_files_orders_by_priority_then_name(tmp_path, shyfem_dir):
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

    for n in ("z.hydro.shy", "a.conz.shy", "m.ts.shy", "r.ext", "r.flx", "r.ts"):
        (tmp_path / n).write_text("x\n")
    got = ShyfemWrapper(shyfem_dir)._find_output_files("shyfem", tmp_path, {})
    want = ["z.hydro.shy", "a.conz.shy", "m.ts.shy", "r.ext", "r.flx", "r.ts"]
    assert got == [str(tmp_path / n) for n in want]
    assert len(got) == len(set(got))


# --- _resolve_args ----------------------------------------------------------------

TEMPLATE = ["-split", "{simulation.output_files[0]}"]
GENERIC = (
    "Unresolved workflow step reference(s): {simulation.output_files[0]}"
    " — a previous step produced no matching output."
)


def _result(status="completed", files=()):
    return {"status": status, "output_files": list(files), "output_dir": "/w", "return_code": 0}


def _resolve(results, tools):
    return WorkflowEngine._resolve_args(TEMPLATE, {}, results, step_tools=tools)


def test_resolve_names_a_completed_shyfem_step_without_output():
    with pytest.raises(ValueError) as e:
        _resolve({"simulation": _result()}, {"simulation": "shyfem"})
    assert str(e.value) == NO_OUTPUT_MESSAGE


def test_resolve_keeps_the_generic_message_for_another_tool():
    with pytest.raises(ValueError) as e:
        _resolve({"simulation": _result()}, {"simulation": "shypre"})
    assert str(e.value) == GENERIC


def test_resolve_keeps_the_generic_message_without_step_tools():
    with pytest.raises(ValueError) as e:
        WorkflowEngine._resolve_args(TEMPLATE, {}, {"simulation": _result()})
    assert str(e.value) == GENERIC


def test_resolve_keeps_the_generic_message_when_the_step_did_not_complete():
    with pytest.raises(ValueError) as e:
        _resolve({"simulation": _result("failed")}, {"simulation": "shyfem"})
    assert str(e.value) == GENERIC


def test_resolve_keeps_the_generic_message_when_the_step_never_ran():
    with pytest.raises(ValueError) as e:
        _resolve({}, {"simulation": "shyfem"})
    assert str(e.value) == GENERIC
