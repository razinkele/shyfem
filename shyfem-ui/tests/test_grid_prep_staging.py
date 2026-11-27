"""Grid Prep stages the grid through stage_grid and keeps an upload's own name (#350).

``_run_shypre`` used to ``shutil.copy2`` the loaded grid into the output
directory without looking at what was there (a different same-named grid was
replaced), and an upload, which Shiny stores as ``0.grd``, was copied under that
name so shypre wrote ``0.bas``.
"""

import pytest

from shyfem_ui.services.file_service import check_plain_file_name
from shyfem_ui.services.grid_prep_logic import named_upload, stage_for_shypre

NAME = "MM_coarse.grd"


def _refusal(name: str) -> str:
    return (
        f"The output directory already has a different {name}. It may be the copy an "
        "earlier run left there: remove or rename it, or choose another output directory."
    )


@pytest.fixture
def dirs(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / NAME).write_bytes(b"grid one\n")
    return src, out


# --- stage_for_shypre -------------------------------------------------------


def test_different_same_named_grid_is_refused_and_left_unchanged(dirs):
    src, out = dirs
    (out / NAME).write_bytes(b"someone else's grid\n")
    with pytest.raises(ValueError) as exc:
        stage_for_shypre(src / NAME, out)
    assert str(exc.value) == _refusal(NAME)
    assert (out / NAME).read_bytes() == b"someone else's grid\n"


def test_identical_grid_is_reused_without_a_new_file(dirs):
    src, out = dirs
    (out / NAME).write_bytes(b"grid one\n")
    before = sorted(p.name for p in out.iterdir())
    assert stage_for_shypre(src / NAME, out) == out / NAME
    assert sorted(p.name for p in out.iterdir()) == before


def test_missing_grid_is_copied_with_its_content(dirs):
    src, out = dirs
    staged = stage_for_shypre(src / NAME, out)
    assert staged == out / NAME
    assert staged.read_bytes() == b"grid one\n"


def test_grid_already_in_the_output_folder_is_returned_as_is(dirs):
    _, out = dirs
    (out / NAME).write_bytes(b"grid one\n")
    assert stage_for_shypre(out / NAME, out) == out / NAME


def test_run_again_after_editing_the_source_is_refused(dirs):
    src, out = dirs
    stage_for_shypre(src / NAME, out)
    (src / NAME).write_bytes(b"grid one, edited\n")
    with pytest.raises(ValueError) as exc:
        stage_for_shypre(src / NAME, out)
    assert str(exc.value) == _refusal(NAME)
    assert (out / NAME).read_bytes() == b"grid one\n"


# --- named_upload -----------------------------------------------------------


def test_upload_is_copied_under_its_own_name(tmp_path):
    temp = tmp_path / "0.grd"
    temp.write_bytes(b"uploaded grid\n")
    named = named_upload(temp, NAME)
    assert named == tmp_path / "named" / NAME
    assert named.read_bytes() == b"uploaded grid\n"
    assert temp.exists()


@pytest.mark.parametrize("bad", ["../x.grd", "a/b.grd", "a\\b.grd", "", "..", "x.txt", "x.GRD"])
def test_bad_upload_names_are_refused(tmp_path, bad):
    temp = tmp_path / "0.grd"
    temp.write_bytes(b"g\n")
    with pytest.raises(ValueError) as exc:
        named_upload(temp, bad)
    assert str(exc.value) == f"Invalid grid file name: {bad!r}"
    assert not (tmp_path / "named").exists() or not any((tmp_path / "named").iterdir())


# --- the shared name rule ---------------------------------------------------


@pytest.mark.parametrize("bad", ["", "a/b", "../x", "..", "x..y"])
def test_check_plain_file_name_refuses(bad):
    with pytest.raises(ValueError):
        check_plain_file_name(bad)


def test_check_plain_file_name_accepts_a_plain_name():
    check_plain_file_name("MM_coarse.grd")


# --- page wiring (source) ---------------------------------------------------


def test_run_shypre_stages_before_running_and_returns_on_refusal():
    import shyfem_ui.pages.grid_prep as page
    from tests._test_helpers import get_server_source

    src = get_server_source(page, "grid_prep_server")
    body = src[src.index("async def _run_shypre(") :]
    assert "shutil.copy2" not in body
    i_stage = body.index("stage_for_shypre(")
    i_run = body.index("wrapper.run_shypre(")
    assert i_stage < i_run
    handler = body[body.index("except ValueError", i_stage) : i_run]
    assert "return" in handler


def test_upload_handler_loads_the_named_copy():
    import shyfem_ui.pages.grid_prep as page
    from tests._test_helpers import get_server_source

    src = get_server_source(page, "grid_prep_server")
    body = src[
        src.index("async def _handle_file_upload(") : src.index("# Initialize child modules")
    ]
    i_named = body.index("named_upload(")
    assert i_named < body.index("GrdParser.parse_file")  # validated before parsing
    assert "current_grd_path.set(named" in body.replace(" ", "") or "current_grd_path.set(" in body
    set_call = body[body.index("current_grd_path.set(") :].split("\n")[0]
    assert "temp_path" not in set_call
