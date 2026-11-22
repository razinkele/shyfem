#!/bin/bash
#------------------------------------------------------------------------
# Checks of the fixes of the Lagrangian module that followed #217 (the
# module on several MPI processes).  Each mode runs the model in a scratch
# copy of this folder (made with mktemp under ${TMPDIR:-/tmp}, removed at
# the end when the mode passes, kept with its path printed when it fails)
# with the shyfem first on PATH, and prints "<MODE>: PASS" or "FAIL".
#
# Usage:  ./check_lgr_fixes.sh MODE
#
#   stk-omp   (#243) the Stokes drift case mm_lgr_e with 4 OpenMP threads
#             (nomp = 4 in $para) and with 1 (nomp = 1), serially and on 4
#             MPI processes: the four runs must end, the 4-thread logs must
#             have the line "used OMP threads: 4" (the build compiles the
#             OpenMP directives: -fopenmp is always in FFLAGS), and the
#             particle file of 4 threads must be byte-identical (cmp) to
#             that of 1 thread, serially and on 4 processes.  This check
#             cannot fail on the data race it guards against (lag_stk set
#             a saved flag on its first call inside the parallel loop):
#             every thread wrote the same value, so no run shows it; it
#             shows that the change of the initialisation (once, before the
#             loop) leaves the result of 1 and 4 threads unchanged.
#
# A run has ended only if its launcher exits with 0 and its log has
# "simulation end".  Needs shyfem, mpirun (Open MPI) and python3 on PATH,
# and `make init` plus (cd GRID && shypre -noopti MM_geo.grd) done here.
# Exit code 0 on PASS, 1 on FAIL, 2 on a usage error.
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
MODE="${1:-}"
NP=4
rc=0

usage() { echo "usage: $0 stk-omp"; exit 2; }
fail() { echo "  FAIL: $*"; rc=1; }

case "$MODE" in
  stk-omp) ;;
  *) usage ;;
esac

for t in shyfem mpirun python3; do
  command -v "$t" > /dev/null 2>&1 || { echo "$MODE: FAIL ($t is not on PATH)"; exit 1; }
done
for b in GRID/MM_geo.bas GRID/MM_coarse.bas; do
  [ -f "$HERE/$b" ] || { echo "$MODE: FAIL ($b is missing: run 'make init' and '(cd GRID && shypre -noopti MM_geo.grd)' in $HERE)"; exit 1; }
done

SCR="$(mktemp -d "${TMPDIR:-/tmp}/lgr_fixes.XXXXXX")" || { echo "$MODE: FAIL (mktemp)"; exit 1; }
cp -r "$HERE" "$SCR/mm" || { echo "$MODE: FAIL (cannot copy the test folder)"; exit 1; }
W="$SCR/mm"
rm -f "$W"/*.shy "$W"/*.inf "$W"/*.ext "$W"/*.log

finish() {
  if [ "$rc" = 0 ]; then
    rm -rf "$SCR"
    echo "$MODE: PASS"
  else
    echo "  logs kept in $SCR"
    echo "$MODE: FAIL"
  fi
  exit "$rc"
}

# with_para SRC DST LINE: copy of SRC.str with LINE right after its $para
# line and the run name (third line of $title) set to DST
with_para() {
  awk -v line="$3" -v name="$2" '
    /^\$title/ { t = 1; nt = 0 }
    t && !/^\$/ { nt++; if( nt == 2 ) { print "        " name; next } }
    /^\$end/ { t = 0 }
    { print }
    !done && /^\$para[ \t\r]*$/ { print "        " line; done = 1 }
  ' "$W/$1.str" > "$W/$2.str"
}

# run NAME LOG LAUNCHER...: run NAME.str in the scratch folder; true if
# the launcher exited with 0 and the log has "simulation end"
run() {
  local name="$1" log="$2" lrc; shift 2
  ( cd "$W" && nice -n 10 "$@" "$name.str" > "$log" 2>&1 )
  lrc=$?
  if [ "$lrc" != 0 ]; then
    echo "  $name: the launcher exited with code $lrc ($W/$log)"
    tail -5 "$W/$log" | sed 's/^/    /'
    return 1
  fi
  grep -q "simulation end" "$W/$log" || { echo "  $name: no 'simulation end' in $W/$log"; return 1; }
}

# threads LOG N: the log reports N OpenMP threads
threads() {
  local line
  line="$(grep -m1 'used OMP threads' "$W/$1")"
  echo "  $1: ${line:-no 'used OMP threads' line}"
  echo "$line" | grep -q "used OMP threads: *$2\$" || fail "$1 does not report $2 OpenMP threads"
}

#=============================== stk-omp (#243) ============================
if [ "$MODE" = stk-omp ]; then
  for n in 1 4; do
    with_para mm_lgr_e stk_t$n "nomp = $n"
  done
  for n in 1 4; do
    echo "=== mm_lgr_e, $n OpenMP thread(s): serial and on $NP processes"
    run stk_t$n stk_t$n.serial.log shyfem || fail "serial run with $n thread(s) did not end"
    mv "$W/stk_t$n.lgr.shy" "$W/stk_t$n.serial.lgr.shy" 2> /dev/null
    run stk_t$n stk_t$n.np$NP.log mpirun --oversubscribe -np $NP shyfem || fail "run on $NP processes with $n thread(s) did not end"
    mv "$W/stk_t$n.lgr.shy" "$W/stk_t$n.np$NP.lgr.shy" 2> /dev/null
  done
  threads stk_t4.serial.log 4
  threads stk_t4.np$NP.log 4
  threads stk_t1.serial.log 1
  for v in serial np$NP; do
    a="$W/stk_t1.$v.lgr.shy"; b="$W/stk_t4.$v.lgr.shy"
    if [ ! -s "$a" ] || [ ! -s "$b" ]; then fail "$v: particle file missing"
    elif cmp -s "$a" "$b"; then echo "  $v: particle file of 4 threads identical to 1 thread ($(stat -c %s "$a") bytes)"
    else fail "$v: particle file of 4 threads differs from 1 thread"; cmp "$a" "$b" | head -1 | sed 's/^/    /'
    fi
  done
  finish
fi
