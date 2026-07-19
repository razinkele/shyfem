"""Relocate existing projects under their owners' per-user home sandbox.

Supports the path-confinement IDOR fix: once ``confine_path`` is enforced in
server mode, a project whose ``work_dir`` still lives under the shared
``work_dir`` (rather than ``user_data_root/{username}/``) is unreachable by its
owner. ``plan_relocations`` computes the moves; the planning is pure and
testable so the risky filesystem move is driven by a vetted plan.
See docs/plans/2026-06-20-ui-path-confinement-idor-fix.md (D1).
"""

from pathlib import Path

from shyfem_ui.services.project_relocation import apply_relocations, plan_relocations


def _proj(pid, work_dir, owner_username):
    return {"id": pid, "work_dir": str(work_dir), "owner_username": owner_username}


class TestPlanRelocations:
    def test_owned_project_under_shared_workdir_is_moved_into_home(self, tmp_path):
        users = tmp_path / "users"
        shared = tmp_path / "work"
        proj = _proj(1, shared / "lagoon_run", "alice")

        plans = plan_relocations([proj], user_data_root=users)

        assert len(plans) == 1
        p = plans[0]
        assert p["id"] == 1
        assert p["action"] == "move"
        assert Path(p["src"]) == (shared / "lagoon_run").resolve()
        assert Path(p["dst"]) == (users / "alice" / "lagoon_run").resolve()

    def test_project_already_under_owner_home_is_skipped(self, tmp_path):
        users = tmp_path / "users"
        proj = _proj(2, users / "bob" / "existing", "bob")

        plans = plan_relocations([proj], user_data_root=users)

        assert len(plans) == 1
        assert plans[0]["action"] == "skip-already-home"

    def test_orphan_project_without_owner_is_skipped_and_flagged(self, tmp_path):
        users = tmp_path / "users"
        shared = tmp_path / "work"
        proj = _proj(3, shared / "ownerless", None)

        plans = plan_relocations([proj], user_data_root=users)

        assert len(plans) == 1
        assert plans[0]["action"] == "skip-orphan"

    def test_basename_is_preserved_and_not_user_controlled_escape(self, tmp_path):
        """A pathological stored work_dir cannot relocate outside the owner's home."""
        users = tmp_path / "users"
        shared = tmp_path / "work"
        proj = _proj(4, shared / "weird", "alice")

        plans = plan_relocations([proj], user_data_root=users)

        dst = Path(plans[0]["dst"]).resolve()
        alice_home = (users / "alice").resolve()
        assert dst == alice_home / "weird"
        assert str(dst).startswith(str(alice_home) + "/")


class TestApplyRelocations:
    def _setup(self, tmp_path):
        users = tmp_path / "users"
        shared = tmp_path / "work"
        src = shared / "lagoon_run"
        src.mkdir(parents=True)
        (src / "mm_hyd.str").write_text("control")
        proj = _proj(1, src, "alice")
        plans = plan_relocations([proj], user_data_root=users)
        return users, src, plans

    def test_dry_run_does_not_move(self, tmp_path):
        users, src, plans = self._setup(tmp_path)
        calls = []
        summary = apply_relocations(
            plans, update_work_dir=lambda pid, p: calls.append((pid, p)), dry_run=True
        )
        assert src.exists()  # untouched
        assert calls == []
        assert summary["moved"] == 0

    def test_real_move_relocates_and_updates_db(self, tmp_path):
        users, src, plans = self._setup(tmp_path)
        calls = []
        summary = apply_relocations(
            plans, update_work_dir=lambda pid, p: calls.append((pid, p)), dry_run=False
        )
        dst = users / "alice" / "lagoon_run"
        assert not src.exists()
        assert (dst / "mm_hyd.str").read_text() == "control"
        assert calls == [(1, str(dst.resolve()))]
        assert summary["moved"] == 1

    def test_idempotent_when_destination_exists(self, tmp_path):
        users, src, plans = self._setup(tmp_path)
        (users / "alice" / "lagoon_run").mkdir(parents=True)  # already there
        summary = apply_relocations(plans, update_work_dir=lambda pid, p: None, dry_run=False)
        assert src.exists()  # not clobbered
        assert summary["moved"] == 0
        assert summary["skipped"] == 1


class TestRelocateLegacyProjects:
    """F15 companion: DB-backed driver that fetches every owned project, plans
    relocations into each owner's home, and applies them. This is for LEGACY
    OWNER access only -- it does NOT fix the tutorial-share case (a project
    owned by admin but shared to the tutorial user moves under the admin's
    home, still outside the tutorial user's allowlist; that is handled by the
    N44 shared-read confinement widening). Defaults to dry_run and is
    operator-invoked, never auto-run at startup."""

    def _db_factory(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from shyfem_ui.db.base import Base
        from shyfem_ui.models.project import Project
        from shyfem_ui.models.user import User

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        return sessionmaker(bind=engine), Project, User

    def test_dry_run_is_default_and_moves_nothing(self, tmp_path):
        from shyfem_ui.services.project_relocation import relocate_legacy_projects

        factory, Project, User = self._db_factory()
        shared = tmp_path / "work"
        src = shared / "lagoon_run"
        src.mkdir(parents=True)
        (src / "mm_hyd.str").write_text("control")
        db = factory()
        alice = User(username="alice", password_hash="x", role="user")
        db.add(alice)
        db.flush()
        db.add(Project(name="P1", work_dir=str(src), owner_id=alice.id))
        db.commit()
        db.close()

        summary = relocate_legacy_projects(
            user_data_root=tmp_path / "users", session_factory=factory
        )
        assert src.exists()  # untouched by default
        assert summary["moved"] == 0

    def test_apply_relocates_owned_project_and_updates_db(self, tmp_path):
        from shyfem_ui.services.project_relocation import relocate_legacy_projects

        factory, Project, User = self._db_factory()
        users = tmp_path / "users"
        shared = tmp_path / "work"
        src = shared / "lagoon_run"
        src.mkdir(parents=True)
        (src / "mm_hyd.str").write_text("control")
        db = factory()
        alice = User(username="alice", password_hash="x", role="user")
        db.add(alice)
        db.flush()
        proj = Project(name="P1", work_dir=str(src), owner_id=alice.id)
        db.add(proj)
        db.commit()
        pid = proj.id
        db.close()

        summary = relocate_legacy_projects(
            user_data_root=users, session_factory=factory, dry_run=False
        )
        dst = users / "alice" / "lagoon_run"
        assert not src.exists()
        assert (dst / "mm_hyd.str").read_text() == "control"
        assert summary["moved"] == 1
        db = factory()
        assert Path(db.query(Project).filter_by(id=pid).one().work_dir) == dst.resolve()
        db.close()

    def test_orphan_project_without_owner_is_skipped(self, tmp_path):
        from shyfem_ui.services.project_relocation import relocate_legacy_projects

        factory, Project, User = self._db_factory()
        shared = tmp_path / "work"
        src = shared / "ownerless"
        src.mkdir(parents=True)
        db = factory()
        db.add(Project(name="P1", work_dir=str(src), owner_id=None))
        db.commit()
        db.close()

        summary = relocate_legacy_projects(
            user_data_root=tmp_path / "users", session_factory=factory, dry_run=False
        )
        assert src.exists()
        assert summary["moved"] == 0
        assert summary["skipped"] == 1
