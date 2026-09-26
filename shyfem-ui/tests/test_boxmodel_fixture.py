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


# --- PR 3, Task 1: STR excerpt and a river file --------------------------------


def test_default_project_writes_no_str_or_forcing(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run)
    assert not (proj / "fixture.str").exists()
    assert not (proj / "forcing").exists()
    manifest = json.loads((proj / "boxmodel.json").read_text())
    assert manifest["str"] is None and manifest["forcing"] is None


def test_default_manifest_is_byte_identical_to_the_pre_str_fixture(tmp_path):
    # Regression guard: explicit False flags produce the same bytes as omitting them.
    run = tmp_path / "run"
    make_box_run(run)
    a = make_box_project(tmp_path / "a", run)
    b = make_box_project(tmp_path / "b", run, str_file=False, forcing=False)
    for name in ("boxmodel.json", "fixture.grd", "boxes.txt", "observations.csv", "sites.csv"):
        assert (a / name).read_bytes() == (b / name).read_bytes()
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())


def test_str_file_written_only_when_asked(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run, str_file=True)
    assert (proj / "fixture.str").is_file()
    assert not (proj / "forcing").exists()
    manifest = json.loads((proj / "boxmodel.json").read_text())
    assert manifest["str"] == "fixture.str"
    assert manifest["forcing"] is None
    assert list(manifest) == [
        "schema",
        "title",
        "boxes",
        "grid",
        "str",
        "forcing",
        "runs",
        "observations",
    ]


def test_forcing_written_only_when_asked(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run, forcing=True)
    assert (proj / "forcing" / "river.txt").is_file()
    assert not (proj / "fixture.str").exists()
    manifest = json.loads((proj / "boxmodel.json").read_text())
    assert manifest["str"] is None
    assert manifest["forcing"] == {"dir": "forcing"}


def test_fixture_str_covers_the_tolerant_reader_acceptance_list(tmp_path):
    from tests._boxmodel_fixture import FIXTURE_STR, fixture_str

    assert FIXTURE_STR == fixture_str(10)
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run, str_file=True)
    text = (proj / "fixture.str").read_text()
    assert text == FIXTURE_STR
    lines = text.splitlines()
    # (5) decoy prose OUTSIDE any section, before &para, tab-separated like the Curonian file
    decoy = " itanf  = 347068800\t itend  = 536450400\tidt = 300\t--> 2008-2013"
    assert decoy in lines and lines.index(decoy) < lines.index("&para")
    # (1) & and $ section openers/closers
    assert "&para" in lines and "&end" in lines
    assert "$title" in lines and "$name" in lines and "$extra" in lines
    # (3) several pairs on one line, tab before idt; date/time pair; tab-separated ireib/czdef
    assert "        itanf  = '2009-01-01'   itend  = '2009-01-11'\tidt = '5m'" in lines
    assert "\tidtbox = '1h'\t\t!box output -- the deliverable" in lines
    assert "        date   = 20090101   time   = 000000" in lines
    assert "        ireib  = 5\tczdef  = 0.0025" in lines
    assert "\tnomp   = 4" in lines
    # (6) orphan directly after &end
    assert lines[lines.index("&end") + 1] == "\tnsigma = 12"
    # (2) trailing header text; (4) kbound continuation line without '='
    b1 = lines.index("$bound1     ---- Baltic sea ---- open boundary")
    assert lines[b1 + 1] == "       kbound  = 1 2 3"
    assert lines[b1 + 2] == "                 4"
    assert lines[b1 + 3] == "\tibtyp  = 1"
    assert lines[b1 + 4] == "\tboundn = 'fem_forcing/sea_level.fem'"
    assert lines[b1 + 5] == "\tsaltn  = 'fem_forcing/salt.fem'"
    assert lines[b1 + 6] == "$end"
    b2 = lines.index("$bound2 ----- Fixture river ---- discharge in m3/s")
    assert lines[b2 + 1 : b2 + 8] == [
        "      kbound = 5 6",
        "      zfact  = 0.25",
        "      ibtyp  = 2",
        "      boundn ='fem_forcing/river.txt'",
        "      temp   = -999",
        "      salt   = 0.1",
        "$end",
    ]
    # (3) comment line inside $name, then the wind file
    n = lines.index("$name")
    assert lines[n + 1] == "      !gotmpa = ''\t\t!not needed: iturb = 0 (2-d run)"
    assert lines[n + 2] == "      wind = 'fem_forcing/wind.fem'"
    # (7) bare-word block outside sections with a bare 'end'
    lv = lines.index("levels")
    assert lines[lv + 1] == " 1 2 3" and lines[lv + 2] == "end"
    # (8) $extra row without '='
    assert lines[lines.index("$extra") + 1] == "        1 'A'"
    # (9) banner and ' - set' lines
    assert any(line.startswith("************************ SECTION ") for line in lines)
    assert any(line.startswith(" - set ") for line in lines)
    assert text.endswith("$end\n")


def test_fixture_str_period_follows_the_day_count():
    from tests._boxmodel_fixture import fixture_str

    assert "itend  = '2009-01-11'" in fixture_str(10)
    assert "itend  = '2009-02-10'" in fixture_str(40)  # not the invalid '2009-01-41'


def test_river_file_overhangs_the_run_period(tmp_path):
    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run, forcing=True)
    lines = (proj / "forcing" / "river.txt").read_text().splitlines()
    assert lines[0] == "# discharge m3/s"
    data = lines[1:]
    assert len(data) == 10 + 5  # T0-2 .. T0+days+2 inclusive
    assert data[0] == "2008-12-30::06:00:00  100"
    assert data[2] == "2009-01-01::06:00:00  102"
    assert data[-1] == "2009-01-13::06:00:00  114"
    for i, line in enumerate(data):
        stamp, value = line.split()
        assert stamp.endswith("::06:00:00") and int(value) == 100 + i
    # obs_days drives the span, as it drives the STR period
    proj40 = make_box_project(tmp_path / "proj40", run, obs_days=40, str_file=True, forcing=True)
    data40 = (proj40 / "forcing" / "river.txt").read_text().splitlines()[1:]
    assert len(data40) == 45 and data40[-1] == "2009-02-12::06:00:00  144"
    assert "itend  = '2009-02-10'" in (proj40 / "fixture.str").read_text()


def test_str_and_forcing_manifest_loads(tmp_path):
    from shyfem_ui.config import Config
    from shyfem_ui.services import boxmodel_manifest as bm

    run = tmp_path / "run"
    make_box_run(run)
    proj = make_box_project(tmp_path / "proj", run, str_file=True, forcing=True)
    cfg = Config(_env_file=None, deployment_mode="local", work_dir=tmp_path)
    m = bm.load_manifest(proj, cfg, None)
    assert m.str_path == (proj / "fixture.str").resolve()
    assert m.forcing_dir == (proj / "forcing").resolve()
    assert (m.forcing_dir / "river.txt").is_file()
