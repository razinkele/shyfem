#!/usr/bin/env python3
"""Compare the info file (NAME.inf) of a particle run on several processes
with that of the serial run.

usage: lgr_inf_compare.py SERIAL.inf MPI.inf [--nbdy N]

Gate: the two files hold the same number of "energy:" lines with the same
times, the same number of "lagrange_nbdy:" lines, and the lagrange_nbdy
values are equal line by line (the global number of particles at every step).
With --nbdy N (case mm_lgr, a random walk in a closed basin: no particle
leaves) every lagrange_nbdy value of both files must be N instead of being
equal line by line.

Exit code 0 (identical), 1 (differences), 2 (a file is unreadable or holds no
lagrange_nbdy line).
"""
import argparse
import sys


def read(path):
    energy, nbdy = [], []
    with open(path, errors="replace") as f:
        for line in f:
            w = line.split()
            if len(w) >= 2 and w[0] == "energy:":
                energy.append(w[1])
            elif len(w) >= 2 and w[0] == "lagrange_nbdy:":
                nbdy.append(w[1])
    return energy, nbdy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("serial")
    ap.add_argument("mpi")
    ap.add_argument("--nbdy", type=int, default=None)
    a = ap.parse_args()
    try:
        es, ns = read(a.serial)
        em, nm = read(a.mpi)
    except OSError as e:
        print("lgr inf: cannot read: %s" % e)
        return 2
    print("lgr inf: energy lines serial %d, mpi %d; lagrange_nbdy lines "
          "serial %d, mpi %d" % (len(es), len(em), len(ns), len(nm)))
    if not ns or not nm:
        print("lgr inf: no lagrange_nbdy line in a file")
        return 2
    bad = 0
    if es != em:
        bad += 1
        n = next((i for i, (x, y) in enumerate(zip(es, em)) if x != y),
                 min(len(es), len(em)))
        print("lgr inf: energy lines differ (count or times), first at "
              "line %d of the energy lines" % (n + 1))
    if a.nbdy is not None:
        wrong = [i for i, v in enumerate(ns) if v != str(a.nbdy)]
        wrong_m = [i for i, v in enumerate(nm) if v != str(a.nbdy)]
        if len(ns) != len(nm):
            bad += 1
            print("lgr inf: the lagrange_nbdy line counts differ")
        if wrong or wrong_m:
            bad += 1
            print("lgr inf: lagrange_nbdy not %d: serial %d lines, mpi %d "
                  "lines" % (a.nbdy, len(wrong), len(wrong_m)))
    else:
        if len(ns) != len(nm):
            bad += 1
            print("lgr inf: the lagrange_nbdy line counts differ")
        else:
            d = [i for i, (x, y) in enumerate(zip(ns, nm)) if x != y]
            if d:
                bad += 1
                print("lgr inf: lagrange_nbdy differs on %d lines, first at "
                      "line %d: serial %s, mpi %s"
                      % (len(d), d[0] + 1, ns[d[0]], nm[d[0]]))
    if bad:
        return 1
    print("lgr inf: identical (lagrange_nbdy %s)"
          % (sorted(set(ns)) if len(set(ns)) < 4 else "varies"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
