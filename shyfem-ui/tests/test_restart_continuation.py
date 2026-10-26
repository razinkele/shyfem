"""J-02 / R-03: "Continue from job" must produce a STR that runs and that
does not overwrite the run it continues.

The derived STR kept the source's run name ($title line 2), so every output
-- including the .rst it restarts from -- was truncated in the source's own
folder (J-02); it kept itend, so the continuation had zero steps, and wrote
the restart file as an absolute path that could break the 80-character line
cap, never validated (R-03). The shipped working pair
testcases/examples/weutro_box/eco_rst_part{1,2}.str shows the shape: new run
name, itanf = previous end, new itend, relative restrt, itrst = -1.
"""

from pathlib import Path

import pytest

from shyfem_ui.services.parser_str import StrParser
from shyfem_ui.services.run_logic import write_restart_str

SRC = """$title
        Curonian test
        curonian29
\tcuronian29
$end
$para
        itanf  = '1993-01-01'   itend = '1993-02-01'\tidt = '5m'
        idtrst = -1
$end
$name
        wind = 'fem_forcing/wind.fem'
$end
"""


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "run.str").write_text(SRC)
    (d / "curonian29.rst").write_text("")
    (d / "curonian29.hydro.shy").write_text("")
    return d


def _derive(run_dir, until="1993-03-01", rst=None):
    return write_restart_str(
        run_dir / "run.str", str(rst or run_dir / "curonian29.rst"), run_dir, until
    )


def _title(path):
    return [line.strip() for line in StrParser.parse_file(path).sections["title"].raw_lines]


def test_the_continuation_gets_a_new_run_name(run_dir):
    title = _title(_derive(run_dir))
    assert title[1] == "curonian29_c1", "the source's outputs must not be overwritten"
    assert title[0] == "Curonian test" and title[2] == "curonian29", "title and basin kept"


def test_the_name_skips_one_already_used_in_the_folder(run_dir):
    (run_dir / "curonian29_c1.inf").write_text("")
    assert _title(_derive(run_dir))[1] == "curonian29_c2"


def test_it_starts_where_the_source_ended_and_runs_to_the_new_end(run_dir):
    p = StrParser.parse_file(_derive(run_dir))
    assert p.get_param("para", "itanf") == "1993-02-01"
    assert p.get_param("para", "itend") == "1993-03-01"
    assert p.get_param("para", "itrst") == -1


def test_a_restart_file_in_the_run_folder_is_written_relative(run_dir):
    p = StrParser.parse_file(_derive(run_dir))
    assert p.get_param("name", "restrt") == "curonian29.rst"


def test_a_restart_file_elsewhere_stays_absolute(run_dir):
    import shutil
    import tempfile

    short = Path(tempfile.mkdtemp(prefix="r", dir="/tmp"))  # fits the 80-char line
    try:
        other = short / "x.rst"
        other.write_text("")
        p = StrParser.parse_file(_derive(run_dir, rst=other))
        assert p.get_param("name", "restrt") == str(other)
    finally:
        shutil.rmtree(short)


@pytest.mark.parametrize("until", ["", "   ", "next week", "1993-13-45", "1993-01-15"])
def test_a_missing_bad_or_too_early_end_is_refused(run_dir, until):
    with pytest.raises(ValueError):
        _derive(run_dir, until=until)
    assert sorted(p.name for p in run_dir.glob("*.str")) == ["run.str"], "nothing written"


def test_an_end_with_a_time_of_day_is_accepted(run_dir):
    p = StrParser.parse_file(_derive(run_dir, until="1993-02-01::12:00:00"))
    assert p.get_param("para", "itend") == "1993-02-01::12:00:00"


def test_a_derived_str_the_core_would_reject_is_refused(run_dir, tmp_path):
    """The 80-character cap: a long absolute restart path made the derived
    STR unreadable (nls.f90 error-stops on it); refuse before writing."""
    deep = tmp_path / ("d" * 70) / "x.rst"
    deep.parent.mkdir()
    deep.write_text("")
    with pytest.raises(ValueError, match="80"):
        _derive(run_dir, rst=deep)
    assert sorted(p.name for p in run_dir.glob("*.str")) == ["run.str"]


def test_the_run_page_requires_and_passes_continue_until():
    import inspect

    from shyfem_ui.pages import run

    src = inspect.getsource(run)
    sec = src[src.index("def restart_section") : src.index("def restart_info")]
    assert '"restart_until"' in sec, "the restart section offers a 'Continue until' field"
    sub = src[src.index("def _submit_job") :]
    call = sub[sub.index("write_restart_str(") : sub.index(")", sub.index("write_restart_str("))]
    assert "input.restart_until()" in call or "restart_until" in call
