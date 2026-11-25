# tfit.py S: cost analysis of the timing runs (timing.sh).
# Reads res/timing_r.txt (reproducer, runs tr_CFG_I) and res/timing_h.txt
# (particle-heavy, runs th_CFG_I), the walk calls of each run from its
# lgr_vdbg counts, discards runs with load > 8 at start or end, and gives:
# - median user time and calls per particle step per configuration;
# - reproducer per-call fits: joint least squares with one intercept and
#   one slope per walk (N2 family: N2, A1, B07, A3; S family: S, Sdt5, Sdt2),
#   and each family's own line;
# - heavy case: in-situ N2 slope from N2 and B07, S per call from the
#   intercept; walk-only ratios with in-situ and with reproducer costs.
import os, re, statistics, sys
import numpy as np

S = sys.argv[1]
LOADMAX = 8.0


def read(tf, prefix):
    rows = []
    for line in open(tf):
        m = re.match(r"(%s_(\w+?)_(\d)) rc=(\d+) end=(\d+) wall ([\d.]+) s user ([\d.]+) s maxrss \d+ kB load ([\d.]+) ([\d.]+)" % prefix, line)
        if not m:
            continue
        n, cfg, i = m.group(1), m.group(2), int(m.group(3))
        rc, end, user = int(m.group(4)), int(m.group(5)), float(m.group(7))
        l0, l1 = float(m.group(8)), float(m.group(9))
        nst = ncl = None
        vd = os.path.join(S, "runs", n, n + ".vdbg.txt")
        for l in open(vd):
            w = l.split()
            if w and w[0] == "counts":
                nst, ncl = int(w[1]), int(w[2])
        rows.append(dict(n=n, cfg=cfg, i=i, ok=(rc == 0 and end == 1), user=user,
                         l0=l0, l1=l1, nst=nst, ncl=ncl))
    return rows


def table(rows, title):
    print("## " + title)
    print("| config | user s (rounds 1 / 2 / 3) | load start-end | median user s | calls per step | discarded |")
    print("|---|---|---|---|---|---|")
    med = {}
    for cfg in dict.fromkeys(r["cfg"] for r in rows):
        rr = sorted([r for r in rows if r["cfg"] == cfg], key=lambda r: r["i"])
        good = [r for r in rr if r["ok"] and max(r["l0"], r["l1"]) <= LOADMAX]
        m = statistics.median([r["user"] for r in good]) if good else float("nan")
        cps = rr[0]["ncl"] / rr[0]["nst"]
        med[cfg] = (m, cps, rr[0]["ncl"], rr[0]["nst"])
        print("| %s | %s | %s | %.2f | %.2f | %d |" % (
            cfg, " / ".join("%.2f" % r["user"] for r in rr),
            " ; ".join("%.1f-%.1f" % (r["l0"], r["l1"]) for r in rr), m, cps,
            len(rr) - len(good)))
    return med


NFAM = ("N2", "A1", "B07", "A3")
SFAM = ("S", "Sdt5", "Sdt2")

r = read(os.path.join(S, "res", "timing_r.txt"), "tr")
mr = table(r, "reproducer (2914 particles, GOTM, advection)")
good = [x for x in r if x["ok"] and max(x["l0"], x["l1"]) <= LOADMAX]
# joint fit: user = a + bN * calls (N2 family) or a + bS * calls (S family)
A = []; y = []
for x in good:
    c = x["ncl"] / 1e6
    A.append([1.0, c if x["cfg"] in NFAM else 0.0, c if x["cfg"] in SFAM else 0.0])
    y.append(x["user"])
A = np.array(A); y = np.array(y)
coef, res, rk, sv = np.linalg.lstsq(A, y, rcond=None)
pred = A @ coef
rms = float(np.sqrt(np.mean((y - pred) ** 2)))
a, bN, bS = coef
print("\njoint fit (%d runs): fixed %.2f s, N2 %.4f us per call, S %.4f us per call, rms residual %.2f s" % (len(y), a, bN, bS, rms))
for fam, name in ((NFAM, "N2"), (SFAM, "S")):
    xs = [x for x in good if x["cfg"] in fam]
    X = np.array([[1.0, x["ncl"] / 1e6] for x in xs]); Y = np.array([x["user"] for x in xs])
    cf = np.linalg.lstsq(X, Y, rcond=None)[0]
    rm = float(np.sqrt(np.mean((Y - X @ cf) ** 2)))
    print("own line %s (%d runs): fixed %.2f s, %.4f us per call, rms %.2f s" % (name, len(xs), cf[0], cf[1], rm))
cS = mr["S"][1]
print("\nreproducer ratios against S (whole run = median user / median user of S; walk-only fit = calls per step x joint-fit us per call):")
for cfg in NFAM:
    whole = mr[cfg][0] / mr["S"][0]
    walk = mr[cfg][1] * bN / (cS * bS)
    print("  %-4s whole %.3f  walk-only (fit) %.3f  (calls per step %.2f against S %.2f)" % (cfg, whole, walk, mr[cfg][1], cS))
if "K" in mr:
    fx = mr["K"][0]
    print("fixed part (N2 at constant K, %.2f calls per step): median %.2f s" % (mr["K"][1], fx))
    for cfg in NFAM + SFAM[1:]:
        print("  %-4s walk-only (user - fixed) / (S - fixed) = (%.2f - %.2f) / (%.2f - %.2f) = %.3f;"
              " us per call %.4f (S %.4f)" % (cfg, mr[cfg][0], fx, mr["S"][0], fx,
              (mr[cfg][0] - fx) / (mr["S"][0] - fx), (mr[cfg][0] - fx) / (mr[cfg][2] / 1e6),
              (mr["S"][0] - fx) / (mr["S"][2] / 1e6)))
    fxc = fx - mr["K"][2] / 1e6 * bN
    print("  with the constant-K run's own walk calls removed (%.1f M calls x joint-fit N2 cost): fixed %.2f s" % (mr["K"][2] / 1e6, fxc))
    for cfg in NFAM + SFAM[1:]:
        print("  %-4s walk-only corrected %.3f" % (cfg, (mr[cfg][0] - fxc) / (mr["S"][0] - fxc)))

hf = os.path.join(S, "res", "timing_h.txt")
if os.path.exists(hf):
    h = read(hf, "th")
    mh = table(h, "\nparticle-heavy (39,960 particles, GOTM, no advection, seed 1)")
    if all(k in mh and mh[k][0] == mh[k][0] for k in ("S", "N2", "B07")):
        uN, cpN, nN, _ = mh["N2"]; uB, cpB, nB, _ = mh["B07"]; uS, cpS, nS, _ = mh["S"]
        bNh = (uB - uN) / ((nB - nN) / 1e6)
        ah = uN - bNh * nN / 1e6
        bSh = (uS - ah) / (nS / 1e6)
        print("\nin-situ: N2 %.4f us per call (N2 to B07), fixed %.1f s, S %.4f us per call" % (bNh, ah, bSh))
        print("heavy whole-run ratio B07 / S %.3f; N2 / S %.3f" % (uB / uS, uN / uS))
        print("heavy walk-only B07 / S: in-situ costs %.3f; reproducer joint-fit costs %.3f" % (
            cpB * bNh / (cpS * bSh), cpB * bN / (cpS * bS)))
        if "K" in mh and mh["K"][0] == mh["K"][0]:
            fx = mh["K"][0]
            print("heavy fixed part (N2 at constant K, %.2f calls per step): median %.2f s" % (mh["K"][1], fx))
            for cfg in ("N2", "B07"):
                print("  %-4s walk-only (user - fixed) / (S - fixed) = (%.2f - %.2f) / (%.2f - %.2f) = %.3f;"
                      " us per call %.4f (S %.4f)" % (cfg, mh[cfg][0], fx, uS, fx,
                      (mh[cfg][0] - fx) / (uS - fx), (mh[cfg][0] - fx) / (mh[cfg][2] / 1e6),
                      (uS - fx) / (nS / 1e6)))
            fxc = fx - mh["K"][2] / 1e6 * bNh
            print("  with the constant-K run's own walk calls removed (%.1f M calls x in-situ N2 cost): fixed %.2f s" % (mh["K"][2] / 1e6, fxc))
            for cfg in ("N2", "B07"):
                print("  %-4s walk-only corrected %.3f" % (cfg, (mh[cfg][0] - fxc) / (uS - fxc)))
