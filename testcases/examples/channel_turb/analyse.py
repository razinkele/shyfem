#!/usr/bin/env python3
"""Compare each run's eddy viscosity at mid-channel with the analytical
neutral open-channel profile  nu_t = kappa u* z (1 - z/H)  (z above bed).

u* comes from the measured surface slope (steady uniform flow:
u*^2 = g H S), independent of either closure and of the friction law.
Reads the -debout *.dbg files (shympi_write_debug_* record layout).
"""
import sys
from pathlib import Path

import numpy as np

KAPPA, G = 0.4, 9.81
PI_COLES = 0.2   # Coles' wake parameter of open-channel experiments (Absi 2021)
NX, NY, DX = 81, 5, 250.0
MID = 2 * NX + NX // 2  # 0-based index of centreline node at x = 10 km (node 203)


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


def profile(path):
    steps = read_dbg(path)
    _, r = steps[-1]
    _, r_prev = steps[-2]
    nl = r["visv"].shape[0]                  # interfaces 1..nl (bottom of each layer)
    z = r["znv"][0]                          # water level per node
    xs = np.arange(NX) * DX
    row = z[2 * NX : 3 * NX]
    sel = slice(20, 61)                      # interior, away from the open ends
    S = -np.polyfit(xs[sel], row[sel], 1)[0]
    H = 10.0 + z[MID]
    ustar = np.sqrt(G * H * S)
    dz = H / nl
    zb = H - dz * np.arange(1, nl + 1)       # height above bed of interfaces 1..nl
    nut = r["visv"][:, MID]
    u = np.hypot(r["uprv"][:, MID], r["vprv"][:, MID])   # layer-centre speed
    drift = np.max(np.abs(nut - r_prev["visv"][:, MID])) / np.max(nut)
    ana = KAPPA * ustar * zb * (1 - zb / H)
    # log-wake-modified profile: the parabola corrected by Coles' wake term
    wake = ana / (1 + np.pi * PI_COLES * (zb / H) * np.sin(np.pi * zb / H))
    # velocity-derived nu_t at the inner interfaces: stress u*^2 (1 - z/H) over shear
    shear = (u[:-1] - u[1:]) / dz
    nut_u = ustar**2 * (1 - zb[:-1] / H) / np.where(shear > 0, shear, np.nan)
    return dict(nl=nl, H=H, S=S, ustar=ustar, U=u.mean(), zb=zb, nut=nut, ana=ana, wake=wake,
                nut_u=nut_u, drift=drift, u=u)


# arguments: run names (each read at 20 and 40 layers) or explicit "stem:nl" pairs
runs = sys.argv[1:] or ["keps", "gotm_gen", "gotm_ke1", "gotm_ke2"]
print(f"{'run':<12}{'nl':>4}{'U m/s':>8}{'u* cm/s':>9}{'drift':>8}"
      f"{'max nut/ana':>13}{'mean nut/ana':>14}{'nut(zb<0.2H)/ana':>18}{'mean/logwake':>14}{'nut/nut_from_u':>16}")
results = {}
pairs = []
for run in runs:
    if ":" in run:
        stem, nl = run.split(":")
        pairs.append((stem, int(nl)))
    else:
        pairs += [(run, 20), (run, 40)]
for run, nl in pairs:
        stem = run if ":" in str(run) or run.endswith(f"_{nl}") or "_d" in run else f"{run}_{nl}"
        p = profile(f"{stem}.dbg")
        results[(run, nl)] = p
        inner = p["zb"] > 0
        lower = (p["zb"] > 0) & (p["zb"] < 0.2 * p["H"])
        ratio_u = np.nanmedian(p["nut"][:-1][inner[:-1]] / p["nut_u"][inner[:-1]])
        print(f"{run:<12}{nl:>4}{p['U']:>8.3f}{100 * p['ustar']:>9.2f}{p['drift']:>8.1e}"
              f"{p['nut'].max() / p['ana'].max():>13.2f}"
              f"{p['nut'][inner].mean() / p['ana'][inner].mean():>14.2f}"
              f"{p['nut'][lower].mean() / p['ana'][lower].mean():>18.2f}"
              f"{p['nut'][inner].mean() / p['wake'][inner].mean():>14.2f}{ratio_u:>16.2f}")

np.save("profiles.npy", {f"{k[0]}_{k[1]}": v for k, v in results.items()}, allow_pickle=True)
