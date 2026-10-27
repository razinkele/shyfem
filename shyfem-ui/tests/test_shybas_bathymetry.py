"""M-03: the Mesh Builder "shybas" bathymetry method must actually run shybas.

It passed a non-existent relative "bathy_temp.xyz" (the loaded points were
never written), ran in a work folder shared by every user, and read back
_mesh_temp.grd/.bas -- but shybas writes basbathy.grd. shybas also needs the
bathymetry as a GRD of depth points (a plain xyz, or any comment line, is a
"Read error" it reports with exit 0 and no output), and with -node it
refuses a mesh whose elements carry depths. Each of those left the mesh
unchanged while the page said "Bathymetry interpolated".
"""

import asyncio
import inspect
import shutil
from pathlib import Path

import numpy as np
import pytest

from shyfem_ui.services.mesh_builder import interpolate_bathymetry_shybas
from shyfem_ui.services.parser_grd import GrdParser
from shyfem_ui.services.shyfem_wrapper import CommandResult, ShyfemWrapper

REPO = Path(__file__).resolve().parents[2]
MM = REPO / "testcases" / "examples" / "mar_menor"
_BIN = REPO / "bin" / "shybas"
SHYBAS = _BIN if _BIN.exists() else Path(shutil.which("shybas") or _BIN)


def _mesh():
    return GrdParser.parse_file(MM / "GRID" / "MM_coarse.grd")


def _points():
    return np.loadtxt(MM / "mar_menor_bathymetry.xyz", comments="#")


class _FakeWrapper:
    def __init__(self, write_output=True):
        self.calls = []
        self.write_output = write_output

    async def run_command(self, tool, args, cwd, *a, **k):
        cwd = Path(cwd)
        self.calls.append((tool, list(args), cwd))
        self.bathy = (cwd / "bathy.grd").read_text()
        self.mesh = GrdParser.parse_file(cwd / "mesh.grd")
        if self.write_output:
            out = GrdParser.parse_file(cwd / "mesh.grd")
            for n in out.nodes.values():
                n.depth = 7.0
            GrdParser.save(out, cwd / "basbathy.grd")
        return CommandResult(
            success=True,
            return_code=0,
            stdout=" Read error on line 1",
            stderr="",
            command="shybas",
            working_dir=str(cwd),
        )


def test_it_runs_shybas_on_the_loaded_points_and_reads_basbathy():
    w = _FakeWrapper()
    got = asyncio.run(interpolate_bathymetry_shybas(_mesh(), _points(), w))
    tool, args, cwd = w.calls[0]
    assert tool == "shybas" and args == ["-bfile", "bathy.grd", "-node", "mesh.grd"]
    lines = w.bathy.splitlines()
    assert len(lines) == len(_points()) and not any(line.startswith("#") for line in lines)
    assert lines[0].split()[:3] == ["1", "1", "0"]
    # The core reads plain numbers (NumPy 2's repr is "np.float64(...)").
    first = [float(t) for t in lines[0].split()[3:6]]
    assert first == _points()[0].tolist()
    assert all(e.depth is None for e in w.mesh.elements.values()), "-node refuses element depths"
    assert all(n.depth == 7.0 for n in got.nodes.values())
    assert set(got.elements) == set(_mesh().elements)
    assert not cwd.exists(), "a private temporary folder, removed afterwards"


def test_no_output_is_an_error_not_an_unchanged_mesh():
    with pytest.raises(RuntimeError, match="Read error"):
        asyncio.run(interpolate_bathymetry_shybas(_mesh(), _points(), _FakeWrapper(False)))


def test_the_page_passes_the_loaded_points():
    from shyfem_ui.pages import mesh_builder

    src = inspect.getsource(mesh_builder)
    assert "bathy_temp.xyz" not in src
    assert "interpolate_bathymetry_shybas(grd, data, wrapper)" in src


@pytest.mark.skipif(not SHYBAS.exists(), reason="needs the built shybas")
def test_the_real_binary_interpolates_every_node():
    w = ShyfemWrapper(SHYBAS.parent.parent)
    got = asyncio.run(interpolate_bathymetry_shybas(_mesh(), _points(), w))
    depths = np.array([n.depth for n in got.nodes.values()])
    assert len(depths) == 1402 and not np.isnan(depths.astype(float)).any()
    z = _points()[:, 2]
    assert z.min() - 1 <= depths.min() and depths.max() <= z.max() + 1
