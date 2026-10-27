"""Reading SHYFEM results (the UGRID NetCDF ``shyelab -outformat nc`` writes)
for the results map: mesh, time axis, variables and per-record node values.
Pure data: no Shiny, no rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
import xarray as xr

CURRENT_SPEED = "current_speed"
_U, _V = "u_velocity", "v_velocity"
_CHUNK = 200  # records per read; a 24-year run is ~180 MB per variable
_CF_UNITS = {"1e-3": "psu"}
_NOT_DATA = {"Mesh2", "Mesh2_face_nodes", "Mesh2_node_x", "Mesh2_node_y", "total_depth"}
_NODE_DIMS = ("time", "nMesh2_node")


class NotUgridError(ValueError):
    """The file is not a SHYFEM UGRID results file."""


@dataclass(frozen=True)
class VarInfo:
    name: str
    label: str
    units: str
    has_level: bool


@dataclass
class ResultsFile:
    path: Path
    stamp: tuple[int, int]  # (st_size, st_mtime_ns)
    ds: xr.Dataset
    node_x: np.ndarray
    node_y: np.ndarray
    faces: np.ndarray  # (n_face, 3) int, 0-based
    times: list[datetime]
    n_levels: int
    variables: dict[str, VarInfo]
    has_currents: bool
    _closed: bool = field(default=False, repr=False)
    _ranges: dict[tuple[str, int], tuple[float, float]] = field(default_factory=dict, repr=False)

    def close(self) -> None:
        """Release the file handle; later reads raise instead of re-opening."""
        self._closed = True
        self.ds.close()


def _label(name: str) -> str:
    text = name.replace("_", " ")
    return text[:1].upper() + text[1:]


def open_results(nc_path: Path) -> ResultsFile:
    """Open a results NetCDF; raise ``NotUgridError`` if it has no UGRID mesh."""
    nc_path = Path(nc_path)
    ds = xr.open_dataset(nc_path, cache=False)
    try:
        if not {"Mesh2_face_nodes", "Mesh2_node_x", "Mesh2_node_y"} <= set(ds.variables):
            raise NotUgridError(
                f"Not a SHYFEM mesh file: {nc_path.name} has no UGRID mesh " "(Mesh2_face_nodes)."
            )
        st = nc_path.stat()
        faces = np.asarray(ds["Mesh2_face_nodes"].values).astype(np.int64)
        start = int(ds["Mesh2_face_nodes"].attrs.get("start_index", 1))
        variables: dict[str, VarInfo] = {}
        for name, da in ds.data_vars.items():
            name = str(name)
            if name in _NOT_DATA or da.dims[:2] != _NODE_DIMS:
                continue
            if da.dims[2:] not in ((), ("level",)):
                continue
            units = str(da.attrs.get("units", ""))
            variables[name] = VarInfo(
                name, _label(name), _CF_UNITS.get(units, units), "level" in da.dims
            )
        has_currents = _U in variables and _V in variables
        if has_currents:
            variables[CURRENT_SPEED] = VarInfo(
                CURRENT_SPEED, "Current speed", "m s-1", variables[_U].has_level
            )
        return ResultsFile(
            path=nc_path,
            stamp=(st.st_size, st.st_mtime_ns),
            ds=ds,
            node_x=np.asarray(ds["Mesh2_node_x"].values, dtype=np.float64),
            node_y=np.asarray(ds["Mesh2_node_y"].values, dtype=np.float64),
            faces=faces - start,
            times=[t.astype("datetime64[us]").astype(datetime) for t in ds["time"].values],
            n_levels=int(ds.sizes.get("level", 1)),
            variables=variables,
            has_currents=has_currents,
        )
    except BaseException:
        ds.close()
        raise


def _check_open(rf: ResultsFile) -> None:
    if rf._closed:
        raise ValueError("results file is closed")


def _clamp(i: int, n: int) -> int:
    return max(0, min(int(i), n - 1))


def _read(rf: ResultsFile, var: str, sel: slice | int, level: int) -> np.ndarray:
    """float64 values of ``var`` for time selection ``sel`` at ``level``."""
    da = rf.ds[var]
    if "level" in da.dims:
        da = da.isel(level=_clamp(level, rf.n_levels))
    return np.asarray(da.isel(time=sel).values, dtype=np.float64)


def frame(rf: ResultsFile, var: str, t: int, level: int = 0) -> np.ndarray:
    """Node values of ``var`` at record ``t`` (NaN where the file has fill)."""
    _check_open(rf)
    t = _clamp(t, len(rf.times))
    if var == CURRENT_SPEED:
        u, v = velocity(rf, t, level)
        return np.hypot(u, v)
    return _read(rf, var, t, level)


def velocity(rf: ResultsFile, t: int, level: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Eastward and northward node velocities at record ``t``."""
    _check_open(rf)
    t = _clamp(t, len(rf.times))
    return _read(rf, _U, t, level), _read(rf, _V, t, level)


def value_range(rf: ResultsFile, var: str, level: int = 0) -> tuple[float, float]:
    """nan-min/nan-max of ``var`` over all records at ``level`` (memoised)."""
    _check_open(rf)
    level = _clamp(level, rf.n_levels)
    key = (var, level)
    if key in rf._ranges:
        return rf._ranges[key]
    lo, hi = np.inf, -np.inf
    for a in range(0, len(rf.times), _CHUNK):
        sel = slice(a, a + _CHUNK)
        if var == CURRENT_SPEED:
            vals = np.hypot(_read(rf, _U, sel, level), _read(rf, _V, sel, level))
        else:
            vals = _read(rf, var, sel, level)
        if not np.isnan(vals).all():
            lo = min(lo, float(np.nanmin(vals)))
            hi = max(hi, float(np.nanmax(vals)))
    result = (lo, hi) if lo <= hi else (float("nan"), float("nan"))
    rf._ranges[key] = result
    return result
