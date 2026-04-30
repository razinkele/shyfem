"""Tests for compare.py helper functions."""


def test_extract_ts_choices_empty_when_no_project(tmp_path):
    from shyfem_ui.pages.compare import _extract_ts_choices

    assert _extract_ts_choices(None) == {}


def test_extract_ts_choices_finds_ts_and_ext(tmp_path):
    from shyfem_ui.pages.compare import _extract_ts_choices

    (tmp_path / "result1.ts").write_text("dummy")
    (tmp_path / "result2.ext").write_text("dummy")
    (tmp_path / "binary.shy").write_text("dummy")  # should be ignored
    proj = {"name": "test_proj", "work_dir": str(tmp_path)}
    choices = _extract_ts_choices(proj)
    paths = list(choices.keys())
    assert any(p.endswith("result1.ts") for p in paths)
    assert any(p.endswith("result2.ext") for p in paths)
    assert not any(p.endswith("binary.shy") for p in paths)


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
