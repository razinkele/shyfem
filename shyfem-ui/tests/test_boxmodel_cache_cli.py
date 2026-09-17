import json
import subprocess
import sys
from datetime import date, datetime

import pandas as pd
import pytest

from shyfem_ui import boxmodel_cache_cli as cli
from tests._boxmodel_fixture import flux_at, make_box_run, value_at


@pytest.fixture
def run(tmp_path):
    make_box_run(tmp_path / "run", days=3)
    return tmp_path / "run"


def _out(tmp_path):
    base = tmp_path / "users"
    proj = base / "alice" / "proj"
    out = proj / ".boxmodel_cache" / "fix.tmp-abc"
    out.mkdir(parents=True)
    return base, out


def test_build_daily_means_match_hand_computation(run, tmp_path):
    base, out = _out(tmp_path)
    meta = cli.build(run, out, hourly=False)
    daily = pd.read_parquet(out / "state_daily.parquet")
    # day 1 has records 01:00..23:00 (23 records); day 2 has 00:00 of day 2 + 01:00..23:00 (24)
    d1 = daily[(daily["date"] == date(2009, 1, 1)) & (daily["box"] == 2)].iloc[0]
    hours = range(1, 24)
    assert d1["temp"] == pytest.approx(
        sum(value_at("temp", 2, datetime(2009, 1, 1, h)) for h in hours) / 23
    )
    assert d1["salt_max"] == pytest.approx(value_at("salt", 2, datetime(2009, 1, 1, 23)))
    d2 = daily[(daily["date"] == date(2009, 1, 2)) & (daily["box"] == 2)].iloc[0]
    assert d2["temp"] == pytest.approx(
        sum(value_at("temp", 2, datetime(2009, 1, 2, h)) for h in range(24)) / 24
    )
    assert set(daily["date"].unique()) == {
        date(2009, 1, 1),
        date(2009, 1, 2),
        date(2009, 1, 3),
        date(2009, 1, 4),
    }
    assert meta["records"] == 72 and meta["period"] == {
        "start": "2009-01-01T00:00:00",
        "end": "2009-01-04T00:00:00",
    }


def test_flux_daily_keeps_split_sections_and_boundary(run, tmp_path):
    base, out = _out(tmp_path)
    cli.build(run, out, hourly=False)
    flux = pd.read_parquet(out / "flux_daily.parquet")
    row = flux[(flux["date"] == date(2009, 1, 2)) & (flux["section"] == 3)].iloc[0]
    exp = [flux_at(3, datetime(2009, 1, 2, h)) for h in range(24)]
    assert row["positive"] == pytest.approx(sum(p for _, p, _ in exp) / 24)
    assert row["total"] == pytest.approx(row["positive"] - row["negative"])
    assert (row["from_box"], row["to_box"]) == (2, 3)
    assert sorted(flux[flux["date"] == date(2009, 1, 2)]["section"].tolist()) == [1, 2, 3, 4]
    assert flux[flux["section"] == 4]["from_box"].iloc[0] == -1


def test_meteo_daily_and_meta_sources_are_relative(run, tmp_path):
    base, out = _out(tmp_path)
    meta = cli.build(run, out, hourly=True)
    meteo = pd.read_parquet(out / "meteo_daily.parquet")
    assert meteo[(meteo["date"] == date(2009, 1, 2)) & (meteo["box"] == 1)]["srad"].iloc[
        0
    ] == pytest.approx(100 + 11.5)
    assert set(meta["sources"]) == {
        "boxes_2d.txt",
        "boxes_meteo.txt",
        "boxes_stats.txt",
        "boxes_geom.txt",
        "run.log",
    }
    assert all("/" not in k for k in meta["sources"]) and meta["hourly"] is True
    hourly = pd.read_parquet(out / "state_hourly.parquet")
    assert len(hourly) == 72 * 3 and str(hourly["temp"].dtype) == "float32"
    assert meta["run_log"]["program_stop_time"] == "2009-01-04::00:00:00"
    assert meta["section_nodes"]["1"] == [[21.01, 55.5], [21.01, 55.51]]
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "done" and prog["exit"] == 0 and prog["records"] == 72


def test_cli_rejects_out_dir_outside_trusted_base(run, tmp_path):
    base, out = _out(tmp_path)
    rc = cli.main(
        ["--run", str(run), "--out", str(out), "--trusted-base", str(tmp_path / "elsewhere")]
    )
    assert rc == 2
    bad = tmp_path / "not_cache" / "x"
    bad.mkdir(parents=True)
    assert cli.main(["--run", str(run), "--out", str(bad), "--trusted-base", str(base)]) == 2


def test_cli_rejects_symlinked_run_dir(run, tmp_path):
    base, out = _out(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(run)
    assert cli.main(["--run", str(link), "--out", str(out), "--trusted-base", str(base)]) == 2


def test_cli_end_to_end_as_subprocess_and_light_imports(run, tmp_path):
    base, out = _out(tmp_path)
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "shyfem_ui.boxmodel_cache_cli",
            "--run",
            str(run),
            "--out",
            str(out),
            "--trusted-base",
            str(base),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    assert (out / "meta.json").exists()
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, shyfem_ui.boxmodel_cache_cli; "
            "bad=[m for m in sys.modules if m.startswith(('shyfem_ui.db','shyfem_ui.services'))]; "
            "print(bad)",
        ],
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "[]", probe.stdout


def test_error_is_recorded_in_progress(run, tmp_path):
    base, out = _out(tmp_path)
    (run / "boxes_2d.txt").write_text("garbage\n")
    rc = cli.main(["--run", str(run), "--out", str(out), "--trusted-base", str(base)])
    assert rc == 1
    prog = json.loads((out / "progress.json").read_text())
    assert prog["phase"] == "error" and "preamble" in prog["error"]
