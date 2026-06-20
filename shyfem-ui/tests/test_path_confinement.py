"""Per-user path confinement (security: cross-user file-read / IDOR fix).

Covers ``Config.confine_path`` — the server-mode guard that restricts a
user-supplied path to the *requesting user's* home (``user_data_root/{username}``)
plus read-only model assets, instead of the shared work_dir/shyfem_dir/tmp that
``validate_path`` allows. See docs/reviews/2026-06-20-full-codebase-deep-review.md
findings H1/H2 and docs/plans/2026-06-20-ui-path-confinement-idor-fix.md.
"""

from pathlib import Path

import pytest

from shyfem_ui.config import Config


def _server_config(tmp_path: Path) -> Config:
    """A server-mode Config with isolated user_data_root / work_dir / shyfem_dir."""
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


def _user(username: str) -> dict:
    return {"id": 1, "username": username, "role": "user"}


class TestConfinePathServerMode:
    def test_rejects_path_in_another_users_home(self, tmp_path):
        """User alice must not resolve a path inside bob's home directory."""
        cfg = _server_config(tmp_path)
        bob_home = cfg.user_data_root / "bob"
        bob_home.mkdir(parents=True, exist_ok=True)
        secret = bob_home / "secret.shy"
        secret.write_text("bob's private data")

        with pytest.raises(ValueError):
            cfg.confine_path(secret, _user("alice"), must_exist=True)

    def test_allows_path_inside_own_home(self, tmp_path):
        """A user may resolve a path inside their own home."""
        cfg = _server_config(tmp_path)
        alice_home = cfg.user_data_root / "alice"
        (alice_home / "proj").mkdir(parents=True, exist_ok=True)
        mine = alice_home / "proj" / "run.shy"
        mine.write_text("data")

        result = cfg.confine_path(mine, _user("alice"), must_exist=True)
        assert result == mine.resolve()

    def test_rejects_tmp(self, tmp_path):
        """/tmp is not a general read root (unlike validate_path)."""
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            cfg.confine_path("/tmp", _user("alice"))

    def test_rejects_shared_work_dir(self, tmp_path):
        """The shared work_dir is not readable in server mode confinement."""
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            cfg.confine_path(cfg.work_dir / "someone_else", _user("alice"))

    def test_none_user_is_denied(self, tmp_path):
        """Server mode with unresolved identity must fail closed (ValueError)."""
        cfg = _server_config(tmp_path)
        alice_home = cfg.user_data_root / "alice"
        alice_home.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError):
            cfg.confine_path(alice_home / "x", None)

    def test_allows_readonly_example_assets(self, tmp_path):
        """Bundled read-only model assets (testcases/examples) stay readable."""
        cfg = _server_config(tmp_path)
        examples = cfg.shyfem_dir / "testcases" / "examples" / "mar_menor"
        examples.mkdir(parents=True, exist_ok=True)
        asset = examples / "mm_hyd.str"
        asset.write_text("control file")

        result = cfg.confine_path(asset, _user("alice"), must_exist=True)
        assert result == asset.resolve()

    def test_for_write_rejects_readonly_asset_root(self, tmp_path):
        """Writes must not target the read-only bundled asset roots."""
        cfg = _server_config(tmp_path)
        examples = cfg.shyfem_dir / "testcases" / "examples"
        examples.mkdir(parents=True, exist_ok=True)
        with pytest.raises(ValueError):
            cfg.confine_path(examples / "evil.str", _user("alice"), for_write=True)

    def test_for_write_allows_own_home(self, tmp_path):
        """Writes into the user's own home are still permitted."""
        cfg = _server_config(tmp_path)
        (cfg.user_data_root / "alice").mkdir(parents=True, exist_ok=True)
        out = cfg.user_data_root / "alice" / "out.grd"
        result = cfg.confine_path(out, _user("alice"), for_write=True)
        assert result == out.resolve()

    def test_rejects_null_bytes(self, tmp_path):
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            cfg.confine_path("/x\x00y", _user("alice"))

    def test_malicious_username_cannot_escape_data_root(self, tmp_path):
        """A username with traversal segments must not widen confinement."""
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            cfg.confine_path(tmp_path / "etc" / "passwd", {"id": 9, "username": "../../etc"})


class TestDisplayPath:
    def test_server_path_under_home_shown_relative(self, tmp_path):
        cfg = _server_config(tmp_path)
        wd = cfg.user_data_root / "alice" / "lagoon_run"
        assert cfg.display_path(wd, _user("alice")) == "~/lagoon_run"

    def test_server_nested_path_relative(self, tmp_path):
        cfg = _server_config(tmp_path)
        wd = cfg.user_data_root / "alice" / "a" / "b"
        assert cfg.display_path(wd, _user("alice")) == "~/a/b"

    def test_server_path_outside_home_shows_basename_only(self, tmp_path):
        """A legacy/foreign absolute path must not leak the host layout."""
        cfg = _server_config(tmp_path)
        out = cfg.display_path("/home/razinka/.shyfem-ui/projects/secret_proj", _user("alice"))
        assert out == "secret_proj"
        assert "/" not in out

    def test_server_none_user_shows_basename(self, tmp_path):
        cfg = _server_config(tmp_path)
        assert cfg.display_path("/var/lib/x/proj", None) == "proj"

    def test_local_mode_shows_absolute_unchanged(self, tmp_path):
        users = tmp_path / "users"
        work = tmp_path / "work"
        shyfem = tmp_path / "shyfem"
        for d in (users, work, shyfem):
            d.mkdir(parents=True, exist_ok=True)
        cfg = Config(
            _env_file=None,
            deployment_mode="local",
            user_data_root=users,
            work_dir=work,
            shyfem_dir=shyfem,
        )
        wd = str(work / "project_x")
        assert cfg.display_path(wd, None) == wd


class TestConfinePathLocalMode:
    def test_local_mode_falls_back_to_validate_path(self, tmp_path):
        """Single-user desktop (local mode) has no per-user home; the shared
        work_dir remains usable and identity may be None."""
        users = tmp_path / "users"
        work = tmp_path / "work"
        shyfem = tmp_path / "shyfem"
        for d in (users, work, shyfem):
            d.mkdir(parents=True, exist_ok=True)
        cfg = Config(
            _env_file=None,
            deployment_mode="local",
            user_data_root=users,
            work_dir=work,
            shyfem_dir=shyfem,
        )
        target = work / "project" / "run.shy"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("data")

        result = cfg.confine_path(target, None, must_exist=True)
        assert result == target.resolve()
