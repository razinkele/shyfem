"""Dashboard actions still work with their work moved off the loop (H-07).

Runs against the real home_server: Details shows the project summary, Clone
creates the copy, and opening a project lands on Grid Prep.
"""

import shutil

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shyfem_ui.models.project import Project

_NAME = "h07_project"


@pytest.fixture
def dash_project(app_work_dir):
    proj_dir = app_work_dir / _NAME
    proj_dir.mkdir(exist_ok=True)
    (proj_dir / "notes.txt").write_text("hello\n")
    engine = create_engine(f"sqlite:///{app_work_dir.parent / 'test.db'}")
    with Session(engine) as db:
        proj = Project(name=_NAME, work_dir=str(proj_dir))
        db.add(proj)
        db.commit()
        pid = proj.id
    yield pid
    with Session(engine) as db:
        for p in db.query(Project).filter(Project.name.like(f"{_NAME}%")).all():
            if p.id != pid:
                shutil.rmtree(p.work_dir, ignore_errors=True)
            db.delete(p)
        db.commit()
    engine.dispose()


def _on_dashboard(pw_page, pid):
    pw_page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
    # The Dashboard re-reads the project list every IDENTITY_POLL_SECONDS.
    expect(pw_page.locator(f"#home-details_{pid}")).to_be_visible(timeout=25000)


@pytest.mark.e2e
def test_details_clone_and_open(pw_page, live_server, dash_project):
    pid = dash_project
    _on_dashboard(pw_page, pid)

    pw_page.locator(f"#home-details_{pid}").click()
    modal = pw_page.locator(".modal-dialog")
    expect(modal).to_contain_text(f"Project: {_NAME}", timeout=15000)
    expect(modal).to_contain_text("notes.txt")
    modal.locator("button:has-text('Close')").click()
    expect(modal).to_have_count(0, timeout=5000)

    pw_page.locator(f"#home-clone_{pid}").click()
    expect(
        pw_page.locator(".shiny-notification").filter(has_text=f"Cloned '{_NAME}'")
    ).to_be_visible(timeout=15000)

    pw_page.locator(f"#home-load_{pid}").click()
    expect(
        pw_page.locator(".shiny-notification").filter(has_text=f"Opened project: {_NAME}")
    ).to_be_visible(timeout=15000)
