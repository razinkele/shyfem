"""Tutorial page -- guided Mar Menor walkthrough.

A two-column layout with a phase navigator on the left and dynamic step
content on the right.  The module exposes pure rendering helpers at
module level so they can be tested without a live Shiny session.
"""

from __future__ import annotations

import re
from pathlib import Path

from shiny import module, reactive, render, ui

from shyfem_ui.tutorial_content import (
    TUTORIAL_CONTENT,
    build_tutorial_context,
    get_all_sim_names,
    get_simulation,
)

# ---------------------------------------------------------------------------
# Pure rendering helpers (testable without a Shiny session)
# ---------------------------------------------------------------------------

_TOTAL_SIMS = 14
_WWW_DIR = Path(__file__).resolve().parent.parent / "www"

_TAB_NAME_MAP = {
    "run": "Run",
    "post_process": "Post-Process",
    "simulation": "Simulation",
    "grid_prep": "Grid Prep",
    "visualize": "Visualize",
    "compare": "Compare",
}


def _md_to_html(text: str) -> str:
    """Convert minimal markdown (bold and inline code) to HTML.

    Handles ``**bold**`` and `` `code` `` patterns commonly used in
    tutorial action strings.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _icon(name: str, extra_class: str = "") -> ui.Tag:
    """Return a Bootstrap Icon ``<i>`` tag."""
    cls = f"bi bi-{name}"
    if extra_class:
        cls += f" {extra_class}"
    return ui.tags.i(class_=cls)


def _render_phase_nav_item(
    phase: dict,
    current_sim: str | None,
    completed: set,
) -> ui.Tag:
    """Render all simulation items for a single phase in the navigator.

    Each simulation is rendered as a row with a status icon and an
    ``input_action_link`` for selection.
    """
    items: list[ui.Tag] = []
    for sim in phase["simulations"]:
        name = sim["name"]
        if name in completed:
            icon = _icon("check-circle-fill", "text-success me-2")
        elif name == current_sim:
            icon = _icon("arrow-right-circle-fill", "text-primary me-2")
        else:
            icon = _icon("circle", "text-muted me-2")

        link = ui.input_action_link(
            f"select_{name}",
            ui.span(icon, name, " - ", sim["title"]),
            class_="d-block py-1 text-decoration-none",
        )
        items.append(link)

    return ui.div(*items)


def _render_step(step: dict, step_num: int) -> ui.Tag:
    """Render a single tutorial step with optional actions, expected result, and screenshot."""
    children: list[ui.Tag] = [
        ui.div(
            ui.span(
                str(step_num),
                class_="badge bg-primary rounded-pill me-2",
            ),
            ui.strong(step["title"]),
            class_="mb-2",
        ),
        ui.p(step["content"], class_="ms-4"),
    ]

    # Actions checklist (numbered instructions in a blue card)
    actions = step.get("actions")
    if actions:
        children.append(
            ui.div(
                ui.h6(
                    ui.tags.i(class_="bi bi-list-check me-1"),
                    "Actions",
                    class_="text-primary",
                ),
                ui.tags.ol(
                    *[ui.tags.li(ui.HTML(_md_to_html(a))) for a in actions],
                ),
                class_="card card-body bg-light border-primary mb-2 ms-4",
            )
        )

    # Expected result box (green-bordered info box)
    expected = step.get("expected")
    if expected:
        children.append(
            ui.div(
                ui.h6(
                    ui.tags.i(class_="bi bi-check2-square me-1"),
                    "Expected Result",
                    class_="text-success",
                ),
                ui.p(expected),
                class_="card card-body border-success bg-success bg-opacity-10 mb-2 ms-4",
            )
        )

    # Screenshot image (only if the file actually exists)
    screenshot = step.get("screenshot")
    if screenshot and (_WWW_DIR / "tutorial" / screenshot).is_file():
        children.append(
            ui.div(
                ui.tags.img(
                    src=f"tutorial/{screenshot}",
                    class_="img-fluid rounded shadow-sm mb-2",
                    alt=step["title"],
                ),
                class_="ms-4",
            )
        )

    nav_target = step.get("nav_target")
    if nav_target:
        children.append(
            ui.div(
                ui.input_action_link(
                    f"nav_{nav_target.lower().replace(' ', '_').replace('-', '_')}",
                    f"Go to {nav_target}",
                    class_="btn btn-outline-secondary btn-sm",
                ),
                class_="ms-4 mb-2",
            )
        )

    return ui.div(*children, class_="mb-3 border-start border-3 ps-3")


def _render_new_params(params: dict) -> ui.Tag | None:
    """Render the 'What's New' parameter table.

    Returns ``None`` when *params* is empty.
    """
    if not params:
        return None

    rows = [
        ui.tags.tr(
            ui.tags.td(ui.code(name), class_="fw-bold"),
            ui.tags.td(desc),
        )
        for name, desc in params.items()
    ]

    return ui.div(
        ui.h6("What's New", class_="text-primary"),
        ui.tags.table(
            ui.tags.thead(
                ui.tags.tr(
                    ui.tags.th("Parameter"),
                    ui.tags.th("Description"),
                ),
            ),
            ui.tags.tbody(*rows),
            class_="table table-sm table-bordered",
        ),
        class_="mb-3",
    )


def _render_sim_header(sim: dict) -> ui.Tag:
    """Render the simulation header (title + summary)."""
    return ui.div(
        ui.h4(
            ui.code(sim["name"], class_="me-2"),
            sim["title"],
        ),
        ui.p(sim["summary"], class_="text-muted"),
    )


def _render_progress_bar(completed: int, total: int) -> ui.Tag:
    """Render a Bootstrap progress bar for tutorial completion."""
    pct = int(100 * completed / total) if total > 0 else 0
    return ui.div(
        ui.p(
            f"Progress: {completed} / {total} simulations",
            class_="small mb-1",
        ),
        ui.div(
            ui.div(
                f"{pct}%",
                class_="progress-bar",
                style=f"width: {pct}%",
                role="progressbar",
                **{
                    "aria-valuenow": str(pct),
                    "aria-valuemin": "0",
                    "aria-valuemax": "100",
                },
            ),
            class_="progress",
            style="height: 20px;",
        ),
        class_="mb-3",
    )


# ---------------------------------------------------------------------------
# Module UI
# ---------------------------------------------------------------------------

@module.ui
def tutorial_ui():
    """Tutorial page UI -- two-column with phase navigator and step content."""
    return ui.layout_columns(
        # Left: phase navigator
        ui.card(
            ui.card_header("Tutorial Phases"),
            ui.output_ui("progress_bar"),
            ui.output_ui("phase_navigator"),
        ),
        # Right: step content
        ui.card(
            ui.output_ui("step_content"),
        ),
        col_widths=[4, 8],
    )


# ---------------------------------------------------------------------------
# Module Server
# ---------------------------------------------------------------------------

@module.server
def tutorial_server(
    input,
    output,
    session,
    config,
    active_project,
    nav_callback=None,
    tutorial_context=None,
):
    """Tutorial page server logic."""

    # Reactive state --------------------------------------------------------
    current_sim: reactive.Value[str] = reactive.value("mm_hyd_00")
    completed_sims: reactive.Value[set] = reactive.value(set())

    # All simulation names in tutorial order
    _all_names = get_all_sim_names()

    # ---- Progress bar -----------------------------------------------------
    @render.ui
    def progress_bar():
        done = len(completed_sims.get())
        return _render_progress_bar(done, _TOTAL_SIMS)

    # ---- Phase navigator --------------------------------------------------
    @render.ui
    def phase_navigator():
        cur = current_sim.get()
        done = completed_sims.get()
        panels = []
        for phase in TUTORIAL_CONTENT:
            panel_content = _render_phase_nav_item(phase, cur, done)
            panels.append(
                ui.accordion_panel(
                    phase["title"],
                    panel_content,
                    value=phase["id"],
                )
            )
        return ui.accordion(*panels, id="phase_accordion", open=True)

    # ---- Step content -----------------------------------------------------
    @render.ui
    def step_content():
        name = current_sim.get()
        sim = get_simulation(name)
        if sim is None:
            return ui.p("Select a simulation from the navigator.", class_="text-muted")

        parts: list[ui.Tag] = [_render_sim_header(sim)]

        new_params_tag = _render_new_params(sim.get("new_params", {}))
        if new_params_tag is not None:
            parts.append(new_params_tag)

        parts.append(ui.h6("Steps", class_="text-primary mt-3"))
        for i, step in enumerate(sim["steps"], start=1):
            parts.append(_render_step(step, i))

        # "Mark Complete & Next" button
        parts.append(
            ui.div(
                ui.input_action_button(
                    "mark_complete",
                    "Mark Complete & Next",
                    class_="btn btn-success mt-2",
                ),
                class_="text-end",
            )
        )
        return ui.div(*parts)

    # ---- Event handlers ---------------------------------------------------

    # Dynamic click handlers for simulation selection links
    def _make_click_handler(name: str):
        @reactive.effect
        @reactive.event(input[f"select_{name}"])
        def _():
            current_sim.set(name)

    for sim_name in _all_names:
        _make_click_handler(sim_name)

    # Mark complete & advance
    @reactive.effect
    @reactive.event(input.mark_complete)
    def _on_mark_complete():
        cur = current_sim.get()
        done = completed_sims.get().copy()
        done.add(cur)
        completed_sims.set(done)

        # Advance to next incomplete simulation
        try:
            idx = _all_names.index(cur)
        except ValueError:
            return
        for next_name in _all_names[idx + 1:]:
            if next_name not in done:
                current_sim.set(next_name)
                return
        # If all done past this point, stay on current or go to first incomplete
        for next_name in _all_names:
            if next_name not in done:
                current_sim.set(next_name)
                return

    # Navigation button handlers
    _nav_targets = {"run", "post_process", "simulation", "grid_prep", "visualize", "compare"}

    def _make_nav_handler(target: str):
        @reactive.effect
        @reactive.event(input[f"nav_{target}"])
        def _():
            tab_name = _TAB_NAME_MAP.get(
                target, target.replace("_", " ").title()
            )
            if tutorial_context is not None:
                cur = current_sim.get()
                proj = active_project.get() if active_project else None
                if proj and cur:
                    ctx = build_tutorial_context(
                        cur, proj["work_dir"], tab_name
                    )
                    tutorial_context.set(ctx)
            if nav_callback is not None:
                nav_callback(tab_name)

    for target in _nav_targets:
        _make_nav_handler(target)
