# vsum.py RUNDIR...: chi2 of the in-model vprof lines (P7's summ.py logic:
# tag 1, hours 12-24, cat 1 all and cat 3 lmax >= 5), counts of lgr_vdbg.txt,
# stats line, user time
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vprof import load, chi2
def summ(rows, cat):
    r = [x for x in rows if x[2] == cat and x[0] == 1 and x[3] > 0]
    late = [x for x in r if x[1] >= 43200]
    if not late: return None
    def rel(sl):
        v = [sum(x[4][sl]) / (x[3] / 20.0 * len(x[4][sl])) for x in late]
        return sum(v) / len(v)
    return (sum(chi2(x[4]) for x in late) / len(late), rel(slice(0, 3)), rel(slice(17, 20)), len(late), sum(x[3] for x in late) / len(late))
print("%-24s %8s %8s %6s %6s %5s %8s %6s %6s %9s %6s %7s %s" % ("run", "chi2all", "chi2deep", "top15", "bot15", "nout", "calls/st", "maxc", "ncap", "tlost", "substp", "user", "env"))
for d in sys.argv[1:]:
    n = os.path.basename(d.rstrip('/'))
    log = os.path.join(d, n + ".log")
    rows = load(log)
    a = summ(rows, 1); b = summ(rows, 3)
    c = {}
    vd = os.path.join(d, n + ".vdbg.txt")
    if os.path.exists(vd):
        for line in open(vd):
            w = line.split()
            if w and w[0] == 'counts':
                c = dict(nsteps=int(w[1]), ncalls=int(w[2]), ncap=int(w[4]), tlost=float(w[5]), maxcall=int(w[12]))
    sub = ""
    for line in open(log, errors='replace'):
        m = re.search(r"sub-steps per step ([0-9.]+)", line)
        if m: sub = m.group(1)
    tm = open(os.path.join(d, n + ".time")).read().split()
    user = tm[tm.index("user") + 1] if "user" in tm else "?"
    env = open(os.path.join(d, n + ".env")).read().strip().replace("LGR_DBG_", "")
    if a is None:
        print("%-24s no vprof rows" % n); continue
    print("%-24s %8.1f %8.1f %6.3f %6.3f %5d %8.2f %6d %6d %9.1f %6s %7s %s" % (
        n, a[0], b[0] if b else float('nan'), a[1], a[2], a[3], c.get('ncalls', 0) / max(1, c.get('nsteps', 1)),
        c.get('maxcall', -1), c.get('ncap', -1), c.get('tlost', -1), sub, user, env))
