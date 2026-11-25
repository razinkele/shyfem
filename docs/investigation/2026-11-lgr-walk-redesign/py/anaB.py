# anaB.py LGRDIR FILE.lgr.shy GEOM.shy K OUT.json
# still-water ilagr = 3 run (measurement B):
#  - column depth H of an element: 2 x mean release hl (P8, wm.py), checked
#    against hev of the SHY header
#  - chi2 of the 20-bin relative-depth histogram, mean over 12:00 ... 24:00
#  - K_eff (P8's method, wm.py with nsig = 3): for each pair of consecutive
#    hourly outputs (t0, t1), dt = 3600 s, sigma = sqrt(2 K dt); particles with
#    depth at t0 >= 3 sigma and H - depth at t0 >= 3 sigma; K_hour =
#    sum(dz^2) / n / (2 dt) (mean square, NOT centred); K_eff = mean of the
#    23 K_hour; also the centred variance and the pooled estimate
#  - thickness of the layer each interior particle starts the hour in
import json, math, sys
from collections import Counter
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
sys.path.insert(0, __import__("os").path.dirname(__file__))
from shyhead import read_geom
path, gpath, K, outp = sys.argv[2], sys.argv[3], float(sys.argv[4]), sys.argv[5]
g = read_geom(gpath)
hlv = [float(v) for v in g["hlv"]]; hev = [float(v) for v in g["hev"]]; ilhv = [int(v) for v in g["ilhv"]]
def hd(ie, lb):
    lmax = ilhv[ie - 1]
    if lmax == 1: return hev[ie - 1]
    if lb == 1: return hlv[0]
    if lb == lmax: return hev[ie - 1] - hlv[lb - 2]
    return hlv[lb - 1] - hlv[lb - 2]
NB = 20
_, times = lc.read_file(path)
rel = {}
for t, b, _ in times: rel.update(b[-1])
acc = {}
for p in rel.values():
    a = acc.setdefault(p["ie"], [0.0, 0]); a[0] += p["hl"]; a[1] += 1
ht = {ie: 2.0 * a[0] / a[1] for ie, a in acc.items()}
dH = max(abs(ht[ie] - hev[ie - 1]) for ie in ht)
nmove = nout = nlost = 0
def hist(parts):
    global nout
    h = [0] * NB
    for p in parts.values():
        r = p["hl"] / ht[p["ie"]]
        if r < -1e-5 or r > 1 + 1e-5: nout += 1
        h[min(max(int(r * NB), 0), NB - 1)] += 1
    return h
def chi2(h):
    e = sum(h) / float(NB); return sum((x - e) ** 2 / e for x in h)
c0 = chi2(hist(rel))
rows = []
for t, b, _ in times:
    if len(b[0]) != len(rel) or b[1]: nlost += 1
    for pid, p in b[0].items():
        r = rel[pid]
        if (p["x"], p["y"], p["ie"]) != (r["x"], r["y"], r["ie"]): nmove += 1
    h = hist(b[0]); rows.append((t, chi2(h), h))
late = [r for r in rows if 43200 <= r[0] <= 86400]
mchi = sum(r[1] for r in late) / len(late)
top = sum(sum(h[0:3]) / (3.0 * sum(h) / NB) for _, _, h in late) / len(late)
bot = sum(sum(h[17:20]) / (3.0 * sum(h) / NB) for _, _, h in late) / len(late)
# K_eff
ks = []; lay = Counter(); pooled = [0.0, 0]; elems = set()
prev = None
for t, b, _ in times:
    if prev is not None and b[0]:
        dt = t - prev[0]; s = math.sqrt(2 * K * dt)
        sq = sm = 0.0; n = 0
        for pid, p in b[0].items():
            q = prev[1].get(pid)
            if q is None: continue
            H = ht[p["ie"]]
            if q["hl"] < 3 * s or H - q["hl"] < 3 * s: continue
            d = p["hl"] - q["hl"]; sq += d * d; sm += d; n += 1
            lay[round(hd(q["ie"], q["lb"]), 2)] += 1; elems.add(q["ie"])
        if n > 1:
            mean = sm / n
            ks.append({"t": t, "n": n, "k": sq / n / (2 * dt) / K,
                       "kc": (sq - n * mean * mean) / (n - 1) / (2 * dt) / K, "mean": mean})
            pooled[0] += sq / (2 * dt) / K; pooled[1] += n
    prev = (t, b[0])
v = [x["k"] for x in ks]; m = sum(v) / len(v)
sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else float("nan")
vc = [x["kc"] for x in ks]; mc = sum(vc) / len(vc)
ntot = sum(lay.values())
out = {"file": path, "K": K, "nrel": len(rel), "chi2_late": mchi, "top15": top, "bot15": bot,
       "rows": [(r[0], r[1], r[2]) for r in rows], "kes": ks, "keff": m, "keff_se": sd / math.sqrt(len(v)),
       "keff_centred": mc, "keff_pooled": pooled[0] / pooled[1], "n_mean": pooled[1] / len(ks),
       "layers": {str(k): c / ntot for k, c in sorted(lay.items())}, "n_elems": len(elems)}
json.dump(out, open(outp, "w"))
print("%s: released %d; H(2 x mean release hl) vs hev max |diff| %.2e m; moved %d, out of column %d, outputs with lost/exited %d; release chi2 %.3f"
      % (path.split("/")[-1], len(rel), dH, nmove, nout, nlost, c0))
print("  chi2 12-24 %.1f  top15 %.3f bot15 %.3f" % (mchi, top, bot))
print("  K_eff/K (P8: mean of %d hourly mean-square estimates, 3 sigma = %.2f m) %.3f +- %.3f (SE); centred %.3f; pooled %.3f; mean n per hour %.0f in %d elements; hourly range %.3f ... %.3f"
      % (len(ks), 3 * math.sqrt(2 * K * 3600), m, out["keff_se"], mc, out["keff_pooled"], out["n_mean"], len(elems), min(v), max(v)))
print("  start layer thickness of the interior particles (fraction): " + ", ".join("%s m %.3f" % (k, c / ntot) for k, c in sorted(lay.items()) if c / ntot >= 0.005))
