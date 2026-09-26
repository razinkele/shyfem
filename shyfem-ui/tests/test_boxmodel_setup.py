"""Tests for ``shyfem_ui.services.boxmodel_setup`` (box-model PR 3, Task 2).

The tolerant STR reader is *defined by* the real Curonian STR
(``curonian29_1993_2016.str``): ``CURONIAN_EXCERPT`` below is copied
verbatim from that file (tabs included) and every item of the plan's
acceptance list is one test on it. Forcing files are built inline in
``tmp_path`` -- this file deliberately does not import
``tests/_boxmodel_fixture.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

from shyfem_ui.config import Config
from shyfem_ui.services import boxmodel_setup as bs
from shyfem_ui.services.boxmodel_setup import (
    Boundary,
    StrSection,
    StrSetup,
    StrSetupError,
    boundaries,
    kind,
    period_from_summary,
    read_forcing_series,
    read_str_tolerant,
    resolve_forcing_file,
    section_interfaces,
    str_summary,
)

# Copied verbatim (sed line ranges 1-9, 11-27, 29, 35, 57-59, 61-70, 107-109,
# 114-123, 125-132, 171-177, 188-194, 206-218) from
# ``~/.shyfem-ui/users/admin/Curonian 29-box/curonian29_1993_2016.str``.
# Do not reformat: the tabs and the odd spacing are the point.
CURONIAN_EXCERPT = r"""
************************ SECTION TITLE **********************
 - set simulation title and grid name

$title
        Curonian 29-box, 2d, 1993-2016 continuous
        curonian29
	curonian29
$end
************************ SECTION PARA **********************
 - set parameter for the simulation

 -----	the starting time of the input files is 1/1/1997 = 0
 itanf  = 347068800	 itend  = 536450400	idt = 300	--> 2008-2013
 itanf  = 378691200	 itend  = 410223600	idt = 300	--> 2009


        itanf  = '2013-01-01'   itend  = '2013-12-31::06:00'	idt = '5m'
        itanf  = '2015-01-01'   itend  = '2015-01-05::23:00'	idt = '5m'
&para
        itanf  = '1993-01-01'   itend  = '2016-12-31'	idt = '5m'
	idtbox = '1h'		!box output -- the deliverable
        idtflx = '1h'		!box fluxes -- needed by the box model
        idtext = '1h'		!extra points, small (~3 MB/yr)
        idtout = 0		!no hydro .shy  (was '6h' = 64 MB/yr)
        idtcon = 0		!no scalar .shy (was '6h' = 15 MB/yr)
        date   = 19930101   time   = 000000
        ireib  = 5	czdef  = 0.0025
	nomp   = 4
&end
	nsigma = 12
************************ SECTION WAVES **********************
 - set parameters for wave model
$waves
        itmwav = '1993-01-01'	idtwav = 0	!no wave .shy (22 MB/yr)
        iwave  = 1		!the wave MODEL still runs; only its
				!output is switched off (waves_admin.f90:
				!"if idtwav is not defined ... does not
				!write any results")
$end
dtwave = '5m'
levels
      1 2 3 4 5 6 7 8 9 10 11 13 15 18 25 35
end
$bound1     ---- Baltic sea ---- raw CMEMS sla, NOT rescaled
       kbound  = 1547 1548 1549 1550 1551 1552 1553
                 1554 1555 1556 1557 1558 1559 1560
                 1561 1562 1563 1564 1565 1566 1567
                 1568 1569 1570 1571 1572 2292 188
	ibtyp  = 1
	boundn = 'fem_forcing/sea_level.fem'
	saltn  = 'fem_forcing/salt.fem'
	tempn  = 'fem_forcing/temp.fem'
$end
$bound2     ---- Nemunas (Silininkai) river ---- discharge in m3/s
      kbound = 1855 1856 1882 1883
      zfact  = 0.25
      ibtyp  = 3
      boundn = 'fem_forcing/nemunas.txt'
      temp   = -999
      salt   = 0.1
$end
$name
      !gotmpa = ''		!not needed: iturb = 0 (2-d run)
      wind = 'fem_forcing/wind.fem'
      qflux= 'fem_forcing/heat.fem'
      rain = 'fem_forcing/rain.fem'
      ice  = 'fem_forcing/ice.fem'
$end
$extra
        1823 'Klaipeda'
        1657 'Juodkrante'
        1692 'Nida'
        1947 'Vente'
        2580 'Nemunas'
$end
flux
        2354 2355 2385 2384 2383 0
        6611 7297 0
        7473 7955 0
        6168 6169 0
        7169 6029 0
       896 897 953 980 1063 1061 1059 1057 1055 1053 1051 1049
       1043 951 889 887 888 1073 1075 1159 1163 1165 1167 1169 1171 1173
       1175 1177 1179 1181 1183 1185 1187 1189 1191 1193 1198 1200 1202
       1204 1206 1208 1210 1212 1214 1216 1218 1220 1222 1224 1226 1228
       1230 1232 1234 1041 1027 907 863 850 851 0

end
"""

# 1-based line numbers *inside the excerpt* (they differ from the real file).
LINE_DECOY_QUOTED_1 = 18  # itanf = '2013-01-01' ... (outside any section)
LINE_DECOY_QUOTED_2 = 19
LINE_NSIGMA = 31
LINE_DTWAVE = 41


@pytest.fixture
def excerpt_path(tmp_path: Path) -> Path:
    p = tmp_path / "curonian_excerpt.str"
    p.write_text(CURONIAN_EXCERPT)
    return p


@pytest.fixture
def setup(excerpt_path: Path) -> StrSetup:
    return read_str_tolerant(excerpt_path)


def _write(tmp_path: Path, text: str, name: str = "t.str") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


# -- module hygiene ----------------------------------------------------------


def test_module_imports_nothing_from_components():
    src = Path(bs.__file__).read_text()
    mods: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            mods.append(node.module or "")
        elif isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
    assert mods
    assert not any(m.startswith("shyfem_ui.components") for m in mods), mods
    assert not any(m.startswith("shyfem_ui.pages") for m in mods), mods


# -- acceptance list ---------------------------------------------------------


def test_01_dollar_and_ampersand_open_and_close_sections_in_file_order(setup: StrSetup):
    names = [s.name for s in setup.sections]
    assert names == [
        "title",
        "para",
        "waves",
        "bound1",
        "bound2",
        "name",
        "extra",
    ]
    # `&para ... &end` is a section like any `$...$end` one.
    assert setup.get("para") is not None
    assert setup.get("PARA") is setup.get("para")  # case-insensitive lookup
    assert setup.get("nope") is None
    assert [b.name for b in setup.bounds()] == ["bound1", "bound2"]
    assert isinstance(setup.sections[0], StrSection)


def test_01b_names_reported_lower_case_and_repeated_names_distinct(tmp_path: Path):
    p = _write(tmp_path, "$BOUND1\n kbound = 1 2\n$END\n&Bound2\n kbound = 3 4\n&End\n")
    got = read_str_tolerant(p)
    assert [s.name for s in got.sections] == ["bound1", "bound2"]
    assert got.sections[0].params["kbound"] == [1, 2]
    assert got.sections[1].params["kbound"] == [3, 4]


def test_02_trailing_header_text_becomes_title_with_dashes_stripped(setup: StrSetup):
    assert setup.get("bound1").title == "Baltic sea ---- raw CMEMS sla, NOT rescaled"
    assert setup.get("bound2").title == "Nemunas (Silininkai) river ---- discharge in m3/s"
    assert setup.get("para").title == ""
    assert setup.get("name").title == ""


def test_03_several_pairs_per_line_quotes_negatives_comments(setup: StrSetup):
    para = setup.get("para").params
    # three pairs on one line, tab-separated, single-quoted
    assert para["itanf"] == "1993-01-01"
    assert para["itend"] == "2016-12-31"
    assert para["idt"] == "5m"
    # trailing `!` comments stripped, tab before the comment
    assert para["idtbox"] == "1h"
    assert para["idtout"] == "0"
    # bare values, two per line
    assert para["date"] == "19930101" and para["time"] == "000000"
    assert para["ireib"] == "5" and para["czdef"] == "0.0025"
    assert para["nomp"] == "4"
    b2 = setup.get("bound2").params
    assert b2["temp"] == "-999"  # bare negative number
    assert b2["salt"] == "0.1"
    assert b2["zfact"] == "0.25"
    assert b2["boundn"] == "fem_forcing/nemunas.txt"
    # whole lines starting with `!` are skipped: `!gotmpa = ''` inside $name
    name = setup.get("name").params
    assert "gotmpa" not in name
    assert name["wind"] == "fem_forcing/wind.fem"
    assert name["qflux"] == "fem_forcing/heat.fem"  # `qflux= '...'` (no space)


def test_03b_no_space_before_quote_double_quotes_and_hash_lines(tmp_path: Path):
    p = _write(
        tmp_path,
        "$bound3\n"
        "  boundn ='fem_forcing/minija.txt'\n"
        '  tempn="a b.fem"  ! trailing comment\n'
        "# a hash comment line\n"
        "  saltn = 'has!bang.fem'\n"
        "$end\n",
    )
    prm = read_str_tolerant(p).get("bound3").params
    assert prm["boundn"] == "fem_forcing/minija.txt"
    assert prm["tempn"] == "a b.fem"
    assert prm["saltn"] == "has!bang.fem"  # `!` inside quotes is not a comment


def test_04_multi_line_integer_list_continues_until_a_pair_line(setup: StrSetup):
    kb = setup.get("bound1").params["kbound"]
    assert isinstance(kb, list) and len(kb) == 28
    assert kb[:7] == [1547, 1548, 1549, 1550, 1551, 1552, 1553]
    assert kb[-3:] == [1572, 2292, 188]
    # the `ibtyp = 1` line ended the continuation
    assert setup.get("bound1").params["ibtyp"] == "1"
    assert setup.get("bound2").params["kbound"] == [1855, 1856, 1882, 1883]


def test_04b_only_a_bare_numeric_list_continues(tmp_path: Path):
    p = _write(
        tmp_path,
        "$bound1\n boundn = 'x.txt'\n 5 6\n ibtyp = 1\n 7\n kbound = 1 2\n 3 4\n\n 5\n$end\n",
    )
    prm = read_str_tolerant(p).get("bound1").params
    assert prm["boundn"] == "x.txt"  # a quoted value never continues
    assert prm["ibtyp"] == "1"  # nor a scalar
    assert prm["kbound"] == [1, 2, 3, 4, 5]  # a blank line does not break the list


def test_05_key_value_lines_outside_sections_never_set_parameters(setup: StrSetup):
    para = setup.get("para").params
    assert para["itanf"] == "1993-01-01"  # not 347068800 (decoy) nor '2013-01-01'
    assert para["itend"] == "2016-12-31"
    assert "nsigma" not in para
    assert "dtwave" not in setup.get("waves").params
    for s in setup.sections:
        assert "347068800" not in str(s.params.values())


def test_06_orphan_assignments_collected_with_line_numbers(setup: StrSetup):
    assert (LINE_NSIGMA, "nsigma", "12") in setup.orphans
    assert (LINE_DTWAVE, "dtwave", "5m") in setup.orphans
    # The quoted decoy lines are made only of pairs, so they are orphans too
    # (SHYFEM ignores them exactly like nsigma).
    assert (LINE_DECOY_QUOTED_1, "itanf", "2013-01-01") in setup.orphans
    assert (LINE_DECOY_QUOTED_2, "itend", "2015-01-05::23:00") in setup.orphans
    # The `--> 2008-2013` decoy lines are prose (a non-pair token follows), and
    # `1/1/1997 = 0` has no identifier key: neither is an orphan.
    assert not any(v in ("347068800", "378691200", "0") for _, _, v in setup.orphans)
    assert not any(k == "1997" for _, k, _ in setup.orphans)
    # orphans are in file order
    assert [ln for ln, _, _ in setup.orphans] == sorted(ln for ln, _, _ in setup.orphans)


def test_06b_pairs_inside_a_bare_word_block_are_not_orphans(tmp_path: Path):
    # Curonian idiom: a header without its marker disables the section.
    p = _write(
        tmp_path,
        "seaice\n        itmice = '2007-01-01'\tidtice = '1d'\n        iice = 1\nend\n"
        "stray = 1\n$para\n idt = '5m'\n$end\n",
    )
    got = read_str_tolerant(p)
    assert got.orphans == [(5, "stray", "1")]
    assert [s.name for s in got.sections] == ["para"]


def test_07_bare_word_blocks_skipped_and_bare_end_never_closes(setup: StrSetup):
    names = [s.name for s in setup.sections]
    assert "levels" not in names and "flux" not in names
    # `flux ... end` follows `$extra ... $end`; a bare `end` closes nothing.
    extra = setup.get("extra")
    assert not any("2354" in ln for ln in extra.lines)
    # and the `levels ... end` block before $bound1 did not swallow $bound1
    assert setup.get("bound1") is not None


def test_07b_bare_end_inside_a_section_is_content(tmp_path: Path):
    p = _write(tmp_path, "$title\nend\nend\n$end\n$name\n wind = 'w.fem'\n$end\n")
    got = read_str_tolerant(p)
    assert got.get("title").lines == ["end", "end"]
    assert got.get("name").params["wind"] == "w.fem"


def test_08_title_and_extra_keep_raw_lines_and_never_raise(setup: StrSetup):
    title = setup.get("title")
    assert title.params == {}
    assert [ln.strip() for ln in title.lines] == [
        "Curonian 29-box, 2d, 1993-2016 continuous",
        "curonian29",
        "curonian29",
    ]
    extra = setup.get("extra")
    assert extra.params == {}
    assert [ln.split() for ln in extra.lines][0] == ["1823", "'Klaipeda'"]
    assert len(extra.lines) == 5


def test_09_banners_and_comment_lines_ignored_tabs_are_whitespace(setup: StrSetup):
    assert all(s.name.isidentifier() for s in setup.sections)
    assert not any("SECTION" in k for s in setup.sections for k in s.params)
    assert setup.orphans and not any("SECTION" in k for _, k, _ in setup.orphans)
    # tab-separated pairs (`ireib  = 5\tczdef  = 0.0025`) parsed as two pairs
    para = setup.get("para").params
    assert para["ireib"] == "5" and para["czdef"] == "0.0025"


def test_09b_size_caps_raise_naming_the_file(tmp_path: Path):
    big = _write(tmp_path, "$para\n idt = 1\n$end\n" + "x" * 2000, "big.str")
    with pytest.raises(StrSetupError, match="big.str"):
        read_str_tolerant(big, max_bytes=1000)
    long_line = _write(tmp_path, "$para\n idt = 1\n" + "y" * 5000 + "\n$end\n", "long.str")
    with pytest.raises(StrSetupError, match="long.str"):
        read_str_tolerant(long_line)
    # the message never leaks the directory
    with pytest.raises(StrSetupError) as ei:
        read_str_tolerant(long_line)
    assert str(tmp_path) not in str(ei.value)


def test_09c_reader_never_raises_on_odd_content(tmp_path: Path):
    p = _write(
        tmp_path,
        "$para\n = 5\n a =\n b = = 3\n 1 2 = 4\n c = 'unterminated\n$end\n$\n&\n$end\n",
    )
    got = read_str_tolerant(p)
    assert got.get("para") is not None
    latin = tmp_path / "latin.str"
    latin.write_bytes(b"$title\n Ma\xf1ana\n$end\n")
    assert read_str_tolerant(latin).get("title").lines


def test_10_duplicate_keys_last_wins_earlier_kept(tmp_path: Path):
    p = _write(tmp_path, "$para\n idt = 300\n idt = '5m'\n kbound = 1 2\n kbound = 3\n$end\n")
    sec = read_str_tolerant(p).get("para")
    assert sec.params["idt"] == "5m"
    assert sec.params["kbound"] == "3"
    assert sec.duplicates == {"idt": ["300"], "kbound": ["1 2"]}


def test_10b_no_duplicates_in_the_curonian_excerpt(setup: StrSetup):
    assert all(s.duplicates == {} for s in setup.sections)


def test_setup_path_name_is_basename_only(setup: StrSetup, excerpt_path: Path):
    assert setup.path_name == excerpt_path.name
    assert str(excerpt_path.parent) not in setup.path_name


# -- boundaries --------------------------------------------------------------


def test_boundaries_on_the_excerpt(setup: StrSetup):
    bnds = boundaries(setup)
    assert [b.number for b in bnds] == [1, 2]
    b1, b2 = bnds
    assert isinstance(b1, Boundary)
    assert b1.title == "Baltic sea ---- raw CMEMS sla, NOT rescaled"
    assert b1.ibtyp == 1 and kind(b1) == "level"
    assert len(b1.kbound) == 28 and b1.kbound[0] == 1547
    assert b1.zfact == 1.0
    assert b1.boundn == "fem_forcing/sea_level.fem"
    assert b1.other_files == {
        "saltn": "fem_forcing/salt.fem",
        "tempn": "fem_forcing/temp.fem",
    }
    assert b2.ibtyp == 3 and kind(b2) == "discharge"
    assert b2.kbound == [1855, 1856, 1882, 1883]
    assert b2.zfact == 0.25
    assert b2.boundn == "fem_forcing/nemunas.txt"
    assert b2.other_files == {}


def test_boundaries_sorted_by_number_single_node_and_unknown_kind(tmp_path: Path):
    p = _write(
        tmp_path,
        "$bound10 -- ten --\n kbound = 7\n ibtyp = 2\n$end\n"
        "$bound2\n kbound = 1 2\n$end\n"
        "$bound3\n kbound = 4\n ibtyp = x\n conzn = 'c.fem'\n$end\n",
    )
    bnds = boundaries(read_str_tolerant(p))
    assert [b.number for b in bnds] == [2, 3, 10]
    assert bnds[2].kbound == [7] and bnds[2].title == "ten"
    assert bnds[0].ibtyp is None and kind(bnds[0]) == "unknown"
    assert bnds[0].boundn is None
    assert bnds[1].ibtyp is None and kind(bnds[1]) == "unknown"
    assert bnds[1].other_files == {"conzn": "c.fem"}


def test_boundaries_bad_zfact_raises(tmp_path: Path):
    p = _write(tmp_path, "$bound1\n kbound = 1\n zfact = abc\n$end\n")
    with pytest.raises(StrSetupError, match="bound1"):
        boundaries(read_str_tolerant(p))


# -- summary / period --------------------------------------------------------


def test_str_summary_on_the_excerpt(setup: StrSetup):
    s = str_summary(setup)
    assert s["title"] == "Curonian 29-box, 2d, 1993-2016 continuous"
    assert s["itanf"] == "1993-01-01" and s["itend"] == "2016-12-31"
    assert s["idt"] == "5m" and s["idtbox"] == "1h" and s["idtflx"] == "1h"
    assert s["date"] == "19930101" and s["time"] == "000000"
    assert s["ireib"] == "5" and s["czdef"] == "0.0025"
    assert s["nomp"] == "4"
    # keys absent from the excerpt's &para head are absent from the summary
    assert "ibarcl" not in s and "iheat" not in s
    assert f"nsigma = 12 (line {LINE_NSIGMA})" in s["orphans"]
    assert f"dtwave = 5m (line {LINE_DTWAVE})" in s["orphans"]
    assert s["orphans"].count(", ") == len(setup.orphans) - 1
    assert all(isinstance(v, str) for v in s.values())


def test_str_summary_without_para_or_orphans():
    st = StrSetup(sections=[], orphans=[], path_name="x.str")
    assert str_summary(st) == {}
    st2 = StrSetup(
        sections=[StrSection("title", "", {}, ["  My run  ", "grid"], {})],
        orphans=[],
        path_name="x.str",
    )
    assert str_summary(st2) == {"title": "My run"}


def test_period_from_summary(setup: StrSetup):
    p = period_from_summary(str_summary(setup))
    assert p == (pd.Timestamp("1993-01-01"), pd.Timestamp("2016-12-31"))
    assert period_from_summary({"itanf": "2013-01-01", "itend": "2013-12-31::06:00"}) == (
        pd.Timestamp("2013-01-01"),
        pd.Timestamp("2013-12-31 06:00"),
    )
    assert period_from_summary({"itanf": "2013-01-01"}) is None
    assert period_from_summary({"itanf": "347068800", "itend": "536450400"}) is None
    assert period_from_summary({"itanf": "2013-13-01", "itend": "2013-12-31"}) is None
    assert period_from_summary({}) is None


# -- forcing: resolve --------------------------------------------------------


@pytest.fixture
def forcing_dir(tmp_path: Path) -> Path:
    d = tmp_path / "proj" / "forcing"
    d.mkdir(parents=True)
    (d / "nemunas.txt").write_text("# c\n2009-01-01::06:00:00  100\n")
    return d


@pytest.fixture
def local_config(tmp_path: Path) -> Config:
    # Local mode: confine_path resolves against work_dir/shyfem_dir/tmp.
    return Config(deployment_mode="local", work_dir=str(tmp_path))


def test_resolve_uses_basename_and_confines(forcing_dir: Path, local_config: Config):
    path, note = resolve_forcing_file(
        "fem_forcing/nemunas.txt", forcing_dir, local_config, user=None
    )
    assert note is None
    assert path == (forcing_dir / "nemunas.txt").resolve()


def test_resolve_non_txt_is_not_read(forcing_dir: Path, local_config: Config):
    assert resolve_forcing_file("fem_forcing/sea_level.fem", forcing_dir, local_config, None) == (
        None,
        "not read (.fem)",
    )


def test_resolve_without_forcing_dir(local_config: Config):
    assert resolve_forcing_file("fem_forcing/nemunas.txt", None, local_config, None) == (
        None,
        "forcing dir not configured",
    )


def test_resolve_missing_file(forcing_dir: Path, local_config: Config):
    assert resolve_forcing_file("x/minija.txt", forcing_dir, local_config, None) == (
        None,
        "not found",
    )
    assert resolve_forcing_file("", forcing_dir, local_config, None)[0] is None


def test_resolve_refuses_symlinks(forcing_dir: Path, local_config: Config, tmp_path: Path):
    target = tmp_path / "secret.txt"
    target.write_text("2009-01-01::00:00:00 1\n")
    (forcing_dir / "link.txt").symlink_to(target)
    assert resolve_forcing_file("link.txt", forcing_dir, local_config, None) == (
        None,
        "symlink refused",
    )
    # a symlinked directory component is refused too
    (tmp_path / "proj" / "forcing_link").symlink_to(forcing_dir)
    assert resolve_forcing_file(
        "nemunas.txt", tmp_path / "proj" / "forcing_link", local_config, None
    ) == (None, "symlink refused")


def test_resolve_refuses_directories(forcing_dir: Path, local_config: Config):
    (forcing_dir / "dir.txt").mkdir()
    path, note = resolve_forcing_file("dir.txt", forcing_dir, local_config, None)
    assert path is None and note


def test_resolve_outside_allowed_roots(tmp_path: Path):
    # Confinement is the config's call: a ValueError from confine_path is the
    # "outside the allowed roots" note, never an exception to the caller.
    class Deny(Config):
        def confine_path(self, *a, **k):
            raise ValueError("nope")

    d = tmp_path / "f"
    d.mkdir()
    (d / "a.txt").write_text("")
    deny = Deny(deployment_mode="local", work_dir=str(tmp_path))
    assert resolve_forcing_file("a.txt", d, deny, None) == (None, "outside the allowed roots")


def test_resolve_calls_confine_path_with_must_exist(forcing_dir: Path, tmp_path: Path):
    calls: list = []

    class Spy(Config):
        def confine_path(self, path, user, **kw):
            calls.append((Path(path), user, kw))
            return Path(path).resolve()

    spy = Spy(deployment_mode="local", work_dir=str(tmp_path))
    user = {"username": "admin"}
    resolve_forcing_file("nemunas.txt", forcing_dir, spy, user)
    assert calls == [(forcing_dir / "nemunas.txt", user, {"must_exist": True})]


# -- forcing: read -----------------------------------------------------------


def _river(tmp_path: Path, days: int = 5, name: str = "river.txt") -> Path:
    lines = ["# fixture river, m3/s"]
    t0 = pd.Timestamp("2009-01-01 06:00:00")
    for i in range(days):
        stamp = (t0 + pd.Timedelta(days=i)).strftime("%Y-%m-%d::%H:%M:%S")
        lines.append(f"{stamp}  {100 + i}")
    lines.append("")
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def test_read_forcing_series_basic(tmp_path: Path):
    s = read_forcing_series(_river(tmp_path))
    assert isinstance(s, pd.Series)
    assert s.dtype == "float64"
    assert isinstance(s.index, pd.DatetimeIndex)
    assert s.index.dtype == "datetime64[ns]"
    assert len(s) == 5
    assert s.index[0] == pd.Timestamp("2009-01-01 06:00:00")
    assert s.iloc[0] == 100.0 and s.iloc[-1] == 104.0


def test_read_forcing_series_first_value_only_and_short_stamps(tmp_path: Path):
    p = tmp_path / "r.txt"
    p.write_text(
        "2009-01-01::06:00:00\t1.5 2.5 3.5\n"
        "\n"
        "2009-01-02::06:00  -2\n"
        "   # indented comment\n"
        "2009-01-03  7e1\n"
    )
    s = read_forcing_series(p)
    assert list(s.values) == [1.5, -2.0, 70.0]
    assert s.index[1] == pd.Timestamp("2009-01-02 06:00") and s.index[2] == pd.Timestamp(
        "2009-01-03"
    )


def test_read_forcing_series_malformed_line_names_the_line(tmp_path: Path):
    p = tmp_path / "bad.txt"
    p.write_text("# h\n2009-01-01::06:00:00 1\n2009-01-02::06:00:00\n")
    with pytest.raises(StrSetupError, match="line 3"):
        read_forcing_series(p)
    p.write_text("2009-01-01::06:00:00 1\n01/02/2009 5\n")
    with pytest.raises(StrSetupError, match="line 2"):
        read_forcing_series(p)
    p.write_text("2009-01-01::06:00:00 abc\n")
    with pytest.raises(StrSetupError, match="line 1"):
        read_forcing_series(p)
    p.write_text("2009-02-30::06:00:00 1\n")
    with pytest.raises(StrSetupError, match="line 1"):
        read_forcing_series(p)


def test_read_forcing_series_caps(tmp_path: Path):
    p = _river(tmp_path, days=10)
    with pytest.raises(StrSetupError, match="river.txt"):
        read_forcing_series(p, max_bytes=50)
    with pytest.raises(StrSetupError, match="rows"):
        read_forcing_series(p, max_rows=3)
    assert len(read_forcing_series(p, max_rows=10)) == 10


def test_read_forcing_series_refuses_a_symlink_leaf(tmp_path: Path):
    real = _river(tmp_path)
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    with pytest.raises(StrSetupError):
        read_forcing_series(link)


def test_read_forcing_series_empty_file(tmp_path: Path):
    p = tmp_path / "e.txt"
    p.write_text("# only a comment\n")
    s = read_forcing_series(p)
    assert len(s) == 0 and isinstance(s.index, pd.DatetimeIndex)


# -- section interfaces ------------------------------------------------------


def test_section_interfaces_from_meta():
    meta = {
        "sections": [
            {"section": 1, "from_box": 1, "to_box": 2},
            {"section": 2, "from_box": -2, "to_box": 3},
            {"section": 3, "from_box": 4, "to_box": 5},  # no coordinates
            {"section": 4, "from_box": 6, "to_box": -1},
        ],
        "section_nodes": {
            "1": [[21.0, 55.0], [21.1, 55.1]],
            "2": [[21.2, 55.2], [21.3, 55.3], [21.4, 55.4]],
            "3": [],
            "4": [[21.5, 55.5], [21.6, 55.6]],
        },
    }
    got = section_interfaces(meta)
    assert [g["section"] for g in got] == [1, 2, 4]
    assert got[0] == {
        "section": 1,
        "from_box": 1,
        "to_box": 2,
        "open_boundary": None,
        "path": [[21.0, 55.0], [21.1, 55.1]],
    }
    assert got[1]["open_boundary"] == 2 and got[1]["from_box"] == -2
    assert len(got[1]["path"]) == 3
    assert got[2]["open_boundary"] == 1  # negative to_box tolerated
    assert all(isinstance(g["section"], int) for g in got)


def test_section_interfaces_tolerates_missing_or_odd_meta():
    assert section_interfaces({}) == []
    assert section_interfaces({"sections": None, "section_nodes": None}) == []
    assert section_interfaces({"sections": [{"section": 1}], "section_nodes": {}}) == []
    got = section_interfaces(
        {
            "sections": [{"section": "1", "from_box": "1", "to_box": "2"}],
            "section_nodes": {"1": [[0, 0], [1, 1]]},
        }
    )
    assert got and got[0]["section"] == 1 and got[0]["path"] == [[0.0, 0.0], [1.0, 1.0]]


def test_03c_quoted_value_may_contain_an_equals_sign(tmp_path: Path):
    p = _write(tmp_path, "$name\n wind = 'a = b.fem'  rain = 'r.fem'\n$end\n")
    prm = read_str_tolerant(p).get("name").params
    assert prm == {"wind": "a = b.fem", "rain": "r.fem"}


def test_resolve_forcing_file_survives_a_nul_byte_in_the_name(tmp_path):
    """The STR reader never raises on content, so a ``boundn`` with an embedded
    NUL byte reaches the resolver; pathlib refuses to stat it. It must come
    back as a note, not a ValueError escaping into a render (PR 3 review)."""
    forcing = tmp_path / "forcing"
    forcing.mkdir()
    cfg = Config(deployment_mode="local", work_dir=str(tmp_path))
    path, note = bs.resolve_forcing_file("fem_forcing/ri\x00ver.txt", forcing, cfg, None)
    assert path is None and note == "not found"
