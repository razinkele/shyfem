"""Grid and bathymetry loaders still work after moving off the loop (M-11).

Runs against the real grid_prep_server and mesh_builder_server: the Grid
Prep Inspect tab (now an async render) shows the grid's statistics, and a
bathymetry points file uploaded on Mesh Builder is loaded.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect

_GRD = Path(__file__).resolve().parents[2] / "testcases/examples/mar_menor/GRID/MM_coarse.grd"


@pytest.mark.e2e
def test_grid_prep_inspect_shows_statistics(pw_page, live_server):
    if not _GRD.is_file():
        pytest.skip(f"sample grid missing: {_GRD}")
    pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
    pw_page.locator("#grid_prep-grd_file-file_input").set_input_files(str(_GRD))
    pw_page.locator("#sf-page-Grid-Prep a[role='tab'][data-value='Inspect']").click()
    inspect = pw_page.locator("#grid_prep-grid_inspect")
    expect(inspect).to_contain_text("Minimum Angle Analysis", timeout=15000)
    expect(inspect).not_to_contain_text("Load a grid file")
    pw_page.locator("#sf-page-Grid-Prep a[role='tab']:has-text('Interactive Map')").click()


@pytest.mark.e2e
def test_mesh_builder_bathymetry_points_load(pw_page, live_server, tmp_path):
    xyz = tmp_path / "survey.xyz"
    xyz.write_text(
        "".join(f"{12 + i * 1e-3} {45 + (i % 50) * 1e-3} {1 + i % 9}\n" for i in range(5000))
    )
    pw_page.locator(".sf-nav-item[data-nav='Mesh Builder']").click(force=True)
    pw_page.locator("#mesh_builder-bathy_file").set_input_files(str(xyz))
    expect(
        pw_page.locator(".shiny-notification").filter(has_text="Loaded 5000 bathymetry points")
    ).to_be_visible(timeout=15000)
