from datetime import datetime

import pytest

from shyfem_ui import boxmodel_output as bo
from tests._boxmodel_fixture import flux_at, make_box_run, value_at


@pytest.fixture
def run(tmp_path):
    make_box_run(tmp_path / "run", days=2)
    return tmp_path / "run"


def test_preamble_and_file_type(run):
    pre = bo.read_preamble(run / "boxes_2d.txt")
    assert (pre.idbox, pre.file_type, pre.nvers) == (473226, bo.FILE_TYPE_STATE, 7)
    assert bo.read_preamble(run / "boxes_meteo.txt").file_type == bo.FILE_TYPE_METEO
    assert bo.read_preamble(run / "boxes_stats.txt").file_type == bo.FILE_TYPE_STATS
    assert bo.read_preamble(run / "boxes_geom.txt").file_type == bo.FILE_TYPE_GEOM


def test_iter_state_records_values_and_sections(run):
    recs = list(bo.iter_state_records(run / "boxes_2d.txt"))
    assert len(recs) == 48
    r = recs[4]  # seconds 5*3600 -> 05:00
    assert r.seconds == 5 * 3600 and r.stamp == datetime(2009, 1, 1, 5)
    assert list(r.box_ids) == [1, 2, 3] and r.values.shape == (3, 7)
    assert r.values[1, bo.STATE_VARS.index("temp")] == pytest.approx(value_at("temp", 2, r.stamp))
    assert r.sections.shape == (4, 6)
    t, p, n = flux_at(3, r.stamp)
    assert r.sections[2].tolist() == pytest.approx([3, 2, 3, t, p, n])
    assert r.sections[3, 1] == -1  # open boundary


def test_state_record_with_wrong_file_type_is_refused(run):
    with pytest.raises(bo.BoxOutputError, match="file_type"):
        list(bo.iter_state_records(run / "boxes_meteo.txt"))


def test_malformed_box_line_reports_record_number(run):
    p = run / "boxes_2d.txt"
    lines = p.read_text().splitlines()
    # record 3 starts at line index 2 + 2*10 (10 lines per record: 5 header + 3 boxes ... ) -> corrupt its second box line
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("   10800.")) + 4
    lines[idx] = "    2   nan_here"
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(bo.BoxOutputError, match="record 3"):
        list(bo.iter_state_records(p))


def test_duplicate_box_in_record_is_refused(run):
    p = run / "boxes_2d.txt"
    lines = p.read_text().splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("    2 "))
    lines[idx] = "    1" + lines[idx][5:]
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(bo.BoxOutputError, match="duplicate box"):
        list(bo.iter_state_records(p))


def test_iter_meteo_records(run):
    recs = list(bo.iter_meteo_records(run / "boxes_meteo.txt"))
    assert len(recs) == 48 and recs[0].values.shape == (3, 8)
    assert recs[7].values[0, bo.METEO_VARS.index("srad")] == pytest.approx(100 + 8)


def test_read_stats(run):
    st = bo.read_stats(run / "boxes_stats.txt")
    assert (st.date0, st.time0, st.idtbox_seconds) == (20090101, 0, 3600)
    assert st.start == datetime(2009, 1, 1) and st.end == datetime(2009, 1, 3)
    assert st.boxes["box"].tolist() == [1, 2, 3] and st.boxes["layers"].max() == 1
    assert st.sections[["from_box", "to_box"]].values.tolist() == [[1, 2], [1, 2], [2, 3], [-1, 1]]
    assert st.section_nodes[1] == [(21.01, 55.50), (21.01, 55.51)]


def test_read_stats_refuses_3d(run):
    p = run / "boxes_stats.txt"
    p.write_text(p.read_text().replace("       1       1  ", "       1       3  ", 1))
    with pytest.raises(bo.BoxOutputError, match="layers"):
        bo.read_stats(p)


def test_stats_nvars_mismatch_is_refused(run):
    p = run / "boxes_stats.txt"
    p.write_text(p.read_text().replace("          3           4", "          3           5", 1))
    with pytest.raises(bo.BoxOutputError, match="nvars"):
        bo.read_stats(p)


def test_read_geom(run):
    g = bo.read_geom(run / "boxes_geom.txt")
    assert g["element"].tolist() == [1, 2, 3, 4, 5, 6] and g["box"].tolist() == [1, 1, 2, 2, 3, 3]


def test_geom_nvars_mismatch_is_refused(run):
    p = run / "boxes_geom.txt"
    p.write_text(p.read_text().replace("        6           3", "        6           2", 1))
    with pytest.raises(bo.BoxOutputError, match="nvars"):
        bo.read_geom(p)


def test_read_run_log_facts(run):
    f = bo.read_run_log(run / "run.log")
    assert f.simulation_start_wall == "2026-09-17::00:40:54"
    assert f.program_stop_time == "2009-01-03::00:00:00"
    assert f.cpu_total_seconds == pytest.approx(123.456)
    assert f.simulation_runtime == "36 s"
    assert [x["file"] for x in f.forcing] == ["fem_forcing/wind.fem", "fem_forcing/nemunas.txt", ""]
    assert f.forcing[0]["descript"] == "meteo wind" and f.forcing[2]["unit"] == -1


def test_read_run_log_streams_large_file(run, monkeypatch):
    p = run / "run.log"
    body = p.read_text()
    head, tail = body.split(" program stop", 1)
    p.write_text(head + ("*** boxes mass error 2d: 1.0E-03\n" * 200_000) + " program stop" + tail)
    f = bo.read_run_log(p, head_bytes=4096, tail_bytes=4096)
    assert (
        f.program_stop_time == "2009-01-03::00:00:00"
        and f.simulation_start_wall == "2026-09-17::00:40:54"
    )


def test_caps_are_enforced(run, monkeypatch):
    monkeypatch.setattr(bo, "MAX_BOXES", 2)
    with pytest.raises(bo.BoxOutputError, match="boxes"):
        list(bo.iter_state_records(run / "boxes_2d.txt"))


def _truncate_state_after(path, predicate) -> None:
    """Rewrite ``path`` keeping every line up to and including the first one
    that satisfies ``predicate``, and nothing after it."""
    lines = path.read_text().splitlines()
    cut = next(i for i, ln in enumerate(lines) if predicate(i, ln))
    path.write_text("\n".join(lines[: cut + 1]) + "\n")


def test_state_file_ending_after_a_time_line_names_file_and_record(run):
    """Review Important 2: a file that stops between two lines used to leave
    ``next(it)`` unguarded inside a generator, which PEP 479 turns into
    ``RuntimeError: generator raised StopIteration`` -- a message naming
    neither the file nor the record."""
    path = run / "boxes_2d.txt"
    marks = [
        i for i, ln in enumerate(path.read_text().splitlines()) if ln.strip() == "# time record"
    ]
    # end the file right after record 2's time-stamp line
    _truncate_state_after(path, lambda i, ln: i == marks[1] + 1)
    with pytest.raises(bo.BoxOutputError) as exc:
        list(bo.iter_state_records(path))
    assert str(exc.value).startswith("boxes_2d.txt: record 2: truncated")
    assert "RuntimeError" not in str(exc.value)


def test_state_file_cut_inside_a_box_block_names_file_and_record(run):
    path = run / "boxes_2d.txt"
    lines = path.read_text().splitlines()
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "# time record"]
    # record 2's box header is 4 lines past its "# time record"; stop one
    # data row into the block
    _truncate_state_after(path, lambda i, ln: i == marks[1] + 5)
    with pytest.raises(
        bo.BoxOutputError, match=r"boxes_2d\.txt: record 2: truncated \(box block\)"
    ):
        list(bo.iter_state_records(path))


def test_state_file_cut_inside_a_section_block_names_file_and_record(run):
    path = run / "boxes_2d.txt"
    lines = path.read_text().splitlines()
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "# time record"]
    start = marks[1]
    hdr = next(i for i in range(start, len(lines)) if lines[i].strip().startswith("# section "))
    _truncate_state_after(path, lambda i, ln: i == hdr + 1)  # one section row, then EOF
    with pytest.raises(
        bo.BoxOutputError, match=r"boxes_2d\.txt: record 2: truncated \(section block\)"
    ):
        list(bo.iter_state_records(path))


def test_meteo_file_cut_mid_record_names_file_and_record(run):
    path = run / "boxes_meteo.txt"
    lines = path.read_text().splitlines()
    marks = [i for i, ln in enumerate(lines) if ln.strip() == "# time record"]
    _truncate_state_after(path, lambda i, ln: i == marks[1] + 3)  # header, no box rows
    with pytest.raises(bo.BoxOutputError, match=r"boxes_meteo\.txt: record 2: truncated"):
        list(bo.iter_meteo_records(path))


def test_stats_file_cut_mid_table_names_the_file(run):
    path = run / "boxes_stats.txt"
    lines = path.read_text().splitlines()
    # stop one row into the box table (preamble + 8 header lines + 1 row)
    path.write_text("\n".join(lines[:11]) + "\n")
    with pytest.raises(bo.BoxOutputError, match=r"^boxes_stats\.txt: truncated"):
        bo.read_stats(path)


def test_stats_file_with_a_non_numeric_header_field_names_the_file(run):
    path = run / "boxes_stats.txt"
    lines = path.read_text().splitlines()
    lines[3] = "    not-a-date           0"  # the date0/time0 line
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(bo.BoxOutputError, match=r"boxes_stats\.txt: malformed date0"):
        bo.read_stats(path)


def test_geom_file_cut_short_names_the_file(run):
    path = run / "boxes_geom.txt"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:3]) + "\n")  # preamble + elements header only
    with pytest.raises(bo.BoxOutputError, match=r"^boxes_geom\.txt: truncated"):
        bo.read_geom(path)


def test_preamble_with_a_non_numeric_field_is_a_box_output_error(run, tmp_path):
    path = tmp_path / "bad.txt"
    path.write_text("#      idbox file_type     nvers\n#     xxx  2  7\n")
    with pytest.raises(bo.BoxOutputError, match=r"bad\.txt: malformed preamble line 2"):
        bo.read_preamble(path)


def test_stats_box_row_cut_mid_line_names_file_line_and_width(run):
    """A box row that stops mid-line is SILENT today: pandas pads the missing
    fields with NaN, so the box table comes back with a NaN volume/depth
    instead of an error naming the file."""
    path = run / "boxes_stats.txt"
    lines = path.read_text().splitlines()
    lines[11] = "       2       1  4.000000E+06"  # file line 12: box 2, 3 of 5 fields
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(
        bo.BoxOutputError,
        match=r"boxes_stats\.txt: line 12: malformed box table row "
        r"\(expected 5 fields, got 3\)",
    ):
        bo.read_stats(path)


def test_stats_box_row_with_an_extra_field_names_file_and_line(run):
    path = run / "boxes_stats.txt"
    lines = path.read_text().splitlines()
    lines[11] = lines[11] + "      9.9999"  # file line 12: 6 of 5 fields
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(
        bo.BoxOutputError,
        match=r"boxes_stats\.txt: line 12: malformed box table row "
        r"\(expected 5 fields, got 6\)",
    ):
        bo.read_stats(path)


def test_stats_section_row_cut_mid_line_names_file_line_and_width(run):
    path = run / "boxes_stats.txt"
    lines = path.read_text().splitlines()
    lines[17] = "           2           1"  # file line 18: 2 of 6 fields
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(
        bo.BoxOutputError,
        match=r"boxes_stats\.txt: line 18: malformed sections table row "
        r"\(expected 6 fields, got 2\)",
    ):
        bo.read_stats(path)
