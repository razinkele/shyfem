import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vprof import load, chi2
def summ(path, cat):
    rows = [x for x in load(path) if x[2] == cat and x[0] == 1 and x[3] > 0]
    late = [x for x in rows if x[1] >= 43200]
    if not late: return None
    def rel(sl):
        v = [sum(x[4][sl]) / (x[3] / 20.0 * len(x[4][sl])) for x in late]
        return sum(v) / len(v)
    end = rows[-1]
    return (sum(chi2(x[4]) for x in late) / len(late), chi2(end[4]), max(chi2(x[4]) for x in late),
            rel(slice(0, 3)), rel(slice(17, 20)), sum(x[3] for x in late) / len(late))
def counts(path):
    v = path.replace('.log', '.vdbg.txt'); c = {}
    for line in open(v):
        w = line.split()
        if w[0] == 'counts': c['nsteps'], c['ncalls'], c['ncross'] = int(w[1]), int(w[2]), int(w[3]); c['maxcall'] = int(w[12])
        if w[0] == 'nflip': c['nflip'] = int(w[1])
        if w[0] == 'wde' and w[1] == '2': c['kmean'] = float(w[3]); c['kmax'] = float(w[4])
    return c
cats = [int(c) for c in sys.argv[1].split(',')]
print("%-22s %4s %8s %7s %7s %6s %6s %7s %8s %6s %s" % ("run", "cat", "chi2_12-24", "end", "max", "top15", "bot15", "n", "calls/st", "maxc", "K mean/max later"))
for path in sys.argv[2:]:
    c = counts(path)
    for cat in cats:
        r = summ(path, cat)
        if r is None: continue
        print("%-22s %4d %8.1f %7.1f %7.1f %6.3f %6.3f %7.0f %8.2f %6d %.3g/%.3g %s" % (
            os.path.basename(path).replace('.log', ''), cat, r[0], r[1], r[2], r[3], r[4], r[5],
            c['ncalls'] / c['nsteps'], c['maxcall'], c.get('kmean', 0), c.get('kmax', 0),
            ("flip %d" % c['nflip']) if c.get('nflip') else ""))
