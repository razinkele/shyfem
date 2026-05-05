"""Inline 'next step' navigation card for completion handlers."""

from __future__ import annotations

import json as _json
from dataclasses import dataclass

from shiny import ui


@dataclass(frozen=True)
class NextStepLink:
    """Self-documenting record for next_step_card links.

    `nav_target` MUST match a `data-nav` value from
    `app.py:SIDEBAR_GROUPS` (e.g. "Run", "Post-Process", "Visualize")
    so `shyfemNavTo()` can find and click the corresponding sidebar item.

    Why @dataclass(frozen=True) rather than NamedTuple: codebase uses
    @dataclass consistently (JobSpec, JobInfo, WorkflowStep). Frozen
    makes the record immutable+hashable; the dataclass form blocks
    positional [0]/[1]/[2] subscripting, forcing readable named access.
    """

    label: str
    nav_target: str
    description: str


def next_step_card(*, title: str, links: list[NextStepLink]) -> ui.Tag:
    """Render an inline alert card with a heading and clickable next-step links.

    Args:
        title: Card heading (e.g. 'Job submitted — what next?')
        links: List of NextStepLink records.

    Returns:
        A ``ui.div`` containing a Bootstrap alert with linked next-step items.
    """
    items = []
    for link in links:
        # nav_target must match a SIDEBAR_GROUPS data-nav value. We allow
        # alnum + hyphen + underscore (e.g. "Post-Process"). Reject anything
        # else as defense-in-depth — Shiny HTML-escapes attributes too,
        # but this surfaces typos at construction time.
        if not link.nav_target or not all(c.isalnum() or c in "-_" for c in link.nav_target):
            raise ValueError(
                f"NextStepLink.nav_target must be alphanumeric / hyphen / "
                f"underscore (got {link.nav_target!r}); shyfemNavTo arg "
                "must match a data-nav identifier from app.py:SIDEBAR_GROUPS."
            )
        # json.dumps always emits double-quoted JSON strings, safe inside
        # an HTML attribute (Shiny will additionally HTML-escape the
        # attribute value when rendering, so " becomes &quot;).
        nav_js = _json.dumps(link.nav_target)
        # NOTE: hash-anchor hrefs (`href="#run"`) do NOT switch Shiny pages.
        # The app uses a custom `shyfemNavTo(name)` JS helper at
        # app.py:497 that finds the sidebar nav item with the matching
        # data-nav attribute and triggers a click. Guard with `typeof`
        # check so a click before JS init doesn't throw a ReferenceError.
        items.append(
            ui.tags.li(
                ui.tags.a(
                    link.label,
                    href="#",
                    onclick=(
                        f"if(typeof shyfemNavTo==='function')"
                        f"{{shyfemNavTo({nav_js});}}return false;"
                    ),
                    class_="text-decoration-none",
                ),
                ui.tags.small(
                    f" — {link.description}",
                    class_="text-muted ms-2",
                ),
            )
        )
    return ui.div(
        ui.tags.h6(title, class_="mb-2"),
        ui.tags.ul(*items, class_="list-unstyled mb-0 small"),
        class_="alert alert-info py-2 px-3 mt-2",
    )
