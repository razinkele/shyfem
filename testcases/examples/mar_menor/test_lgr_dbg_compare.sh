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
# global element: particle 3 sits in element 8 instead of 7
run('elem_diff', [[p(1, 0., 0.), p(2, 0., 0.)], [p(3, 5., 5., ieg=8)]])
# two particles at one point in two elements (a point on a shared side),
# listed in the opposite order in the two runs
run('ser_side', [[p(1, 0., 0., ieg=7), p(2, 0., 0., ieg=8), p(3, 5., 5.)]])
run('side', [[p(1, 0., 0., ieg=8), p(2, 0., 0., ieg=7)], [p(3, 5., 5.)]])
# the same with 520 particles: 520*520 pairs > FULL_EDGES, so the nearest
# match takes its candidate path
row = [p(i, float(i), 0.) for i in range(3, 521)]
run('ser_side_big', [[p(1, 0., 0., ieg=7), p(2, 0., 0., ieg=8)] + row])
run('side_big', [[p(1, 0., 0., ieg=8), p(2, 0., 0., ieg=7)], row])
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

# ---- dumps with the six key columns, two time blocks (hand-over tests)
TK = (3600.0, 7200.0)

def kkey(id):
    return (100 + id, 0.25, 0.5 + 0.001 * id, 1, 0.5, -300.0)

def kbase(id, b):
    return (float(id) + 0.5 * b, 2.0 * b)

def write_k(d, n, lines, key=True):
    """lines = [(block, rank, cls, id, x, y, ncross, key)]"""
    os.makedirs(d, exist_ok=True)
    for r in range(n):
        with open('%s/lgrdbg.part.%02d.txt' % (d, r), 'w') as f:
            f.write('# rank %d of %d\n' % (r, n))
            for b, rank, c, id, x, y, nc, k in lines:
                if rank != r:
                    continue
                f.write('%s %14.1f %10d %.16E %.16E %16.8E %5d %10d %5d %5d'
                        % (c, TK[b], id, x, y, 0.5, 1, 7, rank, nc))
                if key:
                    f.write(' %10d %24.16E %24.16E %5d %16.8E %24.16E' % k)
                f.write('\n')

def krun(name, n, ids, changed=(), off=None, cls=None, nc=None, key=True,
         drop=(), extra=()):
    """Particles `ids` in both blocks.  An MPI run (n > 1) has particle i on
    rank 0 in block 0 and, if i is in `changed`, on rank n-1 in block 1 (else
    on rank 0).  off(i, b) -> (dx, dy) added to the position, cls(i, b) the
    class, nc(i, b) the crossing count; drop = [(i, b)] entries left out,
    extra = lines added."""
    lines = []
    for i in ids:
        for b in (0, 1):
            if (i, b) in drop:
                continue
            x, y = kbase(i, b)
            dx, dy = off(i, b) if off else (0.0, 0.0)
            rank = (n - 1) if (b == 1 and i in changed) else 0
            lines.append((b, rank, cls(i, b) if cls else 'P', i, x + dx,
                          y + dy, nc(i, b) if nc else 1, kkey(i)))
    write_k(os.path.join(root, name), n, lines + list(extra), key)

I10 = range(1, 11)
krun('kser', 1, I10)
krun('kser_old', 1, I10, key=False)
krun('kok', 2, I10, changed=range(1, 6))
krun('kok_old', 2, I10, changed=range(1, 6), key=False)
# every changed particle jumps by 1e-3 in block 1, those that stay do not
krun('kjump', 2, I10, changed=range(1, 6),
     off=lambda i, b: (1e-3, 0.0) if (b == 1 and i <= 5) else (0.0, 0.0))
# both groups diverge in half of their particles (20 particles)
I20 = range(1, 21)
krun('kser20', 1, I20)
krun('krate', 2, I20, changed=range(1, 11),
     off=lambda i, b: (1e-3, 0.0) if (b == 1 and i % 2 == 0) else (0.0, 0.0))
# a single changed particle beyond the step
krun('kone', 2, I10, changed=range(1, 6),
     off=lambda i, b: (1e-3, 0.0) if (b == 1 and i == 3) else (0.0, 0.0))
# three changed particles: at 0, within the step (3e-8), beyond (1e-7)
krun('kwithin', 2, I10, changed=range(1, 4),
     off=lambda i, b: ({2: (3e-8, 0.0), 3: (1e-7, 0.0)}.get(i, (0.0, 0.0))
                       if b == 1 else (0.0, 0.0)))
# a particle not at distance 0 in block 0 is not in the statistic
krun('kfirst', 2, I10, changed=range(1, 6),
     off=lambda i, b: (1e-3, 0.0) if i <= 5 else (0.0, 0.0))
# particle 4 has left the basin in both runs in block 1 (x = y = 0, class D)
krun('kser_left', 1, I10, cls=lambda i, b: 'D' if (i == 4 and b == 1) else 'P')
krun('kleft', 2, I10, changed=range(1, 6),
     cls=lambda i, b: 'D' if (i == 4 and b == 1) else 'P')
# particle 4 has left in the MPI run only
krun('kleft_mpi', 2, I10, changed=range(1, 6),
     cls=lambda i, b: 'D' if (i == 4 and b == 1) else 'P')
# a duplicate key: the MPI run has particle 5 twice (on two ranks) in block 0
krun('kdup', 2, I10, changed=range(1, 6), extra=[(0, 1, 'P', 5, *kbase(5, 0),
     1, kkey(5))])
# serial run with a key twice: particle 2 listed again in block 0
krun('kser_dup', 1, I10, extra=[(0, 0, 'P', 2, *kbase(2, 0), 1, kkey(2))])
# a key that occurs in the MPI run only (particle 11)
krun('kextra', 2, I10, changed=range(1, 6),
     extra=[(0, 0, 'P', 11, 9.0, 9.0, 1, kkey(11)),
            (1, 0, 'P', 11, 9.5, 9.0, 1, kkey(11))])
# crossing count differs at distance 0 (particle 2), and at a non-zero
# distance (particle 3, 1e-3 away in block 1)
krun('kncr0', 2, I10, changed=range(1, 6), nc=lambda i, b: 2 if (b == 1 and i == 2) else 1)
krun('kncrd', 2, I10, changed=range(1, 6), nc=lambda i, b: 2 if (b == 1 and i == 3) else 1,
     off=lambda i, b: (1e-3, 0.0) if (b == 1 and i == 3) else (0.0, 0.0))
# the two ids differ in the MPI run (ids repeat across ranks at this stage)
# while the keys are right: pairing by key does not look at the id
krun('kid', 2, I10, changed=range(1, 6))

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
# (grep -z splits a pattern at a newline: "[^ 0-9]" stands for the end of a line)
check "same element, gated with --elem" 0 "3600.0 +3 +3 +0 +0 +0 +0 +0 +0.000e\+00 +0 +0 +0 +0 +0 +0[^ 0-9].*element differs 0[^ 0-9]" \
    part "$t/ser" "$t/ok" --tol 0 --elem
check "element differs, gated with --elem" 1 "3600.0 +3 +3 +0 +0 +0 +0 +0 +0.000e\+00 +0 +0 +0 +0 +0 +1[^ 0-9].*element differs 1[^ 0-9]" \
    part "$t/ser" "$t/elem_diff" --tol 0 --elem
check "element differs, by id, gated with --elem" 1 "element differs 1[^ 0-9]" \
    part "$t/ser" "$t/elem_diff" --tol 0 --by id --elem
check "element differs, not gated without --elem" 0 "element differs 1 \(not gated\)" \
    part "$t/ser" "$t/elem_diff" --tol 0
check "two elements at one point pair by element with --elem" 0 "element differs 0[^ 0-9]" \
    part "$t/ser_side" "$t/side" --tol 0 --elem
check "the same in the candidate path (520 particles)" 0 "3600.0 +520 +520 .*element differs 0[^ 0-9]" \
    part "$t/ser_side_big" "$t/side_big" --tol 0 --elem
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

# ---- particle key: --by key and the hand-over check
# table columns: time n_ser n_mpi D_ser D_mpi dupid unmat nan max_dist >tol lb!= z!= ncr!= ncr-1 ie!=
check "by key, matching runs" 0 "3600.0 +10 +10 +0 +0 +0 +0 +0 +0.000e\+00 +0 +0 +0 +0 +0 +0[^ 0-9].*ncross differs at distance 0: 0 \(not gated\); at a non-zero distance: 0" \
    part "$t/kser" "$t/kok" --tol 0 --by key
check "by key, a changed particle is far away" 1 "7200.0 +10 +10 +0 +0 +0 +0 +0 +1.000e-03 +5 " \
    part "$t/kser" "$t/kjump" --tol 1e-5 --by key
check "by key, serial dump of the old format" 2 "without the six key columns" \
    part "$t/kser_old" "$t/kok" --tol 0 --by key
check "by key, MPI dump of the old format" 2 "without the six key columns" \
    part "$t/kser" "$t/kok_old" --tol 0 --by key
check "old format still read, by id" 0 "" part "$t/kser_old" "$t/kok_old" --tol 0 --by id
check "old format still read, nearest" 0 "" part "$t/kser_old" "$t/kok_old" --tol 0
check "a key twice in the MPI run" 1 "3600.0 +10 +11 .* +1 +0 " \
    part "$t/kser" "$t/kdup" --tol 0 --by key
check "a key twice in the serial run" 1 "serial dup keys 1" \
    part "$t/kser_dup" "$t/kok" --tol 0 --by key
check "a key in the MPI run only" 1 "3600.0 +10 +11 +0 +0 +0 +1 " \
    part "$t/kser" "$t/kextra" --tol 0 --by key
check "key left in one run, alive in the other" 1 "7200.0 +9 +10 +1 +0 +0 +1 " \
    part "$t/kser_left" "$t/kok" --tol 0 --by key
check "ncross differs at distance 0, gated" 1 "ncross differs at distance 0: 1; at a non-zero distance: 0" \
    part "$t/kser" "$t/kncr0" --tol 0 --by key --ncross
check "ncross differs at distance 0, not gated" 0 "distance 0: 1 \(not gated\)" \
    part "$t/kser" "$t/kncr0" --tol 0 --by key
check "ncross differs at a non-zero distance, no failure" 0 "distance 0: 0; at a non-zero distance: 1" \
    part "$t/kser" "$t/kncrd" --tol 1 --by key --ncross
check "by nearest still gates every differing ncross" 1 "ncross differs 1," \
    part "$t/kser" "$t/kncr0" --tol 0 --ncross
check "hand-over, changed and stayed at 0" 0 "changed process +5 +5 +0 +0 .*stayed +5 +5 +0 +0 .*left out.*: 0[^ 0-9].*: ok" \
    part "$t/kser" "$t/kok" --tol 0 --by key --handover
check "hand-over, changed jump, stayed do not" 1 "changed process +5 +0 +0 +5 +1.0000e-03 .*stayed +5 +5 +0 +0 .*: FAIL[^ 0-9]" \
    part "$t/kser" "$t/kjump" --tol 1 --by key --handover
check "hand-over, both groups diverge at the same rate" 0 "changed process +10 +5 +0 +5 .*stayed +10 +5 +0 +5 .*: ok" \
    part "$t/kser20" "$t/krate" --tol 1 --by key --handover
check "hand-over, one changed pair beyond the step: allowed" 0 "changed process +5 +4 +0 +1 .*: ok" \
    part "$t/kser" "$t/kone" --tol 1 --by key --handover
check "hand-over, one changed pair beyond the step, --allow 0" 1 "changed process +5 +4 +0 +1 .*: FAIL[^ 0-9]" \
    part "$t/kser" "$t/kone" --tol 1 --by key --handover --allow 0
check "hand-over, at 0 / within / beyond the step" 0 "changed process +3 +1 +1 +1 +1.0000e-07 " \
    part "$t/kser" "$t/kwithin" --tol 1 --by key --handover --allow 1
check "hand-over, the step is a parameter" 0 "changed process +3 +1 +2 +0 +1.0000e-07 .*: ok" \
    part "$t/kser" "$t/kwithin" --tol 1 --by key --handover --step 1e-6
check "hand-over, particles off at the first block are not counted" 0 "changed process +0 +0 +0 +0 .*stayed +5 +5 +0 +0 " \
    part "$t/kser" "$t/kfirst" --tol 1 --by key --handover
check "hand-over, a particle that left in both runs is left out" 0 "changed process +4 +4 +0 +0 .*stayed +5 +5 +0 +0 .*left out.*: 1[^ 0-9]" \
    part "$t/kser_left" "$t/kleft" --tol 0 --by key --handover
check "hand-over, a particle that left in one run is a failure" 1 "7200.0 +10 +9 +0 +1 +0 +1 " \
    part "$t/kser" "$t/kleft_mpi" --tol 0 --by key --handover
check "hand-over, distances above --tol are not gated" 0 "" \
    part "$t/kser" "$t/kone" --tol 0 --by key --handover
check "hand-over needs --by key" 2 "needs --by key" \
    part "$t/kser" "$t/kok" --tol 0 --handover

if [ "$fail" -eq 0 ]; then echo "LGR DBG COMPARE TEST: PASS"; exit 0; fi
echo "LGR DBG COMPARE TEST: FAIL"; exit 1
