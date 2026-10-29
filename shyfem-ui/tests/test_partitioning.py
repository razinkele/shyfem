"""The shyparts command line the wrapper builds (M-15).

These tests pinned ``-weighted`` before ``-np``. shyparts has no such option
(``*** no such option: weighted``, then ``STOP clo_usage``), so they pinned
the broken flag the Partitioning page used to send (M-01). The real usage is
``shyparts [-options] -np N grd-file``; its options are ``-np`` and ``-debug``.
"""

import asyncio
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

REPO = Path(__file__).resolve().parents[2]
_BIN = REPO / "bin" / "shyparts"
SHYPARTS = _BIN if _BIN.exists() else Path(shutil.which("shyparts") or _BIN)


def _capture(monkeypatch, tmp_path):
    captured: dict = {}

    async def fake_run_command(self, exe, args, *a, **kw):
        captured["exe"] = exe
        captured["args"] = list(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ShyfemWrapper, "run_command", fake_run_command)
    return ShyfemWrapper(shyfem_dir=tmp_path), captured


def test_the_command_is_np_then_the_grid(monkeypatch, tmp_path):
    wrapper, captured = _capture(monkeypatch, tmp_path)
    grd = tmp_path / "basin.grd"
    asyncio.run(wrapper.run_shyparts(grd, working_dir=tmp_path, np=4))
    assert captured["exe"] == "shyparts"
    assert captured["args"] == ["-np", "4", str(grd)]


def test_extra_options_go_first_and_the_callers_list_is_not_changed(monkeypatch, tmp_path):
    wrapper, captured = _capture(monkeypatch, tmp_path)
    grd = tmp_path / "basin.grd"
    options = ["-debug"]
    asyncio.run(wrapper.run_shyparts(grd, working_dir=tmp_path, np=2, options=options))
    assert captured["args"] == ["-debug", "-np", "2", str(grd)]
    assert options == ["-debug"]


@pytest.mark.skipif(not SHYPARTS.exists(), reason="needs the built shyparts")
def test_the_real_shyparts_has_no_weighted_option(tmp_path):
    """What the old tests pinned is refused by the real tool, and the run
    counts as failed (X-01: shyparts exits 0 on its usage stop)."""
    shutil.copy(REPO / "testcases" / "examples" / "mar_menor" / "GRID" / "MM_coarse.grd", tmp_path)
    w = ShyfemWrapper(SHYPARTS.parent.parent)
    r = asyncio.run(
        w.run_shyparts(tmp_path / "MM_coarse.grd", tmp_path, np=2, options=["-weighted"])
    )
    assert not r.success
    assert "no such option: weighted" in r.stdout + r.stderr
