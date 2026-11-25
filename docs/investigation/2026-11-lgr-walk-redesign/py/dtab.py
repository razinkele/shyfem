# dtab.py RES RUNS NAME...: D's table (closed forced mm_hyd_41, GOTM, 39,960
# particles) from anaA.py's json (release-column weight 'rel', as M299) and
# the walk calls per particle step from RUNS/NAME/NAME.vdbg.txt
import json, os, sys

res, runs = sys.argv[1], sys.argv[2]
print("| run | chi2 12-24 h | chi2 at 24 h | bottom 5 % at 24 h | bottom 15 % at 24 h | bottom 5 % 12-24 h | bottom 15 % 12-24 h | top 5 % at 24 h | top 5 % 12-24 h | calls per step | user s |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for n in sys.argv[3:]:
    p = os.path.join(res, n + ".json")
    if not os.path.exists(p):
        print("| %s | missing |" % n)
        continue
    j = json.load(open(p))
    s = j["summary"]["rel"]
    e = j["rows"][-1]["rel"]["v"]
    calls = float('nan')
    vd = os.path.join(runs, n, n + ".vdbg.txt")
    if os.path.exists(vd):
        for line in open(vd):
            w = line.split()
            if w and w[0] == 'counts':
                calls = int(w[2]) / max(1, int(w[1]))
    user = "?"
    tf = os.path.join(runs, n, n + ".time")
    if os.path.exists(tf):
        tm = open(tf).read().split()
        if "user" in tm:
            user = tm[tm.index("user") + 1]
    print("| %s | %.1f | %.0f | %.2f | %.2f | %.3f | %.3f | %.2f | %.3f | %.2f | %s |" % (
        n, s["chi2"], s["chi2_end"], e[19], sum(e[17:20]) / 3, s["bot5"], s["bot15"],
        e[0], s["top5"], calls, user))
