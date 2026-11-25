# anaA.py LGRDIR FILE.lgr.shy GEOM.shy OUT.json
# weighted relative-depth histograms of a forced ilagr = 3 run (measurement A)
#   relative depth s = hl / (hev(ie) + zeta) in the particle's CURRENT column at
#   the output time; zeta of the column recovered from the particle's own
#   record (lb, z, hl) and the static z-levels (get_layer_thickness):
#     lb >= 2: hl = zeta + hlv(lb-1) + z*hd(lb), hd(lb) static
#     lb == 1: hl = z*(hlv(1) + zeta)  (lmax > 1),  z*(hev + zeta) (lmax = 1)
#   (for lb == 1 with z < 0.05 the median zeta of the element at that output,
#   else 0)
#   weights: 'rel'  depth of the release column at the release, hev(ie0)
#                   (zeta = 0 at the cold start): the volume the particle stands
#                   for, a Lagrangian invariant
#            'p7'   depth of the release column now, hev(ie0) + zeta(ie0, t), as
#                   P7's hook lgr_dbg_vprofw (zeta from the particles in ie0 at
#                   t, the mean zeta of all elements if none)
#            'cur'  depth of the particle's current column, hev(ie) + zeta
#            'one'  unweighted
#   chi2 = sum_k (v_k e - e)^2 / e, v_k = W_k / (W / 20), e = n_eff / 20,
#   n_eff = W^2 / sum w^2  (P7's vprofw.py)
import json, math, sys
from collections import defaultdict
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
sys.path.insert(0, __import__("os").path.dirname(__file__))
from shyhead import read_geom

path, gpath, outp = sys.argv[2], sys.argv[3], sys.argv[4]
g = read_geom(gpath)
hlv = [float(v) for v in g["hlv"]]
hev = [float(v) for v in g["hev"]]
ilhv = [int(v) for v in g["ilhv"]]
NB = 20
_, times = lc.read_file(path)
rel = {}
for t, b, _ in times:
    rel.update(b[-1])
WK = ("rel", "p7", "cur", "one")

def zeta_of(p):
    ie = p["ie"]; lb = p["lb"]; z = p["z"]; hl = p["hl"]
    lmax = ilhv[ie - 1]; H = hev[ie - 1]
    if lb >= 2:
        hd = (H - hlv[lb - 2]) if lb == lmax else (hlv[lb - 1] - hlv[lb - 2])
        return hl - hlv[lb - 2] - z * hd
    if z < 0.05:
        return None
    return hl / z - (H if lmax == 1 else hlv[0])

def analyse(parts, t):
    zs = {}
    ze = defaultdict(list)
    for pid, p in parts.items():
        zz = zeta_of(p)
        zs[pid] = zz
        if zz is not None:
            ze[p["ie"]].append(zz)
    zmed = {}
    spread = 0.0
    for ie, v in ze.items():
        v.sort()
        zmed[ie] = v[len(v) // 2]
        spread = max(spread, v[-1] - v[0])
    zall = sum(zmed.values()) / len(zmed) if zmed else 0.0
    H = {k: [0.0] * NB for k in WK}
    sw = dict.fromkeys(WK, 0.0); sw2 = dict.fromkeys(WK, 0.0)
    nout = nfall = 0
    for pid, p in parts.items():
        ie = p["ie"]
        zz = zs[pid]
        if zz is None:
            zz = zmed.get(ie, 0.0); nfall += 1
        ht = hev[ie - 1] + zz
        s = p["hl"] / ht
        if s < -1.e-5 or s > 1.0 + 1.e-5:
            nout += 1
        k = min(max(int(s * NB), 0), NB - 1)
        ie0 = rel[pid]["ie"]
        w = {"rel": hev[ie0 - 1], "p7": hev[ie0 - 1] + zmed.get(ie0, zall),
             "cur": ht, "one": 1.0}
        for key in WK:
            H[key][k] += w[key]; sw[key] += w[key]; sw2[key] += w[key] ** 2
    res = {"t": t, "n": len(parts), "nout": nout, "nfall": nfall,
           "zspread": spread, "zmean": zall}
    for key in WK:
        neff = sw[key] ** 2 / sw2[key]
        v = [x / (sw[key] / NB) for x in H[key]]
        e = neff / NB
        res[key] = {"neff": neff, "v": v,
                    "chi2": sum((x * e - e) ** 2 / e for x in v)}
    return res

out = {"file": path, "nrel": len(rel), "rows": []}
r0 = analyse(rel, -1.0)
out["release"] = r0
print("%s: %d released; release: chi2 rel %.3f one %.3f, n_eff rel %.1f, s out of [0,1] %d, zeta spread in an element %.2e"
      % (path.split("/")[-1], len(rel), r0["rel"]["chi2"], r0["one"]["chi2"], r0["rel"]["neff"], r0["nout"], r0["zspread"]))
for t, b, _ in times:
    r = analyse(b[0], t)
    r["nexit"] = len(b[1])
    out["rows"].append(r)
late = [r for r in out["rows"] if 43200.0 <= r["t"] <= 86400.0]
end = out["rows"][-1]
print("outputs %d (t %.0f ... %.0f); late outputs %d; active at end %d, exited at end %d; s out of [0,1] (all outputs) %d; lb=1 fallbacks %d; max zeta spread in an element %.2e; zeta mean at end %.4f m"
      % (len(out["rows"]), out["rows"][0]["t"], end["t"], len(late), end["n"], end["nexit"],
         sum(r["nout"] for r in out["rows"]), sum(r["nfall"] for r in out["rows"]),
         max(r["zspread"] for r in out["rows"]), end["zmean"]))
summ = {}
for key in WK:
    m = lambda f: sum(f(r[key]) for r in late) / len(late)
    s = {"chi2": m(lambda x: x["chi2"]), "top5": m(lambda x: x["v"][0]),
         "top15": m(lambda x: sum(x["v"][0:3]) / 3), "bot5": m(lambda x: x["v"][19]),
         "bot15": m(lambda x: sum(x["v"][17:20]) / 3), "neff_end": end[key]["neff"],
         "chi2_end": end[key]["chi2"], "bot5_end": end[key]["v"][19]}
    summ[key] = s
    print("  %-4s chi2 12-24 %7.1f  top5 %.3f top15 %.3f bot15 %.3f bot5 %.3f | end: chi2 %6.1f bot5 %.2f n_eff %.0f"
          % (key, s["chi2"], s["top5"], s["top15"], s["bot15"], s["bot5"], s["chi2_end"], s["bot5_end"], s["neff_end"]))
    print("       end rel. density: " + " ".join("%.2f" % x for x in end[key]["v"]))
out["summary"] = summ
json.dump(out, open(outp, "w"))
