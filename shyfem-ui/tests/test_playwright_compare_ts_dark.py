"""Compare draws two text series, in the toggling session's theme (V-05, H-05).

V-05: a dated SHYFEM ``.txt`` and a comma ``.csv`` were offered but drew an
empty plot. H-05: the plot theme must come from this session's dark-mode
toggle (it used to be a process-wide template that one user's toggle set
for everyone).
"""

import pytest
from playwright.sync_api import expect

DARK_PAPER = "#2A3545"
LIGHT_PAPER = "#F5F0E8"

_PLOT_JS = """() => {
    const el = document.querySelector('#compare-ts_comparison_plot .js-plotly-plot');
    if (!el || !el._fullLayout || !el._fullData) return null;
    return {paper: el._fullLayout.paper_bgcolor, traces: el._fullData.length};
}"""


def _toggle_dark(page, dark: bool) -> None:
    is_dark = page.evaluate("document.documentElement.getAttribute('data-bs-theme') === 'dark'")
    if is_dark != dark:
        # The E2E app's top bar has no toggle button; call what it runs.
        page.evaluate("shyfemToggleDark()")
        page.wait_for_timeout(500)


def _compare(page, work_dir, a: str, b: str) -> None:
    page.locator("#compare-ts_file_a").select_option(str(work_dir / a))
    page.locator("#compare-ts_file_b").select_option(str(work_dir / b))
    page.locator("#compare-compare_ts_btn").click()


@pytest.mark.e2e
def test_compare_draws_text_series_in_session_theme(pw_page, live_server, app_work_dir):
    page = pw_page
    work_dir = app_work_dir / "compare_ts_project"
    work_dir.mkdir(exist_ok=True)
    (work_dir / "river.txt").write_text(
        "1990-01-01::00:00:00 12.5\n1990-01-01::06:00:00 13.0\n1990-01-01::12:00:00 12.0\n"
    )
    (work_dir / "obs.csv").write_text("time,level\n0,1.5\n3600,1.7\n7200,1.6\n")
    page.evaluate(
        """(wd) => window.__test_set_active_project({
            id: 987654, name: 'compare_ts_project', work_dir: wd, description: null,
            grids: [], simulations: [], files: [],
        })""",
        str(work_dir),
    )
    try:
        _toggle_dark(page, True)
        page.locator(".sf-nav-item[data-nav='Compare']").click(force=True)
        page.locator("#sf-page-Compare a[role='tab']:has-text('Time Series')").click()
        expect(page.locator("#compare-ts_file_a option", has_text="river.txt")).to_have_count(
            1, timeout=15000
        )

        _compare(page, work_dir, "river.txt", "obs.csv")
        page.wait_for_function(f"() => {{ const r = ({_PLOT_JS})(); return r && r.traces == 2; }}")
        assert page.evaluate(_PLOT_JS)["paper"] == DARK_PAPER

        # Back to light: the next figure this session draws is light again.
        _toggle_dark(page, False)
        _compare(page, work_dir, "obs.csv", "river.txt")
        page.wait_for_function(
            f"() => {{ const r = ({_PLOT_JS})(); return r && r.paper == '{LIGHT_PAPER}'; }}"
        )
    finally:
        _toggle_dark(page, False)
        page.evaluate("window.__test_set_active_project('')")
        page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
