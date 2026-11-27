#!/usr/bin/env python3
"""Deposition at the bed of ilagr = 3 particles (#311), for check_lgr_bed.sh part 5.

usage: lgr_dep_check.py FILE.lgr.shy FILE.hydro.shy cross LO HI NMIN
       lgr_dep_check.py FILE.lgr.shy FILE.hydro.shy band LO HI NMIN

Still water (no horizontal motion, no erosion), particles released uniformly
in relative depth, each with its sediment class (type) and settling velocity s.

cross: the particles of the fastest class (type 3) deposited between the
  outputs at 1 h and 5 h, over the deterministic crossing count of the same
  particles at K = 0: those whose height above the bed d0 (hev less the depth
  hl at the release) satisfies s (1 h - tt) < d0 <= s (5 h - tt), tt the release
  time.  The ratio must lie in LO ... HI and the count in the interval at least NMIN.
band:  F / S over the run, F the deposits, S = the sum over the intervals
  between outputs of the mean of the two ends of sum(s / 0.2 m) over the
  particles in the water within 0.2 m of the bed (columns at least 0.2 m
  deep), i.e. flux / (sv C_bed) with C_bed the concentration of that band.
  The ratio must lie in LO ... HI and the deposits at least NMIN.
Exit 0 if the ratio is in range, 1 otherwise, 2 on bad input.
"""
import struct
import sys
import os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lgr_vprof as lv

BAND = 0.2


def outputs(path):
    """[(time, {iwhat: structured array})] of a particle file (the layout of
    lgr_compare.py: block header, then per particle three records)."""
    data = open(path, "rb").read()
    pos = 0
    recs = []
    while len(recs) < 60:
        (n,) = struct.unpack_from("<i", data, pos)
        recs.append((pos, n))
        pos += 8 + n
    off = ncust = None
    for i in range(len(recs) - 1):
        if recs[i][1] == 4 and recs[i + 1][1] == 16:
            nc = struct.unpack_from("<i", data, recs[i][0] + 4)[0]
            _, n, iw = struct.unpack_from("<dii", data, recs[i + 1][0] + 4)
            nxt = struct.unpack_from("<i", data, recs[i + 1][0] + 24)[0]
            if iw == 0 and 0 <= nc < 100 and n > 0 and nxt == 24:
                off, ncust = recs[i + 1][0], nc
                break
    if off is None:
        raise SystemExit("no particle section in %s" % path)
    dt = np.dtype([("m1", "<i4"), ("id", "<i4"), ("type", "<i4"), ("tt", "<f8"),
                   ("s", "<f4"), ("ie", "<i4"), ("m1b", "<i4"),
                   ("m2", "<i4"), ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                   ("lb", "<i4"), ("hl", "<f4"), ("m2b", "<i4"),
                   ("m3", "<i4"), ("c", "<f4", (ncust,)), ("m3b", "<i4")])
    out = []
    while off < len(data):
        blocks = {}
        t = None
        for iw in (0, -1, 1):
            (m,) = struct.unpack_from("<i", data, off)
            t, n, iwhat = struct.unpack_from("<dii", data, off + 4)
            if m != 16 or iwhat != iw:
                raise SystemExit("bad block header at byte %d of %s" % (off, path))
            off += 24
            arr = np.frombuffer(data, dtype=dt, count=n, offset=off)
            off += n * dt.itemsize
            blocks[iw] = arr
        out.append((t, blocks))
    return out


def main():
    if len(sys.argv) != 7 or sys.argv[3] not in ("cross", "band"):
        print(__doc__)
        return 2
    lgr, hydro, mode = sys.argv[1], sys.argv[2], sys.argv[3]
    lo, hi, nmin = float(sys.argv[4]), float(sys.argv[5]), int(sys.argv[6])
    g = lv.read_geom(hydro)
    hev = np.asarray(g["hev"], dtype=np.float64)
    outs = outputs(lgr)
    times = [t for t, _ in outs]
    bt = dict(outs)
    rel = outs[0][1][-1]
    print("  %d particles released, %d outputs (%.0f ... %.0f s)"
          % (len(rel), len(outs), times[0], times[-1]))
    if mode == "cross":
        for t in (3600.0, 18000.0):
            if t not in bt:
                print("  FAIL: no output at %.0f s" % t)
                return 1
        ie = rel["ie"].astype(np.int64)
        d0 = hev[ie - 1] - rel["hl"].astype(np.float64)
        sv = rel["s"].astype(np.float64)
        tt = rel["tt"].astype(np.float64)
        c3 = rel["type"] == 3
        n_exp = int(((d0 > sv * (3600.0 - tt)) & (d0 <= sv * (18000.0 - tt)) & c3).sum())

        def ndep(t):
            a = bt[t][0]
            return int(((a["lb"] < 1) & (a["type"] == 3)).sum())
        n_dep = ndep(18000.0) - ndep(3600.0)
        r = n_dep / n_exp if n_exp else float("nan")
        print("  class 3: deposited between 1 h and 5 h %d, deterministic crossings of the same"
              " particles at K = 0: %d, ratio %.3f (required %.2f ... %.2f, at least %d deposited)"
              % (n_dep, n_exp, r, lo, hi, nmin))
        return 0 if (n_dep >= nmin and lo <= r <= hi) else 1
    # band
    num = den = 0.0
    prev = None
    for t, b in outs:
        a = b[0]
        ie = a["ie"].astype(np.int64)
        dep = a["lb"] < 1
        H = hev[np.maximum(ie, 1) - 1]
        dbed = H - a["hl"].astype(np.float64)
        m = (ie >= 1) & ~dep & (dbed <= BAND) & (H >= BAND)
        S = float((a["s"].astype(np.float64)[m] / BAND).sum())
        nd = int(dep.sum())
        if prev is not None:
            dt_ = t - prev[0]
            num += nd - prev[2]
            den += 0.5 * (S + prev[1]) * dt_
        prev = (t, S, nd)
    ndep_all = prev[2]
    r = num / den if den > 0 else float("nan")
    print("  deposited %d; flux / (sv C_bed), C_bed the band of %.1f m above the bed: %.3f"
          " (required %.2f ... %.2f, at least %d deposited)" % (ndep_all, BAND, r, lo, hi, nmin))
    return 0 if (ndep_all >= nmin and lo <= r <= hi) else 1


sys.exit(main())
