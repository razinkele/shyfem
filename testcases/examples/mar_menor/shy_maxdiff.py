#!/usr/bin/env python3
"""shy_maxdiff.py A B : max|A - B| per variable and time of two SHYFEM output
files of the same kind, both .shy (shyfile, id 1617) or both .ext (extra
points, id 947336; the kind is taken from the file, not from its name).

Written for check_restart_fidelity.sh (#303, #304): A is the continuous run,
B the run read from a restart file.  Ported from the audit's shycmp.py and
extcmp.py (docs/investigation/2026-11-restart-v20/tools_i304b).

Records.  A data record is matched by its time (the .shy time relative to
the file's date, the absolute .ext time), its variable (ivar), its size
(.shy: n, m, lmax; .ext: m, lmax) and its order among the records with the
same key at that time (the u and v transports of a .shy file have the same
ivar).  Values are single precision, compared as doubles: |d| = |a - b|.
The same value in both (also the same infinity) or NaN in both at the same
place counts as equal, NaN against a number as an infinite difference.

Compared: every record of B with its match in A.  A record of B without a
match in A, or a record of A at or after B's first time without a match in
B, is "unmatched" and counts as a difference (the runs wrote at other times,
for example after another time-step history).

Prints one line per time and variable: the largest |d| over the matched
records of that variable at that time, and how many values differ; one
line per unmatched record; then a summary line
  SUMMARY <kind>: B has NB records, compared NC, differ ND, unmatched NU
          (B NUB, A NUA), byte-identical NI; max|d| NAME=X@T ...
with the largest |d| of every variable over the run and the time where it
occurs.  Times are in hours from the file's start date (.shy) or from A's
start time atime0 (.ext).

Exit status: 0 if every record of B has its match in A, every record of A
from B's first time on has its match in B, and every value is equal
(max|d| = 0); 1 if a value differs or a record is unmatched; 2 if the files
cannot be compared (unreadable, of another or an unknown kind, another
start date, no data record in B, or no record compared).
"""
import struct
import sys

import numpy as np

SHY_ID = 1617
EXT_ID = 947336
NAMES = {1: 'zeta', 2: 'velocity', 3: 'transport', 11: 'S', 12: 'T'}


class FormatError(Exception):
    pass


def records(path):
    """The records of a Fortran sequential unformatted file (4-byte markers)."""
    with open(path, 'rb') as f:
        buf = f.read()
    out = []
    p = 0
    while p < len(buf):
        if p + 4 > len(buf):
            raise FormatError(f"{path}: truncated record marker at byte {p}")
        (n,) = struct.unpack_from('<i', buf, p)
        if n < 0 or p + 8 + n > len(buf):
            raise FormatError(f"{path}: bad record length {n} at byte {p}")
        (n2,) = struct.unpack_from('<i', buf, p + 4 + n)
        if n2 != n:
            raise FormatError(f"{path}: record markers {n} and {n2} differ at byte {p}")
        out.append(buf[p + 4:p + 4 + n])
        p += 8 + n
    return out


def kind_of(recs, path):
    if recs and len(recs[0]) == 8:
        fid, _ = struct.unpack('<2i', recs[0])
        if fid == SHY_ID:
            return 'shy'
        if fid == EXT_ID:
            return 'ext'
    raise FormatError(f"{path}: neither a .shy file (id {SHY_ID}) nor an .ext file (id {EXT_ID})")


def shy_data(recs, path):
    """(start, t0, [(time_s, ivar, size, values)]) of a .shy file (versions 11-15:
    the header ends at its second empty record; data come in pairs, the
    24-byte (dtime, ivar, n, m, lmax) record, then the values)."""
    # idshy,nvers / ftype / nkn,nel,npr,nlv,nvar / [nfix] / date,time / ...
    # (the versions with nfix have its 4-byte record before date,time)
    if len(recs) < 5 or len(recs[2]) != 20:
        raise FormatError(f"{path}: unexpected .shy header")
    i = 3
    if len(recs[i]) == 4:   # nfix
        i += 1
    if len(recs[i]) != 8:
        raise FormatError(f"{path}: no date,time record in the .shy header")
    start = struct.unpack('<2i', recs[i])  # compared between A and B
    empty = [k for k, r in enumerate(recs) if len(r) == 0]
    if len(empty) < 2:
        raise FormatError(f"{path}: .shy header not terminated")
    i = empty[1] + 1
    out = []
    while i < len(recs):
        r = recs[i]
        if len(r) != 24 or i + 1 >= len(recs):
            raise FormatError(f"{path}: record {i} is not a data header")
        dt, ivar, n, m, lmax = struct.unpack('<d4i', r)
        v = recs[i + 1]
        if len(v) % 4:
            raise FormatError(f"{path}: record {i + 1} is not single precision values")
        out.append((dt, ivar, (n, m, lmax), v))
        i += 2
    return start, 0., out


def ext_data(recs, path):
    """(None, atime0, [(atime, ivar, size, values)]) of an .ext file (version
    > 6: type,version / knausm,lmax,nvar / five header records, the first
    atime0; then the data records (atime, ivar, m, lmax, nlin, values) or,
    for ivar 0, (atime, ivar, m, lm, values))."""
    if len(recs) < 2 or len(recs[1]) != 12:
        raise FormatError(f"{path}: unexpected .ext header")
    _, nvers = struct.unpack('<2i', recs[0])
    knausm, _, _ = struct.unpack('<3i', recs[1])
    if nvers <= 6 or len(recs[2]) != 8:
        raise FormatError(f"{path}: .ext version {nvers} not supported")
    (atime0,) = struct.unpack('<d', recs[2])
    out = []
    for i in range(7, len(recs)):
        r = recs[i]
        if len(r) < 20:
            raise FormatError(f"{path}: record {i} is too short for a data record")
        at, ivar, m, lmax = struct.unpack_from('<d3i', r)
        if ivar == 0:
            v = r[20:]
            if len(v) != 4 * knausm * m:
                raise FormatError(f"{path}: record {i} has a wrong size")
        else:
            (nlin,) = struct.unpack_from('<i', r, 20)
            v = r[24:]
            if len(v) != 4 * nlin:
                raise FormatError(f"{path}: record {i} has a wrong size")
        out.append((at, ivar, (m, lmax), v))
    return None, atime0, out


def load(path):
    recs = records(path)
    kind = kind_of(recs, path)
    start, t0, data = (shy_data if kind == 'shy' else ext_data)(recs, path)
    keyed = {}
    count = {}
    for t, ivar, size, v in data:
        k = (t, ivar, size)
        j = count.get(k, 0)
        count[k] = j + 1
        keyed[k + (j,)] = v
    return kind, start, t0, keyed


def absdiff(a, b):
    x = np.frombuffer(a, '<f4').astype(np.float64)
    y = np.frombuffer(b, '<f4').astype(np.float64)
    if x.size != y.size:
        return float('inf'), max(x.size, y.size), max(x.size, y.size)
    nx, ny = np.isnan(x), np.isnan(y)
    with np.errstate(invalid='ignore'):
        d = np.abs(x - y)
    d[x == y] = 0.          # the same inf in both (inf - inf is NaN)
    d[nx & ny] = 0.
    d[nx ^ ny] = np.inf
    return (float(d.max()) if d.size else 0.), int(np.count_nonzero(d)), d.size


def name(ivar):
    return NAMES.get(ivar, f"iv{ivar}")


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[0])
        return 2
    try:
        ka, sa, t0, a = load(argv[1])
        kb, sb, _, b = load(argv[2])
    except (OSError, FormatError, struct.error) as e:
        print(f"shy_maxdiff: cannot read: {e}")
        return 2
    if ka != kb:
        print(f"shy_maxdiff: {argv[1]} is a .{ka} file, {argv[2]} a .{kb} file")
        return 2
    if sa != sb:
        print(f"shy_maxdiff: the start dates differ: {sa} and {sb}")
        return 2
    if not b:
        print(f"shy_maxdiff: {argv[2]} has no data record")
        return 2
    # hours from the start date (.shy) or from A's atime0 (.ext)
    def hours(t):
        return (t - t0) / 3600.

    tb0 = min(k[0] for k in b)
    per = {}       # (time, ivar) -> [maxd, nonzero, size, nrec]
    run = {}       # ivar -> [maxd, time]
    nc = nd = ni = 0
    unmatched_b = sorted(k for k in b if k not in a)
    unmatched_a = sorted(k for k in a if k[0] >= tb0 and k not in b)
    for k in sorted(b):
        if k not in a:
            continue
        t, ivar = k[0], k[1]
        d, nz, n = absdiff(a[k], b[k])
        nc += 1
        nd += d > 0
        ni += a[k] == b[k]
        p = per.setdefault((t, ivar), [0., 0, 0, 0])
        p[0] = max(p[0], d)
        p[1] += nz
        p[2] += n
        p[3] += 1
        r = run.setdefault(ivar, [0., t])
        if d > r[0]:
            run[ivar] = [d, t]
    for (t, ivar), (d, nz, n, nrec) in sorted(per.items()):
        print(f"  t={hours(t):7.3f}h  {name(ivar):9s} max|d|={d:.3e}  "
              f"differ {nz}/{n} values in {nrec} record(s)")
    for side, ks in (('B', unmatched_b), ('A', unmatched_a)):
        for k in ks:
            other = 'A' if side == 'B' else 'B'
            print(f"  t={hours(k[0]):7.3f}h  {name(k[1]):9s} record #{k[3]} of {side}: "
                  f"no record in {other} at this time")
    nu = len(unmatched_b) + len(unmatched_a)
    mx = " ".join(f"{name(iv)}={run[iv][0]:.3e}@{hours(run[iv][1]):g}h" for iv in sorted(run))
    print(f"SUMMARY {ka}: B has {len(b)} records, compared {nc}, differ {nd}, "
          f"unmatched {nu} (B {len(unmatched_b)}, A {len(unmatched_a)}), "
          f"byte-identical {ni}; max|d| {mx}")
    if nc == 0:
        print("shy_maxdiff: no record compared")
        return 2
    return 1 if nd or nu else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
