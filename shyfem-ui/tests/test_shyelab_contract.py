"""V-02 / V-03: the Post-process page must speak shyelab's real CLI.

It sent -ts, -taver, -minmax, -res, -layer and -<var>, none of which exist;
"Spatial Average" sent -aver (the average over records). -aver/-min/-max only
write a file with -out, always named out.shy, so a preset's steps overwrote
each other; and the real outputs (.shy, .fem, <var>.0d.0, <var>.2d.<n>) were
not among the extensions the page looks for, so it reported 0 files.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from shyfem_ui.pages.postprocess import PRESETS, SHYELAB_OPERATIONS
from shyfem_ui.services.postprocess_logic import build_shyelab_options, name_outputs
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

_REPO_BIN = Path(__file__).resolve().parents[2] / "bin" / "shyelab"
SHYELAB = _REPO_BIN if _REPO_BIN.exists() else Path(shutil.which("shyelab") or _REPO_BIN)


def _real_options() -> set[str]:
    out = subprocess.run([str(SHYELAB), "-h"], capture_output=True, text=True, timeout=30)
    return {tok for line in out.stdout.splitlines() for tok in line.split() if tok.startswith("-")}


@pytest.mark.skipif(not SHYELAB.exists(), reason="needs the built shyelab")
@pytest.mark.parametrize("op", sorted(SHYELAB_OPERATIONS))
def test_every_flag_the_page_sends_is_a_real_shyelab_option(op):
    real = _real_options()
    opts = build_shyelab_options(
        operation=op, op_flags=SHYELAB_OPERATIONS[op]["flags"], nodes="1823"
    )
    flags = [t for t in opts if t.startswith("-") and not t.lstrip("-").isdigit()]
    unknown = [f for f in flags if f not in real]
    assert not unknown, f"{op}: not shyelab options: {unknown}"


def test_the_operations_mean_what_their_labels_say():
    f = {k: v["flags"] for k, v in SHYELAB_OPERATIONS.items()}
    assert f["spatial_avg"] == ["-averbas"]
    assert f["temporal_avg"] == ["-aver", "-out"]
    assert f["time_min"] == ["-min", "-out"] and f["time_max"] == ["-max", "-out"]
    assert "minmax" not in f
    for preset in PRESETS.values():
        assert all(op in SHYELAB_OPERATIONS for op in preset["operations"])


def test_extract_time_series_needs_nodes_and_uses_node():
    with pytest.raises(ValueError):
        build_shyelab_options(operation="extract_ts", op_flags=[], nodes="")
    with pytest.raises(ValueError):
        build_shyelab_options(operation="extract_ts", op_flags=[], nodes="Klaipeda")
    assert build_shyelab_options(operation="extract_ts", op_flags=[], nodes=" 1823, 1657 ") == [
        "-node",
        "1823,1657",
    ]


def test_no_variable_or_layer_flags_are_ever_built():
    opts = build_shyelab_options(operation="split_vars", op_flags=["-split"], tmin="2001-01-01")
    assert opts == ["-split", "-tmin", "2001-01-01"]


def test_out_files_get_the_input_and_operation_in_their_name(tmp_path):
    (tmp_path / "out.shy").write_text("a")
    (tmp_path / "temp.0d.0").write_text("b")
    files = [str(tmp_path / "out.shy"), str(tmp_path / "temp.0d.0")]
    got = name_outputs(files, tmp_path / "curonian29.ts.shy", "temporal_avg")
    assert sorted(Path(p).name for p in got) == ["curonian29.ts.temporal_avg.shy", "temp.0d.0"]
    assert not (tmp_path / "out.shy").exists()


@pytest.mark.parametrize(
    "name", ["out.shy", "out.fem", "temp.0d.0", "zeta.2d.1", "salt.3d.12", "out.nc"]
)
def test_real_shyelab_outputs_are_found(tmp_path, name):
    w = ShyfemWrapper(tmp_path)
    before = w._snapshot_output_files("shyelab", tmp_path)
    (tmp_path / name).write_text("x")
    assert str(tmp_path / name) in w._find_output_files("shyelab", tmp_path, before)


_SAMPLE_SHY = (
    Path(__file__).resolve().parents[2] / "testcases/examples/mar_menor/mm_hyd_assim.ts.shy"
)
if not _SAMPLE_SHY.exists():
    _SAMPLE_SHY = Path("/home/razinka/shyfem/testcases/examples/mar_menor/mm_hyd_assim.ts.shy")


@pytest.mark.skipif(
    not (SHYELAB.exists() and _SAMPLE_SHY.exists()), reason="needs shyelab and a sample .shy"
)
@pytest.mark.parametrize("op", ["info", "split_vars", "spatial_avg", "temporal_avg", "time_max"])
def test_each_operation_runs_on_the_real_binary_at_a_long_path(tmp_path, op):
    """pytest's tmp paths are ~100 characters: shyelab truncated the
    absolute file name and stopped with "file not existing"."""
    import asyncio
    import shutil as _sh

    work = tmp_path / ("long_project_folder_name_" * 2)
    work.mkdir()
    src = work / "run.ts.shy"
    _sh.copy(_SAMPLE_SHY, src)
    wrapper = ShyfemWrapper(SHYELAB.parent.parent)
    opts = build_shyelab_options(operation=op, op_flags=SHYELAB_OPERATIONS[op]["flags"])
    result = asyncio.run(wrapper.run_shyelab(src, work, opts))
    assert result.success, result.stdout[-400:]
    files = name_outputs(result.output_files, src, op)
    if op != "info":
        assert files, f"{op} produced no detected output"
    if op in ("temporal_avg", "time_max"):
        assert (work / f"run.ts.{op}.shy").exists()
