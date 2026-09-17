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


def test_read_geom(run):
    g = bo.read_geom(run / "boxes_geom.txt")
    assert g["element"].tolist() == [1, 2, 3, 4, 5, 6] and g["box"].tolist() == [1, 1, 2, 2, 3, 3]


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
