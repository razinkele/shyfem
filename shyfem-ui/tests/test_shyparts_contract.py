"""M-01: the Partitioning page must match the real shyparts.

shyparts takes a .grd (`shyparts -np N grd-file`); the page gave it the
basin and the option -weighted, which does not exist. It writes
<grd>.<np>.node.grd / <grd>.<np>.elem.grd next to the input grid and
partition.<np>.txt in its working folder; the page looked for
partition.NNNN.par files that shyparts never writes. And it exits 9 when the
grid is partitioned with connectivity warnings it says "can be ignored",
which the page reported as a failure.
"""

import asyncio
import shutil
from pathlib import Path

import pytest

from shyfem_ui.services.partitioning_logic import (
    analyze_partitions,
    collect_shyparts_outputs,
    stage_grid,
)
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

REPO = Path(__file__).resolve().parents[2]
MM = REPO / "testcases" / "examples" / "mar_menor" / "GRID"
_BIN = REPO / "bin" / "shyparts"
SHYPARTS = _BIN if _BIN.exists() else Path(shutil.which("shyparts") or _BIN)


def test_stats_and_map_come_from_the_real_elem_grd():
    stats, pmap = analyze_partitions(MM / "MM_coarse.4.elem.grd")
    assert stats["num_partitions"] == 4
    assert stats["elements_per_partition"] == [478, 549, 594, 924]
    assert len(pmap) == 2545 and set(pmap.values()) == {0, 1, 2, 3}


def test_a_missing_elem_grd_gives_empty_stats(tmp_path):
    stats, pmap = analyze_partitions(tmp_path / "nope.4.elem.grd")
    assert stats["elements_per_partition"] == [] and pmap == {}


def test_a_grid_elsewhere_is_copied_into_the_output_folder(tmp_path):
    """The input is only read-checked (shared project, bundled sample), and
    shyparts writes next to its input: it must run on a copy in the
    write-checked output folder, never in place."""
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    grd = src / "basin.grd"
    grd.write_text("grid")
    staged, created = stage_grid(grd, out)
    assert staged == out / "basin.grd" and created and staged.read_text() == "grid"
    assert stage_grid(out / "basin.grd", out) == (out / "basin.grd", False)


def test_a_different_grid_of_the_same_name_is_not_overwritten(tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "basin.grd").write_text("new")
    (out / "basin.grd").write_text("someone's own")
    with pytest.raises(ValueError):
        stage_grid(src / "basin.grd", out)
    assert (out / "basin.grd").read_text() == "someone's own"


def test_outputs_are_only_listed_from_the_output_folder(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for n in ("basin.3.node.grd", "basin.3.elem.grd", "partition.3.txt"):
        (out / n).write_text("x")
    files = collect_shyparts_outputs(out / "basin.grd", out, 3)
    assert sorted(Path(f).name for f in files) == [
        "basin.3.elem.grd",
        "basin.3.node.grd",
        "partition.3.txt",
    ]


def _fake(tmp_path, tool, rc, text):
    w = ShyfemWrapper(tmp_path)
    w.bin_dir.mkdir(parents=True, exist_ok=True)
    exe = w.bin_dir / tool
    exe.write_text(f"#!/bin/bash\necho '{text}'\nexit {rc}\n")
    exe.chmod(0o755)
    return w


def test_shyparts_exit_9_with_ignorable_warnings_is_a_success(tmp_path):
    w = _fake(tmp_path, "shyparts", 9, " (errors can be ignored)")
    r = asyncio.run(w.run_command("shyparts", ["-np", "2", "x.grd"], tmp_path))
    assert r.success and r.return_code == 9


def test_exit_9_is_still_a_failure_for_other_tools(tmp_path):
    w = _fake(tmp_path, "shypre", 9, " (errors can be ignored)")
    assert not asyncio.run(w.run_command("shypre", ["x.grd"], tmp_path)).success


def test_the_page_runs_shyparts_on_the_grd_without_invented_options():
    import inspect

    from shyfem_ui.pages import partitioning

    src = inspect.getsource(partitioning)
    assert "-weighted" not in src and '"weighted"' not in src
    assert "bas_path" not in src, "shyparts takes a .grd, not the basin"
    run = src[src.index("async def _run_shyparts") : src.index("def _analyze_partitions")]
    assert "input.grd_path()" in run and "collect_shyparts_outputs(" in run
    assert run.index("stage_grid(") < run.index("wrapper.run_shyparts("), "never partition in place"
    assert "staged.unlink(" in run


@pytest.mark.skipif(not SHYPARTS.exists(), reason="needs the built shyparts")
def test_the_real_binary_partitions_and_the_page_reads_it(tmp_path):
    """With the input folder read-only, everything still lands in the output
    folder: nothing is written next to the input."""
    src, out = tmp_path / "grid", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    grd = src / "MM_coarse.grd"
    shutil.copy(MM / "MM_coarse.grd", grd)
    src.chmod(0o555)
    try:
        staged, created = stage_grid(grd, out)
        w = ShyfemWrapper(SHYPARTS.parent.parent)
        r = asyncio.run(w.run_shyparts(staged, out, np=2))
        assert r.success, r.stdout[-400:]
        assert sorted(p.name for p in src.iterdir()) == ["MM_coarse.grd"]
    finally:
        src.chmod(0o755)
    files = collect_shyparts_outputs(staged, out, 2)
    assert any(f.endswith("MM_coarse.2.elem.grd") for f in files)
    stats, pmap = analyze_partitions(out / "MM_coarse.2.elem.grd")
    assert sum(stats["elements_per_partition"]) == 2545 == len(pmap)


def test_exit_9_with_a_fatal_stop_in_the_output_still_fails(tmp_path):
    w = _fake(tmp_path, "shyparts", 9, "STOP error stop read_grd: cannot read file")
    assert not asyncio.run(w.run_command("shyparts", ["-np", "2", "x.grd"], tmp_path)).success
