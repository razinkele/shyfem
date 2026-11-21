#!/bin/bash
#------------------------------------------------------------------------
# MPI gate for the Mar Menor test cases.
#
# A run that ends on several processes is not yet a correct run, and a
# feature that only works serially should say so. This gate checks, on
# NP processes (default 4):
#   1. mm_hyd_01: the per-step energy lines of the .inf file agree with
#      the serial run (relative difference <= 1e-4)
#   2. mm_hyd_11 (tilted open boundary, serial only): stops with the
#      "not supported with MPI" message and a non-zero exit
#   3. mm_rst_write, then mm_rst_read: a restart written and read on NP
#      processes ends normally
#
# Needs shyfem and python3 on PATH, an MPI build, and `make init` done.
# Usage:  ./check_mpi.sh [NP]
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
cd "$(dirname "$0")" || exit 1
rc=0
fail() { echo "MPI GATE FAIL: $*"; rc=1; }
mpi() { mpirun --oversubscribe -np "$NP" shyfem "$1.str" > "$1.mpi.log" 2>&1; }

echo "=== 1. mm_hyd_01: serial vs $NP processes"
if shyfem mm_hyd_01.str > mm_hyd_01.serial.log 2>&1 && grep -q "simulation end" mm_hyd_01.serial.log; then
  cp mm_hyd_01.inf mm_hyd_01.serial.inf
  if mpi mm_hyd_01 && grep -q "simulation end" mm_hyd_01.mpi.log; then
    python3 - mm_hyd_01.serial.inf mm_hyd_01.inf <<'PY' || fail "mm_hyd_01: energy lines differ between serial and MPI"
import sys


def energy(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            if line.lstrip().startswith("energy:"):
                rows.append([float(x) for x in line.split()[2:]])
    return rows


a, b = energy(sys.argv[1]), energy(sys.argv[2])
if not a or len(a) != len(b):
    print(f"energy lines: serial {len(a)}, MPI {len(b)}")
    sys.exit(1)
scale = [max(abs(r[j]) for r in a) or 1.0 for j in range(len(a[0]))]
worst = max(abs(x - y) / scale[j] for ra, rb in zip(a, b) for j, (x, y) in enumerate(zip(ra, rb)))
print(f"{len(a)} energy lines, largest relative difference {worst:.2e} (limit 1e-4)")
sys.exit(0 if worst <= 1e-4 else 1)
PY
  else
    tail -5 mm_hyd_01.mpi.log; fail "mm_hyd_01 did not end on $NP processes"
  fi
else
  tail -5 mm_hyd_01.serial.log; fail "mm_hyd_01 did not end serially"
fi

echo "=== 2. mm_hyd_11 (boundary tilting) must stop with a clear message"
if mpi mm_hyd_11; then
  fail "mm_hyd_11 ran on $NP processes: boundary tilting is serial only"
elif [ "$(grep -c 'not supported with MPI' mm_hyd_11.mpi.log)" != 1 ]; then
  tail -5 mm_hyd_11.mpi.log; fail "mm_hyd_11 stopped without the 'not supported with MPI' message (or printed it more than once)"
else
  echo "stopped as expected: $(grep 'not supported with MPI' mm_hyd_11.mpi.log | tr -s ' ')"
fi

echo "=== 3. restart written and read on $NP processes"
for sim in mm_rst_write mm_rst_read; do
  if mpi "$sim" && grep -q "simulation end" "$sim.mpi.log"; then
    echo "$sim: ended"
  else
    tail -5 "$sim.mpi.log"; fail "$sim did not end on $NP processes"
  fi
done

if [ "$rc" = 0 ]; then echo "MPI GATE: PASS"; else echo "MPI GATE: FAIL"; fi
exit "$rc"
