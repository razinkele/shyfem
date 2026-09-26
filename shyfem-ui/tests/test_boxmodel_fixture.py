import json
from datetime import datetime

import pytest

from shyfem_ui import boxmodel_output as bo
from tests._boxmodel_fixture import make_box_project, make_box_run, value_at


def test_make_box_run_writes_all_files_with_real_envelope(tmp_path):
    info = make_box_run(tmp_path / "run")
    names = {p.name for p in (tmp_path / "run").iterdir()}
    assert {
        "boxes_2d.txt",
        "boxes_meteo.txt",
        "boxes_stats.txt",
        "boxes_geom.txt",
        "run.log",
    } <= names
    assert info["records"] == 240
    assert info["sections"] == [(1, 2), (1, 2), (2, 3), (-1, 1)]
    lines = (tmp_path / "run" / "boxes_2d.txt").read_text().splitlines()
    assert lines[0].startswith("#      idbox file_type     nvers")
    assert lines[1].split() == ["#", "473226", "2", "7"]
    assert lines[2] == "# time record"
    assert lines[3].split() == ["3600.0000000000000", "2009-01-01::01:00:00"]
    assert lines[6].startswith("# box      temp      salt cur_speed")
    assert value_at("temp", 2, datetime(2009, 1, 1, 5)) == 10 + 2 + 0.5


def test_make_box_project_writes_manifest_and_observations(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run)
    assert (proj / "boxmodel.json").exists()
    obs = (proj / "observations.csv").read_text().splitlines()
    assert obs[0] == "date,site,variable,value"
    assert any(",A,level,0" in line for line in obs)  # the zero sentinel row
    sites = (proj / "sites.csv").read_text().splitlines()
    assert sites[0] == "site,lat,lon,box"
    assert any(line.endswith(",") for line in sites[1:])  # unmapped site B


def test_make_box_project_obs_days_parameter(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run, obs_days=12)
    obs = (proj / "observations.csv").read_text().splitlines()
    # Extract all salt rows and get their distinct dates
    salt_rows = [line for line in obs if ",A,salinity," in line]
    salt_dates = {line.split(",")[0] for line in salt_rows}
    assert len(salt_dates) == 12  # 12 distinct dates for 12 observation days


# --- PR 2, Task 1: a second run with an offset --------------------------------

_FIRST_RECORD_BOX1 = (
    "    1  11.10000   0.51000   0.01000  -0.01100  -0.00550   0.00010  1.000000E+08"
)
_RUN_FILES = ("boxes_2d.txt", "boxes_meteo.txt", "boxes_stats.txt", "boxes_geom.txt", "run.log")


def _state_data_lines(run_dir):
    """Box data lines of every state record, in file order (no headers, no sections)."""
    out = []
    in_boxes = False
    for line in (run_dir / "boxes_2d.txt").read_text().splitlines():
        if line.startswith("# box "):
            in_boxes = True
            continue
        if line.startswith("#"):
            in_boxes = False
            continue
        if in_boxes:
            out.append(line)
    return out


def _section_lines(run_dir):
    out = []
    in_sections = False
    for line in (run_dir / "boxes_2d.txt").read_text().splitlines():
        if line.startswith("# section "):
            in_sections = True
            continue
        if line.startswith("#"):
            in_sections = False
            continue
        if in_sections:
            out.append(line)
    return out


def test_value_at_offset_touches_only_temp_and_salt():
    st = datetime(2009, 1, 1, 5)
    assert value_at("temp", 2, st, offset=1.5) == value_at("temp", 2, st) + 1.5
    assert value_at("salt", 2, st, offset=1.5) == value_at("salt", 2, st) + 1.5
    assert value_at("temp", 2, st, offset=0.0) == value_at("temp", 2, st)
    for var in ("cur_speed", "act_eta", "aver_eta", "bstress", "volume", "srad", "tair"):
        assert value_at(var, 2, st, offset=1.5) == value_at(var, 2, st)


def test_offset_run_shifts_state_records_only(tmp_path):
    make_box_run(tmp_path / "a", days=2)
    make_box_run(tmp_path / "b", days=2, offset=1.5)
    a_lines = _state_data_lines(tmp_path / "a")
    b_lines = _state_data_lines(tmp_path / "b")
    assert len(a_lines) == len(b_lines) == 48 * 3
    for la, lb in zip(a_lines, b_lines, strict=True):
        fa, fb = la.split(), lb.split()
        assert fa[0] == fb[0]  # same box
        # File carries 5 decimals, so compare the parsed floats to 1.5 within
        # float tolerance; the formatted cur_speed field is string-identical.
        assert float(fb[1]) - float(fa[1]) == pytest.approx(1.5)  # temp
        assert float(fb[2]) - float(fa[2]) == pytest.approx(1.5)  # salt
        assert fa[3:] == fb[3:]  # cur_speed, etas, bstress, volume untouched
    # meteo and flux are not offset
    assert (tmp_path / "a" / "boxes_meteo.txt").read_bytes() == (
        tmp_path / "b" / "boxes_meteo.txt"
    ).read_bytes()
    assert _section_lines(tmp_path / "a") == _section_lines(tmp_path / "b")
    for name in ("boxes_stats.txt", "boxes_geom.txt", "run.log"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_offset_run_is_readable_by_the_state_parser(tmp_path):
    make_box_run(tmp_path / "b", days=1, offset=1.5)
    recs = list(bo.iter_state_records(tmp_path / "b" / "boxes_2d.txt"))
    assert len(recs) == 24
    r = recs[4]
    assert r.values[1, bo.STATE_VARS.index("temp")] == pytest.approx(
        value_at("temp", 2, r.stamp, offset=1.5)
    )
    assert r.values[1, bo.STATE_VARS.index("cur_speed")] == pytest.approx(
        value_at("cur_speed", 2, r.stamp)
    )


def test_default_offset_is_byte_identical_to_the_pre_offset_fixture(tmp_path):
    # Regression guard (green before and after the change by design): the
    # first data line of the default run is the literal the fixture wrote
    # before ``offset`` existed, and offset=0.0 produces the same bytes as
    # omitting it.
    make_box_run(tmp_path / "a")
    make_box_run(tmp_path / "b", offset=0.0)
    lines = (tmp_path / "a" / "boxes_2d.txt").read_text().splitlines()
    assert lines[7] == _FIRST_RECORD_BOX1
    for name in _RUN_FILES:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_make_box_project_extra_runs_append_after_primary(tmp_path):
    run = tmp_path / "run"
    dir_b = tmp_path / "run_b"
    make_box_run(run)
    make_box_run(dir_b, offset=1.5)
    proj = make_box_project(tmp_path / "proj", run, extra_runs=[("b", "run B", dir_b)])
    manifest = json.loads((proj / "boxmodel.json").read_text())
    assert [r["id"] for r in manifest["runs"]] == ["fix", "b"]
    assert manifest["runs"][0] == {"id": "fix", "label": "fixture run", "dir": str(run)}
    assert manifest["runs"][1] == {"id": "b", "label": "run B", "dir": str(dir_b)}


def test_make_box_project_without_extra_runs_has_one_run(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run)
    manifest = json.loads((proj / "boxmodel.json").read_text())
    assert [r["id"] for r in manifest["runs"]] == ["fix"]
    proj2 = make_box_project(tmp_path / "proj2", run, extra_runs=None)
    assert (proj2 / "boxmodel.json").read_text() == (proj / "boxmodel.json").read_text()
