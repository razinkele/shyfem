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
#   4. ../restart_strip (a 6-node mesh), when NP >= 3: stops with the
#      "use fewer MPI processes" message and a non-zero exit, with no
#      floating-point exception
#   5. mm_lgr_w (Lagrangian particles, one release polygon around the
#      whole basin, so that the release is split between processes on any
#      partition): the particle file of NP processes against the serial one
#      with check_lgr_mpi.sh, mode pos (positions against the floors
#      measured on the serial reference, layers, types, times), mode ids
#      (the same ids in the same blocks at every output, counts per block,
#      valid elements and layers), run at levdbg = 2 (LGR_LEVDBG=2: the
#      built-in consistency check of the particle state is active at every
#      step on NP processes and must stay silent), and mode handover with
#      --min-changed 1 (the debug dump at levdbg = 3: a particle that
#      changes process must stay where the serial run has it, judged
#      against the particles that stay on their process; at least one pair
#      must change process).  The geographic basin GRID/MM_geo.bas, which
#      `make init` does not build, is made first when it is missing
#      (shypre -noopti MM_geo.grd).  Logs: mm_lgr_w.pos.gate.log,
#      mm_lgr_w.ids.gate.log, mm_lgr_w.handover.gate.log, and those of the
#      driver.
# The runs of checks 1 to 3 on NP > 1 processes must also show NP
# processes: the line "shympi initialized: ID NP" once from each rank 0
# to NP-1 (an mpirun that does not match the binary's MPI, or a binary
# without MPI, would run NP serial copies, which end and write the
# serial results).
#
# Needs shyfem, shypre, mpirun and python3 on PATH (an OpenMPI build of
# shyfem), and `make init` done.
# Usage:  ./check_mpi.sh [NP]
#------------------------------------------------------------------------
set -u
NP="${1:-4}"
cd "$(dirname "$0")" || exit 1
rc=0
fail() { echo "MPI GATE FAIL: $*"; rc=1; }
mpi() { mpirun --oversubscribe -np "$NP" shyfem "$1.str" > "$1.mpi.log" 2>&1; }
# ranks_ok LOG: for NP > 1, each of the NP ranks printed once "shympi
# initialized: ID NP" (shympi_setup, src/utils/shympi/mpi_node.f90, only
# in a parallel run). An mpirun that does not match the binary's MPI, or
# a binary without MPI, runs NP serial copies that end and write the
# serial results, and would pass the checks below.
ranks_ok() {
  [ "$NP" -gt 1 ] || return 0
  awk -v np="$NP" '/shympi initialized:/ { n++; if ($4 == np && $3 >= 0 && $3 < np) seen[$3]++ }
    END { ok = (n == np); for (i = 0; i < np; i++) if (seen[i] != 1) ok = 0; exit !ok }' "$1"
}
ranks_msg() { echo "$1: the log does not show $NP MPI processes ($(grep -c 'shympi initialized:' "$1") 'shympi initialized:' lines, expected one from each rank 0 to $((NP - 1)))"; }

echo "=== 1. mm_hyd_01: serial vs $NP processes"
if shyfem mm_hyd_01.str > mm_hyd_01.serial.log 2>&1 && grep -q "simulation end" mm_hyd_01.serial.log; then
  cp mm_hyd_01.inf mm_hyd_01.serial.inf
  if mpi mm_hyd_01 && grep -q "simulation end" mm_hyd_01.mpi.log; then
    if ! ranks_ok mm_hyd_01.mpi.log; then
      fail "$(ranks_msg mm_hyd_01.mpi.log)"
    else
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
    fi
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
elif ! ranks_ok mm_hyd_11.mpi.log; then
  fail "$(ranks_msg mm_hyd_11.mpi.log)"
else
  echo "stopped as expected: $(grep 'not supported with MPI' mm_hyd_11.mpi.log | tr -s ' ')"
fi

echo "=== 3. restart written and read on $NP processes"
for sim in mm_rst_write mm_rst_read; do
  if mpi "$sim" && grep -q "simulation end" "$sim.mpi.log"; then
    if ranks_ok "$sim.mpi.log"; then echo "$sim: ended"; else fail "$(ranks_msg "$sim.mpi.log")"; fi
  else
    tail -5 "$sim.mpi.log"; fail "$sim did not end on $NP processes"
  fi
done

echo "=== 4. a 6-node mesh on $NP processes must stop with a clear message"
if [ "$NP" -lt 3 ]; then
  echo "skipped: the 6-node mesh can be split into $NP domains"
elif ! ( cd ../restart_strip && shypre -silent strip.grd > shypre.mpi.log 2>&1 ); then
  fail "shypre failed on ../restart_strip/strip.grd"
else
  log=../restart_strip/strip_rst.mpi.log
  if ( cd ../restart_strip && mpirun --oversubscribe -np "$NP" shyfem strip_rst.str > strip_rst.mpi.log 2>&1 ); then
    fail "strip_rst ran on $NP processes: a 6-node mesh cannot fill $NP domains"
  elif [ "$(grep -c 'use fewer MPI processes' "$log")" != 1 ]; then
    tail -5 "$log"; fail "strip_rst stopped without the 'use fewer MPI processes' message (or printed it more than once)"
  elif grep -q 'SIGFPE' "$log"; then
    fail "strip_rst: a process died with a floating-point exception"
  else
    echo "stopped as expected:$(grep -B3 'use fewer MPI processes' "$log" | tr -s ' ' | tr '\n' ';')"
  fi
fi

echo "=== 5. mm_lgr_w (particles): particle file of $NP processes vs serial"
if [ ! -f GRID/MM_geo.bas ] && ! ( cd GRID && shypre -noopti MM_geo.grd > shypre_geo.mpi.log 2>&1 ); then
  tail -5 GRID/shypre_geo.mpi.log; fail "shypre failed on GRID/MM_geo.grd"
else
  for mode in pos ids handover; do
    log="mm_lgr_w.$mode.gate.log"
    # the consistency check (levdbg 2) for ids only; an empty LGR_LEVDBG
    # counts as unset (the driver refuses LGR_LEVDBG in mode handover)
    lev=""; extra=""
    [ "$mode" = ids ] && lev=2
    [ "$mode" = handover ] && extra="--min-changed 1"
    if LGR_LEVDBG="$lev" bash check_lgr_mpi.sh mm_lgr_w "$NP" "$mode" $extra > "$log" 2>&1; then
      grep -E '^(floor|tt):|^LGR COMPARE|^lgr inf: (energy|identical|lagrange)|consistency check|^  changed process +[0-9]|^  rule:|^lgr_dbg_compare part:' "$log" \
        | sed 's/^ *//' | cut -c1-200 | sed "s/^/mm_lgr_w $mode: /"
    else
      tail -25 "$log"; fail "mm_lgr_w: mode $mode of check_lgr_mpi.sh failed on $NP processes (log: $log)"
    fi
  done
fi

if [ "$rc" = 0 ]; then echo "MPI GATE: PASS"; else echo "MPI GATE: FAIL"; fi
exit "$rc"
