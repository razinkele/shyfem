"""Cached ``.shy`` -> NetCDF conversion for the results map.

``shyelab -outformat nc`` converts once; the NetCDF is cached in the viewer's
home (key = resolved path + size + mtime) and trimmed to a size cap, least
recently used first.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from ..config import Config

CACHE_DIRNAME = ".shyfem_viewer_cache"


class ConversionError(RuntimeError):
    """``shyelab`` could not turn a ``.shy`` file into a NetCDF."""


def viewer_cache_dir(user: dict | None, config: Config) -> Path:
    """The viewer's NetCDF cache folder (created)."""
    d = config.user_projects_root(user) / CACHE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reason(stdout: str, stderr: str) -> str:
    lines = [ln.strip() for ln in f"{stdout}\n{stderr}".splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "error" in ln.lower():
            return ln
    return lines[-1] if lines else "no output"


def _evict(cache: Path, keep: Path, source: str, cap: int) -> None:
    """Drop stale entries of ``source``, then the oldest until under ``cap``.

    An entry with no readable ``.src`` sidecar belongs to no source but still
    counts toward the cap and can be evicted.
    """
    entries = []
    for nc in cache.glob("*.nc"):
        if nc == keep:
            continue
        src = nc.with_suffix(".src")
        try:
            try:
                owner = src.read_text()
            except OSError:
                owner = None
            if owner == source:
                nc.unlink(missing_ok=True)
                src.unlink(missing_ok=True)
                continue
            entries.append((nc.stat().st_mtime, nc, src))
        except OSError:
            continue
    total = keep.stat().st_size + sum(nc.stat().st_size for _, nc, _ in entries if nc.exists())
    for _, nc, src in sorted(entries):
        if total <= cap:
            break
        try:
            total -= nc.stat().st_size
            nc.unlink(missing_ok=True)
            src.unlink(missing_ok=True)
        except OSError:
            pass


async def netcdf_for(path: Path, user: dict | None, config: Config, wrapper) -> Path:
    """Return a NetCDF for ``path``: a ``.nc`` as is, a ``.shy`` converted once.

    Raises:
        ConversionError: shyelab failed (it exits 0 on most failures, so the
            test is whether it produced a non-empty ``out.nc``).
    """
    path = Path(path)
    if path.suffix.lower() == ".nc":
        return path
    real = path.resolve()
    try:
        st = real.stat()
    except OSError as e:
        raise ConversionError(f"{path.name}: file not found") from e
    key = hashlib.sha1(f"{real}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    cache = viewer_cache_dir(user, config)
    entry = cache / f"{key}.nc"
    if entry.exists():
        os.utime(entry)
        return entry

    tmp = Path(tempfile.mkdtemp(dir=cache, prefix="tmp-"))
    try:
        # shyelab reads at most 80 characters of a path: give it a short name.
        os.symlink(real, tmp / "in.shy")
        try:
            res = await wrapper.run_command("shyelab", ["-outformat", "nc", "in.shy"], tmp)
        except FileNotFoundError as e:
            raise ConversionError(f"Cannot convert {path.name}: shyelab not found ({e})") from e
        out = tmp / "out.nc"
        # A killed or timed-out shyelab can leave a partial out.nc behind.
        if res.return_code != 0 or not out.is_file() or out.stat().st_size == 0:
            reason = _reason(res.stdout, res.stderr)
            if res.return_code != 0 and reason == "no output":
                reason = f"shyelab exited with code {res.return_code}"
            raise ConversionError(f"Cannot convert {path.name}: {reason}")
        os.replace(out, entry)
        (cache / f"{key}.src").write_text(str(real))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    _evict(cache, entry, str(real), max(config.viewer_cache_max_mb, 0) * 1024 * 1024)
    return entry
