"""#352: the Full Simulation Pipeline takes its grid from the STR.

The simulation reads the basin named on the third line of the STR's $title
(``GRID/MM_coarse`` -> ``GRID/MM_coarse.bas``, else ``.grd``), relative to the
working folder.  The template used to prepare an unrelated grid and partition
it for nothing; it now runs ``shypre`` on the ``.grd`` the STR names, in place,
so the ``.bas`` lands where the simulation reads it, and the partitioning
step is gone (the core partitions the mesh itself).

The engine tests run the REAL LocalJobQueue and the real wrapper with
stand-in tools: ``shypre`` writes ``<grid>.bas`` next to its input as the real
one does, ``shyfem`` prints its end line and writes a ``.shy``.
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
from shyfem_ui.models.workflow import Workflow
from shyfem_ui.services.job_local import LocalJobQueue
from shyfem_ui.services.workflow import WORKFLOW_TEMPLATES, WorkflowEngine, WorkflowStatus

SHYPRE = 'printf "%s\\n" "$@" > shypre_args.txt\ng="${@: -1}"\ncp "$g" "${g%.grd}.bas"\n'
SHYFEM = "echo '  simulation end: finished'\necho data > r.hydro.shy\n"
SHYELAB = 'printf "%s\\n" "$@" > elab_args.txt\n'


def _tool(shyfem_dir, name, body):
    path = shyfem_dir / "bin" / name
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_str(path, *title_lines, header="$title", end="$end"):
    path.write_text(header + "\n" + "\n".join(title_lines) + "\n" + end + "\n")
    return path


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
    _tool(d, "shyfem", SHYFEM)
    _tool(d, "shyelab", SHYELAB)
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
    (w / "GRID" / "mm.grd").write_text("grid v1\n")
    return w


@pytest.fixture
def str_file(work):
    return _write_str(work / "run.str", "title", "run", "GRID/mm")


def _engine(shyfem_dir, session_factory):
    queue = LocalJobQueue(shyfem_dir=shyfem_dir, max_workers=2)
    queue._history_loaded = True
    return WorkflowEngine(queue, session_factory=session_factory), queue


async def _run(shyfem_dir, session_factory, work, str_file, **params):
    engine, queue = _engine(shyfem_dir, session_factory)
    wf_id = await engine.create_workflow(
        "full_simulation",
        working_dir=work,
        params={"input_str": str(str_file), "mpi_np": 1, **params},  # 1: no mpirun
    )
    task = engine._polling_tasks[wf_id]
    await asyncio.wait([task], timeout=30)
    assert task.done(), "workflow driver task did not finish"
    assert task.exception() is None
    return engine.get_workflow(wf_id), queue


# --- basin_grid_for_str ------------------------------------------------------


def _basin(strf, work):
    from shyfem_ui.services.workflow import basin_grid_for_str

    return basin_grid_for_str(strf, work)


def test_no_extension_names_the_grd(work, str_file):
    assert _basin(str_file, work) == work / "GRID" / "mm.grd"


def test_a_bas_extension_names_the_grd(work):
    strf = _write_str(work / "b.str", "t", "r", "GRID/mm.bas")
    assert _basin(strf, work) == work / "GRID" / "mm.grd"


def test_blank_and_comment_lines_are_skipped(work):
    strf = _write_str(
        work / "c.str", "", "# a comment", "title", "! another", "", "run", "#x", "GRID/mm"
    )
    assert _basin(strf, work) == work / "GRID" / "mm.grd"


def test_blanks_around_the_name_are_stripped(work):
    strf = _write_str(work / "d.str", "title", "run", "    GRID/mm   \t")
    assert _basin(strf, work) == work / "GRID" / "mm.grd"


def test_an_ampersand_title_section_is_read(work):
    strf = _write_str(work / "e.str", "title", "run", "GRID/mm", header="&title", end="&end")
    assert _basin(strf, work) == work / "GRID" / "mm.grd"


def test_an_absolute_name_inside_the_working_folder_is_allowed(work):
    strf = _write_str(work / "f.str", "t", "r", str(work / "GRID" / "mm"))
    assert _basin(strf, work) == work / "GRID" / "mm.grd"


def _refusal(strf, work):
    from shyfem_ui.services.workflow import basin_grid_for_str

    with pytest.raises(ValueError) as e:
        basin_grid_for_str(strf, work)
    return str(e.value)


@pytest.mark.parametrize("missing", [None, ""])
def test_no_str_is_refused(work, missing):
    assert _refusal(missing, work) == "The Full Simulation Pipeline needs an STR file."


def test_a_title_without_a_third_line_is_refused(work):
    strf = _write_str(work / "g.str", "title", "# comment", "run")
    assert _refusal(strf, work) == (
        "Cannot find the basin name in g.str: it is the third line of its $title section."
    )


def test_an_str_without_a_title_is_refused(work):
    strf = work / "h.str"
    strf.write_text("$para\n  dt = 1\n$end\n")
    assert _refusal(strf, work) == (
        "Cannot find the basin name in h.str: it is the third line of its $title section."
    )


def test_an_unreadable_str_is_refused(work):
    assert _refusal(work / "nope.str", work) == (
        "Cannot find the basin name in nope.str: it is the third line of its $title section."
    )


def test_a_grd_extension_is_refused(work):
    strf = _write_str(work / "i.str", "t", "r", "GRID/mm.grd")
    assert _refusal(strf, work) == (
        "i.str names the basin GRID/mm.grd with the .grd extension, so the simulation "
        "would read the .grd and not the prepared basin. Name it without an extension, "
        "or use Simulate + Post-process."
    )


def test_another_extension_is_refused(work):
    strf = _write_str(work / "j.str", "t", "r", "GRID/mm.msh")
    assert _refusal(strf, work) == (
        "j.str names the basin GRID/mm.msh; the extension must be .bas or none."
    )


OUTSIDE = (
    "The grid {basin} that {str} names is outside the working folder. "
    "Move it into the working folder, or use Simulate + Post-process."
)


def test_a_name_leaving_the_working_folder_is_refused(work, tmp_path):
    (tmp_path / "x.grd").write_text("g\n")
    strf = _write_str(work / "k.str", "t", "r", "../x")
    assert _refusal(strf, work) == OUTSIDE.format(basin="../x", str="k.str")


def test_an_absolute_name_outside_is_refused(work, tmp_path):
    out = tmp_path / "elsewhere"
    out.mkdir()
    (out / "m.grd").write_text("g\n")
    strf = _write_str(work / "l.str", "t", "r", str(out / "m"))
    assert _refusal(strf, work) == OUTSIDE.format(basin=str(out / "m"), str="l.str")


def test_a_symlinked_folder_pointing_outside_is_refused(work, tmp_path):
    out = tmp_path / "elsewhere"
    out.mkdir()
    (out / "mm.grd").write_text("g\n")
    (work / "LINK").symlink_to(out, target_is_directory=True)
    strf = _write_str(work / "n.str", "t", "r", "LINK/mm")
    assert _refusal(strf, work) == OUTSIDE.format(basin="LINK/mm", str="n.str")


def test_a_missing_grd_is_refused(work):
    strf = _write_str(work / "o.str", "t", "r", "GRID/absent")
    assert _refusal(strf, work) == (
        "The grid GRID/absent.grd that o.str names does not exist in the working folder."
    )


# --- the template ------------------------------------------------------------


def test_the_template_is_grid_prep_simulation_postprocess():
    tpl = WORKFLOW_TEMPLATES["full_simulation"]
    assert [s.name for s in tpl["steps"]] == ["grid_prep", "simulation", "postprocess"]
    assert tpl["steps"][0].args_template == ["{basin_grd}"]
    assert tpl["grid_from_str"] is True
    assert tpl["name"] == "Full Simulation Pipeline"
    assert tpl["description"] == (
        "Prepares the grid the STR names (rewrites its .bas) -> Simulate -> Post-process"
    )


# --- the engine chain --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_chain_prepares_the_grid_the_str_names(
    shyfem_dir, session_factory, work, str_file
):
    wf, queue = await _run(shyfem_dir, session_factory, work, str_file)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert [s.name for s in wf.steps] == ["grid_prep", "simulation", "postprocess"]
    assert [j.tool_name for j in queue._jobs.values()] == ["shypre", "shyfem", "shyelab"]
    assert (work / "shypre_args.txt").read_text().split() == [str(work / "GRID" / "mm.grd")]
    assert wf.step_results["grid_prep"]["output_files"] == [str(work / "GRID" / "mm.bas")]
    assert (work / "GRID" / "mm.bas").read_text() == "grid v1\n"
    assert not (work / "mm.grd").exists()  # no staging copy
    assert not (work / "mm.bas").exists()
    assert wf.metadata["params"]["input_str"] == str(str_file)
    assert wf.metadata["params"]["basin_grd"] == str(work / "GRID" / "mm.grd")


@pytest.mark.asyncio
async def test_a_stale_bas_is_rewritten(shyfem_dir, session_factory, work, str_file):
    (work / "GRID" / "mm.bas").write_text("old basin\n")
    wf, _ = await _run(shyfem_dir, session_factory, work, str_file)

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert (work / "GRID" / "mm.bas").read_text() == "grid v1\n"
    assert wf.step_results["grid_prep"]["output_files"] == [str(work / "GRID" / "mm.bas")]


@pytest.mark.asyncio
async def test_a_picked_input_grd_is_ignored(shyfem_dir, session_factory, work, str_file, tmp_path):
    other = tmp_path / "other.grd"
    other.write_text("some other grid\n")
    wf, _ = await _run(shyfem_dir, session_factory, work, str_file, input_grd=str(other))

    assert wf.status == WorkflowStatus.COMPLETED, wf.error_message
    assert (work / "shypre_args.txt").read_text().split() == [str(work / "GRID" / "mm.grd")]
    assert not (work / "other.grd").exists()  # #348 staged nothing
    assert not (work / "other.bas").exists()


@pytest.mark.asyncio
async def test_no_grid_param_is_stored_when_the_page_passes_none(
    shyfem_dir, session_factory, work, str_file
):
    wf, _ = await _run(shyfem_dir, session_factory, work, str_file)
    assert "input_grd" not in wf.metadata["params"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "title_line,message",
    [
        (
            "GRID/absent",
            "The grid GRID/absent.grd that run.str names does not exist in the working folder.",
        ),
        (
            "GRID/mm.grd",
            "run.str names the basin GRID/mm.grd with the .grd extension, so the simulation "
            "would read the .grd and not the prepared basin. Name it without an extension, "
            "or use Simulate + Post-process.",
        ),
    ],
)
async def test_a_refusal_at_creation_stores_nothing(
    shyfem_dir, session_factory, work, title_line, message
):
    strf = _write_str(work / "run.str", "title", "run", title_line)
    engine, queue = _engine(shyfem_dir, session_factory)
    with pytest.raises(ValueError) as e:
        await engine.create_workflow(
            "full_simulation", working_dir=work, params={"input_str": str(strf)}
        )

    assert str(e.value) == message
    assert session_factory().query(Workflow).count() == 0
    assert queue._jobs == {}
    assert engine._polling_tasks == {}


@pytest.mark.asyncio
async def test_no_str_at_creation_stores_nothing(shyfem_dir, session_factory, work):
    engine, queue = _engine(shyfem_dir, session_factory)
    with pytest.raises(ValueError) as e:
        await engine.create_workflow("full_simulation", working_dir=work, params={})

    assert str(e.value) == "The Full Simulation Pipeline needs an STR file."
    assert session_factory().query(Workflow).count() == 0
    assert queue._jobs == {}


# --- the wrapper collects shypre's .bas next to its grid -----------------------


@pytest.mark.asyncio
async def test_shypre_lists_the_bas_in_its_grids_folder(shyfem_dir, work):
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

    grd = work / "GRID" / "mm.grd"
    result = await ShyfemWrapper(shyfem_dir).run_command("shypre", [str(grd)], work)

    assert result.success
    assert result.output_files == [str(work / "GRID" / "mm.bas")]


@pytest.mark.asyncio
async def test_an_untouched_bas_in_the_grids_folder_is_not_listed(shyfem_dir, work):
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

    _tool(shyfem_dir, "shypre", "exit 0\n")  # writes nothing
    (work / "GRID" / "mm.bas").write_text("old\n")
    result = await ShyfemWrapper(shyfem_dir).run_command(
        "shypre", [str(work / "GRID" / "mm.grd")], work
    )

    assert result.success
    assert result.output_files == []


# --- the launch form -----------------------------------------------------------


def test_the_launch_handler_reads_the_grid_only_for_templates_that_use_it():
    import shyfem_ui.pages.run as run_page
    from tests._test_helpers import get_server_source

    src = get_server_source(run_page, "run_server")
    handler = src[src.index("async def _launch_workflow(") :]
    handler = handler[: handler.index("def wf_progress(")]
    assert "input.wf_input_grd()" in handler
    guard = handler.index("if template_uses_input_grd(template_key):")
    assert guard < handler.index("input.wf_input_grd()")  # the read is inside the branch


def test_only_grid_only_uses_input_grd():
    from shyfem_ui.services.workflow import template_uses_input_grd

    assert [k for k in WORKFLOW_TEMPLATES if template_uses_input_grd(k)] == ["grid_only"]


def test_the_grid_picker_gives_way_to_a_note_for_the_full_simulation():
    import shyfem_ui.pages.run as run_page
    from tests._test_helpers import get_server_source

    src = get_server_source(run_page, "run_server")
    picker = src[src.index("def wf_input_grd_picker(") :]
    picker = picker[: picker.index("@render.ui", 10)]
    assert "input.wf_template()" in picker
    assert "template_uses_input_grd(" in picker
    assert "The grid is the one the STR's $title names; the pipeline rewrites its .bas." in picker
