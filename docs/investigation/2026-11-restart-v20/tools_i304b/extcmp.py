#!/usr/bin/env python3
"""extcmp.py A.ext B.ext [T0] : compares the data records (atime double, ivar, m, lmax, values) of two
.ext files at the times both hold (only times > T0 seconds of B's first record if given):
max|d| per ivar over all common records, number of records compared/differing."""
import sys, struct
import numpy as np
def recs(p):
    buf = open(p, 'rb').read(); p0 = 0; out = []
    while p0 < len(buf):
        (n,) = struct.unpack_from('<i', buf, p0); out.append(buf[p0+4:p0+4+n]); p0 += 8 + n
    return out
def data(p):
    res = {}; cnt = {}
    for r in recs(p):
        if len(r) < 24: continue
        at, iv, m, lm = struct.unpack_from('<d3i', r)
        if not (1e8 < at < 1e11 and 0 < iv < 1000 and m in (1, 2, 3) and 0 < lm < 200): continue
        k = (at, iv, m, lm); j = cnt.get(k, 0); cnt[k] = j + 1
        res[k + (j,)] = np.frombuffer(r[20:20 + 4*((len(r)-20)//4)], '<f4')
    return res
a = data(sys.argv[1]); b = data(sys.argv[2])
common = sorted(set(a) & set(b))
tb = sorted(k[0] for k in b)
t0 = tb[0] if tb else 0
mx = {}; nd = 0; nc = 0
for k in common:
    if k[0] <= t0: continue   # skip B's first (initial) record
    x, y = a[k], b[k]
    if x.size != y.size: continue
    with np.errstate(invalid='ignore'):
        d = np.nanmax(np.abs(x.astype(np.float64) - y.astype(np.float64))) if x.size else 0.
    nc += 1; nd += d > 0; mx[k[1]] = max(mx.get(k[1], 0.), d)
print(f"  ext: {nd}/{nc} records differ (after B's first time); max per ivar " + " ".join(f"iv{k}={v:.3e}" for k, v in sorted(mx.items())))
