#!/usr/bin/env python3
"""Task 7.2, spec section 7 case 7: find a side of GRID/MM_geo between two
elements whose main owners differ (from the flux dumps of case A on 2 and on
4 processes), whose midpoint is exact in single precision and lies exactly
on the side in intri's arithmetic, and a square release polygon around it
whose centre (xy_center: sum of the vertices / n in single precision) is
that midpoint exactly.  The polygon release puts its grid point (0, 0) at the
centre, so that point is a release point on the side: a serial run inserts it
in both elements.
usage: t72_c7find.py GRD DUMP_NP2 DUMP_NP4 OUT_POLYGON_FILE
"""
import glob
import math
import os
import sys

import numpy as np

f32 = np.float32
DRY = {365, 870}


def read_grd(path):
    nodes, elems = {}, {}
    for line in open(path):
        p = line.split()
        if not p:
            continue
        if p[0] == '1':
            nodes[int(p[1])] = (f32(float(p[3])), f32(float(p[4])))
        elif p[0] == '2':
            elems[int(p[1])] = tuple(int(v) for v in p[4:7])
    return nodes, elems


def read_owner(d):
    owner, enodes = {}, {}
    for f in sorted(glob.glob(os.path.join(d, 'lgrdbg.flux.*.txt'))):
        for line in open(f):
            if line.startswith('#'):
                continue
            p = line.split()
            ie, nd, mo = int(p[0]), int(p[1]), int(p[3])
            owner.setdefault(ie, set()).add(mo)
            enodes.setdefault(ie, set()).add(nd)
    return {ie: s.pop() if len(s) == 1 else None for ie, s in owner.items()}, enodes


def intri(xe, ye, xp, yp):
    """intri of regular.f90: single-precision differences, double products."""
    vals = []
    for k1 in range(3):
        k2 = (k1 + 1) % 3
        x21 = float(f32(xe[k2] - xe[k1]))
        y21 = float(f32(ye[k2] - ye[k1]))
        scal = float(f32(xp - xe[k1])) * (-y21) + float(f32(yp - ye[k1])) * x21
        vals.append(scal)
    return vals


def center(vals):
    s = f32(0.0)
    for v in vals:
        s = f32(s + v)
    return f32(s / f32(len(vals)))


def main():
    grd, d2, d4, out = sys.argv[1:5]
    nodes, elems = read_grd(grd)
    own2, en2 = read_owner(d2)
    own4, en4 = read_owner(d4)
    bad = [ie for ie in elems if en2.get(ie) != set(elems[ie]) or en4.get(ie) != set(elems[ie])]
    print('elements %d, dump numbering equals the grid file for %d (mismatch %d)'
          % (len(elems), len(elems) - len(bad), len(bad)))
    if bad:
        sys.exit('numbering differs')
    side = {}
    for ie, nn in elems.items():
        for i in range(3):
            a, b = nn[i], nn[(i + 1) % 3]
            side.setdefault((min(a, b), max(a, b)), []).append(ie)
    found = []
    for label, own in (('2', own2), ('4', own4)):
        best = None
        for (a, b), ies in sorted(side.items()):
            if len(ies) != 2:
                continue
            e1, e2 = ies
            if own[e1] == own[e2]:
                continue
            if e1 in DRY or e2 in DRY:	# permanently dry elements of this mesh
                continue
            (xa, ya), (xb, yb) = nodes[a], nodes[b]
            xm, ym = f32((xa + xb) / f32(2)), f32((ya + yb) / f32(2))
            if float(xm) * 2 != float(xa) + float(xb) or float(ym) * 2 != float(ya) + float(yb):
                continue
            ok = True
            for ie in ies:
                xe = [nodes[k][0] for k in elems[ie]]
                ye = [nodes[k][1] for k in elems[ie]]
                v = sorted(intri(xe, ye, xm, ym))
                if v[0] != 0.0 or v[1] <= 0.0:
                    ok = False
            if not ok:
                continue
            # the square holds every vertex of both elements, so that check_elements
            # flags both inside the polygon (an element with no vertex inside it and
            # no polygon vertex inside the element gets no particle)
            ext = max(max(abs(float(nodes[k][0]) - float(xm)), abs(float(nodes[k][1]) - float(ym)))
                      for ie in ies for k in elems[ie])
            d0 = math.ceil(ext * 1.25 / 0.0005) * 0.0005
            if any(abs(float(xm) - float(f[5])) < d0 + f[7] + 0.002 and abs(float(ym) - float(f[6])) < d0 + f[7] + 0.002 for f in found):
                continue
            for dd in [d0 + 0.0005 * j for j in range(20)]:
                xs = [f32(float('%.9g' % f32(xm + s * f32(dd)))) for s in (-1, 1, 1, -1)]
                ys = [f32(float('%.9g' % f32(ym + s * f32(dd)))) for s in (-1, -1, 1, 1)]
                if center(xs) == xm and center(ys) == ym:
                    best = (label, a, b, e1, e2, xm, ym, dd, xs, ys)
                    break
            if best:
                break
        if not best:
            sys.exit('no side for %s processes' % label)
        found.append(best)
    with open(out, 'w') as fh:
        for label, a, b, e1, e2, xm, ym, dd, xs, ys in found:
            for i, (x, y) in enumerate(zip(xs + xs[:1], ys + ys[:1])):
                fh.write('%.9g %.9g %d\n' % (x, y, 1 if i == 0 else 0))
            print('polygon for %s processes: side %d-%d between elements %d and %d; main owners on 2: %d, %d; on 4: %d, %d; '
                  'midpoint %.9g %.9g; square half-size %g'
                  % (label, a, b, e1, e2, own2[e1], own2[e2], own4[e1], own4[e2], xm, ym, dd))
    print('written: %s' % out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
