# vbins.py CAT RUNDIR...: mean relative density per 5 % bin (surface -> bottom)
# over hours 12-24 of the in-model vprof lines, and the hourly chi2
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vprof import load, chi2
cat = int(sys.argv[1])
for d in sys.argv[2:]:
    n = os.path.basename(d.rstrip('/'))
    r = [x for x in load(os.path.join(d, n + ".log")) if x[2] == cat and x[0] == 1 and x[3] > 0]
    late = [x for x in r if x[1] >= 43200]
    if not late: continue
    m = [sum(x[4][b] / (x[3] / 20.0) for x in late) / len(late) for b in range(20)]
    print("%-18s %s" % (n, " ".join("%.2f" % v for v in m)))
    print("%-18s chi2 by hour: %s" % ("", " ".join("%.0f" % chi2(x[4]) for x in r)))
