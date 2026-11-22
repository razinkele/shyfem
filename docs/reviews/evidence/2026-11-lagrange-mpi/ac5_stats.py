#!/usr/bin/env python3
"""ac5_stats.py LABEL=FILE.lgr.shy [LABEL=FILE.lgr.shy ...]

AC5 (Task 6.1, ruling D3): for each particle type (release group) at the last
output of each particle file, the mean position and the standard deviation
(population) in x and in y over the particles of the active block, and their
count.  The first file is the reference (the first serial run), the second
the second serial run: the difference between the two serial runs is the
reference spread of a run whose random walk is not seeded (#225).  Every
further file (the MPI runs) is printed as its difference from the first,
with a flag where it is more than three times the serial-serial difference
of that value.  Reads the files with lgr_compare.py: from the folder named by
the environment variable LGR_COMPARE_DIR, or else testcases/examples/mar_menor
of the repository this file is in (four levels above this folder).
"""
import math
import os
import sys

HERE = os.environ.get('LGR_COMPARE_DIR', os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir,
    os.pardir, os.pardir, 'testcases', 'examples', 'mar_menor'))
sys.path.insert(0, HERE)
import lgr_compare as L  # noqa: E402


def stats(path):
    _, times = L.read_file(path)
    t, blocks, _ = times[-1]
    groups = {}
    for p in blocks[0].values():
        groups.setdefault(p['type'], []).append((p['x'], p['y']))
    out = {}
    for typ, pts in sorted(groups.items()):
        n = len(pts)
        mx = math.fsum(x for x, _ in pts) / n
        my = math.fsum(y for _, y in pts) / n
        sx = math.sqrt(math.fsum((x - mx) ** 2 for x, _ in pts) / n)
        sy = math.sqrt(math.fsum((y - my) ** 2 for _, y in pts) / n)
        out[typ] = (n, mx, my, sx, sy)
    return t, len(blocks[1]), out


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    runs = []
    for a in args:
        label, path = a.split('=', 1)
        runs.append((label, path) + stats(path))
    for label, path, t, nexit, st in runs:
        print('%-8s last output t=%.1f, exited %d, types %s: %s'
              % (label, t, nexit, sorted(st), path))
    ref = runs[0][4]
    ser2 = runs[1][4]
    names = ('mean x', 'mean y', 'sd x', 'sd y')
    nflag = 0
    print()
    hdr = '| Type | Value | %s | %s - %s |' % (runs[0][0], runs[1][0], runs[0][0])
    hdr += ''.join(' %s - %s |' % (r[0], runs[0][0]) for r in runs[2:])
    print(hdr)
    print('|' + '---|' * (3 + len(runs) - 1))
    for typ in sorted(ref):
        counts = [r[4][typ][0] if typ in r[4] else 0 for r in runs]
        print('| %d | particles | %s |' % (typ, ' | '.join(str(c) for c in counts)))
        for k, name in enumerate(names):
            v0 = ref[typ][k + 1]
            d12 = ser2[typ][k + 1] - v0
            cells = []
            for r in runs[2:]:
                d = r[4][typ][k + 1] - v0
                flag = abs(d) > 3. * abs(d12)
                nflag += flag
                cells.append('%+.3e%s' % (d, ' (>3x)' if flag else ''))
            print('| %d | %s | %.6f | %+.3e | %s |'
                  % (typ, name, v0, d12, ' | '.join(cells)))
    print()
    print('values of the MPI runs more than three times the serial-serial'
          ' difference: %d of %d' % (nflag, len(ref) * len(names) * (len(runs) - 2)))


if __name__ == '__main__':
    main()
