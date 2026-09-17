from datetime import datetime

from _boxmodel_fixture import make_box_project, make_box_run, value_at


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
