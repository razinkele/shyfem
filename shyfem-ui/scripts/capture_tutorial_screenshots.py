#!/usr/bin/env python3
"""Capture tutorial screenshots using Playwright.

Navigates through the SHYFEM UI and captures screenshots at key workflow
points for use in the tutorial page.  Run with the Shiny server already
listening on the configured URL.

Usage:
    python scripts/capture_tutorial_screenshots.py [--url URL]

Requires: playwright (pip install playwright && playwright install chromium)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page, expect
except ImportError:
    sys.exit(
        "playwright is required. Install with:\n"
        "  pip install playwright && playwright install chromium"
    )

# Output directory for screenshots
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "shyfem_ui" / "www" / "tutorial"

# Map of screenshot filename -> capture instructions
SCREENSHOTS = [
    {
        "filename": "dashboard_tutorial_btn.png",
        "description": "Dashboard with Tutorial button",
        "tab": "Dashboard",
    },
    {
        "filename": "tutorial_overview.png",
        "description": "Tutorial tab with Phase 1 expanded",
        "tab": "Tutorial",
    },
    {
        "filename": "grid_prep_loaded.png",
        "description": "Grid Prep with mesh visible",
        "tab": "Grid Prep",
    },
    {
        "filename": "grid_prep_stats.png",
        "description": "Grid Prep Statistics tab",
        "tab": "Grid Prep",
    },
    {
        "filename": "simulation_loaded.png",
        "description": "Simulation tab with STR file loaded",
        "tab": "Simulation",
    },
    {
        "filename": "simulation_sections.png",
        "description": "Sections sub-tab showing $title and $para",
        "tab": "Simulation",
    },
    {
        "filename": "simulation_boundaries.png",
        "description": "Boundaries sub-tab showing $bound1",
        "tab": "Simulation",
    },
    {
        "filename": "run_submit.png",
        "description": "Run tab with job form",
        "tab": "Run",
    },
    {
        "filename": "run_completed.png",
        "description": "Run tab after job completion",
        "tab": "Run",
    },
    {
        "filename": "postprocess_scan.png",
        "description": "Post-Process File Info after scan",
        "tab": "Post-Process",
    },
    {
        "filename": "postprocess_timeseries.png",
        "description": "Post-Process Time Series Preview",
        "tab": "Post-Process",
    },
    {
        "filename": "visualize_netcdf.png",
        "description": "Visualize: SHYFEM results map (Mar Menor salinity)",
        "tab": "Visualize",
        # needs a results file loaded (mm_hyd_assim.ts.shy, Salinity, 1280x1080);
        # this script only opens tabs, so it would overwrite it with an empty map
        "manual": True,
    },
    {
        "filename": "visualize_timeseries.png",
        "description": "Visualize tab with time series plot",
        "tab": "Visualize",
    },
    {
        "filename": "compare_params.png",
        "description": "Compare tab showing parameter diff",
        "tab": "Compare",
    },
    {
        "filename": "ensemble_preview.png",
        "description": "Ensemble tab overview",
        "tab": "Ensemble",
    },
]


def wait_for_shiny(page: Page, timeout: int = 5000) -> None:
    """Wait for Shiny to finish rendering."""
    page.wait_for_timeout(timeout)


def navigate_to_tab(page: Page, tab_name: str) -> None:
    """Click a main navbar tab by its text label."""
    tab = page.get_by_role("tab", name=tab_name, exact=True)
    if tab.is_visible():
        tab.click()
        wait_for_shiny(page, 2000)


def capture_tab_screenshot(page: Page, tab_name: str, filename: str) -> Path:
    """Navigate to a tab and take a screenshot."""
    navigate_to_tab(page, tab_name)
    path = SCREENSHOTS_DIR / filename
    page.screenshot(path=str(path), full_page=False)
    print(f"  Captured: {filename} ({tab_name})")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture tutorial screenshots")
    parser.add_argument(
        "--url",
        default="http://localhost:3838/shyfem-ui/",
        help="URL of the running Shiny app (default: %(default)s)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run browser in headed mode (visible window)",
    )
    args = parser.parse_args()

    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Capturing screenshots to: {SCREENSHOTS_DIR}")
    print(f"App URL: {args.url}")
    captured = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Navigate to the app
        print("Loading application...")
        try:
            page.goto(args.url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"Failed to load {args.url}: {e}")
            print("Make sure the Shiny server is running.")
            browser.close()
            sys.exit(1)

        wait_for_shiny(page, 3000)

        # Capture each tab screenshot
        for shot in SCREENSHOTS:
            if shot.get("manual"):
                print(f"  SKIPPED: {shot['filename']} - captured by hand (see SCREENSHOTS)")
                continue
            try:
                capture_tab_screenshot(page, shot["tab"], shot["filename"])
                captured += 1
            except Exception as e:
                print(f"  SKIPPED: {shot['filename']} - {e}")

        browser.close()

    print(f"\nDone: {captured}/{len(SCREENSHOTS)} screenshots captured.")


if __name__ == "__main__":
    main()
