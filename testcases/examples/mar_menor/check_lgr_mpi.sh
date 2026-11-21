#!/bin/bash
#------------------------------------------------------------------------
# Lagrangian MPI gate: one test case run serially and on NP processes, the
# results compared with the matching tool.
#
# Usage:  ./check_lgr_mpi.sh CASE NP MODE [EXTRA ARGS FOR THE TOOL ...]
#
#   CASE  mm_lgr_a | mm_lgr_b | mm_lgr_c | mm_lgr_e | mm_lgr
#         (a, b, c, e are accepted as short names)
#   NP    number of MPI processes of the second run
#   MODE  flux   debug dump of the element fluxes, serial vs MPI
#         part   debug dump of the particles (per output time), serial vs MPI
#         pos    final particle file: positions, layers, types, times
#         ids    final particle file: the ids, the counts, valid cells
#         perturb  two MPI runs (no serial run) with the debug dump, one
#                plain and one with MALLOC_PERTURB_=85; every dump file of
#                the two runs must be byte-identical (dependence of the
#                result on memory that malloc hands out)
#
# The serial outputs are renamed to CASE.serial.* (lgr.shy, hydro.shy, inf,
# log); the MPI log is CASE.npN.log.  For flux and part the run uses a
# temporary copy of the STR file with "levdbg = 3" right after the $para
# line (the run name inside the file is unchanged, so the output names are
# the same); the debug files of each run end up in CASE.serial.dbg/ and
# CASE.npN.dbg/, both made fresh by every call.
#
# Note: flux uses the relative default limit of lgr_dbg_compare.py (1e-5) for
# every case; the per-case --tol below applies to pos and part only.
# Limits: the geographic cases use --tol 1e-5, the Cartesian case mm_lgr_b
# --tol 2 (for pos and part).  The flux comparison is relative and keeps
# the default of lgr_dbg_compare.py.  Part uses --by nearest (the ids repeat
# across ranks at this stage).  Arguments after MODE come last on the tool
# command line and so replace the defaults, for example
#   ./check_lgr_mpi.sh mm_lgr_a 4 part --by id --tol 1e-3
#
# perturb: the dumps of the second run go to CASE.npN.perturb.dbg/ and its log
# is CASE.npN.perturb.log.  A PASS is weak evidence: the perturbation only
# shows a dependence on memory that malloc hands out, and case A on 4
# processes passed with the defect of issue #234 present.  The variable is
# passed with mpirun -x; the mode fails if a launched process does not see it.
#
# Needs shyfem, mpirun and python3 on PATH (an OpenMPI build of shyfem), and
# `make init` done together with
#   (cd GRID && shypre -noopti MM_geo.grd)
# Exit code 0 (LGR GATE: PASS) or 1 (LGR GATE: FAIL).
#------------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)" || exit 1
cd "$HERE" || exit 1
rc=0
fail() { echo "LGR GATE FAIL: $*"; rc=1; }
usage() {
  echo "usage: $0 CASE NP MODE [tool args ...]   (CASE: mm_lgr_a|b|c|e|mm_lgr, MODE: flux|part|pos|ids|perturb)"
  exit 2
}

[ $# -ge 3 ] || usage
CASE="$1"; NP="$2"; MODE="$3"; shift 3
case "$CASE" in
  a|b|c|e) CASE="mm_lgr_$CASE" ;;
  mm_lgr_a|mm_lgr_b|mm_lgr_c|mm_lgr_e|mm_lgr) ;;
  *) echo "unknown case '$CASE'"; usage ;;
esac
case "$NP" in ''|*[!0-9]*) echo "NP must be a number"; usage ;; esac
[ "$NP" -ge 1 ] || usage
case "$MODE" in flux|part|pos|ids|perturb) ;; *) echo "unknown mode '$MODE'"; usage ;; esac
if [ "$CASE" = mm_lgr_b ]; then TOL=2; else TOL=1e-5; fi

#--- preconditions -------------------------------------------------------
command -v shyfem  > /dev/null 2>&1 || { echo "LGR GATE FAIL: shyfem is not on PATH"; exit 1; }
command -v mpirun  > /dev/null 2>&1 || { echo "LGR GATE FAIL: mpirun is not on PATH"; exit 1; }
command -v python3 > /dev/null 2>&1 || { echo "LGR GATE FAIL: python3 is not on PATH"; exit 1; }
for b in GRID/MM_geo.bas GRID/MM_coarse.bas; do
  if [ ! -f "$HERE/$b" ]; then
    echo "LGR GATE FAIL: $b is missing: run 'make init' and '(cd GRID && shypre -noopti MM_geo.grd)' in $HERE"
    exit 1
  fi
done
[ -f "$HERE/$CASE.str" ] || { echo "LGR GATE FAIL: $CASE.str not found in $HERE"; exit 1; }

TMPSTR=""
cleanup() {
  local f
  if [ -n "$TMPSTR" ] && [ -f "$TMPSTR" ]; then rm -f "$TMPSTR"; fi
  # debug files of a failed or aborted run (collect_dbg moves those of a good run)
  for f in "$HERE"/lgrdbg.*.txt; do
    [ -e "$f" ] && rm -f "$f"
  done
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

STR="$CASE.str"
DUMP=0
if [ "$MODE" = flux ] || [ "$MODE" = part ] || [ "$MODE" = perturb ]; then
  DUMP=1
  if grep -q '^[[:space:]]*levdbg' "$HERE/$CASE.str"; then
    echo "LGR GATE FAIL: $CASE.str already sets levdbg; refusing to add a second one"
    exit 1
  fi
  if ! grep -q '^\$para[[:space:]]*$' "$HERE/$CASE.str"; then
    echo "LGR GATE FAIL: $CASE.str has no line with only \$para"
    exit 1
  fi
  TMPSTR="$HERE/$CASE.lgrdbg.$$.str"
  awk '{ print } !done && /^\$para[ \t\r]*$/ { print "        levdbg = 3"; done = 1 }' \
      "$HERE/$CASE.str" > "$TMPSTR" || { echo "LGR GATE FAIL: cannot write $TMPSTR"; exit 1; }
  STR="$(basename "$TMPSTR")"
fi

#--- helpers ---------------------------------------------------------------
# remove the model outputs and debug files of earlier runs (explicit names)
clean_outputs() {
  local ext f
  for ext in lgr.shy hydro.shy inf; do
    rm -f "$HERE/$CASE.$ext" "$HERE/$CASE.serial.$ext"
  done
  if [ "$DUMP" = 1 ]; then
    for f in "$HERE"/lgrdbg.*.txt; do
      [ -e "$f" ] && rm -f "$f"
    done
  fi
}

# before the MPI run: only the model's own outputs (the CASE.serial.* files stay)
clean_outputs_mpi() {
  local ext f
  for ext in lgr.shy hydro.shy inf; do rm -f "$HERE/$CASE.$ext"; done
  if [ "$DUMP" = 1 ]; then
    for f in "$HERE"/lgrdbg.*.txt; do
      [ -e "$f" ] && rm -f "$f"
    done
  fi
}

# keep the run's debug files in a fresh folder of its own
collect_dbg() {
  local dir="$HERE/$1" f n=0
  [ "$DUMP" = 1 ] || return 0
  if [ -d "$dir" ]; then rm -rf "$dir"; fi
  mkdir "$dir" || { fail "cannot create $dir"; return 1; }
  for f in "$HERE"/lgrdbg.*.txt; do
    [ -e "$f" ] || continue
    mv "$f" "$dir/" && n=$((n + 1))
  done
  echo "  $n debug files moved to $1/"
  [ "$n" -gt 0 ] || { fail "run left no lgrdbg.*.txt files"; return 1; }
  return 0
}

summary() { python3 "$HERE/lgr_compare.py" "$1" --summary 2>&1 | sed 's/^/    /'; }

#--- perturb mode: two MPI runs, plain and with MALLOC_PERTURB_=85 -------------
if [ "$MODE" = perturb ]; then
  nlost() { grep -c 'loosing particle adv' "$1"; }
  PERTURB_VALUE=85
  # value of MALLOC_PERTURB_ a process launched by mpirun sees, in brackets;
  # stderr is kept out of the value; $1 = plain | perturbed
  probe() {
    if [ "$1" = plain ]; then
      env -u MALLOC_PERTURB_ nice -n 19 mpirun --oversubscribe -np 1 sh -c 'echo "[${MALLOC_PERTURB_-}]"' 2> /dev/null
    else
      MALLOC_PERTURB_=$PERTURB_VALUE nice -n 19 mpirun --oversubscribe -np 1 -x MALLOC_PERTURB_ sh -c 'echo "[${MALLOC_PERTURB_-}]"' 2> /dev/null
    fi
  }
  echo "=== 1. $CASE on $NP processes, plain"
  seen="$(probe plain)"; probe_rc=$?
  echo "  MALLOC_PERTURB_ seen by a launched process (plain run): $seen"
  if [ "$probe_rc" != 0 ] || [ "$seen" != "[]" ]; then
    fail "the plain run would not be unperturbed (probe exit code $probe_rc, seen '$seen', expected '[]')"
    echo "LGR GATE: FAIL"; exit 1
  fi
  clean_outputs_mpi
  env -u MALLOC_PERTURB_ nice -n 19 mpirun --oversubscribe -np "$NP" shyfem "$STR" > "$HERE/$CASE.np$NP.log" 2>&1
  mpi_rc=$?
  if [ "$mpi_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.np$NP.log"; then
    tail -5 "$HERE/$CASE.np$NP.log"
    fail "$CASE did not end on $NP processes (exit code $mpi_rc)"
    echo "LGR GATE: FAIL"; exit 1
  fi
  collect_dbg "$CASE.np$NP.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
  echo "  plain run ended"

  echo "=== 2. $CASE on $NP processes, MALLOC_PERTURB_=85"
  seen="$(probe perturbed)"; probe_rc=$?
  echo "  MALLOC_PERTURB_ seen by a launched process (perturbed run): $seen"
  if [ "$probe_rc" != 0 ] || [ "$seen" != "[$PERTURB_VALUE]" ]; then
    fail "MALLOC_PERTURB_ does not reach the processes started by mpirun (probe exit code $probe_rc, seen '$seen', expected '[$PERTURB_VALUE]')"
    echo "LGR GATE: FAIL"; exit 1
  fi
  clean_outputs_mpi
  MALLOC_PERTURB_=$PERTURB_VALUE nice -n 19 mpirun --oversubscribe -np "$NP" -x MALLOC_PERTURB_ shyfem "$STR" \
      > "$HERE/$CASE.np$NP.perturb.log" 2>&1
  mpi_rc=$?
  if [ "$mpi_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.np$NP.perturb.log"; then
    tail -5 "$HERE/$CASE.np$NP.perturb.log"
    fail "$CASE did not end on $NP processes with MALLOC_PERTURB_ (exit code $mpi_rc)"
    echo "LGR GATE: FAIL"; exit 1
  fi
  collect_dbg "$CASE.np$NP.perturb.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
  echo "  perturbed run ended"

  echo "=== 3. compare the dump files byte for byte"
  D1="$HERE/$CASE.np$NP.dbg"; D2="$HERE/$CASE.np$NP.perturb.dbg"
  nfiles=0; ndiff=0
  for f in "$D1"/lgrdbg.*.txt; do
    [ -e "$f" ] || continue
    nfiles=$((nfiles + 1)); b="$(basename "$f")"
    if [ ! -f "$D2/$b" ]; then echo "  missing in the perturbed run: $b"; ndiff=$((ndiff + 1))
    elif ! cmp -s "$f" "$D2/$b"; then echo "  differs: $b"; ndiff=$((ndiff + 1)); fi
  done
  for f in "$D2"/lgrdbg.*.txt; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"
    if [ ! -f "$D1/$b" ]; then echo "  missing in the plain run: $b"; ndiff=$((ndiff + 1)); fi
  done
  echo "  $nfiles dump files compared, $ndiff differing or missing"
  echo "  'loosing particle adv' lines: plain $(nlost "$HERE/$CASE.np$NP.log"), perturbed $(nlost "$HERE/$CASE.np$NP.perturb.log")"
  [ "$nfiles" -gt 0 ] || fail "no dump file exists"
  [ "$ndiff" = 0 ] || fail "the dump files of the plain and the perturbed run differ"
  if [ "$rc" = 0 ]; then echo "LGR GATE: PASS"; else echo "LGR GATE: FAIL"; fi
  exit "$rc"
fi

#--- 1. serial run -----------------------------------------------------------
echo "=== 1. $CASE serial (mode $MODE)"
clean_outputs
nice -n 19 shyfem "$STR" > "$HERE/$CASE.serial.log" 2>&1
if ! grep -q "simulation end" "$HERE/$CASE.serial.log"; then
  tail -5 "$HERE/$CASE.serial.log"
  echo "LGR GATE: FAIL"; exit 1
fi
for ext in lgr.shy hydro.shy inf; do
  if [ -f "$HERE/$CASE.$ext" ]; then mv -f "$HERE/$CASE.$ext" "$HERE/$CASE.serial.$ext"
  elif [ "$ext" = lgr.shy ] && { [ "$MODE" = pos ] || [ "$MODE" = ids ]; }; then
    fail "serial run wrote no $CASE.lgr.shy"; echo "LGR GATE: FAIL"; exit 1
  else echo "  note: serial run wrote no $CASE.$ext"; fi
done
collect_dbg "$CASE.serial.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
echo "  serial run ended"

#--- 2. MPI run ------------------------------------------------------------------
echo "=== 2. $CASE on $NP processes"
clean_outputs_mpi
nice -n 19 mpirun --oversubscribe -np "$NP" shyfem "$STR" > "$HERE/$CASE.np$NP.log" 2>&1
mpi_rc=$?
if [ "$mpi_rc" != 0 ] || ! grep -q "simulation end" "$HERE/$CASE.np$NP.log"; then
  tail -5 "$HERE/$CASE.np$NP.log"
  fail "$CASE did not end on $NP processes (exit code $mpi_rc)"
  echo "LGR GATE: FAIL"; exit 1
fi
collect_dbg "$CASE.np$NP.dbg" || { echo "LGR GATE: FAIL"; exit 1; }
echo "  MPI run ended"

#--- 3. comparison ---------------------------------------------------------------
echo "=== 3. compare ($MODE)"
case "$MODE" in
  flux)
    python3 "$HERE/lgr_dbg_compare.py" flux "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" "$@"
    crc=$?
    ;;
  part)
    python3 "$HERE/lgr_dbg_compare.py" part "$HERE/$CASE.serial.dbg" "$HERE/$CASE.np$NP.dbg" \
        --tol "$TOL" --by nearest "$@"
    crc=$?
    ;;
  pos|ids)
    A="$HERE/$CASE.serial.lgr.shy"; B="$HERE/$CASE.lgr.shy"
    if [ ! -f "$A" ] || [ ! -f "$B" ]; then
      echo "  missing particle file: serial $([ -f "$A" ] && echo yes || echo NO), MPI $([ -f "$B" ] && echo yes || echo NO)"
      crc=2
    else
      echo "  serial file:"; summary "$A"
      echo "  MPI file:";    summary "$B"
      if [ "$MODE" = pos ]; then
        python3 "$HERE/lgr_compare.py" "$A" "$B" --mode pos --tol "$TOL" "$@"
      else
        python3 "$HERE/lgr_compare.py" "$A" "$B" --mode ids "$@"
      fi
      crc=$?
    fi
    ;;
esac
case "$crc" in
  0) echo "  comparison: identical within the limits" ;;
  1) fail "$MODE comparison found differences (tool exit code 1)" ;;
  *) fail "$MODE comparison could not be made (tool exit code $crc: unreadable or incomplete input, for example an MPI particle file without output times)" ;;
esac

if [ "$rc" = 0 ]; then echo "LGR GATE: PASS"; else echo "LGR GATE: FAIL"; fi
exit "$rc"
