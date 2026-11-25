"""Relative depth of the particles of an ilagr = 3 run, and its histogram.

Used by check_lgr_wellmixed.sh (the modes linear, parabolic and gotm, #286)
and later checks; ported from the investigation scripts anaA.py and
shyhead.py (docs/investigation/2026-11-lgr-walk-redesign/py299).  Standard
library and numpy only.

read_geom(shy_path) -> dict
    the geometry of the header of a SHY file (io_shy.f90 shy_write_header):
    nkn, nel, nlv, nen3v (nel x 3), hm3v (nel x 3), hlv (nlv), ilhv (nel),
    and hev (nel), the mean of hm3v as makehev computes it, stored as
    float32.

rel_depths(times, geom) -> list
    times as lgr_compare.read_file returns them; for each output (in the
    order of times) a list of (pid, s, weight_rel) for its active particles:
      s = hl / (hev(ie) + zeta), the depth of the particle over the depth of
          its current column ie at the output time;
      weight_rel = hev(ie0) of its release element ie0 (the depth of the
          release column at the cold start, zeta = 0: the volume that the
          particle stands for, the weight 'rel' of anaA).
    The particle file holds no water level, so zeta of the column is
    recovered from the particle's own record (lb, z, hl) and the static
    z-levels (anaA's zeta_of):
      lb >= 2: hl = zeta + hlv(lb-1) + z hd(lb), hd(lb) static
      lb == 1: hl = z (hlv(1) + zeta) (lmax > 1), z (hev + zeta) (lmax = 1)
    and a particle with lb == 1 and z < 0.05 takes the median zeta of the
    other particles of its element at that output (0 if there are none).

chi2(values, weights=None, nb=20) -> float
    the chi-square of the nb-bin histogram of the relative depths values,
    with the effective count of anaA: n_eff = W**2 / sum(w**2), v_k = W_k /
    (W / nb), e = n_eff / nb, chi2 = sum_k (v_k e - e)**2 / e.  Without
    weights it is the plain sum_k (n_k - n/nb)**2 / (n/nb).

bin_ratio(values, weights, k0, k1, nb=20) -> float
    the (weighted) share of the bins k0 ... k1-1 over the uniform share
    (k1 - k0)/nb: 1 if uniform.  The top 5 % (surface) is
    bin_ratio(..., 0, 1), the bottom 5 % bin_ratio(..., 19, 20).

The bins are anaA's: bin k = min(max(int(s nb), 0), nb - 1), so s < 0 goes
to the first bin and s >= 1 to the last.
"""
import struct
from collections import defaultdict

import numpy as np


def _records(data, nmax):
    pos = 0
    out = []
    while pos < len(data) and len(out) < nmax:
        (n,) = struct.unpack_from("<i", data, pos)
        out.append(data[pos + 4:pos + 4 + n])
        pos += 8 + n
    return out


def read_geom(shy_path):
    """Geometry of the header of the SHY file shy_path (see the module doc)."""
    with open(shy_path, "rb") as fh:
        data = fh.read(64 * 1024 * 1024)
    r = _records(data, 24)
    nkn, nel, _npr, nlv, _nvar = struct.unpack("<5i", r[2])
    # r[0] idshy,nvers r[1] ftype r[2] dims r[3] nfix r[4] date r[5] nsimpar
    # r[6] simpar r[7] title r[8] femver r[9] empty; then nen3v ipev ipv
    # iarv iarnv xgv ygv hm3v hlv ilhv ilhkv
    if len(r[9]) != 0:
        raise ValueError("%s: unexpected SHY header layout" % shy_path)
    nen3v = np.frombuffer(r[10], "<i4").reshape(nel, 3)
    hm3v = np.frombuffer(r[17], "<f4").reshape(nel, 3)
    hlv = np.frombuffer(r[18], "<f4")
    ilhv = np.frombuffer(r[19], "<i4")
    if hlv.size != nlv or ilhv.size != nel:
        raise ValueError("%s: hlv or ilhv of the wrong size" % shy_path)
    hev = (hm3v.astype(np.float64).sum(axis=1) / 3.0).astype(np.float32)
    return dict(nkn=nkn, nel=nel, nlv=nlv, nen3v=nen3v, hm3v=hm3v, hlv=hlv,
                ilhv=ilhv, hev=hev)


def _bin(s, nb):
    return min(max(int(s * nb), 0), nb - 1)


def rel_depths(times, geom):
    """Per output, [(pid, s, weight_rel)] of the active particles (module doc)."""
    hlv = [float(v) for v in geom["hlv"]]
    hev = [float(v) for v in geom["hev"]]
    ilhv = [int(v) for v in geom["ilhv"]]
    rel = {}				# release records (inserted blocks)
    for _t, b, _d in times:
        rel.update(b[-1])

    def zeta_of(p):
        ie = p["ie"]
        lb = p["lb"]
        z = p["z"]
        hl = p["hl"]
        lmax = ilhv[ie - 1]
        h = hev[ie - 1]
        if lb >= 2:
            hd = (h - hlv[lb - 2]) if lb == lmax else (hlv[lb - 1] - hlv[lb - 2])
            return hl - hlv[lb - 2] - z * hd
        if z < 0.05:
            return None
        return hl / z - (h if lmax == 1 else hlv[0])

    out = []
    for _t, b, _d in times:
        parts = b[0]
        zs = {}
        ze = defaultdict(list)
        for pid, p in parts.items():
            zz = zeta_of(p)
            zs[pid] = zz
            if zz is not None:
                ze[p["ie"]].append(zz)
        zmed = {}
        for ie, v in ze.items():
            v.sort()
            zmed[ie] = v[len(v) // 2]
        rows = []
        for pid, p in parts.items():
            ie = p["ie"]
            zz = zs[pid]
            if zz is None:
                zz = zmed.get(ie, 0.0)
            s = p["hl"] / (hev[ie - 1] + zz)
            rows.append((pid, s, hev[rel[pid]["ie"] - 1]))
        out.append(rows)
    return out


def _hist(values, weights, nb):
    h = [0.0] * nb
    sw = 0.0
    sw2 = 0.0
    if weights is None:
        for s in values:
            h[_bin(s, nb)] += 1.0
        sw = sw2 = float(len(values))
    else:
        for s, w in zip(values, weights):
            h[_bin(s, nb)] += w
            sw += w
            sw2 += w * w
    return h, sw, sw2


def chi2(values, weights=None, nb=20):
    """Effective-count chi-square of the nb-bin histogram (module doc)."""
    h, sw, sw2 = _hist(values, weights, nb)
    if sw <= 0.0:
        return 0.0
    neff = sw * sw / sw2
    e = neff / nb
    return sum((x / (sw / nb) * e - e) ** 2 / e for x in h)


def bin_ratio(values, weights, k0, k1, nb=20):
    """Share of the bins k0 ... k1-1 over the uniform share (module doc)."""
    h, sw, _ = _hist(values, weights, nb)
    if sw <= 0.0:
        return 0.0
    return sum(h[k0:k1]) / sw / ((k1 - k0) / float(nb))
