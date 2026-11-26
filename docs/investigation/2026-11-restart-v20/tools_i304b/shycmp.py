#!/usr/bin/env python3
"""shycmp.py A.shy B.shy : max |A-B| per (time, ivar, record) for records present in both.
Reads the Fortran sequential records; data records follow a 24-byte header
(dtime double, ivar, n, m, lmax). Values are single precision, packed the same in both
files (same grid), so they are compared element by element."""
import sys, struct
import numpy as np

def records(path):
    out = []
    with open(path, 'rb') as f:
        buf = f.read()
    p = 0
    while p < len(buf):
        (n,) = struct.unpack_from('<i', buf, p)
        out.append(buf[p+4:p+4+n])
        p += 8 + n
    return out

def data(path):
    recs = records(path)
    # header: nkn,nel,npr,nlv,nvar is the 3rd record
    nkn, nel, npr, nlv, nvar = struct.unpack('<5i', recs[2])
    i = 3
    res = []
    while i < len(recs):
        r = recs[i]
        if len(r) == 24:
            dt, ivar, n, m, lmax = struct.unpack('<d4i', r)
            if 0 < ivar < 2000 and n in (nkn, nel) and m in (1, 3) and 1 <= lmax <= nlv and i + 1 < len(recs):
                res.append((dt, ivar, n, m, lmax, np.frombuffer(recs[i+1], '<f4')))
                i += 2
                continue
        i += 1
    return res

a = data(sys.argv[1]); b = data(sys.argv[2])
bmap = {}
for (dt, ivar, n, m, lmax, v) in b:
    bmap.setdefault((dt, ivar, n, m, lmax), []).append(v)
seen = {}
for (dt, ivar, n, m, lmax, v) in a:
    k = (dt, ivar, n, m, lmax)
    j = seen.get(k, 0); seen[k] = j + 1
    if k in bmap and j < len(bmap[k]):
        w = bmap[k][j]
        d = np.abs(v.astype(np.float64) - w.astype(np.float64))
        print(f"t={dt/3600:6.2f}h ivar={ivar:4d} n={n} m={m} lmax={lmax} rec#{j}  max|d|={d.max():.3e}  nonzero={np.count_nonzero(d)}/{d.size}")
