"""Mesh Builder Step 4: the Compare Runs choice and typed adjustments stay (M-07).

The Compare Runs radio and the Depth Adjustments inputs were rendered by an
output that read ``staged_grd``. Picking a run or applying an adjustment
changes ``staged_grd``, so the output re-rendered: the radio snapped back to
the newest run and the typed values were emptied.

Named to sort after test_playwright_mesh_creation.py (in byte and locale
order, so a shell glob runs it later too): the shared page has no
way to reset Mesh Builder, and this test leaves it on Step 4 with a mesh,
which the creation tests (which start from Step 1, no mesh) cannot follow.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_P = "#mesh_builder-"


def _step(pw_page, value: str) -> None:
    pw_page.locator(f"{_P}wizard_step input[value='{value}']").click(force=True)
    pw_page.wait_for_timeout(400)


def _interpolate(pw_page, method: str, runs: int) -> None:
    pw_page.locator(f"{_P}bathy_method").select_option(method)
    pw_page.locator(f"{_P}interpolate_btn").click(force=True)
    expect(pw_page.locator(f"{_P}comparison_selector input[type='radio']")).to_have_count(
        runs if runs >= 2 else 0, timeout=20000
    )
    expect(pw_page.locator(f"{_P}adj_min_clamp")).to_be_attached(timeout=20000)


def test_compare_choice_and_adjustments_survive(pw_page, tmp_path):
    # A 30 km square in untagged UTM-like metres (the creation E2E's fixture).
    pts = [[700000, 4180000], [730000, 4180000], [730000, 4210000], [700000, 4210000]]
    boundary = tmp_path / "boundary.geojson"
    boundary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [pts + pts[:1]]},
                    }
                ],
            }
        )
    )
    xyz = tmp_path / "survey.xyz"
    xyz.write_text(
        "".join(
            f"{700000 + i * 3000} {4180000 + j * 3000} {1 + (i * 7 + j * 3) % 11}\n"
            for i in range(11)
            for j in range(11)
        )
    )

    _dismiss_modals(pw_page)
    pw_page.locator(".sf-nav-item[data-nav='Mesh Builder']").click(force=True)
    _step(pw_page, "import")
    pw_page.locator(f"{_P}boundary_file").set_input_files(str(boundary))
    # The shared page may still show an earlier test's import (Step 2's
    # leaves "2 lines"): wait for this one-square boundary's own text.
    expect(pw_page.locator(f"{_P}import_result")).to_contain_text(" 1 lines", timeout=15000)

    _step(pw_page, "mesh")
    pw_page.locator(f"{_P}mesh_method input[value='delaunay_quality']").click(force=True)
    pw_page.locator(f"{_P}max_area").fill("20000000")
    pw_page.locator(f"{_P}generate_mesh").click(force=True)
    expect(pw_page.locator(f"{_P}mesh_stats_display")).to_contain_text("Elements", timeout=20000)

    _step(pw_page, "bathy")
    pw_page.locator(f"{_P}bathy_source input[value='points']").click(force=True)
    pw_page.locator(f"{_P}bathy_file").set_input_files(str(xyz))
    expect(
        pw_page.locator(".shiny-notification").filter(has_text="Loaded 121 bathymetry points")
    ).to_be_visible(timeout=15000)
    pw_page.locator(f"{_P}use_boundary_zero").uncheck()

    _interpolate(pw_page, "linear", runs=1)
    _interpolate(pw_page, "nearest", runs=2)

    radios = pw_page.locator(f"{_P}comparison_selector input[type='radio']")
    expect(radios.nth(1)).to_be_checked()  # newest preselected
    radios.nth(0).check(force=True)  # the older, linear run
    pw_page.wait_for_timeout(1500)  # a re-render would have snapped it back by now
    expect(radios.nth(0)).to_be_checked()
    assert radios.nth(0).get_attribute("value").startswith("linear")

    clamp = pw_page.locator(f"{_P}adj_min_clamp")
    clamp.fill("2.5")
    pw_page.locator(f"{_P}apply_adjustments_btn").click(force=True)
    expect(
        pw_page.locator(".shiny-notification").filter(has_text="Adjustments applied")
    ).to_be_visible(timeout=10000)
    pw_page.wait_for_timeout(1000)
    expect(clamp).to_have_value("2.5")
    expect(radios.nth(0)).to_be_checked()
    # The clamp reached the staged result shown in the stats.
    expect(pw_page.locator(f"{_P}bathy_stats_display")).to_contain_text("2.50")
