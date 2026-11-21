#!/bin/bash
# Self-test for lgr_dbg_compare.py: writes small hand-made debug dumps
# (lgrdbg.KIND.NN.txt) in a temporary directory and checks exit codes and
# key output lines.
# Prints "LGR DBG COMPARE TEST: PASS" or "FAIL"; exits 0 or 1.

set -u
here="$(cd "$(dirname "$0")" && pwd)" || exit 1
tool="$here/lgr_dbg_compare.py"
tmp="$(mktemp -d -t lgrdbgtest.XXXXXX)" || exit 1
[ -n "$tmp" ] && [ -d "$tmp" ] || exit 1
trap 'case "$tmp" in */lgrdbgtest.*) rm -rf -- "$tmp" ;; esac' EXIT
fail=0

cat > "$tmp/gen.py" <<'PY'
import os, sys
root = sys.argv[1]
T = 3600.0

def p(id, x, y, z=0.5, lb=1, ncross=1, cls='P', ieg=7):
    return (cls, id, x, y, z, lb, ieg, ncross)

def write_part(d, rank, n, parts, header=True):
    os.makedirs(d, exist_ok=True)
    with open('%s/lgrdbg.part.%02d.txt' % (d, rank), 'w') as f:
        if header:
            f.write('# rank %d of %d\n' % (rank, n))
        for c, id, x, y, z, lb, ieg, nc in parts:
            fx = 'NaN' if x != x else '%.16E' % x
            fy = 'NaN' if y != y else '%.16E' % y
            f.write('%s %14.1f %10d %s %s %16.8E %5d %10d %5d %5d\n'
                    % (c, T, id, fx, fy, z, lb, ieg, rank, nc))

def run(name, ranks, n=None):
    """ranks = [particles of rank 0, of rank 1, ...]"""
    d = os.path.join(root, name)
    for r, parts in enumerate(ranks):
        write_part(d, r, n if n is not None else len(ranks), parts)
    return d

nan = float('nan')
run('ser', [[p(1, 0., 0.), p(2, 0., 0.), p(3, 5., 5.)]])
run('ok', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5.)]])
run('lost', [[p(1, 0., 0.)], [p(3, 5., 5.), p(3, 5., 5.)]])
run('nan_both', [[p(1, 0., 0.), p(2, nan, nan)], [p(3, 5., 5.)]])
run('nan_y', [[p(1, 0., 0.), p(2, 1.0, nan)], [p(3, 5., 5.)]])
run('ser_nan', [[p(1, 0., 0.), p(2, nan, 0.), p(3, 5., 5.)]])
run('both_nan', [[p(1, 0., 0.), p(2, nan, 0.)], [p(3, 5., 5.)]])
run('layer', [[p(1, 0., 0.), p(2, 0., 0., lb=2)], [p(3, 5., 5.)]])
run('zdiff', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5., z=0.5001)]])
run('ncr_unknown', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5., ncross=-1)]])
run('ncr_diff', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5., ncross=2)]])
run('empty_rank', [[p(1, 0., 0.), p(2, 0., 0.), p(3, 5., 5.)], []])
# rank 2 is missing: headers say 3 processes, files exist for ranks 0, 1
run('miss_high', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5.)]], n=3)
# extra rank: a third file, all headers say 2 processes
d = run('extra', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5.)]])
write_part(d, 2, 2, [])
# a file left from an older run with 3 processes
d = run('stale', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5.)]])
write_part(d, 2, 3, [])
# old format without the header line
d = os.path.join(root, 'noheader')
write_part(d, 0, 1, [p(1, 0., 0.), p(2, 0., 0.), p(3, 5., 5.)], header=False)

# flux files: serial elements 1, 2; element 2 is mixed (rank 1 main owner)
def write_flux(d, rank, n, rows):
    os.makedirs(d, exist_ok=True)
    with open('%s/lgrdbg.flux.%02d.txt' % (d, rank), 'w') as f:
        f.write('# rank %d of %d\n' % (rank, n))
        for ie, k, owner, ng, f3, f2 in rows:
            f.write('%11d%11d%6d%6d%3d%17.8E%17.8E\n'
                    % (ie, k, rank, owner, ng, f3, f2))
e1 = [(1, 1, 0, 0, 1.0, 1.0), (1, 2, 0, 0, -2.0, -2.0), (1, 3, 0, 0, 1.0, 1.0)]
def e2(owner, ng, v=3.0):
    return [(2, 2, owner, ng, v, v), (2, 3, owner, ng, -v, -v),
            (2, 4, owner, ng, 0.0, 0.0)]
write_flux(root + '/fser', 0, 1, e1 + e2(0, 0))
write_flux(root + '/fok', 0, 2, e1 + e2(1, 1))
write_flux(root + '/fok', 1, 2, e2(1, 1))
write_flux(root + '/foff', 0, 2, e1 + e2(1, 1))
write_flux(root + '/foff', 1, 2, e2(1, 1, v=3.5))
write_flux(root + '/fempty', 0, 2, e1 + e2(1, 1))
write_flux(root + '/fempty', 1, 2, [])
PY
python3 "$tmp/gen.py" "$tmp" || { echo "LGR DBG COMPARE TEST: FAIL (generator)"; exit 1; }

# check DESCRIPTION EXPECTED_EXIT [GREP_REGEX] -- arguments of the tool...
check() {
    local desc="$1" want="$2" rx="$3"; shift 3
    python3 "$tool" "$@" > "$tmp/out.txt" 2>&1
    local got=$?
    if [ "$got" -ne "$want" ]; then
        echo "FAIL: $desc: exit $got, expected $want"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    if [ -n "$rx" ] && ! grep -Ezq -- "$rx" "$tmp/out.txt"; then
        echo "FAIL: $desc: output lacks /$rx/"; sed 's/^/    /' "$tmp/out.txt"; fail=1; return
    fi
    echo "ok: $desc"
}

t="$tmp"
# table columns: time n_ser n_mpi D_ser D_mpi dupid unmat nan max_dist >tol lb!= z!= ncr!= ncr-1
check "matching runs, nearest" 0 "3600.0 +3 +3 +0 +0 +0 +0 +0 +0.000e\+00 +0 +0 +0 +0 +0" \
    part "$t/ser" "$t/ok" --tol 1e-5
check "matching runs, by id, with --ncross" 0 "" part "$t/ser" "$t/ok" --tol 0 --by id --ncross
check "lost particle hidden by a duplicate id, nearest" 1 "3600.0 +3 +3 +0 +0 +1 +0 +0 +5.000e\+00 +1 " \
    part "$t/ser" "$t/lost" --tol 1e-5
check "lost particle, by id" 1 "" part "$t/ser" "$t/lost" --tol 1e-5 --by id
check "NaN position, by id" 1 "3600.0 +3 +3 +0 +0 +0 +0 +1 +nan " part "$t/ser" "$t/nan_both" --tol 1e-5 --by id
check "NaN y, nearest" 1 "3600.0 +3 +3 +0 +0 +0 +1 +1 " part "$t/ser" "$t/nan_y" --tol 1e-5
check "NaN in both runs, nearest" 1 "3600.0 +3 +3 +0 +0 +0 +0 +2 " part "$t/ser_nan" "$t/both_nan" --tol 1e-5
check "layer differs, nearest" 1 "3600.0 +3 +3 +0 +0 +0 +0 +0 +0.000e\+00 +0 +1 +0 " \
    part "$t/ser" "$t/layer" --tol 1e-5
check "layer differs, by id" 1 "layer differs 1" part "$t/ser" "$t/layer" --tol 1e-5 --by id
check "z differs by 1e-4" 1 "z differs 1," part "$t/ser" "$t/zdiff" --tol 1e-5
check "ncross -1 is unknown, not a mismatch" 0 "ncross differs 0, ncross unknown \(-1\) 1" \
    part "$t/ser" "$t/ncr_unknown" --tol 1e-5 --ncross
check "ncross differs, gated with --ncross" 1 "ncross differs 1," part "$t/ser" "$t/ncr_diff" --tol 1e-5 --ncross
check "ncross differs, not gated without --ncross" 0 "ncross differs 1 \(not gated\)" \
    part "$t/ser" "$t/ncr_diff" --tol 1e-5
check "empty rank is a note, not a failure" 0 "note: ranks without any entry in the whole run: \[1\]" \
    part "$t/ser" "$t/empty_rank" --tol 1e-5
check "empty rank with --ranks-empty-ok" 0 "expected: ranks without" \
    part "$t/ser" "$t/empty_rank" --tol 1e-5 --ranks-empty-ok
check "missing highest rank" 2 "missing ranks \[2\]" part "$t/ser" "$t/miss_high" --tol 1e-5
check "extra rank" 2 "extra ranks \[2\]" part "$t/ser" "$t/extra" --tol 1e-5
check "file from an older run with more ranks" 2 "disagree on the number of processes" \
    part "$t/ser" "$t/stale" --tol 1e-5
check "dump without header line" 2 "first line is not" part "$t/noheader" "$t/ok" --tol 1e-5
check "4-rank directory as serial run" 2 "serial run must have 1 process" part "$t/ok" "$t/ok" --tol 1e-5
check "flux equal" 0 "all-own nodes +3 +0 .*mixed, main owner +3 +0 .*mixed, owned elsewhere +3 +0 " \
    flux "$t/fser" "$t/fok"
check "flux off in the main owner's copy" 1 "mixed, main owner +3 +2 " flux "$t/fser" "$t/foff"
check "flux file without data rows" 2 "no data rows" flux "$t/fser" "$t/fempty"

if [ "$fail" -eq 0 ]; then echo "LGR DBG COMPARE TEST: PASS"; exit 0; fi
echo "LGR DBG COMPARE TEST: FAIL"; exit 1
