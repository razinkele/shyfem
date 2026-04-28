"""E2E mesh creation tests — boundary upload, method modes, constraint flow.

Tests run in file order against a single shared Shiny page (per the project's
playwright fixture conventions).  Group structure:

  1. TestMeshBuilderUI       — input visibility per triangulation method
                                (no boundary required)
  2. TestMeshCreationFlow    — boundary upload → step 3 → constraint scenarios
                                (cumulative; later tests depend on earlier
                                state)

Run with:
  /opt/micromamba/envs/shiny/bin/python -m pytest tests/test_playwright_mesh_creation.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import _dismiss_modals

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("live_server")]

_TAB = ".sf-nav-item[data-nav='{name}']"


def _switch_tab(pw_page, name: str) -> None:
    _dismiss_modals(pw_page)
    pw_page.locator(_TAB.format(name=name)).click(force=True)
    pw_page.wait_for_timeout(800)


def _wait_for_inputs(pw_page, selectors: list[str], timeout: int = 5000) -> None:
    """Wait until every selector is attached to the DOM (not necessarily visible)."""
    for sel in selectors:
        pw_page.locator(sel).wait_for(state="attached", timeout=timeout)


@pytest.fixture(scope="module")
def boundary_geojson(tmp_path_factory) -> Path:
    """Write a small square boundary GeoJSON in UTM-like coordinates.

    Sized so triangulation produces a non-trivial (but fast) mesh — area
    around 9e8 in metric units, so max_area=1e8 yields ~9 elements (estimate),
    and the actual count after quality refinement should be under 50.
    """
    pts = [
        [700000.0, 4180000.0],
        [730000.0, 4180000.0],
        [730000.0, 4210000.0],
        [700000.0, 4210000.0],
        [700000.0, 4180000.0],
    ]
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [pts]},
                "properties": {},
            }
        ],
    }
    path = tmp_path_factory.mktemp("mesh_e2e") / "boundary.geojson"
    path.write_text(json.dumps(geojson))
    return path


# ---------------------------------------------------------------------------
# Group 1: UI — method-conditional input visibility (no boundary required)
# ---------------------------------------------------------------------------


class TestMeshBuilderUI:
    """Inputs per triangulation method render correctly."""

    def test_navigate_to_mesh_builder(self, pw_page):
        _switch_tab(pw_page, "Mesh Builder")
        # Step 1 heading should be present in the DOM
        pw_page.locator("text=Step 1: Import Boundaries").wait_for(
            state="visible", timeout=10000
        )

    def test_navigate_to_step3(self, pw_page):
        """Click 'Generate Mesh' wizard radio."""
        # Use the radio with value=mesh — Shiny renders these as
        # <input type="radio" value="mesh"> inside #mesh_builder-wizard_step
        pw_page.locator(
            "#mesh_builder-wizard_step input[value='mesh']"
        ).click(force=True)
        pw_page.wait_for_timeout(800)
        pw_page.locator("text=Step 3: Generate Mesh").wait_for(
            state="visible", timeout=5000
        )

    def test_quality_method_shows_all_four_inputs(self, pw_page):
        """Quality mode: max_area, min_area, min_angle, max_elements all visible."""
        # Default is delaunay_quality — verify by selecting explicitly
        pw_page.locator(
            "#mesh_builder-mesh_method input[value='delaunay_quality']"
        ).click(force=True)
        pw_page.wait_for_timeout(500)
        _wait_for_inputs(pw_page, [
            "#mesh_builder-max_area",
            "#mesh_builder-min_area",
            "#mesh_builder-min_angle",
            "#mesh_builder-max_elements",
        ])

    def test_conforming_mode_shows_angle_and_elements_only(self, pw_page):
        """Conforming mode hides Max/Min area inputs."""
        pw_page.locator(
            "#mesh_builder-mesh_method input[value='delaunay_conforming']"
        ).click(force=True)
        pw_page.wait_for_timeout(500)
        _wait_for_inputs(pw_page, [
            "#mesh_builder-min_angle",
            "#mesh_builder-max_elements",
        ])
        assert pw_page.locator("#mesh_builder-max_area").count() == 0
        assert pw_page.locator("#mesh_builder-min_area").count() == 0

    def test_minimal_mode_shows_only_max_elements(self, pw_page):
        """Minimal mode hides angle and area inputs."""
        pw_page.locator(
            "#mesh_builder-mesh_method input[value='delaunay_minimal']"
        ).click(force=True)
        pw_page.wait_for_timeout(500)
        _wait_for_inputs(pw_page, ["#mesh_builder-max_elements"])
        assert pw_page.locator("#mesh_builder-min_angle").count() == 0
        assert pw_page.locator("#mesh_builder-max_area").count() == 0
        assert pw_page.locator("#mesh_builder-min_area").count() == 0

    def test_back_to_quality_for_remaining_tests(self, pw_page):
        """Reset to quality mode so the next test class can use all inputs."""
        pw_page.locator(
            "#mesh_builder-mesh_method input[value='delaunay_quality']"
        ).click(force=True)
        pw_page.wait_for_timeout(500)
        _wait_for_inputs(pw_page, ["#mesh_builder-max_area"])


# ---------------------------------------------------------------------------
# Group 2: full constraint flow — upload boundary, generate, exercise caps
# ---------------------------------------------------------------------------


class TestMeshCreationFlow:
    """Upload a boundary and exercise the Min Area + Max Elements constraints."""

    def test_upload_boundary(self, pw_page, boundary_geojson):
        """Step 1 file upload reports node + line count."""
        # Switch to step 1 first (radio value is 'import')
        pw_page.locator(
            "#mesh_builder-wizard_step input[value='import']"
        ).click(force=True)
        pw_page.wait_for_timeout(500)

        pw_page.locator("#mesh_builder-boundary_file").set_input_files(
            str(boundary_geojson)
        )
        # Wait for the import to complete and the success summary to render
        pw_page.locator(
            "#mesh_builder-import_result"
        ).get_by_text("Loaded:").wait_for(state="visible", timeout=15000)

    def test_boundary_count_appears_in_summary(self, pw_page):
        """After upload the badge bar shows 'Boundary: N nodes'."""
        # The step indicator badge group at top
        pw_page.locator("text=Boundary:").wait_for(state="visible", timeout=5000)

    def test_navigate_to_step3_with_boundary(self, pw_page):
        pw_page.locator(
            "#mesh_builder-wizard_step input[value='mesh']"
        ).click(force=True)
        pw_page.wait_for_timeout(500)
        pw_page.locator("text=Step 3: Generate Mesh").wait_for(
            state="visible", timeout=5000
        )

    def test_estimate_renders_after_max_area_filled(self, pw_page):
        """element_estimate output updates from 'Enter max area...' to 'Estimated elements: ~N'."""
        pw_page.locator("#mesh_builder-max_area").fill("100000000")
        pw_page.wait_for_timeout(800)
        estimate = pw_page.locator("#mesh_builder-element_estimate").inner_text()
        assert "Estimated elements" in estimate

    def test_preflight_blocks_when_cap_below_estimate(self, pw_page):
        """Pre-flight notification fires when Max Elements < estimate."""
        # estimate ≈ 9 (boundary area 9e8 / max_area 1e8). Set cap=2.
        pw_page.locator("#mesh_builder-max_elements").fill("2")
        pw_page.wait_for_timeout(300)
        pw_page.locator("#mesh_builder-generate_mesh").click(force=True)
        # Notification appears
        pw_page.locator(".shiny-notification").get_by_text(
            "exceeds the limit"
        ).wait_for(state="visible", timeout=10000)
        # And no stats rendered (mesh not generated)
        stats = pw_page.locator("#mesh_builder-mesh_stats_display").inner_text()
        assert "Generate a mesh" in stats

    def test_mesh_generates_when_cap_high_enough(self, pw_page):
        """With cap above estimate, mesh generates successfully."""
        # Clear pending notifications
        _dismiss_modals(pw_page)
        pw_page.locator("#mesh_builder-max_elements").fill("1000")
        pw_page.wait_for_timeout(300)
        pw_page.locator("#mesh_builder-generate_mesh").click(force=True)
        # Wait for stats to populate (Nodes/Elements rows appear)
        pw_page.locator(
            "#mesh_builder-mesh_stats_display"
        ).get_by_text("Elements").wait_for(state="visible", timeout=20000)
        stats = pw_page.locator("#mesh_builder-mesh_stats_display").inner_text()
        assert "Nodes" in stats and "Elements" in stats
        # Quality stats also present (proves real mesh, not placeholder)
        assert "Quality" in stats or "Area" in stats

    def test_min_area_warning_fires_when_threshold_above_smallest_triangle(
        self, pw_page
    ):
        """Setting Min Triangle Area to a value catches triangles below it.

        max_area is 1e8 — Triangle's quality refinement subdivides corner
        triangles below that. Threshold equal to max_area catches every
        triangle that didn't hit the upper bound exactly (most of them).
        """
        pw_page.locator("#mesh_builder-min_area").fill("100000000")
        pw_page.wait_for_timeout(300)
        # Trigger a regeneration
        pw_page.locator("#mesh_builder-generate_mesh").click(force=True)
        # Sliver warning notification
        pw_page.locator(".shiny-notification").get_by_text(
            "below Min Triangle Area"
        ).wait_for(state="visible", timeout=20000)
