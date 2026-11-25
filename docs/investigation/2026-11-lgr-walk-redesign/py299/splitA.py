# splitA.py LGRDIR FILE.lgr.shy GEOM.shy: release-column-weighted relative-depth
# density, mean over 12 ... 24 h, split by the depth of the particle's current
# column (zeta recovered from the record as in anaA.py)
import sys, os
from collections import defaultdict
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
sys.path.insert(0, os.path.dirname(__file__))
from shyhead import read_geom
g = read_geom(sys.argv[3])
hlv = [float(v) for v in g["hlv"]]; hev = [float(v) for v in g["hev"]]; ilhv = [int(v) for v in g["ilhv"]]
_, times = lc.read_file(sys.argv[2])
rel = {}
for t, b, _ in times: rel.update(b[-1])
CL = ((0, 3), (3, 7), (7, 20), (20, 1e9))
NB = 20
def zeta_of(p):
    ie = p["ie"]; lb = p["lb"]; z = p["z"]; hl = p["hl"]; lmax = ilhv[ie - 1]; H = hev[ie - 1]
    if lb >= 2:
        hd = (H - hlv[lb - 2]) if lb == lmax else (hlv[lb - 1] - hlv[lb - 2])
        return hl - hlv[lb - 2] - z * hd
    if z < 0.05: return None
    return hl / z - (H if lmax == 1 else hlv[0])
acc = {c: [0.0] * NB for c in CL}; nl = 0; wsum = {c: 0.0 for c in CL}
for t, b, _ in times:
    if not (43200 <= t <= 86400): continue
    nl += 1
    parts = b[0]
    zs = {pid: zeta_of(p) for pid, p in parts.items()}
    ze = defaultdict(list)
    for pid, p in parts.items():
        if zs[pid] is not None: ze[p["ie"]].append(zs[pid])
    zmed = {ie: sorted(v)[len(v) // 2] for ie, v in ze.items()}
    h = {c: [0.0] * NB for c in CL}
    for pid, p in parts.items():
        zz = zs[pid] if zs[pid] is not None else zmed.get(p["ie"], 0.0)
        ht = hev[p["ie"] - 1] + zz
        k = min(max(int(p["hl"] / ht * NB), 0), NB - 1)
        w = hev[rel[pid]["ie"] - 1]
        for c in CL:
            if c[0] <= hev[p["ie"] - 1] < c[1]:
                h[c][k] += w
    for c in CL:
        s = sum(h[c])
        wsum[c] += s
        for k in range(NB):
            acc[c][k] += h[c][k] / (s / NB) if s > 0 else 0.0
tot = sum(wsum.values())
print(sys.argv[2].split("/")[-1])
for c in CL:
    v = [x / nl for x in acc[c]]
    print("  current column %5.0f-%-5.0f m (weight %.1f %%): top5 %.3f top15 %.3f bot15 %.3f bot5 %.3f | %s" % (
        c[0], min(c[1], 99), 100 * wsum[c] / tot, v[0], sum(v[0:3]) / 3, sum(v[17:20]) / 3, v[19],
        " ".join("%.2f" % x for x in v)))
