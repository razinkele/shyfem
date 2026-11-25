# bydepth.py LGRDIR FILE.lgr.shy GEOM.shy: relative-depth histogram (20 bins)
# of a no-advection run by class of column depth (hev), hours 12-24:
# n, top 5 % / top 15 % / bottom 15 % relative density, chi2 of the class,
# and the class chi2 excess scaled to the whole release ((chi2-19) N/n + 19:
# the chi2 the whole release would give if every column behaved like it)
import math, sys
sys.path.insert(0, sys.argv[1])
import lgr_compare as lc
sys.path.insert(0, __import__("os").path.dirname(__file__))
from shyhead import read_geom
g = read_geom(sys.argv[3]); hev = [float(v) for v in g["hev"]]
_, times = lc.read_file(sys.argv[2])
rel = {}
for t, b, _ in times: rel.update(b[-1])
acc = {}
for p in rel.values():
    a = acc.setdefault(p["ie"], [0.0, 0]); a[0] += p["hl"]; a[1] += 1
ht = {ie: 2.0 * a[0] / a[1] for ie, a in acc.items()}
hlv = [float(v) for v in g["hlv"]]; ilhv = [int(v) for v in g["ilhv"]]
def hd(ie, lb):
    lmax = ilhv[ie - 1]
    if lb == lmax: return hev[ie - 1] - hlv[lb - 2]
    return hlv[lb - 1] - hlv[lb - 2]
def sdepth(p):
    # relative depth in the current column (zeta recovered from the record,
    # z-levels as M286): s = hl / (hev + zeta)
    ie, lb, z, h = p["ie"], p["lb"], p["z"], p["hl"]
    if ilhv[ie - 1] == 1: return z
    if lb == 1:
        if z <= 0.0: return 0.0
        zeta = h / z - hlv[0]
    else:
        zeta = h - hlv[lb - 2] - z * hd(ie, lb)
    return h / (hev[ie - 1] + zeta)
cls = [(0, 1.25), (1.25, 2.5), (2.5, 4), (4, 7), (7, 20), (20, 50), (50, 200)]
NB = 20
def chi2(h):
    n = sum(h); e = n / float(NB)
    return sum((x - e) ** 2 / e for x in h) if e > 0 else 0.0
res = {c: [] for c in cls}; tot = []
for t, b, _ in times:
    if not (43200 <= t <= 86400): continue
    hs = {c: [0] * NB for c in cls}; hall = [0] * NB
    for p in b[0].values():
        r = sdepth(p)
        k = min(max(int(r * NB), 0), NB - 1)
        hall[k] += 1
        for c in cls:
            if c[0] <= hev[p["ie"] - 1] < c[1]: hs[c][k] += 1; break
    tot.append(hall)
    for c in cls: res[c].append(hs[c])
N = sum(tot[0])
print("all: n %d chi2 %.1f" % (N, sum(chi2(h) for h in tot) / len(tot)))
for c in cls:
    hl = res[c]; n = sum(hl[0])
    if n == 0: continue
    e = n / float(NB)
    c2 = sum(chi2(h) for h in hl) / len(hl)
    top5 = sum(h[0] for h in hl) / len(hl) / e
    top15 = sum(sum(h[0:3]) for h in hl) / len(hl) / (3 * e)
    bot15 = sum(sum(h[17:20]) for h in hl) / len(hl) / (3 * e)
    print("H %5.2f-%5.1f m: n %5d (%4.1f%%) chi2 %6.1f scaled %7.1f  top5 %.3f top15 %.3f bot15 %.3f" % (c[0], c[1], n, 100.0 * n / N, c2, (c2 - 19) * N / n + 19, top5, top15, bot15))
