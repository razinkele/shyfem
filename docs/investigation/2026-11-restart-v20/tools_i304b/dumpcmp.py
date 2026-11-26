#!/usr/bin/env python3
"""dumpcmp.py A.bin B.bin [-a] : per-array max |A-B| of two I304 dumps (all in double).
Only differing arrays are printed unless -a."""
import sys, struct
import numpy as np

def load(p):
    d = {}; order = []
    buf = open(p, 'rb').read(); i = 0
    while i < len(buf):
        name = buf[i:i+16].decode().strip(); (n,) = struct.unpack_from('<i', buf, i+16); i += 20
        v = np.frombuffer(buf, '<f8', n, i); i += 8*n
        d[name] = v; order.append(name)
    return d, order

a, oa = load(sys.argv[1]); b, ob = load(sys.argv[2]); alll = '-a' in sys.argv
for k in oa:
    if k not in b: print(f"{k:12s} only in A"); continue
    x, y = a[k], b[k]
    if x.size != y.size: print(f"{k:12s} size {x.size} vs {y.size}"); continue
    fin = np.isfinite(x) & np.isfinite(y)
    d = np.abs(x - y); d[~fin] = 0
    nfin = np.count_nonzero(np.isfinite(x) != np.isfinite(y)) + np.count_nonzero((~np.isfinite(x)) & (~np.isfinite(y)) & (x != y))
    nz = np.count_nonzero(d)
    if nz or nfin or alll:
        sc = np.abs(x[fin]).max() if fin.any() else 0
        print(f"{k:12s} max|d|={d.max():.3e}  nonzero={nz}/{x.size}  nonfinite-mismatch={nfin}  max|A|={sc:.3e}")
for k in ob:
    if k not in a: print(f"{k:12s} only in B")
