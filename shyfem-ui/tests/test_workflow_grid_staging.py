"""#348: a workflow whose grid is not in the working folder.

shypre writes ``<grid>.bas`` next to its input grid and a job's output files
are collected only from its working folder, so a grid in ``GRID/`` left
Grid Prep with no output and the next step failed with "Unresolved workflow
step reference(s)".  The engine now copies the grid into the working folder
before the first step and removes its own copy when the workflow ends.

These run the REAL LocalJobQueue and the real wrapper with fake tools (a
canned queue would pass on the unfixed code): fake ``shypre`` writes its
``.bas`` next to its input, as the real one does.
"""

import asyncio
import stat

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models import project as _p  # noqa: F401 -- register models
from shyfem_ui.models import user as _u  # noqa: F401 -- register models
from shyfem_ui.models import workflow as _wf_model  # noqa: F401 -- register models
from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.workflow import WorkflowEngine, WorkflowStatus

NAME = "mm.grd"

SHYPRE = 'g="${@: -1}"\ncp "$g" "${g%.grd}.bas"\n'
SHYBAS = 'printf "%s\\n" "$@" > bas_args.txt\n'


def _tool(shyfem_dir, name, body):
    path = shyfem_dir / "bin" / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


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
    _tool(d, "shypre", SHYPRE)
    _tool(d, "shybas", SHYBAS)
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
    (w / "GRID").mkdir(parents=True)
    (w / "GRID" / NAME).write_text("grid v1\n")
    return w


async def _run(shyfem_dir, session_factory, work, grid, template="grid_only", **params):
    queue = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    queue._history_loaded = True
    engine = WorkflowEngine(queue, session_factory=session_factory)
    wf_id = await engine.create_workflow(
        template, working_dir=work, params={"input_grd": str(grid), **params}
    )
    task = engine._polling_tasks[wf_id]
    await asyncio.wait([task], timeout=30)
    assert task.done(), "workflow driver task did not finish"
    assert task.exception() is None
    return engine.get_workflow(wf_id), queue


def _listing(folder):
    return sorted(p.name for p in folder.iterdir())


@pytest.mark.asyncio
async def test_grid_in_a_subfolder_runs_and_leaves_nothing_behind(
    shyfem_dir, session_factory, work
):
    grid = work / "GRID" / NAME
    before = _listing(work / "GRID")
    wf, _ = await _run(shyfem_dir, session_factory, work, grid)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    received = (work / "bas_args.txt").read_text().split()
    assert received == ["-quality", "-grd", str(work / "mm.bas")]
    assert _listing(work / "GRID") == before  # nothing written next to the source
    assert not (work / NAME).exists()  # the engine's copy was removed
    # the stored params keep the path the user picked
    assert wf.metadata["params"]["input_grd"] == str(grid)


@pytest.mark.asyncio
async def test_relaunch_after_editing_the_source_grid(shyfem_dir, session_factory, work):
    grid = work / "GRID" / NAME
    first, _ = await _run(shyfem_dir, session_factory, work, grid)
    assert first.status == WorkflowStatus.COMPLETED, first.error_message

    grid.write_text("grid v2 edited\n")
    second, _ = await _run(shyfem_dir, session_factory, work, grid)

    assert second.status == WorkflowStatus.COMPLETED, second.error_message
    assert (work / "mm.bas").read_text() == "grid v2 edited\n"


@pytest.mark.asyncio
async def test_grid_already_in_the_working_folder_is_kept(shyfem_dir, session_factory, work):
    grid = work / NAME
    grid.write_text("grid in place\n")
    wf, _ = await _run(shyfem_dir, session_factory, work, grid)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert grid.read_text() == "grid in place\n"  # the user's own file stays


@pytest.mark.asyncio
async def test_a_different_file_of_that_name_fails_before_any_step(
    shyfem_dir, session_factory, work
):
    mine = work / NAME
    mine.write_text("somebody else's grid\n")
    wf, queue = await _run(shyfem_dir, session_factory, work, work / "GRID" / NAME)

    assert wf.status == WorkflowStatus.FAILED
    assert wf.error_message.startswith(
        "Could not stage the input grid: The working folder already has a different mm.grd"
    )
    assert queue._jobs == {}  # no step job was submitted
    assert mine.read_text() == "somebody else's grid\n"


@pytest.mark.asyncio
async def test_staged_copy_is_removed_when_a_step_fails(shyfem_dir, session_factory, work):
    _tool(shyfem_dir, "shybas", "exit 1\n")
    wf, _ = await _run(shyfem_dir, session_factory, work, work / "GRID" / NAME)

    assert wf.status == WorkflowStatus.FAILED
    assert not (work / NAME).exists()


# --- stage_grid and stage_tool_input ----------------------------------------


def test_stage_grid_names_the_folder_it_is_given(tmp_path):
    from shyfem_ui.services.partitioning_logic import stage_grid

    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / NAME).write_text("one\n")
    (tmp_path / "b" / NAME).write_text("two\n")
    with pytest.raises(ValueError) as named:
        stage_grid(tmp_path / "a" / NAME, tmp_path / "b", folder="working folder")
    assert str(named.value) == (
        "The working folder already has a different mm.grd; choose another working folder"
    )
    with pytest.raises(ValueError) as default:  # the Partitioning page's text
        stage_grid(tmp_path / "a" / NAME, tmp_path / "b")
    assert str(default.value) == (
        "The output folder already has a different mm.grd; choose another output folder"
    )


def test_stage_tool_input_copies_a_shypre_grid_into_the_workdir(work):
    from shyfem_ui.services.run_logic import stage_tool_input

    got = stage_tool_input("shypre", work / "GRID" / NAME, work)
    assert got == work / NAME and got.read_text() == "grid v1\n"


def test_stage_tool_input_leaves_a_grid_already_in_the_workdir(work):
    from shyfem_ui.services.run_logic import stage_tool_input

    (work / NAME).write_text("here\n")
    assert stage_tool_input("shypre", work / NAME, work) == work / NAME
    assert (work / NAME).read_text() == "here\n"


def test_stage_tool_input_does_not_touch_other_tools(work):
    from shyfem_ui.services.run_logic import stage_tool_input

    src = work / "GRID" / NAME
    assert stage_tool_input("shyelab", src, work) == src
    assert _listing(work) == ["GRID"]  # nothing copied


def test_stage_tool_input_refuses_a_different_file_of_that_name(work):
    from shyfem_ui.services.run_logic import stage_tool_input

    (work / NAME).write_text("other\n")
    with pytest.raises(ValueError, match="working folder"):
        stage_tool_input("shypre", work / "GRID" / NAME, work)
    assert (work / NAME).read_text() == "other\n"


def test_stage_tool_input_creates_a_working_folder_that_does_not_exist_yet(work):
    from shyfem_ui.services.run_logic import stage_tool_input

    new = work / "fresh" / "run1"  # confine_path(for_write=True) accepts this
    got = stage_tool_input("shypre", work / "GRID" / NAME, new)
    assert got == new / NAME and new.is_dir() and got.read_text() == "grid v1\n"


def test_stage_tool_input_creates_nothing_for_other_tools(work):
    from shyfem_ui.services.run_logic import stage_tool_input

    new = work / "fresh"
    stage_tool_input("shyelab", work / "GRID" / NAME, new)
    assert not new.exists()


# --- the single shypre job on the Run page ----------------------------------


def test_run_page_stages_before_it_builds_the_spec():
    import shyfem_ui.pages.run as run_page
    from tests._test_helpers import get_server_source

    src = get_server_source(run_page, "run_server")
    body = src[src.index("async def _submit_job(") :]
    assert "stage_tool_input(" in body
    assert body.index("stage_tool_input(") < body.index("build_job_spec(")


@pytest.mark.asyncio
async def test_single_shypre_job_lists_its_bas_and_writes_nothing_next_to_the_grid(
    shyfem_dir, work
):
    from shyfem_ui.services.run_logic import build_job_spec, stage_tool_input

    queue = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=1)
    queue._history_loaded = True
    before = _listing(work / "GRID")
    staged = stage_tool_input("shypre", work / "GRID" / NAME, work)
    spec = build_job_spec(
        name="j", tool_name="shypre", validated_input=staged, validated_workdir=work, session_id="s"
    )
    job_id = await queue.submit(spec)
    for _ in range(400):
        job = queue._jobs[job_id]
        if not job.is_active:
            break
        await asyncio.sleep(0.05)
    assert job.output_files == [str(work / "mm.bas")]
    assert _listing(work / "GRID") == before
