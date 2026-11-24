#!/bin/bash
#------------------------------------------------------------------------
# Node classification of setnod on several processes against the serial
# run (issue #238).
#
# setnod (src/utils/shyutilmpi/topo_update.f90) classifies every node as
# inner (inodv 0), material boundary (-1), open boundary (> 0, the number
# of the boundary) or out of system (-2) from the sum of the angles of its
# elements (inner above 359.99 degrees).  On several processes an element
# is held by every process that has one of its nodes, and its angles must
# enter the sum of each of its nodes exactly once over all processes.
# Before the fix of #238 every process added all its elements and the
# exchange added the partial sums of the other holders on top, so a
# boundary node next to a partition edge could pass 360 degrees and be
# classified inner.
#
# The test runs one short case (one hour, the open boundary of mm_lgr_b:
# $bound1, nodes 85 to 177, ibtyp 1, and its river: $bound2, node 218,
# ibtyp 3) serially, on 2, 4 and 8 processes with the METIS partition the
# model makes, and on 4 processes with each of the two hand-written
# partitions of docs/reviews/evidence/2026-11-lagrange-mpi/d5 (written
# into the basin with shypre -partition; part_first.grd cuts through the
# elements at the open boundary and stopped the unfixed model at start-up
# with "error stop setnod: open boundary node", node 158).  It requires
# that every process classifies every node it holds (own and ghost nodes)
# as the serial run does, at the first three calls of setnod (two at
# start-up, one in the first time step), and that its angle sum is the
# serial one within 1e-3 degrees (so an element counted twice is found
# also at a node whose class it does not change, such as an inner node);
# both angle sums must be finite (a NaN would pass that comparison).
#
# The classification is read from the debug dump of setnod: with the
# environment variable SHYFEM_SETNOD_DUMP=PREFIX every process writes
# PREFIX.RANK.txt (lines: call, external node, inodv, angle sum in
# degrees; subroutine setnod_dump in topo_update.f90).  Without the
# variable the model writes nothing.
#
# Also required: every run ends (exit code 0 and "simulation end" in its
# log; timeout 600 s each); every process wrote its file with the three
# calls and holds the same nodes at each of them (a dump that lacks lines
# of a call fails); at every call the files of a run together hold every
# node of the mesh; the log
# of a run with a hand-written partition says "using these partitiones"
# (the partition of the basin was used), the log of a METIS run does not.
#
# Usage:  ./check_setnod_mpi.sh
# Needs shyfem, shypre, mpirun and python3 on PATH (an OpenMPI build).
# Works in a folder made with mktemp -d under ${TMPDIR:-/tmp}: GRID/
# MM_coarse.grd is copied there and its basins are built there with
# shypre (a partition goes into a basin of that folder only), INPUT is
# linked, so nothing in this folder changes.  The folder is kept (its
# path is the last line).  Prints "SETNOD TEST: PASS" or "SETNOD TEST:
# FAIL" and exits 0 or 1.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
W="$(git -C "$HERE" rev-parse --show-toplevel)" || { echo "SETNOD TEST: FAIL (not inside a git checkout)"; exit 1; }
D5="$W/docs/reviews/evidence/2026-11-lagrange-mpi/d5"
for t in shyfem shypre mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "SETNOD TEST: FAIL ($t is not on PATH)"; exit 1; }
done
for f in "$HERE/GRID/MM_coarse.grd" "$D5/part_first.grd" "$D5/part_second.grd" \
         "$HERE/INPUT/level_Mar_Menor.dat" "$HERE/INPUT/river.txt"; do
  [ -f "$f" ] || { echo "SETNOD TEST: FAIL (missing $f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/setnod.XXXXXX")" || exit 1
echo "setnod test: $(command -v shyfem), in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "SETNOD TEST FAIL: $*"; rc=1; }

#--- basins: METIS (no partition in the basin) and the two hand-written ones
mkbasin() {  # NAME [PARTITION_GRD]
  local g="$P/grid_$1"
  mkdir "$g" && cp "$HERE/GRID/MM_coarse.grd" "$g/" || return 1
  if [ -n "${2:-}" ]; then
    cp "$2" "$g/part.grd" || return 1
    ( cd "$g" && shypre -partition part.grd MM_coarse.grd > shypre.log 2>&1 ) || return 1
    grep -q 'reading partitioning file part.grd' "$g/shypre.log" || return 1
  else
    ( cd "$g" && shypre MM_coarse.grd > shypre.log 2>&1 ) || return 1
  fi
  [ -f "$g/MM_coarse.bas" ]
}
mkbasin metis || { echo "SETNOD TEST: FAIL (shypre failed for the plain basin, log $P/grid_metis/shypre.log)"; exit 1; }
mkbasin first "$D5/part_first.grd" || { echo "SETNOD TEST: FAIL (shypre -partition failed for part_first.grd, log $P/grid_first/shypre.log)"; exit 1; }
mkbasin second "$D5/part_second.grd" || { echo "SETNOD TEST: FAIL (shypre -partition failed for part_second.grd, log $P/grid_second/shypre.log)"; exit 1; }

#--- the case: one hour with the open boundary and the river of mm_lgr_b
cat > "$P/setnod.str" <<'EOF'
$title
        setnod test (#238): open boundary and river of mm_lgr_b
        setnod
        GRID/MM_coarse
$end

$para
        itanf = '2009-01-01'    itend = '2009-01-01::01:00:00'
        idt = '300s'
        idtout = '1h'
        date = 20090101
        ilin = 1
$end

$bound1
        kbound = 85 86 87 88 89 90 91 92 93 94
         95 96 97 98 99 100 101 102 103 104 105
        106 107 108 109 110 111 112 113 114 115
        116 117 118 119 120 121 122 123 124 125
        126 127 128 129 130 131 132 133 134 135
        136 137 138 139 140 141 142 143 144 145
        146 147 148 149 150 151 152 153 154 155
        156 157 158 159 160 161 162 163 164 165
        166 167 168 169 170 171 172 173 174 175
        176 177
        ibtyp = 1
        boundn = 'INPUT/level_Mar_Menor.dat'
$end

$bound2
        kbound = 218
        ibtyp = 3
        boundn = 'INPUT/river.txt'
        intpol = 2
        zfact = 50
$end
EOF

#--- the runs: NAME NP BASIN (NP 1: a plain run without mpirun)
RUNS="serial 1 metis
np2 2 metis
np4 4 metis
np8 8 metis
first4 4 first
second4 4 second"

run() {  # NAME NP BASIN
  local d="$P/run_$1" r
  mkdir "$d" && ln -s "../grid_$3" "$d/GRID" && ln -s "$HERE/INPUT" "$d/INPUT" \
    && cp "$P/setnod.str" "$d/" || { fail "$1: cannot set up $d"; return; }
  if [ "$2" = 1 ]; then
    ( cd "$d" && SHYFEM_SETNOD_DUMP="$d/setnod" timeout 600 nice -n 10 \
        shyfem setnod.str < /dev/null > run.log 2>&1 )
  else
    # stdin from /dev/null: mpirun would read the list of runs
    ( cd "$d" && SHYFEM_SETNOD_DUMP="$d/setnod" timeout 600 nice -n 10 \
        mpirun --oversubscribe -np "$2" -x SHYFEM_SETNOD_DUMP shyfem setnod.str \
        < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" = 0 ] && grep -q "simulation end" "$d/run.log"; then
    echo "  $1 ($2 process(es), basin $3): ended"
  else
    echo "  $1 ($2 process(es), basin $3): DID NOT END (exit code $r)"
    grep -E 'error stop|external node number|the node is' "$d/run.log" | sort | uniq -c | sed 's/^/      /'
    fail "$1 did not end (exit code $r, log $d/run.log)"
  fi
  if [ "$3" = metis ]; then
    if grep -q 'using these partitiones' "$d/run.log"; then
      fail "$1: the basin carried a partition, the METIS partition was not used"
    fi
  elif [ "$2" -gt 1 ] && ! grep -q 'using these partitiones' "$d/run.log"; then
    fail "$1: the log does not say 'using these partitiones' (the hand-written partition was not used)"
  fi
}

echo "=== runs"
while read -r name np basin; do run "$name" "$np" "$basin"; done <<< "$RUNS"

#--- the classification of every process against the serial run
echo "=== classification against the serial run (calls 1 to 3 of setnod)"
ARGS=()
while read -r name np basin; do
  [ "$name" = serial ] && continue
  ARGS+=("$name" "$np" "$P/run_$name")
done <<< "$RUNS"
python3 - "$HERE/GRID/MM_coarse.grd" "$P/run_serial" "${ARGS[@]}" <<'PY' || rc=1
import math
import os
import sys

NCALL = 3
ATOL = 1e-3	# degrees; the dump writes the angle sums to 1e-4
grd, serdir, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
mesh = set()
with open(grd) as fh:
    for line in fh:
        p = line.split()
        if p and p[0] == '1':
            mesh.add(int(p[1]))
NAMES = {0: 'inner', -1: 'boundary', -2: 'out of system'}


def name(v):
    return NAMES.get(v, 'open boundary %d' % v if v > 0 else str(v))


def read(path):
    """lines of one dump file: {(call, node): (inodv, angle)}, stop notes"""
    val, notes = {}, []
    with open(path) as fh:
        for line in fh:
            if line.startswith('#'):
                notes.append(line[1:].strip())
                continue
            p = line.split()
            if len(p) != 4:
                continue
            try:
                ang = float(p[3])
            except ValueError:		# e.g. the asterisks of an overflow
                ang = float('nan')
            val[(int(p[0]), int(p[1]))] = (int(p[2]), ang)
    return val, notes


bad = False
ser_path = os.path.join(serdir, 'setnod.0.txt')
if not os.path.isfile(ser_path):
    print('  serial: no dump file %s' % ser_path)
    sys.exit(1)
ser, notes = read(ser_path)
for c in range(1, NCALL + 1):
    got = {k for (cc, k) in ser if cc == c}
    if got != mesh:
        print('  serial: call %d holds %d of the %d nodes' % (c, len(got), len(mesh)))
        bad = True
nclass = {}
for (c, k), (v, a) in ser.items():
    if c == 1:
        nclass[name(v)] = nclass.get(name(v), 0) + 1
# a NaN would pass every tolerance comparison below
nonfin = sorted({k for (c, k), (v, a) in ser.items() if not math.isfinite(a)})
if nonfin:
    print('  serial: angle sum not finite at %d nodes (first %s)' % (len(nonfin), nonfin[:10]))
    bad = True
print('  serial: %d nodes, %s' % (len(mesh), ', '.join('%s %d' % kv for kv in sorted(nclass.items()))))

for i in range(0, len(rest), 3):
    run, np_, d = rest[i], int(rest[i + 1]), rest[i + 2]
    ncmp, wrong, calls_bad, stops = 0, {}, [], []
    seen = {c: set() for c in range(1, NCALL + 1)}	# nodes held, per call
    nang, kang, dang = 0, set(), 0.0	# angle sums off by more than ATOL
    nfin, kfin = 0, set()		# angle sums that are not finite
    for r in range(np_):
        path = os.path.join(d, 'setnod.%d.txt' % r)
        if not os.path.isfile(path):
            calls_bad.append('rank %d: no file' % r)
            continue
        val, notes = read(path)
        stops += ['rank %d: %s' % (r, n) for n in notes]
        calls = sorted({c for (c, k) in val})
        if calls != list(range(1, NCALL + 1)):
            calls_bad.append('rank %d: calls %s' % (r, calls))
        # a process holds the same nodes at every call: a dump that
        # lacks lines of a call (truncated) differs from its call 1
        held = {c: {k for (cc, k) in val if cc == c} for c in range(1, NCALL + 1)}
        for c in range(2, NCALL + 1):
            if held[c] != held[1]:
                calls_bad.append('rank %d: call %d holds %d nodes, call 1 holds %d'
                                 % (r, c, len(held[c]), len(held[1])))
        for (c, k), (v, a) in sorted(val.items()):
            if c in seen:
                seen[c].add(k)
            if (c, k) not in ser:
                wrong.setdefault(k, []).append((r, c, v, a, None))
                continue
            ncmp += 1
            sv, sa = ser[(c, k)]
            if v != sv:
                wrong.setdefault(k, []).append((r, c, v, a, sa))
            if not (math.isfinite(a) and math.isfinite(sa)):
                # a NaN passes "abs(a - sa) > ATOL" as false
                nfin += 1
                kfin.add(k)
            elif abs(a - sa) > ATOL:
                nang += 1
                kang.add(k)
                dang = max(dang, abs(a - sa))
    covered = all(seen[c] == mesh for c in seen)
    ok = not wrong and not calls_bad and covered and nang == 0 and nfin == 0
    print('  %-8s %d processes: node copies compared %d, nodes held (calls %s) %s of %d, misclassified nodes %d,'
          ' angle sums off by more than %g deg: %d copies of %d nodes (largest %.4f), not finite: %d copies of %d nodes: %s'
          % (run, np_, ncmp, '/'.join(str(c) for c in seen), '/'.join(str(len(seen[c])) for c in seen),
             len(mesh), len(wrong), ATOL, nang, len(kang), dang, nfin, len(kfin), 'ok' if ok else 'FAIL'))
    for s in stops:
        print('      ' + s)
    for s in calls_bad:
        print('      ' + s)
    for c in seen:
        if seen[c] != mesh:
            miss = sorted(mesh - seen[c])
            print('      nodes held by no process at call %d: %d (first %s)' % (c, len(miss), miss[:10]))
    for k in sorted(wrong):
        # the first call that differs, as an example; then all calls
        c0 = min(w[1] for w in wrong[k])
        first = [w for w in wrong[k] if w[1] == c0]
        sv = ser.get((c0, k))
        ranks = sorted({w[0] for w in first})
        vals = sorted({name(w[2]) for w in first})
        angs = sorted({'%.2f' % w[3] for w in first})
        calls = sorted({w[1] for w in wrong[k]})
        stext = '%s (%.2f deg)' % (name(sv[0]), sv[1]) if sv else 'not in the serial dump'
        print('      node %5d, call %d: serial %s, here %s (%s deg) on ranks %s; calls that differ %s'
              % (k, c0, stext, '/'.join(vals), '/'.join(angs), ranks, calls))
    bad = bad or not ok
sys.exit(1 if bad else 0)
PY

if [ "$rc" = 0 ]; then echo "SETNOD TEST: PASS"; else echo "SETNOD TEST: FAIL"; fi
echo "$P"
exit "$rc"
