"""Uploads still land after moving their work off the event loop (F-05).

Runs against the real files_server and grid_prep_server: an upload on the
Files page is written into the project and recorded, and a GRD uploaded on
Grid Prep is parsed and reported.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shyfem_ui.models.project import Project, ProjectFile

_GRD = Path(__file__).resolve().parents[2] / "testcases/examples/mar_menor/GRID/MM_coarse.grd"


@pytest.fixture
def upload_project(app_work_dir):
    proj_dir = app_work_dir / "upload_project"
    proj_dir.mkdir(exist_ok=True)
    engine = create_engine(f"sqlite:///{app_work_dir.parent / 'test.db'}")
    with Session(engine) as db:
        proj = Project(name="upload_project", work_dir=str(proj_dir))
        db.add(proj)
        db.commit()
        pid = proj.id
    yield pid, proj_dir, engine
    with Session(engine) as db:
        db.query(ProjectFile).filter_by(project_id=pid).delete()
        db.query(Project).filter_by(id=pid).delete()
        db.commit()
    engine.dispose()


@pytest.mark.e2e
def test_files_page_upload_is_saved(pw_page, live_server, upload_project, tmp_path):
    pid, proj_dir, engine = upload_project
    src = tmp_path / "forcing.dat"
    payload = b"0 1.5\n3600 1.7\n" * 20000
    src.write_bytes(payload)
    pw_page.evaluate(
        """([pid, wd]) => window.__test_set_active_project({
            id: pid, name: 'upload_project', work_dir: wd, description: null,
            grids: [], simulations: [], files: [],
        })""",
        [pid, str(proj_dir)],
    )
    pw_page.locator(".sf-nav-item[data-nav='Files']").click(force=True)
    pw_page.locator("#files-file_upload-file_input").set_input_files(str(src))

    expect(
        pw_page.locator(".shiny-notification").filter(has_text="Uploaded: forcing.dat")
    ).to_be_visible(timeout=15000)
    saved = list(proj_dir.rglob("forcing.dat"))
    assert len(saved) == 1 and saved[0].read_bytes() == payload
    with Session(engine) as db:
        assert db.query(ProjectFile).filter_by(project_id=pid, filename="forcing.dat").count() == 1


@pytest.mark.e2e
def test_grid_prep_upload_is_parsed(pw_page, live_server):
    if not _GRD.is_file():
        pytest.skip(f"sample grid missing: {_GRD}")
    pw_page.locator(".sf-nav-item[data-nav='Grid Prep']").click(force=True)
    pw_page.locator("#grid_prep-grd_file-file_input").set_input_files(str(_GRD))
    # The log sits in the "Log" tab; a hidden output never re-renders.
    pw_page.locator("#sf-page-Grid-Prep a[role='tab']:has-text('Log')").click()
    expect(pw_page.locator("#grid_prep-command_log-log_content_all")).to_contain_text(
        "Loaded grid: MM_coarse.grd", timeout=15000
    )


@pytest.mark.e2e
def test_files_page_type_and_subdir_hold_across_uploads(
    pw_page, live_server, upload_project, tmp_path
):
    """F-10: the type and subdirectory inputs sat in the output each upload
    re-renders, so after the first upload they reset and the next file went
    to the project root with an auto-detected type."""
    pid, proj_dir, engine = upload_project
    first, second = tmp_path / "wind_a.dat", tmp_path / "wind_b.dat"
    first.write_bytes(b"0 1.5\n")
    second.write_bytes(b"0 2.5\n")
    pw_page.evaluate(
        """([pid, wd]) => window.__test_set_active_project({
            id: pid, name: 'upload_project', work_dir: wd, description: null,
            grids: [], simulations: [], files: [],
        })""",
        [pid, str(proj_dir)],
    )
    pw_page.locator(".sf-nav-item[data-nav='Files']").click(force=True)
    expect(pw_page.locator("#files-upload_type")).to_be_attached(timeout=15000)
    pw_page.wait_for_function(
        "() => { const el = document.getElementById('files-upload_subdir');"
        " return el && el.selectize; }",
        timeout=15000,
    )
    pw_page.locator("#files-upload_type").select_option("forcing")
    pw_page.evaluate("""() => {
        const s = document.getElementById('files-upload_subdir').selectize;
        s.addOption({value: 'meteo', label: 'meteo'});
        s.setValue('meteo');
    }""")
    pw_page.wait_for_timeout(500)

    for src in (first, second):
        pw_page.locator("#files-file_upload-file_input").set_input_files(str(src))
        expect(
            pw_page.locator(".shiny-notification").filter(has_text=f"Uploaded: {src.name}")
        ).to_be_visible(timeout=15000)
        # Let the post-upload re-render land before the next file.
        pw_page.wait_for_timeout(1500)

    # The new folder is listed and still picked for the next upload.
    assert pw_page.evaluate("""() => {
        const s = document.getElementById('files-upload_subdir').selectize;
        return [s.getValue(), Object.keys(s.options).includes('meteo')];
    }""") == ["meteo", True]
    assert pw_page.locator("#files-upload_type").input_value() == "forcing"
    for src in (first, second):
        assert (proj_dir / "meteo" / src.name).is_file(), f"{src.name} not in meteo/"
        assert not (proj_dir / src.name).exists(), f"{src.name} landed in the root"
    with Session(engine) as db:
        rows = db.query(ProjectFile).filter_by(project_id=pid).all()
        assert sorted((r.filename, r.file_type) for r in rows) == [
            ("wind_a.dat", "forcing"),
            ("wind_b.dat", "forcing"),
        ]
