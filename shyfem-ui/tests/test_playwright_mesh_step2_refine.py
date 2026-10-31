"""Mesh Builder Step 2: the line and method choices stay after an Apply.

The whole Step 2 panel (line select, smooth method, both sliders) was
rendered by an output that read ``refined_grd``. Apply Smoothing, Apply
Simplification and Reset all change ``refined_grd``, so the panel
re-rendered: the line select snapped back to "All lines" (the next Apply
then changed every line) and the method back to Chaikin.

Named to sort after test_playwright_mesh_creation.py and before
test_playwright_mesh_step4_post_panel.py (byte and locale order): it leaves
an imported boundary and no mesh, and the Step 4 test imports its own.
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


def test_refine_choices_survive_an_apply(pw_page, tmp_path):
    # Two squares (untagged UTM-like metres) -> two boundary lines.
    def square(x0: int) -> list[list[int]]:
        pts = [[x0, 4180000], [x0 + 30000, 4180000], [x0 + 30000, 4210000], [x0, 4210000]]
        return pts + pts[:1]

    boundary = tmp_path / "boundary.geojson"
    boundary.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [square(x0)]},
                    }
                    for x0 in (700000, 800000)
                ],
            }
        )
    )

    _dismiss_modals(pw_page)
    pw_page.locator(".sf-nav-item[data-nav='Mesh Builder']").click(force=True)
    _step(pw_page, "import")
    pw_page.locator(f"{_P}boundary_file").set_input_files(str(boundary))
    # The shared page still shows the previous test's "Loaded: ... 1 lines":
    # wait for text only THIS import produces.
    expect(pw_page.locator(f"{_P}import_result")).to_contain_text(" 2 lines", timeout=15000)

    _step(pw_page, "refine")
    line_select = pw_page.locator(f"{_P}refine_line")
    expect(line_select.locator("option")).to_have_count(3, timeout=10000)  # all + 2
    line_value = line_select.locator("option").nth(1).get_attribute("value")
    assert line_value != "all"
    line_select.select_option(line_value)
    method = pw_page.locator(f"{_P}smooth_method")
    method.select_option("gaussian")
    pw_page.wait_for_timeout(500)

    options = line_select.locator("option")
    first_label = options.nth(1).inner_text()
    second_label = options.nth(2).inner_text()

    pw_page.locator(f"{_P}apply_smooth").click(force=True)
    pw_page.wait_for_timeout(2000)  # a re-render would have reset them by now
    expect(line_select).to_have_value(line_value)
    expect(method).to_have_value("gaussian")

    # Chaikin adds points: the chosen line's label shows its new count, and
    # the other line (not chosen) is untouched.
    method.select_option("chaikin")
    pw_page.wait_for_timeout(500)
    pw_page.locator(f"{_P}apply_smooth").click(force=True)
    expect(options.nth(1)).not_to_have_text(first_label, timeout=10000)
    expect(options.nth(2)).to_have_text(second_label)
    expect(line_select).to_have_value(line_value)
    expect(method).to_have_value("chaikin")

    pw_page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
