"""Compare the per-step `energy:` lines of two SHYFEM .inf files (serial vs MPI).

Used when a case writes no .shy output. One tab-separated row:
  label  energy(.inf)  nsteps  max|serial|  max relative diff  worst_step  verdict
Verdict (relative, fixed before looking): agree <= 1e-5, drift <= 1e-2, DIFFERS above.
Usage: infcmp.py LABEL serial.inf mpi.inf
"""

import sys

import numpy as np


def energy(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            if line.lstrip().startswith("energy:"):
                rows.append([float(x) for x in line.split()[2:]])
    return np.array(rows)


label, fa, fb = sys.argv[1:4]
a, b = energy(fa), energy(fb)
if a.shape != b.shape or a.size == 0:
    print(f"{label}\tenergy(.inf)\t-\t-\t-\t-\tSHAPE {a.shape} vs {b.shape}")
    sys.exit(0)
scale = np.abs(a).max(axis=0)
scale[scale == 0] = 1.0
rel = np.abs(a - b) / scale
per_step = rel.max(axis=1)
md = float(per_step.max())
verdict = "agree" if md <= 1e-5 else ("drift" if md <= 1e-2 else "DIFFERS")
print(f"{label}\tenergy(.inf)\t{len(a)}\t{np.abs(a).max():.4g}\t{md:.3g}\t{int(per_step.argmax())}\t{verdict} (relative)")
