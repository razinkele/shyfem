#!/usr/bin/env python3
"""Compare two SHYFEM Lagrangian particle files (NAME.lgr.shy) by particle id.

usage: lgr_compare.py A.lgr.shy B.lgr.shy --mode {pos|ids} [--tol FLOAT]
                      [--tol-hl FLOAT] [--max-beyond-last N]
                      [--max-largest D] [--max-tt-differ N]
                      [--same-counts] [--nel N --nlv N]
       lgr_compare.py FILE.lgr.shy --summary
       lgr_compare.py FILE.lgr.shy --dims

--mode pos compares, for every id present in both files and the same block:
x, y within --tol; z within 1e-5; lb, type (ints) exact; tt (float64), s and
the custom values c(1:ncust) (float32) exact; hl within --tol-hl (default
1e-4).  NaN in any compared field is a failure.  The element number ie of a
pair whose x and y are equal (distance exactly 0) must be equal too (the
elements are global numbers, so a pair in the same place is in the same
element): a pair at distance 0 with another ie is a failure, counted per
block and in a line "ie: ...".  For a pair at another distance ie is
information (the number of such pairs is printed per block).

The inserted block (iwhat = -1) holds fixed release data, identical in any two
runs: in --mode pos every pair of that block must be exactly equal in every
field (x, y, z, lb, ie, tt, type, s, custom values), whatever --tol, the
floors and --max-tt-differ allow for the other blocks, except hl: hl is not
release data but the layer thickness computed at output time, which follows
the water level and so differs at single-precision rounding between runs
(serial against serial too, up to 2e-6 relative), so it is compared within
--tol-hl as in every block.  A difference is a failure, printed with its id
and counted in a line "inserted block: ...".

--max-beyond-last N, --max-largest D (--mode pos only) hold the positions
against floors instead of --tol pair by pair, as lgr_dbg_compare.py part does
with the same options.  The distance of a pair is max(|dx|, |dy|).  A pair
beyond --tol is then no failure by itself; the comparison fails if more than
N particles (ids, any block) are beyond --tol at the last output time both
files share, or if the largest distance of any pair at any output is greater
than D or NaN.  Either option alone, or both.  hl depends on the element, so
under the floors it is compared only for pairs whose element ie is the same
in both files (the number of pairs left out is printed per block).
Everything else gates as without the options (ids per block, output times,
NaN positions, lb, z, type, tt, s, custom values).  A line "floor: ..."
states each test with its value, its limit and its verdict.  Without the
two options nothing changes.

--max-tt-differ N (--mode pos only): a time tt that differs is then no
failure by itself; the comparison fails if more than N particles (ids
matched in the same block, at any output) have a different tt.  The count
is printed per block and output ("tt differs K") and in a line "tt: ...".
Without the option tt is compared exactly, as before.  With the option every
particle whose tt differs is listed with both values ("tt a/b"; at most
MAX_TT_LINES lines per block and output, the number left out is printed),
within the floor or not.

--dims prints "nkn N nel E nlv L" from the model header of the file (its
third record: nkn, nel, npr, nlv, nvar); used to pass --nel and --nlv.

Exit status: 0 = files agree, 1 = they differ, 2 = a file cannot be read.

File layout (gfortran sequential unformatted, little endian, every record is
<int32 length><payload><int32 length>): model header (content ignored), one
record `ncust`, then per output time three blocks (iwhat = 0 active,
-1 inserted, 1 exited).  Each block is a record (dtime f8, n i4, iwhat i4)
followed by n particles of three records each:
  (id i4, type i4, tt f8, s f4, ie i4)
  (x f4, y f4, z f4, lb i4, hl f4)
  (c f4 * ncust)
"""
import argparse
import math
import struct
import sys

IWHAT_ORDER = (0, -1, 1)
BLOCK_NAME = {0: "active", -1: "inserted", 1: "exited"}
Z_TOL = 1e-5
MAX_TT_LINES = 20
HEAD = struct.Struct("<dii")
REC1 = struct.Struct("<iidfi")
REC2 = struct.Struct("<fffif")


class FormatError(Exception):
    pass


def split_records(data):
    """Return [(payload_start, length)] for every record of the file."""
    recs = []
    pos = 0
    size = len(data)
    while pos < size:
        if pos + 4 > size:
            raise FormatError("truncated record marker at byte %d" % pos)
        (n,) = struct.unpack_from("<i", data, pos)
        end = pos + 4 + n
        if n < 0 or end + 4 > size:
            raise FormatError("bad record length %d at byte %d" % (n, pos))
        (n2,) = struct.unpack_from("<i", data, end)
        if n2 != n:
            raise FormatError("record markers differ (%d, %d) at byte %d" % (n, n2, pos))
        recs.append((pos + 4, n))
        pos = end + 4
    return recs


def block_header(data, recs, i, want_iwhat=None):
    """Decode record i as a block header; return (dtime, n, iwhat) or None."""
    if i >= len(recs):
        return None
    start, length = recs[i]
    if length != HEAD.size:
        return None
    dtime, n, iwhat = HEAD.unpack_from(data, start)
    if n < 0 or iwhat not in IWHAT_ORDER:
        return None
    if want_iwhat is not None and iwhat != want_iwhat:
        return None
    return dtime, n, iwhat


def first_block_consistent(data, recs, i, ncust):
    """Is record i the header of a well-formed iwhat=0 block?"""
    head = block_header(data, recs, i, 0)
    if head is None:
        return False
    n = head[1]
    first = i + 1
    if first + 3 * n > len(recs):
        return False
    for k in range(n):
        base = first + 3 * k
        if (recs[base][1], recs[base + 1][1], recs[base + 2][1]) != (
            REC1.size, REC2.size, 4 * ncust):
            return False
    nxt = first + 3 * n
    if nxt == len(recs):
        return True
    return block_header(data, recs, nxt, -1) is not None


def find_particle_start(data, recs):
    """Index of the first particle-block header, and ncust.

    It is the first 4-byte record followed by a 16-byte iwhat=0 header and a
    consistent first block.
    """
    for i in range(len(recs) - 1):
        if recs[i][1] != 4:
            continue
        (ncust,) = struct.unpack_from("<i", data, recs[i][0])
        if ncust < 0:
            continue
        if first_block_consistent(data, recs, i + 1, ncust):
            return i + 1, ncust
    raise FormatError("no particle section found (ncust record + iwhat=0 block)")


def read_file(path):
    """Return (ncust, [(dtime, {iwhat: {id: particle dict}, dup: [ids]})])."""
    with open(path, "rb") as fh:
        data = fh.read()
    recs = split_records(data)
    i, ncust = find_particle_start(data, recs)
    times = []
    while i < len(recs):
        blocks = {}
        dups = []
        dtime0 = None
        for iwhat in IWHAT_ORDER:
            head = block_header(data, recs, i, iwhat)
            if head is None:
                raise FormatError("%s: expected iwhat=%d block header at record %d"
                                  % (path, iwhat, i))
            dtime, n, _ = head
            if dtime0 is None:
                dtime0 = dtime
            elif dtime != dtime0:
                raise FormatError("%s: block times differ within one output (%r, %r)"
                                  % (path, dtime0, dtime))
            i += 1
            if i + 3 * n > len(recs):
                raise FormatError("%s: truncated block at record %d" % (path, i))
            parts = {}
            for _ in range(n):
                if recs[i][1] != REC1.size or recs[i + 1][1] != REC2.size or \
                        recs[i + 2][1] != 4 * ncust:
                    raise FormatError("%s: bad particle record sizes at record %d"
                                      % (path, i))
                pid, typ, tt, sink, ie = REC1.unpack_from(data, recs[i][0])
                x, y, z, lb, hl = REC2.unpack_from(data, recs[i + 1][0])
                cust = struct.unpack_from("<%df" % ncust, data, recs[i + 2][0])
                if pid in parts:
                    dups.append((BLOCK_NAME[iwhat], pid))
                parts[pid] = {"x": x, "y": y, "z": z, "lb": lb, "ie": ie, "type": typ,
                              "tt": tt, "s": sink, "hl": hl, "c": cust}
                i += 3
            blocks[iwhat] = parts
        times.append((dtime0, blocks, dups))
    return ncust, times


def fmt_ids(ids):
    return ",".join(str(k) for k in sorted(ids)) if ids else "-"


def exceeds(a, b, tol):
    """True if |a-b| > tol or either value is NaN."""
    return not abs(a - b) <= tol


def compare_pos(pa, pb, tol, tol_hl, floor=False, tt_floor=False, exact=False):
    """Return (ok, onlyA, onlyB, max_dx, max_dy, lb_ok, z_ok, n_ie, detail,
    dist, n_hl_skip, tt_ids, n_ie0, n_exact, tt_lines): dist maps every common
    id to max(|dx|, |dy|) (NaN if either is NaN); with floor a position beyond
    tol is no failure by itself (NaN still is) and hl is compared only if ie
    is equal (n_hl_skip pairs are left out); tt_ids are the common ids whose
    tt differs, with tt_floor no failure by themselves (NaN still is) and
    listed in tt_lines (all, whether or not they are a failure); n_ie0 counts
    the pairs at distance 0 whose ie differs (a failure); with exact (the
    inserted block) no tolerance and no floor applies: every field must be
    equal, n_exact counts the pairs that differ."""
    only_a = set(pa) - set(pb)
    only_b = set(pb) - set(pa)
    max_dx = max_dy = 0.0
    lb_ok = z_ok = True
    n_ie = 0
    n_hl_skip = 0
    detail = []
    tt_ids = set()
    tt_lines = []
    n_ie0 = 0
    n_exact = 0
    dist = {}
    for pid in sorted(set(pa) & set(pb)):
        a, b = pa[pid], pb[pid]
        dx, dy, dz = abs(a["x"] - b["x"]), abs(a["y"] - b["y"]), abs(a["z"] - b["z"])
        for d in (dx, dy):
            if math.isnan(d):
                max_dx = max_dy = float("nan")
        if not math.isnan(max_dx):
            max_dx, max_dy = max(max_dx, dx), max(max_dy, dy)
        dist[pid] = float("nan") if math.isnan(dx) or math.isnan(dy) else max(dx, dy)
        bad = []
        if exact:
            if exceeds(a["x"], b["x"], 0.0) or exceeds(a["y"], b["y"], 0.0):
                bad.append("position")
        elif floor:
            if math.isnan(dist[pid]):
                bad.append("position NaN")
        elif exceeds(a["x"], b["x"], tol) or exceeds(a["y"], b["y"], tol):
            bad.append("position")
        if a["lb"] != b["lb"]:
            lb_ok = False
            bad.append("lb")
        if exceeds(a["z"], b["z"], 0.0 if exact else Z_TOL):
            z_ok = False
            bad.append("z")
        if a["type"] != b["type"]:
            bad.append("type %d/%d" % (a["type"], b["type"]))
        if exceeds(a["tt"], b["tt"], 0.0):
            if exact:
                bad.append("tt %r/%r" % (a["tt"], b["tt"]))
            else:
                tt_ids.add(pid)
                if not tt_floor:
                    bad.append("tt %r/%r" % (a["tt"], b["tt"]))
                else:
                    tt_lines.append("    id %d: tt %r/%r (counted against the"
                                    " tt floor)" % (pid, a["tt"], b["tt"]))
                    if math.isnan(a["tt"]) or math.isnan(b["tt"]):
                        bad.append("tt NaN")
        if exceeds(a["s"], b["s"], 0.0):
            bad.append("s %.9g/%.9g" % (a["s"], b["s"]))
        if exact:
            if exceeds(a["hl"], b["hl"], tol_hl):
                bad.append("hl %.9g/%.9g" % (a["hl"], b["hl"]))
        elif floor and a["ie"] != b["ie"]:
            n_hl_skip += 1
        elif exceeds(a["hl"], b["hl"], tol_hl):
            bad.append("hl %.9g/%.9g" % (a["hl"], b["hl"]))
        for k, (ca, cb) in enumerate(zip(a["c"], b["c"]), 1):
            if exceeds(ca, cb, 0.0):
                bad.append("c(%d) %.9g/%.9g" % (k, ca, cb))
        if a["ie"] != b["ie"]:
            n_ie += 1
            if exact:
                bad.append("ie %d/%d" % (a["ie"], b["ie"]))
            elif dx == 0.0 and dy == 0.0:
                n_ie0 += 1
                bad.append("ie %d/%d" % (a["ie"], b["ie"]))
        if exact and bad:
            n_exact += 1
        if bad:
            detail.append("    id %d differs (%s): dx=%.4e dy=%.4e dz=%.4e lb=%d/%d"
                          % (pid, "; ".join(bad), dx, dy, dz, a["lb"], b["lb"]))
    ok = not (only_a or only_b or detail)
    return (ok, only_a, only_b, max_dx, max_dy, lb_ok, z_ok, n_ie, detail,
            dist, n_hl_skip, tt_ids, n_ie0, n_exact, tt_lines)


def floor_report(beyond_at, worst, args):
    """The floor tests of --max-beyond-last and --max-largest; beyond_at maps
    every output time both files share to the set of ids beyond --tol, worst
    is (largest distance, time).  Print one line per test, return ok."""
    ok = True
    if args.max_beyond_last is not None:
        if not beyond_at:
            print("floor: FAIL: no output time in both files")
            ok = False
        else:
            last = max(beyond_at)
            n = len(beyond_at[last])
            bad = n > args.max_beyond_last
            print("floor: particles beyond --tol %g at the last output both files"
                  " share (t=%r): %d %s %d: %s"
                  % (args.tol, last, n, ">" if bad else "<=",
                     args.max_beyond_last, "FAIL" if bad else "ok"))
            ok = ok and not bad
    if args.max_largest is not None:
        big, at = worst
        bad = not big <= args.max_largest
        print("floor: largest distance at any output%s: %.6g %s %g: %s"
              % ("" if at is None else " (t=%r)" % at, big,
                 ">" if bad else "<=", args.max_largest, "FAIL" if bad else "ok"))
        ok = ok and not bad
    return ok


def dims(path):
    """Print nkn, nel and nlv of the model header (records 1-3: (idshy,
    nvers), (ftype), (nkn, nel, npr, nlv, nvar))."""
    with open(path, "rb") as fh:
        data = fh.read(4096)
    recs = []
    pos = 0
    while len(recs) < 3:
        if pos + 4 > len(data):
            raise FormatError("%s: no model header" % path)
        (n,) = struct.unpack_from("<i", data, pos)
        if n < 0 or pos + 8 + n > len(data) or \
                struct.unpack_from("<i", data, pos + 4 + n)[0] != n:
            raise FormatError("%s: no model header" % path)
        recs.append((pos + 4, n))
        pos += 8 + n
    if [r[1] for r in recs] != [8, 4, 20]:
        raise FormatError("%s: no model header (record lengths %s)"
                          % (path, [r[1] for r in recs]))
    nkn, nel, _npr, nlv, _nvar = struct.unpack_from("<5i", data, recs[2][0])
    print("nkn %d nel %d nlv %d" % (nkn, nel, nlv))
    return 0


def check_ranges(label, parts, nel, nlv):
    """Messages for particles of one block outside 1<=ie<=nel or 1<=lb<=nlv."""
    msgs = []
    for pid in sorted(parts):
        p = parts[pid]
        if nel is not None and not 1 <= p["ie"] <= nel:
            msgs.append("    %s id %d: ie=%d outside 1..%d" % (label, pid, p["ie"], nel))
        if nlv is not None and not 1 <= p["lb"] <= nlv:
            msgs.append("    %s id %d: lb=%d outside 1..%d" % (label, pid, p["lb"], nlv))
    return msgs


def summary(path):
    """Print output-time count and, for first and last time, block counts."""
    _ncust, times = read_file(path)
    print("output times: %d" % len(times))
    for label, idx in (("first", 0), ("last", -1)):
        if not times:
            break
        dtime, blocks, _dups = times[idx]
        counts = " ".join("%s=%d" % (BLOCK_NAME[w], len(blocks[w])) for w in IWHAT_ORDER)
        ids = blocks[0]
        span = "active ids %d..%d" % (min(ids), max(ids)) if ids else "no active ids"
        print("%s output t=%r: %s; %s" % (label, dtime, counts, span))
    return 0


def run(args):
    ncust_a, times_a = read_file(args.a)
    ncust_b, times_b = read_file(args.b)
    ok = True
    if ncust_a != ncust_b:
        print("ncust differs: A=%d B=%d" % (ncust_a, ncust_b))
        ok = False
    for label, times in (("A", times_a), ("B", times_b)):
        for dtime, _blocks, dups in times:
            for name, pid in dups:
                print("t=%r file %s: duplicate id %d in %s block" % (dtime, label, pid, name))
                ok = False

    map_a = {t[0]: t[1] for t in times_a}
    map_b = {t[0]: t[1] for t in times_b}
    floor = args.max_beyond_last is not None or args.max_largest is not None
    tt_floor = args.max_tt_differ is not None
    tt_all = set()           # ids whose tt differs at some output (tt floor)
    ie0_total = 0            # pairs at distance 0 with another ie
    exact_total = 0          # pairs of the inserted block that differ
    beyond_at = {}           # ids beyond --tol per shared time (floor test)
    worst = (0.0, None)      # largest distance at any output, its time
    for dtime in sorted(set(map_a) | set(map_b)):
        if dtime not in map_b:
            print("t=%r only in A (B wrote no output at this time)" % dtime)
            ok = False
            continue
        if dtime not in map_a:
            print("t=%r only in B (A wrote no output at this time)" % dtime)
            ok = False
            continue
        ids_a, ids_b = set(), set()
        beyond_at[dtime] = set()
        for iwhat in IWHAT_ORDER:
            pa, pb = map_a[dtime][iwhat], map_b[dtime][iwhat]
            name = BLOCK_NAME[iwhat]
            ids_a |= set(pa)
            ids_b |= set(pb)
            head = "t=%r %-8s nA=%d nB=%d" % (dtime, name, len(pa), len(pb))
            if args.mode == "pos":
                (good, oa, ob, mdx, mdy, lbok, zok, n_ie, detail, dist,
                 n_hl_skip, tt_ids, n_ie0, n_exact, tt_lines) = compare_pos(
                     pa, pb, args.tol, args.tol_hl, floor, tt_floor,
                     exact=(iwhat == -1))
                ie0_total += n_ie0
                exact_total += n_exact
                tail = ""
                if floor:
                    over = {pid for pid, d in dist.items() if not d <= args.tol}
                    beyond_at[dtime] |= over
                    for pid in sorted(dist):
                        d = dist[pid]
                        if not math.isnan(worst[0]) and (math.isnan(d) or d > worst[0]):
                            worst = (d, dtime)
                    tail = (", beyond tol %d, hl not gated (ie differs) %d"
                            % (len(over), n_hl_skip))
                if tt_floor:
                    tt_all |= tt_ids
                    tail += ", tt differs %d" % len(tt_ids)
                if iwhat == -1:
                    tail += ", exact: differing %d" % n_exact
                else:
                    tail += ", ie differs at distance 0 (gated) %d" % n_ie0
                print("%s only in A: %s only in B: %s max|dx|=%.4e max|dy|=%.4e "
                      "lb %s z %s ie differs (info): %d%s"
                      % (head, fmt_ids(oa), fmt_ids(ob), mdx, mdy,
                         "match" if lbok else "DIFFER", "match" if zok else "DIFFER",
                         n_ie, tail))
                for line in detail:
                    print(line)
                for line in tt_lines[:MAX_TT_LINES]:
                    print(line)
                if len(tt_lines) > MAX_TT_LINES:
                    print("    ... %d more particles with another tt"
                          % (len(tt_lines) - MAX_TT_LINES))
                ok = ok and good
            else:
                line = head
                if len(pa) != len(pb):
                    line += " (count differs)"
                    if args.same_counts:
                        ok = False
                print(line)
        if args.mode == "ids":
            only_a, only_b = ids_a - ids_b, ids_b - ids_a
            print("t=%r all blocks: only in A: %s only in B: %s"
                  % (dtime, fmt_ids(only_a), fmt_ids(only_b)))
            if only_a or only_b:
                ok = False
            for label, mp in (("A", map_a), ("B", map_b)):
                for iwhat in IWHAT_ORDER:
                    msgs = check_ranges("%s %s" % (label, BLOCK_NAME[iwhat]),
                                        mp[dtime][iwhat], args.nel, args.nlv)
                    for m in msgs:
                        print("t=%r%s" % (dtime, m))
                        ok = False
    if args.mode == "pos" and floor:
        ok = floor_report(beyond_at, worst, args) and ok
    if args.mode == "pos":
        print("ie: pairs at distance 0 with another ie (any output, any block): "
              "%d: %s" % (ie0_total, "FAIL" if ie0_total else "ok"))
        print("inserted block: pairs that differ (any output): %d: %s"
              % (exact_total, "FAIL" if exact_total else "ok"))
    if args.mode == "pos" and tt_floor:
        bad = len(tt_all) > args.max_tt_differ
        print("tt: particles whose tt differs (any output, any block): %d %s %d: %s"
              % (len(tt_all), ">" if bad else "<=", args.max_tt_differ,
                 "FAIL" if bad else "ok"))
        ok = ok and not bad
    print("LGR COMPARE: %s (%d output times in A, %d in B)"
          % ("PASS" if ok else "FAIL", len(times_a), len(times_b)))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("a", help="first .lgr.shy file (A)")
    ap.add_argument("b", nargs="?", help="second .lgr.shy file (B)")
    ap.add_argument("--mode", choices=("pos", "ids"))
    ap.add_argument("--summary", action="store_true",
                    help="print counts of the single file A and exit")
    ap.add_argument("--tol", type=float, default=0.0,
                    help="x/y tolerance for --mode pos (default 0); also compares type, tt, s, c exactly")
    ap.add_argument("--tol-hl", type=float, default=1e-4,
                    help="layer-depth (hl) tolerance for --mode pos (default 1e-4)")
    ap.add_argument("--max-beyond-last", type=int, default=None,
                    help="--mode pos: floor test, fail if more than N particles"
                         " are beyond --tol at the last output both files share")
    ap.add_argument("--max-largest", type=float, default=None,
                    help="--mode pos: floor test, fail if the largest distance at"
                         " any output exceeds D (or is NaN)")
    ap.add_argument("--max-tt-differ", type=int, default=None,
                    help="--mode pos: a differing time tt is no failure by itself;"
                         " fail if more than N particles have a different tt")
    ap.add_argument("--same-counts", action="store_true",
                    help="--mode ids: also require equal counts per block")
    ap.add_argument("--nel", type=int, help="--mode ids: check 1 <= ie <= nel (all three blocks)")
    ap.add_argument("--nlv", type=int, help="--mode ids: check 1 <= lb <= nlv (all three blocks)")
    ap.add_argument("--dims", action="store_true",
                    help="print nkn, nel, nlv of the model header of file A and exit")
    args = ap.parse_args()
    if not (args.summary or args.dims) and (args.b is None or args.mode is None):
        ap.error("B and --mode are required unless --summary or --dims is given")
    if (args.max_beyond_last is not None or args.max_largest is not None) \
            and args.mode != "pos":
        ap.error("--max-beyond-last and --max-largest need --mode pos")
    if args.max_tt_differ is not None and args.mode != "pos":
        ap.error("--max-tt-differ needs --mode pos")
    if args.max_tt_differ is not None and args.max_tt_differ < 0:
        ap.error("--max-tt-differ must be >= 0")
    if args.max_beyond_last is not None and args.max_beyond_last < 0:
        ap.error("--max-beyond-last must be >= 0")
    if args.max_largest is not None and not args.max_largest >= 0:
        ap.error("--max-largest must be >= 0")
    try:
        if args.dims:
            return dims(args.a)
        if args.summary:
            return summary(args.a)
        return run(args)
    except (FormatError, OSError) as exc:
        print("cannot read file: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
