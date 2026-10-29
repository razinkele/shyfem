"""Tests for compare.py helper functions."""


def test_extract_ts_choices_empty_when_no_project(tmp_path):
    from shyfem_ui.pages.compare import _extract_ts_choices

    assert _extract_ts_choices(None) == {}


def test_extract_ts_choices_offers_text_series_only(tmp_path):
    """V-05: a .ext file is SHYFEM binary output; the text loader cannot read
    it (it raised and closed the session), so it is not offered."""
    from shyfem_ui.pages.compare import _extract_ts_choices

    for name in ("result1.ts", "river.txt", "obs.csv", "result2.ext", "binary.shy"):
        (tmp_path / name).write_text("dummy")
    proj = {"name": "test_proj", "work_dir": str(tmp_path)}
    names = sorted(p.rsplit("/", 1)[-1] for p in _extract_ts_choices(proj))
    assert names == ["obs.csv", "result1.ts", "river.txt"]


def test_extract_ts_choices_handles_missing_dir(tmp_path):
    from shyfem_ui.pages.compare import _extract_ts_choices

    proj = {"name": "test_proj", "work_dir": str(tmp_path / "nonexistent")}
    assert _extract_ts_choices(proj) == {}


def test_extract_ts_choices_label_format(tmp_path):
    from shyfem_ui.pages.compare import _extract_ts_choices

    (tmp_path / "subdir" / "result.ts").parent.mkdir()
    (tmp_path / "subdir" / "result.ts").write_text("dummy")
    proj = {"name": "myproj", "work_dir": str(tmp_path)}
    choices = _extract_ts_choices(proj)
    labels = list(choices.values())
    assert any("myproj" in label and "subdir/result.ts" in label for label in labels)
