"""M-02, V-07, R-05 (shyelab half): what the pages expect of shybas/shyelab
matches what the real binaries do.

M-02: Grid Prep ran ``shybas -quality -info``; shybas has no ``-info`` (it
prints the basin info by default), stops with "no such option: info", and
since X-01 that is a failed run.
V-07: the Post-process Time Series Preview looked for ``.ts``/``.ext``/``.csv``,
which shyelab never writes; its series are ``<var>.0d.0`` (Basin Average) and
``<var>.2d.<n>`` (Extract Time Series), stamped ``YYYY-MM-DD::HH:MM:SS``.
R-05: shyelab prints no per-record counter, so there is no progress to parse.
"""

import math
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from shyfem_ui.pages.grid_prep import SHYBAS_INFO_FLAGS
from shyfem_ui.services.postprocess_logic import preview_series_file
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
from shyfem_ui.services.timeseries_loader import load_timeseries

_BIN = Path(__file__).resolve().parents[2] / "bin"
_SAMPLES = (
    Path(os.environ.get("SHYFEM_SAMPLES_DIR", "/home/razinka/shyfem/testcases/examples"))
    / "mar_menor"
)


def _tool(name: str) -> Path:
    p = _BIN / name
    return p if p.exists() else Path(shutil.which(name) or p)


# --- M-02 ---------------------------------------------------------------------


@pytest.mark.skipif(not _tool("shybas").exists(), reason="needs the built shybas")
def test_grid_prep_sends_only_real_shybas_options():
    out = subprocess.run([str(_tool("shybas")), "-h"], capture_output=True, text=True, timeout=30)
    real = {t for line in out.stdout.splitlines() for t in line.split() if t.startswith("-")}
    assert SHYBAS_INFO_FLAGS == ["-quality"]
    assert not [f for f in SHYBAS_INFO_FLAGS if f not in real]


# --- V-07: which generated file the preview shows ------------------------------


def test_preview_prefers_water_level_then_salinity_and_skips_non_series():
    node = ["out.fem", "all.2d.1", "dir.2d.1", "speed.2d.1", "zeta.2d.2", "zeta.2d.1"]
    assert Path(preview_series_file(node)).name == "zeta.2d.1"
    ts = ["out.fem", "all_scal_nodes.2d.txt", "temp.2d.1", "salt.2d.1", "salt_s.2d.0"]
    assert Path(preview_series_file(ts)).name == "salt.2d.1"
    assert Path(preview_series_file(["vel.0d.0", "zeta.0d.0"])).name == "zeta.0d.0"
    assert preview_series_file(["out.shy", "a.temporal_avg.shy", "vel_p.3d.1", "salt.3d.4"]) is None
    assert preview_series_file([]) is None


# --- V-07: reading shyelab's series (real output, captured 2026-10-28) ---------

_ZETA = (
    " 2009-01-01::03:00:00  -2.47623585E-02\n"
    " 2009-01-01::06:00:00  -1.87010523E-02\n"
    " 2009-01-01::09:00:00  -1.17179602E-02\n"
)
_SALT = (
    "#               date  salinity (vertically averaged)\n"
    "2009-01-01::06:00:00  35.000\n"
    "2009-01-01::12:00:00  34.900\n"
)
_AVERBAS = (
    "#      date_and_time    minimum    average    maximum        std         total\n"
    "2009-01-01::03:00:00     -0.029   Infinity      0.056      0.016  0.649006E+00\n"
    "2009-01-01::06:00:00     -0.020   Infinity      0.050      0.015  0.649100E+00\n"
)


def test_a_headerless_series_keeps_its_first_record(tmp_path):
    f = tmp_path / "zeta.2d.1"
    f.write_text(_ZETA)
    got = load_timeseries(f)
    assert got["columns"] == ["time", "value"]
    assert len(got["data"]) == 3
    assert str(got["df"]["time"].iloc[0]) == "2009-01-01 03:00:00"
    assert got["df"]["value"].iloc[0] == pytest.approx(-2.47623585e-02)


def test_a_series_header_names_its_columns(tmp_path):
    f = tmp_path / "salt.2d.1"
    f.write_text(_SALT)
    assert load_timeseries(f)["columns"] == ["time", "salinity (vertically averaged)"]
    g = tmp_path / "zeta.0d.0"
    g.write_text(_AVERBAS)
    got = load_timeseries(g)
    assert got["columns"] == ["time", "minimum", "average", "maximum", "std", "total"]
    assert len(got["data"]) == 2


def test_infinity_in_a_series_is_a_gap(tmp_path):
    g = tmp_path / "zeta.0d.0"
    g.write_text(_AVERBAS)
    avg = load_timeseries(g)["df"]["average"]
    assert all(math.isnan(v) for v in avg)


@pytest.mark.skipif(not _tool("shyelab").exists(), reason="needs the built shyelab")
def test_real_extract_time_series_output_is_previewed(tmp_path):
    sample = _SAMPLES / "mm_lgr.hydro.shy"
    if not sample.is_file():
        pytest.skip(f"{sample} not found (set SHYFEM_SAMPLES_DIR; .shy outputs are not in git)")
    shutil.copy2(sample, tmp_path / sample.name)
    subprocess.run(
        [str(_tool("shyelab")), "-node", "100", sample.name],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=True,
    )
    pick = preview_series_file(sorted(str(p) for p in tmp_path.iterdir()))
    assert Path(pick).name == "zeta.2d.1"
    got = load_timeseries(pick)
    assert got["columns"] == ["time", "value"] and len(got["data"]) == 32
    assert str(got["df"]["time"].iloc[0]) == "2009-01-01 03:00:00"


# --- R-05 (shyelab half) ------------------------------------------------------


def test_shyelab_has_no_progress_pattern(tmp_path):
    w = ShyfemWrapper(tmp_path)
    assert "shyelab" not in w.PROGRESS_PATTERNS
    for line in (
        " time :    10800.000000000000       2009-01-01::03:00:00  ivar :            0",
        "          32  time records read",
    ):
        assert w._parse_progress("shyelab", line) is None
