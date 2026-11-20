"""Physics Save asks before writing the panels into a file they do not show.

The picker may show a file the user meant to Load; Save used to write the
loaded settings into it without a word (owner decision 2026-11-21: confirm
when they differ).
"""

from shyfem_ui.pages.physics import _save_into_other_file_modal, _shown_as


def test_the_question_names_the_shown_file_and_the_target(tmp_path):
    target = tmp_path / "c.str"
    target.write_text("$para\n$end\n")
    html = str(_save_into_other_file_modal(tmp_path / "a.str", target, tmp_path))
    assert "The panels show the settings of a.str. Save them into c.str, replacing it?" in html
    assert "Save into c.str" in html
    assert "Cancel" in html


def test_a_new_target_is_created_not_replaced(tmp_path):
    html = str(_save_into_other_file_modal(tmp_path / "a.str", tmp_path / "new.str", tmp_path))
    assert "Save them into new.str, creating it?" in html


def test_before_any_load_the_panels_show_defaults(tmp_path):
    target = tmp_path / "c.str"
    target.write_text("$para\n$end\n")
    html = str(_save_into_other_file_modal(None, target))
    assert "The panels show default settings (no file is loaded)." in html


def test_files_with_the_same_name_are_told_apart(tmp_path):
    # baseline/run.str loaded, scenario/run.str picked: "run.str" twice
    # would hide which file gets replaced.
    (tmp_path / "scenario").mkdir()
    target = tmp_path / "scenario" / "run.str"
    target.write_text("$para\n$end\n")
    html = str(_save_into_other_file_modal(tmp_path / "baseline" / "run.str", target, tmp_path))
    assert "The panels show the settings of baseline/run.str." in html
    assert "Save them into scenario/run.str, replacing it?" in html
    assert "Save into scenario/run.str" in html


def test_a_file_outside_the_project_is_shown_in_full(tmp_path):
    other = tmp_path.parent / "elsewhere.str"
    assert _shown_as(other, tmp_path) == str(other)
    assert _shown_as(tmp_path / "a.str", tmp_path) == "a.str"
    assert _shown_as(tmp_path / "a.str", None) == str(tmp_path / "a.str")
