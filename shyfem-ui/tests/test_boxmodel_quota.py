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
