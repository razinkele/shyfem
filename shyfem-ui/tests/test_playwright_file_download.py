"""A file downloads from the Files page over HTTP (F-06).

Runs against the real files_server. The download button used to inject a
``<script>`` with the whole file as a base64 ``data:`` URI; it now sends a
link to a one-shot session route, and the browser fetches the file.
"""

import io
import json
import zipfile

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from shyfem_ui.models.project import Project, ProjectFile


@pytest.fixture
def seeded_file(app_work_dir):
    """A project with one file, written into the live app's own database."""
    proj_dir = app_work_dir / "dl_project"
    proj_dir.mkdir(exist_ok=True)
    payload = bytes(range(256)) * 4096 + b"end"  # ~1 MiB, binary
    (proj_dir / "results.shy").write_bytes(payload)
    engine = create_engine(f"sqlite:///{app_work_dir.parent / 'test.db'}")
    with Session(engine) as db:
        proj = Project(name="dl_project", work_dir=str(proj_dir))
        db.add(proj)
        db.flush()
        pf = ProjectFile(
            project_id=proj.id,
            filename="results.shy",
            rel_path="results.shy",
            file_type="output",
            size_bytes=len(payload),
        )
        db.add(pf)
        db.commit()
        ids = (proj.id, pf.id)
    yield ids, proj_dir, payload
    with Session(engine) as db:
        db.query(ProjectFile).filter_by(id=ids[1]).delete()
        db.query(Project).filter_by(id=ids[0]).delete()
        db.commit()
    engine.dispose()


@pytest.mark.e2e
def test_download_button_fetches_the_file_over_http(pw_page, live_server, seeded_file):
    (pid, fid), proj_dir, payload = seeded_file
    pw_page.evaluate(
        """([pid, wd]) => window.__test_set_active_project({
            id: pid, name: 'dl_project', work_dir: wd, description: null,
            grids: [], simulations: [], files: [],
        })""",
        [pid, str(proj_dir)],
    )
    pw_page.locator(".sf-nav-item[data-nav='Files']").click(force=True)
    button = pw_page.locator(f"#files-dl_{fid}")
    expect(button).to_be_visible(timeout=10000)

    with pw_page.expect_download(timeout=15000) as info:
        button.click()
    download = info.value
    assert download.suggested_filename == "results.shy"
    assert "/dynamic_route/" in download.url
    assert not download.url.startswith("data:")
    with open(download.path(), "rb") as fh:
        assert fh.read() == payload
    # The old handler left a <script> holding the file behind on every click.
    assert pw_page.locator("body > script:has-text('base64')").count() == 0


@pytest.mark.e2e
def test_export_fetches_the_zip_over_http(pw_page, live_server, seeded_file):
    """Dashboard -> Export streams the project ZIP over HTTP (F-07)."""
    (pid, _fid), _proj_dir, payload = seeded_file
    pw_page.locator(".sf-nav-item[data-nav='Dashboard']").click(force=True)
    link = pw_page.locator(f"#home-export_{pid}")
    # The Dashboard re-reads the project list every IDENTITY_POLL_SECONDS.
    expect(link).to_be_visible(timeout=25000)

    with pw_page.expect_download(timeout=30000) as info:
        link.click()
    download = info.value
    assert download.suggested_filename.endswith(".zip")
    assert "/dynamic_route/" in download.url
    with open(download.path(), "rb") as fh:
        zf = zipfile.ZipFile(io.BytesIO(fh.read()))
    assert zf.read("results.shy") == payload
    assert json.loads(zf.read("manifest.json"))["project"]["name"] == "dl_project"
