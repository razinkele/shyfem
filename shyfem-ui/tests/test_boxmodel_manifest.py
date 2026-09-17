import json

import pytest

from shyfem_ui.config import Config
from shyfem_ui.services import boxmodel_manifest as bm
from tests._boxmodel_fixture import make_box_project, make_box_run


@pytest.fixture
def local_cfg(tmp_path):
    return Config(_env_file=None, deployment_mode="local", work_dir=tmp_path)


@pytest.fixture
def project(tmp_path):
    run = tmp_path / "runs" / "fix"
    make_box_run(run, days=1)
    return make_box_project(tmp_path / "proj", run)


def test_loads_relative_and_absolute_paths_local_mode(project, local_cfg):
    m = bm.load_manifest(project, local_cfg, None)
    assert m.title == "Fixture lagoon" and m.grd == (project / "fixture.grd").resolve()
    assert m.runs[0].id == "fix" and m.runs[0].dir.name == "fix"
    assert m.polygons == (project / "box_polygons.geojson").resolve() and m.id_field == "box"


def test_missing_manifest_is_a_clear_error(tmp_path, local_cfg):
    with pytest.raises(bm.ManifestError, match="boxmodel.json"):
        bm.load_manifest(tmp_path, local_cfg, None)


def test_oversized_manifest_rejected(project, local_cfg):
    (project / "boxmodel.json").write_text("{" + " " * bm.MAX_MANIFEST_BYTES + "}")
    with pytest.raises(bm.ManifestError, match="64 KB"):
        bm.load_manifest(project, local_cfg, None)


def test_invalid_json_and_schema(project, local_cfg):
    (project / "boxmodel.json").write_text("{not json")
    with pytest.raises(bm.ManifestError, match="JSON"):
        bm.load_manifest(project, local_cfg, None)
    (project / "boxmodel.json").write_text(json.dumps({"schema": 2, "runs": []}))
    with pytest.raises(bm.ManifestError, match="schema"):
        bm.load_manifest(project, local_cfg, None)


def test_run_id_must_be_a_unique_slug(project, local_cfg):
    d = json.loads((project / "boxmodel.json").read_text())
    d["runs"].append(dict(d["runs"][0]))
    d["runs"][1]["id"] = "Bad Id!"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match=r"runs\[1\].id"):
        bm.load_manifest(project, local_cfg, None)
    d["runs"][1]["id"] = "fix"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="unique"):
        bm.load_manifest(project, local_cfg, None)


def test_server_mode_absolute_run_dir_must_be_under_a_root(outside_tmp_dir, monkeypatch):
    # Ruling 4: analysis_roots may not overlap /tmp, and pytest's tmp_path lives
    # there -- build the whole server-mode scenario under outside_tmp_dir
    # instead. The project stays under user_data_root/alice (confine_path's
    # "home" for reads), not under work_dir, which confine_path never treats
    # as a read root.
    base = outside_tmp_dir
    udr = base / "users"
    (udr / "alice").mkdir(parents=True)
    wd = base / "projects"
    wd.mkdir()
    root = base / "data"
    run = root / "runs" / "fix"
    make_box_run(run, days=1)
    proj = make_box_project(udr / "alice" / "proj", run)
    user = {"id": 1, "username": "alice", "role": "user"}
    ok = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
        analysis_roots=[str(root)],
    )
    assert bm.load_manifest(proj, ok, user).runs[0].dir == run.resolve()
    no_root = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
    )
    # Without an analysis root, confine_path's N44 branch would otherwise query
    # the DB for shared-project grants via the global session factory; the test
    # suite's global DB is deliberately left uninitialised, so that query would
    # raise sqlalchemy.exc.OperationalError and get caught by
    # accessible_shared_work_dirs' own fail-closed handling -- a real rejection,
    # but not a hermetic one (it depends on the global engine's state and logs
    # an ERROR-level traceback). Stub it directly to keep this test's rejection
    # coming from the roots check alone.
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.accessible_shared_work_dirs",
        lambda user, session_factory=None: [],
    )
    with pytest.raises(bm.ManifestError, match=r"runs\[0\].dir"):
        bm.load_manifest(proj, no_root, user)


def test_paths_may_not_escape_the_project(project, local_cfg, tmp_path):
    d = json.loads((project / "boxmodel.json").read_text())
    d["grid"]["grd"] = "../../etc/passwd"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="grid.grd"):
        bm.load_manifest(project, local_cfg, None)
