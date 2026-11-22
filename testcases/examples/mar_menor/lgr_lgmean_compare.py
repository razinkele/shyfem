#!/usr/bin/env python3
"""AC8: compare `lgrelab -lgmean` of a serial and an MPI particle file against
the spread of serial runs whose wind drag was perturbed.

usage: lgr_lgmean_compare.py SERIAL MPI BASE PERT [PERT ...]
       lgr_lgmean_compare.py --selftest

Each argument is a particle file (NAME.lgr.shy), on which the tool runs
`lgrelab -lgmean NAME.lgr.shy` (lgrelab on PATH) in a fresh temporary folder
holding a link to the file (lgrelab truncates long paths, so it gets a
relative name), or a folder that already holds the outputs of such a run:
the standard output as lgrelab.out and the files lagrange_mean_traj.T (one
per particle type T: per output time, the time, mean x and y with 5
decimals, then mean hl, age, sinking and the custom values with 3 decimals).

SERIAL and MPI must hold the same particles: the table "Particle
distrubution over time" of lgrelab (per record: n_active, n_new, n_exit,
n_beach, n_type) is equal line by line, and both runs have the same type
files with the same times.  The values may differ by no more than the
envelope of BASE against the perturbed runs PERT: for every type, time and
column, |SERIAL - MPI| <= max over PERT of |BASE - PERT| (BASE and every
PERT must have the structure of SERIAL).  The differences are taken on the
printed decimals exactly (no rounding noise).  The tool prints one table row
per type and column: values compared, the largest |SERIAL - MPI|, the
largest envelope value, the values beyond the envelope (gated), and, for
information only, the values beyond the envelope by more than one unit of
the last printed decimal (beyond+1u: 1e-5 for x and y, 1e-3 for the
others); then "LGMEAN COMPARE: PASS" or "FAIL".

Exit status: 0 = pass, 1 = fail, 2 = an input cannot be read or lgrelab
failed.
"""
import decimal
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

COLS = ("x", "y", "hl", "age", "sinking")
COUNT_LINE = re.compile(r"^\s*\d+\s+(\S+::\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")


class InputError(Exception):
    pass


def run_lgrelab(path, keep):
    """Run lgrelab -lgmean on path in a new temporary folder; return it."""
    if not os.path.isfile(path):
        raise InputError("no such file: %s" % path)
    tmp = tempfile.mkdtemp(prefix="lgmean.")
    keep.append(tmp)
    name = os.path.basename(path)
    os.symlink(os.path.abspath(path), os.path.join(tmp, name))
    with open(os.path.join(tmp, "lgrelab.out"), "w") as out:
        rc = subprocess.call(["lgrelab", "-lgmean", name], cwd=tmp,
                             stdout=out, stderr=subprocess.STDOUT)
    if rc != 0:
        raise InputError("lgrelab -lgmean %s failed (exit %d)" % (path, rc))
    return tmp


def read_dir(folder):
    """Return (count table, {type: [(time, [Decimal values])]})."""
    out = os.path.join(folder, "lgrelab.out")
    if not os.path.isfile(out):
        raise InputError("%s: no lgrelab.out" % folder)
    counts = []
    with open(out) as fh:
        for line in fh:
            m = COUNT_LINE.match(line)
            if m:
                counts.append(m.groups())
    trajs = {}
    for f in sorted(glob.glob(os.path.join(folder, "lagrange_mean_traj.*"))):
        typ = int(f.rsplit(".", 1)[1])
        rows = []
        with open(f) as fh:
            for line in fh:
                parts = line.split()
                if not parts:
                    continue
                try:
                    rows.append((parts[0], [decimal.Decimal(v) for v in parts[1:]]))
                except decimal.InvalidOperation:
                    raise InputError("%s: bad line %r" % (f, line))
        trajs[typ] = rows
    if not counts:
        raise InputError("%s: no particle table in lgrelab.out" % folder)
    return counts, trajs


def same_shape(ref, other):
    """Message if other's type files, times or columns differ from ref."""
    if sorted(ref) != sorted(other):
        return "types %s / %s" % (sorted(ref), sorted(other))
    for typ in ref:
        a, b = ref[typ], other[typ]
        if len(a) != len(b):
            return "type %d: %d / %d lines" % (typ, len(a), len(b))
        for (ta, va), (tb, vb) in zip(a, b):
            if ta != tb or len(va) != len(vb):
                return "type %d: line %s / %s" % (typ, ta, tb)
    return None


def compare(serial, mpi, base, perts):
    """Print the table and the verdict; return 0 or 1."""
    ok = True
    if serial[0] != mpi[0]:
        ok = False
        print("particle table differs:")
        for a, b in zip(serial[0], mpi[0]):
            if a != b:
                print("  serial %s  mpi %s" % (" ".join(a), " ".join(b)))
                break
        if len(serial[0]) != len(mpi[0]):
            print("  records: serial %d, mpi %d" % (len(serial[0]), len(mpi[0])))
    else:
        print("particle table: %d records, equal" % len(serial[0]))
    for label, run in [("mpi", mpi), ("base", base)] + \
            [("perturbed %d" % (k + 1), p) for k, p in enumerate(perts)]:
        msg = same_shape(serial[1], run[1])
        if msg:
            print("structure of %s differs from serial: %s" % (label, msg))
            return 1
    print("%-5s %-8s %7s %14s %14s %7s %10s" % ("type", "column", "values",
                                              "max|ser-mpi|", "max envelope",
                                              "beyond", "beyond+1u"))
    for typ in sorted(serial[1]):
        ncol = len(serial[1][typ][0][1]) if serial[1][typ] else 0
        for col in range(ncol):
            name = COLS[col] if col < len(COLS) else "c%d" % (col - len(COLS) + 1)
            nval = nbad = nbad1 = 0
            dmax = emax = decimal.Decimal(0)
            for i, (_t, vs) in enumerate(serial[1][typ]):
                d = abs(vs[col] - mpi[1][typ][i][1][col])
                env = max(abs(base[1][typ][i][1][col] - p[1][typ][i][1][col])
                          for p in perts)
                unit = decimal.Decimal(1).scaleb(vs[col].as_tuple().exponent)
                nval += 1
                dmax = max(dmax, d)
                emax = max(emax, env)
                if d > env:
                    nbad += 1
                if d > env + unit:
                    nbad1 += 1
            print("%-5d %-8s %7d %14s %14s %7d %10d"
                  % (typ, name, nval, dmax, emax, nbad, nbad1))
            if nbad:
                ok = False
    print("LGMEAN COMPARE: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def selftest():
    """Synthetic outputs: one pass and one fail."""
    tmp = tempfile.mkdtemp(prefix="lgmean_selftest.")
    try:
        def make(name, x, y):
            d = os.path.join(tmp, name)
            os.mkdir(d)
            with open(os.path.join(d, "lgrelab.out"), "w") as fh:
                fh.write("    1  2009-01-01::01:00:00       145       145"
                         "         0         0         1\n")
            with open(os.path.join(d, "lagrange_mean_traj.1"), "w") as fh:
                fh.write("2009-01-01::01:00:00 %13.5f %13.5f     2.766     0.045"
                         "     0.000     0.000\n" % (x, y))
            return read_dir(d)
        base = make("base", -0.77963, 37.68299)
        perts = [make("p1", -0.77961, 37.68299), make("p2", -0.77963, 37.68302)]
        serial = make("serial", -0.77963, 37.68299)
        good = compare(serial, make("good", -0.77965, 37.68296), base, perts)
        bad = compare(serial, make("bad", -0.77966, 37.68299), base, perts)
    finally:
        shutil.rmtree(tmp)
    ok = good == 0 and bad == 1
    print("LGMEAN SELFTEST: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    if len(argv) < 4 or any(a.startswith("-") for a in argv):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    keep = []
    try:
        runs = []
        for a in argv:
            if os.path.isdir(a):
                runs.append(read_dir(a))
                print("%s: outputs of lgrelab -lgmean" % a)
            else:
                runs.append(read_dir(run_lgrelab(a, keep)))
                print("%s: lgrelab -lgmean run" % a)
        return compare(runs[0], runs[1], runs[2], runs[3:])
    except (InputError, OSError) as exc:
        print("cannot compare: %s" % exc, file=sys.stderr)
        return 2
    finally:
        for d in keep:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
