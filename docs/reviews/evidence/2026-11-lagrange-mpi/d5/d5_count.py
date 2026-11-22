#!/usr/bin/env python3
"""d5_count.py DBG_DIR [DBG_DIR ...]

Spec section 7, case 4, counted from the debug dump of a run on several
processes (levdbg = 3): a particle that has left the basin stays in the array
of the process that carried it when it left, with ie = -(the element it left)
(class D in lgrdbg.part.NN.txt, column 8 = -global element); the flux dump
lgrdbg.flux.NN.txt gives, for every element a process holds, its main owner
(column 4, id_elem(1,ie)).  A leaving is case 4 if the main owner of the
element left is not the process that holds the particle.

Prints, per folder, at the last output of the part files: the particles that
left, per process, and how many of them left an element whose main owner is
another process (per process and per element).
"""
import collections
import glob
import os
import sys


def count(d):
    owner = {}
    for f in sorted(glob.glob(os.path.join(d, 'lgrdbg.flux.*.txt'))):
        for line in open(f):
            if line.startswith('#'):
                continue
            p = line.split()
            e, mo = int(p[0]), int(p[3])
            if owner.setdefault(e, mo) != mo:
                sys.exit('%s: element %d has main owners %d and %d'
                         % (d, e, owner[e], mo))
    last = {}
    for f in sorted(glob.glob(os.path.join(d, 'lgrdbg.part.*.txt'))):
        for line in open(f):
            if line.startswith('#'):
                continue
            p = line.split()
            t = float(p[1])
            last.setdefault(t, []).append(p)
    if not last:
        sys.exit('%s: no particle line' % d)
    tmax = max(last)
    nleft = collections.Counter()
    nother = collections.Counter()
    byelem = collections.Counter()
    nbad = 0
    for p in last[tmax]:
        if p[0] != 'D':
            continue
        e, r = -int(p[7]), int(p[8])
        nleft[r] += 1
        if e not in owner:
            nbad += 1
            continue
        if owner[e] != r:
            nother[r] += 1
            byelem[(e, owner[e], r)] += 1
    print('%s: last output %.1f: left %d (per process %s); left an element whose'
          ' main owner is another process: %d (per process %s)'
          % (d, tmax, sum(nleft.values()), dict(sorted(nleft.items())),
             sum(nother.values()), dict(sorted(nother.items()))))
    for (e, mo, r), n in sorted(byelem.items()):
        print('    element %d (main owner %d) left by %d particles on process %d'
              % (e, mo, n, r))
    if nbad:
        print('    %d particles left an element missing from the flux dump' % nbad)
    return sum(nother.values())


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for d in sys.argv[1:]:
        count(d)
