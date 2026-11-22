#!/usr/bin/env python3
"""Compare the Lagrangian debug dumps (levdbg >= 3) of a serial and an MPI run.

usage: lgr_dbg_compare.py flux SERIAL_DIR MPI_DIR [--tol 1e-5]
       lgr_dbg_compare.py node SERIAL_DIR MPI_DIR [--tol 1e-5]
       lgr_dbg_compare.py part SERIAL_DIR MPI_DIR --tol FLOAT
                          [--by {id|nearest|key}] [--first-only]
                          [--ranks-empty-ok] [--ncross] [--elem] [--ids]
                          [--handover [--step LENGTH] [--jump-factor J]
                                      [--jump-floor F] [--quantile Q]
                                      [--min-changed N]]
                          [--max-beyond-last N] [--max-largest D]

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
part  compares lgrdbg.part (class time id x y z lb ie_global rank ncross
      [key_ie key_xi1 key_xi2 key_l key_z key_time])
      per time (every particle output, and the release blocks written right
      after a release).  Alive particles (classes P, M, G) are compared; D
      entries are only counted.  Per time it reports the counts, ids that
      occur twice in the MPI run, particles left unmatched, particles with a
      NaN position, the largest distance between matched particles (distance
      = max(|dx|, |dy|) as in lgr_compare.py; NaN propagates), the number of
      pairs beyond --tol, pairs whose layer lb differs, pairs whose z differs
      by more than 1e-5, pairs whose crossing count differs (a pair with
      ncross = -1 on either side, "unknown", is counted apart and is never a
      mismatch), and pairs whose global element ie_global differs.
      --by id       match by id; an id that occurs twice, or in one run only,
                    is a failure (since Task 4.2 a particle has the id of the
                    serial run on every number of processes).
      --by nearest  (default) one-to-one match: pairs are taken by increasing
                    distance (at equal distance: same layer, then with
                    --elem the same element, then closest z) and every
                    particle is used at most once.
      --by key      match by the particle's key, the last six columns of a
                    particle line (global release element, first two release
                    coordinates, release layer, release depth, release time;
                    equal if all six are equal as numbers).  The key is the
                    same in a serial and in an MPI run, and unique (several
                    particles can start at one position, in different
                    layers).  A key that occurs twice in one time block of one
                    run, or that has an alive entry in one run and none in the
                    other (absent, or class D = left the basin), is reported
                    and is a failure, as with --by id.  In an MPI run a
                    particle is on exactly one process at a time; all process
                    files of a time block are read together.  A dump with
                    only the ten old columns still serves every other mode;
                    with --by key it is an input error (exit 2).  With --by
                    key the table has a last column id!=: the pairs of the
                    block whose ids differ; the totals line gives their sum.
      --ids         (with --by key) a pair matched by key whose ids differ is
                    a failure (a particle keeps its id, the one it has in a
                    serial run).  Without --ids the count is printed and
                    marked "(not gated)".  --ids without --by key is a usage
                    error (exit 2).
      --ncross      a differing crossing count is a failure.  With --by key
                    only for a pair at distance exactly 0 (a particle that
                    moved differently can have crossed a different number of
                    elements); both counts are printed.
      --handover    (with --by key) the hand-over fidelity check.  For every
                    particle and every two consecutive time blocks, in which
                    the particle is in the domain (class P, M or G) in both
                    runs at both blocks: if its serial and MPI positions are
                    equal (distance exactly 0) at the first block, the pair
                    goes to one of two groups: "changed process" (its rank
                    column in the MPI run differs between the two blocks) or
                    "stayed" (the control group).  Per group the tool prints
                    the pairs, how many are still at distance 0 at the second
                    block, how many are within --step (a length in the
                    dump's unit: degrees for cases A, C, E, metres for B) and
                    how many are beyond it, and the largest distance.  A
                    particle that changes process and comes back between two
                    outputs cannot be seen in the dump: its pair counts as
                    "stayed".  Pairs of blocks where the particle is not in
                    the domain in both runs at both blocks are left out; the
                    number is printed.  The distance is the one of the part
                    table (max(|dx|, |dy|)).  The rule has two tests; the
                    mode fails if either fails:
                    jump test: a "changed process" pair whose distance is
                    greater than max(J x the largest distance of "stayed",
                    F x step) fails (--jump-factor J, default 2;
                    --jump-floor F, in steps, default 10).  A pair that jumps
                    beyond the noise the particles show without a hand-over
                    is a defect, whatever the counts.
                    count test: the number of "changed process" pairs beyond
                    the step fails if it is greater than the q-quantile of a
                    Poisson count whose mean is the rate of "stayed" (pairs
                    beyond the step / pairs; 0 for a group without pairs)
                    times the number of "changed process" pairs (--quantile
                    q, default 0.999).  The q-quantile is the smallest k with
                    P(X <= k) >= q (cumulative sum of the Poisson terms); it
                    is 0 for a mean of 0, so with a "stayed" group that has
                    no pair beyond the step any changed pair beyond it fails.
                    The rule line states both tests with their thresholds and
                    verdicts; below it every changed pair above the jump
                    threshold is listed (key, times, ranks, distance), after
                    the list of the changed pairs beyond the step (at most
                    100 of them).  A run without any
                    "changed process" pair prints "no changed-process pair:
                    the hand-over was not exercised" and still passes; with
                    --min-changed N (default 0) it fails if fewer than N such
                    pairs exist.  If no pair at distance 0 exists at all
                    (both groups empty) nothing was compared and the mode
                    fails.  Besides these and the rule, the structure fails
                    the run (times, counts, duplicate and unmatched keys, NaN
                    positions), and --ncross (distance 0 only) and --elem
                    gate as without --handover; distances above --tol, layers
                    and z are printed with "(not gated)".  --first-only
                    cannot be combined with --handover (exit 2).
      --elem        a differing global element is a failure.
      --first-only  look at the first time in the files only (the block
                    written right after the first release, before any
                    tracking, when the run releases particles).
      --ranks-empty-ok  mark MPI ranks whose part file has no entry at all
                    as expected.  Such a rank never fails the comparison (in
                    case A on 4 ranks rank 0 holds no particle in the whole
                    run, also when the tracks equal serial); without the flag
                    it is listed as a note.
      --max-beyond-last N, --max-largest D  (with --by key) the positions
                    are held against floors instead of the limit pair by
                    pair: a pair beyond --tol is then no failure by itself;
                    the run fails if the number of matched pairs beyond --tol
                    at the last output both runs share is greater than N
                    (--max-beyond-last), or if the largest distance at any
                    output is greater than D or NaN (--max-largest).  Either
                    option alone, or both; everything else (counts, times,
                    unmatched and duplicate keys, NaN positions, layer and z
                    differences, --ncross, --elem, --ids) gates as without
                    them.  A line "floor: ..." states each test with its
                    value, its limit and its verdict.  Without the two
                    options nothing changes.  check_lgr_mpi.sh mode floor
                    passes the floors measured on the serial reference.

Every mode exits 1 if the comparison fails (flux, node: any row off; part: a
count or time mismatch, an unmatched particle, a NaN position, a distance
above --tol (or, with --max-beyond-last / --max-largest, a floor exceeded), a
differing layer or z, a duplicate id with --by id, a differing crossing count
with --ncross, a differing element with --elem, a differing id with --ids).

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
    """Yield (line number, fields) for every data line ('#' lines skipped);
    nfields is a number or a tuple of allowed numbers."""
    allowed = nfields if isinstance(nfields, tuple) else (nfields,)
    try:
        with open(path) as f:
            for n, line in enumerate(f, 1):
                if line.startswith("#"):
                    continue
                fields = line.split()
                if not fields:
                    continue
                if len(fields) not in allowed:
                    raise DumpError("%s:%d: %d fields, expected %s"
                                    % (path, n, len(fields),
                                       " or ".join(str(a) for a in allowed)))
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


# part entry: (class, id, x, y, z, lb, ie_global, ncross, key, rank); key is
# (ie, xi1, xi2, l, z, time) of the six key columns, None in a dump with the
# ten old columns only
CLS, ID, X, Y, Z, LB, IEG, NCROSS, KEY, RANK = range(10)


def read_part(path, rank):
    """{time: [entry]} of one rank."""
    out = {}
    for n, f in read_lines(path, (10, 16)):
        if f[0] not in ("P", "M", "G", "D"):
            raise DumpError("%s:%d: unknown class %r" % (path, n, f[0]))
        check_rank(path, n, rank, f[8])
        t = round(to_num(path, n, float, f[1]), 1)
        key = None
        if len(f) == 16:
            key = (to_num(path, n, int, f[10]), to_num(path, n, float, f[11]),
                   to_num(path, n, float, f[12]), to_num(path, n, int, f[13]),
                   to_num(path, n, float, f[14]), to_num(path, n, float, f[15]))
        entry = (f[0], to_num(path, n, int, f[2]), to_num(path, n, float, f[3]),
                 to_num(path, n, float, f[4]), to_num(path, n, float, f[5]),
                 to_num(path, n, int, f[6]), to_num(path, n, int, f[7]),
                 to_num(path, n, int, f[9]), key, rank)
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


def tie_break(a, b, elem=False):
    """(layer differs, |dz|) for equal distances: same layer and closest z
    first (several particles can share a position in different layers).
    With elem: (layer differs, element differs, |dz|), so that two particles
    at one point in two elements (a point on a shared side) pair with the
    partner in the same element."""
    dz = abs(a[Z] - b[Z])
    lbd = 0 if a[LB] == b[LB] else 1
    dz = dz if dz == dz else math.inf
    if elem:
        return (lbd, 0 if a[IEG] == b[IEG] else 1, dz)
    return (lbd, dz)


def candidate_edges(ser, mpi, free_s, free_m, k, elem=False):
    """(distance, tie key, i, j) to the k nearest free MPI particles of
    every free serial particle (all positions finite); tie key as in
    tie_break."""
    ms = sorted(free_m, key=lambda j: mpi[j][X])
    xs = [mpi[j][X] for j in ms]
    n = len(ms)
    edges = []
    for i in free_s:
        x, y = ser[i][X], ser[i][Y]
        heap = []                # (-distance, -tie key, -j): k nearest so far
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
                key = tie_break(ser[i], mpi[ms[p]], elem)
                item = (-d, tuple(-v for v in key), -ms[p])
                if len(heap) < k:
                    heapq.heappush(heap, item)
                elif item > heap[0]:
                    heapq.heapreplace(heap, item)
                if side == 0:
                    hi += 1
                else:
                    lo -= 1
        edges.extend((-nd, tuple(-v for v in nkey), i, -nj)
                     for nd, nkey, nj in heap)
    return edges


def match_nearest(ser, mpi, elem=False):
    """One-to-one match by increasing distance (greedy).  Returns the pairs
    [(serial, mpi, distance)] and the numbers of unmatched entries of each
    run.  Entries must have finite positions.  With elem, equal distances
    prefer the partner in the same element (after the same layer)."""
    free_s = list(range(len(ser)))
    free_m = list(range(len(mpi)))
    pairs = []
    while free_s and free_m:
        full = len(free_s) * len(free_m) <= FULL_EDGES
        if full:
            edges = [(distance(ser[i], mpi[j]),
                      tie_break(ser[i], mpi[j], elem), i, j)
                     for i in free_s for j in free_m]
        else:
            edges = candidate_edges(ser, mpi, free_s, free_m, K_NEAREST, elem)
        edges.sort()
        used_s, used_m = set(), set()
        for d, key, i, j in edges:
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


def match_key(ser, mpi):
    """Pairs by key (first entry of each key); returns pairs and the numbers
    of entries of each run left without a partner."""
    mk = {}
    for e in mpi:
        mk.setdefault(e[KEY], e)
    pairs = []
    seen = set()
    for e in ser:
        if e[KEY] in seen:
            continue
        seen.add(e[KEY])
        if e[KEY] in mk:
            m = mk[e[KEY]]
            pairs.append((e, m, distance(e, m)))
    return pairs, len(seen) - len(pairs), len(mk) - len(pairs)


def dup_keys(entries):
    seen, dups = set(), set()
    for e in entries:
        if e[KEY] in seen:
            dups.add(e[KEY])
        seen.add(e[KEY])
    return len(dups)


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


def require_keys(ser, mpi, args):
    """--by key needs the six key columns in every particle line."""
    for name, run, d in (("serial", ser, args.serial_dir),
                         ("mpi", mpi, args.mpi_dir)):
        for entries in run.values():
            if any(e[KEY] is None for e in entries):
                raise DumpError("%s: the %s dump has particle lines without "
                                "the six key columns (a dump of an older "
                                "version): --by key needs them"
                                % (d, name))


def poisson_quantile(mean, q):
    """Smallest k with P(X <= k) >= q for X Poisson with this mean; 0 for a
    mean of 0.  The cumulative sum of the Poisson terms, each from the one
    before (p_0 = exp(-mean), p_k = p_(k-1) * mean / k); for a mean whose
    exp(-mean) underflows (above 700) the terms come from their logarithms.
    The sum stops at mean + 40 sqrt(mean) + 100, beyond which the terms are
    below 1e-300 (only a q within rounding of 1 can get there)."""
    if not mean > 0:
        return 0
    kcap = int(mean + 40.0 * math.sqrt(mean) + 100.0)
    k = 0
    if mean < 700.0:
        term = math.exp(-mean)
        cdf = term
        while cdf < q and k < kcap:
            k += 1
            term *= mean / k
            cdf += term
    else:
        lmean = math.log(mean)
        cdf = math.exp(-mean)
        while cdf < q and k < kcap:
            k += 1
            cdf += math.exp(-mean + k * lmean - math.lgamma(k + 1))
    return k


def handover_stats(times, pairs_at, state_at, step):
    """Hand-over statistic over consecutive blocks.  pairs_at[t] = {key:
    (serial entry, mpi entry, distance)} of the pairs in the domain in both
    runs, state_at[t] = {key: all four classes present} -- see cmd_part.
    Returns {"changed": [...], "stayed": [...]} with [pairs, at 0, within,
    beyond, largest], the number of pairs left out, the pairs beyond the
    step of each group and the "changed" pairs at a distance other than 0
    (each as key, time 1, time 2, rank 1, rank 2, distance)."""
    groups = {"changed": [0, 0, 0, 0, 0.0], "stayed": [0, 0, 0, 0, 0.0]}
    left_out = 0
    beyond = {"changed": [], "stayed": []}
    moved = []
    for t1, t2 in zip(times, times[1:]):
        for key in set(state_at[t1]) & set(state_at[t2]):
            if key not in pairs_at[t1] or key not in pairs_at[t2]:
                left_out += 1
                continue
            s1, m1, d1 = pairs_at[t1][key]
            s2, m2, d2 = pairs_at[t2][key]
            if not d1 == 0:
                continue
            key_name = "changed" if m1[RANK] != m2[RANK] else "stayed"
            g = groups[key_name]
            g[0] += 1
            if d2 == 0:
                g[1] += 1
            elif d2 <= step:
                g[2] += 1
            else:
                g[3] += 1
                beyond[key_name].append((key, t1, t2, m1[RANK], m2[RANK], d2))
            if key_name == "changed" and not d2 == 0:
                moved.append((key, t1, t2, m1[RANK], m2[RANK], d2))
            g[4] = worse(g[4], d2)
    return groups, left_out, beyond, moved


def handover_report(groups, left_out, beyond_list, moved, args):
    """Print the two groups and the rule (jump test, count test: see the
    module docstring); return the number of failures."""
    print("  hand-over check (pairs of consecutive blocks, particle in the "
          "domain in both runs at both blocks and at distance 0 at the "
          "first), step %g" % args.step)
    print("  %-16s %7s %7s %7s %7s %12s %9s"
          % ("group", "pairs", "at 0", "within", "beyond", "largest", "rate"))
    rate = {}
    for name, label in (("changed", "changed process"), ("stayed", "stayed")):
        n, z, w, b, big = groups[name]
        rate[name] = b / n if n else 0.0
        print("  %-16s %7d %7d %7d %7d %12.4e %9.3e"
              % (label, n, z, w, b, big, rate[name]))
    print("  pairs left out (the particle is not in the domain in both runs "
          "at both blocks): %d" % left_out)
    for key, t1, t2, r1, r2, d in beyond_list["changed"][:100]:
        print("  changed process, beyond the step: key %s, times %.1f -> %.1f,"
              " ranks %d -> %d, distance %.4e"
              % (" ".join("%.17g" % v for v in key), t1, t2, r1, r2, d))
    nfail = 0
    if groups["changed"][0] == 0:
        print("  no changed-process pair: the hand-over was not exercised")
    if groups["changed"][0] == 0 and groups["stayed"][0] == 0:
        print("  FAIL: no pair at distance 0 at the first block of any two "
              "consecutive blocks: nothing was compared")
        nfail += 1
    if groups["changed"][0] < args.min_changed:
        print("  FAIL: %d changed-process pairs found, %d required "
              "(--min-changed)" % (groups["changed"][0], args.min_changed))
        nfail += 1
    # jump test: no changed pair beyond the noise of the stayed group
    big_ch, big_st = groups["changed"][4], groups["stayed"][4]
    floor = args.jump_floor * args.step
    jthr = max(args.jump_factor * big_st, floor)
    if math.isnan(big_st):
        jthr = float("nan")
    jump_bad = not big_ch <= jthr
    # count test: no more changed pairs beyond the step than chance allows
    nbeyond = groups["changed"][3]
    mean = rate["stayed"] * groups["changed"][0]
    qk = poisson_quantile(mean, args.quantile)
    count_bad = nbeyond > qk
    print("  rule: jump test: largest changed-process distance %g %s threshold"
          " %g (%g x stayed largest %g, floor %g steps %g): %s; count test: %d"
          " beyond the step %s Poisson %g %% quantile %d (mean %g): %s"
          % (big_ch, ">" if jump_bad else "<=", jthr, args.jump_factor,
             big_st, args.jump_floor, floor, "FAIL" if jump_bad else "ok",
             nbeyond, ">" if count_bad else "<=", 100.0 * args.quantile, qk,
             mean, "FAIL" if count_bad else "ok"))
    above = [m for m in moved if not m[5] <= jthr]
    for key, t1, t2, r1, r2, d in above[:100]:
        print("  changed process, above the jump threshold: key %s, times %.1f"
              " -> %.1f, ranks %d -> %d, distance %.4e"
              % (" ".join("%.17g" % v for v in key), t1, t2, r1, r2, d))
    if len(above) > 100:
        print("  ... %d more changed-process pairs above the jump threshold"
              % (len(above) - 100))
    return nfail + (1 if jump_bad else 0) + (1 if count_bad else 0)


def cmd_part(args):
    ser, _ = load_part(dump_dir(args.serial_dir, True), args.serial_dir)
    mpi, mentries = load_part(dump_dir(args.mpi_dir, False), args.mpi_dir)
    if args.by == "key":
        require_keys(ser, mpi, args)
    print("part: serial %s, mpi %s, ranks %d, match by %s, tol %g"
          % (args.serial_dir, args.mpi_dir, len(mentries), args.by, args.tol))
    nfail = 0
    pairs_at, state_at = {}, {}
    nlisted = 0              # unmatched keys printed (at most 10)
    floor = args.max_beyond_last is not None or args.max_largest is not None
    over_at = {}             # pairs beyond --tol per time (floor test)

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

    print("  %9s %5s %5s %5s %5s %5s %5s %3s %10s %4s %4s %4s %5s %5s %4s%s"
          % ("time", "n_ser", "n_mpi", "D_ser", "D_mpi", "dupid", "unmat",
             "nan", "max dist", ">tol", "lb!=", "z!=", "ncr!=", "ncr-1",
             "ie!=", " id!=" if args.by == "key" else ""))
    worst = (0.0, None)
    tot = dict.fromkeys(("unmat", "nan", "over", "lb", "z", "ncr", "unk",
                         "ie", "ncr0", "ncrn", "id"), 0)
    for t in times:
        sa = [e for e in ser.get(t, []) if e[CLS] in ALIVE]
        ma = [e for e in mpi.get(t, []) if e[CLS] in ALIVE]
        nd_s = len(ser.get(t, [])) - len(sa)
        nd_m = len(mpi.get(t, [])) - len(ma)
        if args.by == "key":
            ndup = dup_keys(ma)
            ndup_s = dup_keys(sa)
        else:
            ndup = dup_ids(ma)
            ndup_s = dup_ids(sa)
        nnan = sum(1 for e in sa + ma if not finite(e))
        if args.by == "key":
            pairs, un_s, un_m = match_key(sa, ma)
        elif args.by == "id":
            pairs, un_s, un_m = match_id(sa, ma)
        else:
            pairs, un_s, un_m = match_nearest([e for e in sa if finite(e)],
                                              [e for e in ma if finite(e)],
                                              args.elem)
        unmat = un_s + un_m
        if args.by == "key" and unmat:
            ks = {e[KEY]: e for e in sa}
            km = {e[KEY]: e for e in ma}
            for k in sorted(set(ks) ^ set(km))[:5]:
                nlisted += 1
                if nlisted > 10:
                    break
                print("  unmatched key at time %.1f: %s only in %s run, "
                      "class %s, other run: %s"
                      % (t, " ".join("%.17g" % v for v in k),
                         "the serial" if k in ks else "the MPI",
                         (ks.get(k) or km.get(k))[CLS],
                         next((e[CLS] for e in (mpi if k in ks else ser)
                               .get(t, []) if e[KEY] == k), "absent")))
        dmax = nan_max(p[2] for p in pairs)
        nover = sum(1 for p in pairs if not p[2] <= args.tol)
        nlb = sum(1 for p in pairs if p[0][LB] != p[1][LB])
        nz = sum(1 for p in pairs if not abs(p[0][Z] - p[1][Z]) <= Z_TOL)
        nunk = sum(1 for p in pairs if p[0][NCROSS] == -1 or p[1][NCROSS] == -1)
        nx = sum(1 for p in pairs if p[0][NCROSS] != -1 and p[1][NCROSS] != -1
                 and p[0][NCROSS] != p[1][NCROSS])
        nie = sum(1 for p in pairs if p[0][IEG] != p[1][IEG])
        nx0 = sum(1 for p in pairs if p[0][NCROSS] != -1 and p[1][NCROSS] != -1
                  and p[0][NCROSS] != p[1][NCROSS] and p[2] == 0)
        nxn = nx - nx0
        nid = sum(1 for p in pairs if p[0][ID] != p[1][ID])
        note = ""
        bad = unmat + nnan
        over_at[t] = nover
        if not args.handover:
            bad += nlb + nz
            if not floor:
                bad += nover
        if len(sa) != len(ma):
            bad += 1
            note += " COUNT"
        if ndup_s:
            bad += ndup_s
            note += " serial dup %s %d" % ("keys" if args.by == "key"
                                           else "ids", ndup_s)
        if args.by in ("id", "key"):
            bad += ndup
        if args.by == "key":
            tot["ncr0"] += nx0
            tot["ncrn"] += nxn
            tot["id"] += nid
        if args.ncross:
            bad += nx0 if args.by == "key" else nx
        if args.elem:
            bad += nie
        if args.ids:
            bad += nid
        nfail += bad
        for key, v in (("unmat", unmat), ("nan", nnan), ("over", nover),
                       ("lb", nlb), ("z", nz), ("ncr", nx), ("unk", nunk),
                       ("ie", nie)):
            tot[key] += v
        if not math.isnan(worst[0]) and (math.isnan(dmax) or dmax > worst[0]):
            worst = (dmax, t)
        if args.handover:
            pairs_at[t] = {p[0][KEY]: p for p in reversed(pairs)}
            sk = {e[KEY]: e[CLS] for e in ser.get(t, [])}
            mk = {e[KEY]: e[CLS] for e in mpi.get(t, [])}
            state_at[t] = {k: 1 for k in set(sk) & set(mk)}
        print("  %9.1f %5d %5d %5d %5d %5d %5d %3d %10.3e %4d %4d %4d %5d %5d"
              " %4d%s%s"
              % (t, len(sa), len(ma), nd_s, nd_m, ndup, unmat, nnan, dmax,
                 nover, nlb, nz, nx, nunk, nie,
                 " %4d" % nid if args.by == "key" else "", note))
    if worst[1] is not None:
        print("  largest distance %.4e at time %.1f" % worst)
    ng = " (not gated)" if args.handover else ""
    if args.handover:
        over_note = ng
    elif floor:
        over_note = " (not gated pair by pair: floor test)"
    else:
        over_note = ""
    if not args.ncross:
        ncr_note = " (not gated)"
    elif args.by == "key":
        ncr_note = " (gated at distance 0 only)"
    else:
        ncr_note = ""
    id_note = ""
    if args.by == "key":
        id_note = (", id differs %d%s"
                   % (tot["id"], "" if args.ids else " (not gated)"))
    print("  totals over %d outputs: unmatched %d, nan %d, beyond tol %d%s,"
          " layer differs %d%s, z differs %d%s, ncross differs %d%s,"
          " ncross unknown (-1) %d, element differs %d%s%s"
          % (len(times), tot["unmat"], tot["nan"], tot["over"], over_note,
             tot["lb"], ng, tot["z"], ng, tot["ncr"], ncr_note,
             tot["unk"], tot["ie"], "" if args.elem else " (not gated)",
             id_note))
    if args.by == "key":
        print("  ncross differs at distance 0: %d%s; at a non-zero distance:"
              " %d (never gated)"
              % (tot["ncr0"], "" if args.ncross else " (not gated)",
                 tot["ncrn"]))
    if args.handover:
        groups, left_out, beyond_list, moved = handover_stats(
            times, pairs_at, state_at, args.step)
        nfail += handover_report(groups, left_out, beyond_list, moved, args)
    if floor:
        nfail += floor_report(times, ser, mpi, over_at, worst, args)
    return nfail


def floor_report(times, ser, mpi, over_at, worst, args):
    """The floor tests of --max-beyond-last and --max-largest (see the
    module docstring); print one line per test, return the failures."""
    nfail = 0
    if args.max_beyond_last is not None:
        shared = [t for t in times if t in ser and t in mpi]
        if not shared:
            print("  floor: FAIL: no output time in both runs")
            nfail += 1
        else:
            last = shared[-1]
            n = over_at[last]
            bad = n > args.max_beyond_last
            print("  floor: pairs beyond --tol %g at the last output both runs"
                  " share (time %.1f): %d %s %d: %s"
                  % (args.tol, last, n, ">" if bad else "<=",
                     args.max_beyond_last, "FAIL" if bad else "ok"))
            nfail += 1 if bad else 0
    if args.max_largest is not None:
        big = worst[0]
        bad = not big <= args.max_largest
        at = "" if worst[1] is None else " (time %.1f)" % worst[1]
        print("  floor: largest distance at any output%s: %.6g %s %g: %s"
              % (at, big, ">" if bad else "<=", args.max_largest,
                 "FAIL" if bad else "ok"))
        nfail += 1 if bad else 0
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
    p.add_argument("--by", choices=("id", "nearest", "key"), default="nearest")
    p.add_argument("--first-only", action="store_true",
                   help="compare the first time in the files only (the"
                        " release block)")
    p.add_argument("--ranks-empty-ok", action="store_true",
                   help="ranks without any entry are expected (never a failure)")
    p.add_argument("--ncross", action="store_true",
                   help="fail if a matched particle's crossing count differs")
    p.add_argument("--elem", action="store_true",
                   help="fail if a matched particle's global element differs")
    p.add_argument("--ids", action="store_true",
                   help="with --by key: fail if the ids of a pair matched by"
                        " key differ")
    p.add_argument("--handover", action="store_true",
                   help="with --by key: compare the particles that changed"
                        " process with those that stayed")
    p.add_argument("--step", type=float, default=6e-8,
                   help="--handover: one single-precision step, a length in"
                        " the dump's unit (default 6e-8, degrees)")
    p.add_argument("--jump-factor", type=float, default=2.0,
                   help="--handover, jump test: a changed-process pair fails"
                        " above this factor times the stayed group's largest"
                        " distance (default 2)")
    p.add_argument("--jump-floor", type=float, default=10.0,
                   help="--handover, jump test: the threshold is at least"
                        " this many steps (default 10)")
    p.add_argument("--quantile", type=float, default=0.999,
                   help="--handover, count test: the Poisson quantile the"
                        " changed-process pairs beyond the step may reach"
                        " (default 0.999)")
    p.add_argument("--min-changed", type=int, default=0,
                   help="--handover: fail if fewer than N pairs are in the"
                        " changed-process group (default 0)")
    p.add_argument("--max-beyond-last", type=int, default=None,
                   help="with --by key: floor test, fail if more than N"
                        " matched pairs are beyond --tol at the last output"
                        " both runs share (a pair beyond --tol is then no"
                        " failure by itself)")
    p.add_argument("--max-largest", type=float, default=None,
                   help="with --by key: floor test, fail if the largest"
                        " distance at any output exceeds D (a pair beyond"
                        " --tol is then no failure by itself)")
    p.set_defaults(func=cmd_part)
    args = ap.parse_args(argv)
    if not args.tol >= 0:
        ap.error("--tol must be >= 0")
    if args.mode == "part":
        if args.handover and args.by != "key":
            ap.error("--handover needs --by key")
        if args.ids and args.by != "key":
            ap.error("--ids needs --by key")
        if args.handover and args.first_only:
            ap.error("--handover cannot be combined with --first-only")
        if args.min_changed < 0:
            ap.error("--min-changed must be >= 0")
        if not args.step >= 0 or not args.jump_factor >= 0 \
                or not args.jump_floor >= 0:
            ap.error("--step, --jump-factor and --jump-floor must be >= 0")
        if not 0 < args.quantile < 1:
            ap.error("--quantile must lie in (0, 1)")
        if (args.max_beyond_last is not None or args.max_largest is not None) \
                and args.by != "key":
            ap.error("--max-beyond-last and --max-largest need --by key")
        if args.max_beyond_last is not None and args.max_beyond_last < 0:
            ap.error("--max-beyond-last must be >= 0")
        if args.max_largest is not None and not args.max_largest >= 0:
            ap.error("--max-largest must be >= 0")
    try:
        nfail = args.func(args)
    except DumpError as e:
        print("lgr_dbg_compare: %s" % e, file=sys.stderr)
        return 2
    print("lgr_dbg_compare %s: %s" % (args.mode, "PASS" if nfail == 0 else "FAIL"))
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
