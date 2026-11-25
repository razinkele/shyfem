import json, sys
print("| run | chi2 12-24 h | bottom 5 % 12-24 h | bottom 15 % 12-24 h | bottom 5 % at 24 h | bottom 15 % at 24 h | chi2 at 24 h |")
for p in sys.argv[1:]:
    j = json.load(open(p)); s = j["summary"]["rel"]; e = j["rows"][-1]["rel"]["v"]
    print("| %s | %.1f | %.3f | %.3f | %.2f | %.2f | %.0f |" % (p.split("/")[-1][:-5], s["chi2"], s["bot5"], s["bot15"], e[19], sum(e[17:20]) / 3, s["chi2_end"]))
