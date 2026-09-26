"""Synthetic SHYFEM box-model run + project used by every boxmodel test.

The envelope reproduces what SHYFEM 8.4 writes with ``idtbox`` (two-line
preamble, time record, ``boxes nvars`` header, section block). Values are
deterministic functions of (variable, box, hour) so tests can compute the
expected daily means by hand -- see ``value_at``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

IDBOX = 473226
STATE_VARS = ("temp", "salt", "cur_speed", "act_eta", "aver_eta", "bstress", "volume")
METEO_VARS = ("srad", "tair", "rhum", "wspeed", "cc", "rain", "evap", "ice")
SECTIONS = [(1, 2), (1, 2), (2, 3), (-1, 1)]  # (from, to); -1 = open boundary
ELEMENT_BOX = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3}
NODES = {  # id: (lon, lat)
    1: (21.00, 55.50),
    2: (21.01, 55.50),
    3: (21.02, 55.50),
    4: (21.03, 55.50),
    5: (21.00, 55.51),
    6: (21.01, 55.51),
    7: (21.02, 55.51),
    8: (21.03, 55.51),
}
ELEMENTS = {1: (1, 2, 6), 2: (1, 6, 5), 3: (2, 3, 7), 4: (2, 7, 6), 5: (3, 4, 8), 6: (3, 8, 7)}
T0 = datetime(2009, 1, 1)


def value_at(var: str, box: int, stamp: datetime, offset: float = 0.0) -> float:
    """Deterministic value of ``var`` in ``box`` at ``stamp``.

    ``offset`` is added to ``temp`` and ``salt`` only, so a second run built
    with ``offset != 0`` differs from the primary by a known constant in the
    two compared state variables and is identical everywhere else.
    """
    h = stamp.hour
    v = {
        "temp": 10 + box + 0.1 * h,
        "salt": 0.5 * box + 0.01 * h,
        "cur_speed": 0.01 * box,
        "act_eta": 0.001 * (h - 12),
        "aver_eta": 0.0005 * (h - 12),
        "bstress": 0.0001 * box,
        "volume": 1e8 * box,
        "srad": 100 + h,
        "tair": 5 + box,
        "rhum": 80.0,
        "wspeed": 3.0,
        "cc": 0.5,
        "rain": 1.0,
        "evap": 2.0,
        "ice": 0.0,
    }[var]
    if var in ("temp", "salt"):
        v += offset
    return v


def flux_at(section: int, stamp: datetime) -> tuple[float, float, float]:
    positive = 10.0 * section + stamp.hour
    negative = float(section)
    return positive - negative, positive, negative


def _stamp(k: int) -> datetime:
    return T0 + timedelta(hours=k)


def _state_record(k: int, boxes: int, offset: float = 0.0) -> str:
    st = _stamp(k)
    out = [
        "# time record",
        f"   {3600.0 * k:.13f}      {st:%Y-%m-%d::%H:%M:%S}",
        "#      boxes       nvars",
        f"          {boxes}           7",
        "# box      temp      salt cur_speed   act_eta  aver_eta   bstress        volume",
    ]
    for b in range(1, boxes + 1):
        v = [value_at(x, b, st, offset) for x in STATE_VARS]
        out.append(
            f"{b:5d} {v[0]:9.5f} {v[1]:9.5f} {v[2]:9.5f} {v[3]:9.5f} {v[4]:9.5f} {v[5]:9.5f} {v[6]:13.6E}"
        )
    out += [
        "#   sections",
        f"          {len(SECTIONS)}",
        "# section  from    to         total      positive      negative",
    ]
    for s, (a, b) in enumerate(SECTIONS, start=1):
        t, p, n = flux_at(s, st)
        out.append(f"{s:9d} {a:5d} {b:5d}  {t:12.6E}  {p:12.6E}  {n:12.6E}")
    return "\n".join(out)


def _meteo_record(k: int, boxes: int) -> str:
    st = _stamp(k)
    out = [
        "# time record",
        f"   {3600.0 * k:.13f}      {st:%Y-%m-%d::%H:%M:%S}",
        "#      boxes       nvars",
        f"          {boxes}           8",
        "# box     srad    tair    rhum  wspeed      cc    rain    evap     ice",
    ]
    for b in range(1, boxes + 1):
        v = [value_at(x, b, st) for x in METEO_VARS]
        out.append(f"{b:5d} " + " ".join(f"{x:7.3f}" for x in v))
    return "\n".join(out)


def _stats(boxes: int, days: int) -> str:
    end = _stamp(24 * days)
    out = [
        "#      idbox file_type     nvers",
        f"#     {IDBOX}         8         7",
        "# information on simulation",
        "    20090101           0",
        "        3600",
        f" start of simulation = {T0:%Y-%m-%d::%H:%M:%S}",
        f"   end of simulation = {end:%Y-%m-%d::%H:%M:%S}",
        "#      boxes       nvars",
        f"          {boxes}           4",
        "#    box  layers          area        volume       depth",
    ]
    for b in range(1, boxes + 1):
        out.append(f"{b:8d}       1  {2e6 * b:12.6E}  {1e8 * b:12.6E}     {5.0 + b:7.4f}")
    out += [
        "#   sections",
        f"          {len(SECTIONS)}",
        "#    section        from          to         nls        nlb1        nlb2",
    ]
    for s, (a, b) in enumerate(SECTIONS, start=1):
        out.append(f"{s:12d} {a:11d} {b:11d}           1           1           1")
    out += ["#  section details", f"          {len(SECTIONS)}"]
    for s, (a, b) in enumerate(SECTIONS, start=1):
        out += [
            "#    section       nodes    from-box      to-box      layers",
            f"{s:12d}           2 {a:11d} {b:11d}           1",
            "#       node node-number            x                y",
            f"           1 {2:11d}   {21.01:.7f}       {55.50:.7f}    ",
            f"           2 {6:11d}   {21.01:.7f}       {55.51:.7f}    ",
        ]
    return "\n".join(out) + "\n"


def _geom() -> str:
    out = [
        "#      idbox file_type     nvers",
        f"#     {IDBOX}         7         7",
        "#   elements       nvars",
        f"        {len(ELEMENTS)}           3",
        "#  element       box            area       depth",
    ]
    for e, b in ELEMENT_BOX.items():
        out.append(f"{e:9d} {b:9d}  {1e6:14.8E}     {5.0 + b:7.4f}")
    return "\n".join(out) + "\n"


def _run_log(days: int) -> str:
    end = _stamp(24 * days)
    return (
        "\n".join(
            [
                " simulation start:   2026-09-17::00:40:54",
                " iff_print_info:",
                "   id  ibc unit nvar intp form descript   file",
                "    1    0   20    3    2    1 meteo wind                  fem_forcing/wind.fem",
                "    6    2   26    1    2    3 disch                    fem_forcing/nemunas.txt",
                "   11    2   -1    1    0   -1 temp                                            ",
                "",
                f" program stop at time = {end:%Y-%m-%d::%H:%M:%S}",
                " cpu time (total):             123.456",
                " simulation end:     2026-09-17::00:41:30",
                " simulation runtime: 36 s",
            ]
        )
        + "\n"
    )


def make_box_run(
    run_dir: Path,
    *,
    days: int = 10,
    boxes: int = 3,
    with_run_log: bool = True,
    offset: float = 0.0,
) -> dict:
    """Write a synthetic run; ``offset`` shifts temp/salt in the state records only."""
    run_dir.mkdir(parents=True, exist_ok=True)
    n = 24 * days
    head2 = "#      idbox file_type     nvers\n"
    (run_dir / "boxes_2d.txt").write_text(
        head2
        + f"#     {IDBOX}         2         7\n"
        + "\n".join(_state_record(k, boxes, offset) for k in range(1, n + 1))
        + "\n"
    )
    (run_dir / "boxes_meteo.txt").write_text(
        head2
        + f"#     {IDBOX}         1         7\n"
        + "\n".join(_meteo_record(k, boxes) for k in range(1, n + 1))
        + "\n"
    )
    (run_dir / "boxes_stats.txt").write_text(_stats(boxes, days))
    (run_dir / "boxes_geom.txt").write_text(_geom())
    if with_run_log:
        (run_dir / "run.log").write_text(_run_log(days))
    return {"records": n, "sections": list(SECTIONS), "start": T0, "end": _stamp(n)}


def _grd() -> str:
    out = ["0 fixture grid"]
    for nid, (x, y) in NODES.items():
        out.append(f"1 {nid} 0 {x:.5f} {y:.5f} {6.0:.2f}")
    for eid, (a, b, c) in ELEMENTS.items():
        out.append(f"2 {eid} 0 3 {a} {b} {c}")
    return "\n".join(out) + "\n"


def _geojson() -> dict:
    def ring(box):
        i = box - 1
        x0, x1 = 21.00 + 0.01 * i, 21.01 + 0.01 * i
        return [[x0, 55.50], [x1, 55.50], [x1, 55.51], [x0, 55.51], [x0, 55.50]]

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"box": b},
                "geometry": {"type": "Polygon", "coordinates": [ring(b)]},
            }
            for b in (1, 2, 3)
        ],
    }


def fixture_str(days: int = 10) -> str:
    """A SHYFEM STR excerpt in the Curonian shape (``curonian29_1993_2016.str``).

    Every feature of the tolerant STR reader's acceptance list that a fixture
    can carry is here: a decoy ``itanf = 347068800 ...`` prose line outside
    any section, ``&para ... &end`` with several ``key = value`` pairs per
    tab-separated line, an orphan ``nsigma = 12`` right after ``&end``,
    ``$boundN`` headers with trailing title text, a multi-line ``kbound``
    list, ``boundn ='...'`` without a space before the quote, a bare
    negative number, a ``!`` comment line inside ``$name``, a bare-word
    ``levels ... end`` block, an ``$extra`` row without ``=``, and the
    ``****** SECTION`` banner / `` - set`` comment lines. Tabs are written
    as ``\t`` escapes so editors cannot expand them.

    The run period is ``T0`` .. ``T0 + days`` (formatted as a real date, so
    ``days=40`` gives ``2009-02-10``, never ``2009-01-41``). Node ids are
    fixture node ids (1-8).
    """
    itend = T0 + timedelta(days=days)
    return (
        "\n"
        "************************ SECTION TITLE **********************\n"
        " - set simulation title and grid name\n"
        "\n"
        "$title\n"
        "        Fixture lagoon, 2d, box output\n"
        "        fixture\n"
        "\tfixture\n"
        "$end\n"
        "\n"
        "************************ SECTION PARA **********************\n"
        " - set parameter for the simulation\n"
        "\n"
        " -----\tthe starting time of the input files is 1/1/1997 = 0\n"
        " itanf  = 347068800\t itend  = 536450400\tidt = 300\t--> 2008-2013\n"
        "\n"
        "&para\n"
        f"        itanf  = '{T0:%Y-%m-%d}'   itend  = '{itend:%Y-%m-%d}'\tidt = '5m'\n"
        "\tidtbox = '1h'\t\t!box output -- the deliverable\n"
        "        idtflx = '1h'\t\t!box fluxes -- needed by the box model\n"
        "\n"
        f"        date   = {T0:%Y%m%d}   time   = 000000\n"
        "\n"
        "        ireib  = 5\tczdef  = 0.0025\n"
        "\n"
        "        iturb = 0       ibarcl = 3      ievap  = 1\n"
        "\n"
        "\tnomp   = 4\n"
        "&end\n"
        "\tnsigma = 12\n"
        "\n"
        "************************ SECTION LEVEL **********************\n"
        " - set layer depths (2d run: ignored, kept for the reader)\n"
        "\n"
        "levels\n"
        " 1 2 3\n"
        "end\n"
        "\n"
        "************************ SECTION BOUND **********************\n"
        " - set open boundary conditions\n"
        "\n"
        "$bound1     ---- Baltic sea ---- open boundary\n"
        "       kbound  = 1 2 3\n"
        "                 4\n"
        "\tibtyp  = 1\n"
        "\tboundn = 'fem_forcing/sea_level.fem'\n"
        "\tsaltn  = 'fem_forcing/salt.fem'\n"
        "$end\n"
        "\n"
        "$bound2 ----- Fixture river ---- discharge in m3/s\n"
        "      kbound = 5 6\n"
        "      zfact  = 0.25\n"
        "      ibtyp  = 2\n"
        "      boundn ='fem_forcing/river.txt'\n"
        "      temp   = -999\n"
        "      salt   = 0.1\n"
        "$end\n"
        "\n"
        "************************ SECTION 'NAME' **********************\n"
        " - set input file for wind, radiative flux and rain\n"
        "\n"
        "$name\n"
        "      !gotmpa = ''\t\t!not needed: iturb = 0 (2-d run)\n"
        "      wind = 'fem_forcing/wind.fem'\n"
        "$end\n"
        "\n"
        "************************ SECTION EXTRA **********************\n"
        " - set extra point for water level and velocity\n"
        "\n"
        "$extra\n"
        "        1 'A'\n"
        "$end\n"
    )


FIXTURE_STR = fixture_str(10)


def _river(days: int) -> str:
    """Daily discharge ``T0 - 2 d`` .. ``T0 + days + 2 d`` inclusive; value = 100 + day index."""
    first = T0 - timedelta(days=2)
    rows = [f"{first + timedelta(days=i):%Y-%m-%d}::06:00:00  {100 + i}" for i in range(days + 5)]
    return "# discharge m3/s\n" + "\n".join(rows) + "\n"


def make_box_project(
    project_dir: Path,
    run_dir: Path,
    *,
    run_id: str = "fix",
    polygons: bool = True,
    obs_days: int = 10,
    extra_runs: list[tuple[str, str, Path]] | None = None,
    str_file: bool = False,
    forcing: bool = False,
) -> Path:
    """Write a project; each ``(id, label, dir)`` in ``extra_runs`` follows the primary run.

    ``str_file=True`` writes ``fixture.str`` (see ``fixture_str``) and sets
    manifest ``"str"``; ``forcing=True`` writes ``forcing/river.txt`` and sets
    manifest ``"forcing": {"dir": "forcing"}``. Both span ``obs_days`` -- the
    fixture's single day count -- so pass the same value as
    ``make_box_run(days=...)`` when the run is not the default 10 days.
    With both flags False the output is byte-identical to the pre-PR-3 fixture.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    if str_file:
        (project_dir / "fixture.str").write_text(fixture_str(obs_days))
    if forcing:
        (project_dir / "forcing").mkdir(exist_ok=True)
        (project_dir / "forcing" / "river.txt").write_text(_river(obs_days))
    (project_dir / "fixture.grd").write_text(_grd())
    (project_dir / "boxes.txt").write_text(
        f"{IDBOX} 9 3\n{len(ELEMENTS)} 3 3\n"
        + "\n".join(f"{e} {b}" for e, b in ELEMENT_BOX.items())
        + "\n"
    )
    if polygons:
        (project_dir / "box_polygons.geojson").write_text(json.dumps(_geojson()))
    obs = ["date,site,variable,value"]
    for d in range(1, obs_days + 1):
        day = T0 + timedelta(days=d - 1)
        obs.append(f"{day:%Y-%m-%d},A,salinity,{0.5 + 0.01 * d:.3f}")
        obs.append(f"{day:%Y-%m-%d},A,temperature,{11.0 + 0.1 * d:.3f}")
        obs.append(f"{day:%Y-%m-%d},A,level,{500 + d}")
    obs.append("2009-01-05,A,level,0")  # zero sentinel -> dropped on load
    obs.append("2009-01-03,B,salinity,1.0")  # unmapped site
    (project_dir / "observations.csv").write_text("\n".join(obs) + "\n")
    (project_dir / "sites.csv").write_text(
        "site,lat,lon,box\nA,55.505,21.005,1\nB,55.505,21.025,\n"
    )
    manifest = {
        "schema": 1,
        "title": "Fixture lagoon",
        "boxes": {
            "polygons": "box_polygons.geojson" if polygons else None,
            "layer": None,
            "id_field": "box",
        },
        "grid": {"grd": "fixture.grd", "bas": None, "boxes_txt": "boxes.txt"},
        "str": "fixture.str" if str_file else None,
        "forcing": {"dir": "forcing"} if forcing else None,
        "runs": [{"id": run_id, "label": "fixture run", "dir": str(run_dir)}]
        + [{"id": i, "label": label, "dir": str(d)} for i, label, d in (extra_runs or [])],
        "observations": {"file": "observations.csv", "sites": "sites.csv"},
    }
    (project_dir / "boxmodel.json").write_text(json.dumps(manifest, indent=1))
    return project_dir
