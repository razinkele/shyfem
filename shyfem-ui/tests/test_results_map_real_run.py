"""Real-binary check of the results map data path (shyelab -> NetCDF -> colours)."""

import asyncio
import math
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from shyfem_ui.components.results_map_layers import NeedsProjection, mesh_lonlat, node_colors
from shyfem_ui.config import Config
from shyfem_ui.services.results_cache import netcdf_for
from shyfem_ui.services.results_data import frame, open_results, value_range
from shyfem_ui.services.shyfem_wrapper import ShyfemWrapper

_SAMPLES = Path(os.environ.get("SHYFEM_SAMPLES_DIR", "/home/razinka/shyfem/testcases/examples"))
_TS = _SAMPLES / "mar_menor" / "mm_hyd_assim.ts.shy"
_REAL = shutil.which("shyelab")

pytestmark = pytest.mark.skipif(
    not (_REAL and _TS.exists()),
    reason="needs shyelab on PATH and the mar_menor sample .shy files",
)


def test_mar_menor_run_converts_and_colours_every_record(tmp_path):
    for d in ("users", "work", "shyfem", "proj"):
        (tmp_path / d).mkdir()
    cfg = Config(
        _env_file=None,
        deployment_mode="local",
        user_data_root=tmp_path / "users",
        work_dir=tmp_path / "work",
        shyfem_dir=tmp_path / "shyfem",
        default_admin_password="strongpass123",
    )
    src = tmp_path / "proj" / _TS.name
    shutil.copy(_TS, src)
    wrapper = ShyfemWrapper(Path(_REAL).absolute().parent.parent)

    nc = asyncio.run(netcdf_for(src, None, cfg, wrapper))
    rf = open_results(nc)
    try:
        with pytest.raises(NeedsProjection):
            mesh_lonlat(rf, None)
        lonlat = mesh_lonlat(rf, 32630)
        assert lonlat.shape == (len(rf.node_x), 2)
        assert np.all((lonlat[:, 0] > -1.0) & (lonlat[:, 0] < 0.0))
        assert np.all((lonlat[:, 1] > 37.0) & (lonlat[:, 1] < 38.5))

        lo, hi = value_range(rf, "salinity")
        assert math.isfinite(lo) and math.isfinite(hi) and lo <= hi
        for t in range(len(rf.times)):
            vals = frame(rf, "salinity", t)
            colors = node_colors(vals, lo, hi, "viridis")
            assert len(colors) == len(vals)
    finally:
        rf.close()
