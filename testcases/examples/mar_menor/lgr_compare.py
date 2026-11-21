#!/usr/bin/env python3
"""Compare two SHYFEM Lagrangian particle files (NAME.lgr.shy) by particle id.

usage: lgr_compare.py A.lgr.shy B.lgr.shy --mode {pos|ids} [--tol FLOAT]
                      [--same-counts] [--nel N --nlv N]
       lgr_compare.py FILE.lgr.shy --summary

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
import struct
import sys

IWHAT_ORDER = (0, -1, 1)
BLOCK_NAME = {0: "active", -1: "inserted", 1: "exited"}
Z_TOL = 1e-5
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
                pid, _typ, _tt, _s, ie = REC1.unpack_from(data, recs[i][0])
                x, y, z, lb, _hl = REC2.unpack_from(data, recs[i + 1][0])
                if recs[i][1] != REC1.size or recs[i + 1][1] != REC2.size or \
                        recs[i + 2][1] != 4 * ncust:
                    raise FormatError("%s: bad particle record sizes at record %d"
                                      % (path, i))
                if pid in parts:
                    dups.append((BLOCK_NAME[iwhat], pid))
                parts[pid] = {"x": x, "y": y, "z": z, "lb": lb, "ie": ie}
                i += 3
            blocks[iwhat] = parts
        times.append((dtime0, blocks, dups))
    return ncust, times


def fmt_ids(ids):
    return ",".join(str(k) for k in sorted(ids)) if ids else "-"


def compare_pos(pa, pb, tol):
    """Return (ok, onlyA, onlyB, max_dx, max_dy, lb_ok, z_ok, detail lines)."""
    only_a = set(pa) - set(pb)
    only_b = set(pb) - set(pa)
    max_dx = max_dy = 0.0
    lb_ok = z_ok = True
    detail = []
    for pid in sorted(set(pa) & set(pb)):
        a, b = pa[pid], pb[pid]
        dx, dy, dz = abs(a["x"] - b["x"]), abs(a["y"] - b["y"]), abs(a["z"] - b["z"])
        max_dx, max_dy = max(max_dx, dx), max(max_dy, dy)
        bad = []
        if dx > tol or dy > tol:
            bad.append("position")
        if a["lb"] != b["lb"]:
            lb_ok = False
            bad.append("lb")
        if dz > Z_TOL:
            z_ok = False
            bad.append("z")
        if bad:
            detail.append("    id %d differs (%s): dx=%.4e dy=%.4e dz=%.4e lb=%d/%d"
                          % (pid, ",".join(bad), dx, dy, dz, a["lb"], b["lb"]))
    ok = not (only_a or only_b or detail)
    return ok, only_a, only_b, max_dx, max_dy, lb_ok, z_ok, detail


def check_ranges(label, parts, nel, nlv):
    """Messages for active particles outside 1<=ie<=nel or 1<=lb<=nlv."""
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
        for iwhat in IWHAT_ORDER:
            pa, pb = map_a[dtime][iwhat], map_b[dtime][iwhat]
            name = BLOCK_NAME[iwhat]
            ids_a |= set(pa)
            ids_b |= set(pb)
            head = "t=%r %-8s nA=%d nB=%d" % (dtime, name, len(pa), len(pb))
            if args.mode == "pos":
                good, oa, ob, mdx, mdy, lbok, zok, detail = compare_pos(pa, pb, args.tol)
                print("%s only in A: %s only in B: %s max|dx|=%.4e max|dy|=%.4e lb %s z %s"
                      % (head, fmt_ids(oa), fmt_ids(ob), mdx, mdy,
                         "match" if lbok else "DIFFER", "match" if zok else "DIFFER"))
                for line in detail:
                    print(line)
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
                msgs = check_ranges(label, mp[dtime][0], args.nel, args.nlv)
                for m in msgs:
                    print("t=%r%s" % (dtime, m))
                    ok = False
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
                    help="position tolerance for --mode pos (default 0)")
    ap.add_argument("--same-counts", action="store_true",
                    help="--mode ids: also require equal counts per block")
    ap.add_argument("--nel", type=int, help="--mode ids: check 1 <= ie <= nel")
    ap.add_argument("--nlv", type=int, help="--mode ids: check 1 <= lb <= nlv")
    args = ap.parse_args()
    if not args.summary and (args.b is None or args.mode is None):
        ap.error("B and --mode are required unless --summary is given")
    try:
        if args.summary:
            return summary(args.a)
        return run(args)
    except (FormatError, OSError) as exc:
        print("cannot read file: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
