"""Writes a tiny NetCDF in the exact layout ``shyelab -outformat nc`` produces
(UGRID-1.0: 1-based ``Mesh2_face_nodes``, ``standard_name`` but no
``long_name``, ``_FillValue`` -999) for the results-map tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

N_NODE = 5
N_FACE = 3
FILL = -999.0


def write_ugrid(
    path: Path,
    *,
    n_time: int = 4,
    kind: str = "hydro",
    fill_at: int | None = None,
    const: float | dict[str, float] | None = None,
    n_levels: int = 1,
) -> Path:
    """Write a 5-node, 3-face UGRID results file and return ``path``.

    ``hydro`` holds ``water_level`` (2-D) and ``u_velocity``/``v_velocity``;
    ``ts`` holds ``salinity``/``temperature``. Values vary with time, node and
    level unless ``const`` is given: a float sets every variable, a dict sets
    the named ones (the others keep their varying values). ``fill_at`` writes
    that node as -999 in every variable and record.
    """
    t = np.arange(n_time, dtype=float)[:, None, None]
    node = np.arange(N_NODE, dtype=float)[None, :, None]
    lev = np.arange(n_levels, dtype=float)[None, None, :]
    shape = (n_time, N_NODE, n_levels)

    if kind == "hydro":
        specs = {
            "water_level": ("m", "water_surface_height_above_reference_datum", False),
            "u_velocity": ("m s-1", "eastward_sea_water_velocity", True),
            "v_velocity": ("m s-1", "northward_sea_water_velocity", True),
        }
        base = {
            "water_level": 0.1 * t + 0.01 * node + 0.0 * lev,
            "u_velocity": 0.2 * t + 0.01 * node + 0.05 * lev,
            "v_velocity": 0.3 * t + 0.02 * node + 0.05 * lev,
        }
    elif kind == "ts":
        specs = {
            "salinity": ("1e-3", "sea_water_salinity", True),
            "temperature": ("degC", "sea_water_temperature", True),
        }
        base = {
            "salinity": 30 + t + 0.1 * node + 0.5 * lev,
            "temperature": 10 + 0.5 * t + 0.1 * node + 0.2 * lev,
        }
    else:
        raise ValueError(f"unknown kind: {kind!r}")

    data = {}
    for name, (units, std, has_level) in specs.items():
        arr = np.broadcast_to(base[name], shape).copy()
        if isinstance(const, dict):
            if name in const:
                arr[:] = const[name]
        elif const is not None:
            arr[:] = const
        if fill_at is not None:
            arr[:, fill_at, :] = FILL
        attrs = {"units": units, "standard_name": std}
        if has_level:
            data[name] = (("time", "nMesh2_node", "level"), arr.astype("f4"), attrs)
        else:
            data[name] = (("time", "nMesh2_node"), arr[:, :, 0].astype("f4"), attrs)

    faces = np.array([[1, 2, 3], [2, 3, 4], [3, 4, 5]], dtype="i4")
    ds = xr.Dataset(
        {
            "Mesh2": ((), np.int32(0), {"cf_role": "mesh_topology"}),
            "Mesh2_face_nodes": (
                ("nMesh2_face", "Three"),
                faces,
                {"cf_role": "face_node_connectivity", "start_index": np.int32(1)},
            ),
            "Mesh2_node_x": (
                ("nMesh2_node",),
                np.linspace(20.0, 21.0, N_NODE, dtype="f4"),
                {"units": "degrees_east", "standard_name": "longitude"},
            ),
            "Mesh2_node_y": (
                ("nMesh2_node",),
                np.linspace(55.0, 55.5, N_NODE, dtype="f4"),
                {"units": "degrees_north", "standard_name": "latitude"},
            ),
            "total_depth": (
                ("nMesh2_node",),
                np.linspace(1.0, 5.0, N_NODE, dtype="f4"),
                {"units": "m"},
            ),
            **data,
        },
        coords={
            "level": ("level", np.arange(n_levels, dtype="f4") + 1.0),
            "time": (
                "time",
                np.datetime64("2001-01-01T00:00:00", "ns")
                + np.arange(n_time) * np.timedelta64(6, "h"),
            ),
        },
    )
    enc = {name: {"_FillValue": np.float32(FILL)} for name in specs}
    for name in ("Mesh2_node_x", "Mesh2_node_y", "total_depth", "level"):
        enc[name] = {"_FillValue": None}
    enc["Mesh2_face_nodes"] = {"_FillValue": None}
    ds.to_netcdf(path, encoding=enc)
    return Path(path)
