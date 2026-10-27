"""The .shy -> NetCDF conversion cache behind the results map."""

import asyncio
import os
import shutil
from pathlib import Path

import pytest

from shyfem_ui.config import Config
from shyfem_ui.services.results_cache import (
    ConversionError,
    netcdf_for,
    viewer_cache_dir,
)
from shyfem_ui.services.shyfem_wrapper import CommandResult, ShyfemWrapper
from tests._ugrid_fixture import write_ugrid

ALICE = {"id": 2, "username": "alice", "role": "user"}


def _cfg(tmp_path, mode="local", **kw):
    for d in ("users", "work", "shyfem"):
        (tmp_path / d).mkdir(exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode=mode,
        user_data_root=tmp_path / "users",
        work_dir=tmp_path / "work",
        shyfem_dir=tmp_path / "shyfem",
        default_admin_password="strongpass123",
        **kw,
    )


class FakeShyelab(ShyfemWrapper):
    """Records each call; writes ``out.nc`` (or not) like shyelab does."""

    def __init__(self, *, write=True, success=True, stdout="", raises=None, pad=0):
        super().__init__(Path("/nonexistent"))
        self.calls: list[list[str]] = []
        self.links: list[Path] = []
        self.write, self.success, self.stdout = write, success, stdout
        self.raises, self.pad = raises, pad

    async def run_command(self, tool_name, args, cwd, *a, **k):
        assert tool_name == "shyelab"
        self.calls.append(list(args))
        self.links.append(Path(cwd) / "in.shy")
        self.link_target = os.readlink(Path(cwd) / "in.shy")
        if self.raises:
            raise self.raises
        if self.write:
            out = write_ugrid(Path(cwd) / "out.nc")
            if self.pad:
                with open(out, "ab") as f:
                    f.write(b"\0" * self.pad)
        return CommandResult(
            self.success, 0 if self.success else 1, self.stdout, "", "shyelab", str(cwd)
        )


def _src(tmp_path, name="run.ts.shy", data=b"shy"):
    d = tmp_path / "proj"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(data)
    return p


def _go(p, cfg, w, user=None):
    return asyncio.run(netcdf_for(p, user, cfg, w))


def test_nc_is_returned_as_is(tmp_path):
    cfg = _cfg(tmp_path)
    nc = write_ugrid(tmp_path / "a.nc")
    w = FakeShyelab()
    assert _go(nc, cfg, w) == nc
    assert w.calls == []


def test_shy_is_converted_once_and_cached(tmp_path):
    cfg, w = _cfg(tmp_path), FakeShyelab()
    src = _src(tmp_path)
    before = sorted(p.name for p in src.parent.iterdir())
    a, b = _go(src, cfg, w), _go(src, cfg, w)
    assert a == b and a.exists() and len(w.calls) == 1
    assert viewer_cache_dir(None, cfg) in a.parents
    assert sorted(p.name for p in src.parent.iterdir()) == before


def test_shyelab_gets_a_short_name_in_its_folder(tmp_path):
    cfg, w = _cfg(tmp_path), FakeShyelab()
    src = _src(tmp_path)
    _go(src, cfg, w)
    assert w.calls == [["-outformat", "nc", "in.shy"]]
    assert w.links[0].name == "in.shy"
    assert Path(w.link_target) == src.resolve()


def test_rerun_invalidates_the_cache(tmp_path):
    cfg, w = _cfg(tmp_path), FakeShyelab()
    src = _src(tmp_path)
    old = _go(src, cfg, w)
    src.write_bytes(b"a longer rewritten file")
    new = _go(src, cfg, w)
    assert len(w.calls) == 2 and new != old
    assert not old.exists() and not old.with_suffix(".src").exists()


@pytest.mark.parametrize(
    "kw, quoted",
    [
        (
            dict(
                write=False,
                success=False,
                stdout="x\nSTOP error stop shyelab: file not existing\n",
            ),
            "STOP error stop shyelab: file not existing",
        ),
        (
            dict(write=False, stdout="a\nError: NetCDF: Not a valid ID\n\n"),
            "Error: NetCDF: Not a valid ID",
        ),
        (
            dict(
                write=False,
                stdout="error reading file, ierr = -1\nfile = in.shy\n",
            ),
            "error reading file, ierr = -1",
        ),
        (dict(write=False, stdout="hello\nfile = in.shy\n"), "file = in.shy"),
        (dict(raises=FileNotFoundError("nope")), "shyelab not found"),
    ],
)
def test_failed_conversion_raises_and_leaves_no_entry(tmp_path, kw, quoted):
    cfg, w = _cfg(tmp_path), FakeShyelab(**kw)
    src = _src(tmp_path, "weird.lgr.shy")
    with pytest.raises(ConversionError) as e:
        _go(src, cfg, w)
    msg = str(e.value)
    assert "weird.lgr.shy" in msg and quoted in msg
    assert "in.shy" not in msg.replace("file = in.shy", "")
    assert list(viewer_cache_dir(None, cfg).iterdir()) == []


def test_killed_shyelab_with_partial_out_nc_is_a_failure(tmp_path):
    cfg = _cfg(tmp_path)

    class Killed(FakeShyelab):
        async def run_command(self, tool_name, args, cwd, *a, **k):
            write_ugrid(Path(cwd) / "out.nc")
            return CommandResult(False, -15, "", "", "shyelab", str(cwd))

    with pytest.raises(ConversionError, match="code -15"):
        _go(_src(tmp_path), cfg, Killed())
    assert list(viewer_cache_dir(None, cfg).iterdir()) == []


def test_missing_source_is_a_conversion_error(tmp_path):
    with pytest.raises(ConversionError, match="gone.shy: file not found"):
        _go(tmp_path / "gone.shy", _cfg(tmp_path), FakeShyelab())


def test_cancelled_conversion_leaves_nothing(tmp_path):
    cfg = _cfg(tmp_path)

    class Hang(FakeShyelab):
        async def run_command(self, tool_name, args, cwd, *a, **k):
            await asyncio.Event().wait()

    async def go():
        t = asyncio.create_task(netcdf_for(_src(tmp_path), None, cfg, Hang()))
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(go())
    assert list(viewer_cache_dir(None, cfg).iterdir()) == []


def test_an_orphan_entry_without_src_is_counted_and_evictable(tmp_path):
    cfg = _cfg(tmp_path, viewer_cache_max_mb=1)
    orphan = viewer_cache_dir(None, cfg) / "deadbeef.nc"
    orphan.write_bytes(b"\0" * 900_000)
    out = _go(_src(tmp_path), cfg, FakeShyelab(pad=600_000))
    assert out.exists() and not orphan.exists()


def test_empty_out_nc_is_a_failure(tmp_path):
    cfg = _cfg(tmp_path)

    class Empty(FakeShyelab):
        async def run_command(self, tool_name, args, cwd, *a, **k):
            (Path(cwd) / "out.nc").write_bytes(b"")
            return CommandResult(True, 0, "ok\n", "", "shyelab", str(cwd))

    with pytest.raises(ConversionError):
        _go(_src(tmp_path), cfg, Empty())
    assert list(viewer_cache_dir(None, cfg).iterdir()) == []


def test_cache_is_bounded(tmp_path):
    cfg = _cfg(tmp_path, viewer_cache_max_mb=1)
    w = FakeShyelab(pad=600_000)
    last = None
    for i in range(3):
        last = _go(_src(tmp_path, f"r{i}.shy"), cfg, w)
    total = sum(p.stat().st_size for p in viewer_cache_dir(None, cfg).iterdir())
    assert total <= 1024 * 1024 and last.exists()


def test_an_entry_bigger_than_the_cap_is_still_returned(tmp_path):
    cfg = _cfg(tmp_path, viewer_cache_max_mb=1)
    out = _go(_src(tmp_path), cfg, FakeShyelab(pad=2 * 1024 * 1024))
    assert out.exists()


def test_cache_is_in_the_viewers_home_in_server_mode(tmp_path):
    cfg = _cfg(tmp_path, mode="server")
    out = _go(_src(tmp_path), cfg, FakeShyelab(), ALICE)
    home = (cfg.user_data_root / "alice").resolve()
    assert viewer_cache_dir(ALICE, cfg) == home / ".shyfem_viewer_cache"
    assert viewer_cache_dir(ALICE, cfg) in out.parents


# --- real binary ------------------------------------------------------------

_SAMPLES = Path(os.environ.get("SHYFEM_SAMPLES_DIR", "/home/razinka/shyfem/testcases/examples"))
_TS = _SAMPLES / "mar_menor" / "mm_hyd_assim.ts.shy"
_LGR = _SAMPLES / "mar_menor" / "mm_lgr.lgr.shy"
_REAL = shutil.which("shyelab")
_skip = pytest.mark.skipif(
    not (_REAL and _TS.exists() and _LGR.exists()),
    reason="needs shyelab on PATH and the mar_menor sample .shy files",
)


def _real(tmp_path):
    shyfem_dir = Path(_REAL).absolute().parent.parent
    return ShyfemWrapper(shyfem_dir)


@_skip
def test_real_shyelab_converts_a_long_path(tmp_path):
    from shyfem_ui.services.results_data import open_results

    d = tmp_path / ("a" * 40) / ("b" * 40) / "src"
    d.mkdir(parents=True)
    src = d / _TS.name
    shutil.copy(_TS, src)
    assert len(str(src)) > 80
    nc = _go(src, _cfg(tmp_path), _real(tmp_path))
    rf = open_results(nc)
    try:
        assert {"salinity", "temperature"} <= set(rf.variables)
    finally:
        rf.close()


@_skip
def test_real_shyelab_failure_is_a_conversion_error(tmp_path):
    src = tmp_path / _LGR.name
    shutil.copy(_LGR, src)
    with pytest.raises(ConversionError, match="mm_lgr.lgr.shy"):
        _go(src, _cfg(tmp_path), _real(tmp_path))
