import sys
CAT = {1: 'all', 2: 'lmax>=2', 3: 'lmax>=5', 4: 'dtvd*100<T now'}
def load(path):
    rows = []
    for line in open(path, errors='replace'):
        if line.startswith(' lgr_dbg_vprof '):
            w = line.split()
            tag, t, cat, n = int(w[1]), float(w[2]), int(w[3]), int(w[4])
            h = [int(x) for x in w[5:25]]
            n0, n1 = int(w[25]), int(w[26])
            rows.append((tag, t, cat, n, h, n0, n1))
    return rows
def chi2(h):
    n = sum(h); e = n / len(h)
    return sum((x - e) ** 2 / e for x in h) if e > 0 else 0.0
def main():
  for path in sys.argv[1:]:
    rows = load(path)
    print("==", path)
    for cat in (1, 2, 3, 4):
        r = [x for x in rows if x[2] == cat]
        if not r: continue
        start = [x for x in r if x[0] == 0][0]
        end = r[-1]
        for lab, x in (("start", start), ("end t=%.0f" % end[1], end)):
            n = x[3]; h = x[4]; e = n / 20.0 if n else 1
            rel = " ".join("%4.2f" % (v / e) for v in h)
            print("  %-15s %-10s n=%6d chi2(19df)=%8.1f surf/bot bins %.3f %.3f  at surface %d bottom %d" % (
                CAT[cat], lab, n, chi2(h), h[0] / e, h[-1] / e, x[5], x[6]))
            print("      rel. density per 5%% bin (surface->bottom): %s" % rel)

if __name__ == '__main__':
    main()
