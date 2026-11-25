# cells.py RUNS SETTING...: table of settings x tests x seeds from the in-model
# vprof lines (P7: tag 1, cat 1 = all columns, mean over hours 12-24) of the
# runs RUNS/{test}_{setting}_s{seed} (test g = GOTM, p1 = linear, p2 =
# parabolic, all without advection), with the pass rule of res/pass_rule.txt:
# all seeds < 31 and worst + (max - min) <= 31; also the top 5 % bin (mean
# relative density, hours 12-24) and the walk calls per particle step
import os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vprof import load, chi2

LIM = 31.0
TESTS = (("p1", "linear"), ("p2", "parabolic"), ("g", "GOTM no adv"))


def one(d):
    n = os.path.basename(d.rstrip('/'))
    log = os.path.join(d, n + ".log")
    if not os.path.exists(log):
        return None
    r = [x for x in load(log) if x[2] == 1 and x[0] == 1 and x[3] > 0]
    late = [x for x in r if x[1] >= 43200]
    if len(late) != 13:
        return None
    c2 = sum(chi2(x[4]) for x in late) / len(late)
    top5 = sum(x[4][0] / (x[3] / 20.0) for x in late) / len(late)
    calls = float('nan')
    vd = os.path.join(d, n + ".vdbg.txt")
    if os.path.exists(vd):
        for line in open(vd):
            w = line.split()
            if w and w[0] == 'counts':
                calls = int(w[2]) / max(1, int(w[1]))
    user = float('nan')
    tf = os.path.join(d, n + ".time")
    if os.path.exists(tf):
        tm = open(tf).read().split()
        if "user" in tm:
            user = float(tm[tm.index("user") + 1])
    return c2, top5, calls, user


runs = sys.argv[1]
sets = sys.argv[2:]
cells = {}
for s in sets:
    for t, _ in TESTS:
        v = [one(os.path.join(runs, "%s_%s_s%d" % (t, s, k))) for k in (1, 2, 3)]
        cells[(s, t)] = v
sd = {}
for t, _ in TESTS:
    sds = [statistics.stdev([x[0] for x in cells[(s, t)]]) for s in sets
           if all(x is not None for x in cells[(s, t)])]
    sd[t] = (sum(x * x for x in sds) / len(sds)) ** 0.5 if sds else float('nan')
print("pooled seed SD per test: " + ", ".join("%s %.2f" % (t, sd[t]) for t, _ in TESTS))
print("| setting | test | chi2 s1 / s2 / s3 | worst | spread | worst + spread | verdict | worst + pooled SD | top 5 %% s1 / s2 / s3 | calls per step |")
print("|---|---|---|---|---|---|---|---|---|---|")
for s in sets:
    for t, lab in TESTS:
        v = cells[(s, t)]
        if any(x is None for x in v):
            have = " / ".join("%.1f" % x[0] if x else "-" for x in v)
            print("| %s | %s | %s | | | | incomplete | | | |" % (s, lab, have))
            continue
        c = [x[0] for x in v]
        w = max(c); sp = w - min(c)
        ok = w < LIM and w + sp <= LIM
        okp = w + sd[t] <= LIM
        print("| %s | %s | %s | %.1f | %.1f | %.1f | %s | %.1f (%s) | %s | %.2f |" % (
            s, lab, " / ".join("%.1f" % x for x in c), w, sp, w + sp,
            "pass" if ok else "FAIL", w + sd[t], "pass" if okp else "fail",
            " / ".join("%.3f" % x[1] for x in v), v[0][2]))
