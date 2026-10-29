"""Per-user path confinement (security: cross-user file-read / IDOR fix).

Covers ``Config.confine_path`` — the server-mode guard that restricts a
user-supplied path to the *requesting user's* home (``user_data_root/{username}``)
plus read-only model assets, instead of the shared work_dir/shyfem_dir/tmp that
``validate_path`` allows. See docs/reviews/2026-06-20-full-codebase-deep-review.md
findings H1/H2 and docs/plans/2026-06-20-ui-path-confinement-idor-fix.md.
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shyfem_ui.config import Config
from shyfem_ui.db.base import Base


def _empty_db_factory():
    """An initialised-but-empty in-memory DB factory.

    Reads for a path OUTSIDE the user's own home now consult the DB for
    shared-project (ProjectPermission) grants (N44). These deny-path tests own
    no shared projects, so an empty schema returns no grants and the confinement
    ValueError is raised as before. Passing a factory keeps the test hermetic:
    conftest deliberately leaves the *global* DB uninitialised, so without this
    the query would raise Operational("no such table") instead of the clean
    ValueError. Production always has an initialised DB (the user identity
    itself is resolved via a DB query before confine_path runs)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


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
            cfg.confine_path(
                secret, _user("alice"), must_exist=True, session_factory=_empty_db_factory()
            )

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
            cfg.confine_path("/tmp", _user("alice"), session_factory=_empty_db_factory())

    def test_rejects_shared_work_dir(self, tmp_path):
        """The shared work_dir is not readable in server mode confinement.

        (A path under work_dir the user holds NO ProjectPermission on stays
        denied; the N44 widening only reaches projects granted to the user.)"""
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            cfg.confine_path(
                cfg.work_dir / "someone_else",
                _user("alice"),
                session_factory=_empty_db_factory(),
            )

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

    def test_dot_username_does_not_widen_confinement_to_data_root(self, tmp_path):
        """N43: username='.' resolves (user_data_root / '.') == user_data_root,
        so the old 'home != root' escape guard was a no-op and confinement
        silently widened to the entire data root (every user's home)."""
        cfg = _server_config(tmp_path)
        bob_home = cfg.user_data_root / "bob"
        bob_home.mkdir(parents=True, exist_ok=True)
        secret = bob_home / "secret.shy"
        secret.write_text("bob's private data")

        with pytest.raises(ValueError):
            cfg.confine_path(secret, _user("."), must_exist=True)

    def test_dotdot_username_rejected_defensively(self, tmp_path):
        """confine_path must itself reject a bad username rather than relying
        solely on create_user-time validation (defense in depth)."""
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            cfg.confine_path(tmp_path / "x", _user(".."))

    @pytest.mark.parametrize("username", [".", "..", "a/b", "a\x00b", "", "foo bar"])
    def test_confine_path_and_validate_username_agree(self, tmp_path, username):
        """Single source of truth: confine_path delegates to
        models.user.validate_username, so both must reject the exact same
        set of unsafe usernames -- this pins that they can't silently drift
        apart (config.py used to carry its own duplicated copy of this
        check; now it imports the one in models/user.py)."""
        from shyfem_ui.models.user import validate_username

        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError):
            validate_username(username)
        with pytest.raises(ValueError):
            cfg.confine_path(tmp_path / "x", _user(username))


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


class TestTildePaths:
    """SEC-08: a user-supplied path starting with ``~name`` used to be expanded
    on the server. An unknown name raised RuntimeError (not the ValueError
    every caller catches), and a known one (``~root``) resolved to that host
    account's home and the rejection message printed it. Both are now the
    same plain ValueError that names no server path."""

    @pytest.mark.parametrize("raw", ["~nosuchuser_sec08/x", "~root/x", "~root", "~/x", "~"])
    def test_server_confine_rejects_tilde_cleanly(self, tmp_path, raw):
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError) as exc:
            cfg.confine_path(raw, _user("alice"))
        msg = str(exc.value)
        assert "/root" not in msg
        assert str(tmp_path) not in msg
        assert str(Path.home()) not in msg

    @pytest.mark.parametrize("raw", ["~nosuchuser_sec08/x", "~root/x"])
    @pytest.mark.parametrize("method", ["validate_path", "validate_save_path"])
    def test_validate_rejects_named_tilde_cleanly(self, tmp_path, raw, method):
        cfg = _server_config(tmp_path)
        with pytest.raises(ValueError) as exc:
            getattr(cfg, method)(raw)
        msg = str(exc.value)
        assert "/root" not in msg
        assert str(tmp_path) not in msg

    def test_named_tilde_gives_same_message_whether_or_not_account_exists(self, tmp_path):
        """No host-account oracle: an existing and a missing name read alike."""
        cfg = _server_config(tmp_path)
        msgs = []
        for raw in ("~root/x", "~nosuchuser_sec08/x"):
            with pytest.raises(ValueError) as exc:
                cfg.confine_path(raw, _user("alice"))
            msgs.append(str(exc.value).replace(raw, "<p>"))
        assert msgs[0] == msgs[1]

    def test_local_mode_still_expands_own_home(self, tmp_path, monkeypatch):
        """Single-user desktop: ``~/...`` still means the desktop user's home."""
        home = tmp_path / "home"
        work = home / "work"
        shyfem = tmp_path / "shyfem"
        for d in (work, shyfem):
            d.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        cfg = Config(
            _env_file=None,
            deployment_mode="local",
            user_data_root=tmp_path / "users",
            work_dir=work,
            shyfem_dir=shyfem,
        )
        assert cfg.confine_path("~/work/run.shy", None) == (work / "run.shy").resolve()
