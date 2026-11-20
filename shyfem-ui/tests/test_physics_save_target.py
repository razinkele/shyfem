"""Physics Save asks before writing the panels into a file they do not show.

The picker may show a file the user meant to Load; Save used to write the
loaded settings into it without a word (owner decision 2026-11-21: confirm
when they differ).
"""

from shyfem_ui.pages.physics import _save_into_other_file_modal


def test_the_question_names_the_shown_file_and_the_target(tmp_path):
    target = tmp_path / "c.str"
    target.write_text("$para\n$end\n")
    html = str(_save_into_other_file_modal(tmp_path / "a.str", target))
    assert "The panels show the settings of a.str. Save them into c.str, replacing it?" in html
    assert "Save into c.str" in html
    assert "Cancel" in html


def test_a_new_target_is_created_not_replaced(tmp_path):
    html = str(_save_into_other_file_modal(tmp_path / "a.str", tmp_path / "new.str"))
    assert "Save them into new.str, creating it?" in html


def test_before_any_load_the_panels_show_defaults(tmp_path):
    target = tmp_path / "c.str"
    target.write_text("$para\n$end\n")
    html = str(_save_into_other_file_modal(None, target))
    assert "The panels show default settings (no file is loaded)." in html
