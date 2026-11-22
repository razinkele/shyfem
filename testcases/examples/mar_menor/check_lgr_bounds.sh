#!/bin/bash
#------------------------------------------------------------------------
# Bounds-checked build of a commit and the Lagrangian test cases run with
# it: the gate that catches a read outside an array (the kind of issue
# #234, where a departed particle's negative element number indexed ilhv
# and the result changed with the contents of memory).
#
# Usage:  ./check_lgr_bounds.sh [COMMIT]          (default HEAD)
#
# Builds COMMIT of this repository with FGNU_BOUNDS=-fcheck=bounds in a
# throwaway git work tree (made in a folder from mktemp -d under
# ${TMPDIR:-/tmp}, removed at the end), with PATH=/usr/bin:$PATH so that the
# OpenMPI compiler wrapper is used; extra make arguments can be given in
# the environment variable LGR_MAKE_FLAGS (for the NetCDF build of the
# development machine: LGR_MAKE_FLAGS="NETCDF=true NETCDFDIR=/usr
# NETCDFFDIR=/usr/local").  The runs use the tracked inputs of COMMIT's
# test folder (git archive; GRID/MM_coarse.bas is the tracked file) and
# GRID/MM_geo.bas built with the new build's shypre.  Serially: mm_lgr_a,
# _b, _c, _e, mm_lgr (case D) and _a, _b, _c at levdbg = 3 (debug dump and
# self-tests); on several processes: a on 8, 4, 3; b on 4; c on 4, 3; e on
# 4; mm_lgr on 4; the levdbg = 3 copies of a, b, c on 4.  Each run has a
# timeout of 1500 s and is niced.
#
# A run with a "Fortran runtime" line (the message of a failed bounds
# check) is a finding; a run that does not end for another reason is listed
# apart and is not a bounds finding.  Prints "BOUNDS GATE: PASS" or "FAIL"
# (also FAIL when no compile line carried the flag) and exits 0 or 1; the
# run logs stay in the scratch folder (its path is the last line).
#------------------------------------------------------------------------
set -u
H="${1:-HEAD}"
HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
W="$(git -C "$HERE" rev-parse --show-toplevel)" || { echo "BOUNDS GATE: FAIL (not inside a git checkout)"; exit 1; }
MM="${HERE#"$W"/}"		# testcases/examples/mar_menor
P="$(mktemp -d "${TMPDIR:-/tmp}/lgrbounds.XXXXXX")" || exit 1
echo "bounds gate on $(git -C "$W" rev-parse --short "$H"): $P  $(date +%H:%M:%S)"
git -C "$W" worktree add --detach "$P/wt" "$H" > "$P/wt_add.log" 2>&1 || { cat "$P/wt_add.log"; exit 1; }
# shellcheck disable=SC2086
( cd "$P/wt" && PATH=/usr/bin:$PATH nice -n 10 make fem FGNU_BOUNDS=-fcheck=bounds ${LGR_MAKE_FLAGS:-} > "$P/build.log" 2>&1 )
brc=$?
echo "bounds build rc=$brc  libmpi.so.40: $(ldd "$P/wt/src/shyfem/shyfem" 2>/dev/null | grep -c 'libmpi.so.40')  compile lines with -fcheck=bounds: $(grep -c 'fcheck=bounds' "$P/build.log")"
nflag=$(grep -c 'fcheck=bounds' "$P/build.log")
if [ ! -x "$P/wt/src/shyfem/shyfem" ]; then
  tail -15 "$P/build.log"
  git -C "$W" worktree remove --force "$P/wt" > /dev/null 2>&1
  echo "BOUNDS GATE: FAIL (the build failed)"; exit 1
fi
mkdir "$P/mm" || exit 1
git -C "$W" archive "$H" "$MM" | tar -x -C "$P/mm" --strip-components=3 || { echo "BOUNDS GATE: FAIL (git archive)"; exit 1; }
export PATH=$P/wt/bin:/usr/bin:$PATH
( cd "$P/mm/GRID" && shypre -noopti MM_geo.grd > shypre_geo.log 2>&1 ) || { echo "BOUNDS GATE: FAIL (shypre MM_geo.grd)"; exit 1; }
cd "$P/mm" || exit 1
for c in mm_lgr_a mm_lgr_b mm_lgr_c; do
  awk '{ print } !done && /^\$para[ \t\r]*$/ { print "        levdbg = 3"; done = 1 }' $c.str > ${c}_dbg.str
done
nbad=0; nother=0
report() { # name logfile : a bounds failure is a run with a Fortran runtime message; other non-ending runs are listed apart
  local nrt; nrt=$(grep -c 'Fortran runtime' "$2")
  if [ "$nrt" != 0 ]; then
    nbad=$((nbad+1)); echo "$1: RUNTIME MESSAGE ($nrt)"
    grep -h -A1 '^At line' "$2" | grep -v '^--' | sort | uniq -c | cut -c1-190 | head -6
  elif grep -q 'simulation end' "$2"; then
    echo "$1: ended (0 runtime messages)"
  else
    nother=$((nother+1)); echo "$1: did not end, no runtime message (not a bounds finding):"
    grep -m1 'Program received' "$2" | cut -c1-100
    grep -m1 -A4 'Backtrace for this error' "$2" | grep -o 'in [a-z_0-9]*_$\|at .*f90:[0-9]*' | head -3 | tr '\n' ' '; echo
    grep -m2 'error stop\|ERROR STOP' "$2" | cut -c1-120
  fi
}
for c in mm_lgr_a mm_lgr_b mm_lgr_c mm_lgr_e mm_lgr mm_lgr_a_dbg mm_lgr_b_dbg mm_lgr_c_dbg; do
  timeout 1500 nice -n 19 shyfem $c.str > $c.ser.log 2>&1; report "serial $c" $c.ser.log
done
for run in "mm_lgr_a 8" "mm_lgr_a 4" "mm_lgr_a 3" "mm_lgr_b 4" "mm_lgr_c 4" "mm_lgr_c 3" "mm_lgr_e 4" "mm_lgr 4" "mm_lgr_a_dbg 4" "mm_lgr_b_dbg 4" "mm_lgr_c_dbg 4"; do
  set -- $run
  timeout 1500 nice -n 19 mpirun --oversubscribe -np $2 shyfem $1.str > $1.np$2.log 2>&1; report "MPI $1 np$2" $1.np$2.log
done
cd "$P" && git -C "$W" worktree remove --force "$P/wt" > "$P/wt_remove.log" 2>&1 && echo "throwaway work tree removed" || cat "$P/wt_remove.log"
echo "runs with a runtime message: $nbad; runs that did not end for another reason: $nother; compile lines with the flag: $nflag"
if [ "$nflag" = 0 ]; then echo "BOUNDS GATE: FAIL (the build was not bounds-checked)"; rc=1
elif [ $nbad = 0 ]; then echo "BOUNDS GATE: PASS"; rc=0
else echo "BOUNDS GATE: FAIL ($nbad runs)"; rc=1; fi
echo "$(date +%H:%M:%S)  logs in $P/mm"
exit "$rc"
