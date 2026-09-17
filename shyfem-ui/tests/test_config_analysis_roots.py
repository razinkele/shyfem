import pytest

from shyfem_ui.config import Config


def _server_cfg(base, roots, **kw):
    udr = base / "users"
    wd = base / "projects"
    udr.mkdir(exist_ok=True)
    wd.mkdir(exist_ok=True)
    return Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
        analysis_roots=roots,
        **kw,
    )


def test_default_is_empty(tmp_path):
    assert _server_cfg(tmp_path, []).analysis_roots == []


def test_roots_are_resolved_and_kept(outside_tmp_dir):
    root = outside_tmp_dir / "data"
    root.mkdir()
    cfg = _server_cfg(outside_tmp_dir, [str(root)])
    assert cfg.resolved_analysis_roots() == [root.resolve()]


@pytest.mark.parametrize(
    "bad",
    [
        "/",
        "{base}/users",
        "{base}/users/alice",
        "{base}",
        "{base}/projects",
        "/tmp",
        "{base}/db",
        "UNDER_TMP",
    ],
)
def test_overlapping_or_forbidden_roots_are_rejected(outside_tmp_dir, tmp_path, bad):
    base = outside_tmp_dir
    (base / "users" / "alice").mkdir(parents=True, exist_ok=True)
    (base / "db").mkdir(exist_ok=True)
    if bad == "UNDER_TMP":
        # Distinct from the other cases: this one must fail on the /tmp
        # subtree rule specifically, not on containment against one of the
        # server-mode sandbox dirs, so it gets its own directory (under
        # pytest's tmp_path, which lives under /tmp) and its own assertion.
        sub = tmp_path / "under_tmp"
        sub.mkdir()
        raw = str(sub)
        expected = r"overlaps a protected location \(/tmp\)"
    else:
        raw = bad.format(base=base)
        expected = "analysis_roots"
    with pytest.raises(ValueError, match=expected):
        _server_cfg(base, [raw])


def test_missing_root_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="analysis_roots"):
        _server_cfg(tmp_path, [str(tmp_path / "nope")])


def test_local_mode_ignores_roots(outside_tmp_dir):
    cfg = Config(
        _env_file=None,
        deployment_mode="local",
        work_dir=outside_tmp_dir,
        analysis_roots=["/definitely/missing"],
    )
    assert cfg.analysis_roots == ["/definitely/missing"]  # not validated, not used


def test_confine_path_reads_under_root_but_never_writes(outside_tmp_dir):
    root = outside_tmp_dir / "data"
    (root / "run").mkdir(parents=True)
    cfg = _server_cfg(outside_tmp_dir, [str(root)])
    (cfg.user_data_root / "alice").mkdir()
    user = {"id": 1, "username": "alice", "role": "user"}
    assert cfg.confine_path(root / "run", user, must_exist=True) == (root / "run").resolve()
    with pytest.raises(ValueError):
        cfg.confine_path(root / "run", user, for_write=True)


def test_confine_path_symlink_from_root_into_sandbox_is_rejected(outside_tmp_dir):
    root = outside_tmp_dir / "data"
    root.mkdir()
    cfg = _server_cfg(outside_tmp_dir, [str(root)])
    (cfg.user_data_root / "bob").mkdir()
    (cfg.user_data_root / "bob" / "secret.txt").write_text("s")
    (root / "link").symlink_to(cfg.user_data_root / "bob" / "secret.txt")
    user = {"id": 1, "username": "alice", "role": "user"}
    (cfg.user_data_root / "alice").mkdir()
    with pytest.raises(ValueError):
        cfg.confine_path(root / "link", user, must_exist=True)


def test_env_var_is_a_json_array(outside_tmp_dir, monkeypatch):
    root = outside_tmp_dir / "data"
    root.mkdir()
    monkeypatch.setenv("SHYFEM_UI_ANALYSIS_ROOTS", f'["{root}"]')
    udr = outside_tmp_dir / "users"
    wd = outside_tmp_dir / "projects"
    udr.mkdir(exist_ok=True)
    wd.mkdir(exist_ok=True)
    cfg = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=outside_tmp_dir / "shyfem",
        database_url=f"sqlite:///{outside_tmp_dir / 'db' / 'ui.db'}",
    )
    assert cfg.resolved_analysis_roots() == [root.resolve()]
