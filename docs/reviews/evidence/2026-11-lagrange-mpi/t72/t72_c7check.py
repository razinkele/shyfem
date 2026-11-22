#!/usr/bin/env python3
"""Task 7.2, spec section 7 case 7: in the release block (time 0.0) of the
particle dumps, the particles released exactly at a given point.
usage: t72_c7check.py SERIAL_DBG MPI_DBG X Y [X Y ...]
For each point: the (id, element) pairs of the serial run, and the (id,
element, process) entries of the MPI run.  Exit 1 unless, for every point,
the serial run has at least two entries in different elements and the MPI
run has the same (id, element) pairs, and at least one point has its copies
on two different processes (the release across a process interface; not
every point: the callers give points chosen for the partitions of two and
of four processes, and one point need not span both).
A particle's x, y in the dump come back from its internal coordinates in its
element (xi2xy), so the copies of one point in two elements differ in the last
bits: a point matches within TOL = 1e-5 degrees (the release spacing is about
1e-3 degrees)."""
import glob
import os
import sys

TOL = 1e-5


def rows(d):
    out = []
    for f in sorted(glob.glob(os.path.join(d, 'lgrdbg.part.*.txt'))):
        for line in open(f):
            if line.startswith('#'):
                continue
            p = line.split()
            if float(p[1]) != 0.0:
                continue
            out.append((int(p[2]), float(p[3]), float(p[4]),
                        int(p[7]), int(p[8])))
    return out


def main():
    sd, md = sys.argv[1:3]
    pts = [(float(sys.argv[i]), float(sys.argv[i + 1]))
           for i in range(3, len(sys.argv), 2)]
    rs, rm = rows(sd), rows(md)
    print('release block: serial %d entries, MPI %d entries' % (len(rs), len(rm)))
    ok = True
    cross = False
    for x, y in pts:
        s = sorted((i, ie) for i, xx, yy, ie, r in rs if abs(xx - x) < TOL and abs(yy - y) < TOL)
        m = sorted((i, ie, r) for i, xx, yy, ie, r in rm if abs(xx - x) < TOL and abs(yy - y) < TOL)
        print('point %.9g %.9g: serial (id, element) %s; MPI (id, element, process) %s'
              % (x, y, s, m))
        if len(s) < 2 or len({ie for _, ie in s}) < 2:
            print('  serial run does not insert it in two elements')
            ok = False
        if [(i, ie) for i, ie, _ in m] != s:
            print('  MPI entries differ from serial')
            ok = False
        ranks = sorted({r for _, _, r in m})
        print('  processes holding the copies: %s' % ranks)
        if len(ranks) >= 2:
            cross = True
    if not cross:
        print('no point has its copies on two different processes: the release'
              ' across a process interface was not tested')
        ok = False
    print('CASE 7 CHECK: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
