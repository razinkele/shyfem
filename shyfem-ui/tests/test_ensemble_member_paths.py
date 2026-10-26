"""R-02: ensemble members ran in <base>/<ensemble>/<run>/, where every
relative path in the base STR (basin on $title line 3, forcing in $name,
boundary files) no longer resolved, so all N runs stopped at once.

Members keep their own folder (outputs must not mix), and each relative
path that exists next to the base STR is rewritten relative to the member's
folder. Nothing else is touched.
"""

import inspect
from pathlib import Path

from shyfem_ui.services.parser_str import StrParser

BASE = """$title
        Ensemble base
        run1
        GRID/basin
$end
$para
        itanf = 0  itend = 3600  idt = 300
$end
$name
        wind = 'fem_forcing/wind.fem'
        qflux = '/abs/elsewhere/heat.fem'
        rain = 'not_there.fem'
$end
$bound1
        boundn = 'fem_forcing/sea_level.txt'
$end
"""


def _base(tmp_path: Path) -> Path:
    b = tmp_path / "proj"
    (b / "GRID").mkdir(parents=True)
    (b / "GRID" / "basin.bas").write_text("")
    (b / "fem_forcing").mkdir()
    (b / "fem_forcing" / "wind.fem").write_text("")
    (b / "fem_forcing" / "sea_level.txt").write_text("")
    (b / "run.str").write_text(BASE)
    return b


def _relocated(tmp_path):
    from shyfem_ui.pages.ensemble import _relocate_member_paths

    b = _base(tmp_path)
    run_dir = b / "ens" / "run_a"
    run_dir.mkdir(parents=True)
    s = StrParser.parse_file(b / "run.str")
    _relocate_member_paths(s, b, run_dir)
    return StrParser.parse(StrParser.generate(s)), b, run_dir


def test_existing_relative_paths_point_back_to_the_base_folder(tmp_path):
    s, b, run_dir = _relocated(tmp_path)
    assert s.get_param("name", "wind") == "../../fem_forcing/wind.fem"
    assert s.get_param("bound1", "boundn") == "../../fem_forcing/sea_level.txt"
    assert (run_dir / s.get_param("name", "wind")).resolve() == (
        b / "fem_forcing" / "wind.fem"
    ).resolve()


def test_the_basin_on_title_line_3_is_relocated(tmp_path):
    s, _, _ = _relocated(tmp_path)
    title = [line.strip() for line in s.sections["title"].raw_lines]
    # With its extension: the core reads the type after the last dot, which
    # in "../../GRID/basin" would be inside "../".
    assert title == ["Ensemble base", "run1", "../../GRID/basin.bas"]


def test_absolute_and_nonexistent_values_are_left_alone(tmp_path):
    s, _, _ = _relocated(tmp_path)
    assert s.get_param("name", "qflux") == "/abs/elsewhere/heat.fem"
    assert s.get_param("name", "rain") == "not_there.fem"


def test_fixed_name_inputs_are_copied_not_linked(tmp_path):
    from shyfem_ui.pages.ensemble import _copy_fixed_inputs

    b = _base(tmp_path)
    (b / "boxes.txt").write_text("29 boxes")
    run_dir = b / "ens" / "run_a"
    run_dir.mkdir(parents=True)
    _copy_fixed_inputs(b, run_dir)
    copied = run_dir / "boxes.txt"
    assert copied.read_text() == "29 boxes" and not copied.is_symlink()


def test_the_submit_handler_relocates_and_validates_each_member():
    from shyfem_ui.pages import ensemble

    src = inspect.getsource(ensemble)
    body = src[src.index("for i, combo in enumerate(combos):\n            # Create a modified") :]
    body = body[: body.index("spec = JobSpec(")]
    assert "_relocate_member_paths(" in body and "_copy_fixed_inputs(" in body
    assert body.index("_relocate_member_paths(") < body.index("validate_str(")
    assert body.index("validate_str(") < body.index("StrParser.save(")


def test_an_existing_absolute_path_is_kept_as_written(tmp_path):
    from shyfem_ui.pages.ensemble import _relocate_member_paths

    b = _base(tmp_path)
    shared = tmp_path / "shared_heat.fem"
    shared.write_text("")
    s = StrParser.parse_file(b / "run.str")
    s.set_param("name", "qflux", f"'{shared}'")
    run_dir = b / "ens" / "run_a"
    run_dir.mkdir(parents=True)
    _relocate_member_paths(s, b, run_dir)
    assert StrParser.parse(StrParser.generate(s)).get_param("name", "qflux") == str(shared)
