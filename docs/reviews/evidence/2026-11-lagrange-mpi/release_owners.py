#!/usr/bin/env python3
"""release_owners.py DBG_DIR [DBG_DIR ...]

The release block of the particle dump (lgrdbg.part.NN.txt of every process;
the lines written right after the release, at the first time of the files):
how many particles each process holds there (its owners), and the type of
release from the key (all particles released at that time).  Ruling D4 of
Task 6.1: the particles of mm_lgr_w's one polygon must have more than one
owner.
"""
import glob
import os
import sys


def owners(d):
    files = sorted(glob.glob(os.path.join(d, 'lgrdbg.part.*.txt')))
    if not files:
        sys.exit('%s: no part file' % d)
    rows = []
    for f in files:
        for line in open(f):
            if line.startswith('#'):
                continue
            p = line.split()
            rows.append((float(p[1]), int(p[2]), int(p[8])))
    t0 = min(r[0] for r in rows)
    per = {}
    ids = []
    for t, pid, rank in rows:
        if t == t0:
            per[rank] = per.get(rank, 0) + 1
            ids.append(pid)
    nproc = len(files)
    counts = [per.get(r, 0) for r in range(nproc)]
    nown = sum(1 for c in counts if c > 0)
    print('%s: release block t=%.1f: %d particles (ids %d..%d, %d distinct) on'
          ' %d processes, per process %s: %s'
          % (d, t0, len(ids), min(ids), max(ids), len(set(ids)), nproc, counts,
             'more than one owner' if nown > 1 else 'ONE OWNER'))
    return nown


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    bad = 0
    for d in sys.argv[1:]:
        bad += owners(d) <= 1
    sys.exit(1 if bad else 0)
