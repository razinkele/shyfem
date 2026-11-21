#!/usr/bin/env python3
"""Compare the Lagrangian debug dumps (levdbg >= 3) of a serial and an MPI run.

usage: lgr_dbg_compare.py flux SERIAL_DIR MPI_DIR [--tol 1e-5]
       lgr_dbg_compare.py node SERIAL_DIR MPI_DIR [--tol 1e-5]
       lgr_dbg_compare.py part SERIAL_DIR MPI_DIR --tol FLOAT
                          [--by {id|nearest}] [--first-only]
                          [--ranks-empty-ok] [--ncross]

Each directory holds the files lgrdbg.KIND.NN.txt of one run (NN = rank),
written by lgr_mpi_debug_dump (src/shyfem/lagrange_mpi.f90).  Every file
starts with the line "# rank R of N".  In each directory all files must agree
on N, R must equal NN, and every kind of file present must exist for exactly
the ranks 0 .. N-1 (otherwise exit 2: a missing rank, an extra rank, or files
left from another run).  SERIAL_DIR must have N = 1.

flux  compares lgrdbg.flux (flux3d of layer 1 and flux2d) and, if present,
      lgrdbg.flux3 (flux3d of the bottom layer).  One row is one line of one
      rank's file, matched to the serial line with the same (element, node).
      Rows are classed by their own columns: "all-own nodes" (no vertex owned
      by another rank), "mixed, main owner" (this rank is the element's main
      owner), "mixed, owned elsewhere".  A row is off if |mpi - serial| >
      tol * scale, scale = max |serial| of that array (if the scale is 0, any
      non-zero difference is off; NaN is off).  Also checked: every MPI row
      exists in serial, and every serial row is covered exactly once by a
      main-owner row.  A flux file without data rows (run ended before 10 h)
      is an error.
node  compares lgrdbg.node (wlnv, mfluxv, difv, wxv, wyv) the same way, with
      the classes "own" and "ghost" node; every serial node must be own on
      exactly one rank.
part  compares lgrdbg.part (class time id x y z lb ie_global rank ncross)
      per output time.  Alive particles (classes P, M, G) are compared; D
      entries are only counted.  Per time it reports the counts, ids that
      occur twice in the MPI run, particles left unmatched, particles with a
      NaN position, the largest distance between matched particles (distance
      = max(|dx|, |dy|) as in lgr_compare.py; NaN propagates), the number of
      pairs beyond --tol, pairs whose layer lb differs, pairs whose z differs
      by more than 1e-5, and pairs whose crossing count differs (a pair with
      ncross = -1 on either side, "unknown", is counted apart and is never a
      mismatch).
      --by id       match by id; an id that occurs twice, or in one run only,
                    is a failure (ids repeat across ranks until stage 4).
      --by nearest  (default) one-to-one match: pairs are taken by increasing
                    distance (at equal distance: same layer, then closest z)
                    and every particle is used at most once.
      --ncross      a differing crossing count is a failure.
      --first-only  look at the first output time only.
      --ranks-empty-ok  mark MPI ranks whose part file has no entry at all
                    as expected.  Such a rank never fails the comparison (in
                    case A on 4 ranks rank 0 holds no particle in the whole
                    run, also when the tracks equal serial); without the flag
                    it is listed as a note.

Every mode exits 1 if the comparison fails (flux, node: any row off; part: a
count or time mismatch, an unmatched particle, a NaN position, a distance
above --tol, a differing layer or z, a duplicate id with --by id, a differing
crossing count with --ncross).

Exit status: 0 = runs agree, 1 = they differ, 2 = a dump cannot be read.
"""
import argparse
import bisect
import glob
import heapq
import math
import os
import re
import sys

FILE_RE = re.compile(r"^lgrdbg\.([a-z0-9]+)\.(\d+)\.txt$")
HEADER_RE = re.compile(r"^# rank (\d+) of (\d+)\s*$")
FLUX_CLASSES = ("all-own nodes", "mixed, main owner", "mixed, owned elsewhere")
NODE_ARRAYS = ("wlnv", "mfluxv", "difv", "wxv", "wyv")
NODE_CLASSES = ("own", "ghost")
ALIVE = ("P", "M", "G")
Z_TOL = 1e-5
K_NEAREST = 8           # candidate partners per particle in a nearest round
FULL_EDGES = 250000     # below this many pairs, use every pair


class DumpError(Exception):
    pass


# ---------------------------------------------------------------- reading


def read_header(path):
    """(rank, nprocs) from the first line '# rank R of N'."""
    try:
        with open(path) as f:
            first = f.readline()
    except OSError as e:
        raise DumpError("%s: %s" % (path, e))
    m = HEADER_RE.match(first)
    if not m:
        raise DumpError("%s: first line is not '# rank R of N' (old dump?)"
                        % path)
    return int(m.group(1)), int(m.group(2))


def dump_dir(dirname, serial):
    """Check all lgrdbg files of one run; return {kind: {rank: path}}."""
    if not os.path.isdir(dirname):
        raise DumpError("%s: not a directory" % dirname)
    kinds = {}
    nprocs = {}
    for path in sorted(glob.glob(os.path.join(dirname, "lgrdbg.*.txt"))):
        m = FILE_RE.match(os.path.basename(path))
        if not m:
            continue
        kind, nn = m.group(1), int(m.group(2))
        rank, n = read_header(path)
        if rank != nn:
            raise DumpError("%s: header says rank %d" % (path, rank))
        nprocs.setdefault(n, []).append(os.path.basename(path))
        kinds.setdefault(kind, {})[nn] = path
    if not kinds:
        raise DumpError("%s: no lgrdbg.KIND.NN.txt files" % dirname)
    if len(nprocs) > 1:
        raise DumpError("%s: files disagree on the number of processes: %s"
                        % (dirname, ", ".join("%d in %s" % (n, f[0])
                                              for n, f in sorted(nprocs.items()))))
    (n,) = nprocs
    if serial and n != 1:
        raise DumpError("%s: serial run must have 1 process, files say %d"
                        % (dirname, n))
    for kind, files in sorted(kinds.items()):
        want = set(range(n))
        have = set(files)
        if have != want:
            raise DumpError("%s: lgrdbg.%s for %d processes: missing ranks %s,"
                            " extra ranks %s" % (dirname, kind, n,
                                                 sorted(want - have),
                                                 sorted(have - want)))
    return kinds


def kind_files(kinds, dirname, kind):
    if kind not in kinds:
        raise DumpError("%s: no lgrdbg.%s.NN.txt files" % (dirname, kind))
    return kinds[kind]


def read_lines(path, nfields):
    """Yield (line number, fields) for every data line ('#' lines skipped)."""
    try:
        with open(path) as f:
            for n, line in enumerate(f, 1):
                if line.startswith("#"):
                    continue
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
    if not rows:
        raise DumpError("%s: no data rows (did the run reach 10 h?)" % path)
    return rows


def read_node(path, rank):
    """Rows (node_global, owner, (wlnv, mfluxv, difv, wxv, wyv))."""
    rows = []
    for n, f in read_lines(path, 8):
        check_rank(path, n, rank, f[1])
        vals = tuple(to_num(path, n, float, v) for v in f[3:8])
        rows.append((to_num(path, n, int, f[0]), to_num(path, n, int, f[2]), vals))
    if not rows:
        raise DumpError("%s: no data rows (did the run reach 10 h?)" % path)
    return rows


# part entry: (class, id, x, y, z, lb, ie_global, ncross)
CLS, ID, X, Y, Z, LB, IEG, NCROSS = range(8)


def read_part(path, rank):
    """{time: [entry]} of one rank."""
    out = {}
    for n, f in read_lines(path, 10):
        if f[0] not in ("P", "M", "G", "D"):
            raise DumpError("%s:%d: unknown class %r" % (path, n, f[0]))
        check_rank(path, n, rank, f[8])
        t = round(to_num(path, n, float, f[1]), 1)
        entry = (f[0], to_num(path, n, int, f[2]), to_num(path, n, float, f[3]),
                 to_num(path, n, float, f[4]), to_num(path, n, float, f[5]),
                 to_num(path, n, int, f[6]), to_num(path, n, int, f[7]),
                 to_num(path, n, int, f[9]))
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


def compare_flux_kind(sfile, mfiles, label3, tol):
    """Compare one flux file kind; return number of failures."""
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
                if is_off(d, tol * scales[j]):
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
    skinds = dump_dir(args.serial_dir, True)
    mkinds = dump_dir(args.mpi_dir, False)
    mfiles = kind_files(mkinds, args.mpi_dir, "flux")
    print("flux: serial %s, mpi %s, ranks %d"
          % (args.serial_dir, args.mpi_dir, len(mfiles)))
    nfail = compare_flux_kind(kind_files(skinds, args.serial_dir, "flux")[0],
                              mfiles, "flux3d (layer 1)", args.tol)
    has3 = ("flux3" in skinds, "flux3" in mkinds)
    if has3 == (True, True):
        nfail += compare_flux_kind(skinds["flux3"][0], mkinds["flux3"],
                                   "flux3d (bottom layer)", args.tol)
    elif has3 == (False, False):
        print("flux3: no files (2D run)")
    else:
        raise DumpError("lgrdbg.flux3 files in only one of the two runs")
    return nfail


# ---------------------------------------------------------------- node


def cmd_node(args):
    sfile = kind_files(dump_dir(args.serial_dir, True), args.serial_dir,
                       "node")[0]
    mfiles = kind_files(dump_dir(args.mpi_dir, False), args.mpi_dir, "node")
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


def distance(a, b):
    """max(|dx|, |dy|); NaN if either position has a NaN."""
    dx = abs(a[X] - b[X])
    dy = abs(a[Y] - b[Y])
    if math.isnan(dx) or math.isnan(dy):
        return math.nan
    return max(dx, dy)


def finite(e):
    return math.isfinite(e[X]) and math.isfinite(e[Y])


def tie_break(a, b):
    """(layer differs, |dz|) for equal distances: same layer and closest z
    first (several particles can share a position in different layers)."""
    dz = abs(a[Z] - b[Z])
    return (0 if a[LB] == b[LB] else 1, dz if dz == dz else math.inf)


def candidate_edges(ser, mpi, free_s, free_m, k):
    """(distance, layer differs, |dz|, i, j) to the k nearest free MPI
    particles of every free serial particle (all positions finite)."""
    ms = sorted(free_m, key=lambda j: mpi[j][X])
    xs = [mpi[j][X] for j in ms]
    n = len(ms)
    edges = []
    for i in free_s:
        x, y = ser[i][X], ser[i][Y]
        heap = []                # (-distance, -tie..., -j): k nearest so far
        hi = bisect.bisect_left(xs, x)
        lo = hi - 1
        while lo >= 0 or hi < n:
            for side in (0, 1):
                p = hi if side == 0 else lo
                if p < 0 or p >= n:
                    continue
                bound = -heap[0][0] if len(heap) == k else math.inf
                dx = abs(xs[p] - x)
                if dx > bound:
                    if side == 0:
                        hi = n
                    else:
                        lo = -1
                    continue
                d = max(dx, abs(mpi[ms[p]][Y] - y))
                lbd, dz = tie_break(ser[i], mpi[ms[p]])
                item = (-d, -lbd, -dz, -ms[p])
                if len(heap) < k:
                    heapq.heappush(heap, item)
                elif item > heap[0]:
                    heapq.heapreplace(heap, item)
                if side == 0:
                    hi += 1
                else:
                    lo -= 1
        edges.extend((-nd, -nl, -nz, i, -nj) for nd, nl, nz, nj in heap)
    return edges


def match_nearest(ser, mpi):
    """One-to-one match by increasing distance (greedy).  Returns the pairs
    [(serial, mpi, distance)] and the numbers of unmatched entries of each
    run.  Entries must have finite positions."""
    free_s = list(range(len(ser)))
    free_m = list(range(len(mpi)))
    pairs = []
    while free_s and free_m:
        full = len(free_s) * len(free_m) <= FULL_EDGES
        if full:
            edges = [(distance(ser[i], mpi[j]),) + tie_break(ser[i], mpi[j])
                     + (i, j) for i in free_s for j in free_m]
        else:
            edges = candidate_edges(ser, mpi, free_s, free_m, K_NEAREST)
        edges.sort()
        used_s, used_m = set(), set()
        for d, lbd, dz, i, j in edges:
            if i in used_s or j in used_m:
                continue
            used_s.add(i)
            used_m.add(j)
            pairs.append((ser[i], mpi[j], d))
        free_s = [i for i in free_s if i not in used_s]
        free_m = [j for j in free_m if j not in used_m]
        if full:
            break
    return pairs, len(free_s), len(free_m)


def match_id(ser, mpi):
    """Pairs by id (first entry of each id); returns pairs and the numbers
    of entries of each run left without a partner."""
    mid = {}
    for e in mpi:
        mid.setdefault(e[ID], e)
    pairs = []
    seen = set()
    for e in ser:
        if e[ID] in seen:
            continue
        seen.add(e[ID])
        if e[ID] in mid:
            m = mid[e[ID]]
            pairs.append((e, m, distance(e, m)))
    return pairs, len(ser) - len(pairs), len(mpi) - len(pairs)


def dup_ids(entries):
    seen, dups = set(), set()
    for e in entries:
        if e[ID] in seen:
            dups.add(e[ID])
        seen.add(e[ID])
    return len(dups)


def load_part(kinds, dirname):
    files = kind_files(kinds, dirname, "part")
    by_time = {}
    nentries = {}
    for rank in sorted(files):
        data = read_part(files[rank], rank)
        nentries[rank] = sum(len(v) for v in data.values())
        for t, entries in data.items():
            by_time.setdefault(t, []).extend(entries)
    return by_time, nentries


def nan_max(values):
    """Largest value; NaN if any value is NaN; 0 for no values."""
    out = 0.0
    for v in values:
        if math.isnan(v):
            return math.nan
        out = max(out, v)
    return out


def cmd_part(args):
    ser, _ = load_part(dump_dir(args.serial_dir, True), args.serial_dir)
    mpi, mentries = load_part(dump_dir(args.mpi_dir, False), args.mpi_dir)
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

    print("  %9s %5s %5s %5s %5s %5s %5s %3s %10s %4s %4s %4s %5s %5s"
          % ("time", "n_ser", "n_mpi", "D_ser", "D_mpi", "dupid", "unmat",
             "nan", "max dist", ">tol", "lb!=", "z!=", "ncr!=", "ncr-1"))
    worst = (0.0, None)
    tot = dict.fromkeys(("unmat", "nan", "over", "lb", "z", "ncr", "unk"), 0)
    for t in times:
        sa = [e for e in ser.get(t, []) if e[CLS] in ALIVE]
        ma = [e for e in mpi.get(t, []) if e[CLS] in ALIVE]
        nd_s = len(ser.get(t, [])) - len(sa)
        nd_m = len(mpi.get(t, [])) - len(ma)
        ndup = dup_ids(ma)
        ndup_s = dup_ids(sa)
        nnan = sum(1 for e in sa + ma if not finite(e))
        if args.by == "id":
            pairs, un_s, un_m = match_id(sa, ma)
        else:
            pairs, un_s, un_m = match_nearest([e for e in sa if finite(e)],
                                              [e for e in ma if finite(e)])
        unmat = un_s + un_m
        dmax = nan_max(p[2] for p in pairs)
        nover = sum(1 for p in pairs if not p[2] <= args.tol)
        nlb = sum(1 for p in pairs if p[0][LB] != p[1][LB])
        nz = sum(1 for p in pairs if not abs(p[0][Z] - p[1][Z]) <= Z_TOL)
        nunk = sum(1 for p in pairs if p[0][NCROSS] == -1 or p[1][NCROSS] == -1)
        nx = sum(1 for p in pairs if p[0][NCROSS] != -1 and p[1][NCROSS] != -1
                 and p[0][NCROSS] != p[1][NCROSS])
        note = ""
        bad = unmat + nnan + nover + nlb + nz
        if len(sa) != len(ma):
            bad += 1
            note += " COUNT"
        if ndup_s:
            bad += ndup_s
            note += " serial dup ids %d" % ndup_s
        if args.by == "id":
            bad += ndup
        if args.ncross:
            bad += nx
        nfail += bad
        for key, v in (("unmat", unmat), ("nan", nnan), ("over", nover),
                       ("lb", nlb), ("z", nz), ("ncr", nx), ("unk", nunk)):
            tot[key] += v
        if not math.isnan(worst[0]) and (math.isnan(dmax) or dmax > worst[0]):
            worst = (dmax, t)
        print("  %9.1f %5d %5d %5d %5d %5d %5d %3d %10.3e %4d %4d %4d %5d %5d%s"
              % (t, len(sa), len(ma), nd_s, nd_m, ndup, unmat, nnan, dmax,
                 nover, nlb, nz, nx, nunk, note))
    if worst[1] is not None:
        print("  largest distance %.4e at time %.1f" % worst)
    print("  totals over %d outputs: unmatched %d, nan %d, beyond tol %d,"
          " layer differs %d, z differs %d, ncross differs %d%s,"
          " ncross unknown (-1) %d"
          % (len(times), tot["unmat"], tot["nan"], tot["over"], tot["lb"],
             tot["z"], tot["ncr"], "" if args.ncross else " (not gated)",
             tot["unk"]))
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
