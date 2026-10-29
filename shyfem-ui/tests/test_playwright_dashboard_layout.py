"""A long project directory keeps the Dashboard's project actions usable.

A path has no spaces to wrap at, so it widened the projects table until the
Actions column (Load, Details, Export, Clone) ran under the Quick Start
card, which then took every click on those buttons.
"""

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shyfem_ui.models.project import Project

_NAME = "layout_project"


@pytest.fixture
def long_path_project(app_work_dir):
    proj_dir = app_work_dir / ("a_rather_long_project_folder_name_" * 3 + "end")
    proj_dir.mkdir(exist_ok=True)
    engine = create_engine(f"sqlite:///{app_work_dir.parent / 'test.db'}")
    with Session(engine) as db:
        proj = Project(name=_NAME, work_dir=str(proj_dir))
        db.add(proj)
        db.commit()
        pid = proj.id
    yield pid
    with Session(engine) as db:
        db.query(Project).filter_by(id=pid).delete()
        db.commit()
    engine.dispose()


def _right(page, selector: str, card: bool = False) -> float:
    return page.evaluate(
        """([sel, card]) => {
            const el = document.querySelector(sel);
            return (card ? el.closest('.card') : el).getBoundingClientRect().right;
        }""",
        [selector, card],
    )


@pytest.mark.e2e
def test_actions_stay_inside_the_projects_card(pw_page, live_server, long_path_project):
    pid = long_path_project
    pw_page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
    details = pw_page.locator(f"#home-details_{pid}")
    # The Dashboard re-reads the project list every IDENTITY_POLL_SECONDS.
    expect(details).to_be_visible(timeout=25000)

    card_right = _right(pw_page, "#home-projects_list", card=True)
    for action in ("load", "details", "export", "clone"):
        sel = f"#home-{action}_{pid}"
        assert _right(pw_page, sel) <= card_right + 1, f"{action} runs out of the card"

    # A real click (no force): nothing may sit on top of the button.
    details.click(timeout=5000)
    expect(pw_page.locator(".modal-dialog")).to_contain_text(f"Project: {_NAME}", timeout=15000)
    pw_page.locator(".modal-dialog button:has-text('Close')").click()


@pytest.mark.e2e
def test_a_reused_project_id_shows_the_current_name(pw_page, live_server, app_work_dir):
    """SQLite reuses a deleted project's id; the Dashboard's per-id handlers
    (registered once per session) must not act under the deleted one's name."""
    engine = create_engine(f"sqlite:///{app_work_dir.parent / 'test.db'}")
    made = []

    def add(name: str) -> int:
        d = app_work_dir / name
        d.mkdir(exist_ok=True)
        with Session(engine) as db:
            p = Project(name=name, work_dir=str(d))
            db.add(p)
            db.commit()
            made.append(name)
            return p.id

    try:
        pw_page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
        old_id = add("reuse_old")
        expect(pw_page.locator(f"#home-clone_{old_id}")).to_be_visible(timeout=25000)
        with Session(engine) as db:
            db.query(Project).filter_by(id=old_id).delete()
            db.commit()
        new_id = add("reuse_new")
        if new_id != old_id:
            pytest.skip("the database did not reuse the id")
        expect(pw_page.locator(f"#home-project_{new_id}")).to_contain_text(
            "reuse_new", timeout=25000
        )
        pw_page.locator(f"#home-clone_{new_id}").click()
        expect(
            pw_page.locator(".shiny-notification").filter(has_text="Cloned 'reuse_new'")
        ).to_be_visible(timeout=15000)
    finally:
        with Session(engine) as db:
            for p in db.query(Project).filter(Project.name.like("reuse_%")).all():
                db.delete(p)
            db.commit()
        engine.dispose()
