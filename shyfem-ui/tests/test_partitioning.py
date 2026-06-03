"""Tests for partitioning page and wrapper integration."""

import asyncio
from unittest.mock import MagicMock


def test_run_shyparts_passes_weighted_flag(monkeypatch, tmp_path):
    """When the weighted checkbox is True, '-weighted' must appear in the
    options list passed to wrapper.run_command, BEFORE '-np'."""
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
    wrapper = ShyfemWrapper(shyfem_dir=tmp_path)
    captured: dict = {}

    async def fake_run_command(self, exe, args, *a, **kw):
        captured["exe"] = exe
        captured["args"] = list(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ShyfemWrapper, "run_command", fake_run_command)

    asyncio.run(wrapper.run_shyparts(
        bas_file=tmp_path / "foo.bas",
        working_dir=tmp_path,
        np=4,
        options=["-weighted"],
    ))

    assert captured["exe"] == "shyparts"
    assert "-weighted" in captured["args"]
    assert captured["args"].index("-weighted") < captured["args"].index("-np")


def test_run_shyparts_no_weighted_when_disabled(monkeypatch, tmp_path):
    """When options is None, '-weighted' must NOT appear."""
    from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper
    wrapper = ShyfemWrapper(shyfem_dir=tmp_path)
    captured: dict = {}

    async def fake_run_command(self, exe, args, *a, **kw):
        captured["args"] = list(args)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ShyfemWrapper, "run_command", fake_run_command)

    asyncio.run(wrapper.run_shyparts(
        bas_file=tmp_path / "foo.bas",
        working_dir=tmp_path,
        np=4,
        options=None,
    ))

    assert "-weighted" not in captured["args"]
