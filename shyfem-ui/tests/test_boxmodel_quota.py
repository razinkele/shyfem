import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project, ProjectFile
from shyfem_ui.services.file_service import _sum_project_bytes


@pytest.fixture
def db(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    s = Session()
    p = Project(name="p", work_dir=str(tmp_path / "p"))
    s.add(p)
    s.commit()
    s.add(
        ProjectFile(
            project_id=p.id,
            filename="a.txt",
            rel_path="a.txt",
            file_type="txt",
            size_bytes=100,
        )
    )
    s.commit()
    return s, p


def test_cache_bytes_are_counted_when_work_dir_given(db, tmp_path):
    s, p = db
    cache = tmp_path / "p" / ".boxmodel_cache" / "fix"
    cache.mkdir(parents=True)
    (cache / "state_daily.parquet").write_bytes(b"x" * 250)
    (cache / "link").symlink_to(tmp_path)  # never followed
    assert _sum_project_bytes(s, p.id) == 100
    assert _sum_project_bytes(s, p.id, work_dir=p.work_dir) == 350


def test_cache_file_symlinks_not_double_counted(db, tmp_path):
    s, p = db
    cache = tmp_path / "p" / ".boxmodel_cache" / "fix"
    cache.mkdir(parents=True)
    (cache / "state_daily.parquet").write_bytes(b"x" * 250)
    (cache / "flink").symlink_to(cache / "state_daily.parquet")  # file symlink
    # Only the real file (250 bytes) is counted, not the symlink
    assert _sum_project_bytes(s, p.id, work_dir=p.work_dir) == 350


def test_cache_missing_file_during_walk_is_skipped(db, tmp_path, monkeypatch):
    from pathlib import Path

    s, p = db
    cache = tmp_path / "p" / ".boxmodel_cache" / "fix"
    cache.mkdir(parents=True)
    file1 = cache / "state_daily.parquet"
    file1.write_bytes(b"x" * 250)
    file2 = cache / "other.parquet"
    file2.write_bytes(b"y" * 150)

    # Monkeypatch lstat to raise FileNotFoundError for file2
    original_lstat = Path.lstat

    def patched_lstat(self):
        if self.name == "other.parquet":
            raise FileNotFoundError(f"File disappeared: {self}")
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", patched_lstat)

    # Should only count file1 (250) + DB file (100) = 350
    assert _sum_project_bytes(s, p.id, work_dir=p.work_dir) == 350


def test_in_flight_and_superseded_dirs_are_not_double_counted(db, tmp_path):
    """The two-step publish (``<run>`` -> ``<run>.old-<token>``, ``<run>.tmp-
    <token>`` -> ``<run>``) leaves a run's bytes on disk twice for a moment.
    Counting the marker dirs charged the project twice for one run -- in BOTH
    windows: ``<run>`` + ``<run>.tmp-*`` before, ``<run>`` + ``<run>.old-*``
    after.
    """
    s, p = db
    root = tmp_path / "p" / ".boxmodel_cache"
    for name, payload in (
        ("fix", b"x" * 250),  # published
        ("fix.tmp-a1b2c3", b"y" * 250),  # a build in flight
        ("fix.old-a1b2c3", b"z" * 250),  # the superseded copy, about to go
    ):
        d = root / name
        d.mkdir(parents=True)
        (d / "state_daily.parquet").write_bytes(payload)
    # 100 (the DB row) + 250 (the ONE published run)
    assert _sum_project_bytes(s, p.id, work_dir=p.work_dir) == 350


def test_every_published_run_and_top_level_file_still_counts(db, tmp_path):
    """Skipping the marker dirs must not skip anything published: two runs and
    a loose file at the cache root all count."""
    s, p = db
    root = tmp_path / "p" / ".boxmodel_cache"
    for name in ("fix", "other-run_2"):
        d = root / name
        d.mkdir(parents=True)
        (d / "state_daily.parquet").write_bytes(b"x" * 250)
    (root / "registry.json").write_bytes(b"j" * 30)
    assert _sum_project_bytes(s, p.id, work_dir=p.work_dir) == 100 + 250 + 250 + 30
