"""Shared-project-aware path confinement (N44).

PR#29's ``Config.confine_path`` restricts server-mode file access to the
requesting user's own home (plus read-only bundled assets). But the
bootstrapped "Mar Menor Tutorial" project is OWNED BY ADMIN and merely SHARED
to the tutorial user via an (accepted) ``ProjectPermission`` row -- its files
live under the shared ``work_dir``, outside the tutorial user's home. So every
postprocess / visualize / simulation / compare op raised "outside your home
directory".

These tests pin the fix: a user holding a ``ProjectPermission`` grant on a
project owned by someone else may *read* files under that project's
``work_dir``; a user with no grant is still denied; and write access stays
scoped to the user's own home for everyone (a read-only tutorial/viewer with a
grant can read shared files but not write outside home). The permission set is
derived server-side from the DB (never a client signal).

See docs/reviews/2026-07-18-full-codebase-deep-review.md N44 / F15.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.config import Config
from shyfem_ui.db.base import Base
from shyfem_ui.models.project import Project
from shyfem_ui.models.user import ProjectPermission, User


def _server_config(tmp_path: Path) -> Config:
    users = tmp_path / "users"
    work = tmp_path / "work"
    shyfem = tmp_path / "shyfem"
    for d in (users, work, shyfem):
        d.mkdir(parents=True, exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode="server",
        user_data_root=users,
        work_dir=work,
        shyfem_dir=shyfem,
        default_admin_password="strongpass123",
    )


def _db_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


class _Fixture:
    """A bootstrapped tutorial-style setup: admin owns a project under the
    shared ``work_dir``; ``student`` (tutorial role) holds an editor grant on
    it; ``mallory`` holds no grant."""

    def __init__(self, tmp_path: Path):
        self.cfg = _server_config(tmp_path)
        # Tutorial project files live under the shared work_dir (as the app.py
        # bootstrap stores them), NOT under any user's home.
        self.proj_dir = self.cfg.work_dir / "Mar Menor Tutorial"
        (self.proj_dir / "GRID").mkdir(parents=True, exist_ok=True)
        self.shared_file = self.proj_dir / "mm_hyd.str"
        self.shared_file.write_text("control file")

        self.factory = _db_factory()
        db = self.factory()
        admin = User(username="admin", password_hash="x", role="admin")
        student = User(username="student", password_hash="x", role="tutorial")
        mallory = User(username="mallory", password_hash="x", role="user")
        db.add_all([admin, student, mallory])
        db.flush()
        proj = Project(
            name="Mar Menor Tutorial",
            work_dir=str(self.proj_dir),
            owner_id=admin.id,
        )
        db.add(proj)
        db.flush()
        db.add(ProjectPermission(project_id=proj.id, user_id=student.id, role="editor"))
        db.commit()
        self.student = {"id": student.id, "username": "student", "role": "tutorial"}
        self.mallory = {"id": mallory.id, "username": "mallory", "role": "user"}
        db.close()


class TestSharedProjectRead:
    def test_grant_holder_can_read_shared_project_file(self, tmp_path):
        """The tutorial user (accepted ProjectPermission on the admin-owned
        tutorial project) may READ a file under that project's work_dir."""
        fx = _Fixture(tmp_path)
        result = fx.cfg.confine_path(
            fx.shared_file,
            fx.student,
            must_exist=True,
            session_factory=fx.factory,
        )
        assert result == fx.shared_file.resolve()

    def test_grant_holder_can_read_nested_shared_file(self, tmp_path):
        fx = _Fixture(tmp_path)
        nested = fx.proj_dir / "GRID" / "MM_coarse.grd"
        nested.write_text("grid")
        result = fx.cfg.confine_path(
            nested, fx.student, must_exist=True, session_factory=fx.factory
        )
        assert result == nested.resolve()

    def test_user_without_grant_is_denied(self, tmp_path):
        """A user holding NO permission on the project is still denied."""
        fx = _Fixture(tmp_path)
        with pytest.raises(ValueError):
            fx.cfg.confine_path(
                fx.shared_file, fx.mallory, must_exist=True, session_factory=fx.factory
            )

    def test_grant_on_p1_does_not_leak_read_of_unshared_p2(self, tmp_path):
        """The widening must not leak sibling projects: a user granted on P1
        cannot read a file under P2 (same owner, no grant to this user).
        Pins that the permission query filters on user_id and only that
        project's work_dir is added -- not every project's."""
        fx = _Fixture(tmp_path)
        # A second admin-owned project the student has NO grant on.
        p2_dir = fx.cfg.work_dir / "Other Project"
        p2_dir.mkdir(parents=True, exist_ok=True)
        p2_file = p2_dir / "secret.str"
        p2_file.write_text("not shared to student")
        db = fx.factory()
        from shyfem_ui.models.project import Project as _Project

        owner_id = db.query(_Project).filter_by(name="Mar Menor Tutorial").one().owner_id
        db.add(_Project(name="Other Project", work_dir=str(p2_dir), owner_id=owner_id))
        db.commit()
        db.close()

        # Student can still read P1 (control), but P2 is denied.
        assert (
            fx.cfg.confine_path(
                fx.shared_file, fx.student, must_exist=True, session_factory=fx.factory
            )
            == fx.shared_file.resolve()
        )
        with pytest.raises(ValueError):
            fx.cfg.confine_path(p2_file, fx.student, must_exist=True, session_factory=fx.factory)

    def test_shared_workdir_outside_trusted_roots_is_not_readable(self, tmp_path):
        """Defense-in-depth (Fix round 1): a pathological ``Project.work_dir``
        stored OUTSIDE both trusted project-storage roots (config.work_dir and
        config.user_data_root) must NOT become a read root, even for a user
        holding a grant on that project. Guards against an over-broad or
        pathological stored path (e.g. ``/``, ``""``, ``.``, ``/etc``, or a path
        into another area of the host) being resolved as an allowlisted read
        root -- the ``home`` path has an equivalent 'escapes the data root'
        guard, and this closes the same asymmetry for shared work_dirs."""
        fx = _Fixture(tmp_path)
        # A rogue project whose work_dir is a sibling of BOTH trusted roots
        # (neither under config.work_dir=tmp/work nor user_data_root=tmp/users).
        rogue_dir = tmp_path / "rogue" / "proj"
        rogue_dir.mkdir(parents=True)
        rogue_file = rogue_dir / "passwd"
        rogue_file.write_text("host secret")
        assert not str(rogue_dir.resolve()).startswith(str(fx.cfg.work_dir.resolve()) + "/")
        assert not str(rogue_dir.resolve()).startswith(str(fx.cfg.user_data_root.resolve()) + "/")

        db = fx.factory()
        from shyfem_ui.models.project import Project as _Project
        from shyfem_ui.models.user import ProjectPermission as _PP

        owner_id = db.query(_Project).filter_by(name="Mar Menor Tutorial").one().owner_id
        rogue = _Project(name="Rogue", work_dir=str(rogue_dir), owner_id=owner_id)
        db.add(rogue)
        db.flush()
        db.add(_PP(project_id=rogue.id, user_id=fx.student["id"], role="editor"))
        db.commit()
        db.close()

        with pytest.raises(ValueError):
            fx.cfg.confine_path(rogue_file, fx.student, must_exist=True, session_factory=fx.factory)


class TestSharedWorkDirBoundIsStrict:
    """Final review hardening: the trusted-base filter on a shared
    ``work_dir`` must reject a project whose stored ``work_dir`` IS one of
    the trusted bases itself (``config.work_dir`` / ``config.user_data_root``)
    -- not just a pathological path outside both. The old filter accepted
    ``wd == base`` as a trusted read root; since ``_within`` then treats any
    path under that root as "inside", a single project stored with
    work_dir == base would grant read of the ENTIRE shared tree (every other
    project, every other user's home under user_data_root), unrelated to any
    actual grant. This mirrors the ``home != root`` equality guard already
    enforced for the per-user home directory (N43)."""

    def test_work_dir_equal_to_work_dir_base_does_not_grant_whole_tree(self, tmp_path):
        fx = _Fixture(tmp_path)
        # A sibling project living directly under the trusted base, unrelated
        # to the student's actual (proj_dir) grant.
        sibling_dir = fx.cfg.work_dir / "Unrelated Project"
        sibling_dir.mkdir(parents=True, exist_ok=True)
        sibling_file = sibling_dir / "secret.str"
        sibling_file.write_text("not shared to student")

        db = fx.factory()
        from shyfem_ui.models.project import Project as _Project
        from shyfem_ui.models.user import ProjectPermission as _PP

        owner_id = db.query(_Project).filter_by(name="Mar Menor Tutorial").one().owner_id
        # A rogue project whose stored work_dir is EXACTLY the trusted base
        # (config.work_dir), not a subdirectory of it.
        rogue = _Project(name="Rogue Base", work_dir=str(fx.cfg.work_dir), owner_id=owner_id)
        db.add(rogue)
        db.flush()
        db.add(_PP(project_id=rogue.id, user_id=fx.student["id"], role="editor"))
        db.commit()
        db.close()

        with pytest.raises(ValueError):
            fx.cfg.confine_path(
                sibling_file, fx.student, must_exist=True, session_factory=fx.factory
            )

    def test_work_dir_equal_to_user_data_root_does_not_grant_whole_tree(self, tmp_path):
        fx = _Fixture(tmp_path)
        # Another user's home, unrelated to the student's grant.
        other_home = fx.cfg.user_data_root / "mallory"
        other_home.mkdir(parents=True, exist_ok=True)
        other_file = other_home / "secret.str"
        other_file.write_text("mallory's private file")

        db = fx.factory()
        from shyfem_ui.models.project import Project as _Project
        from shyfem_ui.models.user import ProjectPermission as _PP

        owner_id = db.query(_Project).filter_by(name="Mar Menor Tutorial").one().owner_id
        # A rogue project whose stored work_dir is EXACTLY the trusted base
        # (config.user_data_root), not a subdirectory of it.
        rogue = _Project(name="Rogue Root", work_dir=str(fx.cfg.user_data_root), owner_id=owner_id)
        db.add(rogue)
        db.flush()
        db.add(_PP(project_id=rogue.id, user_id=fx.student["id"], role="editor"))
        db.commit()
        db.close()

        with pytest.raises(ValueError):
            fx.cfg.confine_path(other_file, fx.student, must_exist=True, session_factory=fx.factory)


class TestSharedProjectWriteStaysHomeOnly:
    def test_grant_holder_cannot_write_into_shared_project(self, tmp_path):
        """WRITE roots stay [home] only: a read-only tutorial/viewer with a
        grant can read shared files but must NOT write outside home."""
        fx = _Fixture(tmp_path)
        with pytest.raises(ValueError):
            fx.cfg.confine_path(
                fx.proj_dir / "out.str",
                fx.student,
                for_write=True,
                session_factory=fx.factory,
            )

    def test_own_home_remains_the_write_root(self, tmp_path):
        """The user's own home stays the only write root (unchanged)."""
        fx = _Fixture(tmp_path)
        home = fx.cfg.user_data_root / "student"
        home.mkdir(parents=True, exist_ok=True)
        out = home / "out.str"
        result = fx.cfg.confine_path(out, fx.student, for_write=True, session_factory=fx.factory)
        assert result == out.resolve()

    def test_no_grant_write_outside_home_denied(self, tmp_path):
        fx = _Fixture(tmp_path)
        with pytest.raises(ValueError):
            fx.cfg.confine_path(
                fx.proj_dir / "out.str",
                fx.mallory,
                for_write=True,
                session_factory=fx.factory,
            )
