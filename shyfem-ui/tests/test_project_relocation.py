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
