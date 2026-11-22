#!/usr/bin/env python3
"""AC8: compare `lgrelab -lgmean` of a serial and an MPI particle file against
the spread of serial runs whose wind drag was perturbed.

usage: lgr_lgmean_compare.py [--perturbed N] SERIAL MPI BASE PERT [PERT ...]
       lgr_lgmean_compare.py --selftest

Each argument is a particle file (NAME.lgr.shy), on which the tool runs
`lgrelab -lgmean NAME.lgr.shy` (lgrelab on PATH) in a fresh temporary folder
holding a link to the file (lgrelab truncates long paths, so it gets a
relative name), or a folder that already holds the outputs of such a run:
the standard output as lgrelab.out and the files lagrange_mean_traj.T (one
per particle type T: per output time, the time, mean x and y with 5
decimals, then mean hl, age, sinking and the custom values with 3 decimals).

Exactly N perturbed runs PERT must be given (--perturbed N, default 6, the
number of the floor runs); any other number fails.  The comparison also fails
if no lagrange_mean_traj file exists (nothing was compared) and if any value
of any run is NaN or infinite (a clean message, no traceback).

SERIAL and MPI must hold the same particles: the table "Particle
distrubution over time" of lgrelab (per record: n_active, n_new, n_exit,
n_beach, n_type) is equal line by line, and both runs have the same type
files with the same times.  The values may differ by no more than the
envelope of BASE against the perturbed runs PERT: for every type, time and
column, |SERIAL - MPI| <= max over PERT of |BASE - PERT| + one unit of the
last printed decimal of the value (1e-5 for x and y, 1e-3 for the others;
BASE and every PERT must have the structure of SERIAL).  The unit is
allowed because the printed means are rounded: a difference far below the
print resolution can flip the last digit, and where every perturbed run
prints the base's digits the envelope is 0 by rounding.  The differences
are taken on the printed decimals exactly (no rounding noise).  The tool
prints one table row per type and column: values compared, the largest
|SERIAL - MPI|, the largest envelope value, the values within the envelope,
the values within the envelope plus one unit (these include the former),
the values beyond (gated: must be 0); a row "all" sums the counts; then
"LGMEAN COMPARE: PASS" or "FAIL".

Exit status: 0 = pass, 1 = fail, 2 = an input cannot be read or lgrelab
failed, or the command line is wrong.
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
NPERT = 6
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


def compare(serial, mpi, base, perts, nperts=NPERT):
    """Print the table and the verdict; return 0 or 1."""
    ok = True
    if len(perts) != nperts:
        print("%d perturbed runs given, %d required" % (len(perts), nperts))
        print("LGMEAN COMPARE: FAIL")
        return 1
    if not serial[1]:
        print("no lagrange_mean_traj file in the serial run: nothing to compare")
        print("LGMEAN COMPARE: FAIL")
        return 1
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
            print("LGMEAN COMPARE: FAIL")
            return 1
    print("%-5s %-8s %7s %14s %14s %10s %13s %7s"
          % ("type", "column", "values", "max|ser-mpi|", "max envelope",
             "within env", "within env+1u", "beyond"))
    tot = [0, 0, 0, 0]
    for typ in sorted(serial[1]):
        ncol = len(serial[1][typ][0][1]) if serial[1][typ] else 0
        for col in range(ncol):
            name = COLS[col] if col < len(COLS) else "c%d" % (col - len(COLS) + 1)
            nval = nenv = nunit = nbad = 0
            dmax = emax = decimal.Decimal(0)
            for i, (_t, vs) in enumerate(serial[1][typ]):
                vals = [("serial", vs[col]), ("mpi", mpi[1][typ][i][1][col]),
                        ("base", base[1][typ][i][1][col])] + \
                    [("perturbed %d" % (k + 1), p[1][typ][i][1][col])
                     for k, p in enumerate(perts)]
                nonfin = [lab for lab, v in vals if not v.is_finite()]
                if nonfin:
                    print("type %d column %s time %s: non-finite value in %s"
                          % (typ, name, _t, ", ".join(nonfin)))
                    nval += 1
                    nbad += 1
                    continue
                d = abs(vs[col] - mpi[1][typ][i][1][col])
                env = max(abs(base[1][typ][i][1][col] - p[1][typ][i][1][col])
                          for p in perts)
                unit = decimal.Decimal(1).scaleb(vs[col].as_tuple().exponent)
                nval += 1
                dmax = max(dmax, d)
                emax = max(emax, env)
                if d <= env:
                    nenv += 1
                if d <= env + unit:
                    nunit += 1
                else:
                    nbad += 1
            print("%-5d %-8s %7d %14s %14s %10d %13d %7d"
                  % (typ, name, nval, dmax, emax, nenv, nunit, nbad))
            tot = [tot[0] + nval, tot[1] + nenv, tot[2] + nunit, tot[3] + nbad]
            if nbad:
                ok = False
    print("%-14s %7d %30s %10d %13d %7d" % ("all", tot[0], "", tot[1], tot[2],
                                           tot[3]))
    if tot[0] == 0:
        print("no value was compared")
        ok = False
    print("LGMEAN COMPARE: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def selftest():
    """Synthetic outputs: values within the envelope and within one printed
    unit of it pass, values two units beyond it fail; so do a comparison of
    nothing, a NaN, a wrong number of perturbed runs and unequal particle
    tables."""
    tmp = tempfile.mkdtemp(prefix="lgmean_selftest.")
    try:
        def make(name, x, y, hl=2.766, table_tail="1", traj=True):
            d = os.path.join(tmp, name)
            os.mkdir(d)
            with open(os.path.join(d, "lgrelab.out"), "w") as fh:
                fh.write("    1  2009-01-01::01:00:00       145       145"
                         "         0         0         %s\n" % table_tail)
            if traj:
                with open(os.path.join(d, "lagrange_mean_traj.1"), "w") as fh:
                    fh.write("2009-01-01::01:00:00 %13s %13.5f %9.3f     0.045"
                             "     0.000     0.000\n" % (
                                 x if isinstance(x, str) else "%.5f" % x, y, hl))
            return read_dir(d)
        # envelope: x 2e-5, y 3e-5, hl 0 (all perturbed runs print the base's hl)
        base = make("base", -0.77963, 37.68299)
        perts = [make("p1", -0.77961, 37.68299), make("p2", -0.77963, 37.68302)]
        serial = make("serial", -0.77963, 37.68299)
        none = make("none", 0.0, 0.0, traj=False)
        res = [compare(serial, make("within", -0.77965, 37.68296), base, perts, 2),
               compare(serial, make("hl_one_unit", -0.77963, 37.68299, 2.767),
                       base, perts, 2),
               compare(serial, make("hl_two_units", -0.77963, 37.68299, 2.768),
                       base, perts, 2),
               compare(serial, make("x_two_units", -0.77967, 37.68299),
                       base, perts, 2),
               compare(none, none, none, [none, none], 2),
               compare(serial, make("nan", "nan", 37.68299), base, perts, 2),
               compare(serial, make("inf", "inf", 37.68299), base, perts, 2),
               compare(serial, make("nan_pert", -0.77963, 37.68299), base,
                       perts[:1] + [make("p3", "nan", 37.68299)], 2),
               compare(serial, make("same", -0.77963, 37.68299), base, perts, 3),
               compare(serial, make("same2", -0.77963, 37.68299), base,
                       perts, 1),
               compare(serial, make("table", -0.77963, 37.68299,
                                    table_tail="0"), base, perts, 2)]
    finally:
        shutil.rmtree(tmp)
    want = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    ok = res == want
    print("LGMEAN SELFTEST: %s (results %s; expected %s: within the envelope,"
          " one unit off with envelope 0, two units off in hl and in x, nothing"
          " compared, NaN, infinite, NaN in a perturbed run, too few and too"
          " many perturbed runs, unequal particle table)"
          % ("PASS" if ok else "FAIL", " ".join(map(str, res)),
             " ".join(map(str, want))))
    return 0 if ok else 1


def main(argv):
    if argv == ["--selftest"]:
        return selftest()
    nperts = NPERT
    if len(argv) >= 2 and argv[0] == "--perturbed":
        if not argv[1].isdigit() or int(argv[1]) < 1:
            print("--perturbed needs a positive number", file=sys.stderr)
            return 2
        nperts = int(argv[1])
        argv = argv[2:]
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
        return compare(runs[0], runs[1], runs[2], runs[3:], nperts)
    except (InputError, OSError) as exc:
        print("cannot compare: %s" % exc, file=sys.stderr)
        return 2
    finally:
        for d in keep:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
