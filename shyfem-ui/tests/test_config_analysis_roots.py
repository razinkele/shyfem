import pytest

from shyfem_ui.config import Config


def _server_cfg(tmp_path, roots, **kw):
    udr = tmp_path / "users"
    wd = tmp_path / "projects"
    udr.mkdir(exist_ok=True)
    wd.mkdir(exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=tmp_path / "shyfem",
        database_url=f"sqlite:///{tmp_path / 'db' / 'ui.db'}",
        analysis_roots=roots,
        **kw,
    )


def test_default_is_empty(tmp_path):
    assert _server_cfg(tmp_path, []).analysis_roots == []


def test_roots_are_resolved_and_kept(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cfg = _server_cfg(tmp_path, [str(root)])
    assert cfg.resolved_analysis_roots() == [root.resolve()]


@pytest.mark.parametrize(
    "bad", ["/", "{tmp}/users", "{tmp}/users/alice", "{tmp}", "{tmp}/projects", "/tmp", "{tmp}/db"]
)
def test_overlapping_or_forbidden_roots_are_rejected(tmp_path, bad):
    (tmp_path / "users" / "alice").mkdir(parents=True, exist_ok=True)
    (tmp_path / "db").mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="analysis_roots"):
        _server_cfg(tmp_path, [bad.format(tmp=tmp_path)])


def test_missing_root_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="analysis_roots"):
        _server_cfg(tmp_path, [str(tmp_path / "nope")])


def test_local_mode_ignores_roots(tmp_path):
    cfg = Config(
        _env_file=None,
        deployment_mode="local",
        work_dir=tmp_path,
        analysis_roots=["/definitely/missing"],
    )
    assert cfg.analysis_roots == ["/definitely/missing"]  # not validated, not used


def test_confine_path_reads_under_root_but_never_writes(tmp_path):
    root = tmp_path / "data"
    (root / "run").mkdir(parents=True)
    cfg = _server_cfg(tmp_path, [str(root)])
    (cfg.user_data_root / "alice").mkdir()
    user = {"id": 1, "username": "alice", "role": "user"}
    assert cfg.confine_path(root / "run", user, must_exist=True) == (root / "run").resolve()
    with pytest.raises(ValueError):
        cfg.confine_path(root / "run", user, for_write=True)


def test_confine_path_symlink_from_root_into_sandbox_is_rejected(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cfg = _server_cfg(tmp_path, [str(root)])
    (cfg.user_data_root / "bob").mkdir()
    (cfg.user_data_root / "bob" / "secret.txt").write_text("s")
    (root / "link").symlink_to(cfg.user_data_root / "bob" / "secret.txt")
    user = {"id": 1, "username": "alice", "role": "user"}
    (cfg.user_data_root / "alice").mkdir()
    with pytest.raises(ValueError):
        cfg.confine_path(root / "link", user, must_exist=True)


def test_env_var_is_a_json_array(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("SHYFEM_UI_ANALYSIS_ROOTS", f'["{root}"]')
    udr = tmp_path / "users"
    wd = tmp_path / "projects"
    udr.mkdir(exist_ok=True)
    wd.mkdir(exist_ok=True)
    cfg = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=tmp_path / "shyfem",
        database_url=f"sqlite:///{tmp_path / 'db' / 'ui.db'}",
    )
    assert cfg.resolved_analysis_roots() == [root.resolve()]
