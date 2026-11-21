#!/usr/bin/env python3
"""Compare the Lagrangian debug dumps (levdbg >= 3) of a serial and an MPI run.

usage: lgr_dbg_compare.py flux SERIAL_DIR MPI_DIR [--tol 1e-5]
       lgr_dbg_compare.py node SERIAL_DIR MPI_DIR [--tol 1e-5]
       lgr_dbg_compare.py part SERIAL_DIR MPI_DIR --tol FLOAT
                          [--by {id|nearest}] [--first-only]
                          [--ranks-empty-ok] [--ncross]

Each directory holds the files lgrdbg.KIND.NN.txt of one run (NN = rank),
written by lgr_mpi_debug_dump (src/shyfem/lagrange_mpi.f90).  SERIAL_DIR must
hold rank 00 only; MPI_DIR must hold ranks 00 .. N-1 without a gap.

flux  compares lgrdbg.flux (flux3d of layer 1 and flux2d) and, if present,
      lgrdbg.flux3 (flux3d of the bottom layer).  One row is one line of one
      rank's file, matched to the serial line with the same (element, node).
      Rows are classed by their own columns: "all-own nodes" (no vertex owned
      by another rank), "mixed, main owner" (this rank is the element's main
      owner), "mixed, owned elsewhere".  A row is off if |mpi - serial| >
      tol * scale, scale = max |serial| of that array (if the scale is 0, any
      non-zero difference is off).  Also checked: every MPI row exists in
      serial, and every serial row is covered exactly once by a main-owner row.
node  compares lgrdbg.node (wlnv, mfluxv, difv, wxv, wyv) the same way, with
      the classes "own" and "ghost" node; every serial node must be own on
      exactly one rank.
part  compares lgrdbg.part per output time: the number of particles alive
      (classes P, M, G; D entries are listed, not compared), the times, ids
      that occur twice, and the largest distance between matched particles,
      distance = max(|dx|, |dy|) as in lgr_compare.py.
      --by id       match by id; an id that occurs twice, or in one run only,
                    is a failure (ids repeat across ranks until stage 4).
      --by nearest  (default) largest nearest-neighbour distance, taken in
                    both directions (serial -> MPI and MPI -> serial).
      --ncross      also compare the crossing count of matched particles (by
                    nearest: the MPI particle nearest to each serial one).
      --first-only  look at the first output time only.
      --ranks-empty-ok  mark MPI ranks whose part file has no entry at all
                    as expected.  Such a rank never fails the comparison (in
                    case A on 4 ranks rank 0 holds no particle in the whole
                    run, also when the tracks equal serial); without the flag
                    it is listed as a note.  A missing part file is an error.

Every mode exits 1 if the comparison fails (flux, node: any row off; part: a
count or time mismatch, a distance above --tol, a duplicate id with --by id,
a differing crossing count with --ncross).

Exit status: 0 = runs agree, 1 = they differ, 2 = a dump cannot be read.
"""
import argparse
import bisect
import glob
import math
import os
import re
import sys

FILE_RE = re.compile(r"^lgrdbg\.([a-z0-9]+)\.(\d+)\.txt$")
FLUX_CLASSES = ("all-own nodes", "mixed, main owner", "mixed, owned elsewhere")
NODE_ARRAYS = ("wlnv", "mfluxv", "difv", "wxv", "wyv")
NODE_CLASSES = ("own", "ghost")
ALIVE = ("P", "M", "G")


class DumpError(Exception):
    pass


# ---------------------------------------------------------------- reading


def dump_files(dirname, kind):
    """Return {rank: path} of the lgrdbg.KIND.NN.txt files in dirname."""
    if not os.path.isdir(dirname):
        raise DumpError("%s: not a directory" % dirname)
    files = {}
    for path in glob.glob(os.path.join(dirname, "lgrdbg.%s.*.txt" % kind)):
        m = FILE_RE.match(os.path.basename(path))
        if m and m.group(1) == kind:
            files[int(m.group(2))] = path
    return files


def rank_files(dirname, kind, serial, required=True):
    """Dump files of one run, checked: serial = rank 0 only, MPI = 0..N-1."""
    files = dump_files(dirname, kind)
    if not files:
        if required:
            raise DumpError("%s: no lgrdbg.%s.NN.txt files" % (dirname, kind))
        return files
    ranks = sorted(files)
    if serial and ranks != [0]:
        raise DumpError("%s: serial run must hold rank 00 only, found ranks %s"
                        % (dirname, ranks))
    if ranks != list(range(len(ranks))):
        raise DumpError("%s: lgrdbg.%s files for ranks %s: a rank is missing"
                        % (dirname, kind, ranks))
    return files


def read_lines(path, nfields):
    """Yield (line number, fields) for every non-empty line."""
    try:
        with open(path) as f:
            for n, line in enumerate(f, 1):
                fields = line.split()
                if not fields:
                    continue
                if len(fields) != nfields:
                    raise DumpError("%s:%d: %d fields, expected %d"
                                    % (path, n, len(fields), nfields))
                yield n, fields
    except OSError as e:
        raise DumpError("%s: %s" % (path, e))


def to_num(path, n, conv, text):
    try:
        return conv(text)
    except ValueError:
        raise DumpError("%s:%d: cannot read %r" % (path, n, text))


def check_rank(path, n, rank, field):
    if to_num(path, n, int, field) != rank:
        raise DumpError("%s:%d: rank column %s, file is rank %d"
                        % (path, n, field, rank))


def read_flux(path, rank):
    """Rows (ie_global, node_global, main_owner, n_ghost, f3, f2)."""
    rows = []
    for n, f in read_lines(path, 7):
        check_rank(path, n, rank, f[2])
        rows.append((to_num(path, n, int, f[0]), to_num(path, n, int, f[1]),
                     to_num(path, n, int, f[3]), to_num(path, n, int, f[4]),
                     to_num(path, n, float, f[5]), to_num(path, n, float, f[6])))
    return rows


def read_node(path, rank):
    """Rows (node_global, owner, (wlnv, mfluxv, difv, wxv, wyv))."""
    rows = []
    for n, f in read_lines(path, 8):
        check_rank(path, n, rank, f[1])
        vals = tuple(to_num(path, n, float, v) for v in f[3:8])
        rows.append((to_num(path, n, int, f[0]), to_num(path, n, int, f[2]), vals))
    return rows


def read_part(path, rank):
    """{time: [(class, id, x, y, z, ie_global, ncross)]} of one rank."""
    out = {}
    for n, f in read_lines(path, 9):
        if f[0] not in ("P", "M", "G", "D"):
            raise DumpError("%s:%d: unknown class %r" % (path, n, f[0]))
        check_rank(path, n, rank, f[7])
        t = round(to_num(path, n, float, f[1]), 1)
        entry = (f[0], to_num(path, n, int, f[2]), to_num(path, n, float, f[3]),
                 to_num(path, n, float, f[4]), to_num(path, n, float, f[5]),
                 to_num(path, n, int, f[6]), to_num(path, n, int, f[8]))
        out.setdefault(t, []).append(entry)
    return out


# ---------------------------------------------------------------- helpers


def is_off(d, limit):
    """True if difference d exceeds limit or is NaN."""
    return not abs(d) <= limit


def fmt_rel(d, scale):
    if math.isnan(d):
        return "nan"
    if scale > 0:
        return "%.1e" % (d / scale)
    return "%.1e abs" % d


def class_table(title, scale, tol, classes, stats):
    """Print one table; stats[class] = [rows, off, worst]; return total off."""
    if scale > 0:
        print("%s: scale %.4e (max |serial|), limit %g of scale"
              % (title, scale, tol))
    else:
        print("%s: all zero in serial, any non-zero difference is off" % title)
    print("  %-26s %8s %8s %13s" % ("class", "rows", "off", "worst/scale"))
    total = 0
    for c in classes:
        rows, off, worst = stats[c]
        total += off
        print("  %-26s %8d %8d %13s" % (c, rows, off,
                                         fmt_rel(worst, scale) if rows else "-"))
    return total


def worse(a, b):
    """Larger of two differences, NaN counts as the largest."""
    if math.isnan(a) or math.isnan(b):
        return float("nan")
    return max(a, b)


# ---------------------------------------------------------------- flux


def compare_flux_kind(serial_dir, mpi_dir, kind, label3, tol):
    """Compare one flux file kind; return number of failures."""
    sfile = rank_files(serial_dir, kind, True)[0]
    serial = {}
    for ieg, nodeg, owner, ng, f3, f2 in read_flux(sfile, 0):
        key = (ieg, nodeg)
        if key in serial:
            raise DumpError("%s: element %d node %d twice" % (sfile, ieg, nodeg))
        serial[key] = (f3, f2)
    scales = [max((abs(v[j]) for v in serial.values()), default=0.0)
              for j in (0, 1)]

    stats = [{c: [0, 0, 0.0] for c in FLUX_CLASSES} for _ in (0, 1)]
    unknown = 0
    bad_class = 0
    main_count = dict.fromkeys(serial, 0)
    mfiles = rank_files(mpi_dir, kind, False)
    for rank in sorted(mfiles):
        for ieg, nodeg, owner, ng, f3, f2 in read_flux(mfiles[rank], rank):
            key = (ieg, nodeg)
            if key not in serial:
                unknown += 1
                continue
            if ng == 0:
                cls = FLUX_CLASSES[0]
                if owner != rank:
                    bad_class += 1
            elif owner == rank:
                cls = FLUX_CLASSES[1]
            else:
                cls = FLUX_CLASSES[2]
            if owner == rank:
                main_count[key] += 1
            for j, v in enumerate((f3, f2)):
                d = abs(v - serial[key][j])
                st = stats[j][cls]
                st[0] += 1
                limit = tol * scales[j]
                if is_off(d, limit):
                    st[1] += 1
                st[2] = worse(st[2], d)

    nfail = 0
    titles = (label3, "flux2d")
    for j in (0, 1):
        nfail += class_table(titles[j], scales[j], tol, FLUX_CLASSES, stats[j])
    not_main = sum(1 for c in main_count.values() if c == 0)
    many_main = sum(1 for c in main_count.values() if c > 1)
    print("  coverage: %d serial rows (%d elements); MPI rows not in serial %d;"
          " serial rows with no main-owner row %d, with more than one %d;"
          " own-node rows with another main owner %d"
          % (len(serial), len({k[0] for k in serial}), unknown, not_main,
             many_main, bad_class))
    nfail += unknown + not_main + many_main + bad_class
    return nfail


def cmd_flux(args):
    print("flux: serial %s, mpi %s, ranks %d"
          % (args.serial_dir, args.mpi_dir,
             len(rank_files(args.mpi_dir, "flux", False))))
    nfail = compare_flux_kind(args.serial_dir, args.mpi_dir, "flux",
                              "flux3d (layer 1)", args.tol)
    has3 = (bool(dump_files(args.serial_dir, "flux3")),
            bool(dump_files(args.mpi_dir, "flux3")))
    if has3 == (True, True):
        nfail += compare_flux_kind(args.serial_dir, args.mpi_dir, "flux3",
                                   "flux3d (bottom layer)", args.tol)
    elif has3 == (False, False):
        print("flux3: no files (2D run)")
    else:
        raise DumpError("lgrdbg.flux3 files in only one of the two runs")
    return nfail


# ---------------------------------------------------------------- node


def cmd_node(args):
    sfile = rank_files(args.serial_dir, "node", True)[0]
    serial = {}
    for nodeg, owner, vals in read_node(sfile, 0):
        if nodeg in serial:
            raise DumpError("%s: node %d twice" % (sfile, nodeg))
        serial[nodeg] = vals
    na = len(NODE_ARRAYS)
    scales = [max((abs(v[j]) for v in serial.values()), default=0.0)
              for j in range(na)]
    stats = [{c: [0, 0, 0.0] for c in NODE_CLASSES} for _ in range(na)]
    unknown = 0
    own_count = dict.fromkeys(serial, 0)
    mfiles = rank_files(args.mpi_dir, "node", False)
    print("node: serial %s, mpi %s, ranks %d"
          % (args.serial_dir, args.mpi_dir, len(mfiles)))
    for rank in sorted(mfiles):
        for nodeg, owner, vals in read_node(mfiles[rank], rank):
            if nodeg not in serial:
                unknown += 1
                continue
            cls = NODE_CLASSES[0] if owner == rank else NODE_CLASSES[1]
            if owner == rank:
                own_count[nodeg] += 1
            for j in range(na):
                d = abs(vals[j] - serial[nodeg][j])
                st = stats[j][cls]
                st[0] += 1
                if is_off(d, args.tol * scales[j]):
                    st[1] += 1
                st[2] = worse(st[2], d)
    nfail = 0
    for j in range(na):
        nfail += class_table("%s (layer 1)" % NODE_ARRAYS[j]
                             if j < 3 else NODE_ARRAYS[j],
                             scales[j], args.tol, NODE_CLASSES, stats[j])
    not_own = sum(1 for c in own_count.values() if c == 0)
    many_own = sum(1 for c in own_count.values() if c > 1)
    print("  coverage: %d serial nodes; MPI nodes not in serial %d;"
          " nodes own on no rank %d, on more than one rank %d"
          % (len(serial), unknown, not_own, many_own))
    return nfail + unknown + not_own + many_own


# ---------------------------------------------------------------- part


def nearest(sorted_pts, xs, x, y):
    """(distance, index) of the point of sorted_pts nearest to (x, y), with
    distance = max(|dx|, |dy|); sorted_pts sorted by x, xs their x values."""
    best, ibest = math.inf, -1
    n = len(sorted_pts)
    i = bisect.bisect_left(xs, x)
    lo, hi = i - 1, i
    while lo >= 0 or hi < n:
        if hi < n:
            dx = abs(xs[hi] - x)
            if dx > best:
                hi = n
            else:
                d = max(dx, abs(sorted_pts[hi][3] - y))
                if d < best:
                    best, ibest = d, hi
                hi += 1
        if lo >= 0:
            dx = abs(xs[lo] - x)
            if dx > best:
                lo = -1
            else:
                d = max(dx, abs(sorted_pts[lo][3] - y))
                if d < best:
                    best, ibest = d, lo
                lo -= 1
    return best, ibest


def match_nearest(ser, mpi):
    """Pairs (serial, mpi, distance) of each serial particle with its nearest
    MPI particle, and the largest nearest distance MPI -> serial."""
    pairs = []
    if not ser or not mpi:
        return pairs, 0.0
    ms = sorted(mpi, key=lambda e: e[2])
    mxs = [e[2] for e in ms]
    for e in ser:
        d, i = nearest(ms, mxs, e[2], e[3])
        pairs.append((e, ms[i], d))
    ss = sorted(ser, key=lambda e: e[2])
    sxs = [e[2] for e in ss]
    back = 0.0
    for e in mpi:
        d, i = nearest(ss, sxs, e[2], e[3])
        back = max(back, d)
    return pairs, back


def match_id(ser, mpi):
    """Pairs (serial, mpi, distance) by id, and the ids in one run only."""
    sid = {}
    for e in ser:
        sid.setdefault(e[1], e)
    mid = {}
    for e in mpi:
        mid.setdefault(e[1], e)
    pairs = []
    for i, e in sid.items():
        if i in mid:
            m = mid[i]
            pairs.append((e, m, max(abs(e[2] - m[2]), abs(e[3] - m[3]))))
    only = len(set(sid) ^ set(mid))
    return pairs, only


def dup_ids(entries):
    seen, dups = set(), set()
    for e in entries:
        if e[1] in seen:
            dups.add(e[1])
        seen.add(e[1])
    return len(dups)


def load_part(dirname, serial):
    files = rank_files(dirname, "part", serial)
    by_time = {}
    nentries = {}
    for rank in sorted(files):
        data = read_part(files[rank], rank)
        nentries[rank] = sum(len(v) for v in data.values())
        for t, entries in data.items():
            by_time.setdefault(t, []).extend(entries)
    return by_time, nentries


def cmd_part(args):
    ser, _ = load_part(args.serial_dir, True)
    mpi, mentries = load_part(args.mpi_dir, False)
    print("part: serial %s, mpi %s, ranks %d, match by %s, tol %g"
          % (args.serial_dir, args.mpi_dir, len(mentries), args.by, args.tol))
    nfail = 0

    empty = [r for r, n in sorted(mentries.items()) if n == 0]
    if empty:
        print("  %s ranks without any entry in the whole run: %s"
              % ("expected:" if args.ranks_empty_ok else "note:", empty))

    times = sorted(set(ser) | set(mpi))
    if not times:
        raise DumpError("no particle entries in either run")
    if args.first_only:
        times = times[:1]
    only_s = [t for t in times if t not in mpi]
    only_m = [t for t in times if t not in ser]
    if only_s or only_m:
        print("  FAIL times only in serial: %d, only in mpi: %d"
              % (len(only_s), len(only_m)))
        nfail += len(only_s) + len(only_m)

    print("  %10s %6s %6s %5s %5s %5s %12s %5s %6s"
          % ("time", "n_ser", "n_mpi", "D_ser", "D_mpi", "dupid", "max dist",
             ">tol", "ncross"))
    worst = (0.0, None)
    for t in times:
        sa = [e for e in ser.get(t, []) if e[0] in ALIVE]
        ma = [e for e in mpi.get(t, []) if e[0] in ALIVE]
        nd_s = len(ser.get(t, [])) - len(sa)
        nd_m = len(mpi.get(t, [])) - len(ma)
        ndup = dup_ids(ma)
        ndup_s = dup_ids(sa)
        if args.by == "id":
            pairs, only = match_id(sa, ma)
            dists = [p[2] for p in pairs]
            nfail += only + ndup
            note = " ids in one run only %d" % only if only else ""
        else:
            pairs, back = match_nearest(sa, ma)
            dists = [p[2] for p in pairs] + ([back] if ma and sa else [])
            note = ""
        dmax = max(dists, default=0.0)
        nover = sum(1 for p in pairs if not p[2] <= args.tol)
        if args.by == "nearest" and not back <= args.tol:
            nover = max(nover, 1)
        nx = sum(1 for p in pairs if p[0][6] != p[1][6])
        if len(sa) != len(ma):
            nfail += 1
            note += " COUNT"
        if ndup_s:
            nfail += ndup_s
            note += " serial dup ids %d" % ndup_s
        if not dmax <= args.tol:
            nfail += 1
        if args.ncross:
            nfail += nx
        if dmax > worst[0] or math.isnan(dmax):
            worst = (dmax, t)
        print("  %10.1f %6d %6d %5d %5d %5d %12.4e %5d %6s%s"
              % (t, len(sa), len(ma), nd_s, nd_m, ndup, dmax, nover,
                 nx if args.ncross else "-", note))
    if worst[1] is not None:
        print("  largest distance %.4e at time %.1f" % worst)
    return nfail


# ---------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Compare the Lagrangian debug dumps of a serial and an "
                    "MPI run (see the module docstring for details).")
    sub = ap.add_subparsers(dest="mode", required=True)
    for name, func in (("flux", cmd_flux), ("node", cmd_node)):
        p = sub.add_parser(name)
        p.add_argument("serial_dir")
        p.add_argument("mpi_dir")
        p.add_argument("--tol", type=float, default=1e-5,
                       help="limit as a fraction of max |serial| (default 1e-5)")
        p.set_defaults(func=func)
    p = sub.add_parser("part")
    p.add_argument("serial_dir")
    p.add_argument("mpi_dir")
    p.add_argument("--tol", type=float, required=True,
                   help="largest allowed distance max(|dx|,|dy|)")
    p.add_argument("--by", choices=("id", "nearest"), default="nearest")
    p.add_argument("--first-only", action="store_true",
                   help="compare the first output time only")
    p.add_argument("--ranks-empty-ok", action="store_true",
                   help="ranks without any entry are expected (never a failure)")
    p.add_argument("--ncross", action="store_true",
                   help="fail if a matched particle's crossing count differs")
    p.set_defaults(func=cmd_part)
    args = ap.parse_args(argv)
    if not args.tol >= 0:
        ap.error("--tol must be >= 0")
    try:
        nfail = args.func(args)
    except DumpError as e:
        print("lgr_dbg_compare: %s" % e, file=sys.stderr)
        return 2
    print("lgr_dbg_compare %s: %s" % (args.mode, "PASS" if nfail == 0 else "FAIL"))
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
