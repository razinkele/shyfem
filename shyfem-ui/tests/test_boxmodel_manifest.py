import json

import pytest

from shyfem_ui.config import Config
from shyfem_ui.services import boxmodel_manifest as bm
from tests._boxmodel_fixture import make_box_project, make_box_run


@pytest.fixture
def local_cfg(tmp_path):
    return Config(_env_file=None, deployment_mode="local", work_dir=tmp_path)


@pytest.fixture
def project(tmp_path):
    run = tmp_path / "runs" / "fix"
    make_box_run(run, days=1)
    return make_box_project(tmp_path / "proj", run)


def test_loads_relative_and_absolute_paths_local_mode(project, local_cfg):
    m = bm.load_manifest(project, local_cfg, None)
    assert m.title == "Fixture lagoon" and m.grd == (project / "fixture.grd").resolve()
    assert m.runs[0].id == "fix" and m.runs[0].dir.name == "fix"
    assert m.polygons == (project / "box_polygons.geojson").resolve() and m.id_field == "box"


def test_missing_manifest_is_a_clear_error(tmp_path, local_cfg):
    with pytest.raises(bm.ManifestError, match="boxmodel.json"):
        bm.load_manifest(tmp_path, local_cfg, None)


def test_oversized_manifest_rejected(project, local_cfg):
    (project / "boxmodel.json").write_text("{" + " " * bm.MAX_MANIFEST_BYTES + "}")
    with pytest.raises(bm.ManifestError, match="64 KB"):
        bm.load_manifest(project, local_cfg, None)


def test_invalid_json_and_schema(project, local_cfg):
    (project / "boxmodel.json").write_text("{not json")
    with pytest.raises(bm.ManifestError, match="JSON"):
        bm.load_manifest(project, local_cfg, None)
    (project / "boxmodel.json").write_text(json.dumps({"schema": 2, "runs": []}))
    with pytest.raises(bm.ManifestError, match="schema"):
        bm.load_manifest(project, local_cfg, None)


def test_run_id_must_be_a_unique_slug(project, local_cfg):
    d = json.loads((project / "boxmodel.json").read_text())
    d["runs"].append(dict(d["runs"][0]))
    d["runs"][1]["id"] = "Bad Id!"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match=r"runs\[1\].id"):
        bm.load_manifest(project, local_cfg, None)
    d["runs"][1]["id"] = "fix"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="unique"):
        bm.load_manifest(project, local_cfg, None)
    # "$" matches before a trailing newline, so a bare re.match(pattern) would
    # accept "fix\n" as a slug distinct from "fix" -- two ids that would name
    # the same cache directory once written to a filesystem path. fullmatch
    # must reject it as a format error, not silently treat it as unique.
    d["runs"][1]["id"] = "fix\n"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match=r"runs\[1\].id"):
        bm.load_manifest(project, local_cfg, None)


def test_server_mode_absolute_run_dir_must_be_under_a_root(outside_tmp_dir, monkeypatch):
    # Ruling 4: analysis_roots may not overlap /tmp, and pytest's tmp_path lives
    # there -- build the whole server-mode scenario under outside_tmp_dir
    # instead. The project stays under user_data_root/alice (confine_path's
    # "home" for reads), not under work_dir, which confine_path never treats
    # as a read root.
    base = outside_tmp_dir
    udr = base / "users"
    (udr / "alice").mkdir(parents=True)
    wd = base / "projects"
    wd.mkdir()
    root = base / "data"
    run = root / "runs" / "fix"
    make_box_run(run, days=1)
    proj = make_box_project(udr / "alice" / "proj", run)
    user = {"id": 1, "username": "alice", "role": "user"}
    ok = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
        analysis_roots=[str(root)],
    )
    assert bm.load_manifest(proj, ok, user).runs[0].dir == run.resolve()
    no_root = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
    )
    # Without an analysis root, confine_path's N44 branch would otherwise query
    # the DB for shared-project grants via the global session factory; the test
    # suite's global DB is deliberately left uninitialised, so that query would
    # raise sqlalchemy.exc.OperationalError and get caught by
    # accessible_shared_work_dirs' own fail-closed handling -- a real rejection,
    # but not a hermetic one (it depends on the global engine's state and logs
    # an ERROR-level traceback). Stub it directly to keep this test's rejection
    # coming from the roots check alone.
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.accessible_shared_work_dirs",
        lambda user, session_factory=None: [],
    )
    with pytest.raises(bm.ManifestError, match=r"runs\[0\].dir"):
        bm.load_manifest(proj, no_root, user)


def test_paths_may_not_escape_the_project(project, local_cfg):
    d = json.loads((project / "boxmodel.json").read_text())
    d["grid"]["grd"] = "../../etc/passwd"
    (project / "boxmodel.json").write_text(json.dumps(d))
    # runs[0].dir (an absolute path outside the project, per the fixture) is
    # resolved before grid.grd in load_manifest's field order, so this test
    # only reaches the grid.grd assertion because that absolute run dir is
    # accepted first (confined by Config.confine_path, not project-contained).
    with pytest.raises(bm.ManifestError, match="grid.grd"):
        bm.load_manifest(project, local_cfg, None)


def test_relative_path_symlink_escaping_the_project_is_rejected(project, local_cfg):
    # A relative value must stay inside the project even when a symlink
    # along the way makes it *resolve* somewhere else -- the containment
    # check runs on the fully resolved path, not the literal string.
    outside = project.parent / "outside"
    outside.mkdir()
    (project / "link").symlink_to("../outside")
    d = json.loads((project / "boxmodel.json").read_text())
    d["grid"]["grd"] = "link/x.grd"
    (project / "boxmodel.json").write_text(json.dumps(d))
    with pytest.raises(bm.ManifestError, match="grid.grd: must stay inside the project directory"):
        bm.load_manifest(project, local_cfg, None)


def test_server_mode_absolute_path_outside_home_and_roots_is_rejected(outside_tmp_dir, monkeypatch):
    # An absolute value that resolves cleanly (no symlink trickery) but sits
    # under another user's home, with no analysis root configured, must be
    # rejected by Config.confine_path itself.
    base = outside_tmp_dir
    udr = base / "users"
    (udr / "alice").mkdir(parents=True)
    (udr / "bob").mkdir(parents=True)
    (udr / "bob" / "secret.grd").write_text("0 secret\n")
    wd = base / "projects"
    wd.mkdir()
    run = udr / "alice" / "run"
    make_box_run(run, days=1)
    proj = make_box_project(udr / "alice" / "proj", run)
    d = json.loads((proj / "boxmodel.json").read_text())
    d["grid"]["grd"] = str(udr / "bob" / "secret.grd")
    (proj / "boxmodel.json").write_text(json.dumps(d))
    user = {"id": 1, "username": "alice", "role": "user"}
    cfg = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
    )
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.accessible_shared_work_dirs",
        lambda user, session_factory=None: [],
    )
    with pytest.raises(bm.ManifestError, match="grid.grd"):
        bm.load_manifest(proj, cfg, user)


def test_server_mode_run_dir_symlink_escaping_the_analysis_root_is_rejected(
    outside_tmp_dir, monkeypatch
):
    # An absolute run dir that is textually under the analysis root but
    # escapes it via a symlink must be rejected -- the confinement acts on
    # the fully resolved (symlink-followed) path, never a string prefix.
    base = outside_tmp_dir
    udr = base / "users"
    (udr / "alice").mkdir(parents=True)
    wd = base / "projects"
    wd.mkdir()
    root = base / "data"
    root.mkdir()
    escape_target = base / "outside_secret"
    real_run = escape_target / "run"
    make_box_run(real_run, days=1)
    (root / "escape").symlink_to(escape_target)
    home_run = udr / "alice" / "run"
    make_box_run(home_run, days=1)
    proj = make_box_project(udr / "alice" / "proj", home_run)
    d = json.loads((proj / "boxmodel.json").read_text())
    d["runs"][0]["dir"] = str(root / "escape" / "run")
    (proj / "boxmodel.json").write_text(json.dumps(d))
    user = {"id": 1, "username": "alice", "role": "user"}
    cfg = Config(
        _env_file=None,
        deployment_mode="server",
        default_admin_password="x" * 12,
        user_data_root=udr,
        work_dir=wd,
        shyfem_dir=base / "shyfem",
        database_url=f"sqlite:///{base / 'db' / 'ui.db'}",
        analysis_roots=[str(root)],
    )
    monkeypatch.setattr(
        "shyfem_ui.services.access_control.accessible_shared_work_dirs",
        lambda user, session_factory=None: [],
    )
    with pytest.raises(bm.ManifestError, match=r"runs\[0\].dir"):
        bm.load_manifest(proj, cfg, user)


# --- parsing a candidate, and writing one -----------------------------------


def _raw(project):
    return json.loads((project / bm.MANIFEST_NAME).read_text())


def test_parse_manifest_validates_a_candidate_without_touching_disk(project, local_cfg):
    """The form has to know whether a candidate is good BEFORE replacing the
    live file. Parsing a dict is what makes validate-then-write possible, so
    there is never a window where the page reads a broken manifest and no
    rollback that could itself fail."""
    parsed = bm.parse_manifest(_raw(project), project, local_cfg, None)
    assert parsed.title == "Fixture lagoon"
    assert parsed.runs[0].id == "fix"

    bad = _raw(project)
    bad["runs"] = []
    with pytest.raises(bm.ManifestError, match="runs"):
        bm.parse_manifest(bad, project, local_cfg, None)
    # ...and the file on disk is untouched, because parsing never writes.
    assert bm.load_manifest(project, local_cfg, None).runs[0].id == "fix"


def test_load_manifest_still_reads_the_file_through_the_same_rules(project, local_cfg):
    """The split must not fork the validation: loading is reading plus parsing."""
    from_file = bm.load_manifest(project, local_cfg, None)
    from_dict = bm.parse_manifest(_raw(project), project, local_cfg, None)
    assert from_file == from_dict


def test_write_manifest_round_trips_and_stays_readable(project, local_cfg):
    doc = _raw(project)
    doc["title"] = "Edited lagoon"

    written = bm.write_manifest(project, doc, local_cfg, None)

    assert written.title == "Edited lagoon"
    assert bm.load_manifest(project, local_cfg, None).title == "Edited lagoon"
    text = (project / bm.MANIFEST_NAME).read_text()
    assert "\n  " in text, "the spec calls this file hand-editable: keep it indented"
    assert text.endswith("\n")


def test_write_manifest_keeps_keys_it_does_not_know_about(project, local_cfg):
    """A save overlays the form's fields onto the raw document, so a key added
    by a future schema or by hand survives a round trip."""
    doc = _raw(project)
    doc["notes"] = {"author": "arturas", "why": "kept"}

    bm.write_manifest(project, doc, local_cfg, None)

    assert _raw(project)["notes"] == {"author": "arturas", "why": "kept"}


def test_a_rejected_candidate_leaves_the_previous_file_byte_identical(project, local_cfg):
    before = (project / bm.MANIFEST_NAME).read_bytes()
    doc = _raw(project)
    doc["runs"] = [{"id": "no spaces allowed", "dir": "runs/fix"}]

    with pytest.raises(bm.ManifestError, match="runs"):
        bm.write_manifest(project, doc, local_cfg, None)

    assert (project / bm.MANIFEST_NAME).read_bytes() == before


def test_write_manifest_creates_the_first_manifest(tmp_path, local_cfg):
    """Creating one is the point: the page is unusable until a manifest exists,
    and today it has to be hand-written."""
    run = tmp_path / "runs" / "fix"
    make_box_run(run, days=1)
    project = make_box_project(tmp_path / "fresh", run)
    (project / bm.MANIFEST_NAME).unlink()

    doc = {
        "schema": 1,
        "title": "From nothing",
        "grid": {"grd": "fixture.grd"},
        "runs": [{"id": "fix", "label": "Fixture", "dir": str(run)}],
    }
    written = bm.write_manifest(project, doc, local_cfg, None)

    assert written.title == "From nothing"
    assert bm.load_manifest(project, local_cfg, None).runs[0].dir == run.resolve()


# --- what the form writes ----------------------------------------------------


def _fields(**over):
    base = {
        "title": "Fixture lagoon",
        "grd": "fixture.grd",
        "bas": "",
        "boxes_txt": "",
        "polygons": "box_polygons.geojson",
        "layer": "",
        "id_field": "box",
        "str": "",
        "forcing_dir": "",
        "observations": "",
        "sites": "",
    }
    base.update(over)
    return base


def test_the_document_overlays_the_form_onto_what_was_there():
    """A save edits the raw document; it does not rebuild one. Keys the form
    knows nothing about have to survive, and so does the shape of the file."""
    from shyfem_ui.pages.boxmodel import _manifest_document

    raw = {
        "schema": 1,
        "title": "Old",
        "grid": {"grd": "old.grd", "bas": "old.bas"},
        "notes": {"kept": True},
        "runs": [{"id": "old", "dir": "runs/old"}],
    }
    doc = _manifest_document(
        raw, _fields(title="New"), [{"id": "fix", "label": "F", "dir": "runs/fix"}]
    )

    assert doc["notes"] == {"kept": True}, "unknown keys must survive a save"
    assert doc["title"] == "New"
    assert doc["grid"]["grd"] == "fixture.grd"
    assert doc["runs"] == [{"id": "fix", "label": "F", "dir": "runs/fix"}]
    assert raw["title"] == "Old", "the source document must not be mutated"


def test_a_blank_optional_field_removes_the_key_rather_than_writing_empty():
    """The loader treats "" as absent, but an empty string in the file is
    noise for the human who opens it next."""
    from shyfem_ui.pages.boxmodel import _manifest_document

    raw = {"schema": 1, "grid": {"grd": "a.grd", "bas": "a.bas"}, "str": "old.str"}
    doc = _manifest_document(raw, _fields(bas="", str=""), [{"id": "r", "label": "", "dir": "d"}])

    assert "bas" not in doc["grid"]
    assert "str" not in doc
    assert doc["grid"]["grd"] == "fixture.grd"


def test_an_empty_section_is_not_left_behind():
    from shyfem_ui.pages.boxmodel import _manifest_document

    raw = {"schema": 1, "observations": {"file": "obs.csv", "sites": "sites.csv"}}
    doc = _manifest_document(raw, _fields(observations="", sites=""), [{"id": "r", "dir": "d"}])

    assert "observations" not in doc


def test_a_run_without_a_label_writes_no_label():
    """The loader defaults label to the id, so writing one is redundant."""
    from shyfem_ui.pages.boxmodel import _manifest_document

    doc = _manifest_document({}, _fields(), [{"id": "fix", "label": "", "dir": "runs/fix"}])

    assert doc["runs"] == [{"id": "fix", "dir": "runs/fix"}]
    assert doc["schema"] == 1, "a document built from nothing still declares the schema"


def test_the_document_round_trips_through_the_loader_unchanged(project, local_cfg):
    """The real guard against the resolved-path trap: filling the form from the
    LOADED manifest would rewrite every relative path as absolute. Saving with
    no edits must leave the file's values exactly as they were."""
    from shyfem_ui.pages.boxmodel import _manifest_document

    before = json.loads((project / bm.MANIFEST_NAME).read_text())
    fields = {
        "title": before["title"],
        "grd": (before.get("grid") or {})["grd"],
        "bas": (before.get("grid") or {}).get("bas", ""),
        "boxes_txt": (before.get("grid") or {}).get("boxes_txt", ""),
        # `or {}` throughout: a section may be present-but-null, which is what
        # the loader's own _section() helper exists to absorb.
        "polygons": (before.get("boxes") or {}).get("polygons", ""),
        "layer": (before.get("boxes") or {}).get("layer", ""),
        "id_field": (before.get("boxes") or {}).get("id_field", "box"),
        "str": before.get("str", ""),
        "forcing_dir": (before.get("forcing") or {}).get("dir", ""),
        "observations": (before.get("observations") or {}).get("file", ""),
        "sites": (before.get("observations") or {}).get("sites", ""),
    }
    doc = _manifest_document(before, fields, before["runs"])

    parsed_before = bm.load_manifest(project, local_cfg, None)
    bm.write_manifest(project, doc, local_cfg, None)
    after = json.loads((project / bm.MANIFEST_NAME).read_text())

    # Same manifest to the loader...
    assert bm.load_manifest(project, local_cfg, None) == parsed_before

    # ...and every value that meant something is untouched, in particular every
    # relative path: this is what fails if the form is ever filled from the
    # resolved dataclass instead of the raw file.
    def _flat(d, prefix=""):
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out.update(_flat(v, f"{prefix}{k}."))
            elif v is not None:
                out[f"{prefix}{k}"] = v
        return out

    assert _flat(after) == _flat(before)
    assert after["runs"] == before["runs"]
    # The only thing a save changes is that explicit nulls go away.
    assert set(_flat(before, "")) <= set(_flat(after, ""))
    assert before["grid"]["bas"] is None and "bas" not in after["grid"]


def test_a_picked_path_is_written_relative_inside_the_project_absolute_outside(tmp_path):
    """The pickers hand back absolute paths, but a manifest stores project
    files relative -- that is what keeps it portable, and the loader rejects a
    relative value that escapes the project. A run directory under an analysis
    root has to stay absolute, which is the live Curonian case."""
    from shyfem_ui.pages.boxmodel import _manifest_path_value

    project = tmp_path / "proj"
    (project / "sub").mkdir(parents=True)
    outside = tmp_path / "published_runs" / "run9316"
    outside.mkdir(parents=True)

    assert _manifest_path_value(str(project / "fixture.grd"), project) == "fixture.grd"
    assert _manifest_path_value(str(project / "sub" / "a.csv"), project) == "sub/a.csv"
    assert _manifest_path_value(str(outside), project) == str(outside)
    assert _manifest_path_value("already/relative.grd", project) == "already/relative.grd"
    assert _manifest_path_value("", project) == ""
    assert _manifest_path_value(None, project) == ""


# --- the select layer, where a save used to delete keys ----------------------


def test_every_picker_offers_the_value_it_was_given(tmp_path):
    """THE regression test for a silent data-loss bug.

    A stored path that the project listing does not contain -- a relative one
    the matcher resolves against the worker's CWD, or a legal absolute one
    outside the project -- rendered as an EMPTY select. The save then read ""
    and removed the key. Opening the tab, editing the title and saving deleted
    `forcing.dir`, and nothing said so.
    """
    from shyfem_ui.pages.boxmodel import _manifest_picker_options

    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "elsewhere" / "run.str"

    selected, extra = _manifest_picker_options("forcing", project)
    assert selected == str(project / "forcing")
    assert extra == {str(project / "forcing"): "forcing"}, "the option must carry the value"

    selected, extra = _manifest_picker_options(str(outside), project)
    assert selected == str(outside)
    assert extra == {str(outside): str(outside)}

    assert _manifest_picker_options("", project) == ("", {})
    assert _manifest_picker_options(None, project) == ("", {})


def test_the_injected_option_really_renders_as_selected(tmp_path, local_cfg):
    """The contract the fix depends on: project_file_select keeps an injected
    value and marks it selected, so the save reads it back unchanged."""
    from shyfem_ui.components.project_select import project_file_select
    from shyfem_ui.pages.boxmodel import _manifest_picker_options

    project = tmp_path / "proj"
    project.mkdir()
    (project / "a.str").write_text("x")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    stored = str(outside / "real.str")

    selected, extra = _manifest_picker_options(stored, project)
    html = str(
        project_file_select(
            "mf_str",
            "STR",
            [".str"],
            proj={"id": 1, "name": "proj", "work_dir": str(project)},
            user=None,
            config=local_cfg,
            selected=selected,
            extra=extra,
        )
    )
    assert stored in html, "the stored path must be one of the options"
    assert "selected" in html


def test_a_no_edit_save_keeps_every_optional_key(project, local_cfg):
    """The end of the same bug, one level up: a save that changes only the
    title must not drop anything else. The fixture carries a forcing directory
    and an STR precisely so this test can see them."""
    from shyfem_ui.pages.boxmodel import _manifest_document, _manifest_picker_options

    raw = json.loads((project / bm.MANIFEST_NAME).read_text())
    grid = raw.get("grid") or {}
    boxes = raw.get("boxes") or {}
    forcing = raw.get("forcing") or {}
    obs = raw.get("observations") or {}
    stored = {
        "grd": grid.get("grd"),
        "bas": grid.get("bas"),
        "boxes_txt": grid.get("boxes_txt"),
        "polygons": boxes.get("polygons"),
        "str": raw.get("str"),
        "forcing_dir": forcing.get("dir"),
        "observations": obs.get("file"),
        "sites": obs.get("sites"),
    }
    # What the form would put in each select, and what the save reads back.
    values = {
        "title": "Only the title changed",
        "layer": boxes.get("layer") or "",
        "id_field": boxes.get("id_field") or "box",
    }
    for field, value in stored.items():
        selected, _extra = _manifest_picker_options(value, project)
        from shyfem_ui.pages.boxmodel import _manifest_path_value

        values[field] = _manifest_path_value(selected, project)

    doc = _manifest_document(raw, values, raw["runs"])
    bm.write_manifest(project, doc, local_cfg, None)
    after = json.loads((project / bm.MANIFEST_NAME).read_text())

    assert after["title"] == "Only the title changed"

    def _meaningful(value):
        """Explicit nulls are dropped by a save on purpose; everything else
        must survive untouched."""
        if isinstance(value, dict):
            return {k: _meaningful(v) for k, v in value.items() if v is not None}
        return value

    for key in ("forcing", "str", "observations", "boxes"):
        if raw.get(key):
            assert _meaningful(after.get(key)) == _meaningful(
                raw.get(key)
            ), f"a no-edit save dropped {key!r}"
    assert (after.get("grid") or {}).get("grd") == grid.get("grd")


def test_a_run_entry_keeps_its_other_keys(tmp_path):
    """A runs[] entry may carry more than the three fields the form shows."""
    from shyfem_ui.pages.boxmodel import _manifest_document

    rows = [{"id": "fix", "label": "F", "dir": "runs/fix", "note": "hand-written"}]
    doc = _manifest_document({"schema": 1}, _fields(), rows)

    assert doc["runs"][0]["note"] == "hand-written"


def test_run_row_keys_are_never_reused(tmp_path):
    """A reused key collides with the per-button ledger and leaves that row's
    Remove button permanently dead."""
    from shyfem_ui.pages import boxmodel

    seen = set()
    counters = {"run_key": 0}
    for _ in range(3):
        rows = boxmodel._new_run_rows(counters, [{"id": "a"}, {"id": "b"}])
        keys = [r["key"] for r in rows]
        assert not (seen & set(keys)), "a key was reused across reseeds"
        seen.update(keys)
