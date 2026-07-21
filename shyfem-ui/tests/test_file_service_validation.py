"""Tests for FileService.validate_simulation_files."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("SHYFEM_UI_DATABASE_URL", db_url)
    monkeypatch.setenv("SHYFEM_UI_SHYFEM_DIR", str(tmp_path / "shyfem"))
    monkeypatch.setenv("SHYFEM_UI_WORK_DIR", str(tmp_path / "projects"))

    import shyfem_ui.config as cfg_mod

    cfg_mod._config = None
    import shyfem_ui.db.base as db_mod

    db_mod._engine = None
    db_mod._SessionLocal = None

    from shyfem_ui.db.base import init_db

    init_db()
    yield
    db_mod._engine = None
    db_mod._SessionLocal = None
    cfg_mod._config = None


@pytest.fixture
def sim_project(tmp_path):
    """Create a project with a simulation and STR file."""
    from shyfem_ui.db.base import db_session
    from shyfem_ui.models.project import Project, Simulation

    work = tmp_path / "projects" / "val_proj"
    work.mkdir(parents=True)

    str_content = """\
$title
    Validation test
    val_sim
    GRID/mesh
$end

$para
    itanf = '2020-01-01'
    itend = '2020-01-02'
    idt = 300
$end

$name
    wind = 'INPUT/wind.fem'
    gotmpa = 'gotmturb.nml'
$end

$bound1
    kbound = 1 2 3
    ibtyp = 1
    boundn = 'INPUT/levels.dat'
    tempn = 'INPUT/temp_bnd.fem'
$end
"""
    (work / "val_sim.str").write_text(str_content)

    with db_session() as db:
        p = Project(name="val_proj", work_dir=str(work))
        db.add(p)
        db.flush()
        s = Simulation(
            project_id=p.id,
            name="val_sim",
            str_file="val_sim.str",
        )
        db.add(s)
        db.flush()
        return {"project_id": p.id, "sim_id": s.id, "work": work}


class TestValidateSimulationFiles:

    def test_all_missing_returns_warnings(self, sim_project):
        from shyfem_ui.services.file_service import FileService

        warnings = FileService.validate_simulation_files(sim_project["sim_id"])
        # wind, gotmpa, boundn, tempn, basin — all missing
        assert len(warnings) >= 4

    def test_no_warnings_when_all_present(self, sim_project):
        from shyfem_ui.services.file_service import FileService

        work = sim_project["work"]

        # Create all referenced files
        (work / "INPUT").mkdir(exist_ok=True)
        (work / "GRID").mkdir(exist_ok=True)
        (work / "INPUT" / "wind.fem").write_text("data")
        (work / "gotmturb.nml").write_text("data")
        (work / "INPUT" / "levels.dat").write_text("data")
        (work / "INPUT" / "temp_bnd.fem").write_text("data")
        (work / "GRID" / "mesh.bas").write_text("data")

        warnings = FileService.validate_simulation_files(sim_project["sim_id"])
        assert len(warnings) == 0

    def test_partial_missing(self, sim_project):
        from shyfem_ui.services.file_service import FileService

        work = sim_project["work"]

        # Create some but not all
        (work / "INPUT").mkdir(exist_ok=True)
        (work / "INPUT" / "wind.fem").write_text("data")
        (work / "gotmturb.nml").write_text("data")

        warnings = FileService.validate_simulation_files(sim_project["sim_id"])
        # levels.dat, temp_bnd.fem, basin still missing
        assert len(warnings) >= 2
        assert any("levels.dat" in w for w in warnings)

    def test_missing_str_file_no_detached_instance_error(self, tmp_path):
        """L34: when the STR file is absent, the 'not found' warning must use a
        scalar captured INSIDE the db_session. db_session commits (expire_on_
        commit=True) and closes; touching the expired ORM instance afterwards
        raises DetachedInstanceError, dropping the warning entirely."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.services.file_service import FileService

        work = tmp_path / "projects" / "detach_proj"
        work.mkdir(parents=True)
        with db_session() as db:
            p = Project(name="detach_proj", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="detach_sim", str_file="does_not_exist.str")
            db.add(s)
            db.flush()
            sim_id = s.id

        # Must not raise DetachedInstanceError and must name the missing file.
        warnings = FileService.validate_simulation_files(sim_id)
        assert warnings == ["STR file not found: does_not_exist.str"]

    def test_invalid_sim_id_raises(self):
        from shyfem_ui.services.file_service import FileService

        with pytest.raises(ValueError, match="not found"):
            FileService.validate_simulation_files(99999)

    def test_str_with_no_file_refs(self, tmp_path):
        """STR with only $para returns no warnings."""
        from shyfem_ui.db.base import db_session
        from shyfem_ui.models.project import Project, Simulation
        from shyfem_ui.services.file_service import FileService

        work = tmp_path / "projects" / "minimal"
        work.mkdir(parents=True)
        (work / "minimal.str").write_text(
            "$title\nMinimal\nminimal\nGRID/m\n$end\n" "$para\nidt = 300\n$end\n"
        )
        (work / "GRID").mkdir()
        (work / "GRID" / "m.bas").write_text("data")

        with db_session() as db:
            p = Project(name="minimal", work_dir=str(work))
            db.add(p)
            db.flush()
            s = Simulation(project_id=p.id, name="minimal", str_file="minimal.str")
            db.add(s)
            db.flush()
            sid = s.id

        warnings = FileService.validate_simulation_files(sid)
        assert len(warnings) == 0
