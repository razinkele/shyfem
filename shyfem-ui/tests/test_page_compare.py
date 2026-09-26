"""Tests for compare page pure functions."""

from pathlib import Path

from shyfem_ui.pages.compare import _compute_param_diff, _extract_str_choices, _load_ts
from shyfem_ui.services.parser_str import StrFile, StrSection

# ── helpers ──────────────────────────────────────────────────────


def _make_str_file(sections_dict: dict[str, dict]) -> StrFile:
    """Build a StrFile from a dict of {section_name: {param: value}}."""
    sf = StrFile()
    for sec_name, params in sections_dict.items():
        section = StrSection(name=sec_name, parameters=dict(params))
        sf.sections[sec_name] = section
    return sf


# ── _compute_param_diff ─────────────────────────────────────────


def test_param_diff_identical():
    a = _make_str_file({"para": {"dt": 10, "itrans": 1}})
    b = _make_str_file({"para": {"dt": 10, "itrans": 1}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 0
    assert result["rows"] == []


def test_param_diff_different_values():
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 20}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["param"] == "dt"
    assert result["rows"][0]["value_a"] == "10"
    assert result["rows"][0]["value_b"] == "20"


def test_param_diff_extra_section():
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 10}, "wind": {"itypw": 1}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["section"] == "wind"
    assert result["rows"][0]["value_a"] == "-"


def test_param_diff_empty_inputs():
    a = _make_str_file({})
    b = _make_str_file({})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 0
    assert result["name_a"] == "A"
    assert result["name_b"] == "B"


def test_param_diff_names_preserved():
    a = _make_str_file({"para": {"dt": 1}})
    b = _make_str_file({"para": {"dt": 2}})
    result = _compute_param_diff(a, b, "run_01", "run_02")
    assert result["name_a"] == "run_01"
    assert result["name_b"] == "run_02"


# ── diff_type classification ─────────────────────────────────────


def test_param_diff_type_changed():
    """Changed values (both present, different) get diff_type='changed'."""
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 20}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["rows"][0]["diff_type"] == "changed"


def test_param_diff_type_only_a():
    """Param only in file A (value_b=='-') gets diff_type='only_a'."""
    a = _make_str_file({"para": {"dt": 10, "extra": 5}})
    b = _make_str_file({"para": {"dt": 10}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["param"] == "extra"
    assert result["rows"][0]["value_b"] == "-"
    assert result["rows"][0]["diff_type"] == "only_a"


def test_param_diff_type_only_b():
    """Param only in file B (value_a=='-') gets diff_type='only_b'."""
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 10, "extra": 5}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["param"] == "extra"
    assert result["rows"][0]["value_a"] == "-"
    assert result["rows"][0]["diff_type"] == "only_b"


def test_param_diff_type_section_only_a():
    """Entire section only in A: all params get diff_type='only_a'."""
    a = _make_str_file({"para": {"dt": 10}, "wind": {"itypw": 1}})
    b = _make_str_file({"para": {"dt": 10}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["section"] == "wind"
    assert result["rows"][0]["diff_type"] == "only_a"


def test_param_diff_type_section_only_b():
    """Entire section only in B: all params get diff_type='only_b'."""
    a = _make_str_file({"para": {"dt": 10}})
    b = _make_str_file({"para": {"dt": 10}, "wind": {"itypw": 1}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 1
    assert result["rows"][0]["section"] == "wind"
    assert result["rows"][0]["diff_type"] == "only_b"


def test_param_diff_type_mixed():
    """Multiple diff types in one comparison."""
    a = _make_str_file({"para": {"dt": 10, "removed": 1}})
    b = _make_str_file({"para": {"dt": 20, "added": 2}})
    result = _compute_param_diff(a, b, "A", "B")
    assert result["diff_count"] == 3
    by_param = {r["param"]: r for r in result["rows"]}
    assert by_param["dt"]["diff_type"] == "changed"
    assert by_param["removed"]["diff_type"] == "only_a"
    assert by_param["added"]["diff_type"] == "only_b"


# ── _load_ts ─────────────────────────────────────────────────────


def test_load_ts_valid(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("0.0 1.0 2.0\n1.0 3.0 4.0\n")
    result = _load_ts(f)
    assert len(result) == 2
    assert result[0] == [0.0, 1.0, 2.0]


def test_load_ts_skips_non_numeric(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("time col1 col2\n0.0 1.0 2.0\n")
    result = _load_ts(f)
    assert len(result) == 1
    assert result[0] == [0.0, 1.0, 2.0]


def test_load_ts_empty_file(tmp_path):
    f = tmp_path / "ts.dat"
    f.write_text("")
    result = _load_ts(f)
    assert result == []


# ── _extract_str_choices ─────────────────────────────────────────


def test_extract_str_choices_none():
    """None project context returns empty dict."""
    assert _extract_str_choices(None) == {}


def test_extract_str_choices_empty_project():
    """Project with no simulations or files returns empty dict."""
    ctx = {"work_dir": "/tmp/proj", "simulations": [], "files": []}
    assert _extract_str_choices(ctx) == {}


def test_extract_str_choices_simulations():
    """Simulations produce label = 'name (filename)'."""
    ctx = {
        "work_dir": "/tmp/proj",
        "simulations": [
            {"name": "Run 1", "str_file": "/tmp/proj/run1.str"},
            {"name": "Run 2", "str_file": "/tmp/proj/run2.str"},
        ],
        "files": [],
    }
    choices = _extract_str_choices(ctx)
    assert len(choices) == 2
    assert choices["/tmp/proj/run1.str"] == "Run 1 (run1.str)"
    assert choices["/tmp/proj/run2.str"] == "Run 2 (run2.str)"


def test_extract_str_choices_project_files():
    """Project files with file_type='str' are included."""
    ctx = {
        "work_dir": "/tmp/proj",
        "simulations": [],
        "files": [
            {
                "id": 1,
                "filename": "extra.str",
                "rel_path": "sims/extra.str",
                "file_type": "str",
                "size_bytes": 100,
            },
            {
                "id": 2,
                "filename": "grid.grd",
                "rel_path": "grids/grid.grd",
                "file_type": "grd",
                "size_bytes": 200,
            },
        ],
    }
    choices = _extract_str_choices(ctx)
    assert len(choices) == 1
    expected_path = str(Path("/tmp/proj") / "sims/extra.str")
    assert expected_path in choices
    assert choices[expected_path] == "extra.str"


def test_extract_str_choices_dedup_sim_wins():
    """When a simulation and project file share the same path, simulation label wins."""
    ctx = {
        "work_dir": "/tmp/proj",
        "simulations": [
            {"name": "My Sim", "str_file": "/tmp/proj/sims/extra.str"},
        ],
        "files": [
            {
                "id": 1,
                "filename": "extra.str",
                "rel_path": "sims/extra.str",
                "file_type": "str",
                "size_bytes": 100,
            },
        ],
    }
    choices = _extract_str_choices(ctx)
    # The simulation label should overwrite the project-file label
    assert len(choices) == 1
    assert choices["/tmp/proj/sims/extra.str"] == "My Sim (extra.str)"


def test_extract_str_choices_missing_str_file():
    """Simulations with no str_file key are skipped."""
    ctx = {
        "work_dir": "/tmp/proj",
        "simulations": [
            {"name": "No file"},
            {"name": "Has file", "str_file": "/tmp/proj/run.str"},
        ],
        "files": [],
    }
    choices = _extract_str_choices(ctx)
    assert len(choices) == 1
    assert "/tmp/proj/run.str" in choices


def test_extract_str_choices_empty_str_file():
    """Simulations with empty str_file string are skipped."""
    ctx = {
        "work_dir": "/tmp/proj",
        "simulations": [{"name": "Empty", "str_file": ""}],
        "files": [],
    }
    assert _extract_str_choices(ctx) == {}


def test_param_diff_spells_a_value_run_as_the_str_does():
    """A parameter whose .str value is a run of numbers parses to a list; the
    diff table must show "1855 1856", not Python's "[1855, 1856]"."""
    from shyfem_ui.pages.compare import _compute_param_diff
    from shyfem_ui.services.parser_str import StrParser

    a = StrParser.parse("$bound1\n  kbound = 1855 1856\n$end\n")
    b = StrParser.parse("$bound1\n  kbound = 1855 1857\n$end\n")
    rows = _compute_param_diff(a, b, "a.str", "b.str")["rows"]
    kbound = [r for r in rows if r["param"] == "kbound"]
    assert kbound, rows
    assert kbound[0]["value_a"] == "1855 1856"
    assert kbound[0]["value_b"] == "1855 1857"
