#!/bin/bash
#------------------------------------------------------------------------
# Order of the element contributions at every own node on several
# processes against the serial run (issue #263).
#
# conz3d_omp (scalar transport) and hydro_zeta (water-level matrix, every
# solver but PETSc) add the contributions of the elements around a node
# subset after subset: the independent element subsets (colors) of
# src/shyfem/subset.f90, where no two elements of a subset share a node.
# The colors decide the order of the additions at a node, and with it the
# rounding of the double-precision sums.  Before the fix of #263 every
# process colored its own part of the mesh, so a node got its elements in
# another order than in a serial run; the sums differed in the last bits
# at every step and, now and then, a salinity or temperature rounded to
# the next single-precision value (venlag_assim on 4 processes, see
# check_mpi_venlag.sh).  This test looks at the order itself, so it does
# not depend on such a rounding.
#
# The order is read from the debug dump of subset.f90: with the
# environment variable SHYFEM_SUBSET_DUMP=PREFIX every process writes, at
# start-up, PREFIX.RANK.txt with one line per own node (the nodes whose
# sums the loops use): the external node number, the number of its
# elements and, in the order the subset loops reach them, the external
# number and the subset of each element (subroutine subset_order_dump).
# Without the variable the model writes nothing.
#
# The case: GRID/MM_coarse.grd, a closed 2D basin, two time steps of 300 s,
# run serially, on 2, 4 and 8 processes with the METIS partition the model
# makes, and on 4 processes with each of the two hand-written partitions
# of docs/reviews/evidence/2026-11-lagrange-mpi/d5 (written into the basin
# with shypre -partition).  Required, for every process of every
# multi-process run: each own node has the elements of the serial run in
# the serial order and with the serial subsets; every node of the mesh is
# an own node of exactly one process; and the serial dump holds every node
# of the mesh.  Also required: every run ends (exit code 0 and
# "simulation end" in its log; timeout 300 s each); the log of a
# multi-process run has the line "shympi initialized: ID NP" once from
# each rank 0 to NP-1 (so that NP serial runs, from an mpirun that does
# not match the binary's MPI or a binary without MPI, cannot pass); the
# log of a run with a hand-written partition says "using these
# partitiones" (the partition of the basin was used), the log of a METIS
# run does not.
#
# Usage:  ./check_subset_order_mpi.sh
# Needs shyfem, shypre, mpirun and python3 on PATH (an OpenMPI build).
# Works in a folder made with mktemp -d under ${TMPDIR:-/tmp}: GRID/
# MM_coarse.grd is copied there and its basins are built there with
# shypre (a partition goes into a basin of that folder only), so nothing
# in this folder changes.  The folder is kept (its path is the last
# line).  Takes about 3 s on the development machine.  Prints "SUBSET
# ORDER TEST: PASS" or "SUBSET ORDER TEST: FAIL" and exits 0 or 1.
#------------------------------------------------------------------------
set -u
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
W="$(git -C "$HERE" rev-parse --show-toplevel)" || { echo "SUBSET ORDER TEST: FAIL (not inside a git checkout)"; exit 1; }
D5="$W/docs/reviews/evidence/2026-11-lagrange-mpi/d5"
for t in shyfem shypre mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "SUBSET ORDER TEST: FAIL ($t is not on PATH)"; exit 1; }
done
for f in "$HERE/GRID/MM_coarse.grd" "$D5/part_first.grd" "$D5/part_second.grd"; do
  [ -f "$f" ] || { echo "SUBSET ORDER TEST: FAIL (missing $f)"; exit 1; }
done
P="$(mktemp -d "${TMPDIR:-/tmp}/subsetorder.XXXXXX")" || exit 1
echo "subset order test: $(command -v shyfem), in $P  $(date +%H:%M:%S)"
rc=0
fail() { echo "SUBSET ORDER TEST FAIL: $*"; rc=1; }

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
mkbasin metis || { echo "SUBSET ORDER TEST: FAIL (shypre failed for the plain basin, log $P/grid_metis/shypre.log)"; exit 1; }
mkbasin first "$D5/part_first.grd" || { echo "SUBSET ORDER TEST: FAIL (shypre -partition failed for part_first.grd, log $P/grid_first/shypre.log)"; exit 1; }
mkbasin second "$D5/part_second.grd" || { echo "SUBSET ORDER TEST: FAIL (shypre -partition failed for part_second.grd, log $P/grid_second/shypre.log)"; exit 1; }

#--- the case: two time steps in the closed basin
cat > "$P/subset.str" <<'EOF'
$title
        subset order test (#263): closed basin, two time steps
        subset
        GRID/MM_coarse
$end

$para
        itanf = '2009-01-01'    itend = '2009-01-01::00:10:00'
        idt = '300s'
        idtout = '1h'
        date = 20090101
        ilin = 1
$end
EOF

#--- the runs: NAME NP BASIN (NP 1: a plain run without mpirun)
RUNS="serial 1 metis
np2 2 metis
np4 4 metis
np8 8 metis
first4 4 first
second4 4 second"

# ranks_ok LOG NP: each of the NP ranks printed once "shympi initialized:
# ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90; printed only when
# the run is parallel)
ranks_ok() {
  awk -v np="$2" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
run() {  # NAME NP BASIN
  local d="$P/run_$1" r
  mkdir "$d" && ln -s "../grid_$3" "$d/GRID" && cp "$P/subset.str" "$d/" \
    || { fail "$1: cannot set up $d"; return; }
  if [ "$2" = 1 ]; then
    ( cd "$d" && SHYFEM_SUBSET_DUMP="$d/subset" timeout 300 nice -n 10 \
        shyfem subset.str < /dev/null > run.log 2>&1 )
  else
    # stdin from /dev/null: mpirun would read the list of runs
    ( cd "$d" && SHYFEM_SUBSET_DUMP="$d/subset" timeout 300 nice -n 10 \
        mpirun --oversubscribe -np "$2" -x SHYFEM_SUBSET_DUMP shyfem subset.str \
        < /dev/null > run.log 2>&1 )
  fi
  r=$?
  if [ "$r" = 0 ] && grep -q "simulation end" "$d/run.log"; then
    echo "  $1 ($2 process(es), basin $3): ended"
  else
    echo "  $1 ($2 process(es), basin $3): DID NOT END (exit code $r)"
    tail -3 "$d/run.log" | sed 's/^/      /'
    fail "$1 did not end (exit code $r, log $d/run.log)"
  fi
  if [ "$2" -gt 1 ] && ! ranks_ok "$d/run.log" "$2"; then
    fail "$1: the log does not show $2 MPI processes ($(grep -c 'shympi initialized:' "$d/run.log") 'shympi initialized:' lines, expected one from each rank 0 to $(( $2 - 1 )))"
  fi
  if [ "$3" = metis ]; then
    if grep -q 'using these partitiones' "$d/run.log"; then
      fail "$1: the basin carried a partition, the METIS partition was not used"
    fi
  elif ! grep -q 'using these partitiones' "$d/run.log"; then
    fail "$1: the log does not say 'using these partitiones' (the hand-written partition was not used)"
  fi
}

echo "=== runs"
while read -r name np basin; do run "$name" "$np" "$basin"; done <<< "$RUNS"

#--- the order at every own node against the serial run
echo "=== element order at the own nodes against the serial run"
ARGS=()
while read -r name np basin; do
  [ "$name" = serial ] && continue
  ARGS+=("$name" "$np" "$P/run_$name")
done <<< "$RUNS"
python3 - "$HERE/GRID/MM_coarse.grd" "$P/run_serial" "${ARGS[@]}" <<'PY' || rc=1
import os
import sys

grd, serdir, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
mesh = set()
with open(grd) as fh:
    for line in fh:
        p = line.split()
        if p and p[0] == '1':
            mesh.add(int(p[1]))


def read(path):
    """one dump file: {node: ((elem, subset), ...)}, nodes listed twice"""
    val, dup, badline = {}, [], 0
    with open(path) as fh:
        for line in fh:
            p = line.split()
            try:
                v = [int(x) for x in p]
            except ValueError:
                badline += 1
                continue
            if len(v) < 2 or len(v) != 2 + 2 * v[1]:
                badline += 1
                continue
            k = v[0]
            if k in val:
                dup.append(k)
            val[k] = tuple(zip(v[2::2], v[3::2]))
    return val, dup, badline


bad = False
ser_path = os.path.join(serdir, 'subset.0.txt')
if not os.path.isfile(ser_path):
    print('  serial: no dump file %s' % ser_path)
    sys.exit(1)
ser, dup, badline = read(ser_path)
if set(ser) != mesh or dup or badline:
    print('  serial: %d of the %d nodes, %d listed twice, %d unreadable lines'
          % (len(set(ser) & mesh), len(mesh), len(dup), badline))
    bad = True
nel_ser = len({e for v in ser.values() for e, c in v})
print('  serial: %d own nodes, %d elements, %d subsets'
      % (len(ser), nel_ser, len({c for v in ser.values() for e, c in v})))

for i in range(0, len(rest), 3):
    run, np_, d = rest[i], int(rest[i + 1]), rest[i + 2]
    owner, problems = {}, []
    norder, nsub, examples = 0, 0, []
    for r in range(np_):
        path = os.path.join(d, 'subset.%d.txt' % r)
        if not os.path.isfile(path):
            problems.append('rank %d: no dump file' % r)
            continue
        val, dup, badline = read(path)
        if dup or badline:
            problems.append('rank %d: %d nodes listed twice, %d unreadable lines'
                            % (r, len(dup), badline))
        if not val:
            problems.append('rank %d: no own node' % r)
        for k, v in val.items():
            owner.setdefault(k, []).append(r)
            if k not in ser:
                problems.append('rank %d: node %d is not in the serial dump' % (r, k))
                continue
            s = ser[k]
            if [e for e, c in v] != [e for e, c in s]:
                norder += 1
                if len(examples) < 5:
                    examples.append('node %d on rank %d: serial %s, here %s'
                                    % (k, r, [e for e, c in s], [e for e, c in v]))
            elif v != s:
                nsub += 1
                if len(examples) < 5:
                    examples.append('node %d on rank %d: same order, subsets serial %s, here %s'
                                    % (k, r, [c for e, c in s], [c for e, c in v]))
    missing = sorted(mesh - set(owner))
    shared = sorted(k for k, rs in owner.items() if len(rs) > 1)
    ok = not problems and not missing and not shared and norder == 0 and nsub == 0
    print('  %-8s %d processes: own nodes %d of %d (on two processes %d, on none %d),'
          ' nodes in another order %d, in the serial order with other subsets %d: %s'
          % (run, np_, len(owner), len(mesh), len(shared), len(missing), norder, nsub,
             'ok' if ok else 'FAIL'))
    for s in problems[:10]:
        print('      ' + s)
    if missing:
        print('      nodes own on no process: first %s' % missing[:10])
    if shared:
        print('      nodes own on two processes: first %s' % shared[:10])
    for s in examples:
        print('      ' + s)
    bad = bad or not ok
sys.exit(1 if bad else 0)
PY

if [ "$rc" = 0 ]; then echo "SUBSET ORDER TEST: PASS"; else echo "SUBSET ORDER TEST: FAIL"; fi
echo "$P"
exit "$rc"
