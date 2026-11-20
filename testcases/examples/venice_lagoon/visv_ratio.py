#!/usr/bin/env python3
"""k-eps / GOTM eddy-viscosity ratio for the Venice lagoon smoke pair (#125).

usage: visv_ratio.py <keps.dbg> <gotm.dbg>     (both from `shyfem -debout`)

Takes the last record of each run and, over the wet nodes, prints the median of
visv(k-eps)/visv(GOTM) at the top interface (interface 1), at the bottom
(deepest interior interface with nonzero visv in both runs) and as a column
mean (mean over the node's interior interfaces, k-eps over GOTM).  The same
three numbers are repeated for the shallow nodes (at most 2 layers).
Interior interfaces of a node with nl layers are 1..nl-1.
"""
import sys
from pathlib import Path

import numpy as np


def read_dbg(path):
    """[(dtime, {name: array(lmax, nn)})] from a shyfem -debout file."""
    raw = Path(path).read_bytes()
    pos, out = 0, []

    def rec():
        nonlocal pos
        n = int(np.frombuffer(raw, "<i4", 1, pos)[0])
        body = raw[pos + 4 : pos + 4 + n]
        pos += n + 8
        return body

    while pos < len(raw):
        dtime = np.frombuffer(rec(), "<f8")[0]
        recs = {}
        while True:
            nn, lmax, typ = np.frombuffer(rec(), "<i4", 3)
            if nn == 0:
                break
            name = rec().decode().strip()
            dt = {1: "<i4", 2: "<f4", 3: "<f8"}[int(typ)]
            recs[name] = np.frombuffer(rec(), dt).reshape(nn, lmax).T
        out.append((dtime, recs))
    return out


def node_stats(rk, rg):
    """Per-node (top, bottom, column) ratios k-eps/GOTM, nan where undefined,
    plus the layer count and a wet mask."""
    vk, vg = rk["visv"], rg["visv"]
    nn = vk.shape[1]
    nlay = (rk["hdknv"] > 0).sum(axis=0)        # layers per node
    wet = (rk["hdknv"][0] > 0) & (rg["hdknv"][0] > 0)
    top = np.full(nn, np.nan)
    bot = np.full(nn, np.nan)
    col = np.full(nn, np.nan)
    for i in range(nn):
        if not wet[i] or nlay[i] < 2:
            continue
        ni = nlay[i] - 1                        # interior interfaces 1..nl-1
        a, b = vk[:ni, i].astype(float), vg[:ni, i].astype(float)
        if b[0] != 0:
            top[i] = a[0] / b[0]
        ok = np.nonzero((a != 0) & (b != 0))[0]
        if ok.size:
            k = ok[-1]
            bot[i] = a[k] / b[k]
        if b.mean() != 0:
            col[i] = a.mean() / b.mean()
    return top, bot, col, nlay, wet


def main(kfile, gfile):
    rk = read_dbg(kfile)[-1][1]
    rg = read_dbg(gfile)[-1][1]
    top, bot, col, nlay, wet = node_stats(rk, rg)
    for label, sel in (("all", wet), ("shallow (<=2 layers)", wet & (nlay <= 2))):
        print(f"{label}: {int(sel.sum())} wet nodes")
        for name, v in (("top", top), ("bottom", bot), ("column", col)):
            x = v[sel]
            x = x[np.isfinite(x)]
            med = np.median(x) if x.size else float("nan")
            print(f"  {name:<7} k-eps/GOTM median = {med:.3f}  (n={x.size})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
