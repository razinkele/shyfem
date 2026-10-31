"""R-08: an ensemble submitted again under the same name (or working
directory) put its members in the previous ensemble's run folders: the new
inputs were copied over the old ones, and the new runs overwrote -- or, with
the earlier ensemble still running, wrote at the same time as -- its results.

The submit handler now refuses before it creates, copies or submits
anything when a member's folder already holds files."""

import inspect

from shyfem_ui.pages.ensemble import _combo_label, _occupied_member_dirs

COMBOS = [{("para", "dt"): "10"}, {("para", "dt"): "20"}]


def _labels():
    return [_combo_label(c, i) for i, c in enumerate(COMBOS)]


def test_fresh_working_dir_has_no_occupied_members(tmp_path):
    assert _occupied_member_dirs(tmp_path / "ens", _labels()) == []


def test_existing_but_empty_member_dir_is_not_occupied(tmp_path):
    work = tmp_path / "ens"
    (work / _labels()[0]).mkdir(parents=True)
    assert _occupied_member_dirs(work, _labels()) == []


def test_member_dir_from_a_previous_ensemble_is_reported(tmp_path):
    work = tmp_path / "ens"
    old = work / _labels()[1]
    old.mkdir(parents=True)
    (old / "run1.hydro.shy").write_text("previous results")
    assert _occupied_member_dirs(work, _labels()) == [old]


def test_other_content_of_the_working_dir_is_not_a_conflict(tmp_path):
    work = tmp_path / "ens"
    (work / "some_other_ensemble_run").mkdir(parents=True)
    (work / "some_other_ensemble_run" / "x.shy").write_text("")
    (work / "notes.txt").write_text("")
    assert _occupied_member_dirs(work, _labels()) == []


def test_submit_handler_refuses_before_creating_or_submitting_anything():
    from shyfem_ui.pages import ensemble

    src = inspect.getsource(ensemble)
    start = src.index("ensemble_id = str(uuid.uuid4())")
    body = src[start : src.index("job_queue.submit(spec)", start)]
    assert "_occupied_member_dirs(" in body
    guard = body.index("_occupied_member_dirs(")
    assert guard < body.index("work_dir_path.mkdir(")
    assert guard < body.index("for i, combo in enumerate(combos):")
    assert "return" in body[guard : body.index("work_dir_path.mkdir(")]
